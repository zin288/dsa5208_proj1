"""Export per-operation p95 latency summaries for one completed run ID."""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "results" / "raw"
MANIFEST_DIR = ROOT / "results" / "manifests"
PROCESSED_DIR = ROOT / "results" / "processed"


def percentile_linear(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return ""
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    groups = defaultdict(lambda: {"latencies": [], "errors": 0, "records": 0})
    manifests = sorted(MANIFEST_DIR.glob("*.json"))
    selected = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_id") == args.run_id:
            if manifest.get("status") != "complete":
                raise SystemExit(f"Run is not complete: {manifest_path.name}")
            selected.append(manifest)

    if not selected:
        raise SystemExit(f"No completed manifests found for run ID {args.run_id!r}")

    for manifest in selected:
        raw_path = RAW_DIR / f"{manifest['experiment_id']}.jsonl"
        if not raw_path.exists():
            raise SystemExit(f"Missing raw log: {raw_path}")
        with raw_path.open(encoding="utf-8") as raw_file:
            for line_number, line in enumerate(raw_file, start=1):
                record = json.loads(line)
                if record.get("run_id") != args.run_id:
                    raise SystemExit(f"Run ID mismatch in {raw_path.name}:{line_number}")
                latency = record.get("latency_ms")
                if latency is None:
                    continue
                key = (
                    manifest["config"], manifest["property"], manifest["scenario"],
                    record.get("operation"), record.get("target_node"),
                )
                group = groups[key]
                group["records"] += 1
                if record.get("success") is True and isinstance(latency, (int, float)):
                    group["latencies"].append(float(latency))
                else:
                    group["errors"] += 1

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / f"p95-{args.run_id}.csv"
    columns = [
        "config", "property", "scenario", "operation", "target_node",
        "successful_observations", "failed_operations", "p95_latency_ms",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=columns)
        writer.writeheader()
        for key, group in sorted(groups.items()):
            config, property_name, scenario, operation, target_node = key
            writer.writerow({
                "config": config,
                "property": property_name,
                "scenario": scenario,
                "operation": operation,
                "target_node": target_node,
                "successful_observations": len(group["latencies"]),
                "failed_operations": group["errors"],
                "p95_latency_ms": percentile_linear(group["latencies"], 0.95),
            })

    print(f"wrote {output_path} from {len(selected)} completed experiment cells")


if __name__ == "__main__":
    main()
