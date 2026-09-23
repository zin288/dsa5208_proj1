"""RYW workload: client writes x=1, then reads x back from a (possibly stale) target node."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from workload_common import build_arg_parser, get_read_collection, run_workload

PROPERTY = "RYW"


def trial(client, delayed_client, session, trial_num, logger, experiment_id, args):
    key = new_trial_id(experiment_id)
    write_col = get_collection(client, args.config)
    read_col, session_supported = get_read_collection(client, delayed_client, args.config, args.read_target)

    def do_write():
        return write_col.insert_one({"_id": key, "version": 1}, session=session)

    _, error, inv, resp, latency = timed_op(do_write)
    logger.log(
        trial=trial_num, client_id="client-A",
        session_id=session.session_id["id"].hex() if session else None,
        operation="write", key=key, requested_version=1,
        returned_version=1 if error is None else None,
        target_node="primary", read_concern=args.config, write_concern=args.config,
        read_preference="primary", invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
    )
    if error is not None:
        return

    def do_read():
        return read_col.find_one({"_id": key}, session=session if session_supported else None)

    doc, error, inv, resp, latency = timed_op(do_read)
    returned_version = doc["version"] if doc else None
    ryw_violation = error is None and (returned_version is None or returned_version < 1)
    logger.log(
        trial=trial_num, client_id="client-A",
        session_id=(session.session_id["id"].hex() if session and session_supported else None),
        operation="read", key=key, requested_version=1, returned_version=returned_version,
        target_node=args.read_target, read_concern=args.config, write_concern=args.config,
        read_preference=args.read_target, invoke_monotonic_ns=inv, response_monotonic_ns=resp,
        latency_ms=latency, success=error is None,
        error_type=type(error).__name__ if error else None, topology_state=args.scenario,
        ryw_violation=ryw_violation,
    )


def main():
    parser = build_arg_parser("Read-your-writes workload", default_read_target="delayed")
    args = parser.parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
