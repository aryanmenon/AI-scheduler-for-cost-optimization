"""Idle-GPU detection, tuned for inference's bursty traffic.

A single low-utilization sample is normal for inference -- a request queue
that's briefly empty looks identical to an abandoned deployment in one
snapshot. What actually distinguishes "genuinely idle" is a *sustained,
unbroken* run of low activity: this requires both the average AND the max
utilization in every hour of the streak to stay at or below the idle
threshold, so a single real burst hidden inside an otherwise-quiet hour
breaks the streak. Training's steady, always-on load doesn't need this
distinction (idle there really does mean idle), but a detector aimed at
inference workloads needs it to avoid flagging healthy bursty services as
waste -- exactly the false-positive risk the roadmap calls out as more
costly than a missed detection.
"""
from __future__ import annotations

import time
from collections import defaultdict

from waste_detector.config import Config
from waste_detector.findings import IDLE, WasteFinding
from waste_detector.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600  # hourly rollups only


def _group_key(row: RollupRow) -> tuple:
    return (row.namespace, row.workload, row.node, row.gpu_index, row.gpu_instance_id)


def _is_idle_hour(row: RollupRow, threshold_pct: float) -> bool:
    return (
        row.avg_utilization_pct is not None
        and row.max_utilization_pct is not None
        and row.avg_utilization_pct <= threshold_pct
        and row.max_utilization_pct <= threshold_pct
    )


def _finding_for_streak(streak: list[RollupRow], key: tuple, config: Config) -> WasteFinding | None:
    if len(streak) < config.min_idle_streak_hours:
        return None

    namespace, workload, node, gpu_index, gpu_instance_id = key
    window_start = streak[0].bucket_start
    window_end = streak[-1].bucket_start + _BUCKET_SECONDS
    confidence = sum(r.coverage_ratio for r in streak) / len(streak)

    return WasteFinding(
        category=IDLE,
        node=node,
        gpu_index=gpu_index,
        gpu_instance_id=gpu_instance_id,
        namespace=namespace,
        workload=workload,
        window_start=window_start,
        window_end=window_end,
        confidence=confidence,
        metric_value=float(len(streak)),
        detail=(
            f"idle (avg and max utilization <= {config.idle_threshold_pct:.0f}%) for "
            f"{len(streak)} consecutive hours with no bursts observed"
        ),
    )


def detect_idle(rows: list[RollupRow], config: Config, now: float | None = None) -> list[WasteFinding]:
    now = now if now is not None else time.time()

    # Low-coverage hours are excluded before streak-walking: a bucket with
    # missing data reading as near-zero utilization is "we don't know,"
    # not confirmed idle, and letting it slip into a streak would credit
    # unobserved time as evidence.
    usable = [r for r in rows if r.attributed and r.coverage_ratio >= config.min_coverage_ratio]

    groups: dict[tuple, list[RollupRow]] = defaultdict(list)
    for row in usable:
        groups[_group_key(row)].append(row)

    findings = []
    for key, group_rows in groups.items():
        group_rows.sort(key=lambda r: r.bucket_start)

        streak: list[RollupRow] = []
        for row in group_rows:
            is_idle = _is_idle_hour(row, config.idle_threshold_pct)
            contiguous = bool(streak) and row.bucket_start == streak[-1].bucket_start + _BUCKET_SECONDS

            if is_idle and contiguous:
                streak.append(row)
                continue

            # Either a non-idle hour, or an idle hour that isn't contiguous
            # with the current streak (a coverage gap broke continuity) --
            # either way the current streak is done; an idle row still
            # starts a fresh one.
            finding = _finding_for_streak(streak, key, config)
            if finding:
                findings.append(finding)
            streak = [row] if is_idle else []

        finding = _finding_for_streak(streak, key, config)
        if finding:
            findings.append(finding)

    return findings
