"""MW workload: client issues x=1 -> x=2 -> x=3 in order; each write is CAS'd on the prior version.

A CAS write (`update_one({_id, version: prev}, {$set: {version: next}})`) failing to match is
evidence the previous write's effect was not visible/durable when the next write was attempted -
the observable proxy for a monotonic-writes violation, since we cannot inspect internal ordering.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from workload_common import build_arg_parser, run_workload

PROPERTY = "MW"


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

    for next_version in (1, 2, 3):
        prev_version = next_version - 1

        def do_cas(nv=next_version, pv=prev_version):
            return col.update_one({"_id": key, "version": pv}, {"$set": {"version": nv}}, session=session)

        result, error, inv, resp, latency = timed_op(do_cas)
        matched = result.matched_count if result else 0
        mw_violation = error is None and matched == 0
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation=f"write_v{next_version}", key=key, requested_version=prev_version,
            returned_version=next_version if matched else None,
            target_node="primary", read_concern=args.config, write_concern=args.config,
            invoke_monotonic_ns=inv, response_monotonic_ns=resp, latency_ms=latency,
            success=error is None, error_type=type(error).__name__ if error else None,
            topology_state=args.scenario, mw_violation=mw_violation,
        )
        if error is not None:
            break


def main():
    parser = build_arg_parser("Monotonic-writes workload")
    args = parser.parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
