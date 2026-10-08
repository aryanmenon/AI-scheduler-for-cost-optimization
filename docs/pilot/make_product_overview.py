"""Build docs/pilot/product-overview.pdf: a two-page, high-level overview of
the product for DevOps/platform engineers at companies considering a first
cluster test. States only what the product does today (see PILOT_GUIDE.md
for the details behind each claim) plus the one planned upgrade: automated
recommendation actions, after recommendations are verified on a client's
cluster.

  python3 docs/pilot/make_product_overview.py
"""
from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "product-overview.pdf")

# DejaVu Sans has the rupee sign; the built-in PDF fonts don't.
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("Sans", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold")

INK = colors.HexColor("#1B2733")
MUTED = colors.HexColor("#5B6875")
ACCENT = colors.HexColor("#1F6F8B")
ACCENT_SOFT = colors.HexColor("#E8F2F6")
RULE = colors.HexColor("#D5DDE3")
NEXT = colors.HexColor("#7A4FB0")
NEXT_SOFT = colors.HexColor("#F3EEFA")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def style(name, **kw):
    base = dict(fontName="Sans", fontSize=9.6, leading=13.8, textColor=INK, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)


TITLE = style("title", fontName="Sans-Bold", fontSize=24, leading=28, textColor=INK)
SUBTITLE = style("subtitle", fontSize=12, leading=16.5, textColor=MUTED)
KICKER = style("kicker", fontName="Sans-Bold", fontSize=8, leading=10, textColor=ACCENT)
H2 = style("h2", fontName="Sans-Bold", fontSize=12.5, leading=16, textColor=ACCENT, spaceBefore=12, spaceAfter=5)
BODY = style("body", spaceAfter=5)
CELL = style("cell", fontSize=8.8, leading=12.2)
CELL_B = style("cellb", fontName="Sans-Bold", fontSize=8.8, leading=12.2)
CELL_H = style("cellh", fontName="Sans-Bold", fontSize=8.4, leading=11, textColor=colors.white)
BULLET = style("bullet", leftIndent=11, bulletIndent=0, spaceAfter=3.2)
NEXT_H = style("nexth", fontName="Sans-Bold", fontSize=12.5, leading=16, textColor=NEXT)


def bullets(items, st=BULLET, color=ACCENT):
    bst = ParagraphStyle(f"{st.name}-{color.hexval()}", parent=st, bulletFontName="Sans",
                         bulletFontSize=6.5, bulletColor=color)
    return [Paragraph(text, bst, bulletText="●") for text in items]


def boxed(flowables, fill, border, pad=10):
    t = Table([[flowables]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 3, border),
        ("LEFTPADDING", (0, 0), (-1, -1), pad + 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad - 2),
    ]))
    return t


def findings_table():
    rows = [
        ("Idle GPUs",
         "A GPU allocated to a workload but essentially unused for hours.",
         "₹ already spent on the idle time"),
        ("Oversized GPUs",
         "A workload whose load never needs the GPU it has — including LLM "
         "inference servers that look busy at peak but are quiet on average.",
         "₹ per month saved by a smaller GPU"),
        ("Recurring quiet hours",
         "The same hours of the day are quiet on most days.",
         "₹ per month saved by scaling down in those hours"),
        ("Review candidates",
         "Underused GPUs on one node that might share hardware; multi-GPU "
         "jobs whose GPUs are mostly idle.",
         "Upper bound, for your team to review"),
        ("Unexplained under-use",
         "Below-target GPU time nothing above explains, including GPUs with "
         "no pod at all.",
         "₹ already spent, no recommendation yet"),
    ]
    data = [[Paragraph("Finding", CELL_H), Paragraph("What it means", CELL_H),
             Paragraph("What you see", CELL_H)]]
    data += [[Paragraph(a, CELL_B), Paragraph(b, CELL), Paragraph(c, CELL)] for a, b, c in rows]
    t = Table(data, colWidths=[34 * mm, CONTENT_W - 34 * mm - 52 * mm, 52 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_SOFT]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def timeline_table():
    steps = [
        ("Day 0", "Install (about 15 minutes) and confirm every GPU is being read."),
        ("Days 1–7", "The product collects data. Nothing for your team to do."),
        ("Week 2", "Review call: every finding marked useful, wrong or already known."),
        ("Weeks 2–3", "Your team acts on one recommendation of its choice."),
        ("Week 4", "Measured saving and latency compared with what was predicted."),
    ]
    data = [[Paragraph(a, CELL_B), Paragraph(b, CELL)] for a, b in steps]
    t = Table(data, colWidths=[26 * mm, CONTENT_W - 26 * mm])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(ACCENT)
    canvas.rect(0, PAGE_H - 6 * mm, PAGE_W, 6 * mm, stroke=0, fill=1)
    canvas.setFont("Sans", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 10 * mm, "GPU Cost Optimizer · Product overview · October 2026 · Confidential")
    canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"{doc.page}")
    canvas.restoreState()


def build():
    story = [
        Spacer(1, 4 * mm),
        Paragraph("PRODUCT OVERVIEW · FOR DEVOPS AND PLATFORM TEAMS", KICKER),
        Spacer(1, 3),
        Paragraph("GPU Cost Optimizer", TITLE),
        Spacer(1, 4),
        Paragraph("Find the GPUs you pay for but don't use — priced in ₹ at your own "
                  "rates, from inside your own Kubernetes cluster.", SUBTITLE),
        Spacer(1, 6),

        Paragraph("What it does", H2),
        Paragraph(
            "GPU Cost Optimizer runs inside your Kubernetes cluster and watches how every "
            "GPU is actually used, hour by hour, and which workload is using it. It tells "
            "you which GPUs are wasting money, how much in rupees, and what to do about "
            "each one. <b>It observes and recommends; it never changes anything in your "
            "cluster.</b>", BODY),

        Paragraph("What it finds", H2),
        findings_table(),

        Paragraph("Recommendations your team can judge", H2),
        *bullets([
            "Every “move to a smaller GPU” recommendation is checked against the three "
            "things a workload can run out of: <b>compute, memory bandwidth and memory "
            "capacity</b>.",
            "Each one states its cost, e.g. <i>“each request may take up to ~1.6x longer — "
            "fine for batch work, check latency targets before moving an interactive "
            "service.”</i>",
            "Where memory fit can't be determined (servers such as vLLM pre-allocate GPU "
            "memory), the recommendation says so instead of guessing.",
            "The headline ₹ figure counts each GPU once.",
        ]),

        KeepTogether([Paragraph("How it runs in your cluster", H2), *bullets([
            "<b>Install:</b> one Helm chart into one namespace, about 15 minutes. One "
            "small pod (about 0.2 CPU and 0.6 GiB memory requested) plus standard exporters.",
            "<b>Read-only:</b> Kubernetes access is limited to get, list and watch on pods, "
            "nodes and namespaces. Nothing can create, change or delete.",
            "<b>Your data stays with you:</b> metrics and findings are stored on a volume in "
            "the product's namespace. Nothing is sent outside your cluster, except an "
            "optional alert webhook you configure yourself.",
            "<b>Standard GPU metrics:</b> uses NVIDIA's DCGM exporter. Already running it "
            "(e.g. through the GPU Operator)? The product reuses yours and deploys no "
            "privileged pod.",
            "<b>Hardened:</b> containers run as non-root with read-only file systems; the "
            "report is reached through <font name='Sans'>kubectl port-forward</font> with a "
            "bearer token.",
            "<b>Uninstall:</b> two commands, nothing left behind.",
        ])]),

        KeepTogether([
            Paragraph("The first cluster test (3–4 weeks)", H2),
            timeline_table(),
        ]),
        Spacer(1, 12),

        KeepTogether([boxed([
            Paragraph("WHAT COMES NEXT", style("k2", fontName="Sans-Bold", fontSize=8,
                                               leading=10, textColor=NEXT)),
            Spacer(1, 3),
            Paragraph("Automated recommendation actions", NEXT_H),
            Spacer(1, 3),
            Paragraph(
                "Once a client cluster test confirms that the recommendations are accurate on "
                "a real cluster, we will add the option for the product to carry out "
                "recommendations for you, instead of your team applying each one by hand:",
                BODY),
            *bullets([
                "Reclaim idle GPU allocations.",
                "Scale workloads down during their recurring quiet hours, and back up after.",
                "Move a workload to the recommended smaller GPU.",
            ], color=NEXT),
            Spacer(1, 3),
            Paragraph(
                "Automation will be opt-in for each type of action, show exactly what will "
                "change before it runs, and wait for your approval. It needs write access, so "
                "it will be a separate component — the read-only product stays as it is.",
                BODY),
        ], NEXT_SOFT, NEXT)]),
    ]

    doc = SimpleDocTemplate(
        OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=18 * mm,
        title="GPU Cost Optimizer — Product overview",
        author="GPU Cost Optimizer", subject="Product overview for a first cluster test",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return OUT


if __name__ == "__main__":
    print(build())
