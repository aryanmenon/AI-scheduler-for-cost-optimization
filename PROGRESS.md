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
- **Fragmentation / realistic-traffic / real-duration test: COMPLETE and
  PASSED.** Ran ~25h on a real 2x RTX 4060 vast.ai VM instance ($0.485/hr,
  on-demand, ~$12 total). Both target findings confirmed with real
  evidence at real (not lowered) thresholds:
  - `fragmented`: confidence 1.0, both `tiny-model-a`/`tiny-model-b`
    workloads simultaneously <50% utilized across the full ~25h window.
  - `over_provisioned`: confidence 1.0, "peak utilization 5.0% across 25h
    observed, never exceeded the 30% threshold" -- the real 24h
    observation floor, met and exceeded.
  Pod-to-GPU correlation confirmed working end-to-end for the first time.
  This closes item 1 of the 3-item pre-pilot technical list. Instance
  torn down after this result. Raw findings.db pulled off the box before
  teardown for the record.
- **Three real Helm chart bugs found and fixed** during that deployment
  (all three block ANY real cluster, not just this environment): (1)
  kube-state-metrics' hardcoded `runAsNonRoot: true` with no `runAsUser`
  crashed with `CreateContainerConfigError` since its image declares a
  non-numeric "nobody" user; (2) no `imagePullSecrets` mechanism existed
  on any of the chart's ServiceAccounts, so GHCR images (private) could
  never be pulled without a live `kubectl patch` workaround; (3)
  dcgm-exporter's `nvidia.com/gpu.present=true` nodeSelector requirement
  was never documented, so its DaemonSet silently sat at 0 scheduled on
  any cluster without NVIDIA's GPU Feature Discovery add-on. All three
  fixed in the actual chart/README (see section 3), verified via
  `helm lint`/`helm template` with and without the new value set,
  committed and pushed.
- **4th bug found from the actual 4h fragmentation result**: a real
  Fragmented finding fired correctly (high confidence, correct
  tiny-model-a/tiny-model-b attribution) -- but its `node` field was
  `gpu-telemetry-dcgm-exporter-d5gfj`, DCGM's DaemonSet pod's own name,
  not the real Kubernetes node hostname. Root cause: DCGM self-reports
  `os.Hostname()` (== its own pod name without extra config) as its
  `Hostname` metric label, which `telemetry-collector/correlator.py`
  reads as node identity. Harmless on this single-node test, but a real
  problem before the multi-node test: if the DCGM pod is ever recreated
  on the *same* physical node (crash/restart/upgrade), it gets a new
  random suffix and every finding silently loses continuity for that
  node -- same failure class as the id-churn bug fixed earlier. Fixed by
  adding a `NODE_NAME` downward-API env var to `dcgm-exporter.yaml`,
  matching NVIDIA's own upstream dcgm-exporter DaemonSet template (which
  wires the identical env var, per public GitHub issues describing this
  exact symptom). Verified live in the heterogeneous-SKU test below --
  each dcgm-exporter pod correctly reports its real node hostname
  (`ubuntu`, `node-b`), not its own pod name.
- **Heterogeneous GPU SKU test: COMPLETE and PASSED.** Ran on a real 2-node
  k3s cluster spanning 2 independently-rented vast.ai VM instances (RTX
  4060 Ti + RTX 4000 Ada Generation -- neither a previously-recognized SKU,
  both added to `capability.py`/`pricing.py` for this test, see section 4
  item 2's earlier entry). Bringing the two nodes onto one cluster required
  real infra work beyond the runbook as originally written: Tailscale mesh
  VPN + an SSH tunnel to bridge the two NAT'd VMs, `--flannel-iface`
  explicitly set alongside `--node-ip` (flannel does **not** follow
  `--node-ip` on its own -- a real, easy-to-miss gotcha, see section 5), a
  `default_runtime_name = "nvidia"` fix to containerd config on both nodes,
  and recovering from an NVML driver/library version mismatch via reboot.
  A genuine product bug was found and fixed along the way (not a test-
  environment artifact -- see section 5's "single-Service DCGM scrape"
  gotcha): `telemetry-collector` only ever scraped one node's DCGM exporter
  per cycle because `DCGM_EXPORTER_URL` pointed at a normal (load-balanced)
  ClusterIP Service fronting the DaemonSet, silently starving both nodes'
  rollup `coverage_ratio` to ~0.3-0.6 -- below waste-detector's
  `min_coverage_ratio=0.8` gate -- indefinitely, with `scrape_runs` showing
  100% scrape success the whole time. Fixed by resolving the DCGM hostname
  to every backing pod IP and scraping each individually
  (`metrics_client.resolve_targets`), plus making the Service headless.
  After the fix and one full clean hourly bucket, both target findings
  fired at confidence 1.0 and were correctly priced at two **distinct**
  INR rates on the actual dashboard: `ubuntu` (RTX 4060 Ti) at ₹28.00/hr,
  `node-b` (RTX 4000 Ada Generation) at ₹40.00/hr -- confirming
  `capability.py` correctly identifies different real GPU models from real
  DCGM output and `savings-estimator` prices each independently rather than
  conflating them. This closes item 2 of the 3-item pre-pilot technical
  list.

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

1. **Fragmentation + realistic traffic + real duration — DONE, PASSED.**
   Ran ~25h on 2x RTX 4060 (T4 unavailable on vast.ai at rental time).
   Both Fragmented and Over-provisioned confirmed at confidence 1.0 under
   real (not lowered) thresholds. See section 1 for the actual finding
   data. Idle never fired (expected -- no quiet gap ran long enough by
   chance); Recurring-pattern was never in scope for this rental (needs
   real calendar-day boundaries).
2. **Heterogeneous GPU SKU test + Real managed-Kubernetes-cluster test —
   SPLIT into two independent tests** (reversed the earlier "run together"
   plan once a leftover ~$6.99 vast.ai balance made the split cheaper than
   combining them):
   - **Heterogeneous SKU** — test kit built and pushed:
     `testing/heterogeneous-sku-test/` (README + k8s manifests). Runs on
     vast.ai: 2 separate VM instances, different recognized GPU types,
     joined into one k3s cluster (server + agent over an SSH tunnel to
     node A's port 6443, not a publicly exposed port -- vast.ai only lets
     you add exposed ports at template time, before launch, not to a
     running instance; the tunnel also keeps k3s's API server off the
     public internet entirely. vast.ai's own native multi-node "Clusters"
     feature needs non-NATed same-subnet machines, not reliable for 2
     independently rented instances, so this plain k3s join is used
     instead). Workloads
     pinned one-per-node via `nodeSelector: kubernetes.io/hostname`.
     Uses `values-smoke-test.yaml` (lowered thresholds, ~4h run) since
     this test targets cross-SKU capability/pricing correctness, not a
     re-proof of real-time thresholds already proven by test 1. Availability
     of 2 different recognized SKUs on vast.ai needs a fresh check each
     time (`vastai search offers 'vms_enabled=true num_gpus>=1' -o 'dph_total'`)
     -- not guaranteed. This is also the first live test of the
     dcgm-exporter NODE_NAME fix (section 1, 4th bug) -- README step 3
     has the verification command; check it before trusting any per-node
     finding in this test.
     **Only recognized SKUs (T4/A10/L4/V100/L40S/A100/H100) were
     available at rental time for prior tests -- when T4/A10/L4/V100 were
     all unavailable again, the plan became RTX 3090 + RTX 3060.** Neither
     was in the capability table before, which would have meant both
     landing in "Not priced" (defeating this test's actual point) --
     fixed properly rather than worked around. `capability.py`'s
     `GPUCapability` now has a `recommendable: bool` field, separate from
     `known`: `known` gates pricing/normalization (safe for consumer GPUs
     too), `recommendable` gates whether `ceiling.py`'s right-sizing
     search may ever suggest a SKU as a downsize *target* (never true for
     consumer/gaming cards -- no real cluster racks them as a node pool
     option). Added RTX 3060/3090/4060 as known+priced,
     recommendable=False. Verified the bug is real by temporarily
     removing the `cap.recommendable` filter in `ceiling.py`: an
     over-provisioned A100 finding recommended "NVIDIA GeForce RTX 3060"
     instead of "NVIDIA T4" -- confirmed exactly the failure mode an
     earlier throwaway experiment (not committed) surfaced. Fix + 2 new
     regression tests + 1 pre-existing test updated for the new flag, all
     committed and pushed; full suites green (63 + 51 passed).
   - **Real managed-Kubernetes-cluster test** — not started, runbook not
     yet written. Simplified now that heterogeneous SKU is decoupled: only
     needs ONE GPU node pool (not two), on GKE (chosen as default --
     easiest device-plugin auto-setup, no existing cloud account to
     prefer otherwise). `persistence.enabled: true` for the first real
     PVC test. Blocked on GCP signup + GPU quota increase request (new
     accounts start at zero GPU quota on all three major clouds --
     approval time is unpredictable, minutes to over a day; start this
     early since it's the long pole, not the last step).
3. **Genuine design-partner pilot** — only after the above two. Explicitly
   discussed and agreed: the actual 30-40% utilization-gain business
   thesis can only be validated against real organic traffic on a real
   client's cluster — never provable by a self-run test, however good.
   Operational readiness (onboarding/RBAC scope, rollback story, false-
   positive response process, pricing mechanics) is a parallel written-
   answers task, not a blocker to starting outreach conversations.

## 5. Key gotchas (learned the hard way, don't re-break these)

- **vast.ai instance type**: the earlier attempt to get k8s + the NVIDIA
  device plugin running on a vast.ai rental failed because the default
  vast.ai instance type is itself a Docker container, which blocks nested
  virtualization/privileged workloads/kernel modules — k3s can't run
  properly inside it. Fix: rent vast.ai's **Linux Virtual Machine**
  instance type instead (full root, systemd, explicitly supports
  Kubernetes/Docker-in-Docker per their own docs). Full bring-up recipe
  (k3s install, NVIDIA Container Toolkit, containerd runtime config,
  device plugin DaemonSet, verification command) is now in
  `testing/fragmentation-and-load-test/README.md` step 0.
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

- **Real bug found by the heterogeneous-SKU test itself**: on a genuine
  multi-node cluster, `telemetry-collector` scraped DCGM through a single
  `http://dcgm-exporter:9400/metrics` URL backed by a normal ClusterIP
  Service in front of the dcgm-exporter DaemonSet. kube-proxy load-balances
  each new connection to one random backend pod, so the collector only
  ever saw *one node's* GPU per cycle — never both — which silently
  produced `coverage_ratio` around 0.3-0.6 on every bucket for both nodes
  (never near 1.0), well below waste-detector's `min_coverage_ratio=0.8`
  gate, so zero findings ever fired despite hours of healthy runtime.
  Scrape-level health metrics (`scrape_runs.success`, `attributed_count`)
  looked perfectly fine the whole time — this only showed up by comparing
  `avg_gpu_count` (stuck at 1.00, should be 2 on a 2-node cluster) against
  actual rollup coverage. This would have hit any real multi-node pilot
  customer, not just this test. Fixed in `telemetry-collector`:
  `metrics_client.resolve_targets()` resolves the DCGM hostname to every
  backing IP and scrapes each individually, merging results (falls back to
  the original URL unchanged if resolution fails or returns one address, so
  single-node deployments and existing tests are unaffected); the Helm
  chart's dcgm-exporter Service is now headless (`clusterIP: None`) so its
  DNS name actually returns one A record per node instead of one virtual
  IP. A partial failure (one node's exporter briefly down) now still
  stores the other node(s)' data with a note in `scrape_runs.error`,
  mirroring the existing kube-state-metrics non-fatal-failure pattern.
  Applied to the live rented cluster (rebuilt image, deleted+recreated the
  Service via `helm upgrade` since `clusterIP` is immutable on an existing
  Service) and confirmed: `gpu_count` went to 2 immediately, `coverage_ratio`
  reached `1.0` on the first full clean hourly bucket on both nodes, and
  real findings fired -- see section 1's heterogeneous-SKU test entry.
- **Flannel does not follow `--node-ip`**: k3s's own advertised address
  (API server/kubelet traffic) can be pinned to a Tailscale IP via
  `--node-ip`, but flannel (the CNI/pod-network overlay) auto-detects its
  own interface *independently* and ignores that setting. Left unset,
  cross-node pod-to-pod networking (and therefore cross-node DNS via
  CoreDNS, and therefore any cross-node Service traffic) silently fails
  while node-to-node kubelet/apiserver traffic keeps working fine --
  a confusing split where the cluster looks healthy (`kubectl get nodes`
  all Ready) but cross-node pods can't reach each other. Fix: also pass
  `--flannel-iface=tailscale0` (or whatever the real cross-node interface
  is) alongside `--node-ip` on every node whenever bridging NAT'd hosts via
  a mesh VPN like Tailscale.

## 6. What I (the assistant) have NOT done

- Not rented, accessed, or run anything on the user's actual vast.ai
  instance — this session has no access to their real infrastructure.
- Not started the heterogeneous-SKU or real-managed-cluster test work.
- Not opened any PR beyond PR #1 (registry/CI fix merge).
