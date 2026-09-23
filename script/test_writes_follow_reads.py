"""WFR workload: read x=v_k from a specified node, derive v_k+1, then write it via primary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from workload_common import build_arg_parser, get_read_collection, run_workload

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
        return

    read_col, session_supported = get_read_collection(client, delayed_client, args.config, args.read_target)

    def do_read():
        return read_col.find_one({"_id": key}, session=session if session_supported else None)

    doc, error, inv, resp, latency = timed_op(do_read)
    read_version = doc["version"] if doc else None
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="read", key=key, requested_version=0, returned_version=read_version,
        target_node=args.read_target, read_concern=args.config, write_concern=args.config,
        read_preference=args.read_target, invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
    )

    if read_version is None:
        # No visible baseline to build the derived write on - counts as an observable WFR violation.
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="wfr_check", key=key, success=False, topology_state=args.scenario,
            wfr_violation=True, error_type="read_miss",
        )
        return

    derived_version = read_version + 1

    def do_write():
        return col.update_one({"_id": key, "version": read_version},
                               {"$set": {"version": derived_version}}, session=session)

    result, error, inv, resp, latency = timed_op(do_write)
    matched = result.matched_count if result else 0
    wfr_violation = error is None and matched == 0
    logger.log(
        trial=trial_num, client_id="client-A", session_id=session_id,
        operation="write_derived", key=key, requested_version=read_version,
        returned_version=derived_version if matched else None,
        target_node="primary", read_concern=args.config, write_concern=args.config,
        invoke_monotonic_ns=inv, response_monotonic_ns=resp, latency_ms=latency,
        success=error is None, error_type=type(error).__name__ if error else None,
        topology_state=args.scenario, wfr_violation=wfr_violation,
    )


def main():
    parser = build_arg_parser("Writes-follow-reads workload", default_read_target="delayed")
    args = parser.parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
