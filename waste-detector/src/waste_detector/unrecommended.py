"""Waste detected without a reliable recommendation.

The other detectors only report waste they can attach a recommendation to,
so anything they can't explain -- or explain correctly -- used to go
unmeasured. Fixing fragmentation's bad advice for multi-GPU jobs showed the
cost of that: on the Philly replay, correcting the recommendation also made
6.3 points of underused GPU-hours disappear from the report, even though the
GPUs really were underused.

This module is the catch-all beneath the actionable categories. Every
GPU-hour whose average utilization is below an efficient-use target (70% by
default, the same ceiling savings-estimator right-sizes against) and that no
other finding already covers is reported here, in one of two categories:

- UNDERUTILIZED: attributed to a workload. Typical causes are bursty
  traffic too short for the idle detector, a single-GPU workload with no
  co-located partner to consolidate with, or a pattern no detector
  classifies.
- UNATTRIBUTED_GPU_TIME: a GPU with no Kubernetes pod attached -- either an
  unassigned GPU on a running node, or work running outside Kubernetes.
  Every other detector skips this time entirely.

metric_value is the average shortfall below the target as a fraction of the
GPU (a GPU averaging 20% against a 70% target is 0.5), so the cost of that
unused capacity over the finding's window is a plain multiplication. These
findings carry no recommendation and are kept out of the dashboard's
headline totals.
"""
from __future__ import annotations

import time
from collections import defaultdict

from waste_detector.config import Config
from waste_detector.findings import (
    RECURRING_PATTERN,
    UNATTRIBUTED_GPU_TIME,
    UNDERUTILIZED,
    WasteFinding,
)
from waste_detector.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600  # hourly rollups only


def _unit(node, gpu_index, gpu_instance_id, namespace, workload, bucket_start: float) -> tuple:
    return (node, gpu_index, gpu_instance_id, namespace, workload, float(bucket_start))


def covered_units(findings: list[WasteFinding]) -> set[tuple]:
    """Every (GPU, workload, hour) some finding already accounts for.

    A recurring-pattern finding's window spans its whole multi-day
    observation, but it only flags one hour of each day -- counting the
    whole span as covered would hide every other hour of that GPU's day.
    """
    covered = set()
    for f in findings:
        t = f.window_start
        pattern_hour = int((f.window_start // _BUCKET_SECONDS) % 24)
        while t < f.window_end:
            if f.category != RECURRING_PATTERN or int((t // _BUCKET_SECONDS) % 24) == pattern_hour:
                covered.add(_unit(f.node, f.gpu_index, f.gpu_instance_id, f.namespace, f.workload, t))
            t += _BUCKET_SECONDS
    return covered


def _runs(rows: list[RollupRow]) -> list[list[RollupRow]]:
    runs: list[list[RollupRow]] = []
    current: list[RollupRow] = []
    for row in sorted(rows, key=lambda r: r.bucket_start):
        if current and row.bucket_start == current[-1].bucket_start + _BUCKET_SECONDS:
            current.append(row)
        else:
            if current:
                runs.append(current)
            current = [row]
    if current:
        runs.append(current)
    return runs


def _detail(category: str, run: list[RollupRow], avg_util: float, config: Config) -> str:
    hours = len(run)
    target = config.underutilized_target_pct
    if category == UNATTRIBUTED_GPU_TIME:
        return (
            f"GPU not tied to any Kubernetes pod for {hours}h, averaging {avg_util:.1f}% busy "
            f"(below the {target:.0f}% target) -- either an unassigned GPU on a running node or "
            f"work running outside Kubernetes. Detected waste, no recommendation yet"
        )
    return (
        f"averaged {avg_util:.1f}% busy over {hours}h, below the {target:.0f}% efficient-use "
        f"target, and not covered by any actionable finding -- detected waste, no reliable "
        f"recommendation yet (e.g. bursts too short to call idle, no co-located workload to "
        f"consolidate with, or a pattern the detectors don't classify)"
    )


def detect_unrecommended_waste(
    rows: list[RollupRow],
    already_found: list[WasteFinding],
    config: Config,
    now: float | None = None,
) -> list[WasteFinding]:
    now = now if now is not None else time.time()
    covered = covered_units(already_found)
    target = config.underutilized_target_pct

    groups: dict[tuple, list[RollupRow]] = defaultdict(list)
    for r in rows:
        if r.coverage_ratio < config.min_coverage_ratio or r.avg_utilization_pct is None:
            continue
        if r.avg_utilization_pct >= target:
            continue
        if _unit(r.node, r.gpu_index, r.gpu_instance_id, r.namespace, r.workload, r.bucket_start) in covered:
            continue
        groups[(r.node, r.gpu_index, r.gpu_instance_id, r.namespace, r.workload)].append(r)

    findings = []
    for (node, gpu_index, gpu_instance_id, namespace, workload), group_rows in groups.items():
        category = UNDERUTILIZED if workload is not None else UNATTRIBUTED_GPU_TIME
        for run in _runs(group_rows):
            if len(run) < config.underutilized_min_run_hours:
                continue
            avg_util = sum(r.avg_utilization_pct for r in run) / len(run)
            shortfall = sum((target - r.avg_utilization_pct) / 100.0 for r in run) / len(run)
            findings.append(
                WasteFinding(
                    category=category,
                    node=node,
                    gpu_index=gpu_index,
                    gpu_instance_id=gpu_instance_id,
                    namespace=namespace,
                    workload=workload,
                    window_start=run[0].bucket_start,
                    window_end=run[-1].bucket_start + _BUCKET_SECONDS,
                    confidence=sum(r.coverage_ratio for r in run) / len(run),
                    metric_value=shortfall,
                    detail=_detail(category, run, avg_util, config),
                )
            )
    return findings
