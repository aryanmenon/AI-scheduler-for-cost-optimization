"""Run every waste-detection category over one set of hourly rollups."""
from __future__ import annotations

import time

from waste_detector.config import Config
from waste_detector.findings import WasteFinding
from waste_detector.fragmentation import detect_fragmentation
from waste_detector.idle import detect_idle
from waste_detector.multi_gpu import detect_multi_gpu_oversized
from waste_detector.over_provisioning import detect_over_provisioning
from waste_detector.patterns import detect_recurring_patterns
from waste_detector.rollup_reader import RollupRow


def run_all_detectors(
    rows: list[RollupRow], config: Config, now: float | None = None
) -> list[WasteFinding]:
    now = now if now is not None else time.time()
    findings: list[WasteFinding] = []
    findings.extend(detect_idle(rows, config, now))
    findings.extend(detect_over_provisioning(rows, config, now))
    findings.extend(detect_fragmentation(rows, config, now))
    findings.extend(detect_recurring_patterns(rows, config, now))
    findings.extend(detect_multi_gpu_oversized(rows, config, now))
    return findings
