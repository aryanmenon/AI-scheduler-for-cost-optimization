"""Glue: read -> aggregate -> render, shared by the live server and the
static-file generator so both always produce the identical report."""
from __future__ import annotations

from dashboard.aggregator import aggregate
from dashboard.config import Config
from dashboard.render import render_report
from dashboard.report_reader import ReportReader


def generate_report_html(config: Config) -> str:
    reader = ReportReader(config.savings_sqlite_path)
    try:
        rows = reader.all_estimates()
    finally:
        reader.close()

    summary = aggregate(rows, top_n=config.top_findings_limit)
    return render_report(summary)
