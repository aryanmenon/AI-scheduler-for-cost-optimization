# GPU Cost-Optimization SaaS

An optimization layer on top of existing Kubernetes GPU schedulers
(KAI/Volcano/native): it detects idle, fragmented, and over-provisioned
GPU capacity on a customer's inference cluster and recommends/automates
fixes, priced as a share of the savings it finds.

This is Phase 1 of a two-product roadmap (see `docs/roadmap.md`): prove
this SaaS, sell it to a beachhead of mid-market inference teams, then use
that revenue and those relationships to fund the harder, higher-moat
power-hard-constraint scheduler for grid-unstable data centers. The
power-constrained scheduler is explicitly out of scope for now.

## Why this, why now

- GPU orchestration software is a ~$1.78B (2025) → $8.16B (2031) market,
  growing ~29% CAGR — but it's crowded (Cast AI, ScaleOps, NVIDIA giving
  Run:ai/KAI away free). The wedge here isn't algorithmic novelty; it's
  fast, low-friction adoption: self-serve, one-command install, prove
  savings in "observe mode" before a customer pays anything.
- The gate that decides whether this business is worth pursuing further:
  **sustain 30–40%+ utilization gains on real inference workloads.** Until
  design-partner data proves that, nothing downstream (sales motion, phase
  3 scheduler funding) matters.

## Architecture (Phase 1 MVP)

```
telemetry collector  →  ingestion & normalization  →  waste detector  →  savings estimator  →  dashboard / report
     (built)                    (built)                  (built)            (planned)             (planned)
```

Five components, in build order — see `docs/roadmap.md` §4–5 for full
detail and status of each:

1. **Telemetry collector** — one-command, read-only install. *Built in
   this repo* (`telemetry-collector/`), validated against synthetic
   fixtures modeling a heterogeneous A100/H100/T4 fleet.
2. **Ingestion & normalization** — per-workload time series,
   capability-aware normalization across heterogeneous GPU SKUs. *Built in
   this repo* (`ingestion-normalization/`): derives a stable workload
   identity from pod names, scales raw utilization by a GPU capability
   reference table so SKUs are comparable, and rolls samples up into
   5-min/hourly/daily buckets with explicit gap/coverage tracking.
3. **Baseline & waste detector** — idle/fragmentation/over-provisioning
   detection. *Built in this repo* (`waste-detector/`): four detectors
   (idle, over-provisioned, fragmented, recurring-pattern), each excluding
   low-coverage rollups and requiring sustained evidence before flagging
   anything, to keep false positives — which cost more customer trust than
   a missed detection — low.
4. Achievable ceiling & savings estimator — SLA-aware target + confidence
   scored $ impact. Not yet built.
5. Observe-mode report & dashboard — the self-serve sales artifact. Not
   yet built.

## What's in this repo right now

```
telemetry-collector/          Python collector: scrape → correlate → store
  src/telemetry_collector/
    config.py                 env-driven configuration
    metrics_client.py         Prometheus scrape + parse, with retry/backoff
    correlator.py             GPU → pod/namespace attribution (MIG-aware)
    storage.py                SQLite (WAL) schema + writes
    collector.py               the scrape/correlate/store loop
    main.py                   entrypoint
  tests/                      unit + integration tests against synthetic
                               DCGM exporter / kube-state-metrics fixtures
  Dockerfile

ingestion-normalization/      Python normalizer: raw samples → per-workload
                               time series, comparable across GPU SKUs
  src/ingestion_normalization/
    raw_reader.py              read-only reader of the collector's SQLite
    workload.py                pod name → stable workload identity
    capability.py               GPU model → FP16 TFLOPS/bandwidth reference
    normalizer.py               joins raw samples into per-workload records
    rollup.py                   5-min/hourly/daily buckets with explicit
                                 coverage_ratio / low_confidence gap handling
    storage.py                  normalized-sample + rollup SQLite schema
    pipeline.py, main.py        the ingest/normalize/rollup loop
  tests/                       unit + integration tests, including a
                                synthetic data-gap and a MIG-sharing scenario
  Dockerfile

waste-detector/                Python detector: rollups → waste findings
  src/waste_detector/
    rollup_reader.py            read-only reader of ingestion's SQLite
    idle.py                     streak-based idle detection, tuned against
                                 flagging healthy bursty inference traffic
    over_provisioning.py        peak-vs-threshold single-snapshot detection
    fragmentation.py            multi-workload, multi-GPU node underuse
    patterns.py                 recurring hour-of-day low-usage windows
                                 (tolerates occasional exception days)
    findings.py                  shared WasteFinding schema + SQLite storage
    detector.py, pipeline.py,
    main.py                      orchestration + the detect/store loop
  tests/                        unit + integration tests per category, plus
                                 a combined-run test and a false-positive
                                 (healthy bursty workload) guard
  Dockerfile

deploy/helm/gpu-telemetry-collector/
                               one-command Helm chart: DCGM exporter
                               DaemonSet + kube-state-metrics + the
                               collector (with ingestion-normalization and
                               waste-detector as sidecars sharing its PVC,
                               each read-only against the stage before it),
                               all RBAC read-only (get/list/watch only — no
                               create/update/patch/delete anywhere)
```

## Quickstart

Run all three components' test suites:

```bash
cd telemetry-collector
pip install -e ".[dev]"
pytest

cd ../ingestion-normalization
pip install -e ../telemetry-collector -e ".[dev]"  # dev-only; see its README
pytest

cd ../waste-detector
pip install -e ../ingestion-normalization -e ".[dev]"  # dev-only; see its README
pytest
```

Install onto a cluster with GPU nodes (once images are published):

```bash
helm install gpu-telemetry deploy/helm/gpu-telemetry-collector \
  --namespace gpu-optimizer --create-namespace
```

This deploys DCGM exporter (per-GPU utilization/memory/power),
kube-state-metrics (pod/node metadata), and the collector — which
correlates the two into a raw SQLite time series, hands it to the
ingestion-normalization sidecar (workload identity + capability
normalization + rollups), which in turn feeds the waste-detector sidecar
that flags idle/over-provisioned/fragmented/recurring-pattern findings for
the (not-yet-built) savings estimator to price. See
`deploy/helm/gpu-telemetry-collector/values.yaml` to toggle persistence,
scrape/poll intervals, detector thresholds, and image tags.

## Key risk / decision gate

Phase 1 cannot justify funding Phase 3 (the power scheduler) unless real
customer workloads sustain 30–40%+ utilization gains. Until 2–3 design
partners validate that on real clusters, treat every number in
`docs/roadmap.md`'s market comparison as directional, not proof.
