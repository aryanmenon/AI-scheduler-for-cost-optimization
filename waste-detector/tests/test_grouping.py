from waste_detector.config import Config
from waste_detector.grouping import group_by, usable_rows
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


def _row(**overrides) -> RollupRow:
    defaults = dict(
        id=1,
        granularity="hourly",
        bucket_start=0.0,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        sample_count=120,
        expected_sample_count=120.0,
        coverage_ratio=1.0,
        low_confidence=False,
        avg_utilization_pct=20.0,
        max_utilization_pct=25.0,
        avg_memory_used_mb=1000.0,
        avg_power_draw_w=100.0,
        avg_effective_tflops=30.0,
    )
    defaults.update(overrides)
    return RollupRow(**defaults)


def test_usable_rows_excludes_unattributed():
    rows = [_row(namespace="unattributed", workload=None), _row()]
    assert usable_rows(rows, _config()) == [rows[1]]


def test_usable_rows_excludes_low_coverage():
    rows = [_row(coverage_ratio=0.1), _row(coverage_ratio=1.0)]
    assert usable_rows(rows, _config(min_coverage_ratio=0.8)) == [rows[1]]


def test_usable_rows_requires_utilization_when_asked():
    rows = [_row(avg_utilization_pct=None), _row(avg_utilization_pct=20.0)]
    assert usable_rows(rows, _config(), require_utilization=True) == [rows[1]]
    # without require_utilization, the None-utilization row still passes
    assert usable_rows(rows, _config()) == rows


def test_group_by_partitions_by_key():
    rows = [_row(gpu_index="0"), _row(gpu_index="1"), _row(gpu_index="0")]
    groups = group_by(rows, lambda r: r.gpu_index)
    assert set(groups.keys()) == {"0", "1"}
    assert groups["0"] == [rows[0], rows[2]]
    assert groups["1"] == [rows[1]]


def test_group_by_empty_input_returns_empty_dict():
    assert group_by([], lambda r: r.gpu_index) == {}
