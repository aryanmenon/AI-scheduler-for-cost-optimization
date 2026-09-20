# PROGRESS.md — handoff / context-save

Written as a checkpoint before a context compaction. Purpose: let a fresh
session (or a fresh me) pick this project back up without re-deriving
everything from scratch. Update or delete this file once it's stale —
it's a scratchpad, not permanent documentation.

Branch this was written on: `claude/cost-optimization-saas-telemetry-w4zbhb`
(the repo's actual default branch).

## 1. Status summary — what's done

- **MVP pipeline**: 5 microservices (telemetry-collector,
  ingestion-normalization, waste-detector, savings-estimator, dashboard),
  connected via a shared SQLite schema, each independently deployable via
  Helm (`deploy/helm/gpu-telemetry-collector/`). CI (`.github/workflows/ci.yml`)
  builds and tests all of them; on pushes to the default branch it also
  builds and publishes real images to GHCR (verified working — see PR #1
  below).
- **Registry placeholder bug**: found and fixed. Everything had only ever
  been pushed to a feature branch (`claude/mvp-bugfixes`); the real default
  branch still had `ghcr.io/example-org/...` placeholders. Fixed by merging
  that branch into default via a real PR (**PR #1**, CI-green, merged).
  Confirmed real GHCR images got published afterward.
- **Dashboard redesign**: `dashboard/src/dashboard/render.py` rewritten —
  dark modern-SaaS theme, donut chart replaced with a horizontal stacked
  bar (flexbox, `flex-grow` by value, fixed category color/order, min-width
  floor so tiny segments stay visible). New tests added and verified via
  `git stash` to fail against the old implementation. Committed, pushed,
  CI-green.
- **First real-hardware smoke test**: user rented a vast.ai GPU instance,
  ran the telemetry-collector alone against real DCGM-format metrics.
  Passed cleanly (idle/load states captured correctly and promptly, retry/
  backoff worked, SQLite persistence held across cycles, graceful
  degradation when kube-state-metrics was unreachable). Instance was then
  destroyed.
- **Fast smoke-test overlay**: `deploy/helm/gpu-telemetry-collector/values-smoke-test.yaml`
  — lowers waste-detector thresholds so findings can be checked quickly on
  a short-lived rental. Committed, `helm lint`/`template` verified, CI-green.
- **Fragmentation / realistic-traffic / real-duration test kit**: built and
  pushed, not yet run. See section 3 and 4.

## 2. What's in progress right now

The user is about to (or has just) rented a **2x NVIDIA T4** instance on
vast.ai (chosen over 3090/4090 — see "GPU choice" gotcha below) to run the
test kit in `testing/fragmentation-and-load-test/` for roughly 48 hours,
targeting real **Fragmented** and **Over-provisioned** findings under the
*real* pilot-default thresholds (not the lowered smoke-test ones). This is
a self-run test on rented hardware, not a client/design-partner pilot.

This session was not directly involved in running that rental — I have no
access to the user's real infrastructure. My role resumes when they come
back with results to interpret, or with problems to debug.

## 3. Key file paths

**Detector source (ground truth for thresholds/logic):**
- `waste-detector/src/waste_detector/detector.py`, `idle.py`,
  `over_provisioning.py`, `fragmentation.py`, `patterns.py`, `grouping.py`,
  `config.py`
- Real defaults: `min_coverage_ratio=0.8`; idle: `idle_threshold_pct=2.0`,
  `min_idle_streak_hours=4`; over-provisioned:
  `over_provision_threshold_pct=30.0`, `over_provision_min_observation_hours=24`;
  fragmented: `fragmentation_threshold_pct=50.0`,
  `fragmentation_min_underutilized_gpus=2`, `fragmentation_min_streak_hours=4`;
  recurring pattern: `pattern_min_days_observed=7`,
  `pattern_idle_threshold_pct=5.0`, `pattern_min_consistent_fraction=0.8`.

**Capability / pricing (real-GPU-only limitation lives here):**
- `ingestion-normalization/src/ingestion_normalization/capability.py` —
  `_CAPABILITY_TABLE` only recognizes datacenter SKUs (H100, A100, L40S,
  L4, A10, V100, T4). Consumer cards (3090, 4090) always come back unknown.
- `savings-estimator/src/savings_estimator/pricing.py` — `lookup_price()`
  returns `UNKNOWN_SOURCE` immediately `if not capability.known`, **before**
  checking `rate_overrides`. This means a manual `GPU_HOURLY_RATES_JSON`
  override cannot rescue pricing for an unrecognized GPU. Confirmed root
  cause, not a guess.

**GPU→pod attribution mechanism:**
- `deploy/helm/gpu-telemetry-collector/templates/dcgm-exporter.yaml` —
  already correctly wired (`DCGM_EXPORTER_KUBERNETES=true` +
  `/var/lib/kubelet/pod-resources` hostPath mount). No fix needed, just
  verified.
- `telemetry-collector/src/telemetry_collector/correlator.py` — a GPU
  sample without namespace/pod labels gets `namespace=UNATTRIBUTED` and is
  filtered out before any detector sees it. Requires: DCGM's kubernetes
  integration + a working NVIDIA device plugin + pods requesting
  `resources.limits: {nvidia.com/gpu: "1"}`.
- `ingestion-normalization/src/ingestion_normalization/workload.py` —
  `derive_workload_name(pod)` strips k8s-generated pod-name suffixes to
  recover the stable Deployment/StatefulSet/Job name.

**Test overlays (Helm, layer on top of `values.yaml`, don't replace it):**
- `deploy/helm/gpu-telemetry-collector/values-smoke-test.yaml` — lowers
  waste-detector thresholds for a quick collector-only smoke test.
  Explicitly documents what threshold-lowering *cannot* fix (fragmentation
  is a scenario requirement, pattern is a calendar requirement).
- `deploy/helm/gpu-telemetry-collector/values-extended-test.yaml` —
  deliberately does **not** lower any threshold; only tightens poll/scrape
  cadence. The whole point is proving the real evidence bars hold up.

**Fragmentation/load test kit** (`testing/fragmentation-and-load-test/`):
- `server.py` — FastAPI app running real inference (`sshleifer/tiny-gpt2`
  via transformers), `/healthz` + `/generate`.
- `Dockerfile` — `FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime`,
  pre-downloads the model at build time.
- `load_generator.py` — drives randomized bursty traffic against multiple
  named targets on independent threads (`--target name=url`, repeatable;
  `--duration-hours`, burst/quiet ranges, concurrency). Functionally
  verified against a local fake HTTP server before finalizing.
- `k8s/namespace.yaml`, `workload-a.yaml`, `workload-b.yaml` — two distinct
  Deployment+Service pairs (`tiny-model-a`/`tiny-model-b`) in namespace
  `inference`, each requesting exactly 1 GPU — this is what makes
  fragmentation detection possible (needs >= 2 distinct
  (namespace,workload) pairs simultaneously underutilized on one node).
- `README.md` — full runbook: build/import image, deploy workloads, verify
  GPU assignment (`nvidia-smi -L` per pod), `helm install` command (run
  from repo root, with both `values.yaml` and `values-extended-test.yaml`),
  start the load generator, expectations table per detector, teardown.

## 4. The plan / pilot-readiness roadmap

1. **Fragmentation + realistic traffic + real duration** (in progress,
   ~48h on 2x T4) — targets Fragmented + Over-provisioned findings under
   real thresholds. Idle may fire incidentally; Recurring-pattern is out of
   reach in this timeframe (needs to cross real calendar-day boundaries).
2. **Heterogeneous GPU SKU test** — not started. Separate future work.
3. **Real managed-Kubernetes-cluster test** — not started (StorageClass,
   RBAC, network policy quirks a bare GPU rental doesn't have). Separate
   future work.
4. **Genuine design-partner pilot** — only after the above. Explicitly
   discussed and agreed: the actual 30-40% utilization-gain business
   thesis can only be validated against real organic traffic on a real
   client's cluster — never provable by a self-run test, however good.

## 5. Key gotchas (learned the hard way, don't re-break these)

- **emptyDir persistence**: survives individual container restarts within
  a pod (e.g. liveness-probe kills), but is **wiped by pod
  recreation** (`helm upgrade` under `Recreate` strategy, `kubectl delete
  pod`, node reboot/eviction). Never do any of those mid-test if
  `persistence.enabled: false` (both test overlays currently set this,
  since a bare rental usually has no default StorageClass) — data loss
  means starting the 48h clock over.
- **Detectors are stateless**: waste-detector itself restarting mid-test
  loses no logical state — it re-derives all findings from rollup history
  every cycle. Only the underlying SQLite data matters.
- **GPU choice**: T4 was recommended over 3090/4090 for this test —
  cheapest option AND the only one the product's own capability/pricing
  tables actually recognize (so it's the only choice that produces real
  *priced* findings, not just detected ones). Real current vast.ai pricing
  was checked via web search rather than assumed, and this was current as
  of that check, not guaranteed at rental time.
- **Waste-detector thresholds are wall-clock-gated**, not scrape-frequency
  gated — increasing poll/scrape frequency only reduces reporting lag, it
  cannot substitute for the real elapsed hours (idle streak, over-provision
  observation window, fragmentation streak) or real calendar days
  (recurring pattern) the thresholds require.
- **Deployment name for kubectl**: Helm chart's `fullname` helper
  (`_helpers.tpl`) is exactly `.Release.Name` — so `helm install
  gpu-telemetry ...` produces Deployment `gpu-telemetry-collector`. Verified
  by reading the template, not assumed, before putting it in the README.

## 6. What I (the assistant) have NOT done

- Not rented, accessed, or run anything on the user's actual vast.ai
  instance — this session has no access to their real infrastructure.
- Not started the heterogeneous-SKU or real-managed-cluster test work.
- Not opened any PR beyond PR #1 (registry/CI fix merge).
