"""MR workload: read x from an up-to-date node, then read again from a lagging/isolated node."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_collection, get_normal_client, new_trial_id
from logging_utils import timed_op
from scenarios import SCENARIOS
from workload_common import get_read_collection, run_workload

PROPERTY = "MR"


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=["C1", "C2", "C3", "C4"], required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--causal", choices=["on", "off"], default="on")
    parser.add_argument("--first-read-target", choices=["primary", "secondary", "delayed"],
                         default="secondary")
    parser.add_argument("--second-read-target", choices=["primary", "secondary", "delayed"],
                         default="delayed")
    parser.add_argument("--read-target", default=None, help=argparse.SUPPRESS)  # for manifest compat
    return parser


def trial(client, delayed_client, session, trial_num, logger, experiment_id, args):
    key = new_trial_id(experiment_id)
    write_col = get_collection(client, args.config)
    session_id = session.session_id["id"].hex() if session else None

    def do_write():
        return write_col.insert_one({"_id": key, "version": 1}, session=session)

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
        return

    versions = {}
    for step, target in (("read1", args.first_read_target), ("read2", args.second_read_target)):
        read_col, session_supported = get_read_collection(client, delayed_client, args.config, target)

        def do_read(col=read_col, use_session=session_supported):
            return col.find_one({"_id": key}, session=session if use_session else None)

        doc, error, inv, resp, latency = timed_op(do_read)
        returned_version = doc["version"] if doc else None
        versions[step] = returned_version
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation=step, key=key, requested_version=1, returned_version=returned_version,
            target_node=target, read_concern=args.config, write_concern=args.config,
            read_preference=target, invoke_monotonic_ns=inv, response_monotonic_ns=resp,
            latency_ms=latency, success=error is None,
            error_type=type(error).__name__ if error else None, topology_state=args.scenario,
        )

    v1, v2 = versions.get("read1"), versions.get("read2")
    if v1 is not None and v2 is not None and v2 < v1:
        logger.log(
            trial=trial_num, client_id="client-A", session_id=session_id,
            operation="mr_check", key=key, requested_version=v1, returned_version=v2,
            success=True, topology_state=args.scenario, mr_violation=True,
        )


def main():
    args = build_arg_parser().parse_args()
    run_workload(PROPERTY, args, get_normal_client, trial)


if __name__ == "__main__":
    main()
