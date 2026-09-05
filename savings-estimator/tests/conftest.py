"""Test-only dependency on the real storage of the two upstream components,
so reader/pipeline tests exercise the actual schemas rather than a
hand-rolled copy (see findings_reader.py / rollup_reader.py docstrings for
why production code reads schemas directly instead of importing code).

pip install -e ../ingestion-normalization -e ../waste-detector -e ".[dev]"
before running tests.
"""
from ingestion_normalization.rollup import RollupRecord
from ingestion_normalization.storage import NormalizedStorage
from waste_detector.findings import FindingsStorage, WasteFinding


def make_rollup_record(
    bucket_start: float,
    node: str = "gpu-node-1",
    gpu_index: str = "0",
    gpu_instance_id: str | None = None,
    namespace: str = "inference",
    workload: str | None = "bert-large",
    sample_count: int = 120,
    expected_sample_count: float = 120.0,
    avg_utilization_pct: float | None = 20.0,
    max_utilization_pct: float | None = 25.0,
    avg_memory_used_mb: float | None = 1000.0,
    avg_power_draw_w: float | None = 200.0,
    avg_effective_tflops: float | None = 60.0,
    gpu_model: str | None = "NVIDIA A100-SXM4-80GB",
    fp16_tflops: float | None = 312.0,
    low_confidence_threshold: float = 0.5,
) -> RollupRecord:
    coverage_ratio = min(1.0, sample_count / expected_sample_count)
    return RollupRecord(
        bucket_start=bucket_start,
        node=node,
        gpu_index=gpu_index,
        gpu_instance_id=gpu_instance_id,
        namespace=namespace,
        workload=workload,
        sample_count=sample_count,
        expected_sample_count=expected_sample_count,
        coverage_ratio=coverage_ratio,
        low_confidence=coverage_ratio < low_confidence_threshold,
        avg_utilization_pct=avg_utilization_pct,
        max_utilization_pct=max_utilization_pct,
        avg_memory_used_mb=avg_memory_used_mb,
        avg_power_draw_w=avg_power_draw_w,
        avg_effective_tflops=avg_effective_tflops,
        gpu_model=gpu_model,
        fp16_tflops=fp16_tflops,
    )


def write_rollups(path: str, granularity: str, records: list[RollupRecord]) -> None:
    storage = NormalizedStorage(path)
    if records:
        start = min(r.bucket_start for r in records)
        end = max(r.bucket_start for r in records) + 1
        storage.replace_rollups(granularity, start, end, records)
    storage.close()


def make_finding(category: str, **overrides) -> WasteFinding:
    defaults = dict(
        category=category,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        window_start=0.0,
        window_end=3600.0,
        confidence=0.9,
        metric_value=4.0,
        detail="synthetic test finding",
    )
    defaults.update(overrides)
    return WasteFinding(**defaults)


def write_findings(path: str, findings: list[WasteFinding], detected_at: float = 1000.0) -> None:
    storage = FindingsStorage(path)
    storage.insert_findings(findings, detected_at=detected_at)
    storage.close()
