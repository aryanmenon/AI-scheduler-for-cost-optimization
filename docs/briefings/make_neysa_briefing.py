"""Build docs/briefings/neysa-cto-briefing.pdf: a founder-only, skimmable
briefing for a conversation with Neysa's CTO -- the product under the hood,
every finding's recommendation, and how it could fit with Neysa Velocis.
Contains internals (thresholds, sizing rules): do not share before an NDA.

  python3 docs/briefings/make_neysa_briefing.py
"""
from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "neysa-cto-briefing.pdf")

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("Sans", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")

INK = colors.HexColor("#1B2733")
MUTED = colors.HexColor("#5B6875")
ACCENT = colors.HexColor("#1F6F8B")
ACCENT_SOFT = colors.HexColor("#E8F2F6")
RULE = colors.HexColor("#D5DDE3")
WARN = colors.HexColor("#B4501E")
WARN_SOFT = colors.HexColor("#FBEFE7")
GOOD = colors.HexColor("#2E7D4F")
GOOD_SOFT = colors.HexColor("#E9F5EE")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
W = PAGE_W - 2 * MARGIN


def st(name, **kw):
    base = dict(fontName="Sans", fontSize=9.2, leading=12.8, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


TITLE = st("t", fontName="Sans-Bold", fontSize=22, leading=26)
SUB = st("s", fontSize=11, leading=15, textColor=MUTED)
H1 = st("h1", fontName="Sans-Bold", fontSize=15, leading=19, textColor=ACCENT, spaceBefore=4, spaceAfter=6)
H2 = st("h2", fontName="Sans-Bold", fontSize=11.2, leading=14.5, textColor=INK, spaceBefore=9, spaceAfter=4)
BODY = st("b", spaceAfter=4)
SMALL = st("sm", fontSize=7.8, leading=10.4, textColor=MUTED)
CELL = st("c", fontSize=8.2, leading=10.9)
CELLB = st("cb", fontName="Sans-Bold", fontSize=8.2, leading=10.9)
CELLH = st("ch", fontName="Sans-Bold", fontSize=8, leading=10.4, textColor=colors.white)
BUL = st("bul", leftIndent=10, bulletIndent=0, spaceAfter=2.4, bulletFontName="Sans",
         bulletFontSize=6, bulletColor=ACCENT)
BOXH = st("bh", fontName="Sans-Bold", fontSize=10.5, leading=13.5)


def P(text, style=BODY):
    return Paragraph(text, style)


def bullets(items, style=BUL):
    return [Paragraph(t, style, bulletText="●") for t in items]


def box(flowables, fill, border):
    t = Table([[flowables]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 3, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def table(header, rows, widths, first_col_bold=True):
    data = [[P(h, CELLH) for h in header]]
    for row in rows:
        data.append([P(c, CELLB if (i == 0 and first_col_bold) else CELL) for i, c in enumerate(row)])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_SOFT]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return t


def flow_diagram():
    stages = [
        ("1. Collect", "telemetry-collector: scrapes DCGM every 30 s"),
        ("2. Normalise", "ingestion: cleans, adds GPU specs, rolls up 5 min / hourly / daily"),
        ("3. Detect", "waste-detector: rule-based detectors, every 5 min"),
        ("4. Price", "savings-estimator: ₹ per finding, right-sizing checks"),
        ("5. Report", "dashboard: HTML report, bearer token"),
    ]
    cells = []
    for i, (name, what) in enumerate(stages):
        cells.append([P(f"<b>{name}</b>", CELL), P(what, SMALL)])
        if i < len(stages) - 1:
            cells.append([P("→", st("arr", fontName="Sans-Bold", fontSize=13, leading=14, textColor=ACCENT))])
    widths = []
    row = []
    for c in cells:
        if len(c) == 1:
            row.append(c[0]); widths.append(5 * mm)
        else:
            row.append(c); widths.append((W - 4 * 5 * mm) / 5)
    t = Table([row], colWidths=widths)
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    for col in range(0, len(row), 2):
        style += [("BACKGROUND", (col, 0), (col, 0), ACCENT_SOFT), ("BOX", (col, 0), (col, 0), 0.6, ACCENT)]
    t.setStyle(TableStyle(style))
    return t


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(ACCENT)
    canvas.rect(0, PAGE_H - 5 * mm, PAGE_W, 5 * mm, stroke=0, fill=1)
    canvas.setFont("Sans", 7.3)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 9 * mm, "Neysa CTO briefing · founder only · contains internals: do not share before an NDA")
    canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def build():
    s = []

    # ------------------------------------------------------------ page 1
    s += [
        P("FOUNDER-ONLY BRIEFING · OCTOBER 2026", st("k", fontName="Sans-Bold", fontSize=8, textColor=ACCENT)),
        Spacer(1, 2),
        P("Meeting Neysa's CTO", TITLE),
        Spacer(1, 3),
        P("Your product under the hood, every recommendation it makes, and how it could fit with "
          "Neysa Velocis. Skim page 1; the rest is reference.", SUB),
        Spacer(1, 9),
        box([
            P("Read this first", BOXH), Spacer(1, 4),
            *bullets([
                "<b>The pitch:</b> “Command Center shows what's happening. We tell each team what to "
                "change, what it saves in ₹, and what it costs them in latency.” You're a decision layer on "
                "their data layer, not a second monitoring tool.",
                "<b>What it is:</b> a read-only Helm chart, inside the customer's Kubernetes cluster. It "
                "reads NVIDIA DCGM metrics, links each GPU to its pod, classifies waste with fixed rules and "
                "prices it at the customer's own ₹ rates. It recommends; it never acts.",
                "<b>Evidence:</b> live on GKE (L4) and a k3s RTX 3090 cluster (full pilot rehearsal, all 6 "
                "checks passed); Microsoft Philly trace (15.6% of GPU-hours with a headline recommendation); "
                "Azure LLM trace (19,366/19,366 requests served); right-sizing tested on real GPUs.",
                "<b>The ask:</b> a free pilot on ONE cluster: one of Neysa's own managed-service clusters, or "
                "one willing VKE customer. Pilot agreement signed first.",
            ]),
        ], ACCENT_SOFT, ACCENT),
        Spacer(1, 8),
        box([
            P("Watch out", st("wh", fontName="Sans-Bold", fontSize=10.5, leading=13.5, textColor=WARN)),
            Spacer(1, 4),
            *bullets([
                "<b>H200, B200 and GH200 are not recognised yet.</b> Findings on them show no ₹ figure. H100, "
                "L40S and L4 work. Don't demo on H200. About a 30-minute fix plus tests, before any pilot.",
                "<b>Don't share internals before an NDA.</b> They collect the same DCGM data and could build "
                "this. Talk outcomes and evidence; hold back thresholds and sizing formulas.",
                "<b>Velocis VMs, bare metal and Slurm aren't supported</b> (Kubernetes only). Don't promise them.",
                "<b>Expect the conflict question:</b> “you tell our customers to use fewer GPUs.” "
                "Answers on page 6.",
            ], st("bw", parent=BUL, bulletColor=WARN)),
        ], WARN_SOFT, WARN),
        Spacer(1, 8),
        box([
            P("Ask them", st("ah", fontName="Sans-Bold", fontSize=10.5, leading=13.5, textColor=GOOD)),
            Spacer(1, 4),
            *bullets([
                "Does Command Center make recommendations today, or only show data? Is it on the roadmap?",
                "How do customers split between VKE, VMs, bare metal and Slurm?",
                "What's utilisation on your own managed inference fleet? Would you pilot it there?",
                "Are you capacity-constrained? Would freed GPUs be resold?",
            ], st("ba", parent=BUL, bulletColor=GOOD)),
        ], GOOD_SOFT, GOOD),
        PageBreak(),
    ]

    # ------------------------------------------------------------ under the hood
    s += [
        P("1. Under the hood", H1),
        P("Five services in <b>one pod</b> sharing one 5 GiB volume. Each has its own SQLite database, reads "
          "the previous stage's database read-only and writes only its own. Python, shipped as compiled "
          "native code (no source in the images)."),
        Spacer(1, 3),
        flow_diagram(),
        P("DCGM exporter (one per GPU node) and kube-state-metrics feed stage 1.", SMALL),

        P("What it measures", H2),
        *bullets([
            "<b>DCGM fields:</b> GPU utilisation, framebuffer memory used and free, power draw, SM clock.",
            "<b>“Utilisation” is busy time:</b> DCGM GPU_UTIL is the share of time any kernel runs, not compute "
            "used. An LLM server reads 70–100% whenever one request is in flight. That's why the "
            "average-load detector exists.",
            "<b>GPU-to-pod link:</b> dcgm-exporter reads the kubelet pod-resources socket (namespace, pod, "
            "container). The <b>workload</b> (Deployment/StatefulSet/Job) is derived from the pod-name pattern, "
            "so history survives rescheduling. Honest detail: owner references aren't read yet; kube-state-"
            "metrics is scraped but not used yet.",
            "<b>Per-node scraping</b> through a headless Service, so every node's exporter is read.",
        ]),
        P("Processing", H2),
        *bullets([
            "Bad values (NaN, out of range) rejected. Each GPU model matched to FP16 TFLOPS, memory bandwidth "
            "and memory size. MIG instances tracked separately.",
            "Rolled up into 5-minute, hourly and daily summaries per GPU per workload.",
            "<b>Coverage:</b> every hour records the share of expected scrapes that arrived. Detectors ignore "
            "hours under 80% coverage: missing data is “unknown”, never “idle”.",
            "Retention: raw 14 days, cleaned samples 3 days, summaries and findings 90 days.",
        ]),
        P("Running it, and security", H2),
        *bullets([
            "<b>Install:</b> helm install into one namespace, ~15 min. ~0.2 CPU and ~0.6 GiB requested for the main pod.",
            "<b>Permissions:</b> get/list/watch on pods, nodes, namespaces only. The collector has no Kubernetes API token.",
            "<b>Hardening:</b> non-root, read-only file systems. Report via kubectl port-forward with a rate-limited bearer token.",
            "<b>No privileged pod</b> if the cluster already runs dcgm-exporter (GPU Operator): it reuses it.",
            "<b>No data leaves the cluster</b>, except an optional alert webhook the customer configures.",
            "Liveness checks on every service; webhook alert when a service keeps failing.",
        ]),
        P("Evidence you can quote", H2),
        table(["Test", "Result"], [
            ["Live clusters", "GKE (L4); k3s RTX 3090 pilot install rehearsal: all 6 checks passed, survived a node "
                              "reboot, upgraded in place with data intact, found and fixed a real bug"],
            ["Microsoft Philly training trace", "15.6% of GPU-hours carry a headline recommendation"],
            ["Azure LLM inference trace", "19,366/19,366 requests served; over-provisioning finding fired"],
            ["Right-sizing on real GPUs", "Compute-only sizing failed (RTX 3090 → T4 was 2.3x slower vs 1.1x "
                                          "predicted). Fixed with the bandwidth check; the fix held on an RTX 4060 Ti "
                                          "(predicted up to 3.25x, measured 1.72x)"],
            ["Automated tests", "351 tests, run in CI against the compiled code"],
        ], [44 * mm, W - 44 * mm]),
        PageBreak(),
    ]

    # ------------------------------------------------------------ detectors + money
    s += [
        P("2. Findings and recommendations", H1),
        P("Every threshold below is a Helm setting the customer can change. An hour counts only with ≥ 80% "
          "coverage; a finding is priced only with average coverage ≥ 0.7."),
        P("How findings are grouped in the report", H2),
        table(["Group", "Findings", "In the headline?"], [
            ["Already wasted (observed)", "Idle", "Yes: money already spent"],
            ["Monthly, if usage continues (projected)", "Over-provisioned; Oversized by average load; Recurring quiet hours", "Yes"],
            ["Review candidates (upper bound)", "Fragmentation; Multi-GPU job could use fewer GPUs", "No, shown separately"],
            ["Detected, no recommendation yet", "Under-use; GPU time with no pod", "No, shown last"],
        ], [52 * mm, W - 52 * mm - 36 * mm, 36 * mm]),
        P("<b>Headline counting:</b> one action per GPU — alternatives on the same GPU aren't added; the "
          "GPU's largest estimate counts. Recurring quiet hours add up with each other, then compete as one "
          "alternative. Idle amounts are summed (separate windows of money already spent).", SMALL),
        P("<b>No ₹ figure (“none -- not priceable”)</b> when: the GPU model isn't in the spec table (today "
          "H200, B200, GH200); there's no rate; the recommended GPU has no rate; or it's right-sizing on a "
          "MIG slice.", SMALL),

        P("Every finding at a glance", H2),
        table(["Finding", "Fires when", "Recommendation (exact text)", "₹ figure"], [
            ["1. Idle GPU", "Average <b>and</b> peak ≤ 2% in every hour, for ≥ 4 consecutive hours. Any burst breaks it.",
             "“terminate or reclaim this idle GPU allocation”",
             "Idle hours × ₹/hr. Already spent, not projected."],
            ["2. Over-provisioned", "Peak ≤ 30% over ≥ 24 observed hours.",
             "“right-size to &lt;GPU&gt; (&lt;cautions&gt;)”",
             "(current ₹/hr − target ₹/hr) × 730 h/month"],
            ["3. Oversized by average load (LLM servers)", "Peak &gt; 30% but busiest hour's average ≤ 30%, over ≥ 24 h.",
             "Same “right-size to …”, sized against a stricter 50% target",
             "Same formula as 2"],
            ["4. Recurring quiet hours", "Same hour of day (UTC) ≤ 5% on ≥ 80% of ≥ 7 observed days.",
             "“scale down or scale to zero during this recurring low-usage window”",
             "Share of quiet days × 30 days × ₹/hr, per hour slot; slots add up"],
            ["5. Fragmentation (review)", "≥ 2 GPUs on one node, from ≥ 2 workloads, each ≤ 50% at once, for ≥ 4 h.",
             "“review whether this workload can share a GPU … (needs GPU sharing via time-slicing, MPS, or MIG; memory fit not checked)”",
             "Rate × (1 − avg util) × 50% capture × 730. Upper bound."],
            ["6. Multi-GPU job could use fewer GPUs (review)", "Job's combined busy time fits on fewer GPUs at 70% each, for ≥ 4 h.",
             "“review whether this multi-GPU job can run on fewer GPUs (check memory fit, batch size and run time; …)”",
             "Rate × fraction releasable × 50% × 730, per GPU. Upper bound."],
            ["7. Under-used, no recommendation", "Attributed GPU-hour below the 70% target, not covered by any other finding.",
             "“none yet -- detected waste without a reliable recommendation; review manually”",
             "Rate × shortfall below 70% × hours. Already spent."],
            ["8. GPU time with no pod", "Same as 7, for GPUs not linked to any pod.",
             "Same as 7; says “unassigned GPU on a running node or work running outside Kubernetes”",
             "Same as 7"],
        ], [33 * mm, 44 * mm, W - 33 * mm - 44 * mm - 40 * mm, 40 * mm]),
        PageBreak(),
    ]

    # ------------------------------------------------------------ right-sizing engine
    s += [
        P("3. The right-sizing engine (findings 2 and 3)", H1),
        *bullets([
            "<b>Need:</b> current capacity × observed load ÷ target (70%; 50% for the average-load finding), "
            "computed for both <b>FP16 compute</b> and <b>memory bandwidth</b>.",
            "<b>Memory:</b> if peak memory use is known, the target's usable memory (93% of spec) must hold "
            "the peak + 10%.",
            "<b>Pick:</b> the smallest datacenter GPU that passes every check. Consumer GPUs are never suggested as targets.",
            "<b>Slowdown caution:</b> the larger of the compute and bandwidth drops: “each request may take up to "
            "~Nx longer -- fine for batch/offline work, check latency targets before moving an interactive service”.",
            "<b>“memory fit not checked”</b> when the workload holds ≥ 85% of GPU memory (vLLM/TensorFlow "
            "pre-allocate) or there's no memory data.",
            "<b>When nothing fits:</b> “none -- no smaller known SKU meets the SLA ceiling” at ₹0.",
        ]),
        P("Real outputs from the engine (A100 80GB at ₹300/hr)", H2),
        table(["Situation", "Target", "Cautions", "Monthly saving"], [
            ["Peak 20%, no memory data", "A10", "~3.4x slower; memory fit not checked (24 GB vs 80 GB)", "(₹300 − ₹105) × 730 = ₹1,42,350"],
            ["Peak 20%, peak memory 18 GiB", "A10", "~3.4x slower; memory checked (needs 19.8 GiB, fits)", "₹1,42,350"],
            ["Peak 20%, holds 92% of memory (vLLM)", "A10", "~3.4x slower; memory fit not checked (pre-allocation)", "₹1,42,350"],
            ["Busiest-hour average 25% (finding 3)", "A100 40GB", "~1.3x slower; memory fit not checked (40 GB vs 80 GB)", "(₹300 − ₹220) × 730 = ₹58,400"],
        ], [46 * mm, 22 * mm, W - 46 * mm - 22 * mm - 45 * mm, 45 * mm]),
        P("Example idle: 6 h on an A100 80GB at ₹300 = ₹1,800 already wasted. Example quiet hours: 90% of days "
          "at 03:00 on an L4 at ₹70 = 27 h × ₹70 = ₹1,890/month.", SMALL),

        P("Limits a CTO might probe", H2),
        *bullets([
            "<b>“Smallest” is by specs, not price.</b> With some rate cards the target costs the same or more and the saving shows ₹0 (e.g. RTX 3090 → T4).",
            "<b>The slowdown is an upper bound from specs</b>, not measured. In our real test: predicted up to 3.25x, measured 1.72x.",
            "<b>No right-sizing on MIG slices:</b> DCGM doesn't report slice size, so it says “not priceable” rather than guess.",
            "<b>Recurring patterns use UTC hours</b> (03:00 UTC = 08:30 IST).",
            "<b>Known cosmetic issue:</b> a 0%-peak idle GPU also appears under Over-provisioned at ₹0 with “none”. Logged, to fix.",
            "<b>H100 NVL</b> is matched to H100 SXM specs (understates memory: 94 GB, not 80 GB).",
        ]),
        PageBreak(),
    ]

    # ------------------------------------------------------------ Neysa fit
    s += [
        P("4. How it fits with Neysa Velocis", H1),
        P("What Velocis already has (public sources)", H2),
        *bullets([
            "<b>Command Center:</b> real-time GPU, disk and NVMe utilisation; GPU health via DCGM; custom metrics; "
            "role-based access; per-team cost tracking. An add-on with Velocis instances.",
            "<b>Overwatch</b> is network observability; <b>Aegis</b> is model security. Neither overlaps with you.",
            "<b>Where workloads run:</b> GPU VMs, containers, VKE (customer-owned Kubernetes), bare metal (Elite BMaaS), Slurm. "
            "GPUs include H100, H200, L40S, L4.",
            "From search summaries of Neysa's pages (couldn't open them directly). Confirm on the call.",
        ]),
        P("Overlap and gap", H2),
        table(["Capability", "Velocis Command Center", "Your product"], [
            ["GPU utilisation and health (DCGM)", "Yes", "Yes (same data source)"],
            ["Spend per team or project", "Yes", "Partly (₹ per finding and per workload)"],
            ["Classifies <i>why</i> a GPU is wasting money", "Not mentioned", "Yes"],
            ["Names a smaller GPU, checked for compute, bandwidth, memory, with stated slowdown", "Not mentioned", "Yes, tested on real GPUs"],
            ["Catches oversized LLM servers that look 100% busy", "Not mentioned", "Yes"],
            ["Prices each recommendation in ₹", "Not mentioned", "Yes"],
        ], [W - 2 * 42 * mm, 42 * mm, 42 * mm]),

        P("Four ways it could fit, easiest first", H2),
        table(["Option", "What happens", "Gaps / work", "Commercially"], [
            ["A. Add-on for VKE customers (works today)", "Customers install the Helm chart in their VKE cluster; it can reuse "
             "their DCGM exporter. Neysa's price list as default rates.", "H200/B200/GH200 support (~30 min).",
             "Marketplace listing, revenue share"],
            ["B. Neysa's own fleet", "Run on clusters behind their managed Inference-as-a-Service and AI PaaS: idle "
             "GPUs there cost Neysa, so the case is simplest.", "H200 support; maybe scale (see C).", "Internal licence"],
            ["C. Built into Command Center", "Engine reads metrics Neysa already collects; findings appear in their dashboard.",
             "Prometheus/Thanos input adapter; JSON/REST output (today HTML only); per-tenant isolation; fleet-scale "
             "database (today SQLite in one pod); SSO/RBAC. ~2–4 months solo [estimate].", "Annual OEM / white-label licence"],
            ["D. VMs, bare metal, Slurm", "Not supported today (roadmap #2): metrics visible but no link to the job using the GPU.",
             "Don't promise it.", "—"],
        ], [36 * mm, W - 36 * mm - 50 * mm - 34 * mm, 50 * mm, 34 * mm]),
        PageBreak(),

        P("The conflict question, and your answers", H2),
        P("“A GPU cloud earns more when customers use more GPUs — you tell them to use fewer.”"),
        *bullets([
            "<b>Neysa sells on cost</b> (40–60% better unit economics than hyperscalers). Right-sizing H100 → L40S/L4 "
            "<i>within Neysa</i> keeps the customer; one who feels overcharged leaves.",
            "<b>GPU capacity is scarce in India.</b> Freed GPUs resell to IndiaAI-driven demand: more revenue per GPU.",
            "<b>On their managed services (option B), waste is Neysa's own cost.</b>",
        ]),
        P("Protect your IP: share vs. hold back", H2),
        table(["Fine to share now", "Hold back until an NDA / pilot agreement"], [
            ["What it finds; sample findings and recommendations; validation results (3090 → T4 test, rehearsal, "
             "Philly, Azure); install, read-only, data stays in cluster",
             "Detector thresholds; right-sizing formulas; the 85% pre-allocation rule; the 93% usable-memory "
             "figure; how the headline is counted — the IP the compiled images protect (layer 2 in "
             "docs/IP_PROTECTION.md)"],
        ], [W / 2, W / 2], first_col_bold=False),

        P("Questions to ask", H2),
        *bullets([
            "Does Command Center make recommendations today, or only show data? On the roadmap?",
            "How do customers split between VKE, VMs, bare metal and Slurm? (Decides whether option A is big enough.)",
            "Do customers' VKE clusters run a DCGM exporter by default?",
            "What's utilisation on your own managed inference fleet? Would you pilot option B?",
            "Are you capacity-constrained? (Decides whether freed GPUs are good news.)",
            "Marketplace add-on, or embedded in Command Center?",
        ]),
        Spacer(1, 4),
        box([
            P("What to propose", BOXH), Spacer(1, 3),
            P("A free pilot on <b>one</b> cluster — one of Neysa's internal managed-service clusters (B) or one "
              "willing VKE customer (A). Pilot agreement signed first; H200 support added before it starts."),
        ], ACCENT_SOFT, ACCENT),
        Spacer(1, 10),
        P("Sources: neysa.ai/neysa-velocis ; neysa.ai/pricing (Command Center add-on) ; "
          "neysa.ai/blog/ai-acceleration-cloud-system ; getinfra.cloud/providers/neysa ; "
          "enterpriseitworld.com (Neysa platforms) ; Neysa careers page (Overwatch) ; analyticsindiamag.com "
          "(Neysa funding). Product facts checked against the code on 2026-10-05.", SMALL),
    ]

    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=14 * mm, bottomMargin=15 * mm,
                            title="Neysa CTO briefing", author="Founder", subject="Founder-only briefing")
    doc.build(s, onFirstPage=on_page, onLaterPages=on_page)
    return OUT


if __name__ == "__main__":
    print(build())
