"""Build a validated map from consistency cells to their authoritative raw evidence.

The main matrix is the baseline; corrected MR runs supersede the affected old MR
cells. An optional focused MW partition comparison appends C2/C4 fault-episode
rows. High-resolution normal-operation latency inputs are listed separately.
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
CHECK_OPERATIONS = {"ryw_check", "mr_check", "mw_check", "wfr_check", "mw_fault_check"}


def read_jsonl_records(raw_path, experiment_id, run_id):
    with raw_path.open(encoding="utf-8") as raw_file:
        for line_number, line in enumerate(raw_file, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {raw_path}:{line_number}") from exc
            if record.get("experiment_id") != experiment_id or record.get("run_id") != run_id:
                raise ValueError(f"Run/experiment ID mismatch at {raw_path}:{line_number}")
            yield record


def require_manifest(experiment_id, run_id, expected):
    manifest_path = RESULTS / "manifests" / f"{experiment_id}.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest for {experiment_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_values = {"experiment_id": experiment_id, "run_id": run_id, **expected}
    mismatches = {key: (manifest.get(key), value) for key, value in expected_values.items()
                  if manifest.get(key) != value}
    if mismatches:
        raise ValueError(f"Manifest mismatch for {experiment_id}: {mismatches}")
    if manifest.get("status") != "complete":
        raise ValueError(f"Manifest is not complete for {experiment_id}")
    return manifest, manifest_path


def validate_trial_coverage(trial_ids, check_trials, expected_trials, experiment_id):
    expected_ids = set(range(1, expected_trials + 1))
    if trial_ids != expected_ids:
        raise ValueError(f"Trial coverage mismatch for {experiment_id}: {len(trial_ids)}/{expected_trials}")
    if check_trials != expected_ids:
        missing = sorted(expected_ids - check_trials)[:10]
        raise ValueError(f"Final check record missing for {experiment_id}: {missing}")


def count_trial_statuses(statuses):
    counts = {}
    for status in statuses.values():
        counts[status] = counts.get(status, 0) + 1
    return counts


def load_validated_run(run_id, config, property_name, scenario, expected_trials):
    experiment_id = f"{config}-{scenario}-{property_name}-{run_id}-seed0"
    raw_path = RESULTS / "raw" / f"{experiment_id}.jsonl"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Missing raw log for {experiment_id}")
    manifest, manifest_path = require_manifest(experiment_id, run_id, {
        "config": config,
        "property": property_name,
        "scenario": scenario,
        "trials": expected_trials,
    })

    trial_ids = set()
    check_statuses = {}
    operation_failures = 0
    for record in read_jsonl_records(raw_path, experiment_id, run_id):
        trial_number = record.get("trial")
        if not isinstance(trial_number, int) or not 1 <= trial_number <= expected_trials:
            raise ValueError(f"Invalid trial number in {experiment_id}")
        trial_ids.add(trial_number)
        operation = record.get("operation")
        if record.get("success") is False and operation not in CHECK_OPERATIONS:
            operation_failures += 1
        if operation in CHECK_OPERATIONS:
            check_statuses[trial_number] = record.get("trial_status", "missing_trial_status")

    validate_trial_coverage(trial_ids, set(check_statuses), expected_trials, experiment_id)
    counts = count_trial_statuses(check_statuses)
    return {
        "consistency_experiment_id": experiment_id,
        "consistency_manifest_status": manifest["status"],
        "consistency_planned_trials": expected_trials,
        "consistency_observed_trials": len(trial_ids),
        "valid_observations": counts.get("valid_observation", 0),
        "in_order": counts.get("in_order", 0),
        "timeouts": counts.get("timeout", 0),
        "operation_errors": counts.get("operation_error", 0),
        "read_misses": counts.get("read_miss", 0),
        "precondition_unmatched": counts.get("precondition_unmatched", 0),
        "acked_write_lost": counts.get("acked_write_lost", 0),
        "unacknowledged_effect_present": counts.get("unacknowledged_effect_present", 0),
        "interrupted": counts.get("interrupted", 0),
        "indeterminate": counts.get("indeterminate", 0),
        "observed_violations": sum(counts.get(status, 0)
                                    for status in ("precondition_unmatched", "acked_write_lost")),
        "failed_operations": operation_failures,
        "fault_events": "",
        "recovery_events": "",
        "fault_kind": "",
        "fault_point": "",
        "consistency_raw_log": raw_path.relative_to(ROOT).as_posix(),
        "consistency_manifest": manifest_path.relative_to(ROOT).as_posix(),
    }


def load_latency_run(run_id, config, property_name):
    scenario = "normal"
    experiment_id = f"{config}-{scenario}-{property_name}-{run_id}-seed0"
    raw_path = RESULTS / "raw" / f"{experiment_id}.jsonl"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Missing latency raw log for {experiment_id}")
    require_manifest(experiment_id, run_id, {
        "config": config,
        "property": property_name,
        "scenario": scenario,
        "trials": 2000,
        "latency_clock": "perf_counter_ns",
    })

    trial_ids = set()
    successful_latency_records = 0
    failed_latency_records = 0
    for record in read_jsonl_records(raw_path, experiment_id, run_id):
        trial_number = record.get("trial")
        if not isinstance(trial_number, int) or not 1 <= trial_number <= 2000:
            raise ValueError(f"Invalid latency trial in {experiment_id}")
        trial_ids.add(trial_number)
        if record.get("latency_ms") is not None:
            if record.get("success") is True:
                successful_latency_records += 1
            else:
                failed_latency_records += 1
    if trial_ids != set(range(1, 2001)):
        raise ValueError(f"Latency trial coverage mismatch for {experiment_id}")

    manifest_path = RESULTS / "manifests" / f"{experiment_id}.json"
    return {
        "latency_run_id": run_id,
        "latency_trials": len(trial_ids),
        "latency_successful_operation_records": successful_latency_records,
        "latency_failed_operation_records": failed_latency_records,
        "latency_raw_log": raw_path.relative_to(ROOT).as_posix(),
        "latency_manifest": manifest_path.relative_to(ROOT).as_posix(),
    }


def load_mw_fault_run(run_id, config, expected_episodes):
    experiment_id = f"{config}-mw_fault_partition-{run_id}-seed0"
    raw_path = RESULTS / "raw" / f"{experiment_id}.jsonl"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Missing MW fault raw log for {experiment_id}")
    manifest, manifest_path = require_manifest(experiment_id, run_id, {
        "config": config,
        "property": "MW",
        "scenario": "mid_partition",
        "fault_kind": "partition",
        "fault_point": "after_v1",
        "trials": expected_episodes,
    })

    trial_ids = set()
    check_statuses = {}
    operation_failures = 0
    fault_events = set()
    recovery_events = set()
    for record in read_jsonl_records(raw_path, experiment_id, run_id):
        trial_number = record.get("trial")
        if not isinstance(trial_number, int) or not 1 <= trial_number <= expected_episodes:
            raise ValueError(f"Invalid episode number in {experiment_id}")
        trial_ids.add(trial_number)
        operation = record.get("operation")
        if operation == "fault_applied":
            if record.get("success") is not True or record.get("fault_kind") != "partition":
                raise ValueError(f"Partition injection not confirmed in {experiment_id}, episode {trial_number}")
            fault_events.add(trial_number)
        elif operation == "fault_recovered":
            if record.get("success") is not True:
                raise ValueError(f"Fault recovery not confirmed in {experiment_id}, episode {trial_number}")
            recovery_events.add(trial_number)
        if record.get("success") is False and operation != "mw_fault_check":
            operation_failures += 1
        if operation == "mw_fault_check":
            check_statuses[trial_number] = record.get("trial_status", "missing_trial_status")

    validate_trial_coverage(trial_ids, set(check_statuses), expected_episodes, experiment_id)
    if fault_events != set(range(1, expected_episodes + 1)):
        raise ValueError(f"Fault injection evidence incomplete for {experiment_id}")
    if recovery_events != set(range(1, expected_episodes + 1)):
        raise ValueError(f"Fault recovery evidence incomplete for {experiment_id}")

    counts = count_trial_statuses(check_statuses)
    return {
        "consistency_experiment_id": experiment_id,
        "consistency_manifest_status": manifest["status"],
        "consistency_planned_trials": expected_episodes,
        "consistency_observed_trials": len(trial_ids),
        "valid_observations": counts.get("valid_observation", 0),
        "in_order": counts.get("in_order", 0),
        "timeouts": counts.get("timeout", 0),
        "operation_errors": counts.get("operation_error", 0),
        "read_misses": counts.get("read_miss", 0),
        "precondition_unmatched": counts.get("precondition_unmatched", 0),
        "acked_write_lost": counts.get("acked_write_lost", 0),
        "unacknowledged_effect_present": counts.get("unacknowledged_effect_present", 0),
        "interrupted": counts.get("interrupted", 0),
        "indeterminate": counts.get("indeterminate", 0),
        "observed_violations": counts.get("acked_write_lost", 0),
        "failed_operations": operation_failures,
        "fault_events": len(fault_events),
        "recovery_events": len(recovery_events),
        "fault_kind": manifest["fault_kind"],
        "fault_point": manifest["fault_point"],
        "consistency_raw_log": raw_path.relative_to(ROOT).as_posix(),
        "consistency_manifest": manifest_path.relative_to(ROOT).as_posix(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-run-id", default="matrix-20260926T063608Z")
    parser.add_argument("--corrected-mr-run-id", default="mr-corrected-20260926")
    parser.add_argument("--latency-run-id", default="p95-hires-20260926")
    parser.add_argument("--mw-fault-run-id", default="mw-partition-final-20260926",
                        help="optional run ID for the selected C2/C4 MW partition episode comparison")
    parser.add_argument("--mw-fault-episodes", type=int, default=3)
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

    if args.mw_fault_run_id:
        if args.mw_fault_episodes < 1:
            parser.error("--mw-fault-episodes must be positive")
        for config in ("C2", "C4"):
            fault_data = load_mw_fault_run(args.mw_fault_run_id, config, args.mw_fault_episodes)
            rows.append({
                "config": config,
                "property": "MW",
                "scenario": "mid_partition",
                "selection_reason": "supplemental independently injected MW partition episodes",
                "consistency_run_id": args.mw_fault_run_id,
                **fault_data,
                "latency_run_id": "",
                "latency_trials": "",
                "latency_successful_operation_records": "",
                "latency_failed_operation_records": "",
                "latency_raw_log": "",
                "latency_manifest": "",
            })

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote authoritative index for {len(rows)} cells -> {output_path}")
    print(f"core run: {args.core_run_id}; corrected MR run: {args.corrected_mr_run_id}; "
          f"normal latency run: {args.latency_run_id}")
    if args.mw_fault_run_id:
        print(f"supplemental MW fault run: {args.mw_fault_run_id} ({args.mw_fault_episodes} episodes per config)")


if __name__ == "__main__":
    main()
