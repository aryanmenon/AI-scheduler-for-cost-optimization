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

**Phase 1's MVP pipeline is fully built** (all five components below),
validated against synthetic fixtures end to end. What's still needed
before it's sellable: a real GPU cluster to validate against, and 2–3
design partners to prove the 30–40%+ utilization-gain gate below.

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
     (built)                    (built)                  (built)              (built)               (built)
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
   detection. *Built in this repo* (`waste-detector/`): actionable
   detectors (idle, over-provisioned, fragmented, recurring-pattern) plus a
   "below actionable recommendations" tier -- a multi-GPU "could use fewer
   GPUs" upper bound, and every other below-target or pod-less GPU-hour
   measured as detected waste with no recommendation -- each excluding
   low-coverage rollups and requiring sustained evidence before flagging
   anything, to keep false positives — which cost more customer trust than
   a missed detection — low.
4. **Achievable ceiling & savings estimator** — SLA-aware target +
   confidence-scored INR impact. *Built in this repo* (`savings-estimator/`):
   prices each finding, distinguishing money already spent (idle, scoped
   strictly to its observed window) from projected monthly savings
   (over-provisioned/fragmented/recurring, extrapolated from a
   sustained-by-construction observed rate); right-sizes over-provisioned
   workloads against a configurable SLA utilization ceiling (default 70%,
   not 100%); and marks anything with no known GPU price as explicitly
   unpriceable rather than guessing.
5. **Observe-mode report & dashboard** — the self-serve sales artifact.
   *Built in this repo* (`dashboard/`): renders savings-estimator's priced
   findings both as a live, always-current page and as a standalone HTML
   file to email a prospect — the two headline numbers (projected monthly
   savings vs. already-wasted spend observed) are never added together,
   for the same reason component 4 keeps them separate; a "not priced"
   section discloses findings that couldn't be quantified instead of
   hiding them.

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
    multi_gpu.py                multi-GPU jobs that may need fewer GPUs
                                 (visibility-only upper bound)
    unrecommended.py            all remaining below-target / pod-less GPU
                                 time: detected waste, no recommendation
    findings.py                  shared WasteFinding schema + SQLite storage
    detector.py, pipeline.py,
    main.py                      orchestration + the detect/store loop
  tests/                        unit + integration tests per category, plus
                                 a combined-run test and a false-positive
                                 (healthy bursty workload) guard
  Dockerfile

savings-estimator/              Python pricer: findings → INR impact
  src/savings_estimator/
    findings_reader.py           read-only reader of waste-detector's SQLite
    rollup_reader.py              read-only reader of ingestion's SQLite
                                   (including gpu_model/fp16_tflops)
    pricing.py                    GPU ₹/hour lookup, illustrative defaults
                                   overridable with a customer's real rates
    ceiling.py                    SLA-aware right-sizing recommendation
                                   (smallest SKU meeting a utilization
                                   ceiling, not a naive 100% target)
    estimator.py                  per-category ₹ calc: idle priced as
                                   already-spent money in its exact
                                   observed window; over-provisioned/
                                   fragmented/recurring-pattern projected
                                   to a monthly figure, clearly labeled
    storage.py, pipeline.py,
    main.py                       SavingsEstimate schema + the price loop
  tests/                         unit + integration tests per category,
                                 including an unpriceable-GPU guard
  Dockerfile                     (built from the repo root -- see its
                                 comment; this is the one component with
                                 real cross-package runtime dependencies)

dashboard/                      Python report: ₹ estimates → sales artifact
  src/dashboard/
    report_reader.py             read-only reader of savings-estimator's SQLite
    aggregator.py                 estimates → summary (observed vs. projected
                                   totals kept separate, by-category
                                   breakdown, top findings, unpriceable list)
    render.py                     self-contained HTML (inline CSS, HTML-
                                   escaped, no external requests)
    report.py                     shared read→aggregate→render glue
    server.py                     stdlib HTTP server, regenerates live
    main.py                       dashboard-server + generate-report entrypoints
  tests/                         unit tests + a real HTTP server integration
                                 test + an XSS-escaping guard
  Dockerfile

integration-tests/              End-to-end test wiring all five services'
                                 real entrypoints together against real,
                                 on-disk SQLite files -- proves the schema
                                 handoffs between components actually
                                 hold, not just that each one's own test
                                 suite is internally consistent.

deploy/helm/gpu-telemetry-collector/
                               one-command Helm chart: DCGM exporter
                               DaemonSet + kube-state-metrics + the
                               collector (with ingestion-normalization,
                               waste-detector, savings-estimator, and
                               dashboard as sidecars sharing its PVC, each
                               read-only against the stage before it, plus
                               a Service exposing the dashboard), all RBAC
                               read-only (get/list/watch only — no
                               create/update/patch/delete anywhere)
```

## Quickstart

Run all five components' test suites:

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

cd ../savings-estimator
pip install -e ../ingestion-normalization -e ../waste-detector -e ".[dev]"  # REAL runtime deps here, not dev-only; see its README
pytest

cd ../dashboard
pip install -e ../savings-estimator -e ".[dev]"  # dev-only (production code is stdlib-only); see its README
pytest
```

Install onto a cluster with GPU nodes:

```bash
helm install gpu-telemetry deploy/helm/gpu-telemetry-collector \
  --namespace gpu-optimizer --create-namespace
```

Two prerequisites this command assumes are already true on the target
cluster:

- **A pull secret for GHCR**, since the five `image.repository` defaults
  below are not public images. Without one, every container in the
  collector pod fails with `ImagePullBackOff`/`401 Unauthorized` --
  this chart creates its own dedicated ServiceAccounts rather than using
  `default`, so a secret patched onto `default` never reaches these pods.
  Create one and set `global.imagePullSecrets` (see values.yaml):
  ```bash
  kubectl create secret docker-registry ghcr-secret \
    --docker-server=ghcr.io --docker-username=<user> \
    --docker-password=<PAT-with-read:packages> -n gpu-optimizer
  ```
- **GPU nodes labeled `nvidia.com/gpu.present=true`**, which
  `dcgmExporter.nodeSelector` requires by default so its DaemonSet never
  lands on a non-GPU node. NVIDIA's GPU Feature Discovery add-on sets
  this automatically on a real production cluster; without it (a bare
  single-node rental, for instance), the DaemonSet shows `0 desired, 0
  scheduled` until you label the node yourself:
  ```bash
  kubectl label node <node-name> nvidia.com/gpu.present=true
  ```

**Cluster that already runs a dcgm-exporter** (NVIDIA GPU Operator, most
managed GPU clusters): don't run a second one. Turn the chart's off and let
it put a headless Service in front of the existing pods, so every GPU node
gets scraped (defaults match a stock GPU Operator install):

```bash
helm install gpu-telemetry deploy/helm/gpu-telemetry-collector \
  --namespace gpu-optimizer --create-namespace \
  --set dcgmExporter.enabled=false
# non-default install: --set dcgmExporter.external.namespace=<ns> and
#   --set-json 'dcgmExporter.external.podSelector={"app":"<label>"}'
# or point at a URL directly: --set dcgmExporter.external.url=http://...
```

Images are built and published to GHCR by `.github/workflows/ci.yml`'s
`docker-build` job on every push to this repo's default branch (`:latest`
and `:<git-sha>` tags); `values.yaml`'s five `image.tag` fields default to
`:latest` but should be pinned to a specific `:<git-sha>` for a
reproducible/rollback-able production deployment.

This deploys DCGM exporter (per-GPU utilization/memory/power),
kube-state-metrics (pod/node metadata), and the collector — which
correlates the two into a raw SQLite time series, hands it to the
ingestion-normalization sidecar (workload identity + capability
normalization + rollups), which feeds the waste-detector sidecar
(idle/over-provisioned/fragmented/recurring-pattern findings), which
feeds the savings-estimator sidecar (prices those findings into ₹
impact), which finally feeds the dashboard sidecar + Service that renders
it as the sales artifact. Every sidecar carries a livenessProbe: the four
background loops each touch a heartbeat file at the end of every cycle
(success or failure -- these loops catch their own exceptions and keep
running, so a plain "is the process alive" check can't catch a genuinely
stuck one) and the dashboard's own `/healthz` backs its liveness and
readiness probes. A heartbeat-driven restart is self-healing, not
alerting, though -- set `alerting.webhookUrl` to a Slack-compatible
incoming webhook (kept in a Secret, not values.yaml, since it's a
credential) to also get a human-visible message once a service's
consecutive cycle/request failures cross `alerting.consecutiveFailureThreshold`
(default 3), and a second message once it recovers. See
`deploy/helm/gpu-telemetry-collector/values.yaml` to toggle persistence,
scrape/poll intervals, detector thresholds, and image tags — and set
`savingsEstimator.gpuHourlyRatesJson` to the customer's actual contracted
rates before trusting any rupee figure it produces. Then:

```bash
kubectl -n gpu-optimizer get secret gpu-telemetry-dashboard-auth \
  -o jsonpath='{.data.DASHBOARD_AUTH_TOKEN}' | base64 -d; echo
kubectl -n gpu-optimizer port-forward svc/gpu-telemetry-dashboard 8080:8080
# then, with the token above:
curl -H "Authorization: Bearer <token>" http://localhost:8080/
```

`kubectl port-forward` is safe to use as-is here — it's tunneled through
the Kubernetes API server's own TLS/mTLS, so the token and every rupee
figure in the report stay encrypted end to end. See
`dashboard/README.md`'s Security section before changing
`dashboard.serviceType` away from the default `ClusterIP`.

## Key risk / decision gate

Phase 1 cannot justify funding Phase 3 (the power scheduler) unless real
customer workloads sustain 30–40%+ utilization gains. Until 2–3 design
partners validate that on real clusters, treat every number in
`docs/roadmap.md`'s market comparison as directional, not proof.
