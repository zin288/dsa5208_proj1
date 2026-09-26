# DSA5208 Project 1 — MongoDB Consistency Experiments

Distributed MongoDB replica set (`rs0`) used to study client-centric consistency models
(read-your-writes, monotonic-reads, monotonic-writes, writes-follow-reads) under tunable
read/write concern configurations, node failures, and network partitions.

## Environment (recorded on first setup, Windows host)

| Component | Version |
|---|---|
| OS | Windows 11 |
| Docker Desktop | 4.92.0 (engine 29.8.0, API 1.56) |
| Docker Compose | v5.5.1 |
| Python (host venv) | 3.10.9 (used for recorded runs; workflow recommends 3.11+) |
| PyMongo | 4.17.0 |
| MongoDB image | `dsa5208/mongo-lab:8.0.32` (built from `mongo:8.0.32-noble`) |
| Git | 2.36.1 |

## Topology

| Container | Hostname | Port | Role | Priority | Notes |
|---|---|---|---|---|---|
| dsa-mongo1 | mongo1 | 27017 | intended PRIMARY | 2 | |
| dsa-mongo2 | mongo2 | 27018 | SECONDARY | 1 | |
| dsa-mongo3 | mongo3 | 27019 | SECONDARY | 0 | `secondaryDelaySecs=10`, tag `role: delayed` |

## One-time host setup (Windows)

1. Install Docker Desktop, ensure Python 3.10+ and Git are installed.
2. **Add hostname mappings** — required so PyMongo (running on the host) can resolve replica
   set member hostnames configured in [replica-init.js](config/replica-init.js). Edit
   `C:\Windows\System32\drivers\etc\hosts` as Administrator and add:
   ```
   127.0.0.1 mongo1
   127.0.0.1 mongo2
   127.0.0.1 mongo3
   ```
3. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r project1\requirements.txt
   ```

## Bring up the cluster

```powershell
docker compose -f project1\docker-compose.yml up -d --build
docker compose -f project1\docker-compose.yml ps   # wait until all 3 are "healthy"
```

Initialize the replica set (safe to re-run; it's a no-op if already initialized):

```powershell
Get-Content project1\config\replica-init.js | docker exec -i dsa-mongo1 mongosh --port 27017 --quiet
```

Verify topology:

```powershell
docker exec -i dsa-mongo1 mongosh --port 27017 --quiet --eval "rs.status().members.forEach(m => print(m.name + ' | ' + m.stateStr))"
```

Expect `mongo1 | PRIMARY`, `mongo2 | SECONDARY`, `mongo3 | SECONDARY`.

## Running experiments

Shared connection helpers and the C1–C4 read/write concern configurations live in
[script/common.py](../script/common.py). Experiment and fault-injection scripts live in
[script/](../script/):

- `preflight.py`, `cluster_status.py` — health checks, run before/after any batch.
- `fault_secondary_down.py`, `fault_primary_down.py`, `fault_partition.py`, `fault_recover.py` —
  manual fault injection (`fault_recover.py` always cleans up; workload scripts call it
  automatically via `scenarios.py`).
- `test_ryw.py`, `test_monotonic_reads.py`, `test_monotonic_writes.py`,
  `test_writes_follow_reads.py` — one workload each, e.g.:
  ```powershell
  .\.venv\Scripts\python.exe script\test_ryw.py --config C3 --scenario normal --trials 30
  ```
  Common flags: `--config {C1..C4}`, `--scenario {normal,secondary_down,primary_down,partition}`,
  `--trials N`, `--seed N`, `--causal {on,off}`, `--read-target {primary,secondary,delayed}`.
- `run_matrix.py` — sweeps configs x properties x scenarios, e.g. a full formal run:
  ```powershell
  .\.venv\Scripts\python.exe script\run_matrix.py --trials 30
  ```
  Use `--configs`, `--properties`, and `--scenarios` to restrict a run. `--run-id` gives a batch
  a distinct output namespace; choose a new value if the requested trial count differs from an
  existing batch. The runner validates each manifest and trial-ID coverage before skipping a cell,
  uses OS-managed locks to reject concurrent runs, publishes raw JSONL only after a cell completes,
  and enforces a default one-hour per-cell timeout (`--cell-timeout-seconds` can override it).

### P95 latency run

The p95 extension measures normal-operation latency for all four consistency configurations and
all four workloads: 16 cells, with 2,000 trials per cell (32,000 trials total). Each operation
type and target node is summarized separately; reads and writes are not pooled. The estimator uses
linear interpolation at position `(n - 1) * 0.95`. Failed operations and timeouts are excluded from
the successful-operation percentile and reported in a separate count. At 2,000 successful samples,
roughly 100 observations lie in the upper 5% tail.

Latency is measured with Python's high-resolution monotonic `time.perf_counter_ns()` clock. Its
source and reported resolution are stored in each manifest. The initial batch used
`time.monotonic_ns()`, which this Python 3.10.9 Windows environment reports at only 15.625 ms
resolution; its quantized output is preserved for audit but should not be used for p95 conclusions.

Run the p95 batch with a unique label:

```powershell
.\.venv\Scripts\python.exe script\run_matrix.py --configs C1 C2 C3 C4 --properties RYW MR MW WFR --scenarios normal --trials 2000 --run-id p95-hires-20260926 2>&1 | Tee-Object -FilePath results\run_p95_hires_2000.log
```

The run creates one JSONL file and manifest for each cell. After it completes, produce the CSV:

```powershell
.\.venv\Scripts\python.exe script\analyze_latency.py --run-id p95-hires-20260926
```

The summary is written to `results/processed/p95-p95-hires-20260926.csv`. Review the successful sample
count for every operation group before interpreting its p95; groups with few successful samples
should not be compared as if they had 2,000 observations. This p95 batch is for normal operation.
The existing primary-failure, secondary-failure, and partition runs remain the consistency/fault
experiments; a long batch under one injected fault would not represent many independent fault
episodes. For failure scenarios, report each fault episode and failover/recovery duration separately.

The matrix and workload scripts use local OS-managed locks, so duplicate invocations in this
workspace are rejected and the locks are automatically released when the owning process exits.
These locks do not coordinate separate clones or manual Docker/fault commands. Do not run a second
experiment from another checkout or manipulate the cluster while a batch is active.

Predictions made before running the formal matrix are recorded in
[results/manifests/predictions.md](../results/manifests/predictions.md).

Raw per-operation JSONL logs land in `results/raw/<experiment_id>.jsonl`; run manifests (config,
scenario, trial count, seed, git commit) land in `results/manifests/<experiment_id>.json`.
An interrupted cell leaves only a `.partial` file, not a completed JSONL. Use a new `--run-id` for a
fresh batch rather than reusing a run ID with a different trial count.

**Note:** mongo3 (priority 0, delayed secondary) does not appear in the replica-set client's
discovered topology (absent from `hello`'s `hosts`/`passives` fields), so it can only be reached
via a direct connection (`get_delayed_client()` in `common.py`), not via tag-based read preference
on the normal replica-set client. Reads routed to `--read-target delayed` therefore do not share a
causal `ClientSession` with the rest of the trial.

## Tear down

```powershell
docker compose -f project1\docker-compose.yml down
```

This removes containers but keeps named volumes (`mongo1-data`, `mongo2-data`, `mongo3-data`)
unless `-v` is also passed.
