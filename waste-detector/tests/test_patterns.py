from waste_detector.config import Config
from waste_detector.findings import RECURRING_PATTERN
from waste_detector.patterns import detect_recurring_patterns
from waste_detector.rollup_reader import RollupRow

_DAY = 86400
_HOUR = 3600


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


def _row(bucket_start, avg_utilization_pct=50.0, coverage_ratio=1.0, **overrides) -> RollupRow:
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
        max_utilization_pct=avg_utilization_pct + 5.0,
        avg_memory_used_mb=1000.0,
        avg_power_draw_w=100.0,
        avg_effective_tflops=30.0,
    )
    defaults.update(overrides)
    return RollupRow(**defaults)


def _daily_rows(n_days: int, hour_of_day: int, avg_utilization_pct_fn) -> list[RollupRow]:
    rows = []
    for day in range(n_days):
        bucket_start = day * _DAY + hour_of_day * _HOUR
        rows.append(_row(float(bucket_start), avg_utilization_pct=avg_utilization_pct_fn(day)))
    return rows


def test_flags_consistent_overnight_low_usage():
    # Quiet at 3am on every one of 10 observed days.
    rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 1.0)
    findings = detect_recurring_patterns(rows, _config())
    assert len(findings) == 1
    f = findings[0]
    assert f.category == RECURRING_PATTERN
    assert f.metric_value == 1.0


def test_tolerates_occasional_exception_night():
    # Quiet at 3am on 9 of 10 days; one noisy night (a deploy, a retry storm).
    rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 60.0 if day == 5 else 1.0)
    findings = detect_recurring_patterns(rows, _config(pattern_min_consistent_fraction=0.8))
    assert len(findings) == 1
    assert findings[0].metric_value == 0.9


def test_utilization_exactly_at_threshold_counts_as_quiet():
    # Boundary semantics: pattern_idle_threshold_pct=5.0 is inclusive --
    # exactly at the threshold counts as quiet, consistent across every
    # detector.
    rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 5.0)
    findings = detect_recurring_patterns(rows, _config())
    assert len(findings) == 1
    assert findings[0].metric_value == 1.0


def test_does_not_flag_below_minimum_days_observed():
    rows = _daily_rows(5, hour_of_day=3, avg_utilization_pct_fn=lambda day: 1.0)  # need 7
    findings = detect_recurring_patterns(rows, _config(pattern_min_days_observed=7))
    assert findings == []


def test_does_not_flag_consistently_busy_hour():
    rows = _daily_rows(10, hour_of_day=14, avg_utilization_pct_fn=lambda day: 70.0)
    findings = detect_recurring_patterns(rows, _config())
    assert findings == []


def test_does_not_flag_inconsistent_hour_below_fraction_threshold():
    # Quiet only half the time -- not a reliable enough pattern to act on.
    rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 1.0 if day % 2 == 0 else 60.0)
    findings = detect_recurring_patterns(rows, _config(pattern_min_consistent_fraction=0.8))
    assert findings == []


def test_different_hours_of_day_evaluated_independently():
    quiet_rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 1.0)
    busy_rows = _daily_rows(10, hour_of_day=14, avg_utilization_pct_fn=lambda day: 70.0)
    findings = detect_recurring_patterns(quiet_rows + busy_rows, _config())
    assert len(findings) == 1


def test_unattributed_never_flagged():
    rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 1.0)
    for r in rows:
        r.namespace = "unattributed"
        r.workload = None
    findings = detect_recurring_patterns(rows, _config())
    assert findings == []


def test_low_coverage_days_excluded_from_consistency_calc():
    rows = _daily_rows(10, hour_of_day=3, avg_utilization_pct_fn=lambda day: 1.0)
    # Drop coverage on a couple of days -- they must not count as either
    # supporting or refuting the pattern.
    rows[0].coverage_ratio = 0.1
    rows[1].coverage_ratio = 0.1
    findings = detect_recurring_patterns(rows, _config(pattern_min_days_observed=7))
    assert len(findings) == 1
    assert findings[0].metric_value == 1.0
