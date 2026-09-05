"""Wire rollup_reader -> detector -> findings storage into one detection cycle.

Every cycle re-evaluates all hourly rollups currently in the normalized
database and re-derives the full findings set, rather than incrementally
tracking state -- simpler and correct, at the cost of redoing work that
scales with total rollup history. Acceptable for a phase-1 MVP; flagged
here as the first thing to revisit if a customer's rollup history grows
large enough to make a full re-scan slow.
"""
from __future__ import annotations

import logging
import time

from waste_detector.config import Config
from waste_detector.detector import run_all_detectors
from waste_detector.findings import FindingsStorage
from waste_detector.rollup_reader import RollupReader

logger = logging.getLogger(__name__)


def run_once(config: Config, reader: RollupReader, storage: FindingsStorage) -> int:
    now = time.time()
    rows = reader.fetch("hourly")

    if not rows:
        logger.info("no hourly rollups available yet")
        return 0

    findings = run_all_detectors(rows, config, now)
    storage.insert_findings(findings, detected_at=now)

    logger.info("evaluated %d hourly rollups, produced %d findings", len(rows), len(findings))
    return len(findings)
