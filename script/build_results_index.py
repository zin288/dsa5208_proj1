"""Build a curated map from each consistency cell to its authoritative raw data.

The selected main-matrix run is the baseline; corrected MR runs override its
MR cells for C2-C4. The high-resolution normal-only run is listed separately
as latency input and never replaces the consistency-history source.
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
CONFIGS = ["C1", "C2", "C3", "C4"]
PROPERTIES = ["RYW", "MR", "MW", "WFR"]
SCENARIOS = ["normal", "secondary_down", "primary_down", "partition"]
CORRECTED_MR_CONFIGS = {"C2", "C3", "C4"}
CHECK_OPERATIONS = {"ryw_check", "mr_check", "mw_check", "wfr_check"}


def load_validated_run(run_id, config, property_name, scenario, expected_trials):
    experiment_id = f"{config}-{scenario}-{property_name}-{run_id}-seed0"
    raw_path = RESULTS / "raw" / f"{experiment_id}.jsonl"
    manifest_path = RESULTS / "manifests" / f"{experiment_id}.json"
    if not raw_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"Missing raw log or manifest for {experiment_id}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "config": config,
        "property": property_name,
        "scenario": scenario,
        "trials": expected_trials,
        "status": "complete",
    }
    mismatches = {key: (manifest.get(key), value) for key, value in expected.items()
                  if manifest.get(key) != value}
    if mismatches:
        raise ValueError(f"Manifest mismatch for {experiment_id}: {mismatches}")

    trial_ids = set()
    trial_statuses = {}
    operation_failures = 0
    with raw_path.open(encoding="utf-8") as raw_file:
        for line_number, line in enumerate(raw_file, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {raw_path}:{line_number}") from exc
            if record.get("experiment_id") != experiment_id or record.get("run_id") != run_id:
                raise ValueError(f"Run/experiment ID mismatch at {raw_path}:{line_number}")
            trial_number = record.get("trial")
            if not isinstance(trial_number, int) or not 1 <= trial_number <= expected_trials:
                raise ValueError(f"Invalid trial number at {raw_path}:{line_number}")
            trial_ids.add(trial_number)
            operation = record.get("operation")
            if record.get("success") is False and operation not in CHECK_OPERATIONS:
                operation_failures += 1
            if operation in CHECK_OPERATIONS:
                trial_statuses[trial_number] = record.get("trial_status", "missing_trial_status")

    expected_ids = set(range(1, expected_trials + 1))
    if trial_ids != expected_ids:
        raise ValueError(
            f"Trial coverage mismatch for {experiment_id}: {len(trial_ids)}/{expected_trials}"
        )
    if set(trial_statuses) != expected_ids:
        missing = sorted(expected_ids - set(trial_statuses))[:10]
        raise ValueError(f"Missing final check records for {experiment_id}: {missing}")

    status_counts = {}
    for status in trial_statuses.values():
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "consistency_experiment_id": experiment_id,
        "consistency_manifest_status": manifest["status"],
        "consistency_planned_trials": expected_trials,
        "consistency_observed_trials": len(trial_ids),
        "valid_observations": status_counts.get("valid_observation", 0),
        "in_order": status_counts.get("in_order", 0),
        "timeouts": status_counts.get("timeout", 0),
        "operation_errors": status_counts.get("operation_error", 0),
        "read_misses": status_counts.get("read_miss", 0),
        "precondition_unmatched": status_counts.get("precondition_unmatched", 0),
        "acked_write_lost": status_counts.get("acked_write_lost", 0),
        "interrupted": status_counts.get("interrupted", 0),
        "indeterminate": status_counts.get("indeterminate", 0),
        "observed_violations": sum(
            status_counts.get(status, 0)
            for status in ("precondition_unmatched", "acked_write_lost")
        ),
        "failed_operations": operation_failures,
        "consistency_raw_log": raw_path.relative_to(ROOT).as_posix(),
        "consistency_manifest": manifest_path.relative_to(ROOT).as_posix(),
    }


def load_latency_run(run_id, config, property_name):
    scenario = "normal"
    experiment_id = f"{config}-{scenario}-{property_name}-{run_id}-seed0"
    raw_path = RESULTS / "raw" / f"{experiment_id}.jsonl"
    manifest_path = RESULTS / "manifests" / f"{experiment_id}.json"
    if not raw_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"Missing latency raw log or manifest for {experiment_id}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "config": config,
        "property": property_name,
        "scenario": scenario,
        "trials": 2000,
        "status": "complete",
        "latency_clock": "perf_counter_ns",
    }
    mismatches = {key: (manifest.get(key), value) for key, value in expected.items()
                  if manifest.get(key) != value}
    if mismatches:
        raise ValueError(f"Latency manifest mismatch for {experiment_id}: {mismatches}")

    trial_ids = set()
    successful_latency_records = 0
    failed_latency_records = 0
    with raw_path.open(encoding="utf-8") as raw_file:
        for line_number, line in enumerate(raw_file, start=1):
            record = json.loads(line)
            if record.get("experiment_id") != experiment_id or record.get("run_id") != run_id:
                raise ValueError(f"Run/experiment ID mismatch at {raw_path}:{line_number}")
            trial_number = record.get("trial")
            if not isinstance(trial_number, int) or not 1 <= trial_number <= 2000:
                raise ValueError(f"Invalid latency trial at {raw_path}:{line_number}")
            trial_ids.add(trial_number)
            if record.get("latency_ms") is not None:
                if record.get("success") is True:
                    successful_latency_records += 1
                else:
                    failed_latency_records += 1

    if trial_ids != set(range(1, 2001)):
        raise ValueError(f"Latency trial coverage mismatch for {experiment_id}")

    return {
        "latency_run_id": run_id,
        "latency_trials": len(trial_ids),
        "latency_successful_operation_records": successful_latency_records,
        "latency_failed_operation_records": failed_latency_records,
        "latency_raw_log": raw_path.relative_to(ROOT).as_posix(),
        "latency_manifest": manifest_path.relative_to(ROOT).as_posix(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-run-id", default="matrix-20260926T063608Z")
    parser.add_argument("--corrected-mr-run-id", default="mr-corrected-20260926")
    parser.add_argument("--latency-run-id", default="p95-hires-20260926")
    parser.add_argument("--output", default=str(RESULTS / "processed" / "latest_results.csv"))
    args = parser.parse_args()

    rows = []
    for config in CONFIGS:
        for property_name in PROPERTIES:
            for scenario in SCENARIOS:
                consistency_run_id = args.core_run_id
                corrected_mr = property_name == "MR" and config in CORRECTED_MR_CONFIGS
                if corrected_mr:
                    consistency_run_id = args.corrected_mr_run_id
                trials = 2000 if scenario == "normal" else 30
                consistency = load_validated_run(
                    consistency_run_id, config, property_name, scenario, trials
                )
                row = {
                    "config": config,
                    "property": property_name,
                    "scenario": scenario,
                    "selection_reason": "corrected MR rerun supersedes parser-bugged historical MR cell"
                    if corrected_mr else "primary consistency matrix",
                    "consistency_run_id": consistency_run_id,
                    **consistency,
                }
                if scenario == "normal":
                    row.update(load_latency_run(args.latency_run_id, config, property_name))
                else:
                    row.update({
                        "latency_run_id": "",
                        "latency_trials": "",
                        "latency_successful_operation_records": "",
                        "latency_failed_operation_records": "",
                        "latency_raw_log": "",
                        "latency_manifest": "",
                    })
                rows.append(row)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote authoritative index for {len(rows)} cells -> {output_path}")
    print(f"core run: {args.core_run_id}; corrected MR run: {args.corrected_mr_run_id}; "
          f"normal latency run: {args.latency_run_id}")


if __name__ == "__main__":
    main()
