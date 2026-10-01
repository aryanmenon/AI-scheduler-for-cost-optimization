# waste-detector

Phase 1, Component 3 of the GPU cost-optimization SaaS: reads
ingestion-normalization's hourly rollups and flags five categories of
wasted GPU spend for the (not yet built) savings estimator to price.

## Waste categories

| Category | Signal | Built to avoid |
|---|---|---|
| `idle` | A sustained, unbroken run of near-zero avg **and** max utilization over several consecutive hours | Flagging bursty-but-healthy inference traffic, where a single low-average snapshot is normal |
| `over_provisioned` | Peak utilization never exceeds a threshold over a full observation window | Flagging a workload before enough hours are observed to trust the verdict |
| `fragmented` | Multiple GPUs on the same node, owned by *different* single-GPU workloads, all underutilized at the same time for a sustained streak. A consolidation *candidate*: GPU memory fit, combined compute and cluster GPU sharing (time-slicing/MPS/MIG) are not checked | Telling a multi-GPU job to consolidate onto a shared GPU (impossible: NCCL refuses two ranks per GPU) -- any workload on 2+ GPUs in an hour is excluded |
| `recurring_pattern` | A specific hour-of-day that's reliably low-utilization across many observed days, tolerating occasional exceptions | The idle detector's strict contiguity requirement, which would fragment "quiet most nights" into many too-short streaks |
| `multi_gpu_oversized` | A workload on 2+ GPUs whose summed hourly-average busy time would fit on fewer GPUs under a 70% ceiling, for a 4h+ streak. **Visibility only, an upper bound** -- sized on averages (bursts may exceed the ceiling), memory fit unchecked; priced on its own basis and kept out of the dashboard headline | Silently losing multi-GPU underuse once fragmentation stopped covering it (22% of Philly GPU-hours) |

## Local development

```bash
pip install -e ../ingestion-normalization -e ".[dev]"  # dev-only, for test fixtures
pytest
```

## Running standalone

```bash
export NORMALIZED_SQLITE_PATH=../ingestion-normalization/normalized.db
export FINDINGS_SQLITE_PATH=./findings.db
waste-detector
```

## Design notes

- **A wrong recommendation costs more than a missed one.** Every detector
  excludes rollup buckets below `MIN_COVERAGE_RATIO` before evaluating
  anything -- a bucket with missing data reading as near-zero utilization
  is "we don't know," not "confirmed idle." Findings also carry a
  `confidence` score (average coverage across the evidence window) so a
  consumer can choose how aggressively to act on borderline cases.
- **Idle vs. bursty is the central false-positive risk for inference
  workloads.** `idle.py` requires both the average AND the max utilization
  to stay low for the whole streak -- one real request inside an
  otherwise-quiet hour breaks it. This is what separates "abandoned
  deployment" from "healthy service between requests."
- **Fragmentation excludes intentional multi-GPU jobs.** Multiple
  underutilized GPUs only count as fragmented if they belong to at least
  two *distinct* workloads -- a distributed training job spanning several
  GPUs is excluded even though each GPU looks underused alone.
- **Recurring patterns tolerate exceptions; idle streaks don't.**
  `patterns.py` asks "is this hour-of-day usually quiet across many
  days?" rather than requiring an unbroken run, catching workloads
  idle.py's strict streak logic would otherwise miss (one noisy night
  out of twenty shouldn't erase an otherwise-actionable pattern).
- **Component boundary is the rollups schema, not shared code** --
  same pattern as the two components before this one. `rollup_reader.py`
  connects to ingestion-normalization's database read-only.
- **Idempotent findings.** Re-running detection over unchanged rollups
  replaces (not duplicates) each finding, keyed by category + GPU
  identity + time window.

See `../deploy/helm/gpu-telemetry-collector` for how this runs alongside
the collector and ingestion sidecar in-cluster.
