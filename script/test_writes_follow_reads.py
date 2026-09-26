"""WFR workload: read x=v_k from a specified node, derive v_k+1, then write it via primary.

Trial classification (trial_status on the final wfr_check record):
- valid_observation: the read returned a baseline version and the derived CAS write
  matched it - the writes-follow-reads sequence formed and held. A single-client
  sequence cannot produce positive evidence that the write landed on a state older
  than the read basis, so wfr_violation stays False for these trials.
- read_miss: the read succeeded but returned no document. The WFR sequence never
  formed (there is no read basis to derive from), so this is NOT a WFR violation -
  it is reported separately as a staleness observation of the read path.
- precondition_unmatched: the read succeeded but the derived CAS write found no
  matching version. With a single client this is indeterminate (e.g. a concurrent
  writer or a stale read basis), not proof of a WFR violation.
- operation_error / timeout: a write or read failed; the trial judges nothing.

--settle-ms waits between the baseline insert and the read so that a delayed read
target (secondaryDelaySecs=10) can catch up to the baseline and actually return a
version; use e.g. --read-target delayed --settle-ms 11000 for that path.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from workload_common import build_arg_parser, classify_error, find_one_bounded, get_read_collection, run_workload

PROPERTY = "WFR"


def trial(client, delayed_client, session, trial_num, logger, experiment_id, args):
    key = new_trial_id(experiment_id)
    col = get_collection(client, args.config)
    session_id = session.session_id["id"].hex() if session else None

    def do_insert():
        return col.insert_one({"_id": key, "version": 0}, session=session)

    _, error, inv, resp, latency = timed_op(do_insert)
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="write_init", key=key, requested_version=0,
        returned_version=0 if error is None else None,
        target_node="primary", read_concern=args.config, write_concern=args.config,
        invoke_monotonic_ns=inv, response_monotonic_ns=resp, latency_ms=latency,
        success=error is None, error_type=type(error).__name__ if error else None,
        topology_state=args.scenario,
    )
    if error is not None:
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="wfr_check", key=key, success=False,
            error_type=type(error).__name__, topology_state=args.scenario,
            wfr_violation=False, trial_status=classify_error(error),
        )
        return

    if args.settle_ms:
        time.sleep(args.settle_ms / 1000)

    read_col, session_supported = get_read_collection(client, delayed_client, args.config, args.read_target)

    def do_read():
        return find_one_bounded(
            read_col, key, session if session_supported else None, args.read_timeout_ms
        )

    doc, error, inv, resp, latency = timed_op(do_read)
    read_version = doc["version"] if doc else None
    logger.log(
        trial=trial_num, client_id="client-A",
        session_id=session_id if session_supported else None,
        session_transmitted=session_supported,
        operation="read", key=key, requested_version=0, returned_version=read_version,
        target_node=args.read_target, read_concern=args.config, write_concern=args.config,
        read_preference=args.read_target, invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
    )

    if error is not None:
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="wfr_check", key=key, success=False,
            error_type=type(error).__name__, topology_state=args.scenario,
            wfr_violation=False, trial_status=classify_error(error),
        )
        return
    if read_version is None:
        # No visible baseline: the WFR sequence never formed. Not a violation.
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="wfr_check", key=key, success=False, topology_state=args.scenario,
            wfr_violation=False, trial_status="read_miss", error_type="read_miss",
        )
        return

    derived_version = read_version + 1

    def do_write():
        return col.update_one({"_id": key, "version": read_version},
                              {"$set": {"version": derived_version}}, session=session)

    result, error, inv, resp, latency = timed_op(do_write)
    matched = result.matched_count if result else 0
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="write_derived", key=key, requested_version=read_version,
        returned_version=derived_version if matched else None,
        target_node="primary", read_concern=args.config, write_concern=args.config,
        invoke_monotonic_ns=inv, response_monotonic_ns=resp, latency_ms=latency,
        success=error is None, error_type=type(error).__name__ if error else None,
        topology_state=args.scenario,
    )

    if error is not None:
        status, violation = classify_error(error), False
    elif matched == 0:
        status, violation = "precondition_unmatched", False
    else:
        status, violation = "valid_observation", False
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="wfr_check", key=key, requested_version=read_version,
        returned_version=derived_version if matched else None,
        success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
        wfr_violation=violation, trial_status=status,
    )


def main():
    parser = build_arg_parser("Writes-follow-reads workload", default_read_target="secondary")
    parser.add_argument("--settle-ms", type=int, default=0,
                        help="pause between the baseline insert and the read, so a lagging read target can return a version")
    args = parser.parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
