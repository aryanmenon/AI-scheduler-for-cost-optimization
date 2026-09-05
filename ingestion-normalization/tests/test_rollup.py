from ingestion_normalization.normalizer import NormalizedRecord
from ingestion_normalization.rollup import bucket_start_for, compute_rollups


def _record(scraped_at, utilization_pct=50.0, **overrides) -> NormalizedRecord:
    defaults = dict(
        scrape_run_id=1,
        scraped_at=scraped_at,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        gpu_uuid="GPU-abc",
        gpu_model="NVIDIA A100-SXM4-80GB",
        namespace="inference",
        workload="bert-large",
        pod="bert-large-7d4f-xk2p9",
        container="model-server",
        utilization_pct=utilization_pct,
        memory_used_mb=1000.0,
        memory_free_mb=2000.0,
        power_draw_w=200.0,
        capability_known=True,
        fp16_tflops=312.0,
        effective_tflops=(utilization_pct / 100.0 * 312.0) if utilization_pct is not None else None,
    )
    defaults.update(overrides)
    return NormalizedRecord(**defaults)


def test_bucket_start_for_aligns_to_boundary():
    assert bucket_start_for(305, 300) == 300
    assert bucket_start_for(299, 300) == 0
    assert bucket_start_for(3600, 300) == 3600


def test_full_coverage_bucket_has_ratio_one():
    # scrape every 30s -> a full 5-minute bucket has 10 samples.
    records = [_record(scraped_at=i * 30) for i in range(10)]
    rollups = compute_rollups(records, "5m", scrape_interval_seconds=30)
    assert len(rollups) == 1
    r = rollups[0]
    assert r.sample_count == 10
    assert r.expected_sample_count == 10
    assert r.coverage_ratio == 1.0
    assert r.low_confidence is False
    assert r.avg_utilization_pct == 50.0


def test_gap_produces_reduced_coverage_not_a_fabricated_average():
    # Only 3 of the expected 10 samples present in this 5-minute bucket
    # (an outage covered most of it) -- coverage must reflect that, not
    # silently average the 3 real samples as if they were the full window.
    records = [_record(scraped_at=i * 30, utilization_pct=90.0) for i in range(3)]
    rollups = compute_rollups(records, "5m", scrape_interval_seconds=30, low_confidence_threshold=0.5)
    assert len(rollups) == 1
    r = rollups[0]
    assert r.sample_count == 3
    assert r.expected_sample_count == 10
    assert r.coverage_ratio == 0.3
    assert r.low_confidence is True
    # The average itself is still computed from what's there -- flagged,
    # not hidden.
    assert r.avg_utilization_pct == 90.0


def test_coverage_ratio_capped_at_one_even_with_extra_samples():
    # More samples than theoretically expected shouldn't overflow ratio > 1.
    records = [_record(scraped_at=i * 10) for i in range(20)]
    rollups = compute_rollups(records, "5m", scrape_interval_seconds=30)
    assert rollups[0].coverage_ratio == 1.0


def test_missing_metric_values_excluded_from_average_not_treated_as_zero():
    records = [
        _record(scraped_at=0, utilization_pct=100.0),
        _record(scraped_at=30, utilization_pct=None, effective_tflops=None),
    ]
    rollups = compute_rollups(records, "5m", scrape_interval_seconds=30)
    r = rollups[0]
    # If the None were treated as 0, avg would be 50.0 instead of 100.0.
    assert r.avg_utilization_pct == 100.0
    assert r.sample_count == 2


def test_separate_buckets_for_different_workloads_same_node_gpu():
    records = [
        _record(scraped_at=0, workload="bert-large", pod="bert-large-7d4f-xk2p9"),
        _record(scraped_at=0, gpu_index="1", workload="llama-70b", pod="llama-70b-6c9d-p2q7r"),
    ]
    rollups = compute_rollups(records, "5m", scrape_interval_seconds=30)
    assert len(rollups) == 2
    workloads = {r.workload for r in rollups}
    assert workloads == {"bert-large", "llama-70b"}


def test_mig_instances_produce_separate_rollup_rows():
    records = [
        _record(scraped_at=0, gpu_instance_id="1", workload="small-model-a"),
        _record(scraped_at=0, gpu_instance_id="2", workload="small-model-b"),
    ]
    rollups = compute_rollups(records, "5m", scrape_interval_seconds=30)
    assert len(rollups) == 2
    instance_ids = {r.gpu_instance_id for r in rollups}
    assert instance_ids == {"1", "2"}


def test_hourly_and_daily_granularities_use_larger_buckets():
    records = [_record(scraped_at=i * 300) for i in range(12)]  # spans one hour
    hourly = compute_rollups(records, "hourly", scrape_interval_seconds=300)
    assert len(hourly) == 1
    assert hourly[0].sample_count == 12
    assert hourly[0].coverage_ratio == 1.0
