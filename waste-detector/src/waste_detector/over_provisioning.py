"""Over-provisioning: peak utilization never approaches what's allocated.

Per the roadmap, this is built first because it's a single-snapshot
comparison -- no time-pattern reasoning needed, just "has this workload's
peak utilization, over enough observed hours, ever gotten close to full
use of its GPU?" -- making it the fastest waste category to a
demonstrable number.
"""
from __future__ import annotations

import time
from collections import defaultdict

from waste_detector.config import Config
from waste_detector.findings import OVER_PROVISIONED, WasteFinding
from waste_detector.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600  # hourly rollups only


def _group_key(row: RollupRow) -> tuple:
    return (row.namespace, row.workload, row.node, row.gpu_index, row.gpu_instance_id)


def detect_over_provisioning(
    rows: list[RollupRow], config: Config, now: float | None = None
) -> list[WasteFinding]:
    now = now if now is not None else time.time()

    # Unattributed capacity has no workload to right-size, and low-coverage
    # buckets aren't trustworthy evidence either way -- both are excluded
    # before any grouping happens.
    usable = [r for r in rows if r.attributed and r.coverage_ratio >= config.min_coverage_ratio]

    groups: dict[tuple, list[RollupRow]] = defaultdict(list)
    for row in usable:
        groups[_group_key(row)].append(row)

    findings = []
    for (namespace, workload, node, gpu_index, gpu_instance_id), group_rows in groups.items():
        if len(group_rows) < config.over_provision_min_observation_hours:
            continue  # not enough observed hours yet to trust a verdict

        peaks = [r.max_utilization_pct for r in group_rows if r.max_utilization_pct is not None]
        if not peaks:
            continue
        peak = max(peaks)

        if peak > config.over_provision_threshold_pct:
            continue

        window_start = min(r.bucket_start for r in group_rows)
        window_end = max(r.bucket_start for r in group_rows) + _BUCKET_SECONDS
        confidence = sum(r.coverage_ratio for r in group_rows) / len(group_rows)

        findings.append(
            WasteFinding(
                category=OVER_PROVISIONED,
                node=node,
                gpu_index=gpu_index,
                gpu_instance_id=gpu_instance_id,
                namespace=namespace,
                workload=workload,
                window_start=window_start,
                window_end=window_end,
                confidence=confidence,
                metric_value=peak,
                detail=(
                    f"peak utilization {peak:.1f}% across {len(group_rows)}h observed, "
                    f"never exceeded the {config.over_provision_threshold_pct:.0f}% threshold"
                ),
            )
        )

    return findings
