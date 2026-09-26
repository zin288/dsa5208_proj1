# DSA5208 Project 1
## Client-Centric Consistency in a Replicated MongoDB Deployment

**Group members:** [Name, Student ID], [Name, Student ID], [Name, Student ID]  
**Course:** DSA5208  
**Report status:** Draft through methodology; evaluation and results are pending until the latest combined matrix is run and analyzed.

## 1. Introduction

Replicated databases improve availability and fault tolerance by maintaining multiple copies of data. However, replication also means that a client may observe different versions of the same item depending on which replica serves a read, when a write is acknowledged, and whether the system is experiencing a node failure or a network partition. The consistency observed by an application is therefore not determined by replication alone.

This project studies four client-centric consistency properties in a three-member MongoDB replica set:

- read-your-writes (RYW);
- monotonic reads (MR);
- monotonic writes (MW); and
- writes-follow-reads (WFR).

The experiment varies MongoDB read concern, write concern, causal sessions, read target, and failure condition. The deployment contains two ordinary voting members and a deliberately delayed secondary. The delayed member provides a controlled opportunity to observe stale reads. In addition, the experiment distinguishes an unavailable secondary, a failed primary, and a live network partition.

The purpose of the experiment is not to prove a consistency property from a finite number of trials. Instead, the experiment compares documented or theoretically expected behavior with observed operation histories under a defined workload and deployment. The results section will therefore report both violations and unsuccessful operations, while keeping theoretical guarantees separate from observations in this finite test sample.

## 2. Background

### 2.1 Replication and tunable consistency

A MongoDB replica set contains multiple copies of a database. One member normally acts as the primary and accepts writes, while secondary members replicate the operation history. MongoDB allows clients to select read and write semantics using read concern, write concern, read preference, and sessions.

Read concern controls the consistency level of data returned by reads. This project compares `majority` and `local`. Write concern controls when a write is acknowledged. This project compares `majority` and `w:1`. A majority concern generally waits for acknowledgement from a voting majority, while `w:1` acknowledges after the primary has accepted the write. These settings affect both the visibility of data and the behavior of the system during failures.

A causally consistent session allows related operations to carry causal information between reads and writes. The normal client enables causal sessions for the main replica-set path. The delayed secondary is accessed through a direct connection because MongoDB 8.0.32 does not advertise this priority-zero delayed member in the replica-set client's discovered `hello.hosts` or `hello.passives` list. Consequently, reads directed to the delayed member cannot share the normal client's `ClientSession`; this is recorded as an experimental limitation rather than hidden from the methodology.

### 2.2 Client-centric consistency properties

The project uses the following operational definitions for a single logical client:

**Read-your-writes (RYW).** After a client receives acknowledgement for a write of version $v$, a later read by that client should not return a version older than $v$.

**Monotonic reads (MR).** If a client has read version $v_i$, a later read by that client should not return a version smaller than $v_i$.

**Monotonic writes (MW).** A client's writes should take effect in the order issued by that client. The workload uses sequential version updates and records the invocation and response order. A compare-and-set update that cannot find the immediately preceding version is recorded as evidence that the expected predecessor was not visible at that point; this is an observable proxy, not direct access to MongoDB's internal ordering.

**Writes-follow-reads (WFR).** If a client reads version $v_i$ and then derives a write from that observation, the write should be based on $v_i$ or a later state. The workload records the read version and uses it as the compare-and-set precondition for the derived write.

### 2.3 Failure conditions

The experiment distinguishes three required scenario classes:

- **Normal operation:** all three members are running and inter-member communication is available.
- **Node failure:** either a secondary (`mongo3`) or the primary (`mongo1`) is stopped. These are measured separately because they affect availability and election behavior differently.
- **Network partition:** the `mongo1` container remains running, but iptables rules block its traffic to and from `mongo2` and `mongo3`. This is not treated as equivalent to stopping a node. The majority side can elect a primary while the isolated member remains alive and reachable through its mapped host port.

## 3. System and Deployment

### 3.1 Software environment

The experiments were run on a Windows host using Docker Desktop and a Python virtual environment.

| Component | Version |
|---|---|
| Host operating system | Windows 11 |
| Docker Desktop | 4.92.0 |
| Docker Engine | 29.8.0, API 1.56 |
| Docker Compose | v5.5.1 |
| Python | 3.10.9 |
| PyMongo | 4.17.0 |
| MongoDB base image | `mongo:8.0.32-noble` |
| Project image | `dsa5208/mongo-lab:8.0.32` |
| Git | 2.36.1.windows.1 |

The project workflow recommends Python 3.11 or later; the recorded experiments and current virtual environment use Python 3.10.9. This version deviation should be considered when reproducing the environment.

The custom MongoDB image installs `iptables` and `iproute2` and is granted the Docker `NET_ADMIN` capability. This supports controlled network fault injection inside the containers.

### 3.2 Replica-set architecture

The deployment uses one Docker bridge network and three data-bearing voting members. Each container has an independent named data volume. Host ports are mapped separately so that the Windows experiment controller can contact each member directly.

```text
                         Windows Python controller
                    /          |                  \
       127.0.0.1:27017  127.0.0.1:27018   127.0.0.1:27019
                /              |                  \
          mongo1             mongo2             mongo3
       priority 2          priority 1          priority 0
         PRIMARY            SECONDARY       delayed SECONDARY
                                           delay: 10 seconds
```

| Member | Container | Replica-set address | Host port | Priority | Role |
|---|---|---|---:|---:|---|
| 1 | `dsa-mongo1` | `mongo1:27017` | 27017 | 2 | Normal voting member; preferred primary |
| 2 | `dsa-mongo2` | `mongo2:27018` | 27018 | 1 | Normal voting secondary |
| 3 | `dsa-mongo3` | `mongo3:27019` | 27019 | 0 | Voting delayed secondary; 10-second delay |

All three members have one vote. The replica-set election timeout is 10 seconds. The delayed member has the tag `role: delayed`, although the workload reaches it using a direct connection because of the driver-discovery behavior described in Section 2.1.

### 3.3 Installation and initialization

The environment was created with the following steps:

1. Start Docker Desktop with Linux containers enabled.
2. Add the following entries to the Windows hosts file as Administrator:
   ```text
   127.0.0.1 mongo1
   127.0.0.1 mongo2
   127.0.0.1 mongo3
   ```
   This is required because the replica-set configuration advertises member names such as `mongo1:27017` to the host-side PyMongo client.
3. Create the Python virtual environment and install `project1/requirements.txt`.
4. Build and start the deployment:
   ```powershell
   docker compose -f project1\docker-compose.yml up -d --build
   ```
5. Wait until all three Docker healthchecks report healthy.
6. Pipe `project1/config/replica-init.js` into `mongosh` running in `dsa-mongo1`:
   ```powershell
   Get-Content project1\config\replica-init.js | docker exec -i dsa-mongo1 mongosh --port 27017 --quiet
   ```
7. Verify that `rs.status()` reports one primary and two secondaries.
8. Run the Python preflight and cluster-status scripts before experiments.

The initialization script is idempotent: if the replica set is already initialized, it reports that state rather than creating a second configuration.

## 4. Consistency Configurations and Pre-Experiment Predictions

The workload configuration names are defined in `script/common.py` and are reused by every test script.

| Configuration | Read concern | Write concern | RYW | MR | MW | WFR |
|---|---|---|---|---|---|---|
| C1 | `majority` | `majority` | Expected to hold | Expected to hold | Expected to hold | Expected to hold |
| C2 | `majority` | `w:1` | Not guaranteed | Expected to hold | Not guaranteed | Expected to hold |
| C3 | `local` | `w:1` | Not guaranteed | Not guaranteed | Not guaranteed | Not guaranteed |
| C4 | `local` | `majority` | Not guaranteed | Not guaranteed | Expected to hold | Not guaranteed |

The entries in the last four columns are hypotheses for the tested operation histories. “Not guaranteed” means that the configuration permits a violating history; it does not mean that every finite run must produce a violation. Conversely, a property marked “expected to hold” is a theoretical prediction for the configured causal operation sequence, not a claim that the experiment has proved it universally.

The complete pre-registration table, including scenario-specific rationale and observable fields, is stored in [results/manifests/predictions.md](../results/manifests/predictions.md). It was prepared before the formal matrix was run.

## 5. Experimental Methodology

### 5.1 Data and version model

Each trial uses a fresh logical document identifier to avoid contamination between trials. Documents contain a monotonically ordered integer version, for example:

```json
{
  "_id": "trial-specific-id",
  "version": 3,
  "writer": "client-A"
}
```

The operation history, rather than only the final document value, is used for consistency classification. Each operation records its invocation and response using Python's high-resolution `time.perf_counter_ns()` clock. UTC timestamps are retained for log location and correlation only; they are not used as proof of cross-process happens-before ordering. An earlier collection attempt used `time.monotonic_ns()`, which had only 15.625 ms resolution in this Windows/Python environment; those quantized latency values are retained for audit but excluded from latency-percentile conclusions.

### 5.2 Workloads

Each trial ends with a `*_check` record carrying a `trial_status` classification:
`valid_observation` / `in_order` (the property's check was decidable and held or was
tested), `read_miss` (a read returned no document; the sequence never formed),
`precondition_unmatched` (a compare-and-set predicate failed; indeterminate proxy),
`acked_write_lost` (an acknowledged write's effect vanished), `interrupted`,
`timeout`, `operation_error`, or `indeterminate`. Violation flags are set only on
decidable observations: an empty read on a lagging path or a failed operation is
never counted as a consistency violation.

**RYW workload.** The client first writes a baseline version 0, then the tested
version 1 to the primary, and then reads the same document from a selected target:
primary, normal secondary, or delayed secondary. A read returning a version older
than the acknowledged write (i.e. the baseline) is a `ryw_violation` on a
`valid_observation` trial; a read returning no document is recorded as `read_miss`
(a staleness observation of that path, kept separate from violations); driver
errors and timeouts are reported separately. Optional timing pauses
(`--pre-write-pause-ms`, `--post-write-delay-ms`) place the delayed read inside the
window where the delayed member has applied the baseline but not the tested write,
which is how a non-null stale version becomes observable.

**MR workload.** The client writes a baseline version 0, optionally waits a
configurable settle time, updates to version 1, then performs two reads of the same
document from configurable targets (default: normal secondary for both, inside the
causal session). A successful second read with a strictly smaller non-null version
than the first is an `mr_violation` on a `valid_observation` trial; a read
returning no document makes the trial `read_miss`. The two-version design makes a
version regression observable at all; with `--second-read-target delayed` and a
settle of ~11 s, the second read lands in the window where the delayed member has
the baseline but not the update.

**MW workload.** The client performs sequential updates from version 0 to 1, 2, and 3.
Each update uses the immediately preceding version as a compare-and-set predicate.
The logs record whether the predecessor matched, along with invocation order,
acknowledgement, and errors. A failed predecessor match on an otherwise successful
sequence is recorded as `precondition_unmatched` - the observable proxy for a
monotonic-writes violation - while errors and timeouts are classified separately.

**MW mid-sequence fault workload.** The main matrix applies one fault around a whole
cell, so a separate workload injects a fault *between* the client's writes: insert a
counter, increment it (acknowledged), inject a partition or stop the primary,
increment again, wait out the election, increment a third time, recover, and read
the final counter. Because increments compose, the final value exposes whether every
acknowledged increment's effect survived: with `w:1`, the middle increment is
acknowledged by the isolated old primary alone and rolls back on rejoin, while the
third increment persists from the majority side - the client observed three
acknowledgements but the final state misses one (`acked_write_lost`, recorded as an
observable monotonic-writes ordering break caused by rollback). With `majority`
write concern the faulted writes time out instead, showing the availability price
of the stronger concern. Each trial is an independent inject/recover episode.

**WFR workload.** The client inserts a baseline version 0, optionally waits a
settle time, reads the document from a selected target, derives the next version
from the returned version, and sends a compare-and-set update using the read
version as its predicate. The read value, derived write value, target, session
transmission flag, and update result are logged. A read returning no document is
`read_miss` (the writes-follow-reads sequence never formed, so the trial judges
nothing); a failed predicate is `precondition_unmatched` (indeterminate with a
single client); a matched derived write is a `valid_observation` with the sequence
formed and held.

### 5.3 Logging and reproducibility

Every operation is appended as one JSON object to a JSON Lines file under `results/raw/`. Logs are first written to a partial file and only published as completed JSONL after the entire cell finishes. The log schema includes:

- experiment ID, trial number, operation ID, client and session identifiers;
- logical key and requested/returned versions;
- target node, read/write configuration, and read preference;
- high-resolution monotonic invocation and response times and latency;
- success flag and error type;
- scenario, Git commit, and UTC timestamp;
- property-specific violation flags when applicable.

Each experiment cell also produces a manifest under `results/manifests/` containing the configuration, scenario, property, trial count, random seed, causal-session setting, timer source/resolution, run ID, and Git commit. Completed result files are validated against their manifests and trial IDs before being treated as resumable. The runner uses OS-managed locks to reject concurrent matrix/workload runs and recovers after failed cells.

### 5.4 Scenario execution and cleanup

The formal matrix contains four scenarios:

1. `normal`;
2. `secondary_down`, which stops `mongo3`;
3. `primary_down`, which stops `mongo1` and triggers a new election;
4. `partition`, which blocks traffic between `mongo1` and the other two members using in-container iptables rules while keeping the mongod process alive.

The workload harness places fault injection inside a context with recovery in its cleanup path. The recovery script restarts stopped containers, flushes iptables rules, and is run again after the matrix to verify that all members rejoin the replica set.

### 5.5 Formal experiment matrix

The planned combined matrix uses different sample counts for normal and fault conditions:

$$16\text{ normal cells} \times 2{,}000 + 48\text{ fault/partition cells} \times 30 = 33{,}440\text{ operation trials}.$$

Each cell is one configuration × one consistency property × one scenario. The four configurations are crossed with four properties and four scenarios (`normal`, `secondary_down`, `primary_down`, `partition`), yielding 64 cells. This covers the three scenario classes required by the project; node failure is split into secondary and primary failure for additional detail. Normal-operation cells use 2,000 trials to supply larger per-operation latency samples. Fault/partition cells use 30 operations during one sustained injected episode; this is a consistency-under-fault sample, not 30 independent failures and not a robust tail-latency sample. The combined matrix is documented and implemented but has not yet been rerun; prior 64-cell/30-trial and 16-cell/2,000-normal-trial collections are separate historical runs and should not be described as the combined matrix.

The command in `project1/README.md` runs all cells in one batch with an automatically generated run ID. The run can be previewed with `script/run_matrix.py --plan` and resumed by passing the same printed run ID. In addition, `script/run_matrix.py --preset revised` runs the priority batch assembled after the verdict-semantics revision: twelve same-session normal cells (RYW/MR/WFR x C1-C4, reads on the normal secondary inside the causal session - the path the prediction table actually describes) plus four MW mid-sequence fault cells (C1-C4, ten independent inject/recover episodes each). Optional delayed-path contrast cells with explicit settle timings are documented in the README. For users seeking additional evidence about failure-to-failure variability, `script/run_fault_episodes.py` provides an optional focused study: by default it compares C1/C3 over four properties and three fault conditions, with three independent inject/recover episodes per combination and ten operations per episode (72 episodes, 720 operation trials). It requires the topology to be healthy and replication lag to be within bounds before starting the next episode. This follow-up is optional and separate from the main matrix.

## 6. Results and Evaluation

*To be completed by the evaluation/analysis owner after the combined matrix is run. Report the actual run ID, per-cell sample counts, successful operations, errors and timeouts, violation counts/rates, normal-operation latency percentiles, and prediction-versus-observation comparisons. `script/summarize_trials.py` produces the per-cell `trial_summary.csv` with corrected `trial_status` labels for both pre-revision and revised logs, and flags incomplete cells. If the optional independent fault-episode study is run, report episode counts separately from operation counts and summarize recovery timing. Do not treat `0/N` observed violations as proof of a universal guarantee.*

## 7. Discussion and Limitations

*To be completed after evaluation. Include the single-host Docker deployment limitation; the finite sample sizes; the fact that each main-matrix fault cell represents one sustained episode rather than independent repetitions; and the direct delayed-secondary connection's inability to share the causal session.*

## 8. Conclusion

*To be completed after evaluation.*

## References

1. MongoDB, “Causal Consistency and Read and Write Concerns.” https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/
2. MongoDB, “Read Concern.” https://www.mongodb.com/docs/manual/reference/read-concern/
3. MongoDB, “Write Concern.” https://www.mongodb.com/docs/manual/reference/write-concern/
4. MongoDB, “Replica Set Elections.” https://www.mongodb.com/docs/manual/core/replica-set-elections/
5. MongoDB, “Replica Set Members.” https://www.mongodb.com/docs/manual/core/replica-set-members/
6. PyMongo documentation, “Read Preferences.” https://pymongo.readthedocs.io/en/stable/api/pymongo/read_preferences.html
7. DSA5208 course lectures 1–3, client-centric consistency and distributed-system ordering.

## AI-use statement

Generative AI tools were used to assist with project planning, code implementation, debugging, report drafting, and language editing. The group members remain responsible for verifying the deployment, experiment scripts, raw logs, technical claims, citations, and final submitted report.
