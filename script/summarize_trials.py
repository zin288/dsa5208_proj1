"""Summarize per-cell trial outcomes from raw JSONL logs.

Works for both pre-revision logs (no trial_status field; derived from the
operation records) and post-revision logs (trial_status on the final *_check
record is trusted as-is).

Violation counting rule: only trials whose status is a decidable observation
count toward observed_violations. read_miss, precondition_unmatched (proxy),
interrupted, timeouts and operation errors are reported as separate columns -
an empty-read on a lagging path or a write timeout is NEVER silently counted
as a consistency violation or as a clean trial.

Usage:
    python script/summarize_trials.py [--run-id PREFIX] [--output PATH]
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR.parent / "results"
DEFAULT_OUTPUT = RESULTS_DIR / "processed" / "trial_summary.csv"

STATUS_COLUMNS = [
    "valid_observation", "in_order", "read_miss", "precondition_unmatched",
    "acked_write_lost", "interrupted", "timeout", "operation_error",
    "indeterminate", "not_executed",
]


def classify_error_type(error_type):
    if not error_type:
        return "operation_error"
    return "timeout" if "Timeout" in error_type else "operation_error"


def check_record(records):
    """The final per-trial check record (ryw_check / mr_check / mw_check /
    mw_fault_check / wfr_check), if present."""
    checks = [r for r in records if str(r.get("operation", "")).endswith("_check")]
    return checks[-1] if checks else None


def derive_status(records, prop):
    """Reconstruct trial_status for pre-revision logs from the operation records."""
    by_op = {}
    order = []
    for r in records:
        op = r.get("operation")
        if op is None or op.endswith("_check") or op in ("fault_applied", "fault_recovered", "election_wait"):
            continue
        by_op.setdefault(op, []).append(r)
        if op not in order:
            order.append(op)

    def first_error(ops):
        for op in ops:
            recs = by_op.get(op, [])
            for r in recs:
                if r.get("success") is False:
                    return r.get("error_type")
        return None

    if prop == "RYW":
        err = first_error(["write", "write_baseline"])
        if err is not None:
            return classify_error_type(err), False
        read = (by_op.get("read") or [{}])[-1]
        if read.get("success") is False:
            return classify_error_type(read.get("error_type")), False
        if read.get("returned_version") is None:
            return "read_miss", False
        return "valid_observation", read["returned_version"] < 1

    if prop == "MR":
        err = first_error(["write", "write_baseline"])
        if err is not None:
            return classify_error_type(err), False
        for step in ("read1", "read2"):
            rec = (by_op.get(step) or [{}])[-1]
            if rec.get("success") is False:
                return classify_error_type(rec.get("error_type")), False
        v1 = (by_op.get("read1") or [{}])[-1].get("returned_version")
        v2 = (by_op.get("read2") or [{}])[-1].get("returned_version")
        if v1 is None or v2 is None:
            return "read_miss", False
        return "valid_observation", v2 < v1

    if prop == "MW":
        if not by_op.get("write_init"):
            return "not_executed", False
        init = by_op["write_init"][-1]
        if init.get("success") is False:
            return classify_error_type(init.get("error_type")), False
        writes = [by_op.get(f"write_v{v}", [{}])[-1] for v in (1, 2, 3)]
        failed = [w for w in writes if w.get("success") is False]
        succeeded = [w for w in writes if w.get("success")]
        if failed:
            # first failure with nothing succeeding afterwards -> the fault killed
            # the sequence at that write; some later write succeeded -> interrupted
            if not succeeded:
                return classify_error_type(failed[0].get("error_type")), False
            return "interrupted", False
        missing = [w for w in writes if not w]
        if missing and not failed:
            return "interrupted", False
        if any(w.get("mw_violation") for w in writes):
            return "precondition_unmatched", True
        return "in_order", False

    if prop == "WFR":
        init = (by_op.get("write_init") or [{}])[-1]
        if not by_op.get("write_init") or init.get("success") is False:
            return classify_error_type(init.get("error_type")), False
        read = (by_op.get("read") or [{}])[-1]
        if read.get("success") is False:
            return classify_error_type(read.get("error_type")), False
        if read.get("returned_version") is None:
            return "read_miss", False
        derived = (by_op.get("write_derived") or [{}])[-1]
        if not by_op.get("write_derived"):
            return "read_miss", False
        if derived.get("success") is False:
            return classify_error_type(derived.get("error_type")), False
        if derived.get("returned_version") is None:
            return "precondition_unmatched", False
        return "valid_observation", False

    return "indeterminate", False


VIOLATION_FLAG = {
    "RYW": "ryw_violation",
    "MR": "mr_violation",
    "MW": "mw_violation",
    "WFR": "wfr_violation",
}


def summarize_file(path, manifest):
    trials = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for line in f:
            trials[json.loads(line).get("trial")].append(json.loads(line))

    prop = manifest.get("property")
    counts = defaultdict(int)
    violations = 0
    duplicate_op_records = 0
    for trial_num, records in trials.items():
        check = check_record(records)
        if check is not None and check.get("trial_status"):
            status = check["trial_status"]
            violation = bool(check.get(VIOLATION_FLAG.get(prop, ""), False))
        else:
            status, violation = derive_status(records, prop)
        counts[status] += 1
        if violation and status in ("valid_observation", "precondition_unmatched", "acked_write_lost"):
            violations += 1
        # more than one record of the same operation inside a trial usually means a
        # resumed/interleaved run appended onto an existing trial (seen in the old
        # C2-partition-MR log); these trials deserve manual inspection
        op_counts = defaultdict(int)
        for r in records:
            op = r.get("operation")
            if op and not op.endswith("_check"):
                op_counts[op] += 1
        duplicate_op_records += sum(c - 1 for c in op_counts.values() if c > 1)

    row = {
        "experiment_id": manifest.get("experiment_id", path.stem),
        "run_id": manifest.get("run_id", ""),
        "config": manifest.get("config", ""),
        "scenario": manifest.get("scenario", ""),
        "property": prop or "",
        "read_target": manifest.get("read_target", ""),
        "causal": manifest.get("causal", ""),
        "causal_session_effective_for_reads": manifest.get("causal_session_effective_for_reads", ""),
        "manifest_status": manifest.get("status", "(pre-revision: none)"),
        "git_commit": manifest.get("git_commit", ""),
        "planned_trials": manifest.get("trials", ""),
        "observed_trials": len(trials),
        "duplicate_op_records": duplicate_op_records,
    }
    for status in STATUS_COLUMNS:
        row[status] = counts.get(status, 0)
    decidable = ("valid_observation", "in_order", "precondition_unmatched", "acked_write_lost")
    row["decidable_trials"] = sum(counts.get(s, 0) for s in decidable)
    row["observed_violations"] = violations
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None,
                        help="only include experiments whose manifest run_id starts with this prefix")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    manifests = {}
    for mpath in sorted((RESULTS_DIR / "manifests").glob("*.json")):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: unparseable manifest skipped: {mpath.name}")
            continue
        manifests[manifest.get("experiment_id", mpath.stem)] = manifest

    rows = []
    for rpath in sorted((RESULTS_DIR / "raw").glob("*.jsonl")):
        experiment_id = rpath.stem
        manifest = manifests.get(experiment_id)
        if manifest is None:
            print(f"warning: raw log without manifest skipped: {rpath.name}")
            continue
        if args.run_id and not str(manifest.get("run_id", "")).startswith(args.run_id):
            continue
        rows.append(summarize_file(rpath, manifest))

    if not rows:
        raise SystemExit("no experiments matched")

    fieldnames = list(rows[0].keys())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total_trials = sum(r["observed_trials"] for r in rows)
    print(f"wrote {len(rows)} experiments ({total_trials} trials) -> {output}")
    flagged = [r for r in rows if r["observed_trials"] != r["planned_trials"]
               or r["duplicate_op_records"] or r["manifest_status"] not in ("complete", "(pre-revision: none)")]
    if flagged:
        print("cells needing attention (trial mismatch / duplicates / incomplete):")
        for r in flagged:
            print(f"  {r['experiment_id']}: planned={r['planned_trials']} observed={r['observed_trials']} "
                  f"duplicate_op_records={r['duplicate_op_records']} manifest_status={r['manifest_status']}")


if __name__ == "__main__":
    main()
