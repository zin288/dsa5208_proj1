"""MR workload: two comparable versions exist, then read from target 1 and target 2.

Per trial: insert v0 -> optional settle (--settle-ms) -> update to v1 ->
read1 from --first-read-target -> read2 from --second-read-target.

The two versions make a version regression actually observable: read2 returning v0
after read1 returned v1 is a real monotonic-reads violation. (The previous design
wrote only v1, so the second read could never return anything comparable - the old
"0 violations" were vacuous.)

On the delayed target (secondaryDelaySecs=10), v0 is applied at ~t0+10s and v1 at
~t0+settle+10s, so with --settle-ms 11000 a read2 issued right after read1 lands in
the window where the delayed member has v0 but not v1.

Trial classification (trial_status on the final mr_check record):
- valid_observation: both reads returned versions; mr_violation is True only when
  the second returned a strictly smaller version than the first.
- read_miss: either read succeeded but returned no document (comparison impossible;
  recorded as a staleness observation of the miss path, NOT as a violation).
- operation_error / timeout: a write or read failed; the trial judges nothing.

Default targets are secondary/secondary so both reads share the causal session -
this is the path the C1-C4 prediction table actually describes. Delayed targets go
through a direct connection that cannot carry the session; manifests record
causal_session_effective_for_reads accordingly.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from scenarios import SCENARIOS
from workload_common import classify_error, find_one_bounded, get_read_collection, run_workload

PROPERTY = "MR"


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=["C1", "C2", "C3", "C4"], required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--causal", choices=["on", "off"], default="on")
    parser.add_argument("--first-read-target", choices=["primary", "secondary", "delayed"],
                        default="secondary")
    parser.add_argument("--second-read-target", choices=["primary", "secondary", "delayed"],
                        default="secondary")
    parser.add_argument("--read-timeout-ms", type=int, default=10000,
                        help="server-side maximum duration for an individual read")
    parser.add_argument("--settle-ms", type=int, default=0,
                        help="pause between the v0 insert and the v1 update, so a lagging second-read target can hold v0 but not v1")
    parser.add_argument("--read-target", default=None, help=argparse.SUPPRESS)  # for manifest compat
    return parser


def trial(client, delayed_client, session, trial_num, logger, experiment_id, args):
    key = new_trial_id(experiment_id)
    write_col = get_collection(client, args.config)
    session_id = session.session_id["id"].hex() if session else None

    def do_insert():
        return write_col.insert_one({"_id": key, "version": 0}, session=session)

    _, error, inv, resp, latency = timed_op(do_insert)
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="write_baseline", key=key, requested_version=0,
        returned_version=0 if error is None else None,
        target_node="primary", read_concern=args.config, write_concern=args.config,
        read_preference="primary", invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
    )
    if error is not None:
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="mr_check", key=key, success=False,
            error_type=type(error).__name__, topology_state=args.scenario,
            mr_violation=False, trial_status=classify_error(error),
        )
        return

    if args.settle_ms:
        time.sleep(args.settle_ms / 1000)

    def do_update():
        return write_col.update_one({"_id": key}, {"$set": {"version": 1}}, session=session)

    _, error, inv, resp, latency = timed_op(do_update)
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="write", key=key, requested_version=1,
        returned_version=1 if error is None else None,
        target_node="primary", read_concern=args.config, write_concern=args.config,
        read_preference="primary", invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
    )
    if error is not None:
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="mr_check", key=key, success=False,
            error_type=type(error).__name__, topology_state=args.scenario,
            mr_violation=False, trial_status=classify_error(error),
        )
        return

    versions = {}
    for step, target in (("read1", args.first_read_target), ("read2", args.second_read_target)):
        read_col, session_supported = get_read_collection(client, delayed_client, args.config, target)

        def do_read(col=read_col, use_session=session_supported):
            return find_one_bounded(
                col, key, session if use_session else None, args.read_timeout_ms
            )

        doc, error, inv, resp, latency = timed_op(do_read)
        returned_version = doc["version"] if doc else None
        versions[step] = returned_version
        logger.log(
            trial=trial_num, client_id="client-A",
            session_id=session_id if session_supported else None,
            session_transmitted=session_supported,
            operation=step, key=key, requested_version=1, returned_version=returned_version,
            target_node=target, read_concern=args.config, write_concern=args.config,
            read_preference=target, invoke_monotonic_ns=inv, response_monotonic_ns=resp,
            latency_ms=latency, success=error is None,
            error_type=type(error).__name__ if error else None, topology_state=args.scenario,
        )
        if error is not None:
            logger.log(
                trial=trial_num, client_id="client-A", session_id=session_id,
                operation="mr_check", key=key, success=False,
                error_type=type(error).__name__, topology_state=args.scenario,
                mr_violation=False, trial_status=classify_error(error),
            )
            return

    v1, v2 = versions.get("read1"), versions.get("read2")
    if v1 is None or v2 is None:
        status, violation = "read_miss", False
        reason = "read1 missed" if v1 is None else "read2 missed"
    else:
        status = "valid_observation"
        violation = v2 < v1
        reason = f"read1={v1} read2={v2}"
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="mr_check", key=key, requested_version=v1, returned_version=v2,
        success=True, topology_state=args.scenario,
        mr_violation=violation, trial_status=status, reason=reason,
    )


def main():
    args = build_arg_parser().parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
