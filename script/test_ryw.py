"""RYW workload: client writes v0 then v1, then reads the same key from a chosen target.

Trial classification (trial_status on the final ryw_check record):
- valid_observation: the read returned a document. ryw_violation is True only when
  the returned version is older than the acknowledged write (i.e. the baseline v0) -
  a version-regression RYW violation.
- read_miss: the read succeeded but returned no document. On a no-session lagging
  read path this is itself a staleness observation, but it is NOT counted as
  ryw_violation so that staleness/availability and version regressions stay separable.
- operation_error / timeout: a write or read failed; the trial judges nothing.

Timing knobs for observing a non-null stale version on the delayed target
(secondaryDelaySecs=10): with --pre-write-pause-ms P the target applies v0 at
~t0+10s and v1 at ~t0+P+10s, so a read at t0+P+R sees v0 (not v1, not empty) when
10 <= P+R < 10+P... i.e. P+R must be at least 10s and R below 10s, e.g.
--pre-write-pause-ms 11000 --post-write-delay-ms 1000.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from workload_common import build_arg_parser, classify_error, find_one_bounded, get_read_collection, run_workload

PROPERTY = "RYW"


def trial(client, delayed_client, session, trial_num, logger, experiment_id, args):
    key = new_trial_id(experiment_id)
    write_col = get_collection(client, args.config)
    read_col, session_supported = get_read_collection(client, delayed_client, args.config, args.read_target)
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
            operation="ryw_check", key=key, success=False,
            error_type=type(error).__name__, topology_state=args.scenario,
            ryw_violation=False, trial_status=classify_error(error),
        )
        return

    if args.pre_write_pause_ms:
        time.sleep(args.pre_write_pause_ms / 1000)

    def do_write():
        return write_col.update_one({"_id": key}, {"$set": {"version": 1}}, session=session)

    _, error, inv, resp, latency = timed_op(do_write)
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
            operation="ryw_check", key=key, success=False,
            error_type=type(error).__name__, topology_state=args.scenario,
            ryw_violation=False, trial_status=classify_error(error),
        )
        return

    if args.post_write_delay_ms:
        time.sleep(args.post_write_delay_ms / 1000)

    def do_read():
        return find_one_bounded(
            read_col, key, session if session_supported else None, args.read_timeout_ms
        )

    doc, error, inv, resp, latency = timed_op(do_read)
    returned_version = doc["version"] if doc else None
    logger.log(
        trial=trial_num, client_id="client-A",
        session_id=session_id if session_supported else None,
        session_transmitted=session_supported,
        operation="read", key=key, requested_version=1, returned_version=returned_version,
        target_node=args.read_target, read_concern=args.config, write_concern=args.config,
        read_preference=args.read_target, invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
    )

    if error is not None:
        status, violation = classify_error(error), False
    elif returned_version is None:
        status, violation = "read_miss", False
    else:
        status = "valid_observation"
        violation = returned_version < 1
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="ryw_check", key=key, requested_version=1,
        returned_version=returned_version, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
        ryw_violation=violation, trial_status=status,
    )


def main():
    parser = build_arg_parser("Read-your-writes workload", default_read_target="secondary")
    parser.add_argument("--pre-write-pause-ms", type=int, default=0,
                        help="pause between the v0 baseline insert and the tested v1 write")
    parser.add_argument("--post-write-delay-ms", type=int, default=0,
                        help="pause between the tested v1 write and the read")
    args = parser.parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
