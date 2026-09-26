"""Inject a partition or primary stop between successive writes in one MW trial.

The fault target is the current primary at the start of each episode. A C2/w:1
write may be acknowledged by the isolated member and later lost. A C4/majority
write that times out was not acknowledged as majority-committed; its effect may
still appear locally or after recovery, which is logged separately from acked loss.
"""
import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pymongo.read_preferences import Primary

from common import get_collection, get_normal_client, new_trial_id
from docker_utils import CONTAINERS, docker_stop
from experiment_lock import experiment_lock
from fault_partition import partition
from fault_recover import recover
from logging_utils import JsonlLogger, timed_op, write_manifest
from run_fault_episodes import wait_for_healthy_cluster
from workload_common import classify_error, find_one_bounded

PROPERTY = "MW"


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=["C1", "C2", "C3", "C4"], required=True)
    parser.add_argument("--trials", type=int, default=3,
                        help="number of independent inject/recover episodes")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-id", required=True,
                        help="unique ID shared by the selected comparison cells")
    parser.add_argument("--causal", choices=["on", "off"], default="on")
    parser.add_argument("--fault-kind", choices=["partition", "primary_down"], default="partition")
    parser.add_argument("--election-wait-s", type=int, default=15)
    parser.add_argument("--settle-ms", type=int, default=15000)
    parser.add_argument("--read-timeout-ms", type=int, default=10000)
    parser.add_argument("--recovery-timeout-seconds", type=int, default=180)
    return parser


def inject_fault(kind, fault_node, logger, trial_num):
    started_ns = time.perf_counter_ns()
    if kind == "partition":
        partition(fault_node)
        peers = [node for node in CONTAINERS if node != fault_node]
        detail = f"iptables DROP {fault_node}<->{peers}; node processes remain running"
    else:
        docker_stop(fault_node)
        detail = f"docker stop {fault_node}; process is stopped"
    logger.log(
        trial=trial_num,
        operation="fault_applied",
        success=True,
        fault_kind=kind,
        fault_point="after_v1",
        target_node=fault_node,
        notes=detail,
        invoke_monotonic_ns=started_ns,
        response_monotonic_ns=time.perf_counter_ns(),
        topology_state=f"mid_{kind}",
    )


def log_write(logger, trial_num, session_id, operation, key, requested_value, config, target, error,
              invoke_ns, response_ns, latency_ms, topology_state):
    acknowledged = error is None
    logger.log(
        trial=trial_num,
        client_id="client-A",
        session_id=session_id,
        operation=operation,
        key=key,
        requested_version=requested_value,
        returned_version=requested_value if acknowledged else None,
        target_node=target,
        read_concern=config,
        write_concern=config,
        invoke_monotonic_ns=invoke_ns,
        response_monotonic_ns=response_ns,
        latency_ms=latency_ms,
        success=acknowledged,
        acknowledged=acknowledged,
        error_type=type(error).__name__ if error else None,
        topology_state=topology_state,
    )


def log_check(logger, trial_num, key, args, status, violation, final_value, reason):
    logger.log(
        trial=trial_num,
        client_id="client-A",
        operation="mw_fault_check",
        key=key,
        returned_version=final_value,
        success=status not in ("operation_error", "timeout"),
        topology_state=f"mid_{args.fault_kind}",
        fault_kind=args.fault_kind,
        mw_violation=violation,
        trial_status=status,
        reason=reason,
    )


def run_fault_trial(client, trial_num, logger, experiment_id, args, fault_node):
    key = new_trial_id(experiment_id)
    collection = get_collection(client, args.config)
    session = client.start_session(causal_consistency=args.causal == "on") if args.causal == "on" else None
    session_id = session.session_id["id"].hex() if session else None
    v2_attempted = False
    v3_attempted = False
    v2_acked = False
    v3_acked = False
    final_value = None
    final_read_error = None

    def increment():
        return collection.update_one({"_id": key}, {"$inc": {"n": 1}}, session=session)

    try:
        _, error, invoke_ns, response_ns, latency_ms = timed_op(
            lambda: collection.insert_one({"_id": key, "n": 0}, session=session)
        )
        log_write(logger, trial_num, session_id, "write_init", key, 0, args.config,
                  fault_node, error, invoke_ns, response_ns, latency_ms, "normal")
        if error is not None:
            log_check(logger, trial_num, key, args, classify_error(error), False, None,
                      "baseline insert failed")
            return

        _, error, invoke_ns, response_ns, latency_ms = timed_op(increment)
        log_write(logger, trial_num, session_id, "write_v1_prefault", key, 1, args.config,
                  fault_node, error, invoke_ns, response_ns, latency_ms, "normal")
        if error is not None:
            log_check(logger, trial_num, key, args, classify_error(error), False, None,
                      "pre-fault v1 increment failed")
            return

        v2_error = None
        v3_error = None
        try:
            inject_fault(args.fault_kind, fault_node, logger, trial_num)

            v2_attempted = True
            _, v2_error, invoke_ns, response_ns, latency_ms = timed_op(increment)
            v2_acked = v2_error is None
            log_write(logger, trial_num, session_id, "write_v2_faulted", key, 2, args.config,
                      fault_node, v2_error, invoke_ns, response_ns, latency_ms,
                      f"mid_{args.fault_kind}")

            time.sleep(args.election_wait_s)
            logger.log(
                trial=trial_num,
                operation="election_wait",
                success=True,
                target_node=fault_node,
                topology_state=f"mid_{args.fault_kind}",
                notes=f"waited {args.election_wait_s}s after fault",
                response_monotonic_ns=time.perf_counter_ns(),
            )

            v3_attempted = True
            _, v3_error, invoke_ns, response_ns, latency_ms = timed_op(increment)
            v3_acked = v3_error is None
            log_write(logger, trial_num, session_id, "write_v3_faulted", key, 3, args.config,
                      "replica_set_primary", v3_error, invoke_ns, response_ns, latency_ms,
                      f"mid_{args.fault_kind}")
        finally:
            recover()
            recovered_primary = wait_for_healthy_cluster(args.recovery_timeout_seconds)
            time.sleep(args.settle_ms / 1000)
            logger.log(
                trial=trial_num,
                operation="fault_recovered",
                success=True,
                target_node=recovered_primary,
                topology_state="normal",
                notes=f"all members healthy; settled {args.settle_ms}ms",
                response_monotonic_ns=time.perf_counter_ns(),
            )

        read_client = get_normal_client()
        try:
            read_collection = get_collection(read_client, args.config).with_options(
                read_preference=Primary()
            )
            document, final_read_error, invoke_ns, response_ns, latency_ms = timed_op(
                lambda: find_one_bounded(read_collection, key, None, args.read_timeout_ms)
            )
            final_value = document["n"] if document else None
            logger.log(
                trial=trial_num,
                client_id="client-A",
                operation="final_read",
                key=key,
                returned_version=final_value,
                target_node="primary",
                read_concern=args.config,
                read_preference="primary",
                invoke_monotonic_ns=invoke_ns,
                response_monotonic_ns=response_ns,
                latency_ms=latency_ms,
                success=final_read_error is None,
                error_type=type(final_read_error).__name__ if final_read_error else None,
                topology_state="normal",
            )
        finally:
            read_client.close()

        acknowledged_increments = 1 + int(v2_acked) + int(v3_acked)
        attempted_increments = 1 + int(v2_attempted) + int(v3_attempted)
        if final_read_error is not None:
            status, violation, reason = classify_error(final_read_error), False, "final read failed"
        elif final_value is None:
            status, violation, reason = "read_miss", False, "final read returned no document"
        elif final_value < acknowledged_increments:
            status, violation = "acked_write_lost", True
            reason = (f"final n={final_value} is below {acknowledged_increments} acknowledged increments; "
                      "at least one acknowledged effect was lost")
        elif final_value > attempted_increments:
            status, violation = "indeterminate", False
            reason = f"final n={final_value} exceeds {attempted_increments} attempted increments"
        elif final_value > acknowledged_increments:
            status, violation = "unacknowledged_effect_present", False
            reason = (f"final n={final_value} exceeds {acknowledged_increments} acknowledged increments "
                      f"but is within {attempted_increments} attempts; a timed-out write effect is present")
        elif v2_acked and v3_acked:
            status, violation = "in_order", False
            reason = f"final n={final_value} equals all acknowledged increments"
        elif v3_error is not None:
            status, violation = "interrupted", False
            reason = f"v3 failed ({type(v3_error).__name__}); final n={final_value}"
        else:
            status, violation = "indeterminate", False
            reason = "final counter cannot identify which effects from unacknowledged writes survived"
        log_check(logger, trial_num, key, args, status, violation, final_value, reason)
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
        read_timeout_ms=args.read_timeout_ms,
        primary_selection="current_primary_at_episode_start",
        latency_clock="perf_counter_ns",
    )
    with experiment_lock():
        logger = JsonlLogger(experiment_id, run_id=args.run_id)
        write_manifest(experiment_id, status="running", **manifest_fields)
        client = get_normal_client()
        try:
            for trial_num in range(1, args.trials + 1):
                try:
                    fault_node = wait_for_healthy_cluster(args.recovery_timeout_seconds)
                    run_fault_trial(client, trial_num, logger, experiment_id, args, fault_node)
                finally:
                    recover()
            logger.finalize()
            write_manifest(experiment_id, status="complete", **manifest_fields)
        finally:
            client.close()
    print(f"done: {experiment_id} ({args.trials} trials) -> results/raw/{experiment_id}.jsonl")


if __name__ == "__main__":
    main()
