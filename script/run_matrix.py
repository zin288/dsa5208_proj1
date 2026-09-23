"""Sweeps {C1..C4} x {RYW,MR,MW,WFR} x {normal, node-failure, partition} and runs each workload script.

Node-failure scenarios are split into secondary_down and primary_down, so this covers 4 scenarios
per property/config cell. Recovery is guaranteed by scenarios.apply_scenario in each workload's harness.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fault_recover import recover

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
MAX_ATTEMPTS = 8
RETRY_DELAY_S = 5


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--configs", nargs="+", default=CONFIGS, choices=CONFIGS)
    parser.add_argument("--properties", nargs="+", default=list(PROPERTIES), choices=list(PROPERTIES))
    parser.add_argument("--scenarios", nargs="+", default=SCENARIOS, choices=SCENARIOS)
    parser.add_argument("--force", action="store_true",
                         help="re-run a cell even if its result file already exists")
    args = parser.parse_args()

    cells = [
        (config, prop, scenario)
        for config in args.configs
        for prop in args.properties
        for scenario in args.scenarios
    ]

    print(f"running {len(cells)} cells x {args.trials} trials")
    failures = []
    for i, (config, prop, scenario) in enumerate(cells, start=1):
        experiment_id = f"{config}-{scenario}-{prop}-seed{args.seed}"
        result_path = RESULTS_RAW_DIR / f"{experiment_id}.jsonl"
        if result_path.exists() and not args.force:
            print(f"[{i}/{len(cells)}] {config} {prop} {scenario} - skip (already done: {result_path.name})")
            continue

        script = SCRIPT_DIR / PROPERTIES[prop]
        cmd = [
            sys.executable, str(script),
            "--config", config, "--scenario", scenario,
            "--trials", str(args.trials), "--seed", str(args.seed),
        ]
        print(f"[{i}/{len(cells)}] {config} {prop} {scenario}")

        for attempt in range(1, MAX_ATTEMPTS + 1):
            start = time.monotonic()
            result = subprocess.run(cmd)
            elapsed = time.monotonic() - start
            if result.returncode == 0:
                print(f"  ok ({elapsed:.1f}s)")
                break
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} FAILED (exit {result.returncode}, {elapsed:.1f}s)")
            if attempt < MAX_ATTEMPTS:
                # A failure is usually a stale lock/partition from a colliding process - recover
                # the cluster and retry rather than leaving the whole matrix run stuck on one cell.
                recover()
                Path(script.parent.parent / ".experiment.lock").unlink(missing_ok=True)
                time.sleep(RETRY_DELAY_S)
        else:
            failures.append((config, prop, scenario))

    if failures:
        print(f"\n{len(failures)} cell(s) failed: {failures}")
        sys.exit(1)
    print("\nall cells completed")


if __name__ == "__main__":
    main()
