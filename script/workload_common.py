"""Shared CLI, causal-session and logging harness for the four consistency workload scripts."""
import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pymongo.read_preferences import Primary, Secondary

from common import get_collection, get_delayed_client
from experiment_lock import experiment_lock
from logging_utils import JsonlLogger, write_manifest
from scenarios import SCENARIOS, apply_scenario

# Matches the tags set in project1/config/replica-init.js.
TAG_SETS = {
    "secondary": [{"role": "normal"}],
}


def read_preference_for(target):
    if target == "primary":
        return Primary()
    return Secondary(tag_sets=TAG_SETS["secondary"])


def get_read_collection(client, delayed_client, config, target):
    """Returns (collection, session_supported). mongo3 (priority 0, delayed) is not part of the
    driver's discovered replica-set topology (absent from hello's hosts/passives), so it can only be
    reached via a direct connection - which cannot share a causal ClientSession with `client`."""
    if target == "delayed":
        return get_collection(delayed_client, config), False
    return get_collection(client, config).with_options(read_preference=read_preference_for(target)), True


def build_arg_parser(description, default_read_target="secondary"):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", choices=["C1", "C2", "C3", "C4"], required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--causal", choices=["on", "off"], default="on")
    parser.add_argument("--read-target", choices=["primary", "secondary", "delayed"],
                         default=default_read_target)
    return parser


def classify_error(error):
    """Map a caught driver exception to a trial_status bucket.

    Timeouts (wtimeout, server selection) are separated from other operation
    errors because they say "unavailable within limits", not "consistency broke".
    """
    if error is None:
        return None
    return "timeout" if "Timeout" in type(error).__name__ else "operation_error"


def manifest_fields(args):
    """Read-routing/timing fields to merge into every manifest this workload writes.

    causal_session_effective_for_reads records whether the reads of this workload
    can actually travel inside the causal session: delayed reads use a direct
    connection that cannot carry the replica-set client's ClientSession, so any
    delayed read target makes this False regardless of --causal on.
    """
    fields = {}
    for name in ("read_target", "first_read_target", "second_read_target", "settle_ms",
                 "pre_write_pause_ms", "post_write_delay_ms"):
        value = getattr(args, name, None)
        if value is not None:
            fields[name] = value
    targets = [t for t in (fields.get("read_target"), fields.get("first_read_target"),
                           fields.get("second_read_target")) if t]
    if targets:
        fields["causal_session_effective_for_reads"] = (
            args.causal == "on" and "delayed" not in targets
        )
    return fields


def make_experiment_id(property_name, args):
    run_component = f"-{args.run_id}" if args.run_id else ""
    return f"{args.config}-{args.scenario}-{property_name}{run_component}-seed{args.seed}"


def run_workload(property_name, args, get_client, trial_fn):
    """trial_fn(client, delayed_client, session, trial_num, logger, experiment_id, args) -> None,
    called once per trial. Use get_read_collection() to route reads to primary/secondary/delayed.
    """
    random.seed(args.seed)
    experiment_id = make_experiment_id(property_name, args)
    extras = manifest_fields(args)
    with experiment_lock():
        logger = JsonlLogger(experiment_id, run_id=args.run_id)
        write_manifest(
            experiment_id,
            config=args.config,
            scenario=args.scenario,
            property=property_name,
            trials=args.trials,
            seed=args.seed,
            run_id=args.run_id,
            causal=args.causal,
            read_target=args.read_target,
            latency_clock="perf_counter_ns",
            latency_clock_resolution_ns=time.get_clock_info("perf_counter").resolution * 1e9,
            status="running",
            **extras,
        )

        client = get_client()
        delayed_client = get_delayed_client()
        causal = args.causal == "on"

        try:
            with apply_scenario(args.scenario):
                for trial_num in range(1, args.trials + 1):
                    session = client.start_session(causal_consistency=causal) if causal else None
                    try:
                        trial_fn(client, delayed_client, session, trial_num, logger, experiment_id, args)
                    finally:
                        if session is not None:
                            session.end_session()
            logger.finalize()
            write_manifest(
                experiment_id,
                config=args.config,
                scenario=args.scenario,
                property=property_name,
                trials=args.trials,
                seed=args.seed,
                run_id=args.run_id,
                causal=args.causal,
                read_target=args.read_target,
                latency_clock="perf_counter_ns",
                latency_clock_resolution_ns=time.get_clock_info("perf_counter").resolution * 1e9,
                status="complete",
                **extras,
            )
        finally:
            client.close()
            delayed_client.close()
    print(f"done: {experiment_id} ({args.trials} trials) -> results/raw/{experiment_id}.jsonl")
