from waste_detector.config import Config
from waste_detector.findings import FRAGMENTED
from waste_detector.fragmentation import detect_fragmentation
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


def _row(bucket_start, gpu_index, workload, avg_utilization_pct=20.0, node="gpu-node-1", coverage_ratio=1.0, **overrides) -> RollupRow:
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


def _two_underutilized_gpus_over(hours: range) -> list[RollupRow]:
    rows = []
    for i in hours:
        bs = i * 3600.0
        rows.append(_row(bs, "0", "model-a", avg_utilization_pct=20.0))
        rows.append(_row(bs, "1", "model-b", avg_utilization_pct=15.0))
    return rows


def test_flags_two_underutilized_workloads_sharing_a_node():
    rows = _two_underutilized_gpus_over(range(4))
    findings = detect_fragmentation(rows, _config())
    assert len(findings) == 2  # one per GPU/workload
    assert all(f.category == FRAGMENTED for f in findings)
    workloads = {f.workload for f in findings}
    assert workloads == {"model-a", "model-b"}


def test_single_workload_across_multiple_gpus_not_flagged():
    # A distributed job legitimately spanning 2 GPUs -- same workload, not
    # fragmentation, even though each GPU looks underutilized alone.
    rows = []
    for i in range(4):
        bs = i * 3600.0
        rows.append(_row(bs, "0", "distributed-job", avg_utilization_pct=20.0))
        rows.append(_row(bs, "1", "distributed-job", avg_utilization_pct=20.0))
    findings = detect_fragmentation(rows, _config())
    assert findings == []


def test_below_minimum_underutilized_gpu_count_not_flagged():
    rows = [_row(i * 3600.0, "0", "model-a", avg_utilization_pct=20.0) for i in range(4)]
    findings = detect_fragmentation(rows, _config(fragmentation_min_underutilized_gpus=2))
    assert findings == []


def test_below_minimum_streak_length_not_flagged():
    rows = _two_underutilized_gpus_over(range(2))  # only 2 hours, need 4
    findings = detect_fragmentation(rows, _config())
    assert findings == []


def test_utilization_exactly_at_threshold_counts_as_underutilized():
    # Regression: this detector used strict "<" while every other detector
    # (idle.py, over_provisioning.py, patterns.py) is inclusive ("<=") --
    # a GPU sitting exactly at fragmentation_threshold_pct=50.0 must now
    # qualify too, consistent with the rest of the module.
    rows = []
    for i in range(4):
        bs = i * 3600.0
        rows.append(_row(bs, "0", "model-a", avg_utilization_pct=50.0))
        rows.append(_row(bs, "1", "model-b", avg_utilization_pct=50.0))
    findings = detect_fragmentation(rows, _config())
    assert len(findings) == 2


def test_well_utilized_gpus_not_flagged():
    rows = []
    for i in range(4):
        bs = i * 3600.0
        rows.append(_row(bs, "0", "model-a", avg_utilization_pct=80.0))
        rows.append(_row(bs, "1", "model-b", avg_utilization_pct=85.0))
    findings = detect_fragmentation(rows, _config())
    assert findings == []


def test_different_nodes_evaluated_independently():
    rows = _two_underutilized_gpus_over(range(4))
    # A single underutilized GPU on a different node shouldn't combine
    # with node-1's pair to falsely qualify.
    rows.append(_row(0.0, "0", "model-c", avg_utilization_pct=10.0, node="gpu-node-2"))
    findings = detect_fragmentation(rows, _config())
    nodes = {f.node for f in findings}
    assert nodes == {"gpu-node-1"}


def test_metric_value_reflects_average_underutilized_gpu_count():
    rows = _two_underutilized_gpus_over(range(4))
    findings = detect_fragmentation(rows, _config())
    assert all(f.metric_value == 2.0 for f in findings)


def test_multi_gpu_workload_excluded_even_alongside_another_workload():
    # Regression: the old check only required 2+ distinct workloads among
    # the underutilized GPUs, so a 4-GPU distributed job next to one small
    # model qualified and every one of the job's GPUs got a "consolidate"
    # finding -- advice that can't be followed, since NCCL won't run two
    # ranks on one GPU. Without the job, a lone small model doesn't qualify.
    rows = []
    for i in range(6):
        bs = i * 3600.0
        for gpu in ("0", "1", "2", "3"):
            rows.append(_row(bs, gpu, "llm-train", avg_utilization_pct=20.0))
        rows.append(_row(bs, "4", "small-model", avg_utilization_pct=10.0))
    findings = detect_fragmentation(rows, _config())
    assert findings == []


def test_multi_gpu_workload_excluded_but_other_single_gpu_workloads_still_flagged():
    rows = _two_underutilized_gpus_over(range(4))
    for i in range(4):
        bs = i * 3600.0
        rows.append(_row(bs, "2", "llm-train", avg_utilization_pct=20.0))
        rows.append(_row(bs, "3", "llm-train", avg_utilization_pct=20.0))
    findings = detect_fragmentation(rows, _config())
    assert {f.workload for f in findings} == {"model-a", "model-b"}


def test_multi_gpu_detection_counts_busy_gpus_and_other_nodes():
    # One busy GPU on this node plus one on another node still makes it a
    # multi-GPU job; only its underutilized GPU on this node is visible to
    # the per-node check, so the exclusion must look at all usable rows.
    rows = _two_underutilized_gpus_over(range(4))
    for i in range(4):
        bs = i * 3600.0
        rows.append(_row(bs, "2", "llm-train", avg_utilization_pct=20.0))
        rows.append(_row(bs, "0", "llm-train", avg_utilization_pct=95.0, node="gpu-node-2"))
    findings = detect_fragmentation(rows, _config())
    assert "llm-train" not in {f.workload for f in findings}
    assert {f.workload for f in findings} == {"model-a", "model-b"}


def test_detail_marks_finding_as_unverified_candidate():
    rows = _two_underutilized_gpus_over(range(4))
    findings = detect_fragmentation(rows, _config())
    for f in findings:
        assert "consolidation candidate" in f.detail
        assert "not checked" in f.detail
