"""Wire findings_reader + rollup_reader -> estimator -> storage into one
pricing cycle.

Every cycle re-evaluates all findings currently in waste-detector's
database and re-derives the full estimate set -- same simplicity/cost
tradeoff as ingestion-normalization and waste-detector before it (see
their pipeline.py docstrings); flagged as the first thing to revisit if
findings history grows large.
"""
from __future__ import annotations

import json
import logging
import time

from savings_estimator.config import Config
from savings_estimator.estimator import estimate_for_finding
from savings_estimator.findings_reader import FindingsReader
from savings_estimator.pricing import parse_rate_overrides
from savings_estimator.recoverable import compute_recoverable_ceiling
from savings_estimator.rollup_reader import RollupReader
from savings_estimator.storage import SavingsStorage

logger = logging.getLogger(__name__)


def _log_cycle(duration_ms: float, rows_in: int, rows_out: int, errors: int, **extra) -> None:
    """One structured summary line per cycle, same core schema across all
    five services (component/event/duration_ms/rows_in/rows_out/errors) so
    an operator can query cycle health without reading source code to
    learn what each service's ad-hoc log message meant.
    """
    payload = {
        "event": "cycle_complete",
        "component": "savings-estimator",
        "duration_ms": round(duration_ms, 1),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "errors": errors,
        **extra,
    }
    logger.info(json.dumps(payload))


def run_once(
    config: Config,
    findings_reader: FindingsReader,
    rollup_reader: RollupReader,
    storage: SavingsStorage,
) -> int:
    start = time.monotonic()
    now = time.time()
    rate_overrides = parse_rate_overrides(config.gpu_hourly_rates_json)

    _update_ceiling(config, rollup_reader, storage, rate_overrides, now)

    findings = findings_reader.all_findings(min_confidence=config.min_finding_confidence)
    if not findings:
        logger.info("no findings available yet (or none meet min_finding_confidence)")
        _prune(config, storage, now)
        _log_cycle((time.monotonic() - start) * 1000, rows_in=0, rows_out=0, errors=0)
        return 0

    estimates = []
    for finding in findings:
        rollup_rows = rollup_reader.fetch_for_gpu(
            "hourly",
            finding.node,
            finding.gpu_index,
            finding.gpu_instance_id,
            since=finding.window_start,
            until=finding.window_end,
        )
        estimates.append(estimate_for_finding(finding, rollup_rows, config, rate_overrides))

    storage.insert_estimates(estimates, estimated_at=now)
    _prune(config, storage, now)

    priceable = sum(1 for e in estimates if e.priceable)
    unpriceable = len(estimates) - priceable
    duration_ms = (time.monotonic() - start) * 1000
    logger.info("priced %d/%d findings (%d unpriceable)", priceable, len(estimates), unpriceable)
    _log_cycle(
        duration_ms, rows_in=len(findings), rows_out=len(estimates), errors=0,
        priceable=priceable, unpriceable=unpriceable,
    )
    return len(estimates)


def _update_ceiling(
    config: Config, rollup_reader: RollupReader, storage: SavingsStorage,
    rate_overrides: dict[str, float], now: float,
) -> None:
    # Independent of findings: a cluster with nothing flagged still has a
    # ceiling (often near zero, which is worth showing too).
    rows = rollup_reader.fetch_recent("hourly", config.ceiling_window_hours)
    ceiling = compute_recoverable_ceiling(
        rows, config.sla_target_utilization_pct, config.hours_per_month, rate_overrides,
    )
    storage.save_ceiling(ceiling, computed_at=now)


def _prune(config: Config, storage: SavingsStorage, now: float) -> None:
    if config.savings_estimates_retention_hours <= 0:
        return
    cutoff = now - config.savings_estimates_retention_hours * 3600
    deleted = storage.prune_older_than(cutoff)
    if deleted:
        logger.info(
            "pruned %d stale savings_estimates older than %.1fh",
            deleted, config.savings_estimates_retention_hours,
        )
