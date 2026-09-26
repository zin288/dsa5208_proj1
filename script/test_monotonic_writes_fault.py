"""MW mid-sequence fault workload: a fault lands BETWEEN the client's writes.

The main-matrix MW cells apply one fault around a whole cell, so the write sequence
is never interrupted. This workload injects the fault after the first increment:

    insert {n:0}; $inc -> 1 (acked pre-fault); INJECT FAULT;
    $inc (v2); wait for election; $inc (v3); recover; settle; read final n.

Because $inc is compositional, the final counter exposes whether every acknowledged
increment's effect survived. With the default partition of mongo1 (the old primary,
still primary in the client's view for a few seconds): a w:1 v2 write is acknowledged
by the isolated member alone; after the election, v3 is applied by the new primary
from its own state (n=1, since v2 never replicated); on rejoin the isolated member
rolls v2 back. The client saw acknowledgements for v1..v3 but the final state holds
n=2 - a later write's effect survived while an earlier acknowledged write's effect
was lost, an observable monotonic-writes ordering break caused by w:1 rollback.
With majority write concern (C1/C4) the v2/v3 writes instead time out while the
delayed voting member cannot acknowledge - the availability price of the stronger
concern, not a violation.

trial_status on the final mw_fault_check record:
- in_order: final n equals the number of acknowledged increments.
- acked_write_lost: final n is smaller than the number of acknowledged increments
  (mw_violation=True; at least one acknowledged write's effect vanished).
- interrupted: the v3 write failed (the sequence never resumed after the fault).
- read_miss / indeterminate: the final read returned nothing / an unexplainable value.
- operation_error / timeout: the baseline write or the final read failed.

Assumes mongo1 is primary when the trial starts (same assumption as scenarios.py);
run cluster_status.py first. Each trial is an independent inject/recover episode and
the cluster must be healthy before the next trial starts.
"""
import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pymongo.read_preferences import Primary

from common import get_collection, get_normal_client, new_trial_id
from docker_utils import docker_stop
from experiment_lock import experiment_lock
from fault_partition import partition
from fault_recover import recover
from logging_utils import JsonlLogger, timed_op, write_manifest
from run_fault_episodes import wait_for_healthy_cluster
from workload_common import classify_error

PROPERTY = "MW"


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=["C1", "C2", "C3", "C4"], required=True)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--causal", choices=["on", "off"], default="on")
    parser.add_argument("--fault-kind", choices=["partition", "primary_down"], default="partition")
    parser.add_argument("--election-wait-s", type=int, default=15,
                        help="seconds to wait after the fault for step-down/election before v3")
    parser.add_argument("--settle-ms", type=int, default=15000,
                        help="post-recovery pause so rollback and the delayed member can catch up before the final read")
    parser.add_argument("--recovery-timeout-seconds", type=int, default=180)
    return parser


def inject_fault(kind, logger, trial_num):
    started_ns = time.perf_counter_ns()
    if kind == "partition":
        partition("mongo1")
        detail = "iptables DROP mongo1<->mongo2, mongo1<->mongo3; processes running"
    else:
        docker_stop("mongo1")
        detail = "docker stop mongo1 (process not running)"
    logger.log(trial=trial_num, operation="fault_applied", success=True,
               fault_kind=kind, fault_point="after_v1", notes=detail,
               invoke_monotonic_ns=started_ns, response_monotonic_ns=time.perf_counter_ns(),
               topology_state=f"mid_{kind}")


def log_check(logger, trial_num, key, args, status, violation, final_n, reason):
    logger.log(trial=trial_num, client_id="client-A", operation="mw_fault_check", key=key,
               returned_version=final_n, success=status not in ("operation_error", "timeout"),
               topology_state=f"mid_{args.fault_kind}",
               mw_violation=violation, trial_status=status, reason=reason)


def log_write(logger, trial_num, session_id, op_name, key, args, requested, error, inv, resp, latency, state):
    acked = error is None
    logger.log(trial=trial_num, client_id="client-A", session_id=session_id,
               operation=op_name, key=key, requested_version=requested,
               returned_version=requested if acked else None, target_node="primary",
               read_concern=args.config, write_concern=args.config,
               invoke_monotonic_ns=inv, response_monotonic_ns=resp, latency_ms=latency,
               success=acked, error_type=type(error).__name__ if error else None,
               topology_state=state)


def run_fault_trial(client, trial_num, logger, experiment_id, args):
    """One inject/recover episode wrapped around the middle of the write sequence."""
    key = new_trial_id(experiment_id)
    col = get_collection(client, args.config)
    session = client.start_session(causal_consistency=args.causal == "on") if args.causal == "on" else None
    session_id = session.session_id["id"].hex if session else None

    def inc():
        return col.update_one({"_id": key}, {"$inc": {"n": 1}}, session=session)

    try:
        _, error, inv, resp, latency = timed_op(lambda: col.insert_one({"_id": key, "n": 0}, session=session))
        log_write(logger, trial_num, session_id, "write_init", key, args, 0, error, inv, resp, latency, "normal")
        if error is not None:
            log_check(logger, trial_num, key, args, classify_error(error), False, None, "baseline insert failed")
            return

        result, error, inv, resp, latency = timed_op(inc)
        log_write(logger, trial_num, session_id, "write_v1_prefault", key, args, 1, error, inv, resp, latency, "normal")
        if error is not None:
            log_check(logger, trial_num, key, args, classify_error(error), False, None, "pre-fault v1 write failed")
            return

        v2_acked = v3_acked = False
        try:
            inject_fault(args.fault_kind, logger, trial_num)

            result, error, inv, resp, latency = timed_op(inc)
            v2_acked = error is None
            log_write(logger, trial_num, session_id, "write_v2_faulted", key, args, 2, error, inv, resp, latency,
                      f"mid_{args.fault_kind}")

            time.sleep(args.election_wait_s)
            logger.log(trial=trial_num, operation="election_wait", success=True,
                       topology_state=f"mid_{args.fault_kind}",
                       notes=f"waited {args.election_wait_s}s for step-down/election",
                       response_monotonic_ns=time.perf_counter_ns())

            result, error, inv, resp, latency = timed_op(inc)
            v3_acked = error is None
            log_write(logger, trial_num, session_id, "write_v3_faulted", key, args, 3, error, inv, resp, latency,
                      f"mid_{args.fault_kind}")
        finally:
            recover()
            time.sleep(args.settle_ms / 1000)
            logger.log(trial=trial_num, operation="fault_recovered", success=True,
                       topology_state="recovering", notes=f"recovered; settled {args.settle_ms}ms",
                       response_monotonic_ns=time.perf_counter_ns())

        read_client = get_normal_client()
        try:
            read_col = get_collection(read_client, args.config).with_options(read_preference=Primary())
            doc, error, inv, resp, latency = timed_op(lambda: read_col.find_one({"_id": key}))
            final_n = doc["n"] if doc else None
            logger.log(trial=trial_num, client_id="client-A", session_id=None,
                       session_transmitted=False, operation="final_read", key=key,
                       requested_version=None, returned_version=final_n,
                       target_node="primary", read_concern=args.config,
                       read_preference="primary",
                       invoke_monotonic_ns=inv, response_monotonic_ns=resp, latency_ms=latency,
                       success=error is None, error_type=type(error).__name__ if error else None,
                       topology_state="normal")
        finally:
            read_client.close()

        acked = 1 + int(v2_acked) + int(v3_acked)
        if error is not None:
            status, violation, reason = classify_error(error), False, "final read failed"
        elif final_n is None:
            status, violation, reason = "read_miss", False, "final read returned no document"
        elif final_n == acked:
            status, violation, reason = "in_order", False, f"final n={final_n} equals acked increments ({acked})"
        elif final_n > acked:
            status, violation, reason = "indeterminate", False, f"final n={final_n} exceeds acked increments ({acked})"
        elif not v3_acked:
            status, violation, reason = "interrupted", False, f"v3 failed (v2 acked={v2_acked}); final n={final_n}"
        else:
            status, violation = "acked_write_lost", True
            reason = (f"acked={acked} but final n={final_n}: an acknowledged increment's "
                      f"effect was lost (v2 acked={v2_acked})")
        log_check(logger, trial_num, key, args, status, violation, final_n, reason)
    finally:
        if session is not None:
            session.end_session()


def main():
    args = build_arg_parser().parse_args()
    if args.trials < 1:
        raise SystemExit("--trials must be positive")
    random.seed(args.seed)
    run_component = f"-{args.run_id}" if args.run_id else ""
    experiment_id = f"{args.config}-mw_fault_{args.fault_kind}{run_component}-seed{args.seed}"
    manifest_fields = dict(
        config=args.config,
        scenario=f"mid_{args.fault_kind}",
        property=PROPERTY,
        trials=args.trials,
        seed=args.seed,
        run_id=args.run_id,
        causal=args.causal,
        fault_kind=args.fault_kind,
        fault_point="after_v1",
        election_wait_s=args.election_wait_s,
        settle_ms=args.settle_ms,
        latency_clock="perf_counter_ns",
    )
    with experiment_lock():
        logger = JsonlLogger(experiment_id, run_id=args.run_id)
        write_manifest(experiment_id, status="running", **manifest_fields)
        client = get_normal_client()
        try:
            for trial_num in range(1, args.trials + 1):
                try:
                    wait_for_healthy_cluster(args.recovery_timeout_seconds)
                    run_fault_trial(client, trial_num, logger, experiment_id, args)
                finally:
                    recover()
            logger.finalize()
            write_manifest(experiment_id, status="complete", **manifest_fields)
        finally:
            client.close()
    print(f"done: {experiment_id} ({args.trials} trials) -> results/raw/{experiment_id}.jsonl")


if __name__ == "__main__":
    main()
