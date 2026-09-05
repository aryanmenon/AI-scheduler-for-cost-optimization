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

### 5.2 Ingestion & Normalization — ○ PLANNED

- Define the per-workload record schema
- Build a GPU-capability reference table (FLOPS/bandwidth) so raw
  utilization % is comparable across SKUs — worth building slightly more
  general now, since phase 3's scheduler will reuse this for heterogeneous
  capability reasoning
- Build the time-aggregation layer (5-min / hourly / daily rollups)
- Handle missing data and gaps explicitly
- Handle shared-GPU edge cases (MIG, time-slicing) — important early since
  the product's own advice will push customers toward sharing GPUs
- Validate against raw source data

### 5.3 Baseline & Waste Detector — ○ PLANNED

- Define waste categories with concrete thresholds (idle / fragmented /
  over-provisioned)
- Build over-provisioning detection first — single-snapshot comparison,
  fastest to a demonstrable number
- Build idle-GPU detection, tuned for inference's bursty traffic (not
  training's steady load)
- Build fragmentation detection — hardest piece; timebox it and ship
  without it if needed
- Add daily/weekly pattern detection (overnight idle-fleet pattern)
- Validate against real traffic and tune false positives — a bad
  recommendation that breaks a customer's SLA costs more trust than a
  missed one

## 6. Key Risks & Decision Gates

- Phase 1 gate: cannot proceed to funding phase 3 unless real customer
  workloads sustain 30–40%+ utilization gains.
- Phase 3 gate: check for competing 2026/2027 papers before over-investing
  in the scheduler's technical novelty.
- Both ideas rely partly on vendor-reported or non-peer-reviewed evidence
  — treat headline numbers as directional, not proof, until validated on
  owned data.
