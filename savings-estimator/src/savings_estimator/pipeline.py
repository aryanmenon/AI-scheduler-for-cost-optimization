"""Wire findings_reader + rollup_reader -> estimator -> storage into one
pricing cycle.

Every cycle re-evaluates all findings currently in waste-detector's
database and re-derives the full estimate set -- same simplicity/cost
tradeoff as ingestion-normalization and waste-detector before it (see
their pipeline.py docstrings); flagged as the first thing to revisit if
findings history grows large.
"""
from __future__ import annotations

import logging
import time

from savings_estimator.config import Config
from savings_estimator.estimator import estimate_for_finding
from savings_estimator.findings_reader import FindingsReader
from savings_estimator.pricing import parse_rate_overrides
from savings_estimator.rollup_reader import RollupReader
from savings_estimator.storage import SavingsStorage

logger = logging.getLogger(__name__)


def run_once(
    config: Config,
    findings_reader: FindingsReader,
    rollup_reader: RollupReader,
    storage: SavingsStorage,
) -> int:
    now = time.time()
    rate_overrides = parse_rate_overrides(config.gpu_hourly_rates_json)

    findings = findings_reader.all_findings(min_confidence=config.min_finding_confidence)
    if not findings:
        logger.info("no findings available yet (or none meet min_finding_confidence)")
        _prune(config, storage, now)
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
    logger.info(
        "priced %d/%d findings (%d unpriceable)", priceable, len(estimates), len(estimates) - priceable
    )
    return len(estimates)


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
