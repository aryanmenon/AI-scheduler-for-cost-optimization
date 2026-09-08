"""Wire rollup_reader -> detector -> findings storage into one detection cycle.

Every cycle re-evaluates all hourly rollups currently in the normalized
database and re-derives the full findings set, rather than incrementally
tracking state -- simpler and correct, at the cost of redoing work that
scales with total rollup history. Acceptable for a phase-1 MVP; flagged
here as the first thing to revisit if a customer's rollup history grows
large enough to make a full re-scan slow.
"""
from __future__ import annotations

import json
import logging
import time

from waste_detector.config import Config
from waste_detector.detector import run_all_detectors
from waste_detector.findings import FindingsStorage
from waste_detector.rollup_reader import RollupReader

logger = logging.getLogger(__name__)


def _log_cycle(duration_ms: float, rows_in: int, rows_out: int, errors: int, **extra) -> None:
    """One structured summary line per cycle, same core schema across all
    five services (component/event/duration_ms/rows_in/rows_out/errors) so
    an operator can query cycle health without reading source code to
    learn what each service's ad-hoc log message meant.
    """
    payload = {
        "event": "cycle_complete",
        "component": "waste-detector",
        "duration_ms": round(duration_ms, 1),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "errors": errors,
        **extra,
    }
    logger.info(json.dumps(payload))


def run_once(config: Config, reader: RollupReader, storage: FindingsStorage) -> int:
    start = time.monotonic()
    now = time.time()
    rows = reader.fetch("hourly")

    if not rows:
        logger.info("no hourly rollups available yet")
        _prune(config, storage, now)
        _log_cycle((time.monotonic() - start) * 1000, rows_in=0, rows_out=0, errors=0)
        return 0

    findings = run_all_detectors(rows, config, now)
    storage.insert_findings(findings, detected_at=now)
    _prune(config, storage, now)

    duration_ms = (time.monotonic() - start) * 1000
    logger.info("evaluated %d hourly rollups, produced %d findings", len(rows), len(findings))
    _log_cycle(duration_ms, rows_in=len(rows), rows_out=len(findings), errors=0)
    return len(findings)


def _prune(config: Config, storage: FindingsStorage, now: float) -> None:
    if config.findings_retention_hours <= 0:
        return
    cutoff = now - config.findings_retention_hours * 3600
    deleted = storage.prune_older_than(cutoff)
    if deleted:
        logger.info("pruned %d stale findings older than %.1fh", deleted, config.findings_retention_hours)
