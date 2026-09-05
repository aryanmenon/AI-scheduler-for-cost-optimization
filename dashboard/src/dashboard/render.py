"""Render a ReportSummary as a single self-contained HTML page.

No external requests (fonts, scripts, stylesheets) -- this needs to work
as a file a salesperson downloads and emails, not just as a live page, so
everything is inlined. All interpolated text is HTML-escaped: workload,
namespace, and node names ultimately come from a customer's own cluster
and shouldn't be trusted as safe markup just because they're usually
DNS-safe strings.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from dashboard.aggregator import BASIS_OBSERVED_WINDOW, ReportSummary
from dashboard.report_reader import EstimateRow

_CATEGORY_LABELS = {
    "idle": "Idle GPUs",
    "over_provisioned": "Over-Provisioned",
    "fragmented": "Fragmented Capacity",
    "recurring_pattern": "Recurring Low-Usage Pattern",
}


def _e(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def _fmt_usd(amount: float | None) -> str:
    if amount is None:
        return "n/a"
    return f"${amount:,.2f}"


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_window(row: EstimateRow) -> str:
    hours = (row.window_end - row.window_start) / 3600
    return f"{_fmt_ts(row.window_start)} ({hours:.1f}h)"


def _gpu_identity(row: EstimateRow) -> str:
    base = f"{row.node} / gpu{row.gpu_index}"
    if row.gpu_instance_id:
        base += f" (MIG {row.gpu_instance_id})"
    return base


def _findings_table_rows(rows: list[EstimateRow]) -> str:
    if not rows:
        return '<tr><td colspan="7" class="empty">No priceable findings yet.</td></tr>'
    out = []
    for r in rows:
        out.append(
            "<tr>"
            f'<td><span class="badge badge-{_e(r.category)}">{_e(_category_label(r.category))}</span></td>'
            f"<td>{_e(r.workload or 'unattributed')}</td>"
            f"<td>{_e(r.namespace)}</td>"
            f"<td>{_e(_gpu_identity(r))}</td>"
            f"<td>{_e(_fmt_window(r))}</td>"
            f'<td class="amount">{_e(_fmt_usd(r.amount_usd))}{" /mo" if r.basis != BASIS_OBSERVED_WINDOW else ""}</td>'
            f"<td>{r.confidence * 100:.0f}%</td>"
            f"<td>{_e(r.recommended_action)}<div class=\"methodology\">{_e(r.methodology)}</div></td>"
            "</tr>"
        )
    return "\n".join(out)


def _category_table_rows(summary: ReportSummary) -> str:
    if not summary.by_category:
        return '<tr><td colspan="4" class="empty">No findings yet.</td></tr>'
    out = []
    for c in summary.by_category:
        suffix = " /mo" if c.basis != BASIS_OBSERVED_WINDOW else " (observed)"
        out.append(
            "<tr>"
            f'<td><span class="badge badge-{_e(c.category)}">{_e(_category_label(c.category))}</span></td>'
            f"<td>{c.count}</td>"
            f'<td class="amount">{_e(_fmt_usd(c.total_usd))}{suffix}</td>'
            f"<td>{c.avg_confidence * 100:.0f}%</td>"
            "</tr>"
        )
    return "\n".join(out)


def _unpriceable_section(summary: ReportSummary) -> str:
    if summary.unpriceable_count == 0:
        return ""
    samples = "".join(
        f"<li>{_e(_gpu_identity(r))} ({_e(r.workload or 'unattributed')}): {_e(r.methodology)}</li>"
        for r in summary.unpriceable_samples
    )
    return f"""
    <section class="card">
      <h2>Not priced ({summary.unpriceable_count})</h2>
      <p class="muted">These findings couldn't be converted to a dollar figure -- usually an
      unrecognized GPU model or no configured rate for it. They're real waste findings,
      just not quantified here.</p>
      <ul class="unpriceable-list">{samples}</ul>
    </section>
    """


def render_report(summary: ReportSummary) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GPU Cost Optimization Report</title>
<style>
  :root {{
    --bg: #0b0f14; --panel: #131a22; --panel-2: #1a232d; --border: #26313d;
    --text: #e8edf2; --muted: #94a3b3; --accent: #4fd1a5; --accent-2: #7aa2ff;
    --warn: #f0b656;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.5;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }}
  header {{ margin-bottom: 28px; }}
  header h1 {{ margin: 0 0 4px; font-size: 26px; }}
  header .subtitle {{ color: var(--muted); font-size: 14px; }}
  .hero {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 28px; }}
  @media (max-width: 640px) {{ .hero {{ grid-template-columns: 1fr; }} }}
  .stat {{
    background: linear-gradient(160deg, var(--panel-2), var(--panel));
    border: 1px solid var(--border); border-radius: 12px; padding: 20px;
  }}
  .stat .label {{ color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: .04em; }}
  .stat .value {{ font-size: 32px; font-weight: 700; margin: 6px 0 4px; }}
  .stat.projected .value {{ color: var(--accent); }}
  .stat.observed .value {{ color: var(--accent-2); }}
  .stat .note {{ color: var(--muted); font-size: 12.5px; }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px; margin-bottom: 20px;
  }}
  .card h2 {{ margin: 0 0 12px; font-size: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
  td.amount {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.empty {{ color: var(--muted); text-align: center; padding: 20px; }}
  .methodology {{ color: var(--muted); font-size: 11.5px; margin-top: 3px; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11.5px;
    background: var(--panel-2); border: 1px solid var(--border); white-space: nowrap;
  }}
  .badge-idle {{ color: var(--warn); }}
  .badge-over_provisioned {{ color: var(--accent-2); }}
  .badge-fragmented {{ color: #e08bd6; }}
  .badge-recurring_pattern {{ color: var(--accent); }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  .unpriceable-list {{ color: var(--muted); font-size: 13px; padding-left: 20px; }}
  .disclaimer {{
    color: var(--muted); font-size: 12px; border-top: 1px solid var(--border);
    margin-top: 32px; padding-top: 16px;
  }}
  .table-scroll {{ overflow-x: auto; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>GPU Cost Optimization Report</h1>
    <div class="subtitle">Generated {_e(_fmt_ts(summary.generated_at))} &middot;
      {summary.total_estimates} findings evaluated ({summary.priceable_count} priced,
      {summary.unpriceable_count} not priceable)</div>
  </header>

  <div class="hero">
    <div class="stat projected">
      <div class="label">Projected Monthly Savings</div>
      <div class="value">{_e(_fmt_usd(summary.projected_monthly_total_usd))}</div>
      <div class="note">If right-sizing / consolidation / scale-down recommendations below are
        acted on and current usage patterns continue. Not a guarantee.</div>
    </div>
    <div class="stat observed">
      <div class="label">Already-Wasted Spend Observed</div>
      <div class="value">{_e(_fmt_usd(summary.observed_window_total_usd))}</div>
      <div class="note">Actual cost of idle GPU time during the exact windows observed --
        a lower bound, not extrapolated to a full month.</div>
    </div>
  </div>

  <section class="card">
    <h2>By category</h2>
    <div class="table-scroll">
    <table>
      <thead><tr><th>Category</th><th>Findings</th><th>Total</th><th>Avg. confidence</th></tr></thead>
      <tbody>{_category_table_rows(summary)}</tbody>
    </table>
    </div>
  </section>

  <section class="card">
    <h2>Top findings</h2>
    <div class="table-scroll">
    <table>
      <thead><tr>
        <th>Category</th><th>Workload</th><th>Namespace</th><th>GPU</th>
        <th>Window</th><th>Impact</th><th>Confidence</th><th>Recommendation</th>
      </tr></thead>
      <tbody>{_findings_table_rows(summary.top_findings)}</tbody>
    </table>
    </div>
  </section>

  {_unpriceable_section(summary)}

  <div class="disclaimer">
    Dollar figures depend on the GPU hourly rates configured for this deployment -- verify
    against your actual contracted pricing before treating any number here as final.
    This report reflects observed telemetry only; results depend on the pilot window being
    representative of normal usage.
  </div>
</div>
</body>
</html>
"""
