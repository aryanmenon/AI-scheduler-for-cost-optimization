"""Fragmentation: several small workloads each partially using their own
GPU, on a node where their combined work could fit on fewer GPUs.

This is the hardest of the three waste categories -- true bin-packing
(could these specific workloads actually be co-scheduled, given memory and
scheduling constraints?) is out of scope for an MVP. What's built here is
the detectable signal the roadmap actually asks for: multiple GPUs on the
same node, owned by *different* workloads, all underutilized at the same
time, for long enough that it's a pattern rather than a coincidence. A
single workload spread across several GPUs for a distributed job is
excluded on purpose -- that's an intentional multi-GPU allocation, not
fragmentation, even if each GPU looks underused individually.
"""
from __future__ import annotations

import time
from collections import defaultdict

from waste_detector.config import Config
from waste_detector.findings import FRAGMENTED, WasteFinding
from waste_detector.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600  # hourly rollups only


def _gpu_identity(row: RollupRow) -> tuple:
    return (row.node, row.gpu_index, row.gpu_instance_id)


def _find_qualifying_hours(
    rows: list[RollupRow], config: Config
) -> dict[tuple, list[RollupRow]]:
    """(node, bucket_start) -> the underutilized rows in that hour, for
    every hour where enough distinct GPUs from distinct workloads on that
    node were simultaneously underutilized."""
    usable = [
        r for r in rows
        if r.attributed and r.coverage_ratio >= config.min_coverage_ratio
        and r.avg_utilization_pct is not None
    ]

    by_hour: dict[tuple, list[RollupRow]] = defaultdict(list)
    for row in usable:
        by_hour[(row.node, row.bucket_start)].append(row)

    qualifying = {}
    for key, hour_rows in by_hour.items():
        # Inclusive of the threshold itself, consistent with every other
        # detector (idle.py, over_provisioning.py, patterns.py) -- a GPU
        # sitting exactly at the threshold counts as qualifying everywhere
        # in this module, not just here.
        underutilized = [r for r in hour_rows if r.avg_utilization_pct <= config.fragmentation_threshold_pct]
        distinct_gpus = {_gpu_identity(r) for r in underutilized}
        distinct_workloads = {(r.namespace, r.workload) for r in underutilized}
        if (
            len(distinct_gpus) >= config.fragmentation_min_underutilized_gpus
            and len(distinct_workloads) >= 2
        ):
            qualifying[key] = underutilized

    return qualifying


def _streaks_for_node(bucket_starts: list[float]) -> list[list[float]]:
    streaks: list[list[float]] = []
    current: list[float] = []
    for bs in sorted(bucket_starts):
        if current and bs == current[-1] + _BUCKET_SECONDS:
            current.append(bs)
        else:
            if current:
                streaks.append(current)
            current = [bs]
    if current:
        streaks.append(current)
    return streaks


def _findings_for_streak(
    node: str,
    streak_hours: list[float],
    qualifying: dict[tuple, list[RollupRow]],
    config: Config,
) -> list[WasteFinding]:
    if len(streak_hours) < config.fragmentation_min_streak_hours:
        return []

    rows_by_gpu: dict[tuple, list[RollupRow]] = defaultdict(list)
    workloads_per_hour = []
    for bs in streak_hours:
        hour_rows = qualifying[(node, bs)]
        workloads_per_hour.append(len({(r.namespace, r.workload) for r in hour_rows}))
        for row in hour_rows:
            rows_by_gpu[_gpu_identity(row)].append(row)

    avg_underutilized_gpus = sum(
        len({_gpu_identity(r) for r in qualifying[(node, bs)]}) for bs in streak_hours
    ) / len(streak_hours)
    avg_workloads = sum(workloads_per_hour) / len(workloads_per_hour)

    findings = []
    for (gpu_node, gpu_index, gpu_instance_id), gpu_rows in rows_by_gpu.items():
        # A GPU may drop in and out of the underutilized set within the
        # streak; report the finding over the hours it actually appeared in.
        namespace = gpu_rows[0].namespace
        workload = gpu_rows[0].workload
        window_start = min(r.bucket_start for r in gpu_rows)
        window_end = max(r.bucket_start for r in gpu_rows) + _BUCKET_SECONDS
        confidence = sum(r.coverage_ratio for r in gpu_rows) / len(gpu_rows)

        findings.append(
            WasteFinding(
                category=FRAGMENTED,
                node=gpu_node,
                gpu_index=gpu_index,
                gpu_instance_id=gpu_instance_id,
                namespace=namespace,
                workload=workload,
                window_start=window_start,
                window_end=window_end,
                confidence=confidence,
                metric_value=avg_underutilized_gpus,
                detail=(
                    f"node {gpu_node} had an average of {avg_underutilized_gpus:.1f} GPUs "
                    f"(< {config.fragmentation_threshold_pct:.0f}% utilized) from "
                    f"{avg_workloads:.1f} distinct workloads simultaneously idle-ish "
                    f"for {len(streak_hours)}h -- consider consolidating"
                ),
            )
        )
    return findings


def detect_fragmentation(
    rows: list[RollupRow], config: Config, now: float | None = None
) -> list[WasteFinding]:
    now = now if now is not None else time.time()

    qualifying = _find_qualifying_hours(rows, config)

    nodes = {node for node, _ in qualifying}
    findings = []
    for node in nodes:
        bucket_starts = [bs for (n, bs) in qualifying if n == node]
        for streak_hours in _streaks_for_node(bucket_starts):
            findings.extend(_findings_for_streak(node, streak_hours, qualifying, config))

    return findings
