import pytest
from waste_detector.findings import FRAGMENTED, IDLE, OVER_PROVISIONED, RECURRING_PATTERN

from savings_estimator.config import Config
from savings_estimator.estimate import BASIS_OBSERVED_WINDOW, BASIS_PROJECTED_MONTHLY
from savings_estimator.estimator import estimate_for_finding
from savings_estimator.findings_reader import FindingRow
from savings_estimator.rollup_reader import RollupRow


def _config(**overrides) -> Config:
    defaults = dict(
        findings_sqlite_path=":memory:",
        normalized_sqlite_path=":memory:",
        savings_sqlite_path=":memory:",
        poll_interval_seconds=300,
        min_finding_confidence=0.7,
        sla_target_utilization_pct=70.0,
        hours_per_month=730.0,
        fragmentation_capture_fraction=0.5,
        gpu_hourly_rates_json=None,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _finding(category, **overrides) -> FindingRow:
    defaults = dict(
        id=1,
        category=category,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        window_start=0.0,
        window_end=4 * 3600.0,
        confidence=0.9,
        metric_value=4.0,
        detail="synthetic",
        detected_at=1000.0,
    )
    defaults.update(overrides)
    return FindingRow(**defaults)


def _rollup(gpu_model="NVIDIA A100-SXM4-80GB", avg_utilization_pct=20.0, **overrides) -> RollupRow:
    defaults = dict(
        id=1,
        granularity="hourly",
        bucket_start=0.0,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        avg_utilization_pct=avg_utilization_pct,
        max_utilization_pct=avg_utilization_pct + 5.0,
        avg_effective_tflops=60.0,
        gpu_model=gpu_model,
        fp16_tflops=312.0,
        coverage_ratio=1.0,
    )
    defaults.update(overrides)
    return RollupRow(**defaults)


def test_idle_priced_as_observed_window_not_projected():
    finding = _finding(IDLE, window_start=0.0, window_end=4 * 3600.0)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert estimate.priceable
    assert estimate.basis == BASIS_OBSERVED_WINDOW
    # 4 hours idle at the A100 default illustrative rate (₹300.00/hr).
    assert estimate.amount_inr == 4 * 300.00


def test_over_provisioned_recommends_smaller_sku_and_monthly_savings():
    finding = _finding(OVER_PROVISIONED, metric_value=10.0)  # 10% peak
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert estimate.priceable
    assert estimate.basis == BASIS_PROJECTED_MONTHLY
    assert estimate.amount_inr > 0
    assert "T4" in estimate.recommended_action


def test_over_provisioned_high_peak_may_yield_zero_savings():
    # Peak close to the ceiling itself -- recommended SKU may end up being
    # a similarly large one, or none smaller; either way savings floor at 0.
    finding = _finding(OVER_PROVISIONED, metric_value=68.0)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(sla_target_utilization_pct=70.0), {})
    assert estimate.amount_inr >= 0.0


def test_idle_with_inverted_window_is_unpriceable_not_negative():
    # Regression: a corrupted or clock-skewed upstream finding with
    # window_end before window_start must not silently produce a negative
    # rupee "savings" figure shown to a customer.
    finding = _finding(IDLE, window_start=3600.0, window_end=0.0)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert not estimate.priceable
    assert estimate.amount_inr is None


def test_recurring_pattern_out_of_range_fraction_is_unpriceable():
    # Regression: metric_value here is a fraction in [0, 1] (share of
    # observed days quiet at this hour). A corrupted upstream value above 1
    # must not silently inflate the monthly projection without limit.
    finding = _finding(RECURRING_PATTERN, metric_value=1.5)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert not estimate.priceable
    assert estimate.amount_inr is None


def test_recurring_pattern_negative_fraction_is_unpriceable():
    finding = _finding(RECURRING_PATTERN, metric_value=-0.1)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert not estimate.priceable


def test_over_provisioned_mig_slice_is_unpriceable_not_mispriced():
    # Regression: capability.fp16_tflops here is the *physical* GPU's full
    # capacity (312 TFLOPS for an A100), but finding.metric_value (peak
    # utilization) for a MIG slice is relative to that slice, not the whole
    # GPU. Sizing a recommendation from full-GPU TFLOPS against
    # slice-relative utilization mixed two different bases and could
    # recommend a SKU actually bigger than the slice already is (e.g. "NVIDIA
    # A10" for a workload confined to a small MIG slice). This must come back
    # unpriceable instead of a misleading number.
    finding = _finding(OVER_PROVISIONED, gpu_instance_id="1", metric_value=15.0)
    rows = [_rollup(gpu_instance_id="1")]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert not estimate.priceable
    assert estimate.amount_inr is None
    assert "MIG" in estimate.methodology


def test_fragmented_priced_with_capture_discount():
    finding = _finding(FRAGMENTED, metric_value=2.0)
    rows = [_rollup(avg_utilization_pct=20.0)]
    config = _config(fragmentation_capture_fraction=0.5)
    estimate = estimate_for_finding(finding, rows, config, {})
    assert estimate.priceable
    assert estimate.basis == BASIS_PROJECTED_MONTHLY
    # wasted_fraction = (1 - 0.20) * 0.5 = 0.40; monthly = 300.00 * 0.40 * 730
    assert estimate.amount_inr == 300.00 * 0.40 * 730.0


def test_fragmented_weights_avg_utilization_by_coverage_ratio():
    # Regression: a low-coverage bucket (mostly missing data, reading near
    # zero) must not count the same as a full-coverage one in the average
    # -- that would understate a workload's real utilization and overstate
    # its fragmentation waste. One reliable, busy hour and one sparse,
    # near-empty hour should land close to the reliable reading, not
    # halfway between them.
    finding = _finding(FRAGMENTED, metric_value=2.0)
    rows = [
        _rollup(avg_utilization_pct=90.0, coverage_ratio=1.0),
        _rollup(avg_utilization_pct=0.0, coverage_ratio=0.05),
    ]
    config = _config(fragmentation_capture_fraction=0.5)
    estimate = estimate_for_finding(finding, rows, config, {})

    # weighted avg = (90*1.0 + 0*0.05) / 1.05 =~ 85.7%
    weighted_avg = (90.0 * 1.0 + 0.0 * 0.05) / 1.05
    unweighted_avg = (90.0 + 0.0) / 2  # what the old, buggy average would give: 45%

    wasted_fraction = max(0.0, 1 - weighted_avg / 100.0) * 0.5
    assert estimate.amount_inr == pytest.approx(300.00 * wasted_fraction * 730.0)

    wrong_wasted_fraction = max(0.0, 1 - unweighted_avg / 100.0) * 0.5
    assert estimate.amount_inr != pytest.approx(300.00 * wrong_wasted_fraction * 730.0)


def test_recurring_pattern_priced_from_consistent_fraction():
    finding = _finding(RECURRING_PATTERN, metric_value=0.9)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert estimate.priceable
    assert estimate.basis == BASIS_PROJECTED_MONTHLY
    # 0.9 * 30 days * ₹300.00/hr
    assert estimate.amount_inr == 0.9 * 30.0 * 300.00


def test_unknown_gpu_model_is_unpriceable():
    finding = _finding(IDLE)
    rows = [_rollup(gpu_model="Some Future GPU")]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert not estimate.priceable
    assert estimate.amount_inr is None
    assert estimate.basis is None


def test_no_rollup_data_is_unpriceable():
    finding = _finding(IDLE)
    estimate = estimate_for_finding(finding, [], _config(), {})
    assert not estimate.priceable


def test_customer_rate_override_changes_amount():
    finding = _finding(IDLE, window_start=0.0, window_end=3600.0)
    rows = [_rollup()]
    estimate = estimate_for_finding(finding, rows, _config(), {"NVIDIA A100 80GB": 120.00})
    assert estimate.amount_inr == 120.00


def test_estimate_preserves_finding_identity():
    finding = _finding(IDLE, id=42, workload="my-svc", namespace="prod")
    rows = [_rollup(workload="my-svc", namespace="prod")]
    estimate = estimate_for_finding(finding, rows, _config(), {})
    assert estimate.finding_id == 42
    assert estimate.workload == "my-svc"
    assert estimate.namespace == "prod"
