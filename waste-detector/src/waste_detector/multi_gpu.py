"""Multi-GPU jobs that may be able to run on fewer GPUs.

fragmentation.py deliberately excludes any workload holding more than one
GPU: distributed training and tensor-parallel inference run one process per
GPU, so "consolidate onto a shared GPU" can't be acted on. Their
underutilization is still real, though -- on the Philly replay, multi-GPU
GPU-hours averaging 2-50% that no other detector flags came to 22% of all
GPU-hours -- and the actionable question for them is a different one:
could this job have been given fewer GPUs?

For each hour a workload holds N > 1 GPUs, the GPUs' hourly-average busy
time is summed and divided by a per-GPU ceiling (70% by default) to get how
many GPUs that load would need. If that's fewer than N for a long enough
streak, every GPU of the job gets a finding whose metric_value is the
fraction of the job's GPUs that could be released (the smallest such
fraction across the streak).

This is a visibility signal and an upper bound, not a verified
recommendation, and it is sized on purpose from hourly *averages*:

- Sizing on hourly peaks instead was prototyped on Philly and found almost
  nothing (+0.4 points of GPU-hours vs +6.6 for averages), because a job's
  busiest minute in an hour is usually high. Averages show the scale of
  the opportunity; they also mean a smaller GPU count could push the job's
  bursts past the ceiling and slow it down.
- DCGM_FI_DEV_GPU_UTIL is the share of time any kernel was running, not how
  much of the GPU it used, so summed busy time is a rough proxy for work.
- GPU memory fit isn't checked (rollups don't carry peak memory or GPU
  memory capacity yet): a model sharded across N GPUs may simply not fit in
  fewer.
- For data-parallel training, fewer GPUs means a smaller global batch (or
  more gradient accumulation) and a longer run; and low utilization in
  training is often a data-loading or communication bottleneck, which is
  cheaper to fix than the GPU count.

Rollups only carry workload identity, not pod, so a Deployment whose
replicas each hold one GPU also counts as a "multi-GPU job" here -- and for
it, fewer replicas is genuinely the fix. The finding's detail spells all of
this out, and savings-estimator prices it on a separate basis that the
dashboard keeps out of its headline total.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict

from waste_detector.config import Config
from waste_detector.findings import MULTI_GPU_OVERSIZED, WasteFinding
from waste_detector.grouping import group_by, usable_rows
from waste_detector.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600  # hourly rollups only


def _gpu_identity(row: RollupRow) -> tuple:
    return (row.node, row.gpu_index, row.gpu_instance_id)


def _releasable_by_hour(
    rows: list[RollupRow], config: Config
) -> dict[tuple, dict[float, tuple[int, int, float, list[RollupRow]]]]:
    """(namespace, workload) -> bucket_start -> (gpus held, gpus releasable,
    summed avg busy %, rows), for hours where at least one GPU could go."""
    usable = usable_rows(rows, config, require_utilization=True)
    by_workload_hour = group_by(usable, lambda r: (r.namespace, r.workload, r.bucket_start))

    result: dict[tuple, dict[float, tuple[int, int, float, list[RollupRow]]]] = defaultdict(dict)
    for (namespace, workload, bucket_start), hour_rows in by_workload_hour.items():
        held = len({_gpu_identity(r) for r in hour_rows})
        if held < 2:
            continue
        busy_sum = sum(r.avg_utilization_pct for r in hour_rows)
        needed = max(1, math.ceil(busy_sum / config.multi_gpu_target_utilization_pct))
        releasable = held - needed
        if releasable >= 1:
            result[(namespace, workload)][bucket_start] = (held, releasable, busy_sum, hour_rows)
    return result


def _streaks(bucket_starts: list[float]) -> list[list[float]]:
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
    namespace: str,
    workload: str | None,
    streak: list[float],
    hours: dict[float, tuple[int, int, float, list[RollupRow]]],
    config: Config,
) -> list[WasteFinding]:
    held_per_hour = [hours[bs][0] for bs in streak]
    # The smallest releasable *fraction* across the streak, so the claim
    # holds in every hour of it, not just on average.
    fraction = min(hours[bs][1] / hours[bs][0] for bs in streak)
    min_releasable = min(hours[bs][1] for bs in streak)
    avg_held = sum(held_per_hour) / len(held_per_hour)
    avg_busy_sum = sum(hours[bs][2] for bs in streak) / len(streak)

    rows_by_gpu: dict[tuple, list[RollupRow]] = defaultdict(list)
    for bs in streak:
        for row in hours[bs][3]:
            rows_by_gpu[_gpu_identity(row)].append(row)

    detail = (
        f"multi-GPU job held {avg_held:.1f} GPUs on average for {len(streak)}h with combined "
        f"hourly-average busy time of {avg_busy_sum:.0f}% of one GPU -- could likely release at "
        f"least {min_releasable} GPU(s) and keep each remaining GPU under "
        f"{config.multi_gpu_target_utilization_pct:.0f}% on hourly average. Upper bound for "
        f"review, not a verified recommendation: sized on hourly averages, so bursts may exceed "
        f"that ceiling on fewer GPUs; GPU memory fit not checked; GPU utilization is busy time, "
        f"not compute used; for training, fewer GPUs changes batch size and run time, and a "
        f"data-loading or communication bottleneck may be the cheaper fix"
    )

    findings = []
    for (node, gpu_index, gpu_instance_id), gpu_rows in rows_by_gpu.items():
        findings.append(
            WasteFinding(
                category=MULTI_GPU_OVERSIZED,
                node=node,
                gpu_index=gpu_index,
                gpu_instance_id=gpu_instance_id,
                namespace=namespace,
                workload=workload,
                window_start=min(r.bucket_start for r in gpu_rows),
                window_end=max(r.bucket_start for r in gpu_rows) + _BUCKET_SECONDS,
                confidence=sum(r.coverage_ratio for r in gpu_rows) / len(gpu_rows),
                metric_value=fraction,
                detail=detail,
            )
        )
    return findings


def detect_multi_gpu_oversized(
    rows: list[RollupRow], config: Config, now: float | None = None
) -> list[WasteFinding]:
    now = now if now is not None else time.time()

    findings = []
    for (namespace, workload), hours in _releasable_by_hour(rows, config).items():
        for streak in _streaks(list(hours)):
            if len(streak) < config.multi_gpu_min_streak_hours:
                continue
            findings.extend(_findings_for_streak(namespace, workload, streak, hours, config))
    return findings
