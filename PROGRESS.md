# PROGRESS.md — handoff / context-save

Written as a checkpoint before a context compaction. Purpose: let a fresh
session (or a fresh me) pick this project back up without re-deriving
everything from scratch. Update or delete this file once it's stale —
it's a scratchpad, not permanent documentation.

Branch this was written on: `claude/cost-optimization-saas-telemetry-w4zbhb`
(the repo's actual default branch). **Since 2026-09-29, work continues on
`claude/agent-skills-setup-fno99z`**, which was fast-forwarded from it and
holds everything in this file plus the market report, the fragmentation
fixes and the multi-GPU signal below; `...-w4zbhb` does not have those.

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
- **Real managed-Kubernetes-cluster test: COMPLETE and PASSED**
  (`testing/real-managed-cluster-test/`). Ran on a real GKE Standard
  cluster (L4 GPU, `g2-standard-4`, `asia-south1-b` -- T4 hit
  `GCE_STOCKOUT` in 3 zones first). Three real product bugs found and
  fixed live (dcgm-exporter GPU access competing with workloads for
  schedulable GPU count, dcgm-exporter pod attribution silently failing
  on GKE's device-ID format, collector PVC-permission failure) -- full
  detail in section 2. Real `over_provisioned` finding fired
  (`gke-gpu-optimizer-test-default-pool-330304fd-jggp`, GPU 0,
  `tiny-model`, 4.0% peak) at real thresholds; real PVC persistence
  confirmed surviving a forced collector-pod deletion (23 rollup rows
  before and after, against a real `standard-rwo` PD CSI volume, not
  `emptyDir`); real RBAC confirmed clean under GKE's own enforcement
  (kube-state-metrics: `"Communication with server successful"`, zero
  permission errors). This closes item 3 of the 3-item pre-pilot
  technical list -- **all 3 items are now done.**
- **Real-trace replay: COMPLETE and PASSED** (`testing/real-trace-replay/`).
  Not one of the original 3-item list -- added after the section 6
  methodology review, to get real evidence on "does the detector actually
  find real waste" rather than only having synthetic-load-generator
  evidence. Replayed Microsoft's real 2017 Philly production GPU cluster
  trace (552 machines, 117k jobs, real per-minute utilization from
  `nvidia-smi`) through the actual `waste_detector` code at real (not
  smoke-test-lowered) pilot thresholds, over a real 31-day window: 10,990
  idle, 279 over-provisioned, 5,718 fragmented, 6,848 recurring-pattern
  findings, and **16.7% of observed GPU-workload-hours flagged as
  actionable waste** (merged across categories, no double-counting; 14.7%
  without the unverified fragmentation candidates). Separately, the
  visibility-only multi-GPU signal shows **12.7%** of GPU-hours as
  releasable capacity (7.0% not already flagged) -- an upper bound, never
  added to the 16.7%. The "no recommendation yet" tier adds 13.4% of
  GPU-hours below the 70% target (2.5% of capacity), also separate.
  **Use 16.7% (floor 14.7%) when quoting Philly.**
  **Total waste, all tiers in one unit** (GPU capacity unused below the
  70% target; `summarize.py` with `rollups.pkl`): total waste **27.0% of
  capacity**, of which **23.0% detected (85%)** -- actionable 11.1%,
  multi-GPU review 9.4%, no recommendation 2.5% -- and 4.0% (15%) in
  low-coverage hours the detectors skip on purpose; 0.0% undetected in
  checked hours. Raw unused capacity incl. slack above 70%: 51.3%.
  The 23.0% of *capacity* here is unrelated to the old 23.0% of
  *GPU-hours* -- don't mix them up with prospects. Suggested claim: "on
  Microsoft's real Philly cluster, 23% of GPU capacity went unused below
  an efficient-use target; the product classified all of it -- about
  half with an actionable recommendation, a third flagged for review,
  the rest measured without a recommendation yet."
  History: originally reported as 23.0% with 12,568 fragmented findings;
  17.1% after fragmentation stopped flagging multi-GPU jobs; 16.7% after
  the per-workload mislabel fix (all 2026-10-01, see the fragmentation
  entries below) -- the first
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
- **Azure inference-trace replay: COMPLETE and PASSED**
  (`testing/azure-inference-trace-replay/`). Also not one of the original
  3-item list -- closes the one caveat the Philly replay above still
  carried (2017 *training* workloads, not this product's bursty
  small-batch *inference* target). Replayed a real November 2023 Azure
  production LLM-inference request-arrival trace (19,366 real requests,
  `microsoft/AzurePublicDataset`, CC-BY) at real (1.0x) speed against a
  real GPU-backed inference server on a real vast.ai/k3s single-GPU
  cluster (RTX 4060 Ti) -- real request timing and real per-request
  token sizes driving genuinely real DCGM utilization, not
  `load_generator.py`'s own randomization. 100% request success; fired a
  real `over_provisioned` finding (confidence 1.0, peak utilization
  11.0%) driven entirely by that real traffic. See
  `testing/azure-inference-trace-replay/RESULTS.md` for full output.
  **Three real bugs found and fixed live before this succeeded**, all
  worth remembering for future live GPU tests: (1) the shared stand-in
  inference server (`fragmentation-and-load-test/server.py`) had no
  synchronization around its one shared PyTorch CUDA model instance --
  FastAPI's per-request thread-pool workers called `.generate()`
  concurrently from different threads, and a burst of real concurrent
  requests crashed the process with `CUDA error: device-side assert
  triggered`, which poisons the CUDA context for every request
  afterward until the pod restarts, not just the overlapping ones;
  fixed with a `threading.Lock()` (commit `d64a82e`) -- this was a
  latent bug in a test artifact every live GPU test in this project
  reuses, uncaught until real burst timing (further compressed by an
  initial `--speed 50` sanity check) produced truly simultaneous
  requests for the first time; (2) the replay script clipped
  ContextTokens and GeneratedTokens independently against separate
  limits, so a request needing both a long prompt and more than a
  token or two of generation could still exceed the model's real total
  position budget -- GPT-2's position embeddings support exactly 1024
  total positions covering *both* the prompt and every generated token
  combined, so a 1024-token prompt plus even one more generated token
  needs position 1024, out of bounds, the identical CUDA crash; isolated
  via a sequential no-concurrency diagnostic (800 tokens + 16 new
  tokens succeeded, exactly 1024 + 16 failed every time, ruling out bug
  #1 as this specific cause) and fixed by computing each row's context
  budget as `max_context_tokens - max_new_tokens` (commit `a6ae78e`);
  (3) the GKE test's dcgm-exporter pod-attribution fix
  (`DCGM_EXPORTER_KUBERNETES_GPU_ID_TYPE=device-name`, commit `64a4033`)
  had been hardcoded unconditionally into the shared chart, which broke
  attribution the identical silent way in the opposite direction on
  this test's standard NVIDIA k8s-device-plugin cluster (vast.ai/k3s
  reports device IDs in UUID form, dcgm-exporter's own default
  assumption, and forcing device-name there made the match fail
  instead) -- every GPU sample came back with zero pod/namespace label,
  same symptom as the original GKE bug, opposite root cause. Fixed by
  making it a `dcgmExporter.kubernetesGpuIdType` values.yaml field
  (empty/unset by default, matching dcgm-exporter's own UUID-assuming
  default), only set explicitly for GKE now (commit `349bd68`, also
  updated `testing/real-managed-cluster-test/README.md`'s `helm install`
  command to pass it explicitly since it's no longer the chart-wide
  default -- **if re-running the GKE test, don't drop that flag**).

  A **4th real bug** was found just after the test itself already
  passed, while trying to pull the live dashboard report for the
  record: `generate-report` (the chart's own install NOTES document it
  as a supported feature, "generate a standalone HTML file to share")
  fails immediately with `OSError: [Errno 30] Read-only file system`
  the moment it's actually run -- `readOnlyRootFilesystem: true` on the
  dashboard container, combined with zero volumes mounted for it at
  all (confirmed live: neither the documented default path nor `/tmp`
  had anywhere writable), means the command could never have worked in
  any real deployment of this chart, ever. Fixed (commit `eab36ee`)
  with a small `dashboard-tmp` emptyDir mounted at `/tmp` specifically
  for this one container (kept separate from the existing read-only
  savings-estimator data mount, rather than loosening
  `readOnlyRootFilesystem` itself) plus
  `REPORT_OUTPUT_PATH=/tmp/report.html`; updated the install NOTES'
  documented `kubectl cp` path to match. Confirmed working live:
  `generate-report` succeeded and the file copied out cleanly.

  **Real operational gotcha, not itself a bug**, hit applying that
  4th fix: it required a `helm upgrade`, which restarts the collector
  pod -- and since this test deliberately used
  `persistence.enabled=false` (emptyDir, matching every prior
  non-GKE test; this test wasn't exercising PVC persistence, the GKE
  test already covers that), the restart reset the live findings/
  savings-estimates database to empty. The `over_provisioned` finding
  from the real run was still fully captured in `RESULTS.md`/this file
  from before the restart, so nothing about the test's actual result
  was lost -- but the live dashboard could no longer show it, and
  there was no live capture of what `savings-estimator`'s specific ₹
  pricing/right-sizing recommendation for that finding would have been
  (that data was never queried before the restart wiped it). **Lesson
  for next time**: query and record `savings_estimates`, not just
  `waste_findings`, for the record immediately once a finding fires --
  don't assume there's time to come back to it later on a
  non-persistent deployment.

- **Market research, competition & unit economics report: DONE (2026-09-29
  to 2026-10-01).** `reports/gpu_waste_detection_market_research.pdf`,
  built by `reports/build_market_report.py` (reportlab; edit the script and
  re-run to change numbers -- every figure is tagged [S] sourced or [A]
  assumption, assumptions ledger in section 8 of the PDF). 14 pages:
  market context, TAM/SAM/SOM (India + global + per region), competitor
  table (CAST AI, ScaleOps, Datadog GPU Monitoring, IBM Kubecost/OpenCost,
  PerfectScale/DoiT, NVIDIA Run:ai/KAI, DIY DCGM+Grafana, Indian GPU-cloud
  consoles), unit economics (solo-founder), international expansion,
  India-only vs India+international comparison, and a reconciliation with
  the founder's earlier September SMB market study. Key numbers are in
  section 8 of this file.
- **Fragmentation honesty fixes ("step A"): DONE (2026-10-01, commit
  62142d2).** Prompted by a critique that fragmentation doesn't prove
  consolidation is possible (true -- the module's own docstring said
  bin-packing was out of scope). Verified against the code before
  changing anything; all three code claims reproduced:
  1. Multi-GPU jobs weren't fully excluded: the only check was "2+
     distinct workloads among the underused GPUs", so a 4-GPU training
     job next to one small model got "consolidate" findings on all 4 of
     its GPUs. **Fix:** any workload on >1 GPU in an hour is excluded
     from fragmentation (rollups carry workload, not pod, so a Deployment
     whose replicas each hold one GPU is excluded too -- deliberately
     conservative).
  2. Fragmentation ₹ = (1 - utilization) x 50% per GPU with no fit check.
     **Fix:** finding detail says "consolidation candidate, needs engineer
     review" and lists what wasn't checked (memory fit, combined compute,
     cluster GPU sharing); recommended_action now "review whether this
     workload can share a GPU ... (needs time-slicing, MPS, or MIG)";
     methodology says it's an upper bound that may be zero.
  3. The dashboard headline summed every projected estimate, so a GPU
     flagged both over-provisioned and fragmented (alternative actions)
     was counted twice. **Fix:** headline counts each physical GPU once at
     its largest projected estimate, with a note when category totals add
     up to more.
  Philly re-run: 23.0% -> 17.1%. Also fixed `replay.py` crashing at the
  end of a 10-minute run because it didn't create its output directory.
- **Multi-GPU "could use fewer GPUs" signal ("option B") + fragmentation
  mislabel fix: DONE (2026-10-01).** Step A dropped real multi-GPU
  underuse along with the bad advice (multi-GPU GPU-hours averaging 2-50%
  that nothing flags = 22.2% of Philly GPU-hours). New category
  `multi_gpu_oversized` (`waste-detector/src/waste_detector/multi_gpu.py`):
  per hour a workload holds N>1 GPUs, GPUs needed = ceil(sum of hourly-avg
  utilization / 70%); if fewer than N for a 4h+ streak, every GPU of the
  job gets a finding with metric_value = smallest releasable fraction
  across the streak. **Sized on averages on purpose** (founder chose this
  after seeing the prototype): peak-based sizing found +0.4 pts on Philly,
  average-based +6.6 -- so it's an upper bound. Priced by savings-estimator
  on a new `visibility_upper_bound` basis (fraction x rate x
  MULTI_GPU_CAPTURE_FRACTION 0.5 x 730h); the dashboard keeps that basis
  out of both headline totals, shows it as its own card only when
  present, and sorts its rows after actionable findings. Helm values:
  `wasteDetector.multiGpuTargetUtilizationPct` (70),
  `wasteDetector.multiGpuMinStreakHours` (4; smoke-test 1),
  `savingsEstimator.multiGpuCaptureFraction` (0.5).
  **Mislabel fix (pre-existing bug found during verification):**
  fragmentation findings were keyed by GPU only and labeled with the first
  row's workload, so a GPU that switched jobs mid-streak charged the first
  job for every hour (6,419 Philly GPU-hours). Now keyed by GPU and
  workload. Philly: 17.1% -> 16.7%; multi-GPU signal 12.7% (7.0% new).
  `testing/real-trace-replay/replay.py` now saves `rollups.pkl` and
  `rerun_detectors.py` re-runs every detector on it in seconds.
- **"Below actionable recommendations" tier: DONE (2026-10-01).** Founder's
  requirement: *never detect less waste just because there's no correct
  recommendation for it* -- detect it and classify it below the actionable
  findings. New `waste-detector/src/waste_detector/unrecommended.py` runs
  last (after the actionable detectors and the multi-GPU signal) and
  reports every GPU-hour averaging below `UNDERUTILIZED_TARGET_PCT` (70%,
  same as savings-estimator's SLA ceiling) that no finding already covers:
  `underutilized` (attributed) and `unattributed_gpu_time` (GPU time with
  no Kubernetes pod -- previously dropped by every detector).
  metric_value = average shortfall below target as a fraction of the GPU.
  Recurring-pattern findings only count as covering their own hour of
  day. Priced as *observed* cost on a new `detected_no_recommendation`
  basis (rate x shortfall x hours, not projected). Dashboard: new "Below
  actionable recommendations" section holding this tier and the
  multi-GPU upper bound (moved out of the headline row); never added to
  either headline figure; rows sort after actionable findings. Also
  fixed observed tier amounts being labeled "/mo". Helm:
  `wasteDetector.underutilizedTargetPct` (70),
  `wasteDetector.underutilizedMinRunHours` (1). Philly: 58,491 findings,
  13.4% of GPU-hours, 2.5% of capacity below target (median run 1h).
  **Tiers now, in order of trust:** (1) actionable: idle, over-provisioned,
  recurring pattern, fragmentation candidates -> headline figures;
  (2) multi-GPU "fewer GPUs" upper bound (projected/month); (3) detected
  waste with no recommendation (observed). Tiers 2-3 never enter a
  headline.
- **Right-sizing mini-test (2026-10-04): FAIL -- found a real flaw in
  `ceiling.py`.** `testing/rightsizing-mini-test/` (results + full
  `compare.py` output in `results/`). ~$0.30 total: RTX 3090 on vast.ai,
  free T4 on Colab. Same model (Qwen2.5-1.5B-Instruct, vLLM 0.8.5.post1,
  fp16, V0 engine, ~12 GB each), same 15 min of the Azure conv trace at
  keep 0.05 (237 requests each, 0 errors each).
  - 3090: mean busy 21.4%, product-style peak (30 s sampling) 75%, p95
    2.21 s. T4: mean busy 54.3%, peak 97%, p95 5.16 s. Throughput 1.00x.
  - **Product's assumption (busy % scales by FP16 TFLOPS ratio, 1.09x)
    predicted ~23% on the T4; measured 54% (2.54x), close to the
    memory-speed ratio (2.92x).** Latency p50/p95/p99 rose 2.3x (FAIL vs
    the 1.5x bar). Capacity held: same throughput, no queueing, no errors.
  - Finding 2: at this light load (~0.26 req/s) the 3090's 30-s-sampled
    peak was 71-75%, so `over_provisioning.py` (peak <= 30%) would never
    fire: GPU busy % reads high whenever any request is in flight. For
    LLM serving the right-sizing path is mostly unreachable (safe, but this
    waste only lands in the no-recommendation tier). At that peak
    `ceiling.py` would pick an L4 (121 TFLOPS but 300 GB/s -- slower memory
    than the T4), so the hypothetical recommendation would very likely fail
    the same way.
  - Not a product recommendation tested literally (the product wouldn't
    flag this load); it tests the assumption every right-sizing number
    rests on. One model, 15 min, two hosts, single run.
  - Fix built the same day (section 4); out-of-sample A10 re-test pending.

## 2. What's in progress right now

**All 3 items of the pre-pilot list are now DONE, including item 3
(real managed-Kubernetes-cluster / GKE test) — see below.** Nothing is
actively blocked; next real work is either the genuine design-partner
pilot (section 4 item 3) or GKE cluster teardown to stop billing.

The Azure inference-trace replay test (section 1) is also now DONE,
PASSED, four real bugs found and fixed, **vast.ai instance torn down**.

**Real managed-Kubernetes-cluster test (GKE) — DONE, PASSED.**
`GPUS_ALL_REGIONS` (the global aggregate quota) is now `grantedValue: 1`
(approved instantly on request), and `NVIDIA_T4_GPUS` in `us-central1` was
already at `limit: 1` by default.

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

**Three real bugs found live, all genuine pre-pilot findings, not
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
   - **Second fix (commit `5fc6ce5`, then `09692a4`, CONFIRMED WORKING
     live):** replaced the resource-request approach entirely with direct
     host-level access via hostPath mounts (`/dev`, plus
     `privileged: true`) and `LD_LIBRARY_PATH` pointed at the mounted
     driver libs -- the same approach NVIDIA's own GPU-Operator
     dcgm-exporter deployments use, and it doesn't compete with workloads
     for schedulable GPU count at all. The exact host paths were taken
     directly from GKE's own already-working `nvidia-gpu-device-plugin`
     pod's live config on this same cluster (`kubectl -n kube-system get
     pod nvidia-gpu-device-plugin-... -o yaml`) rather than guessed from
     memory. Caught and fixed two real authoring bugs of my own along the
     way, both before ever reaching the live cluster: (a) an accidental
     duplicate `env:` key in the container spec from a sloppy edit (some
     YAML parsers silently resolve this to only the last block -- would
     have silently dropped `NODE_NAME` and `DCGM_EXPORTER_KUBERNETES` if
     it had shipped); (b) mounting the ENTIRE hostPath
     `/home/kubernetes/bin` onto the container's `/usr/local` clobbers the
     whole `/usr/local` tree baked into the dcgm-exporter image itself,
     hiding `/usr/local/dcgm/dcgm-exporter-entrypoint.sh` and failing live
     with `RunContainerError: ... no such file or directory` -- GKE's own
     device-plugin pod gets away with this exact mount only because its
     base image has nothing of its own under `/usr/local`; dcgm-exporter's
     does. Fixed (commit `09692a4`) by narrowing the mount to just the
     driver installer's own subdirectory
     (`/home/kubernetes/bin/nvidia` → `/usr/local/nvidia`), leaving the
     image's own `/usr/local/dcgm` untouched. Confirmed live: pod reached
     `1/1 Running`, logs showed `"DCGM successfully initialized!"` and
     `"Kubernetes metrics collection enabled!"`.
3. **dcgm-exporter pod attribution silently failing (confirmed fixed,
   commit `64a4033`).** Even with the above fix and DCGM successfully
   initialized, every GPU sample came through the pipeline as
   `unattributed` (`telemetry-collector`'s own per-cycle log showed
   `"attributed": 0, "unattributed": 1` every cycle) despite the
   workload pod actually running on that exact node/GPU. Root-caused by
   querying dcgm-exporter's own `/metrics` endpoint directly: the
   `DCGM_FI_DEV_GPU_UTIL` sample had `device="nvidia0"` but no `pod=`/
   `namespace=` label at all, and no error was logged anywhere. Cause:
   `DCGM_EXPORTER_KUBERNETES=true` alone assumes device IDs from the
   kubelet's pod-resources API come in full-UUID form
   (`GPU-a85a9bb4-...`) by default, but GKE's device plugin reports
   device-name form instead (`nvidia0`) -- the ID-matching silently fails
   with no error, and no pod/namespace label is ever attached. Fixed by
   setting `DCGM_EXPORTER_KUBERNETES_GPU_ID_TYPE=device-name`. Confirmed
   live: the same raw `/metrics` query afterward showed
   `container="server", namespace="inference", pod="tiny-model-..."` on
   the GPU sample.

**Final result: real `over_provisioned` finding fired** on the actual
GKE node (`gke-gpu-optimizer-test-default-pool-330304fd-jggp`), GPU 0,
workload `tiny-model`, peak utilization `4.0%` (real, not lowered,
`overProvisionThresholdPct` comparison via `values-smoke-test.yaml`'s
1-hour observation window). **PVC persistence confirmed**: rollup row
count was 23 both immediately before and immediately after force-deleting
the collector pod -- real cloud block storage (`standard-rwo`) survives
pod recreation, unlike the `emptyDir` used in both prior tests. **Real
RBAC confirmed**: kube-state-metrics' own logs showed
`"Communication with server successful"` against real GKE
(`v1.35.8-gke.1225000`) with zero permission errors, under the chart's
get/list/watch-only ClusterRole.

**Unrelated gotcha hit twice mid-test: the Cloud Shell VM itself
restarted** (independent of anything in this test), each time silently
killing whatever client-side process was running in that terminal --
first a `kubectl port-forward`, later the `load_generator.py` process
driving traffic, truncating its run and leaving a gap in rollup
`coverage_ratio` right in the hourly bucket the detectors most needed
intact. Fixed properly rather than just restarted: moved load generation
into the cluster itself as a real Kubernetes Job
(`testing/real-managed-cluster-test/k8s/load-generator-job.yaml`, script
content via a `ConfigMap`, no port-forward needed since it reaches
`tiny-model.inference.svc.cluster.local:8000` over in-cluster DNS
directly) -- this has no dependency on any client shell staying connected
at all, so it can't be silently truncated by a Cloud Shell restart again.

**Teardown: COMPLETE.** Deleted the `inference` namespace, `helm
uninstall`ed the release, deleted the GKE cluster, and deleted the
Artifact Registry `test-images` repo. One extra real finding here worth
recording: `gcloud container clusters list` at teardown time turned up a
**second, orphaned cluster** (`gpu-optimizer-test` in `us-central1-c`,
`STATUS: ERROR`) -- a leftover from one of the earlier T4 `GCE_STOCKOUT`
attempts that silently failed to fully provision and was never cleaned
up, sitting there consuming quota/possibly billing the whole time
unnoticed. Deleted it too. **Lesson for next time: always run `gcloud
container clusters list` (not just check the one cluster you think you
created) before declaring teardown done** -- a failed `clusters create`
attempt can still leave a real billable resource behind even though the
command itself appeared to just fail and move on. Confirmed fully clean
afterward: `gcloud container clusters list` and `gcloud compute instances
list` both return zero items project-wide.

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
  multi-GPU oversized (`multi_gpu.py`, visibility only):
  `multi_gpu_target_utilization_pct=70.0`, `multi_gpu_min_streak_hours=4`.
- Visibility-only pricing basis: `savings-estimator/src/savings_estimator/estimate.py`
  (`BASIS_VISIBILITY_UPPER_BOUND`); headline dedupe and the separate
  figure: `dashboard/src/dashboard/aggregator.py`.

**Market report:** `reports/build_market_report.py` (source of truth) ->
`reports/gpu_waste_detection_market_research.pdf`. Fonts: DejaVu Sans
(Helvetica can't render ₹).

**Philly replay:** `testing/real-trace-replay/replay.py` (full run, saves
`rollups.pkl`), `rerun_detectors.py` (detectors only, from saved rollups),
`summarize.py` (flagged %, plus the separate multi-GPU figure),
`RESULTS.md` (every run's raw output and the 2026-10-01 analysis).

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
  `DCGM_EXPORTER_KUBERNETES=true` + `DCGM_EXPORTER_KUBERNETES_GPU_ID_TYPE=
  device-name` (the latter required on GKE specifically -- see section 2's
  3rd bug, commit `64a4033`) + `/var/lib/kubelet/pod-resources` hostPath
  mount for attribution. GPU/driver access itself is hostPath-based
  (`/dev`, GKE COS's `/home/kubernetes/bin/nvidia` → `/usr/local/nvidia`)
  + `privileged: true` as of commits `5fc6ce5`/`09692a4` -- NOT a
  `nvidia.com/gpu` resource request, which was tried first (`9c582ce`) and
  found to make dcgm-exporter compete with real workloads for the node's
  schedulable GPU count. All three confirmed working live on GKE with a
  real attributed finding. See section 2 for the full story.
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
   - **Real managed-Kubernetes-cluster test — DONE, PASSED, see section 2
     for the full live-debugging story (3 real bugs found and fixed:
     dcgm-exporter GPU access, dcgm-exporter pod attribution, collector
     PVC permissions).** Ran on GKE (L4/`g2-standard-4`, `asia-south1-b` --
     T4 hit `GCE_STOCKOUT` in 3 different zones first). Real
     `over_provisioned` finding fired at real thresholds; real PVC
     persistence survived a forced pod deletion (23 rows before and
     after); real RBAC confirmed clean under GKE's own enforcement.
3. **Genuine design-partner pilot** — only after the above two. Explicitly
   discussed and agreed: the actual 30-40% utilization-gain business
   thesis can only be validated against real organic traffic on a real
   client's cluster — never provable by a self-run test, however good.
   Operational readiness (onboarding/RBAC scope, rollback story, false-
   positive response process, pricing mechanics) is a parallel written-
   answers task, not a blocker to starting outreach conversations.

### Open product items (decided or discussed 2026-09-29 to 2026-10-01, not built)

- **`ceiling.py` memory-speed aware: BUILT 2026-10-04, awaiting A10
  re-test.** Target must fit on both FP16 TFLOPS and memory bandwidth;
  `RightSizingRecommendation` gained `required_mem_bandwidth_gbps` and
  `expected_latency_factor` (max of compute and bandwidth drops); the
  estimator passes the current GPU's bandwidth and the recommended action
  now reads "right-size to X (each request may take up to ~Fx longer --
  fine for batch/offline work, check latency targets before moving an
  interactive service)". verify.py's "right-size to" regex updated for the
  suffix. 7 new/changed tests fail on the old code, pass on the new; all
  suites green (37 + 66 + 90 + 71 + 49 + 2 = 315). Effect: fewer and larger
  downsize targets (e.g. A100 80GB at 25% peak -> V100 instead of L4; RTX
  3090 at 25-30% -> A10 instead of T4), so projected savings shown drop --
  correctly. Next: re-run the mini-test "after" side on an A10 (product's
  prediction: busy % and latency up by at most 1.56x).

Ordered roughly by what was recommended first:

- **Client-cluster verification test: KIT BUILT, NOT RUN** (2026-10-01,
  `testing/client-cluster-verification-test/`). Verifies the ₹ estimates and
  recommendations by applying them and measuring (not just detection): one
  4x A100 VM running vLLM (Qwen2.5-1.5B under the real Azure conv trace,
  Qwen2.5-0.5B under 15% of the code trace) and a data-loading-bound DDP
  job on 2 GPUs that trains, holds idle, then exits; then (a) both vLLM
  services co-located on one GPU, (b) the job on 1 GPU with 2 and 4 loader
  workers, (c) phase 2: the identical trace on 1x whatever GPU the product
  recommends. `verify.py` prints predicted vs measured with PASS/MARGINAL/
  FAIL. Founder chose **Quick (smoke thresholds, ~6 h + ~1.5 h, ~$25-50)
  then Full (real thresholds, ~29 h + ~1.5 h, ~$90-180)**. All scripts
  dry-run here: load generator vs a fake vLLM server, DDP script on CPU
  with 2 processes, verify.py on real product output from a synthetic
  scenario. Pinned images: vllm/vllm-openai:v0.8.5.post1,
  pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime (both confirmed on Docker
  Hub); driver must be >= 550.
- **Use an existing dcgm-exporter (Helm value)** -- small (~hours). The
  collector's DCGM_EXPORTER_URL is hard-coded to the chart's own service
  (`templates/collector.yaml:8`); `dcgmExporter.enabled: false` exists but
  there's no way to point at a cluster's GPU-Operator dcgm-exporter.
  Main blocker for neocloud/managed GPU clusters.
- **Optional ~1h alternative to step B:** keep fragmentation on the
  dashboard but out of the headline ₹ total. Recommended before pilots;
  not chosen yet.
- **Step B -- fragmentation fit check** (~1 week, 3 services): add peak
  memory + GPU memory capacity (used+free) to rollups (schema migration),
  group candidates by GPU model, pack by peak memory (10% headroom) and
  summed peak compute (<=70%), flag only if fewer GPUs suffice, price as
  freed GPUs x rate. Caveats: still can't see whether GPU sharing is
  enabled; vLLM pre-allocates ~90% of GPU memory by default
  (`gpu_memory_utilization=0.9`) and PyTorch caches freed memory, so the
  memory check will rarely flag those servers; Philly can't validate it
  (its memory data is host RAM). Recommended *after* the first pilot.
- **Option C -- percentile-based multi-GPU sizing** (e.g. p90 of
  per-minute readings instead of hourly average): needs percentiles in
  rollups (~+1 day). Calibrate on a pilot, then consider moving the
  multi-GPU signal from visibility-only toward a recommendation.
- **No-recommendation tier tuning:** `underutilizedMinRunHours` defaults
  to 1, so a live cluster will get many short findings (Philly: 58k,
  median 1h). Raise it (or aggregate per day) if the dashboard gets
  noisy; check on the first pilot.
- **Step C -- read cluster scheduling settings** (is time-slicing/MPS/MIG
  configured; pod affinity) via the K8s API, still read-only. Later.
- **GPU VM support (no Kubernetes)** -- today non-K8s customers get zero
  findings (`waste-detector/src/waste_detector/grouping.py` drops
  unattributed rows). Cheapest step: keep unattributed rows and report
  idle/recurring per host+GPU (days); then a PID->Docker-container
  agent for over-provisioned/fragmented (1-2 weeks); then a Docker
  Compose installer. Estimated to roughly double India SAM. Build only if
  customer interviews show demand (ask "Kubernetes or plain VMs?").

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

- **DCGM_FI_DEV_GPU_UTIL is busy time, not compute.** It's the % of time
  any kernel ran; a tiny kernel and a full-GPU kernel both read 100%.
  Summing it across GPUs ("8 GPUs at 20% = 1.6 GPUs of work") is only a
  rough proxy. DCGM_FI_PROF_SM_ACTIVE is the better compute signal if
  ever needed.
- **Kubernetes gives each pod whole GPUs** unless time-slicing, MPS, MIG
  (or DRA) is set up; time-slicing has no memory or fault isolation
  (NVIDIA GPU Operator docs). Any "share a GPU" advice must say so.
- **NCCL refuses two ranks on the same GPU** ("Duplicate GPU detected",
  since NCCL 2.5) -- never tell a multi-GPU job to consolidate onto a
  shared GPU.
- **Rollups carry workload identity, not pod**, so "same workload on >1
  GPU" can't distinguish distributed-job ranks from Deployment replicas.
- **Philly is 82% multi-GPU GPU-hours** (single-GPU median hourly avg
  utilization 54.3%, multi-GPU 53.6%). Effects that depend on multi-GPU
  jobs look much bigger on Philly than they will on a single-GPU-pod
  inference cluster.
- **Philly trace download can be cut off** (seen: connection reset at
  27MB). Use `curl -C - --retry 5` in a loop and check the sha256 in the
  replay README before extracting. 1GB download / 6.6GB extracted; delete
  it after building rollups.
- **Never pass the rates JSON to Helm with `--set`/`--set-string`.** Helm
  parses `{...}` as list syntax: `'{"NVIDIA A100 80GB": 100.0}'` renders
  as `["NVIDIA A100 80GB": 100.0]`, invalid JSON, so the product silently
  ignores the real prices. Use a values file
  (`testing/client-cluster-verification-test/rates.py` writes one).
- **The published GHCR images lag this branch.** They're private and only
  rebuilt from the default branch, so a live test of work on
  `claude/agent-skills-setup-fno99z` must build images on the VM
  (`testing/client-cluster-verification-test/build_images.sh` +
  `values-local-images.yaml`), or it silently runs old detectors.
- **After a detector change, re-run Philly from saved rollups**
  (`testing/real-trace-replay/rerun_detectors.py`) and update every place
  that quotes the Philly %: replay README + RESULTS.md, this file, and
  `reports/build_market_report.py` (scope paragraph, section 4.3, A12,
  sources), then rebuild the PDF.

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

## 8. Business and market conclusions (2026-09-29 to 2026-10-01)

All from `reports/gpu_waste_detection_market_research.pdf`; [A] figures
are assumptions to replace with pilot/interview data.

- **What the product is:** GPU observability + waste classification
  priced in ₹ -- it detects and recommends, it never acts. "GPU cost
  optimization SaaS" is a fair category label as long as claims don't
  imply automatic action, verified savings, or a performance fee.
- **Founder:** solo, doing engineering and sales, planning to stay solo
  until scale. Fixed costs ~₹50k/month without salary (~₹1.5L with a
  ₹1L draw) -> break-even ~2 (or ~5) customers at the assumed tier mix.
  The real constraint is time: ~25 customers supportable alone (2.5 h
  support/customer/month at 40% of time), ~1 new customer/month. First
  hire = support engineer at ~20-25 customers (~₹60-75L ARR).
- **Source-verified re-estimate (report section 8, Oct 2026) -- prefer
  this when citing externally.** Built top-down from published figures
  only: K8s cost management $2.23B (2026) x GPUs' 14% share of compute
  cost (Datadog, 22 Apr 2026) = **global TAM ~$312M (~₹2,980 Cr)**; SAM
  (NVIDIA 80-92%) ~$250-287M; SOM [A] ~$0.25-1.4M ARR. India = global x
  1.89% (Gartner 2025 cloud spend 13.7/723.4): **TAM ~$5.9M (~₹56 Cr)**,
  SAM ~$4.7-5.4M, SOM [A] ~$95-270K ARR. Closest category, GPU
  monitoring software: ~$1.65B (2026). Cross-check: 2,700-28,674 Indian
  K8s companies x 6% using GPUs (Datadog) = ~160-1,700 orgs. ₹95.45/$.
  India likely understated (GPU capacity growing faster than cloud).
- **TAM/SAM/SOM [A]:** India TAM ₹78-190 Cr/yr, SAM ~₹38 Cr (~885 orgs on
  Kubernetes), 3-yr SOM 27-45 customers / ₹0.8-1.35 Cr ARR. With SE Asia,
  Middle East, US, EU: TAM ~₹860 Cr, SAM ~₹270 Cr; 30 India + 15 overseas
  -> ~₹2.6 Cr ARR. Global top-down TAM ~$0.45B (2026).
- **Year-3 margins [A]** (₹ lakh/yr, with 1 support engineer, ₹2L/month
  salary, ~25% tax): 27 customers -> net 22 (27%); 35 -> 40 (38%); 45 ->
  62 (46%); India+overseas -> 113 (44%). Gross margin 78-87% (no hosting
  cost; self-hosted). The ₹4.35 Cr scenario (100 customers, full planned
  product) needs ~8 people and nets ~₹1.78 Cr (41%) -- likely year 4-5
  if self-funded.
- **Pricing:** current tiers by GPU count (₹9,999 / 29,999 / 74,999 /
  custom) underprice H100 fleets and overprice cheap-GPU fleets.
  Recommended: ~1% of monitored GPU spend with a ₹9,999 floor; move
  toward 2% only after a pilot proves >=15% savings or once the product
  acts on waste.
- **Recoverable-waste assumption:** the report's ROI tables use 10% of
  GPU spend, now flagged as optimistic: Philly 16.7% flagged x 30-50%
  acted on = ~5-8%. At 7% every ROI is ~30% lower (16xA100 8.2x; 4xL4
  1.4x). The first pilot's before/after number replaces this.
- **Competition:** CAST AI ($1B, Jan 2026) and ScaleOps ($800M+, Mar 2026)
  automate; Datadog GPU Monitoring (GA Apr 2026) overlaps most on
  detection. The product wins only where read-only + self-hosted + INR +
  non-hyperscaler (on-prem/neocloud/k3s) clusters matter. Defensibility is
  low today.
- **Earlier SMB study reconciliation:** its ₹216 Cr SAM / ₹7.2 Cr SOM
  sizes the full planned product sold by a team, with a ₹7.2L average
  contract that contradicts its own tiers (corrected: ₹130 Cr / ₹4.35
  Cr). The gap to this report is the feature roadmap (VM support, billing
  integration, approve-then-act, serving metrics, multi-cluster).
- **Neoclouds:** the product already runs on any K8s with NVIDIA+DCGM
  (proven on GKE and vast.ai/k3s); the gaps are the dcgm-exporter URL
  override and non-K8s GPU VMs. Recommended: stay self-hosted (a hosted
  SaaS loses the "data never leaves your cluster" edge), and pursue Indian
  GPU clouds (E2E, Yotta, Neysa) as distribution partners.
- **Next steps agreed with the earlier study:** 20 discovery interviews ->
  5 read-only pilots -> 2 paid pilots with verified savings; ask every
  prospect whether they run Kubernetes or plain VMs.

