import pytest

from waste_detector.detector import run_all_detectors
from waste_detector.findings import (
    IDLE,
    RECURRING_PATTERN,
    UNATTRIBUTED_GPU_TIME,
    UNDERUTILIZED,
    WasteFinding,
)
from waste_detector.unrecommended import covered_units, detect_unrecommended_waste
from test_fragmentation import _config, _row


def _finding(category, start_h, end_h, gpu_index="0", workload="model-a"):
    return WasteFinding(
        category=category, node="gpu-node-1", gpu_index=gpu_index, gpu_instance_id=None,
        namespace="inference", workload=workload, window_start=start_h * 3600.0,
        window_end=end_h * 3600.0, confidence=1.0, metric_value=1.0, detail="x",
    )


def test_below_target_hours_reported_with_shortfall_as_metric():
    rows = [_row(h * 3600.0, "0", "model-a", avg_utilization_pct=20.0) for h in range(3)]
    findings = detect_unrecommended_waste(rows, [], _config())
    assert len(findings) == 1
    f = findings[0]
    assert f.category == UNDERUTILIZED
    assert (f.window_start, f.window_end) == (0.0, 3 * 3600.0)
    # 70% target - 20% busy = 50% of the GPU unused below target.
    assert f.metric_value == pytest.approx(0.5)
    assert "no reliable recommendation" in f.detail


def test_hours_at_or_above_target_not_reported():
    rows = [_row(h * 3600.0, "0", "model-a", avg_utilization_pct=u) for h, u in enumerate([70.0, 95.0])]
    assert detect_unrecommended_waste(rows, [], _config()) == []


def test_hours_already_covered_by_an_actionable_finding_are_skipped():
    rows = [_row(h * 3600.0, "0", "model-a", avg_utilization_pct=1.0) for h in range(6)]
    idle = _finding(IDLE, 0, 4)
    findings = detect_unrecommended_waste(rows, [idle], _config())
    # Hours 0-3 belong to the idle finding; only hours 4-5 are left over.
    assert [(f.window_start, f.window_end) for f in findings] == [(4 * 3600.0, 6 * 3600.0)]


def test_recurring_pattern_covers_only_its_own_hour_of_day():
    pattern = _finding(RECURRING_PATTERN, 2, 2 + 24 * 2 + 1)  # 02:00 on days 0, 1 and 2
    covered = covered_units([pattern])
    hours = sorted(int(u[-1] // 3600) for u in covered)
    assert hours == [2, 26, 50]


def test_unattributed_gpu_time_gets_its_own_category():
    rows = [
        _row(h * 3600.0, "0", None, avg_utilization_pct=0.0, namespace="unattributed")
        for h in range(2)
    ]
    findings = detect_unrecommended_waste(rows, [], _config())
    assert len(findings) == 1
    assert findings[0].category == UNATTRIBUTED_GPU_TIME
    assert findings[0].metric_value == pytest.approx(0.7)
    assert "not tied to any Kubernetes pod" in findings[0].detail


def test_low_coverage_and_missing_utilization_hours_skipped():
    missing = _row(3600.0, "0", "model-a", avg_utilization_pct=10.0)
    missing.avg_utilization_pct = None
    rows = [
        _row(0.0, "0", "model-a", avg_utilization_pct=10.0, coverage_ratio=0.3),
        missing,
    ]
    assert detect_unrecommended_waste(rows, [], _config()) == []


def test_gaps_split_runs():
    rows = [_row(h * 3600.0, "0", "model-a", avg_utilization_pct=10.0) for h in (0, 1, 5)]
    findings = detect_unrecommended_waste(rows, [], _config())
    assert sorted((f.window_start, f.window_end) for f in findings) == [
        (0.0, 2 * 3600.0), (5 * 3600.0, 6 * 3600.0),
    ]


def test_target_and_min_run_are_configurable():
    rows = [_row(h * 3600.0, "0", "model-a", avg_utilization_pct=40.0) for h in range(2)]
    assert detect_unrecommended_waste(rows, [], _config(underutilized_target_pct=30.0)) == []
    assert detect_unrecommended_waste(rows, [], _config(underutilized_min_run_hours=3)) == []


def test_waste_no_longer_disappears_when_fragmentation_excludes_a_multi_gpu_job():
    # The case that motivated this tier: a small model next to a multi-GPU
    # job. Fragmentation rightly excludes both, and the multi-GPU job is too
    # busy for the multi-GPU signal, so before this tier the small model's
    # underuse was reported nowhere.
    rows = []
    for h in range(6):
        bs = h * 3600.0
        for gpu in ("0", "1", "2", "3"):
            rows.append(_row(bs, gpu, "llm-train", avg_utilization_pct=65.0))
        rows.append(_row(bs, "4", "small-model", avg_utilization_pct=10.0))
    findings = run_all_detectors(rows, _config())
    small = [f for f in findings if f.workload == "small-model"]
    assert {f.category for f in small} == {UNDERUTILIZED}
    assert small[0].metric_value == pytest.approx(0.6)
