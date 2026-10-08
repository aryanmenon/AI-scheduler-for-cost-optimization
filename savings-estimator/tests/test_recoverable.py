import pytest

from savings_estimator.recoverable import compute_recoverable_ceiling
from savings_estimator.rollup_reader import RollupRow


def _row(bucket_start=0.0, util=20.0, model="NVIDIA A100-SXM4-80GB", coverage=1.0,
         gpu_index="0", instance=None, namespace="inference", workload="svc"):
    return RollupRow(
        id=1, granularity="hourly", bucket_start=bucket_start, node="n", gpu_index=gpu_index,
        gpu_instance_id=instance, namespace=namespace, workload=workload,
        avg_utilization_pct=util, max_utilization_pct=util, avg_effective_tflops=None,
        gpu_model=model, fp16_tflops=None, coverage_ratio=coverage,
    )


def test_empty_input_has_no_ceiling():
    assert compute_recoverable_ceiling([], 70.0, 730.0, {}) is None


def test_ceiling_is_spend_below_the_target():
    # A100 Rs300/hr: one GPU-hour at 7% (90% of it below a 70% target) and
    # one at 70% (none below) -> Rs270 recoverable of Rs600 spent.
    c = compute_recoverable_ceiling([_row(util=7.0), _row(util=70.0, gpu_index="1")], 70.0, 730.0, {})
    assert c.observed_gpu_hours == 2
    assert c.observed_spend_inr == 600.0
    assert c.recoverable_inr == pytest.approx(270.0)
    assert c.fraction == pytest.approx(0.45)


def test_busier_than_target_never_counts_negative():
    c = compute_recoverable_ceiling([_row(util=95.0)], 70.0, 730.0, {})
    assert c.recoverable_inr == 0.0 and c.fraction == 0.0


def test_customer_rates_are_used():
    c = compute_recoverable_ceiling([_row(util=0.0)], 70.0, 730.0, {"NVIDIA A100 80GB": 250.0})
    assert c.observed_spend_inr == 250.0 and c.recoverable_inr == 250.0


def test_monthly_figures_scale_the_observed_run_rate():
    # Two consecutive hours of one idle A100: Rs300/hr run rate -> Rs219,000/mo.
    c = compute_recoverable_ceiling([_row(0.0, util=0.0), _row(3600.0, util=0.0)], 70.0, 730.0, {})
    assert c.window_end - c.window_start == 7200
    assert c.monthly_spend_inr == pytest.approx(300.0 * 730)
    assert c.monthly_recoverable_inr == pytest.approx(300.0 * 730)


def test_gpu_hours_weighted_by_coverage():
    # A GPU whose pod changed mid-hour: two half-covered rows count as one
    # GPU-hour in total, not two.
    rows = [_row(util=0.0, coverage=0.5, workload=None, namespace="unattributed"),
            _row(util=70.0, coverage=0.5, workload="svc")]
    c = compute_recoverable_ceiling(rows, 70.0, 730.0, {})
    assert c.observed_gpu_hours == 1.0
    assert c.observed_spend_inr == 300.0
    assert c.recoverable_inr == pytest.approx(150.0)


def test_unknown_gpus_mig_slices_and_missing_utilization_are_excluded_not_guessed():
    rows = [
        _row(util=0.0),                                        # counted
        _row(util=0.0, model="NVIDIA H200", gpu_index="1"),    # no capability data
        _row(util=0.0, instance="1g.10gb", gpu_index="2"),     # MIG slice
        _row(util=None, gpu_index="3"),                        # no reading
    ]
    c = compute_recoverable_ceiling(rows, 70.0, 730.0, {})
    assert c.observed_gpu_hours == 1
    assert c.excluded_gpu_hours == 3
    assert c.observed_spend_inr == 300.0


def test_only_excluded_gpus_gives_zero_spend_and_zero_fraction():
    c = compute_recoverable_ceiling([_row(model="NVIDIA H200")], 70.0, 730.0, {})
    assert c.observed_spend_inr == 0.0 and c.fraction == 0.0 and c.excluded_gpu_hours == 1
