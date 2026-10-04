import pytest
from waste_detector.findings import FRAGMENTED, IDLE, OVER_PROVISIONED, OVERSIZED_BY_AVERAGE, RECURRING_PATTERN

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
    # The default rollup GPU is an A100; a T4 has far less memory
    # bandwidth, so the action must warn that requests get slower.
    assert "longer" in estimate.recommended_action
    assert "GB/s" in estimate.methodology
    # A T4 (16 GB) has far less memory than an A100 80GB, and fit isn't checked.
    assert estimate.recommended_action.endswith("; memory fit not checked)")
    assert "16 GB vs 80 GB" in estimate.methodology


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


def test_fragmented_framed_as_unverified_candidate_not_a_directive():
    # The detector can't prove consolidation is possible (memory fit,
    # combined compute, cluster GPU-sharing support are all unchecked), so
    # the customer-facing action must read as "review", not "consolidate".
    finding = _finding(FRAGMENTED, metric_value=2.0)
    estimate = estimate_for_finding(finding, [_rollup(avg_utilization_pct=20.0)], _config(), {})
    assert estimate.recommended_action.startswith("review whether")
    assert "time-slicing, MPS, or MIG" in estimate.recommended_action
    assert "upper-bound" in estimate.methodology


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


def test_multi_gpu_oversized_priced_as_visibility_upper_bound():
    from waste_detector.findings import MULTI_GPU_OVERSIZED
    from savings_estimator.estimate import BASIS_VISIBILITY_UPPER_BOUND

    finding = _finding(MULTI_GPU_OVERSIZED, metric_value=0.625)
    estimate = estimate_for_finding(finding, [_rollup(avg_utilization_pct=20.0)], _config(), {})
    assert estimate.priceable
    assert estimate.basis == BASIS_VISIBILITY_UPPER_BOUND
    # 300.00/hr * 0.625 releasable * 0.5 capture * 730h
    assert estimate.amount_inr == pytest.approx(300.00 * 0.625 * 0.5 * 730.0)
    assert estimate.recommended_action.startswith("review whether")
    assert "not included in the headline total" in estimate.methodology


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.2, 1.5, float("nan")])
def test_multi_gpu_oversized_rejects_invalid_fraction(bad):
    from waste_detector.findings import MULTI_GPU_OVERSIZED

    estimate = estimate_for_finding(_finding(MULTI_GPU_OVERSIZED, metric_value=bad), [_rollup()], _config(), {})
    assert not estimate.priceable


@pytest.mark.parametrize("category", ["underutilized", "unattributed_gpu_time"])
def test_no_recommendation_tier_priced_as_observed_unused_capacity(category):
    from savings_estimator.estimate import BASIS_DETECTED_NO_RECOMMENDATION

    finding = _finding(category, metric_value=0.5, window_start=0.0, window_end=3 * 3600.0)
    estimate = estimate_for_finding(finding, [_rollup(avg_utilization_pct=20.0)], _config(), {})
    assert estimate.priceable
    assert estimate.basis == BASIS_DETECTED_NO_RECOMMENDATION
    # 300.00/hr * 0.5 below target * 3h observed -- not projected to a month
    assert estimate.amount_inr == pytest.approx(300.00 * 0.5 * 3.0)
    assert estimate.recommended_action.startswith("none yet")


@pytest.mark.parametrize("bad", [0.0, 1.5, -0.1, float("nan")])
def test_no_recommendation_tier_rejects_invalid_fraction(bad):
    estimate = estimate_for_finding(_finding("underutilized", metric_value=bad), [_rollup()], _config(), {})
    assert not estimate.priceable


def test_oversized_by_average_sized_on_busiest_hour_with_stricter_target():
    # A100 80GB whose busiest hour averaged 20%: at the default 50% target
    # it needs ~125 TFLOPS and ~816 GB/s -> V100 16GB (125 TFLOPS, 900 GB/s).
    finding = _finding(OVERSIZED_BY_AVERAGE, metric_value=20.0)
    estimate = estimate_for_finding(finding, [_rollup(max_utilization_pct=80.0)], _config(), {})
    assert estimate.priceable
    assert estimate.basis == BASIS_PROJECTED_MONTHLY
    assert estimate.recommended_action.startswith("right-size to NVIDIA V100 16GB (")
    assert "longer" in estimate.recommended_action
    assert estimate.amount_inr == pytest.approx((300.00 - 175.00) * 730.0)
    assert "busiest-hour average utilization" in estimate.methodology
    assert "50% ceiling" in estimate.methodology


def test_oversized_by_average_target_is_configurable_and_separate_from_sla():
    finding = _finding(OVERSIZED_BY_AVERAGE, metric_value=20.0)
    looser = estimate_for_finding(finding, [_rollup()], _config(avg_load_target_utilization_pct=70.0), {})
    assert looser.recommended_action.startswith("right-size to NVIDIA A10 (")
    # The peak-based category keeps using the SLA target, unaffected.
    peak = estimate_for_finding(_finding(OVER_PROVISIONED, metric_value=20.0), [_rollup()],
                                _config(avg_load_target_utilization_pct=10.0), {})
    assert peak.recommended_action.startswith("right-size to NVIDIA A10 (")


def test_oversized_by_average_mini_test_workload_gets_a_bandwidth_safe_target():
    # The measured RTX 3090 LLM server (busiest hour ~21.4%): TFLOPS-only
    # sizing would have said T4; the T4 run showed 2.3x latency. At the
    # 50% target it needs ~401 GB/s -> A10. The A10 costs more than a
    # 3090 at the illustrative rates, so the projected saving floors at 0.
    finding = _finding(OVERSIZED_BY_AVERAGE, metric_value=21.4)
    rollup = _rollup(gpu_model="NVIDIA GeForce RTX 3090", fp16_tflops=71.0)
    estimate = estimate_for_finding(finding, [rollup], _config(), {})
    assert estimate.recommended_action.startswith("right-size to NVIDIA A10 (")
    assert estimate.amount_inr == 0.0


def test_over_provisioned_uses_measured_peak_memory_to_pick_a_gpu_that_holds_it():
    # A100 80GB at a 10% peak would go to a T4 -- but this workload peaked
    # at 20 GiB of memory, which a T4 can't hold. Every row carries a peak.
    rows = [_rollup(max_memory_used_mb=used, memory_total_mb=81920.0) for used in (12000.0, 20480.0)]
    estimate = estimate_for_finding(_finding(OVER_PROVISIONED, metric_value=10.0), rows, _config(), {})
    assert estimate.recommended_action.startswith("right-size to NVIDIA L4 (")
    assert "memory fit not checked" not in estimate.recommended_action
    assert "22.0 GiB of memory (peak 20.0 GiB used + 10%)" in estimate.methodology
    assert estimate.amount_inr == pytest.approx((300.00 - 70.00) * 730.0)


def test_preallocated_memory_keeps_the_caution():
    rows = [_rollup(max_memory_used_mb=73728.0, memory_total_mb=81920.0)]  # 90%, vLLM default
    estimate = estimate_for_finding(_finding(OVER_PROVISIONED, metric_value=10.0), rows, _config(), {})
    assert estimate.recommended_action.endswith("; memory fit not checked)")
    assert "pre-allocation" in estimate.methodology


def test_window_with_pre_upgrade_rows_is_not_trusted_for_memory():
    # One row predates the memory columns: its peak is unknown and could be
    # larger, so memory isn't used to size and the caution stays.
    rows = [_rollup(max_memory_used_mb=4096.0, memory_total_mb=81920.0), _rollup()]
    estimate = estimate_for_finding(_finding(OVER_PROVISIONED, metric_value=10.0), rows, _config(), {})
    assert estimate.recommended_action.startswith("right-size to NVIDIA T4 (")
    assert estimate.recommended_action.endswith("; memory fit not checked)")
