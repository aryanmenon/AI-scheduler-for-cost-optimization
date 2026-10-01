"""Fragmentation: several small workloads each partially using their own
GPU, on a node where their combined work could fit on fewer GPUs.

This is the hardest of the three waste categories -- true bin-packing
(could these specific workloads actually be co-scheduled, given memory and
scheduling constraints?) is out of scope for an MVP. What's built here is
the detectable signal the roadmap actually asks for: multiple GPUs on the
same node, owned by *different* workloads, all underutilized at the same
time, for long enough that it's a pattern rather than a coincidence.

A finding here is a consolidation *candidate*, not a proven consolidation.
Nothing in this module checks whether the workloads' GPU memory or combined
compute would fit on fewer GPUs, or whether the cluster has GPU sharing
(time-slicing, MPS, or MIG) enabled at all -- Kubernetes otherwise gives
each pod a whole GPU, so co-locating two pods on one GPU is impossible
without it. The finding's detail text says so, so nobody acts on it as if
it had been checked.

Any workload holding more than one GPU in a given hour is excluded from
that hour entirely, whether or not the other workloads around it
qualify. Distributed training and tensor-parallel inference run one
process per GPU (NCCL refuses two ranks on the same GPU), so "consolidate
onto a shared GPU" is never actionable advice for them; their low
per-GPU utilization usually has a different cause and fix. Rollups only
carry workload identity, not pod, so this also excludes a Deployment
whose replicas each hold one GPU -- deliberately conservative, since a
wrong "consolidate" recommendation costs more trust than a missed one.
idle.py and over_provisioning.py still evaluate those GPUs individually.
"""
from __future__ import annotations

import time
from collections import defaultdict

from waste_detector.config import Config
from waste_detector.findings import FRAGMENTED, WasteFinding
from waste_detector.grouping import group_by, usable_rows
from waste_detector.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600  # hourly rollups only


def _gpu_identity(row: RollupRow) -> tuple:
    return (row.node, row.gpu_index, row.gpu_instance_id)


def _multi_gpu_workloads_by_hour(rows: list[RollupRow]) -> dict[float, set[tuple]]:
    """bucket_start -> workloads seen on more than one distinct GPU in that
    hour, counted across every node so a job spanning nodes is caught too,
    and across all of its GPUs (not only underutilized ones) so a job with
    one busy GPU and three idle ones still counts as multi-GPU."""
    gpus_by_workload: dict[tuple, set[tuple]] = defaultdict(set)
    for r in rows:
        gpus_by_workload[(r.bucket_start, r.namespace, r.workload)].add(_gpu_identity(r))

    multi_gpu: dict[float, set[tuple]] = defaultdict(set)
    for (bucket_start, namespace, workload), gpus in gpus_by_workload.items():
        if len(gpus) > 1:
            multi_gpu[bucket_start].add((namespace, workload))
    return multi_gpu


def _find_qualifying_hours(
    rows: list[RollupRow], config: Config
) -> dict[tuple, list[RollupRow]]:
    """(node, bucket_start) -> the underutilized rows in that hour, for
    every hour where enough distinct GPUs from distinct workloads on that
    node were simultaneously underutilized."""
    usable = usable_rows(rows, config, require_utilization=True)
    multi_gpu = _multi_gpu_workloads_by_hour(usable)
    by_hour = group_by(usable, lambda r: (r.node, r.bucket_start))

    qualifying = {}
    for key, hour_rows in by_hour.items():
        excluded = multi_gpu.get(key[1], set())
        hour_rows = [r for r in hour_rows if (r.namespace, r.workload) not in excluded]
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
                    f"for {len(streak_hours)}h -- consolidation candidate, needs engineer review: "
                    f"GPU memory fit, combined compute, and whether GPU sharing (time-slicing, "
                    f"MPS, or MIG) is enabled on this cluster were not checked"
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
