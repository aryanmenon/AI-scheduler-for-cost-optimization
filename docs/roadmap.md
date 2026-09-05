# GPU Infra Startup — Build Roadmap

India-market GPU optimization & power-scheduling ventures — comparison,
sequencing, and MVP technical build status.

## 1. Executive Summary

Two product ideas are on the table, drawn from two separate research
tracks. Both are evaluated below, and the current plan is to pursue them
sequentially: start with the proven-market cost-optimization SaaS to
generate revenue and credibility fast, then use that base to fund and
de-risk the harder, more technically novel power-hard-constraint scheduler.

## 2. Product Comparison

| Metric | Cost-optimization SaaS | Power-hard-constraint scheduler |
|---|---|---|
| Core product | Optimization layer on top of an existing scheduler (KAI/Volcano/native); detects waste, recommends/automates fixes | An actual scheduler treating power as a hard, time-varying ceiling for heterogeneous older GPU fleets, with admission control + graceful degradation |
| Target buyer | Mid-market/SMB inference teams without dedicated MLOps staff, self-serve | GPU-cloud operators and data-center operators running grid-unstable / backup-power-limited facilities |
| Market size (global) | GPU orchestration software ~$1.78B (2025) → $8.16B (2031), 28.7% CAGR | Not sized as a market — a technical/academic gap, not a costed category |
| Market size (India, bottom-up) | Not India-specific; competing globally from day one vs Cast AI / ScaleOps entering India | ~15–20 India GPU-cloud operators × $50K–300K/yr ≈ $1–5M/yr near-term TAM |
| Competitive intensity | High, consolidating fast — Cast AI ($1B+), ScaleOps ($800M+, 350% YoY), NVIDIA giving Run:ai/KAI away free | Low to none for this exact combination; adjacent players (PowerSlider, PALS) target homogeneous modern GPUs at hyperscalers |
| Technical novelty / defensibility | Low — table-stakes technique; moat is distribution/beachhead/trust, not algorithm | High — genuinely unsolved combination per literature review |
| Evidence quality behind opportunity | Mixed — vendor-reported savings (Cast AI 49%, ScaleOps projected $1.4M) are directional, not independently verified | Weaker differently — very recent 2026 arXiv preprints, not peer-reviewed; India/Oman power figures from non-academic sources that disagree with each other |
| Capital to MVP | Low — software-only, self-serve, needs only a test cluster | Low-moderate — needs real heterogeneous older-GPU hardware and a way to simulate power-capped/unreliable-grid conditions |
| Time to MVP | ~8–10 weeks build, ~12–14 weeks incl. pilot validation | ~3–6 months for something credible |
| Time to first revenue | Faster — self-serve, savings-share pricing removes adoption friction | Slower — relationship-heavy, infra-procurement sales cycles |
| Sales motion complexity | Low-to-medium — one Helm command, observe mode, prove value before charging | High — trust, hands-on support, integration depth matter more than self-serve UX |
| India regulatory / context fit | Moderate — DPDP compliance relevant, no special sovereign angle | Strong — rides India's older/mixed-hardware reality and grid-instability concerns; IndiaAI Mission tailwind |
| Biggest single risk | If utilization gains can't be sustained at 30–40%+ on real workloads, the wedge collapses — against two well-capitalized incumbents doing the same thing | If a 2026/2027 paper ships the same combination, technical novelty collapses — would need to pivot to owning deployment context instead of algorithm |
| Long-term scalability | High — SaaS, low marginal cost per customer, expands to verticals/arbitrage | Lower and narrower — bounded by the number of grid-unstable/backup-limited operators, though geographically expandable (Oman, etc.) |
| Realistic exit path | Acquisition by a neocloud moving up-stack, or an incumbent filling vertical/mid-market gaps | Less obvious — likely acquihire by a hyperscaler or GPU-cloud operator, or stays a specialized infra vendor |

## 3. Sequenced Roadmap

The two ideas aren't run in parallel from day one — phase 1 funds and
de-risks phase 3, and phase 2's customer relationships are the natural
entry point into phase 4's buyers.

**Phase 1 — Build & validate the optimization SaaS (0–4 months)**
- Build the observe-mode MVP: telemetry collector → waste detector →
  savings estimator → dashboard.
- Run against 2–3 real design-partner clusters.
- Gate: sustain 30–40%+ utilization gains on real inference workloads
  before spending real money on phase 3.

**Phase 2 — Sell the beachhead (4–10 months)**
- Convert design partners to paying, savings-share customers.
- Target 10–20 referenceable mid-market logos with quantified savings.
- Prioritize design partners with a plausible path to power/grid concerns
  later — a warm bridge into phase 4's buyers.

**Phase 3 — Start the scheduler R&D in parallel, unpaid (starting month
6–8)**
- Begin once phase 1 revenue covers runway — don't start early just
  because runway allows it.
- Literature synthesis is already done; start building admission control +
  DVFS + quantization degradation on a real heterogeneous older-GPU
  testbed.
- Treat as unpaid validation — no committed buyer yet.

**Phase 4 — Validate the technical gap still holds (10–14 months)**
- Check whether any 2026/2027 paper has shipped the same combination (hard
  cap + heterogeneous fleet + degradation).
- If yes: pivot to owning deployment context (grid-signal integration,
  brownout ride-through) rather than the algorithm.
- If the gap holds: pitch the working prototype to India GPU-cloud
  operator relationships built in phase 2.

**Phase 5 — Decide how the two businesses relate (14+ months)**
- Either: the scheduler becomes a distinct, higher-moat product line
  cross-sold to the same operator relationships.
- Or: it becomes acquisition-friendly IP a neocloud/hyperscaler buys the
  team for.
- The optimization SaaS keeps running as the revenue base either way.

## 4. Phase 1 MVP — Technical Component Build Order

Five core components, in build order, with current status:

1. Telemetry collector — one-command, read-only install (≈ 2 weeks)
2. Ingestion & normalization — per-workload time series, heterogeneous GPU
   handling (≈ 1 week)
3. Baseline & waste detector — idle/fragmentation/over-provisioning
   detection (≈ 2–3 weeks)
4. Achievable ceiling & savings estimator — SLA-aware target +
   confidence-scored $ impact (≈ 2 weeks)
5. Observe-mode report & dashboard — the self-serve sales artifact (≈ 1–2
   weeks)

Total: ~8–10 weeks active build, ~12–14 weeks including the design-partner
pilot window (which cannot be compressed — it needs real elapsed calendar
time on real traffic).

## 5. Component Detail & Status

### 5.1 Telemetry Collector — ✓ BUILT & VALIDATED against synthetic fixtures

- Stand up a test GPU cluster (heterogeneous SKUs)
- Deploy DCGM exporter for per-GPU utilization/memory/power
- Deploy kube-state-metrics for pod/node metadata
- Build GPU-to-pod correlation — simplified once discovered that DCGM's
  native kubernetes pod-resources integration already attaches
  pod/namespace labels in most cases; fallback to explicit 'unattributed'
  records where it isn't enabled
- Build the scrape-and-store loop (SQLite-backed, tested across repeated
  scrapes)
- Lock down RBAC to read-only (get/list/watch only — verified structurally
  valid)
- Package as a single Helm chart with toggleable persistent storage

Still needed: validation against real hardware and a second real cluster.

### 5.2 Ingestion & Normalization — ✓ BUILT & VALIDATED against synthetic fixtures

- Define the per-workload record schema — done (`NormalizedRecord`)
- Build a GPU-capability reference table (FLOPS/bandwidth) so raw
  utilization % is comparable across SKUs — done, covering
  A100/H100/T4/V100/A10/L4/L40S with an explicit "unknown" fallback
  rather than a guessed default; built general enough for phase 3's
  scheduler to reuse for heterogeneous capability reasoning
- Build the time-aggregation layer (5-min / hourly / daily rollups) — done
- Handle missing data and gaps explicitly — done, via a `coverage_ratio` +
  `low_confidence` flag on every rollup bucket, rather than silently
  averaging whatever samples happened to be present
- Handle shared-GPU edge cases (MIG, time-slicing) — done for MIG (each
  instance tracked as a distinct workload via DCGM's `GPU_I_ID`, which
  required a small fix to component 1's correlator to stop colliding MIG
  instances sharing a physical GPU index); time-slicing on a non-MIG GPU
  is a known, documented limitation — DCGM reports one utilization value
  per physical device, so per-tenant accounting isn't exact there
- Validate against raw source data — validated against synthetic DCGM
  fixtures (heterogeneous fleet, MIG sharing, and a scrape-gap scenario);
  still needs validation against a real cluster

Still needed: validation against real hardware and a second real cluster
(same caveat as component 1 — no live cluster available yet).

### 5.3 Baseline & Waste Detector — ✓ BUILT & VALIDATED against synthetic fixtures

- Define waste categories with concrete thresholds (idle / fragmented /
  over-provisioned) — done, plus a fourth category (recurring pattern) not
  originally enumerated but needed to catch workloads idle detection's
  strict streak logic would otherwise miss
- Build over-provisioning detection first — single-snapshot comparison,
  fastest to a demonstrable number — done: flags a workload whose peak
  utilization never exceeds a threshold over a minimum observation window
- Build idle-GPU detection, tuned for inference's bursty traffic (not
  training's steady load) — done: requires a sustained, unbroken run of
  low avg *and* max utilization, so a single real request inside an
  otherwise-quiet hour breaks the streak and the service isn't flagged
- Build fragmentation detection — hardest piece; timebox it and ship
  without it if needed — done at MVP scope (no bin-packing, just the
  detectable signal: multiple GPUs on one node, owned by different
  workloads, concurrently underutilized for a sustained streak); an
  intentional multi-GPU job from one workload is explicitly excluded
- Add daily/weekly pattern detection (overnight idle-fleet pattern) — done:
  groups hourly rollups by hour-of-day across many observed days and
  tolerates occasional exception days, catching patterns the continuous-
  streak idle detector would fragment into too-short pieces
- Validate against real traffic and tune false positives — validated
  against synthetic fixtures covering the false-positive risks explicitly
  (bursty-but-healthy traffic, a legitimate multi-GPU job, low-coverage
  buckets); every detector excludes rollups below a coverage threshold and
  requires a minimum observation window before flagging anything. Still
  needs tuning against real customer traffic — the thresholds here are
  reasonable starting points, not validated numbers.

### 5.4 Achievable Ceiling & Savings Estimator — ✓ BUILT & VALIDATED against synthetic fixtures

The original roadmap only sized this component at one line ("SLA-aware
target + confidence-scored $ impact, ≈ 2 weeks") without the detailed
build-order breakdown given to 5.1–5.3. Built out as:

- **SLA-aware achievable ceiling**: rather than recommend right-sizing a
  workload to run its new GPU at 100%, `ceiling.py` recommends the
  smallest known SKU whose capacity — sized to the workload's own
  already-observed peak load — lands at or below a configurable target
  utilization ceiling (default 70%). Full utilization leaves no headroom
  for a traffic spike or a latency-sensitive retry storm; a
  recommendation that causes an SLA breach costs more trust than the
  waste it fixed.
- **Confidence-scored $ impact, split into observed vs. projected
  bases** — a distinction the original one-liner didn't specify but that
  turned out to matter: an idle finding's own idle-fraction is 100% by
  construction (that's what makes it a streak), so pricing it as a full
  month's waste would overclaim what a single window can support. Idle is
  priced strictly against its own observed window (money already spent,
  a defensible lower bound); over-provisioned, fragmented, and
  recurring-pattern findings all require a sustained multi-hour or
  multi-day observation before they fire at all, so projecting their
  observed rate to a monthly figure is the standard, clearly-labeled
  basis for a right-sizing ROI calculation.
- **Pricing is configurable, not asserted** — ships illustrative public
  on-demand list-price defaults, but is designed to be overridden with a
  customer's actual contracted rate card. An unrecognized GPU model or a
  model with no known rate is marked explicitly `unpriceable` rather than
  guessed, consistent with every other "don't guess, say unknown" choice
  made across this pipeline.
- A gap surfaced building this component: the rollups schema (5.2) never
  carried the GPU model forward, only a derived effective-TFLOPS number —
  which can't be reverse-engineered into a capability at 0% utilization
  (the idle case). Fixed by adding `gpu_model`/`fp16_tflops` columns to
  the rollups table, the same kind of small, well-justified schema
  addition as the MIG fix made building 5.2.
- Validated against synthetic fixtures per category, plus an
  unpriceable-GPU guard. Still needs real customer contracted rates (the
  shipped defaults are explicitly illustrative) and real traffic to
  validate the SLA ceiling default and the fragmentation capture-fraction
  discount.

### 5.5 Observe-Mode Report & Dashboard — ✓ BUILT & VALIDATED against synthetic fixtures

The original roadmap sized this at one line too ("the self-serve sales
artifact, ≈ 1–2 weeks"). Built as:

- **Two delivery modes sharing one code path**: a live page that always
  reflects current data (no cache, regenerated per request — this is a
  low-traffic internal tool where correctness beats a cheap render cost),
  and a `generate-report` CLI producing a standalone HTML file with no
  external requests, meant to be attached to an email. Both call the same
  read → aggregate → render function, so they can never drift from each
  other.
- **The observed/projected split survives all the way to the UI**: the
  report's two headline numbers ("Projected Monthly Savings" and
  "Already-Wasted Spend Observed") are deliberately never summed —
  continuing the same reasoning from 5.4's basis distinction. A sales
  artifact whose top-line number can't be defended to a skeptical
  customer champion isn't worth having.
- **Unpriceable findings get their own disclosed section** rather than
  being dropped silently — consistent with the "don't guess, say
  unknown" principle applied everywhere else in this pipeline.
- Needed zero new runtime dependencies (stdlib `http.server` + f-string
  HTML, no templating engine, no web framework) — the one component in
  this pipeline with no cross-package coupling at all in production code.
- Validated with a real HTTP server integration test (not just unit tests
  of the render function) and an explicit HTML-escaping test against an
  adversarial workload name, since workload/namespace/node strings
  ultimately originate from a customer's own cluster.

This completes the Phase 1 MVP pipeline end to end (telemetry collector →
ingestion & normalization → waste detector → savings estimator →
dashboard), all validated against synthetic fixtures. What's not yet
true: none of it has run against a real GPU cluster, and no design
partner has validated the 30–40%+ utilization-gain gate below.

## 6. Key Risks & Decision Gates

- Phase 1 gate: cannot proceed to funding phase 3 unless real customer
  workloads sustain 30–40%+ utilization gains.
- Phase 3 gate: check for competing 2026/2027 papers before over-investing
  in the scheduler's technical novelty.
- Both ideas rely partly on vendor-reported or non-peer-reviewed evidence
  — treat headline numbers as directional, not proof, until validated on
  owned data.
