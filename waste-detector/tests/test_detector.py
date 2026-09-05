from waste_detector.config import Config
from waste_detector.detector import run_all_detectors
from waste_detector.findings import FRAGMENTED, IDLE, OVER_PROVISIONED, RECURRING_PATTERN
from waste_detector.rollup_reader import RollupRow


def _config(**overrides) -> Config:
    defaults = dict(
        normalized_sqlite_path=":memory:",
        findings_sqlite_path=":memory:",
        poll_interval_seconds=300,
        min_coverage_ratio=0.8,
        idle_threshold_pct=2.0,
        min_idle_streak_hours=4,
        over_provision_threshold_pct=30.0,
        over_provision_min_observation_hours=24,
        fragmentation_threshold_pct=50.0,
        fragmentation_min_underutilized_gpus=2,
        fragmentation_min_streak_hours=4,
        pattern_min_days_observed=7,
        pattern_idle_threshold_pct=5.0,
        pattern_min_consistent_fraction=0.8,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _row(bucket_start, node, gpu_index, workload, avg_utilization_pct, max_utilization_pct=None, **overrides) -> RollupRow:
    defaults = dict(
        id=1,
        granularity="hourly",
        bucket_start=bucket_start,
        node=node,
        gpu_index=gpu_index,
        gpu_instance_id=None,
        namespace="inference",
        workload=workload,
        sample_count=120,
        expected_sample_count=120.0,
        coverage_ratio=1.0,
        low_confidence=False,
        avg_utilization_pct=avg_utilization_pct,
        max_utilization_pct=max_utilization_pct if max_utilization_pct is not None else avg_utilization_pct,
        avg_memory_used_mb=1000.0,
        avg_power_draw_w=100.0,
        avg_effective_tflops=30.0,
    )
    defaults.update(overrides)
    return RollupRow(**defaults)


def test_all_four_categories_detected_independently_in_one_run():
    rows = []

    # Idle: 6 consecutive quiet hours on node-1/gpu-0.
    rows += [_row(i * 3600.0, "node-1", "0", "abandoned-svc", 0.0, 0.0) for i in range(6)]

    # Over-provisioned: 24h of low peaks on node-2/gpu-0.
    rows += [_row(i * 3600.0, "node-2", "0", "over-sized-svc", 10.0, 20.0) for i in range(24)]

    # Fragmented: two distinct underutilized workloads on node-3 for 4h.
    rows += [_row(i * 3600.0, "node-3", "0", "small-a", 20.0, 25.0) for i in range(4)]
    rows += [_row(i * 3600.0, "node-3", "1", "small-b", 15.0, 20.0) for i in range(4)]

    # Recurring pattern: quiet at hour 3 on node-4/gpu-0 across 10 days.
    rows += [_row(day * 86400 + 3 * 3600.0, "node-4", "0", "batch-job", 1.0, 3.0) for day in range(10)]

    findings = run_all_detectors(rows, _config())
    categories = {f.category for f in findings}
    assert categories == {IDLE, OVER_PROVISIONED, FRAGMENTED, RECURRING_PATTERN}

    by_category = {c: [f for f in findings if f.category == c] for c in categories}
    assert {f.workload for f in by_category[IDLE]} == {"abandoned-svc"}
    assert {f.workload for f in by_category[OVER_PROVISIONED]} == {"over-sized-svc"}
    assert {f.workload for f in by_category[FRAGMENTED]} == {"small-a", "small-b"}
    assert {f.workload for f in by_category[RECURRING_PATTERN]} == {"batch-job"}


def test_healthy_bursty_workload_produces_no_findings():
    # High peaks, high average -- a well-utilized, busy service.
    rows = [_row(i * 3600.0, "node-1", "0", "healthy-svc", 70.0, 95.0) for i in range(48)]
    findings = run_all_detectors(rows, _config())
    assert findings == []


def test_empty_input_produces_no_findings():
    assert run_all_detectors([], _config()) == []
