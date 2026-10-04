"""Over-provisioning: peak utilization never approaches what's allocated.

Per the roadmap, this is built first because it's a single-snapshot
comparison -- no time-pattern reasoning needed, just "has this workload's
peak utilization, over enough observed hours, ever gotten close to full
use of its GPU?" -- making it the fastest waste category to a
demonstrable number.
"""
from __future__ import annotations

import time

from waste_detector.config import Config
from waste_detector.findings import OVER_PROVISIONED, OVERSIZED_BY_AVERAGE, WasteFinding
from waste_detector.grouping import group_by, usable_rows
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
    usable = usable_rows(rows, config)
    groups = group_by(usable, _group_key)

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


def detect_oversized_by_average(
    rows: list[RollupRow], config: Config, now: float | None = None
) -> list[WasteFinding]:
    """Oversized GPUs the peak-based check above can't see.

    GPU busy % (DCGM_FI_DEV_GPU_UTIL) counts any time a kernel is running,
    so an LLM server reads 70-100% whenever a single request is in flight:
    on the 2026-10-04 mini-test (testing/rightsizing-mini-test/) an RTX 3090
    serving ~0.26 requests/s averaged 21% busy yet peaked at 71-75%, so
    detect_over_provisioning never fires for it. The busiest hour's
    *average* is the load signal that still means something there.

    Flags a workload whose peak is above over_provision_threshold_pct (the
    peak-based check owns everything at or below it) but whose busiest
    observed hour averaged at or below avg_load_threshold_pct, over the same
    minimum observation hours. metric_value is that busiest-hour average;
    savings-estimator sizes a smaller GPU against it with extra headroom,
    because an hourly average hides bursts within the hour.
    """
    usable = usable_rows(rows, config)
    groups = group_by(usable, _group_key)

    findings = []
    for (namespace, workload, node, gpu_index, gpu_instance_id), group_rows in groups.items():
        if len(group_rows) < config.over_provision_min_observation_hours:
            continue
        peaks = [r.max_utilization_pct for r in group_rows if r.max_utilization_pct is not None]
        averages = [r.avg_utilization_pct for r in group_rows if r.avg_utilization_pct is not None]
        if not peaks or not averages:
            continue
        if max(peaks) <= config.over_provision_threshold_pct:
            continue  # detect_over_provisioning reports this one
        busiest_hour_avg = max(averages)
        if busiest_hour_avg > config.avg_load_threshold_pct:
            continue

        findings.append(
            WasteFinding(
                category=OVERSIZED_BY_AVERAGE,
                node=node,
                gpu_index=gpu_index,
                gpu_instance_id=gpu_instance_id,
                namespace=namespace,
                workload=workload,
                window_start=min(r.bucket_start for r in group_rows),
                window_end=max(r.bucket_start for r in group_rows) + _BUCKET_SECONDS,
                confidence=sum(r.coverage_ratio for r in group_rows) / len(group_rows),
                metric_value=busiest_hour_avg,
                detail=(
                    f"busiest hour averaged {busiest_hour_avg:.1f}% utilization across "
                    f"{len(group_rows)}h observed (at or below {config.avg_load_threshold_pct:.0f}%), "
                    f"though momentary peaks reached {max(peaks):.0f}% -- typical of request-serving "
                    f"workloads, where any in-flight request reads as busy"
                ),
            )
        )
    return findings
