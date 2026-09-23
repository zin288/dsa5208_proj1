# Pre-experiment predictions (workflow §8.3)

Filled in before running the formal 30-trial matrix, per the C1-C4 guarantee table in
[Project1_Workflow_chi.md](../../Project1_Workflow_chi.md) §8.2. All predictions assume a
causally-consistent session (`--causal on`) unless noted; "not guaranteed" means an execution
history that violates the property is possible under the documented behaviour, not that every
run will show a violation.

| Config | Read concern | Write concern | RYW | MR | MW | WFR |
|---|---|---|---|---|---|---|
| C1 | majority | majority | guaranteed | guaranteed | guaranteed | guaranteed |
| C2 | majority | w:1 | not guaranteed | guaranteed | not guaranteed | guaranteed |
| C3 | local | w:1 | not guaranteed | not guaranteed | not guaranteed | not guaranteed |
| C4 | local | majority | not guaranteed | not guaranteed | guaranteed | not guaranteed |

## Experiment ID -> prediction

| Experiment ID pattern | Scenario | Property | Prediction | Rationale | Observable judgment |
|---|---|---|---|---|---|
| C1-*-RYW | normal | RYW | no violation observed | majority read after majority write always sees the write | `ryw_violation=false` in all trials |
| C2-normal-RYW | normal | RYW | violations possible | w:1 write may not have propagated to the majority-commit snapshot a `majority` read observes | `ryw_violation=true` on some trials, especially reading the delayed secondary |
| C3-*-RYW | normal | RYW | violations expected | `local` read + w:1 write gives no ordering guarantee at all | frequent `ryw_violation=true`, esp. against `delayed` target |
| C4-*-RYW | normal | RYW | violations possible | `local` read may see a stale local snapshot even though the write itself used majority concern | `ryw_violation=true` on some trials |
| *-*-MR (C1,C2) | any | MR | no violation observed | majority read concern is monotonic: once a majority snapshot is seen, later majority reads cannot regress | `mr_violation` absent |
| *-*-MR (C3,C4) | any | MR | violations possible | `local` read concern can observe non-monotonic snapshots, especially across differently-lagged secondaries | `mr_violation=true` when read2 (delayed) reports an older version than read1 |
| *-*-MW (C1,C4) | normal | MW | no violation observed | majority write concern only acknowledges after replication to a majority, so a later write's CAS precondition should already be visible | `mw_violation` absent |
| *-*-MW (C2,C3) | normal | MW | violations possible under failover, less likely in `normal` | w:1 acknowledges before replication; a failover mid-sequence can lose the "committed" write | `mw_violation=true` more likely in `primary_down`/`partition` scenarios than `normal` |
| *-primary_down/partition-MW | node failure / partition | MW | violations more likely for w:1 configs (C2, C3) | unreplicated w:1 writes on the old primary can be rolled back after election | CAS mismatch (`mw_violation=true`) correlated with failover window |
| *-*-WFR (C1,C2) | any | WFR | no violation observed | majority read concern for tracking `read_version` interacts safely with primary writes | `wfr_violation` absent |
| *-*-WFR (C3,C4) | any | WFR | violations possible | `local` read (esp. against delayed secondary) may return a stale `read_version`, and by write time state has moved on, causing CAS mismatch | `wfr_violation=true` on some trials |

## Scope of "observed" vs "guaranteed"

- A `0/N` violation count for a formal run is reported as "no violation observed in N trials",
  never as "proven to hold" - see workflow §13.3/§18.
- Timeouts/errors (`success=false`) are reported separately from violation counts; they are not
  silently treated as violations.
