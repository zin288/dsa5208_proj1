"""Sweep configurations, client properties, and scenarios with separate normal/fault sample sizes.

Node-failure scenarios are split into secondary_down and primary_down, so this covers 4 scenarios
per property/config cell. Recovery is guaranteed by scenarios.apply_scenario in each workload's harness.
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
    args = parser.parse_args()
    if args.trials is not None:
        if args.trials < 1:
            parser.error("--trials must be positive")
        args.normal_trials = args.trials
        args.fault_trials = args.trials
    if args.normal_trials < 1 or args.fault_trials < 1:
        parser.error("--normal-trials and --fault-trials must be positive")
    if args.run_id is None:
        args.run_id = datetime.now(timezone.utc).strftime("matrix-%Y%m%dT%H%M%SZ")
    cells = [
        (config, prop, scenario)
        for config in args.configs
        for prop in args.properties
        for scenario in args.scenarios
    ]

    normal_cells = sum(scenario == "normal" for _, _, scenario in cells)
    fault_cells = len(cells) - normal_cells
    planned_trials = normal_cells * args.normal_trials + fault_cells * args.fault_trials
    print(
        f"run_id={args.run_id}; cells={len(cells)}; "
        f"normal={normal_cells} x {args.normal_trials}; "
        f"fault/partition={fault_cells} x {args.fault_trials}; "
        f"planned_trials={planned_trials}",
        flush=True,
    )
    if args.plan:
        return

    acquire_matrix_lock()

    failures = []
    for i, (config, prop, scenario) in enumerate(cells, start=1):
        cell_trials = args.normal_trials if scenario == "normal" else args.fault_trials
        run_component = f"-{args.run_id}"
        experiment_id = f"{config}-{scenario}-{prop}{run_component}-seed{args.seed}"
        if validate_completed_cell(experiment_id, cell_trials, args.run_id):
            print(f"[{i}/{len(cells)}] {config} {prop} {scenario} - skip (validated complete)", flush=True)
            continue

        script = SCRIPT_DIR / PROPERTIES[prop]
        cmd = [
            sys.executable, str(script),
            "--config", config, "--scenario", scenario,
            "--trials", str(cell_trials), "--seed", str(args.seed),
        ]
        cmd.extend(["--run-id", args.run_id])
        print(
            f"[{i}/{len(cells)}] {config} {prop} {scenario} ({cell_trials} trials)",
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
            failures.append((config, prop, scenario))

    if failures:
        print(f"\n{len(failures)} cell(s) failed: {failures}")
        sys.exit(1)
    print("\nall cells completed")


if __name__ == "__main__":
    main()
