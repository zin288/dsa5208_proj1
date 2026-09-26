"""JSONL experiment logging + timing helpers, per workflow doc section 9.2 log schema."""
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_RAW_DIR = REPO_ROOT / "results" / "raw"
RESULTS_MANIFEST_DIR = REPO_ROOT / "results" / "manifests"


def get_git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


class JsonlLogger:
    """Publishes a raw JSONL file only after every trial completes."""

    def __init__(self, experiment_id, out_dir=RESULTS_RAW_DIR, run_id=None):
        self.experiment_id = experiment_id
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / f"{experiment_id}.jsonl"
        self.partial_path = out_dir / f"{experiment_id}.jsonl.partial"
        self.partial_path.unlink(missing_ok=True)
        self.run_id = run_id
        self._git_commit = get_git_commit()

    def log(self, **fields):
        record = {
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "trial": None,
            "op_id": uuid.uuid4().hex,
            "client_id": None,
            "session_id": None,
            "operation": None,
            "key": None,
            "requested_version": None,
            "returned_version": None,
            "target_node": None,
            "read_concern": None,
            "write_concern": None,
            "read_preference": None,
            "invoke_monotonic_ns": None,
            "response_monotonic_ns": None,
            "latency_ms": None,
            "success": None,
            "error_type": None,
            "topology_state": None,
            "git_commit": self._git_commit,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        record.update(fields)
        with self.partial_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def finalize(self):
        if not self.partial_path.exists():
            raise RuntimeError("Cannot publish an empty experiment log")
        with self.partial_path.open("ab") as f:
            f.flush()
            os.fsync(f.fileno())
        os.replace(self.partial_path, self.path)


def write_manifest(experiment_id, out_dir=RESULTS_MANIFEST_DIR, **fields):
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "experiment_id": experiment_id,
        "git_commit": get_git_commit(),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest.update(fields)
    path = out_dir / f"{experiment_id}.json"
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(temporary_path, path)
    return path


def timed_op(func, *args, **kwargs):
    """Runs func(*args, **kwargs); returns (result, error, invoke_ns, response_ns, latency_ms).

    error is the caught Exception instance, or None on success; result is None on failure.
    """
    invoke_ns = time.monotonic_ns()
    error = None
    result = None
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        error = exc
    response_ns = time.monotonic_ns()
    latency_ms = (response_ns - invoke_ns) / 1e6
    return result, error, invoke_ns, response_ns, latency_ms
