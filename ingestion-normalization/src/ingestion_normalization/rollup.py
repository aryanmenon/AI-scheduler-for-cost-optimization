"""Bucket normalized samples into fixed-width time-series rollups.

The roadmap calls out "handle missing data and gaps explicitly" as its own
requirement, separate from just building the aggregation layer. The
mechanism here is coverage_ratio: every bucket records how many samples it
actually got against how many a full window at the source scrape cadence
would produce. A collector outage, a still-filling "current" bucket, and a
genuinely idle GPU all produce *different* signals under this scheme --
only the last one has full coverage with low utilization. Averaging
present-but-incomplete samples as if the bucket were whole would conflate
"no data" with "verified low usage," which is exactly the kind of wrong
recommendation that costs a customer's trust (see the roadmap's waste
detector risk note).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from ingestion_normalization.normalizer import NormalizedRecord

GRANULARITY_SECONDS = {
    "5m": 300,
    "hourly": 3600,
    "daily": 86400,
}


@dataclass
class RollupRecord:
    bucket_start: float
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    namespace: str
    workload: str | None
    sample_count: int
    expected_sample_count: float
    coverage_ratio: float
    low_confidence: bool
    avg_utilization_pct: float | None
    max_utilization_pct: float | None
    avg_memory_used_mb: float | None
    avg_power_draw_w: float | None
    avg_effective_tflops: float | None
    # Carried through (not aggregated) from the group's samples: a
    # physical GPU's model doesn't change within an hour, so any sample in
    # the group reflects it. Downstream consumers (the savings estimator)
    # need this to price a bucket without re-deriving the GPU's capability
    # from avg_effective_tflops, which is impossible when utilization is 0.
    gpu_model: str | None
    fp16_tflops: float | None
    # Peak framebuffer memory used in the bucket, and the GPU's usable
    # memory size as reported by DCGM (used + free on the same sample).
    # savings-estimator's right-sizing needs the peak, not the average, to
    # decide whether a workload fits a smaller GPU. Defaults keep older
    # callers (and rows written before these columns existed) valid.
    max_memory_used_mb: float | None = None
    memory_total_mb: float | None = None


def bucket_start_for(ts: float, bucket_seconds: int) -> float:
    return math.floor(ts / bucket_seconds) * bucket_seconds


def _avg(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _max(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def compute_rollups(
    records: list[NormalizedRecord],
    granularity: str,
    scrape_interval_seconds: float,
    low_confidence_threshold: float = 0.5,
) -> list[RollupRecord]:
    if granularity not in GRANULARITY_SECONDS:
        raise ValueError(f"unknown granularity: {granularity}")
    if scrape_interval_seconds <= 0:
        raise ValueError("scrape_interval_seconds must be positive")

    bucket_seconds = GRANULARITY_SECONDS[granularity]
    expected = bucket_seconds / scrape_interval_seconds

    groups: dict[tuple, list[NormalizedRecord]] = defaultdict(list)
    for r in records:
        key = (
            bucket_start_for(r.scraped_at, bucket_seconds),
            r.node,
            r.gpu_index,
            r.gpu_instance_id,
            r.namespace,
            r.workload,
        )
        groups[key].append(r)

    rollups = []
    for (bucket_start, node, gpu_index, gpu_instance_id, namespace, workload), items in groups.items():
        coverage_ratio = min(1.0, len(items) / expected)
        rollups.append(
            RollupRecord(
                bucket_start=bucket_start,
                node=node,
                gpu_index=gpu_index,
                gpu_instance_id=gpu_instance_id,
                namespace=namespace,
                workload=workload,
                sample_count=len(items),
                expected_sample_count=expected,
                coverage_ratio=coverage_ratio,
                low_confidence=coverage_ratio < low_confidence_threshold,
                avg_utilization_pct=_avg([i.utilization_pct for i in items]),
                max_utilization_pct=_max([i.utilization_pct for i in items]),
                avg_memory_used_mb=_avg([i.memory_used_mb for i in items]),
                avg_power_draw_w=_avg([i.power_draw_w for i in items]),
                avg_effective_tflops=_avg([i.effective_tflops for i in items]),
                gpu_model=items[0].gpu_model,
                fp16_tflops=items[0].fp16_tflops,
                max_memory_used_mb=_max([i.memory_used_mb for i in items]),
                memory_total_mb=_max([
                    i.memory_used_mb + i.memory_free_mb
                    for i in items
                    if i.memory_used_mb is not None and i.memory_free_mb is not None
                ]),
            )
        )
    return rollups
