# savings-estimator

Phase 1, Component 4 of the GPU cost-optimization SaaS: prices
waste-detector's findings into confidence-scored rupee (INR) figures,
sizing right-sizing recommendations against an SLA-aware utilization
ceiling rather than a naive "run at 100%" target.

## Estimate basis: observed vs. projected

Every estimate is tagged with a `basis`, because conflating "already
spent" money with "projected future" money would overclaim:

| Category | Basis | Why |
|---|---|---|
| `idle` | `observed_window` | An idle streak's own idle-fraction is 100% by construction (that's what makes it a streak). Projecting that rate to a full month would claim the GPU is idle *all the time*, which the finding says nothing about outside its own window. Priced as money already spent with zero value during exactly that window -- a defensible lower bound, not a forecast. |
| `over_provisioned` | `projected_monthly` | Requires 24h+ of observed peak-never-exceeds-threshold evidence before it fires at all -- built to represent a persistent state, so projecting its rate forward is the standard basis for a right-sizing ROI calculation. |
| `oversized_by_average` | `projected_monthly` | Peak too high for `over_provisioned` (any in-flight request reads as busy on an LLM server) but the busiest hour averaged low. Same right-sizing as `over_provisioned`, sized on that average against the stricter `AVG_LOAD_TARGET_UTILIZATION_PCT` (default 50%) because an hourly average hides bursts. |
| `fragmented` | `projected_monthly` | Same reasoning: a 4h+ sustained streak is the detector's minimum before flagging, so it's evidence of an ongoing pattern. |
| `recurring_pattern` | `projected_monthly` | Explicitly measures a rate across many observed calendar days already -- extrapolation is what the category is *for*. |
| `underutilized`, `unattributed_gpu_time` | `detected_no_recommendation` | Waste with no reliable recommendation. Priced like idle -- rate x shortfall below the efficient-use target x observed hours, already spent, not projected -- and kept out of the headline totals. |
| `multi_gpu_oversized` | `visibility_upper_bound` | Projected monthly like the above, but sized on hourly averages with no memory check, so it's an upper bound to prompt a review, not a figure to stand behind. Its own basis keeps it out of the headline total; discounted by `MULTI_GPU_CAPTURE_FRACTION` (default 0.5). |

## Achievable ceiling, not 100%

`ceiling.py` recommends the smallest known GPU SKU whose capacity, sized
to a workload's *already-observed peak* load, would land at or below a
configurable `SLA_TARGET_UTILIZATION_PCT` (default 70%) -- not 100%. Full
utilization leaves no headroom for a traffic spike or a latency-sensitive
retry storm; a right-sizing recommendation that causes an SLA breach costs
more customer trust than the waste it fixed.

A candidate must fit on all three resources a workload can run out of:

- **FP16 compute** and **memory bandwidth**, each sized as current
  capacity x observed load / target. Sizing on compute alone was disproved
  on real GPUs: token generation is bandwidth-bound (see
  `testing/rightsizing-mini-test/`).
- **Memory capacity**: the target's usable memory must hold the window's
  peak memory used (rollups' `max_memory_used_mb`) x 1.1. When the workload
  holds >= 85% of its GPU's memory -- vLLM and TensorFlow pre-allocate --
  or no peak is recorded for every hour, need can't be seen; then a
  smaller-memory target is still recommended but the action says
  "memory fit not checked".

Every recommendation states its expected per-request slowdown (the larger
of the compute and bandwidth drops), e.g. "right-size to NVIDIA A10 (each
request may take up to ~1.6x longer -- fine for batch/offline work, check
latency targets before moving an interactive service)".

## Pricing is configurable, not asserted

`pricing.py` ships illustrative Indian GPU-cloud on-demand list-price
approximations (in INR) as a fallback, but a real deployment should
always set `GPU_HOURLY_RATES_JSON` to the customer's actual contracted
rate. A GPU model with no known rate anywhere is marked explicitly
`unpriceable` rather than priced against a guess -- a wrong "savings"
number computed against a rate the customer doesn't pay would undermine
the one thing this product is selling: a trustworthy rupee figure.

## Local development

```bash
pip install -e ../ingestion-normalization -e ../waste-detector -e ".[dev]"
pytest
```

## Running standalone

```bash
export FINDINGS_SQLITE_PATH=../waste-detector/findings.db
export NORMALIZED_SQLITE_PATH=../ingestion-normalization/normalized.db
export SAVINGS_SQLITE_PATH=./savings.db
export GPU_HOURLY_RATES_JSON='{"NVIDIA A100 80GB": 2.75, "NVIDIA T4": 0.35}'  # your actual rates
savings-estimator
```

## Design notes

- **Component boundary is the schema, not shared code, for the two
  databases it reads** (`findings_reader.py`, `rollup_reader.py`) --
  same pattern as every reader before this one in the pipeline.
- **Capability and category vocabulary ARE real dependencies**, unlike
  the database schemas: `ceiling.py`/`pricing.py` import
  `ingestion_normalization.capability` directly, and `estimator.py`
  imports `waste_detector.findings`' category constants. Both are shared
  domain reference data, not another service's mutable state, so reuse
  avoids re-deriving SKU-matching logic that already exists. See
  `pyproject.toml` and the Dockerfile (which builds from the repo root,
  not this directory, to reach the sibling packages).
- **A finding below `MIN_FINDING_CONFIDENCE` isn't priced at all** --
  same false-positive-cost principle as the detector itself: an estimate
  built on shaky evidence is worse than no estimate.
- **Idempotent estimates.** Re-running pricing over unchanged findings
  replaces (not duplicates) each estimate, keyed by `finding_id`.

See `../deploy/helm/gpu-telemetry-collector` for how this runs alongside
the rest of the pipeline in-cluster.
