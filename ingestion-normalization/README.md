# ingestion-normalization

Phase 1, Component 2 of the GPU cost-optimization SaaS: reads raw GPU
samples from telemetry-collector's SQLite database, attributes each one to
a stable workload identity (surviving pod restarts/reschedules), scales
raw utilization % by GPU capability so heterogeneous SKUs are comparable,
and rolls the result up into 5-minute/hourly/daily time buckets for the
(not yet built) waste detector to consume.

## Local development

Depends on telemetry-collector's Storage/correlator only in its test
fixtures (see `tests/conftest.py`) -- production code never imports it,
only reads its documented SQLite schema. To run tests:

```bash
pip install -e ../telemetry-collector -e ".[dev]"
pytest
```

## Running standalone

```bash
export RAW_TELEMETRY_SQLITE_PATH=../telemetry-collector/telemetry.db
export NORMALIZED_SQLITE_PATH=./normalized.db
export SOURCE_SCRAPE_INTERVAL_SECONDS=30   # must match the collector's own interval
ingestion-normalization
```

## Design notes

- **Component boundary is the SQLite schema, not shared code.** `raw_reader.py`
  connects to telemetry-collector's database read-only (`mode=ro`) and
  reads the `gpu_metrics`/`scrape_runs` tables directly by name, so this
  component can be deployed and scaled independently of the collector.
- **Workload identity, not pod identity.** `workload.py` strips
  Kubernetes-generated suffixes (ReplicaSet hash + pod suffix, StatefulSet
  ordinal, Job suffix) using a vowel-free character class matching k8s's
  own random-suffix alphabet -- this is what keeps a real word like
  "data-loader" from being misread as a fake hash.
- **Capacity-normalized comparability.** `capability.py` maps a GPU model
  string to public spec-sheet FP16 TFLOPS/bandwidth so "80% utilized T4"
  and "80% utilized H100" aren't treated as equivalent. An unrecognized
  model is marked explicitly unknown rather than guessed.
- **Gaps are visible, not smoothed over.** Every rollup carries
  `coverage_ratio` (samples present / samples a full window at the source
  scrape cadence should have) and a `low_confidence` flag. A collector
  outage and a genuinely idle GPU both produce low average utilization,
  but only the idle GPU has coverage_ratio == 1.0 -- that distinction is
  the whole point of doing this explicitly instead of just averaging
  whatever data showed up.
- **MIG and time-sliced sharing.** Component 1 preserves DCGM's `GPU_I_ID`
  per MIG instance, so this layer treats each instance as its own
  workload row rather than merging them. True time-slicing on a
  non-MIG GPU can't be split this way -- DCGM only reports one
  utilization value per physical device -- so a time-sliced GPU's samples
  are attributed to whichever pod DCGM's integration reports, a known
  limitation rather than exact per-tenant accounting.
- **Idempotent re-runs.** Both the normalized-sample insert (`INSERT OR
  IGNORE` on a unique key) and rollup recomputation (delete-then-insert
  over the touched time window) are safe to run repeatedly over
  overlapping windows -- needed because the pipeline always recomputes
  rollups for the full range touched by each ingestion cycle.

See `../deploy/helm/gpu-telemetry-collector` for how this runs alongside
the collector in-cluster.
