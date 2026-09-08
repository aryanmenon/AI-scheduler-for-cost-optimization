from waste_detector.config import Config
from waste_detector.findings import IDLE
from waste_detector.idle import detect_idle
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


def _row(bucket_start, avg_utilization_pct=0.0, max_utilization_pct=0.0, coverage_ratio=1.0, **overrides) -> RollupRow:
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
        avg_utilization_pct=avg_utilization_pct,
        max_utilization_pct=max_utilization_pct,
        avg_memory_used_mb=1000.0,
        avg_power_draw_w=50.0,
        avg_effective_tflops=0.0,
    )
    defaults.update(overrides)
    return RollupRow(**defaults)


def test_flags_sustained_idle_streak():
    rows = [_row(i * 3600.0) for i in range(6)]
    findings = detect_idle(rows, _config())
    assert len(findings) == 1
    f = findings[0]
    assert f.category == IDLE
    assert f.metric_value == 6.0
    assert f.window_start == 0.0
    assert f.window_end == 6 * 3600.0


def test_does_not_flag_streak_shorter_than_minimum():
    rows = [_row(i * 3600.0) for i in range(3)]  # below min_idle_streak_hours=4
    findings = detect_idle(rows, _config())
    assert findings == []


def test_bursty_but_used_traffic_not_flagged():
    # Low average utilization every hour (normal for bursty inference) but
    # a real request burst inside every single hour -- this is a healthy
    # service, not an idle one, and must never be flagged.
    rows = [_row(i * 3600.0, avg_utilization_pct=1.5, max_utilization_pct=45.0) for i in range(10)]
    findings = detect_idle(rows, _config())
    assert findings == []


def test_single_burst_hour_breaks_an_otherwise_idle_streak():
    rows = [_row(i * 3600.0) for i in range(4)]
    rows.append(_row(4 * 3600.0, avg_utilization_pct=0.5, max_utilization_pct=80.0))  # one real burst
    rows += [_row(i * 3600.0) for i in range(5, 9)]
    findings = detect_idle(rows, _config())
    # Two separate streaks of 4, each meeting the minimum, split by the burst.
    assert len(findings) == 2
    assert {f.metric_value for f in findings} == {4.0}


def test_low_coverage_hour_breaks_streak_continuity():
    rows = [_row(i * 3600.0) for i in range(4)]
    rows.append(_row(4 * 3600.0, coverage_ratio=0.1))  # missing data, not confirmed idle
    rows += [_row(i * 3600.0) for i in range(5, 9)]
    findings = detect_idle(rows, _config())
    assert len(findings) == 2
    assert {f.metric_value for f in findings} == {4.0}


def test_time_gap_between_buckets_breaks_streak_continuity():
    rows = [_row(i * 3600.0) for i in range(4)]
    rows += [_row(i * 3600.0) for i in range(10, 14)]  # non-contiguous jump
    findings = detect_idle(rows, _config())
    assert len(findings) == 2


def test_utilization_exactly_at_threshold_counts_as_idle():
    # Boundary semantics: idle_threshold_pct=2.0 is inclusive -- exactly at
    # the threshold qualifies, consistent across every detector in this
    # module (see fragmentation.py, which was the one exception until it
    # was aligned to match).
    rows = [_row(i * 3600.0, avg_utilization_pct=2.0, max_utilization_pct=2.0) for i in range(6)]
    findings = detect_idle(rows, _config())
    assert len(findings) == 1


def test_unattributed_gpu_never_flagged():
    rows = [_row(i * 3600.0, namespace="unattributed", workload=None) for i in range(6)]
    findings = detect_idle(rows, _config())
    assert findings == []


def test_confidence_reflects_average_coverage_across_streak():
    rows = [_row(i * 3600.0, coverage_ratio=1.0) for i in range(3)]
    rows.append(_row(3 * 3600.0, coverage_ratio=0.8))
    findings = detect_idle(rows, _config())
    assert len(findings) == 1
    assert findings[0].confidence == (1.0 + 1.0 + 1.0 + 0.8) / 4
