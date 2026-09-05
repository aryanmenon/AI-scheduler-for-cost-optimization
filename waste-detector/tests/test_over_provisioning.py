from waste_detector.config import Config
from waste_detector.findings import OVER_PROVISIONED
from waste_detector.over_provisioning import detect_over_provisioning
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


def _row(bucket_start, max_utilization_pct=20.0, coverage_ratio=1.0, **overrides) -> RollupRow:
    defaults = dict(
        id=1,
        granularity="hourly",
        bucket_start=bucket_start,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        sample_count=120,
        expected_sample_count=120.0,
        coverage_ratio=coverage_ratio,
        low_confidence=coverage_ratio < 0.5,
        avg_utilization_pct=10.0,
        max_utilization_pct=max_utilization_pct,
        avg_memory_used_mb=1000.0,
        avg_power_draw_w=200.0,
        avg_effective_tflops=30.0,
    )
    defaults.update(overrides)
    return RollupRow(**defaults)


def test_flags_workload_that_never_peaks_above_threshold():
    rows = [_row(i * 3600.0, max_utilization_pct=20.0) for i in range(24)]
    findings = detect_over_provisioning(rows, _config())
    assert len(findings) == 1
    f = findings[0]
    assert f.category == OVER_PROVISIONED
    assert f.workload == "bert-large"
    assert f.metric_value == 20.0
    assert f.confidence == 1.0


def test_does_not_flag_workload_with_a_real_peak():
    rows = [_row(i * 3600.0, max_utilization_pct=20.0) for i in range(23)]
    rows.append(_row(23 * 3600.0, max_utilization_pct=95.0))  # one real burst
    findings = detect_over_provisioning(rows, _config())
    assert findings == []


def test_requires_minimum_observation_window():
    # Only 5 hours observed -- too early to trust a verdict even though
    # every sample so far looks over-provisioned.
    rows = [_row(i * 3600.0, max_utilization_pct=20.0) for i in range(5)]
    findings = detect_over_provisioning(rows, _config(over_provision_min_observation_hours=24))
    assert findings == []


def test_low_coverage_rows_excluded_from_observation_count():
    good_rows = [_row(i * 3600.0, max_utilization_pct=20.0) for i in range(24)]
    noisy_rows = [_row((24 + i) * 3600.0, max_utilization_pct=95.0, coverage_ratio=0.1) for i in range(5)]
    findings = detect_over_provisioning(good_rows + noisy_rows, _config())
    # The low-coverage "burst" shouldn't rescue this from being flagged --
    # it's excluded as untrustworthy, not treated as evidence either way.
    assert len(findings) == 1
    assert findings[0].metric_value == 20.0


def test_unattributed_rows_never_flagged():
    rows = [_row(i * 3600.0, max_utilization_pct=20.0, namespace="unattributed", workload=None) for i in range(24)]
    findings = detect_over_provisioning(rows, _config())
    assert findings == []


def test_separate_workloads_produce_separate_findings():
    rows = [_row(i * 3600.0, max_utilization_pct=20.0, workload="bert-large") for i in range(24)]
    rows += [_row(i * 3600.0, max_utilization_pct=15.0, gpu_index="1", workload="llama-70b") for i in range(24)]
    findings = detect_over_provisioning(rows, _config())
    assert len(findings) == 2
    workloads = {f.workload for f in findings}
    assert workloads == {"bert-large", "llama-70b"}


def test_mig_instances_evaluated_independently():
    rows = [_row(i * 3600.0, max_utilization_pct=20.0, gpu_instance_id="1", workload="small-model-a") for i in range(24)]
    rows += [_row(i * 3600.0, max_utilization_pct=90.0, gpu_instance_id="2", workload="small-model-b") for i in range(24)]
    findings = detect_over_provisioning(rows, _config())
    assert len(findings) == 1
    assert findings[0].workload == "small-model-a"
