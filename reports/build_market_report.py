from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable,
    ListItem, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-Bold", italic="DV", boldItalic="DV-Bold")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1", fontName="DV-Bold", fontSize=20, leading=25, spaceAfter=10))
styles.add(ParagraphStyle(name="H2", fontName="DV-Bold", fontSize=13, leading=16, spaceBefore=14, spaceAfter=7,
                          textColor=colors.HexColor("#1a1a1a")))
styles.add(ParagraphStyle(name="H3", fontName="DV-Bold", fontSize=11, leading=14, spaceBefore=8, spaceAfter=5))
styles.add(ParagraphStyle(name="Body", fontName="DV", fontSize=9.8, leading=13.5, spaceAfter=7, alignment=TA_LEFT))
styles.add(ParagraphStyle(name="Small", fontName="DV", fontSize=8.3, leading=11, spaceAfter=5,
                          textColor=colors.HexColor("#444444")))
styles.add(ParagraphStyle(name="Cell", fontName="DV", fontSize=8.2, leading=10.5))
styles.add(ParagraphStyle(name="CellBold", parent=styles["Cell"], fontName="DV-Bold"))
styles.add(ParagraphStyle(name="Callout", fontName="DV", fontSize=9.8, leading=13.5, leftIndent=8,
                          rightIndent=8, spaceBefore=4, spaceAfter=10, backColor=colors.HexColor("#f4f6f8"),
                          borderPadding=(7, 7, 7, 7)))


def P(text, style="Body"):
    return Paragraph(text, styles[style])


def bullets(items, style="Body"):
    return ListFlowable(
        [ListItem(P(t, style), bulletColor=colors.black) for t in items],
        bulletType="bullet", start="•", leftIndent=14, spaceBefore=0, spaceAfter=6,
    )


def make_table(header, rows, col_widths, bold_last=False):
    data = [[P(h, "CellBold") for h in header]] + [[P(c, "Cell") for c in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf1")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if bold_last:
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f7f7f2")))
    t.setStyle(TableStyle(style))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("DV", 7.5)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(0.7 * inch, 0.45 * inch,
                      "GPU waste-detection product: market research, competition & unit economics (Sept 2026)")
    canvas.drawRightString(A4[0] - 0.7 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


W = A4[0] - 1.4 * inch  # usable width

doc = SimpleDocTemplate(
    "gpu_waste_detection_market_research.pdf", pagesize=A4,
    topMargin=0.7 * inch, bottomMargin=0.75 * inch, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    title="GPU Waste Detection: Market Research, Competition, Unit Economics & International Expansion",
)
s = []

# ================================================================= Title / exec summary
s.append(P("GPU Waste Detection for Kubernetes: Market Research, Competition, Unit Economics &amp; International Expansion", "H1"))
s.append(P("Scope: the product <b>as it is actually built today</b> (September 2026), not the broader vision. "
           "That product is a read-only, self-hosted Helm install that reads NVIDIA DCGM telemetry plus "
           "Kubernetes pod identity, classifies GPU waste into four categories (idle, over-provisioned, "
           "fragmented, recurring pattern), prices each finding in INR against a right-sizing ceiling, and shows "
           "it on a dashboard. It recommends; it does not act. It has been validated on GKE (L4), on a vast.ai/k3s "
           "GPU node, against the real Microsoft Philly training trace (23.0% of GPU-workload-hours flagged as "
           "waste) and the real Azure LLM inference trace (19,366/19,366 requests served, over-provisioning "
           "finding fired).", "Body"))
s.append(P("How to read the numbers: every figure is tagged <b>[S]</b> (sourced, see Sources at the end) or "
           "<b>[A]</b> (our assumption, listed in the Assumptions ledger). Market-research firm estimates vary "
           "widely and are treated as directional. Currency: INR; USD conversions at ₹88/USD [A].", "Small"))

s.append(P("Executive summary", "H2"))
s.append(make_table(
    ["Question", "Answer"],
    [
        ["TAM", "<b>Global:</b> ~$0.45B (2026) spent on cost visibility/optimization for GPU workloads on "
                "Kubernetes [S+A]. <b>India:</b> ~₹78-190 Cr/yr (~$9-22M) at this product's own price points [A], "
                "growing fast with India's GPU build-out."],
        ["SAM", "<b>India, Kubernetes-based GPU fleets reachable with read-only, self-hosted, INR-priced "
                "software:</b> ~885 organizations, ~₹38 Cr/yr (~$4.4M) [A]."],
        ["SOM (3 yrs)", "<b>India only: 27-45 paying customers, ~₹0.8-1.35 Cr ARR (~$92-153k)</b> [A]. "
                        "Viable as a bootstrapped business; not venture-scale on this product alone."],
        ["International", "Adding SE Asia, Middle East, US and EU raises TAM to <b>~₹860 Cr (~$98M)</b> and SAM "
                          "to <b>~₹270 Cr (~$31M)</b> [A]. With the same 45 customers (30 India + 15 abroad), "
                          "year-3 ARR rises from ₹1.35 Cr to <b>~₹2.6 Cr</b> and net profit from ~₹62 L to "
                          "<b>~₹1.13 Cr</b> [A]. Overseas customers pay ~3-5x more for similar support effort."],
        ["Earlier study", "The Sept 2026 SMB market study's ₹216 Cr SAM / ₹7.2 Cr SOM sizes the <b>full planned "
                          "product with a team</b>; with its price assumption corrected it is ₹130 Cr / ₹4.35 Cr. "
                          "The gap to this report is the feature roadmap (section 7)."],
        ["Main competitor", "CAST AI ($1B valuation, Jan 2026) and ScaleOps ($800M+, Mar 2026) automate; "
                            "Datadog launched GPU Monitoring (Apr 2026) and overlaps most directly on detection. "
                            "You win only where read-only + self-hosted + INR + non-hyperscaler clusters matter."],
        ["Unit economics", "Gross margin 78-89% (no hosting cost; you're self-hosted). LTV:CAC 3.4x (Starter) "
                           "to 18x (Enterprise); CAC payback 4-6 months, founder-led [A]. As a solo founder, "
                           "break-even is ~2 customers with no salary, ~5 with a ₹1 L/month draw [A]; your time "
                           "(~25 customers supportable alone) is the real limit, not money."],
        ["Biggest risk", "<b>One-time-audit churn:</b> a customer finds the waste, fixes it, cancels. If churn "
                         "doubles, Starter LTV:CAC drops to 1.7x (unprofitable). Also: GPU-count pricing "
                         "underprices H100 fleets and overprices cheap-GPU fleets."],
    ],
    [1.2 * inch, W - 1.2 * inch],
))

# ================================================================= Market context
s.append(P("1. Market context", "H2"))
s.append(make_table(
    ["Signal", "Figure", "Tag"],
    [
        ["India end-user public cloud spending (Gartner)", "$17.5B in 2026, up 28.1% from $13.7B in 2025", "[S]"],
        ["India data-center GPU market (MarkNtel)", "~$0.17B (2025) to $5.29B (2032), 63% CAGR", "[S]"],
        ["IndiaAI Mission compute", "38,000+ GPUs onboarded at ~₹65/GPU-hr; target 100,000 by Dec 2026", "[S]"],
        ["Indian GenAI startups (Nasscom)", "890+ in H1 CY2025 (740+ application layer); $990M cumulative funding", "[S]"],
        ["India GPU installed base (third-party survey)", "80,000+ GPUs across public/private deployments", "[S, 3rd-party blog]"],
        ["Global GPU-as-a-Service (MarketsandMarkets)", "$8.21B (2025) to $26.62B (2030), 26.5% CAGR", "[S]"],
        ["Global Kubernetes cost management market", "~$1.75B (2025) to ~$2.23B (2026), ~27% CAGR; "
                                                      "other estimates $1.38B (2025)", "[S, analyst range]"],
        ["Kubernetes for AI inference (CNCF 2025 survey)", "66% of orgs hosting GenAI use Kubernetes for some or all inference", "[S]"],
        ["GPU share of compute cost (Datadog)", "GPU instances = 14% of compute costs across its customer base", "[S]"],
    ],
    [2.35 * inch, 3.35 * inch, W - 5.7 * inch],
))
s.append(P("What this means: the value pool (GPU spend) is growing 25-60% a year, and Kubernetes is now the "
           "default place GPU inference runs. But the software pool this product can capture is a thin slice "
           "of GPU spend: cost-visibility tools typically capture 1% or less of the spend they watch.", "Body"))

# ================================================================= TAM/SAM/SOM
s.append(P("2. TAM, SAM, SOM", "H2"))
s.append(P("2.1 Global TAM (top-down, for context)", "H3"))
s.append(P("Global Kubernetes cost-management spend is ~$2.23B in 2026 [S]. We assume 15-25% of it is "
           "GPU-driven [A], anchored on Datadog's finding that GPUs are already 14% of compute cost and rising "
           "[S], and on GPU nodes costing several times more per hour than CPU nodes. That gives "
           "<b>~$0.33-0.56B, midpoint ~$0.45B (~₹3,900 Cr)</b> of global spend on cost visibility and "
           "optimization for GPU workloads on Kubernetes. This is the category CAST AI, ScaleOps, Kubecost and "
           "Datadog are fighting over. It is <b>not</b> reachable by a two-person, INR-priced, founder-led "
           "product in the next three years; it matters as the ceiling and as the reason incumbents will keep "
           "investing here.", "Body"))

s.append(P("2.2 India TAM (bottom-up, at this product's own prices)", "H3"))
s.append(make_table(
    ["Segment (orgs running dedicated NVIDIA GPU fleets, 2026)", "Count", "Basis"],
    [
        ["AI / GenAI startups that train or self-host models", "~900",
         "[A] from Nasscom's 890+ GenAI startups [S]: most of the ~150 infra/model-layer firms, a minority of "
         "the 740 app-layer firms (most call APIs), plus non-GenAI AI firms (vision, speech, health AI)"],
        ["Enterprises with in-house GPU clusters (BFSI, telecom, IT services, e-commerce, auto)", "~600", "[A]"],
        ["Research, academic and government labs (IITs, IISc, IndiaAI compute users)", "~300", "[A]"],
        ["GPU clouds / neoclouds / MSPs (E2E, Yotta, Neysa, NxtGen, Netweb, smaller)", "~30",
         "[A] better treated as channel partners than end customers"],
        ["<b>Total</b>", "<b>~1,800</b>", ""],
    ],
    [2.9 * inch, 0.6 * inch, W - 3.5 * inch], bold_last=True,
))
s.append(Spacer(1, 6))
s.append(KeepTogether([make_table(
    ["Tier (current pricing)", "GPUs", "Annual price", "Assumed share of orgs [A]"],
    [
        ["Starter", "1-5", "₹1.2 L", "45%"],
        ["Growth", "6-25", "₹3.6 L", "35%"],
        ["Scale", "26-100", "₹9.0 L", "15%"],
        ["Enterprise (assumed ₹2 L/mo)", "100+", "₹24 L", "5%"],
        ["<b>Blended ACV at list</b>", "", "<b>₹4.35 L</b>", ""],
    ],
    [2.2 * inch, 0.9 * inch, 1.3 * inch, W - 4.4 * inch], bold_last=True,
)]))
s.append(Spacer(1, 6))
s.append(P("<b>Method A (by organization):</b> 1,800 orgs x ₹4.35 L = <b>~₹78 Cr/yr (~$8.9M)</b>. "
           "<b>Method B (by GPU):</b> 80,000 GPUs [S, third-party] x ~₹2,000 per GPU-month (the Growth tier's "
           "effective per-GPU price at ~15 GPUs) x 12 = <b>~₹192 Cr/yr (~$21.8M)</b>. "
           "India TAM is therefore <b>~₹78-190 Cr/yr</b>. Method B is higher because it counts GPU-cloud "
           "and IndiaAI capacity that sits in a few very large fleets. With IndiaAI alone targeting 100,000 GPUs "
           "by Dec 2026 [S], this number should roughly double by 2027-28.", "Body"))

s.append(P("2.3 SAM (India, serviceable by the product as built)", "H3"))
s.append(P("The product requires Kubernetes, NVIDIA GPUs with DCGM, and a buyer willing to install a Helm "
           "chart. Filters applied [A]:", "Body"))
s.append(bullets([
    "Exclude GPU clouds as direct customers (channel instead): 1,770 end-user orgs.",
    "Keep only fleets run on Kubernetes: 50% [A]. This is deliberately below CNCF's 66% [S] because many Indian "
    "startups run GPUs on bare VMs, Slurm, or notebooks rather than Kubernetes.",
    "Result: <b>~885 orgs x ₹4.35 L = ~₹38.5 Cr/yr (~$4.4M)</b>.",
]))
s.append(P("Not filtered out, but harder to win inside the SAM: teams on EKS/GKE/AKS that already have CAST AI, "
           "Datadog, or hyperscaler cost tools, and teams whose GPU spend is subsidized (IndiaAI at ~₹65/GPU-hr "
           "shrinks the rupee value of the same waste roughly 4-5x vs. commercial A100 rates).", "Small"))

s.append(P("2.4 SOM (3-year obtainable)", "H3"))
s.append(make_table(
    ["Scenario", "Share of SAM", "Paying customers", "Realized ACV [A]", "ARR"],
    [
        ["Conservative", "3%", "27", "₹3.0 L", "₹0.81 Cr (~$92k)"],
        ["Base", "4%", "35", "₹3.0 L", "₹1.05 Cr (~$119k)"],
        ["Stretch", "5%", "45", "₹3.0 L", "₹1.35 Cr (~$153k)"],
    ],
    [1.1 * inch, 1.0 * inch, 1.2 * inch, 1.2 * inch, W - 4.5 * inch],
))
s.append(Spacer(1, 6))
s.append(P("Realized ACV is below the ₹4.35 L list blend because early customers skew small and pilots get "
           "discounted [A]. 3-5% of SAM in three years is normal for a founder-led product with no sales team.", "Body"))
s.append(P("<b>Honest read:</b> the product as built supports a profitable small business (break-even for a solo founder is "
           "2-5 customers, section 4), not a venture-scale one. Getting to venture scale needs one or more of: "
           "(1) selling outside India (SE Asia, Middle East, US, EU: a ~$26M international SAM, "
           "see section 5); (2) white-labelling through Indian GPU "
           "clouds to reach their customers; (3) moving from detection to action (the queue-depth/TTFT and "
           "bin-packing items from the MVP roadmap), which is what justifies CAST AI's and ScaleOps's "
           "valuations.", "Callout"))

# ================================================================= Competitors
s.append(PageBreak())
s.append(P("3. Competitive landscape", "H2"))
s.append(P("Four kinds of competitor: <b>automation platforms</b> that change your cluster (CAST AI, ScaleOps, "
           "PerfectScale), <b>cost-allocation tools</b> (Kubecost/OpenCost), <b>observability platforms</b> "
           "adding GPU views (Datadog), and <b>schedulers</b> (NVIDIA Run:ai / KAI). The default competitor is "
           "still <b>DIY</b>: dcgm-exporter + Prometheus + Grafana.", "Body"))
s.append(make_table(
    ["Competitor", "What it is", "GPU capability", "Pricing (public / reported)", "Scale", "Overlap"],
    [
        ["<b>CAST AI</b>", "Kubernetes automation platform (autoscaling, bin-packing, Spot, rightsizing)",
         "GPU node autoscaling, Spot GPUs, time-slicing/MIG sharing, GPU cost monitoring, OMNI Compute / GPU "
         "marketplace", "Free monitoring; paid tiers reported at $200 / $1,000 / $5,000 per month; savings-share "
         "~15-20% reported (third-party)", "$1B valuation (Jan 2026); ~$181M raised", "High on visibility; they "
                                                                                       "act, you recommend"],
        ["<b>ScaleOps</b>", "Autonomous real-time Kubernetes resource management", "Adjusts compute and GPU "
         "resources automatically", "Not public (enterprise)", "$130M Series C at $800M+ (Mar 2026); $210M total; "
                                                               "350%+ YoY growth", "Medium-high"],
        ["<b>Datadog GPU Monitoring</b>", "Observability platform add-on (GA Apr 22, 2026)",
         "Fleet health, idle/misconfigured GPUs, cost + chargeback by team, cloud / neocloud / on-prem",
         "Usage-based on top of Datadog agent pricing", "Public company; huge installed base",
         "<b>Highest on detection</b>"],
        ["<b>IBM Kubecost / OpenCost</b>", "Kubernetes cost allocation (acquired by IBM Sep 2024; OpenCost is "
                                           "the CNCF open-source core)", "Per-GPU hourly cost allocation; "
         "idle-capacity cost; not GPU-utilization waste classification", "Free/OSS tier; Business plan "
         "reported ~$449/mo per 100 nodes", "IBM FinOps suite (Apptio, Cloudability, Turbonomic)", "Medium"],
        ["<b>PerfectScale (DoiT)</b>", "Kubernetes optimization and governance (acquired by DoiT Feb 2025)",
         "Rightsizing across CPU, GPU, storage, networking", "Bundled with DoiT services", "Part of DoiT",
         "Medium"],
        ["<b>NVIDIA Run:ai / KAI Scheduler</b>", "GPU scheduler/orchestrator; KAI is the Apache 2.0 open-source "
                                                 "core (CNCF Sandbox)", "Fair-share quotas, gang scheduling, "
         "GPU sharing; utilization dashboards in Run:ai", "KAI free; Run:ai enterprise", "NVIDIA", "Low "
                                                                                                  "(different layer)"],
        ["<b>DIY: DCGM + Prometheus + Grafana</b>", "Free open-source metrics stack", "Raw utilization per GPU; "
         "no waste taxonomy, no workload rollups, no ₹ recommendations out of the box", "Free (engineer time)",
         "Everywhere", "High on raw data"],
        ["<b>Indian GPU clouds' own consoles</b>", "E2E, Yotta, etc. instance dashboards", "Basic per-instance "
         "utilization for their own GPUs", "Included", "Growing fast", "Low; potential channel partners"],
    ],
    [0.95 * inch, 1.2 * inch, 1.35 * inch, 1.15 * inch, 0.95 * inch, W - 5.6 * inch],
))

s.append(KeepTogether([P("3.1 Feature comparison vs. CAST AI (closest well-known name)", "H3"), make_table(
    ["Capability", "Your product", "CAST AI"],
    [
        ["GPU waste detection (idle / over-provisioned / fragmented / recurring)", "Yes, four categories, "
         "confidence-scored", "Partial (utilization + cost monitoring; not this taxonomy)"],
        ["₹ savings estimate per finding", "Yes, native INR, SLA-aware right-sizing ceiling", "USD cost; savings "
                                                                                             "reported after "
                                                                                             "automation"],
        ["Automatic action (scale, rebin, Spot, sharing)", "<b>No</b> (recommends only)", "<b>Yes</b> (core product)"],
        ["Cluster permissions", "<b>Read-only</b> (get/list/watch only)", "Needs write access for automation"],
        ["Where data lives", "<b>Customer's own cluster</b> (self-hosted, SQLite)", "CAST AI SaaS"],
        ["Cluster types", "Any Kubernetes with NVIDIA+DCGM; tested GKE and k3s/vast.ai", "Strongest on EKS/GKE/AKS"],
        ["Cloud-billing integration", "No", "Yes"],
        ["Serving metrics (queue depth, TTFT)", "No (roadmap)", "Partial"],
        ["Multi-cluster, SSO, SOC 2", "No", "Yes"],
        ["Pricing model", "Flat INR subscription by GPU count", "USD tiers + savings share"],
    ],
    [2.3 * inch, 2.1 * inch, W - 4.4 * inch],
)]))

s.append(P("3.2 Where you win and where you lose", "H3"))
s.append(make_table(
    ["You win when...", "You lose when..."],
    [[
        "- Security won't grant write access to a third-party agent (banks, government, regulated health)<br/>"
        "- Data must stay in-cluster or in-country (DPDP Act, sovereign-AI projects)<br/>"
        "- The cluster is on-prem, a neocloud, or k3s, not EKS/GKE/AKS<br/>"
        "- The buyer wants a flat INR invoice, not a USD savings share<br/>"
        "- The team is small (5-50 GPUs) and not a Datadog customer",
        "- The buyer wants savings to happen automatically (CAST AI, ScaleOps)<br/>"
        "- They already pay Datadog and can switch on GPU Monitoring<br/>"
        "- They need billing reconciliation, multi-cluster, SSO, SOC 2<br/>"
        "- Their GPUs are subsidized and the waste isn't worth ₹ to them<br/>"
        "- An engineer says \"we'll build it in Grafana\"",
    ]],
    [W / 2, W / 2],
))
s.append(Spacer(1, 6))
s.append(P("<b>Defensibility is low today.</b> The detection logic can be copied, and Datadog shipped a "
           "similar capability this year. Your advantages are distribution (India, INR, founder-led), the "
           "trust model (read-only, self-hosted), and speed. The durable moat has to come later from "
           "real pilot data (calibrated thresholds, per-workload baselines) and from being the tool Indian GPU "
           "clouds bundle.", "Callout"))

# ================================================================= Unit economics
s.append(PageBreak())
s.append(P("4. Unit economics", "H2"))
s.append(P("The product is self-hosted in the customer's cluster, so you pay nothing for compute or storage "
           "per customer. Cost of goods is mostly <b>your support time</b>. All inputs below are assumptions "
           "[A] until pilots produce real data; founder time is costed at ₹1,500/hour [A].", "Body"))

s.append(P("4.1 Per-customer, monthly", "H3"))
s.append(make_table(
    ["Line item", "Starter", "Growth", "Scale", "Enterprise"],
    [
        ["Price / month", "₹9,999", "₹29,999", "₹74,999", "₹2,00,000 [A]"],
        ["Hosting / compute", "₹0", "₹0", "₹0", "₹0"],
        ["Shared tooling (CI, registry, email, domain)", "₹500", "₹500", "₹500", "₹500"],
        ["Support hours / month [A]", "1 h = ₹1,500", "2 h = ₹3,000", "5 h = ₹7,500", "12 h = ₹18,000"],
        ["Payment processing (2%) [A]", "₹200", "₹600", "₹1,500", "₹4,000"],
        ["<b>COGS</b>", "₹2,200", "₹4,100", "₹9,500", "₹22,500"],
        ["<b>Gross profit / month</b>", "<b>₹7,799 (78%)</b>", "<b>₹25,899 (86%)</b>", "<b>₹65,499 (87%)</b>",
         "<b>₹1,77,500 (89%)</b>"],
    ],
    [2.1 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, W - 5.7 * inch],
))

s.append(P("4.2 Acquisition, lifetime value, payback", "H3"))
s.append(make_table(
    ["Metric", "Starter", "Growth", "Scale", "Enterprise"],
    [
        ["CAC: founder-led sales, incl. ~4 free scans per win [A]", "₹40,000", "₹90,000", "₹2,50,000", "₹6,00,000"],
        ["Onboarding (install, 7-day scan, readout) [A]", "4 h = ₹6,000", "8 h = ₹12,000", "16 h = ₹24,000",
         "40 h = ₹60,000"],
        ["<b>Total acquisition cost</b>", "₹46,000", "₹1,02,000", "₹2,74,000", "₹6,60,000"],
        ["Monthly churn [A]", "5%", "3%", "2%", "1.5%"],
        ["Expected lifetime", "20 months", "33 months", "50 months", "67 months"],
        ["<b>LTV</b> (gross profit x lifetime)", "₹1.56 L", "₹8.63 L", "₹32.7 L", "₹1.18 Cr"],
        ["<b>LTV : CAC</b>", "<b>3.4x</b>", "<b>8.5x</b>", "<b>12.0x</b>", "<b>17.9x</b>"],
        ["CAC payback", "5.9 months", "3.9 months", "4.2 months", "3.7 months"],
        ["LTV : CAC if churn doubles", "1.7x", "4.2x", "6.0x", "9.0x"],
    ],
    [2.1 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, W - 5.7 * inch],
))
s.append(Spacer(1, 6))
s.append(P("Rule of thumb: LTV:CAC above 3x and payback under 12 months is healthy. Every tier clears that "
           "on paper, but <b>Starter is marginal</b>: it breaks if churn is higher than assumed, and it "
           "breaks as soon as a paid salesperson replaces founder time. CAC is founder-time CAC; hiring an "
           "account executive at ~₹1.5-2 L/month [A] roughly doubles to triples CAC for the lower tiers.", "Body"))

s.append(KeepTogether([P("4.3 Customer-side ROI: does the price make sense to the buyer?", "H3"), P("Recoverable waste assumed at <b>10% of GPU spend</b> [A]. Basis: the Philly replay flagged "
           "23.0% of GPU-workload-hours as waste [S, own test]; not all flagged waste is recoverable (SLA "
           "headroom, team inertia), so we assume 30-50% of it gets acted on, i.e. ~7-12%. GPU rates are the "
           "product's own illustrative INR defaults (L4 ₹70/h, A100 80GB ₹300/h, H100 SXM ₹520/h), and "
           "IndiaAI's ~₹65/h [S]; 730 hours/month.", "Body"), make_table(
    ["Customer fleet", "GPU spend / month", "Tier", "Price as % of spend", "10% recovered", "ROI (x price)"],
    [
        ["4 x L4", "₹2.04 L", "Starter", "4.9%", "₹20,440", "<b>2.0x</b> (weak)"],
        ["16 x GPUs on IndiaAI subsidy", "₹7.59 L", "Growth", "4.0%", "₹75,920", "<b>2.5x</b> (weak)"],
        ["4 x A100 80GB", "₹8.76 L", "Starter", "1.1%", "₹87,600", "<b>8.8x</b>"],
        ["16 x A100 80GB", "₹35.0 L", "Growth", "0.86%", "₹3.50 L", "<b>11.7x</b>"],
        ["64 x H100 SXM", "₹2.43 Cr", "Scale", "0.31%", "₹24.3 L", "<b>32x</b> (underpriced)"],
    ],
    [1.45 * inch, 1.05 * inch, 0.65 * inch, 1.05 * inch, 1.0 * inch, W - 5.2 * inch],
)]))
s.append(Spacer(1, 6))
s.append(P("<b>Pricing problem:</b> pricing by GPU count ignores that an H100 costs ~7x an L4. Small fleets of "
           "cheap or subsidized GPUs get a weak 2-2.5x return (a 2x ROI is usually not enough for a buyer to "
           "bother), while large H100 fleets pay 0.3% of spend for a 32x return. <b>Recommendation:</b> price "
           "on monitored GPU spend, e.g. ~1% of monitored monthly GPU spend with a ₹9,999 floor and volume "
           "discounts [A]. That keeps ROI around 10x for everyone and grows revenue with the customer's "
           "fleet.", "Callout"))

s.append(P("4.4 Company break-even (solo founder)", "H3"))
s.append(P("You are a solo founder doing engineering and sales, and the product has no hosting cost, so "
           "the company's fixed costs are small [A]:", "Body"))
s.append(make_table(
    ["Monthly fixed cost", "No salary", "With ₹1 L/month personal draw"],
    [
        ["GPU test rentals (occasional)", "₹10-20k", "₹10-20k"],
        ["CA / GST compliance", "₹5-10k", "₹5-10k"],
        ["Tools, domain, email", "₹3-5k", "₹3-5k"],
        ["Travel to customer meetings", "₹10-20k", "₹10-20k"],
        ["Founder draw", "₹0", "₹1,00,000"],
        ["<b>Total (rounded)</b>", "<b>~₹50k</b>", "<b>~₹1.5 L</b>"],
        ["<b>Break-even customers</b> (avg ~₹31,300/month gross profit at the 45/35/15/5 tier mix)",
         "<b>~2</b>", "<b>~5</b>"],
    ],
    [3.1 * inch, 1.3 * inch, W - 4.4 * inch],
))
s.append(Spacer(1, 6))
s.append(P("<b>Your time is the constraint, not money.</b> At ~2.5 support hours per customer per month and "
           "~40% of a 160-hour month on support, one person can look after <b>~25 customers</b>. Winning one "
           "customer takes ~30 hours (about 4 free scans plus onboarding), so ~30 sales hours a month gives "
           "~1 new customer a month, roughly the 3-year SOM. Two levers stretch this: make the free scan "
           "self-serve (cuts a scan from ~6 hours to ~1), and favour Growth tier and above. "
           "<b>First hire</b> (a support engineer, ~₹1.25 L/month): when support passes ~40% of your time or "
           "~20-25 customers (~₹60-75 L ARR).", "Body"))

s.append(P("4.5 What would change these numbers most", "H3"))
s.append(bullets([
    "<b>Churn</b> (the biggest swing factor). If customers treat the product as a one-time audit, lifetime "
    "collapses. Counter-measures: continuous value (weekly ₹ reports, regression alerts when waste returns, "
    "per-team chargeback) and annual contracts.",
    "<b>Free-scan conversion.</b> CAC assumes ~1 in 4 free scans converts. At 1 in 10, lower-tier CAC more "
    "than doubles.",
    "<b>Pilot-proven savings.</b> The whole ROI table rests on the 10% recoverable assumption. The first "
    "pilot's before/after number replaces it.",
    "<b>Moving to action</b> (bin-packing recommendations, queue-depth-aware right-sizing) supports a "
    "higher price and lower churn, but brings you into direct competition with CAST AI and ScaleOps.",
]))

# ================================================================= International
s.append(P("5. International expansion", "H2"))
s.append(P("Overseas buyers tend to run larger GPU fleets and pay in USD, so each customer is worth ~2-6x an "
           "Indian one for broadly similar support effort. That matters most for a solo founder, whose limit is "
           "customer count, not money. Four candidate regions:", "Body"))
s.append(make_table(
    ["Region", "Market signals [S]", "Competition", "Fit for this product"],
    [
        ["<b>SE Asia</b> (Singapore, Malaysia, Indonesia, Philippines)",
         "680+ AI startups, $2.3B AI funding in 12 months (e-Conomy SEA 2025); Malaysia leads SE Asia data-centre "
         "construction (1,039 MW); Aolani + NVIDIA plan 22,000 GPUs in Malaysia/Philippines",
         "Lighter; global tools present but little local focus",
         "<b>Good.</b> Close time zones, similar price sensitivity, new GPU clouds as channel partners"],
        ["<b>Middle East</b> (UAE, Saudi Arabia)",
         "MENA AI startups raised $858M in 2025 (60% UAE); 673 AI companies in Abu Dhabi; HUMAIN ordered 18,000 "
         "GB300 GPUs; G42's Stargate UAE first stage ~400,000 NVIDIA chips",
         "Sovereign buyers work through large integrators; few SaaS tools allowed in",
         "<b>Good for the trust model.</b> Read-only + self-hosted suits sovereign data rules, but needs a "
         "local partner; the mega-fleets are enterprise deals out of solo reach"],
        ["<b>United States</b>",
         "~6,956 AI startups (largest share globally); neocloud revenue >$25B in 2025, projected ~$42B in 2026",
         "<b>Heaviest:</b> CAST AI, ScaleOps, Datadog, Kubecost all sell here",
         "<b>Largest pool, hardest sale.</b> Target neocloud/on-prem GPU users, not EKS/GKE teams; SOC 2 required"],
        ["<b>EU + UK</b>",
         "~1,192 GenAI companies in Europe; UK 800+ AI startups, France 468, Germany 394",
         "CAST AI (EU-founded), Datadog, Kubecost",
         "<b>Moderate.</b> Data-residency rules favour self-hosted; GDPR paperwork; SOC 2 / ISO 27001 expected"],
    ],
    [1.05 * inch, 2.3 * inch, 1.35 * inch, W - 4.7 * inch],
))

s.append(KeepTogether([P("5.1 TAM, SAM, SOM by region (bottom-up, at this product's prices)", "H3"), P("Pricing assumed at ~1% of monitored GPU spend in USD. Org counts and average contract values are "
           "our assumptions [A], anchored on the startup and funding counts above [S]. SAM keeps orgs on "
           "Kubernetes (CNCF: 66% of GenAI hosts [S]) and, in the US and EU, only the share that values a "
           "read-only, self-hosted tool or runs on neocloud/on-prem clusters.", "Body"), make_table(
    ["Region", "Orgs with GPU fleets [A]", "Avg contract / yr [A]", "TAM", "SAM filter [A]", "SAM", "3-yr SOM [A]"],
    [
        ["India", "~1,800", "₹3-4.35 L", "₹78 Cr ($8.9M)", "50% on K8s", "₹38 Cr ($4.4M)", "30 cust, ₹0.90 Cr"],
        ["SE Asia", "~370", "$8k (₹7 L)", "₹26 Cr ($3.0M)", "55% on K8s", "₹14 Cr ($1.6M)", "6 cust, ₹0.42 Cr"],
        ["Middle East", "~250", "$20k (₹17.6 L)", "₹44 Cr ($5.0M)", "55% on K8s", "₹24 Cr ($2.8M)", "3 cust, ₹0.53 Cr"],
        ["United States", "~4,200", "$15k (₹13.2 L)", "₹554 Cr ($63M)", "66% K8s x 40% fit", "₹146 Cr ($16.6M)", "4 cust, ₹0.53 Cr"],
        ["EU + UK", "~1,500", "$12k (₹10.6 L)", "₹158 Cr ($18M)", "60% K8s x 50% fit", "₹48 Cr ($5.4M)", "2 cust, ₹0.21 Cr"],
        ["<b>Intl. only</b>", "~6,300", "", "<b>₹783 Cr ($89M)</b>", "", "<b>₹233 Cr ($26.4M)</b>",
         "<b>15 cust, ₹1.69 Cr</b>"],
        ["<b>India + intl.</b>", "~8,100", "", "<b>~₹860 Cr ($98M)</b>", "", "<b>~₹270 Cr ($31M)</b>",
         "<b>45 cust, ~₹2.6 Cr</b>"],
    ],
    [0.95 * inch, 0.85 * inch, 0.95 * inch, 0.95 * inch, 0.95 * inch, 0.95 * inch, W - 5.6 * inch],
    bold_last=True,
)]))
s.append(Spacer(1, 6))
s.append(P("<b>Consistency check:</b> the bottom-up total (~$98M) is about 22% of the ~$446M global top-down TAM "
           "in section 2.1. The top-down figure also counts very large hyperscaler customers, automation "
           "platforms' revenue and spend this product can't serve, so a bottom-up number well below it is "
           "expected. <b>Why SOM is small abroad:</b> 15 overseas customers is 0.4-3% of each region's SAM, "
           "limited by one founder's selling time, not by demand.", "Small"))

s.append(PageBreak())
s.append(P("6. Comparison: India only vs. India + international (year 3)", "H2"))
s.append(P("Same total of 45 customers in both cases, since one founder plus one or two support engineers "
           "can't handle many more. Figures in ₹ lakh per year; all costs are assumptions [A].", "Body"))
s.append(make_table(
    ["", "India only (45 India)", "India + international (30 India + 15 abroad)"],
    [
        ["<b>Revenue (ARR)</b>", "<b>135</b>", "<b>259</b>"],
        ["Payment processing (+ FX abroad)", "2.7 (2%)", "6.5 (2.5%)"],
        ["CI, registry, tooling", "1.0", "1.5"],
        ["Support engineers", "15 (one)", "30 (two; one covering US/EU hours)"],
        ["<b>Gross profit</b>", "<b>116 (86%)</b>", "<b>221 (85%)</b>"],
        ["SOC 2 / security certification", "4", "20 (required by overseas buyers)"],
        ["US company + US accountant", "0", "3"],
        ["Travel", "2.4", "12 (2-3 overseas trips)"],
        ["Conferences (attend, not exhibit)", "0", "5"],
        ["CA, legal, tools, GPU testing", "3.6", "6"],
        ["<b>Profit before your salary</b>", "<b>106 (79%)</b>", "<b>175 (68%)</b>"],
        ["Your salary (₹2 L/month)", "24", "24"],
        ["Corporate tax (~25%)", "21", "38"],
        ["<b>Net profit</b>", "<b>62 (46%)</b>", "<b>113 (44%)</b>"],
    ],
    [2.3 * inch, 1.9 * inch, W - 4.2 * inch],
))
s.append(Spacer(1, 6))
s.append(make_table(
    ["", "India only", "India + international"],
    [
        ["TAM / SAM", "₹78 Cr / ₹38 Cr", "~₹860 Cr / ~₹270 Cr"],
        ["Avg revenue per customer", "₹3 L", "₹5.8 L"],
        ["Competition", "Light; INR pricing and local presence are real advantages",
         "Heavy in the US; your edge narrows to read-only / self-hosted / neocloud"],
        ["Fixed costs to enter", "Minimal", "SOC 2, US entity, travel, conferences, 2nd support engineer: ~₹50 L/yr extra"],
        ["Sales cycle and trust", "Shorter; in-person possible", "Longer; security reviews; solo-founder risk questions"],
        ["Can you stay solo?", "Until ~25 customers", "Needs a support hire earlier because of time zones"],
        ["Risk if it goes badly", "Low: costs stay small", "Higher: ~₹50 L/yr of fixed costs before overseas revenue"],
    ],
    [1.6 * inch, 2.3 * inch, W - 3.9 * inch],
))
s.append(Spacer(1, 6))
s.append(P("<b>Recommendation: sequence it, don't choose.</b> (1) Now to year 1: India only. Get pilot-proven "
           "savings and 2-3 written case studies; you need them anywhere. (2) Years 1-2: SE Asia and the "
           "Middle East, sold remotely and through GPU-cloud partners; close time zones and a trust model that "
           "suits sovereign buyers. (3) Years 2-3: US and EU, once SOC 2 and case studies exist, targeting "
           "neocloud and on-prem GPU users rather than EKS/GKE teams already on CAST AI. This keeps the ~₹50 L/yr "
           "of international fixed costs until revenue can pay for them.", "Callout"))

# ================================================================= Reconciliation
s.append(PageBreak())
s.append(P("7. Reconciling with the earlier market study", "H2"))
s.append(P("An earlier study, <i>India GPU Optimization SaaS: SMB Market Research</i> (September 2026), sized "
           "the same opportunity much larger. Both are planning estimates built on assumptions; the difference is "
           "mostly <b>what product is being sized</b> and <b>who is selling it</b>, not a disagreement about the "
           "market.", "Body"))
s.append(make_table(
    ["", "Earlier study (base case)", "Earlier study, price corrected [A]", "This report (India, as built)"],
    [
        ["Product sized", "Full plan: Kubernetes + GPU VMs, billing, approve-then-act fixes, verified savings, "
                          "multi-cluster", "Same full plan", "Kubernetes only; detect and recommend; read-only"],
        ["Seller", "A team", "A team", "One founder"],
        ["Orgs (TAM / SAM)", "12,000 / 3,000", "12,000 / 3,000", "1,800 / 885"],
        ["Avg contract / yr", "₹7.2 L (₹60k/month)", "₹4.35 L", "₹4.35 L list, ₹3 L realized"],
        ["TAM", "₹720 Cr (range 250-1,750)", "₹522 Cr", "₹78-190 Cr"],
        ["SAM", "₹216 Cr (range 60-600)", "₹130 Cr", "₹38 Cr"],
        ["SOM, year 3", "100 customers, ₹7.2 Cr (range 1.2-30)", "100 customers, ₹4.35 Cr",
         "27-45 customers, ₹0.8-1.35 Cr"],
    ],
    [1.15 * inch, 1.95 * inch, 1.6 * inch, W - 4.7 * inch],
))
s.append(Spacer(1, 6))
s.append(P("7.1 Why the numbers differ", "H3"))
s.append(bullets([
    "<b>Product scope.</b> The earlier study includes teams running GPUs on plain VMs without Kubernetes, which "
    "the current product can't serve. That alone roughly halves the reachable market [A].",
    "<b>Organisation count.</b> 12,000 vs ~1,800. Neither is sourced; the earlier study says so itself. 12,000 "
    "likely includes occasional single-GPU renters who won't pay for optimisation; 1,800 counts dedicated fleets "
    "built up from Nasscom's ~890 GenAI startups plus enterprises and labs. The real number is probably between.",
    "<b>Average price.</b> ₹60k/month implies most customers on the 26-100 GPU Scale tier, which contradicts the "
    "study's own 1-50 GPU SMB target and its ₹9,999 / ₹29,999 / ₹74,999 tiers. At the tier mix used here the "
    "blended price is ₹4.35 L/yr; that correction alone cuts the earlier TAM and SAM by ~28%.",
    "<b>Seller capacity.</b> 100 customers in 3 years is ~4x what one founder can support (~25). The earlier "
    "study's upside (300 accounts, ₹30 Cr) needs a sales and support team. At the low end the two agree: its "
    "conservative ₹1.2 Cr SOM sits between this report's base (₹1.05 Cr) and stretch (₹1.35 Cr).",
]))
s.append(KeepTogether([P("7.2 The gap is the roadmap", "H3"),
    P("Each missing feature widens the market the product can serve or raises what each customer pays. "
      "Effects are rough assumptions [A] to size priorities, not forecasts.", "Body"),
    make_table(
    ["Feature (in earlier study, not built)", "What it unlocks", "Effect on market / price [A]", "When"],
    [
        ["Reuse an existing dcgm-exporter (Helm value)", "Neocloud and GPU-Operator clusters that already run "
         "one", "Removes an install blocker; no new segment", "Now (hours)"],
        ["GPU VM support (no Kubernetes)", "Teams renting bare GPU VMs, common on Indian GPU clouds",
         "SAM roughly 2x (₹38 Cr to ~₹75 Cr)", "If pilots show demand"],
        ["Cloud / GPU-cloud billing integration", "Real invoice costs instead of rate tables; before/after "
                                                  "savings proof", "Enables a verified-savings fee (10-15% of "
         "savings); lowers churn", "After first pilots"],
        ["Savings verification (baseline vs after)", "Proof the fixes worked", "Turns the 10% assumption into "
         "a measured number; supports 2% pricing", "With billing"],
        ["Approve-then-act fixes (Slack/Jira, rollback, audit)", "Engineers approve a change, product applies "
         "it", "~1.5x price; less one-time-audit churn", "Year 1-2"],
        ["Serving metrics (queue depth, TTFT, cost per token)", "Inference teams that care about latency",
         "Stronger fit for inference buyers; safer right-sizing", "Year 1-2"],
        ["Multi-cluster, SSO, audit export", "Scale and Enterprise tiers", "Unlocks ₹75k+/month deals", "Year 2"],
    ],
    [1.75 * inch, 1.75 * inch, 1.75 * inch, W - 5.25 * inch],
)]))
s.append(Spacer(1, 6))
s.append(P("<b>How to use the two documents.</b> Use this report to plan the business you are running now "
           "(costs, break-even, when to hire). Use the earlier study's framing to describe the long-term "
           "vision to investors or partners, with the corrected ₹4.35 L average price and its organisation "
           "counts labelled as assumptions. The earlier study's positioning, free-scan offer, GPU-cloud "
           "partnerships and validation plan (20 interviews, 5 read-only pilots, 2 paid pilots with verified "
           "15-25% savings) remain the right next steps.", "Callout"))

# ================================================================= Assumptions + sources
s.append(PageBreak())
s.append(P("8. Assumptions ledger", "H2"))
s.append(make_table(
    ["#", "Assumption", "Value", "Why / how to validate"],
    [
        ["A1", "USD/INR", "₹88", "Approximate 2025-26 rate"],
        ["A2", "GPU share of Kubernetes cost-management spend", "15-25%", "Datadog: GPUs 14% of compute cost and "
                                                                            "rising; GPU nodes cost more per hour"],
        ["A3", "Indian orgs running dedicated NVIDIA GPU fleets", "~1,800", "Built from Nasscom startup counts + "
                                                                              "estimates; validate via GPU-cloud "
                                                                              "partner conversations"],
        ["A4", "Share of those on Kubernetes", "50%", "Below CNCF's 66%; ask every prospect"],
        ["A5", "Tier mix of customers", "45/35/15/5", "Skewed small; replace with pipeline data"],
        ["A6", "Enterprise price", "₹2 L/month", "Custom tier; placeholder"],
        ["A7", "Realized ACV", "₹3.0 L", "Discounts + small-customer skew"],
        ["A8", "Founder time value", "₹1,500/hour", "Opportunity cost placeholder"],
        ["A9", "Support / onboarding hours", "See 4.1-4.2", "Measure on first pilots"],
        ["A10", "CAC per tier", "₹40k to ₹6 L", "Founder-led, ~4 free scans per win"],
        ["A11", "Monthly churn", "1.5-5%", "Biggest uncertainty; see 4.5"],
        ["A12", "Recoverable waste", "10% of GPU spend", "From Philly 23% flagged x 30-50% acted on; prove in pilot"],
        ["A13", "Monthly fixed costs (solo founder)", "₹50k-1.5 L", "With or without a ₹1 L personal draw"],
        ["A14", "3-year SAM capture (India)", "3-5%", "Typical for founder-led B2B infrastructure software"],
        ["A15", "Overseas orgs with GPU fleets", "SEA 370, ME 250, US 4,200, EU 1,500",
         "Anchored on startup counts in section 5; validate with regional partners"],
        ["A16", "Overseas average contract", "$8k-20k/yr", "~1% of monitored GPU spend; larger fleets abroad"],
        ["A17", "Overseas SAM filters", "55-66% on K8s; 40-50% fit in US/EU", "Share that values read-only, "
                                                                               "self-hosted or runs neocloud/on-prem"],
        ["A18", "International entry costs", "~₹50 L/yr", "SOC 2, US entity, travel, conferences, 2nd support hire"],
        ["A19", "Solo support capacity", "~25 customers", "2.5 h/customer/month, 40% of time on support"],
    ],
    [0.4 * inch, 2.2 * inch, 1.1 * inch, W - 3.7 * inch],
))

s.append(P("9. Sources", "H2"))
src = [
    "Gartner, India public cloud forecast (Jun 2026): gartner.com/en/newsroom/press-releases/2026-06-01-gartner-"
    "forecasts-end-user-public-cloud-spending-in-india-to-surpass-17-billion-us-dollars-in-2026",
    "MarkNtel Advisors, India Data Center GPU Market 2025-2032 (via prior research).",
    "Nasscom, India Generative AI Startup Landscape 2025: nasscom.in/knowledge-center/publications/india-"
    "generative-ai-startup-landscape-2025-mapping-momentum",
    "PIB (Government of India), IndiaAI Mission compute update: pib.gov.in/PressReleasePage.aspx?PRID=2245069",
    "Introl, India GPU infrastructure survey (80,000+ GPUs): introl.com/blog/indias-gpu-infrastructure-"
    "landscape-a-comprehensive-survey",
    "MarketsandMarkets, GPU-as-a-Service market 2025-2030 (via prior research).",
    "Kubernetes cost management market (TBRC via Research and Markets / GII Research; GM Insights; Growth "
    "Market Reports): researchandmarkets.com/reports/6215668/kubernetes-cost-management-market-report",
    "CNCF 2025 Annual Cloud Native Survey (66% use K8s for GenAI inference): cncf.io/announcements/2026/01/20/",
    "Datadog GPU Monitoring GA (Apr 22, 2026): datadoghq.com/about/latest-news/press-releases/datadog-gpu-"
    "monitoring-launch/",
    "CAST AI $1B valuation, GPU marketplace (Jan 2026): siliconangle.com/2026/01/12/cast-ai-raises-funds-pacific-"
    "alliance-ventures-1b-valuation-launch-unified-gpu-marketplace/ ; multiples.vc/private-comps/cast-ai",
    "CAST AI pricing (third-party): usage.ai/blogs/finops/tools/cast-ai-pricing/",
    "ScaleOps $130M Series C (Mar 30, 2026): prnewswire.com/news-releases/scaleops-raises-130m-series-c-at-over-"
    "800m-valuation-...-302728822.html ; thenextweb.com/news/scaleops-130m-series-c",
    "IBM acquires Kubecost (Sep 17, 2024): techcrunch.com/2024/09/17/ibm-acquires-kubernetes-cost-optimization-"
    "startup-kubecost/",
    "Kubecost pricing (third-party): trustradius.com/products/ibm-kubecost/pricing",
    "DoiT acquires PerfectScale (Feb 2025): businesswire.com/news/home/20250203440309/en/",
    "NVIDIA open-sources KAI Scheduler: developer.nvidia.com/blog/nvidia-open-sources-runai-scheduler-to-foster-"
    "community-collaboration/",
    "Bain, Google, Temasek, e-Conomy SEA 2025 (680+ AI startups, $2.3B AI funding): bain.com/insights/e-conomy-sea-2025/",
    "SE Asia data-centre pipeline (Malaysia 1,039 MW under construction): technode.global/2026/05/12/asia-pacific-"
    "ai-driven-data-center-boom-reshapes-southeast-asia-landscape/ ; Aolani + NVIDIA 22,000 GPUs: "
    "technode.global/2026/09/22/aolani-nvidia-22000-gpu-ai-infrastructure-southeast-asia/",
    "MENA AI funding $858M in 2025 (MAGNiTT): enterpriseam.com/ksa/2026/02/15/mena-ai-funding-hits-usd-858-mn-in-2025-"
    "led-by-the-uae-and-saudi-arabia/ ; Abu Dhabi 673 AI companies: startupgenome.com/insights/abu-dhabis-rise-"
    "as-a-global-ai-and-startup-capital",
    "HUMAIN and G42 GPU deployments: restofworld.org/2026/gulf-ai-investment-nvidia-monopoly-blackwell/ ; "
    "presenc.ai/research/sovereign-ai-infrastructure-tracker-2026",
    "Neocloud revenue >$25B in 2025 (DCD) and ~$42B 2026 projection (Research and Markets): "
    "datacenterdynamics.com/en/news/neocloud-revenue-exceeds-25bn-in-2025/ ; "
    "researchandmarkets.com/reports/6225920/neocloud-global-market-report",
    "AI startup counts, US and Europe (StartUs Insights, StartupBlink): startus-insights.com/innovators-guide/"
    "how-many-ai-companies-are-there/ ; startupblink.com/blog/top-ai-startups/",
    "Earlier study: India GPU Optimization SaaS: SMB Market Research (September 2026), provided by the founder.",
    "Own test results: testing/real-trace-replay/RESULTS.md (Philly, 23.0% flagged); "
    "testing/azure-inference-trace-replay/RESULTS.md; PROGRESS.md.",
]
s.append(ListFlowable([ListItem(P(x, "Small"), bulletColor=colors.black) for x in src], bulletType="bullet", start="•", leftIndent=12, spaceAfter=4))
s.append(P("Market-research-firm figures differ substantially between publishers; treat them as ranges. "
           "Competitor pricing marked third-party was not confirmed on the vendor's own pricing page.", "Small"))

doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("ok")
