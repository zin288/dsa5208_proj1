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
  `test_writes_follow_reads.py`, `test_monotonic_writes_fault.py` — one workload each, e.g.:
  ```powershell
  .\.venv\Scripts\python.exe script\test_ryw.py --config C3 --scenario normal --trials 30
  ```
  Common flags: `--config {C1..C4}`, `--scenario {normal,secondary_down,primary_down,partition}`,
  `--trials N`, `--seed N`, `--causal {on,off}`, `--read-target {primary,secondary,delayed}`.
- `run_matrix.py` — runs the complete 64-cell matrix in one command, or the
  `--preset revised` priority batch (see "Revised workloads" below). By default, normal-operation
  cells use 2,000 trials and node-failure/partition cells use 30 trials:
  ```powershell
  .\.venv\Scripts\python.exe script\run_matrix.py 2>&1 | Tee-Object -FilePath results\run_full_matrix.log
  ```
  To inspect the workload without running it:
  ```powershell
  .\.venv\Scripts\python.exe script\run_matrix.py --plan
  .\.venv\Scripts\python.exe script\run_matrix.py --plan --preset revised
  ```
  This is 16 normal cells x 2,000 trials plus 48 fault/partition cells x 30 trials, for 33,440
  planned trials. The runner prints its generated run ID and per-cell progress. Use `--normal-trials`
  or `--fault-trials` to adjust sample counts; `--configs`, `--properties`, and `--scenarios` can
  restrict a run. `--trials N` overrides both trial counts and is useful for smoke tests. Each run
  gets an automatic unique ID; pass `--run-id` to set one explicitly. The runner validates manifests
  and trial-ID coverage before skipping completed cells, uses OS-managed locks to reject concurrent
  runs, and publishes raw JSONL only after a cell completes. Cells have a six-hour timeout and at
  most one retry (`--cell-timeout-seconds` can override the timeout). If a run is interrupted, resume
  it with the same `--run-id` printed at startup; otherwise a new ID starts a separate batch.
   Individual reads have a 10-second server-side limit by default (`--read-timeout-ms` overrides it),
   so a causal read waiting on an unreplicated write during a partition is logged as a timeout rather
   than blocking that cell indefinitely.

### Revised workloads (branch `revised`)

The 2026-09-26 review of the historical batches found that the original workload
verdicts conflated several distinct outcomes. The revised workloads fix the
semantics; **historical logs remain untouched and are summarized with corrected
labels by `summarize_trials.py`**. Changes:

1. Every trial ends with a `*_check` record carrying `trial_status`:
   `valid_observation`, `in_order`, `read_miss`, `precondition_unmatched`,
   `acked_write_lost`, `interrupted`, `timeout`, `operation_error`, `indeterminate`.
   Violation flags are True only on decidable observations. An empty read
   (`read_miss`) or a failed operation is never counted as a consistency violation.
2. RYW now writes a v0 baseline before the tested v1 write, so a stale non-null
   version is actually observable (`--pre-write-pause-ms` / `--post-write-delay-ms`
   place the delayed read inside the v0-not-v1 window, e.g. 11000/1000).
   Default read target changed `delayed` -> `secondary` (same-session path).
3. MR now creates two versions (v0 baseline, settle, v1) before read1/read2, so a
   version regression is possible at all; `--settle-ms 11000 --second-read-target
   delayed` lands read2 in the window where the delayed member has v0 but not v1.
   Defaults changed to secondary/secondary (same-session path).
4. WFR no longer marks `read_miss`/read errors as violations; `--settle-ms` lets a
   delayed read target return the baseline so the derived write actually happens.
5. New `test_monotonic_writes_fault.py`: the fault lands BETWEEN the client's
   `$inc` writes (partition or primary_down after v1), making w:1 rollback loss
   observable via the final counter. Each trial is an independent episode.
6. Manifests now record `first_read_target`/`second_read_target`/`settle_ms` and
   `causal_session_effective_for_reads` (False whenever a delayed target is used,
   because the direct connection cannot carry the session).

Priority rerun batch (~45 min total; commit first so manifests record the SHA):

```powershell
git add -A; git commit -m "revised workloads"
.\.venv\Scripts\python.exe script\run_matrix.py --preset revised 2>&1 | Tee-Object -FilePath results\run_revised.log
```

This runs 12 same-session normal cells (200 trials each; the path the C1–C4
prediction table describes) plus 4 MW mid-sequence partition cells (10 independent
episodes each). Optional delayed-path contrast cells:

```powershell
.\.venv\Scripts\python.exe script\test_ryw.py --config C3 --scenario normal --trials 5 --run-id delayed-contrast --read-target delayed --pre-write-pause-ms 11000 --post-write-delay-ms 1000
.\.venv\Scripts\python.exe script\test_monotonic_reads.py --config C3 --scenario normal --trials 5 --run-id delayed-contrast --second-read-target delayed --settle-ms 11000
.\.venv\Scripts\python.exe script\test_writes_follow_reads.py --config C3 --scenario normal --trials 5 --run-id delayed-contrast --read-target delayed --settle-ms 11000
```

### Sampling and latency analysis

Normal-operation cells use 2,000 trials to provide a larger latency sample for later analysis.
Fault/partition cells retain 30 trials because each cell injects one sustained fault episode and
performs its operations during that episode. More trials in that same episode would not constitute
more independent failures and would substantially increase runtime. These fault-cell samples are
for consistency outcomes and errors; they are not intended as robust tail-latency estimates.

### Optional repeated fault episodes

The main matrix injects one sustained fault per fault cell. To assess whether observations repeat
across independent failure/recovery cycles, use the optional episode runner:

```powershell
.\.venv\Scripts\python.exe script\run_fault_episodes.py --plan
.\.venv\Scripts\python.exe script\run_fault_episodes.py 2>&1 | Tee-Object -FilePath results\run_fault_episodes.log
```

By default it compares C1 and C3, runs all four properties under secondary-down, primary-down,
and partition scenarios, and repeats each combination for three episodes with ten trials per
episode. That is 72 independently injected episodes and 720 operation trials. The cluster is
recovered and must show one healthy primary, two healthy secondaries, and bounded replica lag in
two consecutive checks before the next episode starts. Use `--configs`, `--properties`,
`--scenarios`, `--episodes`, and `--trials-per-episode` to adjust the scope. Each episode gets its
own run ID and raw log/manifest. This is a focused follow-up, not a replacement for the full matrix;
it does not claim that ten operations within one episode are ten independent failures.

For the targeted monotonic-writes partition comparison (`w:1` C2 versus `majority` C4), run three
independent fault/recovery episodes per configuration:

```powershell
.\.venv\Scripts\python.exe script\test_monotonic_writes_fault.py --config C2 --fault-kind partition --trials 3 --run-id mw-partition-compare-20260926
.\.venv\Scripts\python.exe script\test_monotonic_writes_fault.py --config C4 --fault-kind partition --trials 3 --run-id mw-partition-compare-20260926
.\.venv\Scripts\python.exe script\summarize_trials.py --run-id mw-partition-compare-20260926 --output results\processed\trial_summary_mw-partition-compare-20260926.csv
.\.venv\Scripts\python.exe script\build_results_index.py --mw-fault-run-id mw-partition-compare-20260926 --mw-fault-episodes 3
```

The completed selected comparison in this repository uses run ID `mw-partition-final-20260926`;
its episode summary is `results/processed/trial_summary_mw-partition-final-20260926.csv`. The
index generator includes that run by default. Use a new run ID for any additional execution and
pass it to both the summary and index commands.

Each episode logs the primary that was isolated, the fault application/recovery events, each write
acknowledgement or timeout, and the post-recovery counter. `acked_write_lost` means the recovered
counter is below the number of acknowledged increments. `unacknowledged_effect_present` means an
unacknowledged/timed-out increment nevertheless appears in the recovered state; it is not counted
as a successful majority commit or as an acknowledged-write loss. The results index adds these two
supplemental MW rows without rerunning other matrix cells.

Latency is measured with Python's high-resolution monotonic `time.perf_counter_ns()` clock. Its
source and reported resolution are stored in each manifest. The initial batch used
`time.monotonic_ns()`, which this Python 3.10.9 Windows environment reports at only 15.625 ms
resolution; that earlier quantized batch is retained for audit but should not be used for latency
percentile conclusions.

After a completed matrix run, the analysis owner can calculate latency percentiles separately by
configuration, property, scenario, operation, and target node:

```powershell
.\.venv\Scripts\python.exe script\analyze_latency.py --run-id matrix-YYYYMMDDTHHMMSSZ
```

The summary CSV is written under `results/processed/`. Interpret normal-operation groups using
their 2,000 observations. Fault/partition groups have 30 observations and must be described with
that sample size; they do not support equally stable tail-percentile claims. Failed operations and
timeouts are counted separately from successful-operation latency.

For per-cell trial outcomes (with the corrected `trial_status` labels, derived
retroactively for pre-revision logs), run:

```powershell
.\.venv\Scripts\python.exe script\summarize_trials.py
```

This writes `results/processed/trial_summary.csv` and flags any cell with trial
shortfalls, duplicated operation records, or a non-complete manifest status.

To give the analysis owner an unambiguous file map for the 64 consistency cells,
run:

```powershell
.\.venv\Scripts\python.exe script\build_results_index.py
```

This validates manifests and trial-ID coverage, then writes
`results/processed/latest_results.csv`. It selects the completed main matrix for
the consistency cells, substitutes the corrected MR rerun for C2-C4 MR cells,
and lists the high-resolution normal-operation latency logs separately. Each row
contains the selected run ID, raw JSONL and manifest paths, trial/status counts,
and (for normal cells) the separate latency-data paths. If the curated run IDs
change, provide `--core-run-id`, `--corrected-mr-run-id`, and `--latency-run-id`.
The current generated index is [latest_results.csv](../results/processed/latest_results.csv).

The earlier standalone normal-only high-sample batch and the 64-cell 30-trial matrix remain in the
results tree as separate historical runs. They are not the combined 33,440-trial run described
above. The combined run is planned but has not been started; a new invocation of the default
command above collects both sampling levels under one run ID without overwriting historical data.

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
