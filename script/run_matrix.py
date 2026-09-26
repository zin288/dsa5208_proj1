"""Sweep configurations, client properties, and scenarios with separate normal/fault sample sizes.

Node-failure scenarios are split into secondary_down and primary_down, so this covers 4 scenarios
per property/config cell. Recovery is guaranteed by scenarios.apply_scenario in each workload's harness.

--preset revised runs the priority rerun batch for the revised workloads: same-session
normal cells (the path the C1-C4 prediction table describes) plus MW mid-sequence
fault cells; see revised_preset_cells() below.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fault_recover import recover
from experiment_lock import LOCK_PATH as EXPERIMENT_LOCK_PATH
from file_lock import FileLock
from matrix_lock import acquire as acquire_matrix_lock

CONFIGS = ["C1", "C2", "C3", "C4"]
PROPERTIES = {
    "RYW": "test_ryw.py",
    "MR": "test_monotonic_reads.py",
    "MW": "test_monotonic_writes.py",
    "WFR": "test_writes_follow_reads.py",
}
SCENARIOS = ["normal", "secondary_down", "primary_down", "partition"]

SCRIPT_DIR = Path(__file__).parent
RESULTS_RAW_DIR = SCRIPT_DIR.parent / "results" / "raw"
MAX_ATTEMPTS = 2
RETRY_DELAY_S = 5
DEFAULT_CELL_TIMEOUT_S = 21600


def validate_completed_cell(experiment_id, trials, run_id):
    result_path = RESULTS_RAW_DIR / f"{experiment_id}.jsonl"
    manifest_path = RESULTS_RAW_DIR.parent / "manifests" / f"{experiment_id}.json"
    if not result_path.exists():
        return False
    if not manifest_path.exists():
        raise RuntimeError(f"Result exists without a manifest: {result_path}; use a new --run-id")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("trials") != trials or manifest.get("run_id") != run_id:
        raise RuntimeError(
            f"Existing result {result_path.name} has different run metadata; use a new --run-id"
        )
    if manifest.get("status", "complete") != "complete":
        raise RuntimeError(f"Existing result is not marked complete: {manifest_path}")

    observed_trials = set()
    with result_path.open(encoding="utf-8") as result_file:
        for line_number, line in enumerate(result_file, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON at {result_path}:{line_number}") from exc
            if record.get("experiment_id") != experiment_id:
                raise RuntimeError(f"Mismatched experiment ID in {result_path}:{line_number}")
            if record.get("run_id") != run_id:
                raise RuntimeError(f"Mismatched run ID in {result_path}:{line_number}")
            trial_number = record.get("trial")
            if not isinstance(trial_number, int) or not 1 <= trial_number <= trials:
                raise RuntimeError(f"Invalid trial number in {result_path}:{line_number}")
            observed_trials.add(trial_number)
    if observed_trials != set(range(1, trials + 1)):
        raise RuntimeError(f"Incomplete result {result_path.name}; use a new --run-id to rerun")
    return True


def experiment_lock_is_free():
    lock = FileLock(EXPERIMENT_LOCK_PATH, "experiment")
    try:
        lock.acquire()
    except SystemExit:
        return False
    lock.release()
    return True


# Global read-routing/timing flags this runner can forward to each workload script.
# Only flags the target script actually defines are forwarded for that property,
# and cell-level flags (appended last) override the global passthrough.
GLOBAL_FLAGS = {
    "RYW": {"--read-target": "read_target", "--read-timeout-ms": "read_timeout_ms"},
    "MR": {"--first-read-target": "first_read_target",
           "--second-read-target": "second_read_target",
        "--settle-ms": "settle_ms",
        "--read-timeout-ms": "read_timeout_ms"},
    "MW": {},
    "WFR": {"--read-target": "read_target", "--settle-ms": "settle_ms",
         "--read-timeout-ms": "read_timeout_ms"},
}

MW_FAULT_SCRIPT = "test_monotonic_writes_fault.py"


def make_cell(config, prop, scenario, trials, flags=None, script=None):
    return {"config": config, "property": prop, "scenario": scenario,
            "trials": trials, "flags": flags or {}, "script": script}


def revised_preset_cells(normal_trials, mw_fault_trials):
    """Priority rerun batch for the revised workloads.

    12 same-session normal cells put the causal session on the read path
    (secondary reads share the replica-set client's session), which is what the
    C1-C4 prediction table actually describes; the delayed direct path cannot
    carry the session and is kept out of this batch. 4 MW mid-sequence fault
    cells inject a partition between the client's writes; each trial is an
    independent inject/recover episode.
    """
    cells = []
    for config in CONFIGS:
        cells.append(make_cell(config, "RYW", "normal", normal_trials,
                               flags={"--read-target": "secondary"}))
        cells.append(make_cell(config, "MR", "normal", normal_trials,
                               flags={"--first-read-target": "secondary",
                                      "--second-read-target": "secondary"}))
        cells.append(make_cell(config, "WFR", "normal", normal_trials,
                               flags={"--read-target": "secondary"}))
    for config in CONFIGS:
        cells.append(make_cell(config, "MWF", "mw_fault_partition", mw_fault_trials,
                               script=MW_FAULT_SCRIPT, flags={"--fault-kind": "partition"}))
    return cells


def cell_experiment_id(cell, run_id, seed):
    if cell["property"] == "MWF":
        return f"{cell['config']}-mw_fault_partition-{run_id}-seed{seed}"
    return f"{cell['config']}-{cell['scenario']}-{cell['property']}-{run_id}-seed{seed}"


def cell_command(cell, args):
    if cell["property"] == "MWF":
        cmd = [sys.executable, str(SCRIPT_DIR / cell["script"]),
               "--config", cell["config"], "--trials", str(cell["trials"]),
               "--seed", str(args.seed)]
    else:
        cmd = [sys.executable, str(SCRIPT_DIR / PROPERTIES[cell["property"]]),
               "--config", cell["config"], "--scenario", cell["scenario"],
               "--trials", str(cell["trials"]), "--seed", str(args.seed)]
        for flag, attr in GLOBAL_FLAGS[cell["property"]].items():
            value = getattr(args, attr, None)
            if value is not None:
                cmd.extend([flag, str(value)])
    cmd.extend(["--run-id", args.run_id])
    for flag, value in cell["flags"].items():
        cmd.extend([flag, str(value)])
    return cmd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal-trials", type=int, default=2000)
    parser.add_argument("--fault-trials", type=int, default=30)
    parser.add_argument("--trials", type=int, default=None,
                        help="override both normal and fault trial counts (useful for smoke tests)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--configs", nargs="+", default=CONFIGS, choices=CONFIGS)
    parser.add_argument("--properties", nargs="+", default=list(PROPERTIES), choices=list(PROPERTIES))
    parser.add_argument("--scenarios", nargs="+", default=SCENARIOS, choices=SCENARIOS)
    parser.add_argument("--run-id", default=None,
                        help="unique batch label (generated automatically if omitted)")
    parser.add_argument("--cell-timeout-seconds", type=int, default=DEFAULT_CELL_TIMEOUT_S)
    parser.add_argument("--plan", action="store_true", help="print planned cell/trial counts without running")
    parser.add_argument("--preset", choices=["revised"], default=None,
                        help="run a predefined batch instead of the full cross product "
                             "(revised = same-session normal cells + MW mid-sequence fault cells)")
    parser.add_argument("--revised-normal-trials", type=int, default=200)
    parser.add_argument("--revised-mw-fault-trials", type=int, default=10)
    # Read-routing/timing passthrough, forwarded per property via GLOBAL_FLAGS.
    parser.add_argument("--read-target", choices=["primary", "secondary", "delayed"], default=None)
    parser.add_argument("--first-read-target", choices=["primary", "secondary", "delayed"], default=None)
    parser.add_argument("--second-read-target", choices=["primary", "secondary", "delayed"], default=None)
    parser.add_argument("--settle-ms", type=int, default=None)
    parser.add_argument("--read-timeout-ms", type=int, default=None,
                        help="override the workload read maxTimeMS (default 10000ms)")
    args = parser.parse_args()
    if args.trials is not None:
        if args.trials < 1:
            parser.error("--trials must be positive")
        args.normal_trials = args.trials
        args.fault_trials = args.trials
    if args.normal_trials < 1 or args.fault_trials < 1:
        parser.error("--normal-trials and --fault-trials must be positive")
    if args.preset == "revised":
        if args.revised_normal_trials < 1 or args.revised_mw_fault_trials < 1:
            parser.error("--revised-normal-trials and --revised-mw-fault-trials must be positive")
        args.configs = args.properties = args.scenarios = None  # not used by the preset
    if args.run_id is None:
        args.run_id = datetime.now(timezone.utc).strftime("matrix-%Y%m%dT%H%M%SZ")

    if args.preset == "revised":
        cells = revised_preset_cells(args.revised_normal_trials, args.revised_mw_fault_trials)
    else:
        cells = [
            make_cell(config, prop, scenario,
                      args.normal_trials if scenario == "normal" else args.fault_trials)
            for config in args.configs
            for prop in args.properties
            for scenario in args.scenarios
        ]

    planned_trials = sum(cell["trials"] for cell in cells)
    print(f"run_id={args.run_id}; preset={args.preset or 'full'}; cells={len(cells)}; "
          f"planned_trials={planned_trials}", flush=True)
    if args.plan:
        for cell in cells:
            flags = " ".join(f"{k}={v}" for k, v in cell["flags"].items())
            print(f"  {cell['config']:3s} {cell['property']:4s} {cell['scenario']:20s} "
                  f"trials={cell['trials']:<5d} {flags}", flush=True)
        return

    acquire_matrix_lock()

    failures = []
    for i, cell in enumerate(cells, start=1):
        experiment_id = cell_experiment_id(cell, args.run_id, args.seed)
        if validate_completed_cell(experiment_id, cell["trials"], args.run_id):
            print(f"[{i}/{len(cells)}] {cell['config']} {cell['property']} {cell['scenario']}"
                  f" - skip (validated complete)", flush=True)
            continue

        cmd = cell_command(cell, args)
        flags_text = " ".join(f"{k}={v}" for k, v in cell["flags"].items())
        print(
            f"[{i}/{len(cells)}] {cell['config']} {cell['property']} {cell['scenario']} "
            f"({cell['trials']} trials){' ' + flags_text if flags_text else ''}",
            flush=True,
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            start = time.monotonic()
            try:
                result = subprocess.run(cmd, timeout=args.cell_timeout_seconds)
            except subprocess.TimeoutExpired:
                result = subprocess.CompletedProcess(cmd, returncode=124)
            elapsed = time.monotonic() - start
            if result.returncode == 0:
                print(f"  ok ({elapsed:.1f}s)", flush=True)
                break
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} FAILED (exit {result.returncode}, {elapsed:.1f}s)", flush=True)
            if attempt < MAX_ATTEMPTS:
                if experiment_lock_is_free():
                    recover()
                time.sleep(RETRY_DELAY_S)
        else:
            failures.append((cell["config"], cell["property"], cell["scenario"]))

    if failures:
        print(f"\n{len(failures)} cell(s) failed: {failures}")
        sys.exit(1)
    print("\nall cells completed")


if __name__ == "__main__":
    main()
