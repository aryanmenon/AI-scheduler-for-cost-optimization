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

from dashboard.aggregator import BASIS_OBSERVED_WINDOW, CategorySummary, ReportSummary
from dashboard.report_reader import EstimateRow

_CATEGORY_LABELS = {
    "idle": "Idle GPUs",
    "over_provisioned": "Over-Provisioned",
    "fragmented": "Fragmented Capacity",
    "recurring_pattern": "Recurring Low-Usage Pattern",
}

# Fixed hue per category -- never reassigned based on sort order or which
# categories happen to be present, so a color always means the same thing
# report to report. An unrecognized category (a future detector this
# report doesn't know about yet) falls back to a neutral gray rather than
# an arbitrary cycled hue.
_CATEGORY_COLORS = {
    "idle": "#3987e5",
    "over_provisioned": "#d95926",
    "fragmented": "#199e70",
    "recurring_pattern": "#c98500",
}
_CATEGORY_COLOR_FALLBACK = "#676761"


def _e(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def _category_color(category: str) -> str:
    return _CATEGORY_COLORS.get(category, _CATEGORY_COLOR_FALLBACK)


def _fmt_inr(amount: float | None) -> str:
    if amount is None:
        return "n/a"
    return f"₹{amount:,.2f}"


def _fmt_inr_compact(amount: float) -> str:
    if amount >= 100_000:
        return f"₹{amount / 100_000:.1f}L"
    if amount >= 1_000:
        return f"₹{amount / 1_000:.1f}k"
    return f"₹{amount:,.0f}"


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
        return '<tr><td colspan="8" class="empty">No priceable findings yet.</td></tr>'
    out = []
    for r in rows:
        color = _category_color(r.category)
        out.append(
            "<tr>"
            f'<td><span class="chip" style="background:{color}1a;color:{color}">{_e(_category_label(r.category))}</span></td>'
            f"<td class=\"workload\">{_e(r.workload or 'unattributed')}</td>"
            f"<td>{_e(r.namespace)}</td>"
            f"<td>{_e(_gpu_identity(r))}</td>"
            f"<td>{_e(_fmt_window(r))}</td>"
            f'<td class="num">{_e(_fmt_inr(r.amount_inr))}{" /mo" if r.basis != BASIS_OBSERVED_WINDOW else ""}</td>'
            f"<td>{r.confidence * 100:.0f}%</td>"
            f"<td>{_e(r.recommended_action)}<div class=\"methodology\">{_e(r.methodology)}</div></td>"
            "</tr>"
        )
    return "\n".join(out)


# Stable left-to-right order for the stacked bar and its legend -- a
# category's position (and hue) never depends on which categories happen
# to have findings this cycle, only on the fixed list above. Anything not
# in that list (a category this report doesn't recognize) is appended
# after, in whatever order aggregate() produced it.
_CATEGORY_ORDER = list(_CATEGORY_LABELS.keys())


def _ordered_categories(by_category: list[CategorySummary]) -> list[CategorySummary]:
    by_name = {c.category: c for c in by_category}
    ordered = [by_name.pop(cat) for cat in _CATEGORY_ORDER if cat in by_name]
    ordered.extend(by_name.values())
    return ordered


def _category_breakdown(summary: ReportSummary) -> str:
    if not summary.by_category:
        return '<p class="empty">No findings yet.</p>'

    categories = _ordered_categories(summary.by_category)

    segments = "".join(
        f'<div class="segment" style="flex-grow:{c.total_inr};background:{_category_color(c.category)}" '
        f'title="{_e(_category_label(c.category))} — {_e(_fmt_inr(c.total_inr))}"></div>'
        for c in categories
    )

    legend = "".join(
        "<div class=\"legend-item\">"
        f'<div class="legend-dot" style="background:{_category_color(c.category)}"></div>'
        f"<span>{_e(_category_label(c.category))} ({c.count})</span>"
        f'<span class="amount">{_e(_fmt_inr_compact(c.total_inr))}'
        f'{" /mo" if c.basis != BASIS_OBSERVED_WINDOW else " obs."}</span>'
        "</div>"
        for c in categories
    )

    return f'<div class="stack-bar">{segments}</div><div class="legend">{legend}</div>'


def _unpriceable_section(summary: ReportSummary) -> str:
    if summary.unpriceable_count == 0:
        return ""
    items = "".join(
        "<div class=\"unpriced-item\">"
        "<div>"
        f"<div class=\"name\">{_e(r.workload or 'unattributed')}</div>"
        f'<div class="why">{_e(_gpu_identity(r))} &middot; {_e(r.methodology)}</div>'
        "</div>"
        '<div class="flag">Unpriceable</div>'
        "</div>"
        for r in summary.unpriceable_samples
    )
    return f"""
    <section class="card">
      <h2>Not priced ({summary.unpriceable_count})</h2>
      <p class="muted">These findings couldn't be converted to a rupee figure -- usually an
      unrecognized GPU model or no configured rate for it. They're real waste findings,
      just not quantified here.</p>
      {items}
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
    --page: #0d0d0d; --surface: #1a1a19; --surface-raised: #232322;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --border: rgba(255,255,255,0.08); --gridline: #2c2c2a;
    --idle: #3987e5; --overprov: #d95926;
    --warning-bg: rgba(250,178,25,0.12); --warning-fg: #fab219;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--page); color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.5;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }}
  header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }}
  .logo {{
    width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
    background: linear-gradient(135deg, var(--idle), var(--overprov));
    display: flex; align-items: center; justify-content: center;
    color: white; font-weight: 800; font-size: 16px;
  }}
  header h1 {{ margin: 0; font-size: 19px; font-weight: 700; }}
  header .subtitle {{ color: var(--text-muted); font-size: 12.5px; margin-top: 2px; }}
  .stat-row {{ display: flex; gap: 20px; margin-bottom: 20px; }}
  @media (max-width: 640px) {{ .stat-row {{ flex-direction: column; }} }}
  .stat-card {{
    flex: 1; background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 22px 24px; box-shadow: var(--shadow);
  }}
  .stat-card .label {{ color: var(--text-muted); font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 10px; }}
  .stat-card .value {{ font-size: 30px; font-weight: 800; letter-spacing: -0.4px;
    font-variant-numeric: tabular-nums; }}
  .stat-card.projected .value {{ color: var(--overprov); }}
  .stat-card.observed .value {{ color: var(--idle); }}
  .stat-card .note {{ color: var(--text-secondary); font-size: 12.5px; margin-top: 8px; line-height: 1.5; }}
  .card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
    padding: 22px 24px; margin-bottom: 20px; box-shadow: var(--shadow);
  }}
  .card h2 {{ margin: 0 0 16px; font-size: 13px; font-weight: 700; }}
  .stack-bar {{ display: flex; height: 22px; border-radius: 6px; overflow: hidden;
    background: var(--surface-raised); gap: 2px; margin-bottom: 16px; }}
  .stack-bar .segment {{ flex-shrink: 1; flex-basis: 0; min-width: 6px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 8px 24px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-secondary); }}
  .legend-item .amount {{ color: var(--text-primary); font-weight: 700; font-variant-numeric: tabular-nums; }}
  .legend-dot {{ width: 9px; height: 9px; border-radius: 3px; flex-shrink: 0; }}
  .table-scroll {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid var(--gridline); vertical-align: top; }}
  th {{ color: var(--text-muted); font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }}
  td {{ color: var(--text-secondary); }}
  td.workload {{ color: var(--text-primary); font-weight: 600; }}
  td.num {{ font-weight: 700; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.empty {{ color: var(--text-muted); text-align: center; padding: 24px; }}
  .methodology {{ color: var(--text-muted); font-size: 11px; margin-top: 3px; }}
  .chip {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; white-space: nowrap; }}
  .muted {{ color: var(--text-secondary); font-size: 13px; }}
  .empty {{ color: var(--text-muted); font-size: 13px; }}
  .unpriced-item {{ display: flex; justify-content: space-between; align-items: center;
    padding: 12px 14px; background: var(--warning-bg); border: 1px solid rgba(250,178,25,0.2);
    border-radius: 10px; margin-top: 10px; }}
  .unpriced-item .name {{ font-weight: 600; font-size: 13.5px; }}
  .unpriced-item .why {{ font-size: 12px; color: var(--text-secondary); margin-top: 2px; }}
  .unpriced-item .flag {{ font-size: 11px; font-weight: 700; color: var(--warning-fg); text-transform: uppercase; white-space: nowrap; }}
  .disclaimer {{ color: var(--text-muted); font-size: 12px; border-top: 1px solid var(--gridline);
    margin-top: 32px; padding-top: 16px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">G</div>
    <div>
      <h1>GPU Cost Optimization Report</h1>
      <div class="subtitle">Generated {_e(_fmt_ts(summary.generated_at))} &middot;
        {summary.total_estimates} findings evaluated ({summary.priceable_count} priced,
        {summary.unpriceable_count} not priceable)</div>
    </div>
  </header>

  <div class="stat-row">
    <div class="stat-card projected">
      <div class="label">Projected Monthly Savings</div>
      <div class="value">{_e(_fmt_inr(summary.projected_monthly_total_inr))}</div>
      <div class="note">If right-sizing / consolidation / scale-down recommendations below are
        acted on and current usage patterns continue. Not a guarantee.</div>
    </div>
    <div class="stat-card observed">
      <div class="label">Already-Wasted Spend Observed</div>
      <div class="value">{_e(_fmt_inr(summary.observed_window_total_inr))}</div>
      <div class="note">Actual cost of idle GPU time during the exact windows observed --
        a lower bound, not extrapolated to a full month.</div>
    </div>
  </div>

  <section class="card">
    <h2>By category</h2>
    {_category_breakdown(summary)}
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
    Rupee figures depend on the GPU hourly rates configured for this deployment -- verify
    against your actual contracted pricing before treating any number here as final.
    This report reflects observed telemetry only; results depend on the pilot window being
    representative of normal usage.
  </div>
</div>
</body>
</html>
"""
