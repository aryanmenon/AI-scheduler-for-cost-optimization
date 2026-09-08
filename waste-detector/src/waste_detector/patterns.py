"""Recurring daily low-utilization windows (the "overnight idle fleet"
pattern the roadmap calls out), distinct from idle.py's continuous-streak
detector.

A workload that's reliably quiet every night between 1am-6am, but has the
occasional exception (a deploy, a retry storm, one noisy night out of
twenty), never shows up as one unbroken streak -- idle.py's strict
contiguity requirement would fragment it into many short streaks, each
individually below the minimum. This detector instead asks a calendar
question: for a given hour-of-day, across many observed days, how often is
utilization low? A workload that's quiet at 3am on 18 of the last 20 days
has a real, actionable pattern even though night 7 had a burst.
"""
from __future__ import annotations

import time

from waste_detector.config import Config
from waste_detector.findings import RECURRING_PATTERN, WasteFinding
from waste_detector.grouping import group_by, usable_rows
from waste_detector.rollup_reader import RollupRow

_HOUR_SECONDS = 3600
_DAY_SECONDS = 86400


def _group_key(row: RollupRow) -> tuple:
    return (row.namespace, row.workload, row.node, row.gpu_index, row.gpu_instance_id)


def _hour_of_day(bucket_start: float) -> int:
    return int((bucket_start // _HOUR_SECONDS) % 24)


def _day_index(bucket_start: float) -> int:
    return int(bucket_start // _DAY_SECONDS)


def detect_recurring_patterns(
    rows: list[RollupRow], config: Config, now: float | None = None
) -> list[WasteFinding]:
    now = now if now is not None else time.time()

    usable = usable_rows(rows, config, require_utilization=True)

    # (group_key, hour_of_day) -> rows, one per observed calendar day.
    slots = group_by(usable, lambda r: (_group_key(r), _hour_of_day(r.bucket_start)))

    findings = []
    for (group_key, hour_of_day), slot_rows in slots.items():
        distinct_days = {_day_index(r.bucket_start) for r in slot_rows}
        if len(distinct_days) < config.pattern_min_days_observed:
            continue  # not enough calendar history to call this a pattern

        low_rows = [r for r in slot_rows if r.avg_utilization_pct <= config.pattern_idle_threshold_pct]
        consistent_fraction = len(low_rows) / len(slot_rows)

        if consistent_fraction < config.pattern_min_consistent_fraction:
            continue

        namespace, workload, node, gpu_index, gpu_instance_id = group_key
        window_start = min(r.bucket_start for r in slot_rows)
        window_end = max(r.bucket_start for r in slot_rows) + _HOUR_SECONDS
        confidence = sum(r.coverage_ratio for r in slot_rows) / len(slot_rows)

        findings.append(
            WasteFinding(
                category=RECURRING_PATTERN,
                node=node,
                gpu_index=gpu_index,
                gpu_instance_id=gpu_instance_id,
                namespace=namespace,
                workload=workload,
                window_start=window_start,
                window_end=window_end,
                confidence=confidence,
                metric_value=consistent_fraction,
                detail=(
                    f"utilization <= {config.pattern_idle_threshold_pct:.0f}% at "
                    f"{hour_of_day:02d}:00 UTC on {len(low_rows)}/{len(distinct_days)} "
                    f"observed days -- recurring low-usage window"
                ),
            )
        )

    return findings
