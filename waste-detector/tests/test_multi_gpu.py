import pytest

from waste_detector.findings import MULTI_GPU_OVERSIZED
from waste_detector.multi_gpu import detect_multi_gpu_oversized
from test_fragmentation import _config, _row


def _job(hours, gpus, util, workload="llm-train", node="gpu-node-1", start=0):
    return [
        _row((start + h) * 3600.0, str(g), workload, avg_utilization_pct=util, node=node)
        for h in range(hours) for g in range(gpus)
    ]


def test_flags_every_gpu_of_an_oversized_multi_gpu_job():
    # 8 GPUs at 20% average = 160% of one GPU's busy time -> needs
    # ceil(160/70) = 3 GPUs, so 5 of 8 could be released.
    findings = detect_multi_gpu_oversized(_job(4, 8, 20.0), _config())
    assert len(findings) == 8
    assert {f.category for f in findings} == {MULTI_GPU_OVERSIZED}
    assert all(f.metric_value == pytest.approx(5 / 8) for f in findings)
    assert all("at least 5 GPU(s)" in f.detail for f in findings)


def test_single_gpu_workloads_never_flagged():
    findings = detect_multi_gpu_oversized(_job(6, 1, 5.0), _config())
    assert findings == []


def test_well_utilized_multi_gpu_job_not_flagged():
    # 4 GPUs at 60% = 240% -> needs ceil(240/70) = 4: nothing to release.
    findings = detect_multi_gpu_oversized(_job(6, 4, 60.0), _config())
    assert findings == []


def test_streak_shorter_than_minimum_not_flagged():
    findings = detect_multi_gpu_oversized(_job(3, 8, 20.0), _config())
    assert findings == []


def test_streak_broken_by_a_busy_hour_restarts():
    rows = _job(3, 4, 10.0) + _job(1, 4, 90.0, start=3) + _job(3, 4, 10.0, start=4)
    assert detect_multi_gpu_oversized(rows, _config()) == []


def test_releasable_fraction_is_smallest_across_streak():
    # Hours 0-1: 4 GPUs at 10% (40% -> needs 1, releases 3/4).
    # Hours 2-3: 4 GPUs at 40% (160% -> needs 3, releases 1/4).
    rows = _job(2, 4, 10.0) + _job(2, 4, 40.0, start=2)
    findings = detect_multi_gpu_oversized(rows, _config())
    assert len(findings) == 4
    assert all(f.metric_value == pytest.approx(1 / 4) for f in findings)


def test_job_spanning_nodes_counted_as_one_job():
    rows = _job(4, 2, 10.0, node="gpu-node-1") + _job(4, 2, 10.0, node="gpu-node-2")
    findings = detect_multi_gpu_oversized(rows, _config())
    # 4 GPUs at 10% = 40% -> needs 1, so 3/4 releasable, reported on all 4 GPUs.
    assert len(findings) == 4
    assert {f.node for f in findings} == {"gpu-node-1", "gpu-node-2"}
    assert all(f.metric_value == pytest.approx(3 / 4) for f in findings)


def test_target_utilization_is_configurable():
    # 4 GPUs at 30% = 120%: at a 70% ceiling needs 2 (releases 2); at a
    # 40% ceiling needs 3 (releases 1).
    rows = _job(4, 4, 30.0)
    default = detect_multi_gpu_oversized(rows, _config())
    strict = detect_multi_gpu_oversized(rows, _config(multi_gpu_target_utilization_pct=40.0))
    assert default[0].metric_value == pytest.approx(2 / 4)
    assert strict[0].metric_value == pytest.approx(1 / 4)


def test_low_coverage_hours_excluded():
    rows = [
        _row(h * 3600.0, str(g), "llm-train", avg_utilization_pct=10.0, coverage_ratio=0.3)
        for h in range(4) for g in range(4)
    ]
    assert detect_multi_gpu_oversized(rows, _config()) == []


def test_detail_states_it_is_an_unverified_upper_bound():
    findings = detect_multi_gpu_oversized(_job(4, 8, 20.0), _config())
    detail = findings[0].detail
    assert "Upper bound for review" in detail
    assert "memory fit not checked" in detail
    assert "busy time" in detail
