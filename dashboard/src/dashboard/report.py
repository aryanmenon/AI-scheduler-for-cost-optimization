"""Glue: read -> aggregate -> render, shared by the live server and the
static-file generator so both always produce the identical report."""
from __future__ import annotations

import json
import logging
import time

from dashboard.aggregator import aggregate
from dashboard.config import Config
from dashboard.render import render_report
from dashboard.report_reader import ReportReader

logger = logging.getLogger(__name__)


def _log_cycle(duration_ms: float, rows_in: int, rows_out: int, errors: int, **extra) -> None:
    """One structured summary line per report generation, same core schema
    across all five services (component/event/duration_ms/rows_in/
    rows_out/errors) so an operator can query cycle health without reading
    source code to learn what each service's ad-hoc log message meant.
    """
    payload = {
        "event": "cycle_complete",
        "component": "dashboard",
        "duration_ms": round(duration_ms, 1),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "errors": errors,
        **extra,
    }
    logger.info(json.dumps(payload))


def generate_report_html(config: Config) -> str:
    start = time.monotonic()
    reader = ReportReader(config.savings_sqlite_path)
    try:
        rows = reader.all_estimates()
    finally:
        reader.close()

    summary = aggregate(rows, top_n=config.top_findings_limit)
    html = render_report(summary)

    duration_ms = (time.monotonic() - start) * 1000
    _log_cycle(
        duration_ms, rows_in=len(rows), rows_out=1, errors=0,
        priceable=summary.priceable_count, unpriceable=summary.unpriceable_count,
    )
    return html
