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
- **Real-trace replay: COMPLETE and PASSED** (`testing/real-trace-replay/`).
  Not one of the original 3-item list -- added after the section 6
  methodology review, to get real evidence on "does the detector actually
  find real waste" rather than only having synthetic-load-generator
  evidence. Replayed Microsoft's real 2017 Philly production GPU cluster
  trace (552 machines, 117k jobs, real per-minute utilization from
  `nvidia-smi`) through the actual `waste_detector` code at real (not
  smoke-test-lowered) pilot thresholds, over a real 31-day window: 10,990
  idle, 279 over-provisioned, 12,568 fragmented, 6,848 recurring-pattern
  findings, and **23.0% of observed GPU-workload-hours flagged as some form
  of waste** (merged across categories, no double-counting) -- the first
  real-evidence answer to "will this reliably find >=15-20% waste,"
  previously only a synthetic-data claim. Two public Alibaba `clusterdata`
  releases were tried first and ruled out (`cluster-trace-gpu-v2023` turned
  out to be pure scheduling data with no utilization measurements at all;
  `cluster-trace-gpu-v2020` only has one aggregate figure per job's entire
  lifetime, not a real time series) before landing on Philly's genuinely
  per-minute `cluster_gpu_util`. See `testing/real-trace-replay/README.md`
  for the full method and `RESULTS.md` for the complete raw output. Caveats
  (see that README's last section): 2017 *training* workloads, not the
  bursty small-batch *inference* traffic this product targets; the section
  6 GPU_UTIL-as-FLOPS-proxy gap applies here identically; this validates
  detection logic only, not `ceiling.py`'s pricing/right-sizing math
  (Philly-era K80/P100 GPUs aren't in `capability.py`, and pricing wasn't
  attempted here); still not a substitute for the real 30-40%
  utilization-gain business thesis, which only a real customer's real
  traffic can prove.

## 2. What's in progress right now

Items 1 and 2 of the 3-item pre-pilot list are DONE (see section 1), plus
the extra real-trace-replay validation. Only item 3 remains, and its GPU
quota blocker is now CLEARED:

**Real managed-Kubernetes-cluster test (GKE)** — quota unblocked, cluster
built and live, two real bugs found and fixed, dcgm-exporter's fix not
yet re-verified on the live cluster (next step). `GPUS_ALL_REGIONS` (the
global aggregate quota) is now `grantedValue: 1` (approved instantly on
request), and `NVIDIA_T4_GPUS` in `us-central1` was already at `limit: 1`
by default -- enough for a single T4 GPU node right now, no more waiting.

Getting here required a real, multi-step debugging saga worth recording
precisely since it'll very likely recur on the next GCP project this
product is tested against:
1. The unified "Quotas & System Limits" console page (IAM & Admin →
   Quotas) kept returning empty/unusable results no matter how it was
   filtered (by Name, by Service, sorting + scrolling manually) --
   eventually root-caused via web search: **the console's quota UI does
   not support requesting an increase for a quota with zero prior usage**,
   and every GPU quota on a fresh project shows `usage: 0.0`. This wasn't
   a navigation mistake; the console path is a dead end for this exact
   situation.
2. The account was still on a free trial, which independently restricts
   GPU provisioning -- upgraded to a full (still-credit-backed) account
   first, though this alone didn't auto-raise the quota either.
3. The real path: `gcloud alpha quotas` (the Cloud Quotas API), run from
   Cloud Shell. Required enabling `cloudquotas.googleapis.com` (prompted
   automatically), and every call needed `--billing-project=<project>`
   explicitly -- ADC's implicit quota-project resolution doesn't work
   correctly in this context and errors otherwise.
4. `gcloud alpha quotas info list --service=compute.googleapis.com
   --filter="name:GPUS-ALL-REGIONS"` confirmed `quotaIncreaseEligibility:
   isEligible: true` for `GPUS-ALL-REGIONS-per-project` -- this is the
   quota ID that actually matters (the global aggregate; the per-model
   regional ones like `NVIDIA_T4_GPUS` were already non-zero by default
   and never needed a request).
5. `gcloud alpha quotas preferences create --service=compute.googleapis.com
   --project=<project> --billing-project=<project>
   --quota-id=GPUS-ALL-REGIONS-per-project --preferred-value=1
   --justification="..." --email=<contact> --preference-id=<id>` --
   **no `--dimensions` flag** for this quota specifically, since it's a
   pure project-level global quota with no regional dimension (passing
   `--dimensions=region=global` produces `INVALID_ARGUMENT: ... is not
   regional`). Submitted successfully, and approved within ~2 seconds
   (`stateDetail: Quota request approved to 1`) -- evidently an
   auto-approvable request at this size, not a manual-review case.
6. Check status anytime with `gcloud alpha quotas preferences describe
   <preference-id> --project=<project> --billing-project=<project>`
   (note: `describe` does NOT take `--service`/`--quota-id`, unlike
   `create` -- the preference ID alone is sufficient).

Runbook built and pushed: `testing/real-managed-cluster-test/README.md`
(+ `k8s/namespace.yaml`, `k8s/workload.yaml`). Single-GPU (no fragmentation
re-proof needed), GKE Standard mode with `gpu-driver-version=default` for
automatic NVIDIA driver install (no manual containerd/toolkit steps unlike
the vast.ai tests -- the actual point of testing a *managed* cluster), test
image pushed to Google Artifact Registry instead of GHCR (avoids the whole
fine-grained-vs-classic-PAT issue for this one test-only image; the
product's own 5 images still pull from GHCR as usual, same pull-secret
setup as before). Two things this test specifically targets that neither
prior test could: `persistence.enabled=true` against a real StorageClass
(both prior tests used `emptyDir` since bare vast.ai rentals have no
default StorageClass) -- verified by deleting the collector pod and
confirming DB row counts survive instead of resetting to 0; and real GKE
RBAC/Pod Security Admission behavior (flagged a likely real snag: GKE's
default Pod Security Standards can block dcgm-exporter's required
`SYS_ADMIN` capability on newer cluster versions -- the runbook documents
the exact namespace-label fix rather than assuming it away, since a real
pilot customer's own namespace policies could hit the identical wall).
Cluster stood up live-interactive, same pattern as the heterogeneous-SKU
test. T4 hit `GCE_STOCKOUT` twice (`us-central1-a`, `us-central1-c`, ~35min
wait each) and again on a third zone (`asia-south1-b`, cut short on user's
call that it was "taking too long") -- pivoted to L4/`g2-standard-4`
instead of continuing to chase T4 availability, which succeeded
immediately. Test workload pushed to Google Artifact Registry (as planned)
and deployed onto the GPU node; needed one extra IAM grant not anticipated
in the runbook -- the GKE node's default Compute Engine service account
needs `roles/artifactregistry.reader` explicitly (not automatic even for
a same-project registry), otherwise image pulls 403. Real default
StorageClass (`standard-rwo`) confirmed present, the actual point of this
test.

**Two real bugs found live, both are genuine pre-pilot findings, not
environment quirks:**
1. **Collector pod PVC-permission bug (confirmed fixed).** With
   `persistence.enabled=true` against a real dynamically-provisioned
   volume (GKE's PD CSI driver) for the first time ever in this project's
   testing, the collector pod's 5 containers -- each pinned to a distinct
   non-root UID (10001-10005) sharing subPath-remapped views of one PVC --
   all failed at startup with `sqlite3.OperationalError: unable to open
   database file`. Root cause: `emptyDir` (used in every prior test, since
   bare vast.ai rentals have no StorageClass) happens to come out writable
   by whatever UID mounts it regardless of runAsUser, so this was never
   caught before -- but a real cloud block-storage volume mounts owned by
   root with restrictive permissions, and needs a pod-level
   `securityContext.fsGroup` to be made writable by the 5 distinct UIDs at
   all. Fixed by adding `fsGroup: 10000` conditionally (only when
   `persistence.enabled`) in `collector.yaml`. Verified two ways: `helm
   template` with `persistence.enabled=true`/`false` (fsGroup
   present/absent as expected), and live -- pod went from 4/5
   CrashLoopBackOff to 5/5 Running after `helm upgrade`. Commit `f80b910`.
2. **dcgm-exporter GPU access, two iterations (first iteration wrong,
   second iteration current/unverified live).** First real evidence that
   this chart's dcgm-exporter deployment pattern, written and only ever
   tested against a bare containerd config with
   `default_runtime_name=nvidia` (vast.ai/k3s -- gives every container
   automatic driver/device access regardless of resource requests), does
   not work unmodified on a real managed cluster's standard
   Kubernetes-device-plugin model (GKE/EKS/AKS all work this way: a
   container gets driver library/device-file access ONLY if it explicitly
   requests `nvidia.com/gpu` as a resource).
   - **First fix (commit `9c582ce`, now known WRONG/incomplete):** added
     `resources.requests/limits: {nvidia.com/gpu: 1}` to dcgm-exporter.
     This did fix the immediate crash (`Failed to initialize NVML`), but
     introduced a worse problem live: `nvidia.com/gpu` claims are
     exclusive/competitive per node, so on this test's single-GPU node
     with the `tiny-model` workload pod already holding the one GPU,
     dcgm-exporter's identical claim had nothing left to allocate and sat
     `Pending` forever (`FailedScheduling ... Insufficient nvidia.com/gpu`,
     confirmed live, 5+ minutes, no preemption victim). A monitoring
     daemon that can only schedule when a node's GPU is idle defeats the
     product's actual purpose -- it needs to observe GPUs especially when
     they're busy.
   - **Second fix (commit `5fc6ce5`, pushed, NOT yet re-verified live --
     this is the current next step):** replaced the resource-request
     approach entirely with direct host-level access via hostPath mounts
     (`/dev`, and GKE COS's driver directory `/home/kubernetes/bin` →
     `/usr/local`, plus `LD_LIBRARY_PATH=/usr/local/nvidia/lib64`) and
     `privileged: true` -- the same approach NVIDIA's own GPU-Operator
     dcgm-exporter deployments use, and it doesn't compete with workloads
     for schedulable GPU count at all. The exact host paths were taken
     directly from GKE's own already-working `nvidia-gpu-device-plugin`
     pod's live config on this same cluster (`kubectl -n kube-system get
     pod nvidia-gpu-device-plugin-... -o yaml`) rather than guessed from
     memory. `helm lint`/`helm template` confirm the rendered YAML is
     well-formed (caught and fixed one real authoring bug of my own along
     the way: an accidental duplicate `env:` key in the container spec
     from a sloppy edit, which some YAML parsers silently resolve to only
     the last block -- would have silently dropped `NODE_NAME` and
     `DCGM_EXPORTER_KUBERNETES` if it had shipped). **Not yet applied to
     the live cluster or confirmed reaching `Running` -- next step is
     `helm upgrade` + `kubectl get pods` there.**

This session has no direct access to the user's real infrastructure (GCP
or vast.ai) — my role is interpreting real output the user pastes back and
debugging real problems as they come up, not running anything myself.

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
  `DCGM_EXPORTER_KUBERNETES=true` + `/var/lib/kubelet/pod-resources`
  hostPath mount for attribution (unchanged, correct). GPU/driver access
  itself is hostPath-based (`/dev`, GKE COS's `/home/kubernetes/bin` →
  `/usr/local`) + `privileged: true` as of commit `5fc6ce5` -- NOT a
  `nvidia.com/gpu` resource request, which was tried first (`9c582ce`) and
  found to make dcgm-exporter compete with real workloads for the node's
  schedulable GPU count. See section 2 for the full story.
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
   - **Heterogeneous SKU — DONE, PASSED, see section 1.** Kept the
     planning detail below for reference (what the runbook anticipated
     going in); section 1's entry has what actually happened, including
     the real bugs found along the way.
     Test kit built and pushed:
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
- **vast.ai only allows exposing ports at template-configuration time**,
  never to an already-running instance. This is why the heterogeneous-SKU
  runbook uses an SSH tunnel to reach node A's k3s API server (port 6443)
  from node B, instead of exposing that port directly -- also the better
  choice regardless, since it keeps the API server off the public internet
  entirely rather than relying on the join token alone as the security
  boundary. Don't use vast.ai's own native multi-node "Clusters" feature
  either -- it requires non-NATed same-subnet machines, not available for
  2 independently rented instances.
- **SSH between two independent vast.ai rentals has no shared trust**: a
  fresh SSH keypair generated on the joining node must have its pubkey
  manually appended to the other node's `authorized_keys` before a tunnel
  can open -- two separate rentals share no common trusted key by default,
  unlike two nodes provisioned together in the same account/cluster tooling.
- **k3s agent join "Node password rejected, duplicate hostname"**: vast.ai's
  default Ubuntu image gives every rented instance the identical hostname
  `ubuntu`, and k3s uses hostname as the default node name -- joining a
  second node without overriding this collides with the first. Fix: pass
  `K3S_NODE_NAME=<unique-name>` on the agent's join command.
- **containerd needs `default_runtime_name = "nvidia"`, not just a named
  `nvidia` runtime entry**: adding `[plugins.'io.containerd.cri.v1.runtime'.
  runtimes.nvidia]` to containerd's config makes the runtime available, but
  pods (including the NVIDIA device plugin itself) still run under plain
  `runc` unless `default_runtime_name` in the parent
  `[plugins.'io.containerd.cri.v1.runtime'.containerd]` block is also set
  to `"nvidia"`. Symptom without this: device plugin logs "Incompatible
  strategy detected auto" / NVML init failure. Must be set on **every**
  node independently -- missing it on just one (e.g. the second node
  joined) reproduces the identical failure there even after fixing the
  first.
- **k3s's `INSTALL_K3S_EXEC` CLI flags (`--node-ip`, `--tls-san`,
  `--flannel-iface`) render into the systemd service's `ExecStart=` line**
  (a multi-line, backslash-continued command in
  `/etc/systemd/system/k3s-agent.service`), **not** into
  `k3s-agent.service.env`. That `.env` file only holds simple env-var
  settings (`K3S_URL`, `K3S_TOKEN`, `K3S_NODE_NAME`) -- checking it for
  CLI-flag values will always come up empty even when they're set
  correctly. Check the actual service file's `ExecStart=` line instead.
- **NVML "Driver/library version mismatch"**: a silent background driver
  package update (`unattended-upgrades`) can change the on-disk userspace
  NVIDIA libraries without reloading the already-loaded kernel module,
  so `nvidia-smi` starts failing on a previously-healthy box with no
  obvious trigger. Confirm via `/proc/driver/nvidia/version` (on-disk)
  vs. the NVML library's own reported version disagreeing. Fix: a full
  `sudo reboot` -- both kernel module and userspace libraries load fresh
  from disk and are guaranteed to match afterward. k3s/Tailscale/Docker
  all auto-recovered on their own after reboot; no need to rejoin nodes.
- **GHCR + fine-grained GitHub PATs don't reliably work for image pulls**:
  a fine-grained PAT can succeed at `docker login` (auth itself is fine)
  and still fail `docker pull`/`ImagePullBackOff` with `403 Forbidden` --
  this is a known, longstanding GHCR authorization gap specific to
  fine-grained tokens, even with the right permissions checked. A
  **classic** PAT with `repo` + `read:packages` scopes is the reliable
  path for pulling; confirmed empirically (same account, fine-grained
  token failed pull, classic token succeeded immediately after).
- **GHCR pushes need `write:packages` specifically**: a classic PAT scoped
  only for pulling (`read:packages`) authenticates fine via `docker login`
  but fails `docker push` with `denied: permission_denied: The token
  provided does not match expected scopes.` Add `write:packages` to the
  same token (editing an existing classic PAT's scopes on GitHub keeps the
  token string unchanged -- no need to regenerate/re-login anywhere else
  that already uses it) before pushing a locally-built image.
- **Downloading a Git-LFS-tracked file in this environment**: a plain
  `git clone` (even via the session's anonymous public-repo read lane)
  only fetches the ~100-byte LFS pointer stub, never the real file content
  -- that lane explicitly does not serve LFS objects, and no `git-lfs`
  binary is installed. Fetch the real content directly via GitHub's
  LFS-resolving media CDN instead, which is a plain HTTPS GET (no LFS
  client needed): `https://media.githubusercontent.com/media/<owner>/<repo>/<branch>/<path>`.
  Verify the download against the pointer's `sha256 oid` (visible in the
  pointer stub's plaintext content) before trusting it.
- **`helm` needs `KUBECONFIG=/etc/rancher/k3s/k3s.yaml` explicitly
  exported** -- only the k3s-provided `kubectl` wrapper (`k3s kubectl`)
  knows to default to that path; plain `helm` (a separate binary) does
  not, and fails with "cluster unreachable: localhost:8080" without it.
  This needs re-exporting in every fresh shell/reconnected SSH session
  (doesn't persist unless added to `~/.bashrc`).
- **GCP Console's Quotas UI cannot request an increase for a zero-usage
  quota** -- on a fresh project every GPU quota shows `usage: 0.0`, and no
  amount of correct filtering (by Name, by Service, sorting + scrolling)
  makes the console's edit/increase flow work for it; this isn't a
  navigation mistake, it's a real console limitation. The actual working
  path is the `gcloud alpha quotas` CLI (Cloud Quotas API) instead -- see
  section 2's GKE entry for the exact working command sequence (enable
  `cloudquotas.googleapis.com`, always pass `--billing-project=<project>`
  explicitly or every call errors on ADC quota-project resolution, find
  the real `quotaId` via `quotas info list` before guessing at
  `preferences create`'s flags, and don't pass `--dimensions` for a
  quota that turns out to be a pure project-level global one). Also: a
  free-trial (not-yet-upgraded) GCP account independently restricts GPU
  provisioning regardless of quota values -- upgrade first if quota
  requests seem to go nowhere.

## 6. Methodology risk found via math review (not a code bug -- nothing changed)

User asked, before the managed-cluster test, to sanity-check the detection/
recommendation math itself: would this reliably find real waste, and is the
right-sizing math actually correct? Reviewed `idle.py`, `over_provisioning.py`,
`fragmentation.py`, `patterns.py`, `ceiling.py`, `estimator.py` line by line.
No code changed -- this was requested as read-only analysis.

- **No code can promise a specific "at least X% waste" number** -- that's a
  property of the customer's real usage, not the detector's logic. What's
  checkable is whether thresholds are well-calibrated: they're deliberately
  conservative (idle needs 4 unbroken hours at <=2% util; over-provisioned
  needs peak <=30% across 24+ observed hours), which biases toward missing
  marginal waste rather than false-flagging healthy workloads. `min_coverage_
  ratio=0.8` is also a real, live risk to this, not just theoretical: it's
  exactly the mechanism that silently zeroed out every finding during this
  session's real multi-node scrape bug (section 1/5) -- any future telemetry
  gap (network blip, exporter restart) narrows what gets reported and never
  inflates it.
- **The bigger finding: `ceiling.py`'s right-sizing math treats
  `DCGM_FI_DEV_GPU_UTIL` as if it were linearly proportional to FLOPS
  actually consumed** (`normalizer.py`'s `_effective_tflops`: `utilization_pct
  / 100 * fp16_tflops`), but NVIDIA's own definition of that metric is "%
  of the last sample period during which *any* kernel was executing" -- a
  binary time-occupancy signal, not a compute-throughput one. A kernel using
  1 of an A100's 108 SMs reports the same number as one saturating all 108.
  This matters most for exactly the workload class this product targets:
  bursty, small-batch inference (`idle.py`'s own docstring says as much) --
  frequent small kernel launches keep occupancy high while real FLOPS usage
  stays low. Worked example: an A100 workload showing 60% peak GPU_UTIL
  computes `required_fp16_tflops = (312*0.60)/0.70 = 267.4` -- close to the
  A100 itself, so no meaningful downsize gets recommended, even if the
  workload's *real* compute footprint would fit comfortably on a T4. The
  error isn't one-directional (memory-bound and kernel-launch-bound kernels
  both inflate the proxy; it happens to track real FLOPS reasonably well for
  dense tensor-core-saturating batch jobs), so no single safety margin fixes
  it uniformly. Of the three detectors: `idle.py` is low-risk (near-zero
  occupancy and near-zero FLOPS agree at the extreme); fragmentation's $
  estimate under-states reclaimable capacity for bursty inference (errs
  toward under-promising); over-provisioned + `ceiling.py`'s SKU
  recommendation is the highest-stakes exposure, since it's the only one
  that names a specific replacement GPU a customer might actually provision.
  Possible real fix: DCGM's profiling counters (`DCGM_FI_PROF_SM_ACTIVE`,
  `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE`) get meaningfully closer to real compute
  intensity than plain `GPU_UTIL` -- currently not scraped at all
  (`telemetry-collector/correlator.py`'s `_METRIC_FIELD_MAP` only has
  `GPU_UTIL`/`FB_USED`/`FB_FREE`/`POWER_USAGE`/`SM_CLOCK`). Real trade-off,
  not a clean win: these profiling counters aren't available on all real
  clusters (some cloud/vGPU/virtualized setups restrict them, historically
  gated behind elevated permissions), so a fix would need a dual-mode
  fallback to plain `GPU_UTIL` rather than a straight swap; `SM_ACTIVE`
  narrows the gap but still doesn't capture per-cycle ALU/tensor throughput
  within an active SM, and `PIPE_TENSOR_ACTIVE` is itself workload-shape-
  dependent (says nothing about attention softmax, activations, data
  movement). Not done as part of this session -- flagged as the most
  important open question before trusting `ceiling.py`'s recommendations in
  front of a real pilot customer; the near-term cheaper mitigation is being
  explicit (in customer-facing docs, not just code comments) that
  over-provisioned right-sizing suggestions are directional and worth a
  staged/canary rollout before fully acting on them.
- **Two smaller inconsistencies, not bugs**: (1) `savings_estimator.config.
  min_finding_confidence=0.7` is currently dead weight -- every finding that
  reaches it already has confidence >= `waste_detector.config.min_coverage_
  ratio=0.8` (confidence is the average of per-row coverage values already
  individually >=0.8), so this second gate never actually excludes anything
  at current defaults; only matters if `min_coverage_ratio` is ever lowered
  below 0.7 without noticing this dependency. (2) `patterns.py`'s monthly
  projection hardcodes `_DAYS_PER_MONTH = 30.0` while `over_provisioned`/
  `fragmented` use the configurable `hours_per_month` (default 730 ≈ 30.4
  days) -- ~1-2% drift if a customer overrides `hours_per_month`.
- Everything else traced (rate-delta arithmetic, floor-at-zero on negative
  savings, the idle-observed-vs-projected `basis` distinction) is
  arithmetically sound and honestly labeled. The real gap is the metric
  choice underneath the arithmetic, not the arithmetic itself.

## 7. What I (the assistant) have NOT done

- Not rented, accessed, or run anything on the user's actual vast.ai
  instance — this session has no access to their real infrastructure.
- Not started the real-managed-cluster (GKE) test work.
- Not opened any PR beyond PR #1 (registry/CI fix merge).
- Not made any code changes based on the section 6 methodology review --
  explicitly requested as read-only analysis.
- **Not confirmed: THREE GitHub PATs have now been pasted into chat in
  plaintext across this project's sessions** -- two during the
  heterogeneous-SKU test's live debugging (a fine-grained token and,
  separately, a classic token used after the fine-grained one hit the GHCR
  pull gap above), and a third classic token pasted during the
  real-managed-cluster (GKE) test's live debugging, used in a `git clone`
  URL when Cloud Shell's terminal wouldn't accept interactive input for
  the credential prompt. Flagged to the user each time as compromised and
  recommended for rotation (GitHub → Settings → Developer settings →
  Personal access tokens), but never confirmed as actually done for any of
  the three. **A future session should re-raise this if it comes up
  again** -- treat all three as still-live exposed credentials until the
  user confirms otherwise. This is now a recurring pattern (three
  incidents across two separate live-debugging sessions) worth being
  extra vigilant about: whenever a stuck/uncooperative terminal makes an
  interactive credential prompt (SSH, git, docker login) fail, the safer
  fallback is `--password-stdin`-style piping or a fresh terminal/tab
  reconnect, not embedding the raw token in a command that then gets
  pasted back into this chat for review.
