import pytest

from savings_estimator.ceiling import right_sized_capability


def test_over_provisioned_a100_recommends_smaller_sku():
    # A100 (312 TFLOPS) peaking at 10% -> demand ~31.2 TFLOPS; at a 70%
    # ceiling that needs ~44.6 TFLOPS -- well within a T4 (65) or A10 (125).
    rec = right_sized_capability(
        current_fp16_tflops=312.0, observed_peak_utilization_pct=10.0, sla_target_utilization_pct=70.0
    )
    assert rec.recommended is not None
    assert rec.recommended.fp16_tflops < 312.0
    assert rec.recommended.canonical_name == "NVIDIA T4"  # smallest SKU >= ~44.6 TFLOPS


def test_recommendation_respects_sla_headroom_not_100_percent():
    # Same peak demand, but a stricter (lower) SLA ceiling should require
    # a *larger* recommended GPU than a looser one -- more headroom needed.
    loose = right_sized_capability(312.0, 20.0, sla_target_utilization_pct=90.0)
    strict = right_sized_capability(312.0, 20.0, sla_target_utilization_pct=30.0)
    assert strict.required_fp16_tflops > loose.required_fp16_tflops


def test_high_peak_utilization_may_recommend_no_downsize():
    # Already running close to the ceiling -- the required capability is
    # close to (or above) current, so no smaller SKU should be recommended
    # as clearly better; here it still finds *a* SKU but it won't be tiny.
    rec = right_sized_capability(312.0, 65.0, sla_target_utilization_pct=70.0)
    assert rec.recommended is not None
    assert rec.required_fp16_tflops > 250.0


def test_no_known_sku_meets_extreme_requirement():
    rec = right_sized_capability(
        current_fp16_tflops=10000.0, observed_peak_utilization_pct=100.0, sla_target_utilization_pct=99.0
    )
    assert rec.recommended is None
    assert "no known SKU" in rec.detail


def test_zero_peak_utilization_has_no_sizing_basis():
    rec = right_sized_capability(312.0, 0.0, sla_target_utilization_pct=70.0)
    assert rec.recommended is None
    assert rec.required_fp16_tflops == 0.0


def test_recommendation_never_exceeds_required_headroom_by_picking_smallest_fit():
    rec = right_sized_capability(312.0, 5.0, sla_target_utilization_pct=70.0)
    assert rec.recommended.fp16_tflops >= rec.required_fp16_tflops
    # And it should be the *smallest* such *recommendable* SKU, not an
    # oversized one -- a smaller but non-recommendable (consumer/gaming)
    # SKU existing doesn't count as a missed smaller fit, see
    # capability.py's module docstring on why the two are separate flags.
    from ingestion_normalization.capability import all_known_capabilities
    smaller_fits = [
        c for c in all_known_capabilities()
        if c.fp16_tflops is not None
        and c.recommendable
        and rec.required_fp16_tflops <= c.fp16_tflops < rec.recommended.fp16_tflops
    ]
    assert smaller_fits == []


def test_never_recommends_a_consumer_gpu_even_when_cheapest_fit():
    # RTX 3060 (51 TFLOPS) is cheaper and numerically closer to a ~44.6
    # TFLOPS requirement than T4 (65 TFLOPS) -- this same scenario used to
    # recommend "NVIDIA GeForce RTX 3060" before capability.recommendable
    # existed. No real cluster racks a GeForce card as a node pool option,
    # so it must never be recommended regardless of TFLOPS fit.
    rec = right_sized_capability(
        current_fp16_tflops=312.0, observed_peak_utilization_pct=10.0, sla_target_utilization_pct=70.0
    )
    assert rec.recommended is not None
    assert rec.recommended.canonical_name == "NVIDIA T4"
    assert "RTX" not in rec.recommended.canonical_name
    assert "GeForce" not in rec.recommended.canonical_name


# --- memory bandwidth (testing/rightsizing-mini-test/, 2026-10-04) ---
# Measured: same LLM service and traffic on an RTX 3090 then a T4.
MEASURED_3090_MEAN_BUSY_PCT = 21.37
MEASURED_T4_MEAN_BUSY_PCT = 54.27


def _cap(name):
    from ingestion_normalization.capability import lookup_capability
    cap = lookup_capability(name)
    assert cap.known
    return cap


def test_measured_busy_shift_follows_memory_bandwidth_not_tflops():
    # Documents the evidence behind the bandwidth check: TFLOPS-only sizing
    # predicted the T4 would be ~1.09x busier; it was 2.54x busier, within
    # the bandwidth ratio (2.92x). Sizing on the max of the two ratios
    # never under-predicts what was measured.
    rtx3090, t4 = _cap("NVIDIA GeForce RTX 3090"), _cap("Tesla T4")
    measured = MEASURED_T4_MEAN_BUSY_PCT / MEASURED_3090_MEAN_BUSY_PCT
    tflops_x = rtx3090.fp16_tflops / t4.fp16_tflops
    bw_x = rtx3090.mem_bandwidth_gbps / t4.mem_bandwidth_gbps
    assert tflops_x < measured <= max(tflops_x, bw_x)


def test_does_not_downsize_into_slower_memory_the_mini_test_failed_on():
    # Regression: a 3090 peaking at 25% (under the 30% over-provisioned
    # bar) used to get "right-size to NVIDIA T4" from TFLOPS alone; the
    # T4 and L4 both lack the memory bandwidth, so the A10 is the smallest fit.
    rtx3090 = _cap("NVIDIA GeForce RTX 3090")
    tflops_only = right_sized_capability(rtx3090.fp16_tflops, 25.0, sla_target_utilization_pct=70.0)
    assert tflops_only.recommended.canonical_name == "NVIDIA T4"
    rec = right_sized_capability(
        rtx3090.fp16_tflops, 25.0, sla_target_utilization_pct=70.0,
        current_mem_bandwidth_gbps=rtx3090.mem_bandwidth_gbps,
    )
    assert rec.recommended.canonical_name == "NVIDIA A10"
    assert rec.recommended.mem_bandwidth_gbps >= rec.required_mem_bandwidth_gbps
    assert rec.required_mem_bandwidth_gbps == pytest.approx(936.0 * 0.25 / 0.70)


def test_bandwidth_can_push_recommendation_above_the_tflops_fit():
    # A100 80GB at 25%: TFLOPS alone fits an L4 (121), but ~728 GB/s is
    # needed -- L4 (300) and A10 (600) are too slow, V100 (900) fits.
    a100 = _cap("NVIDIA A100 80GB")
    rec = right_sized_capability(a100.fp16_tflops, 25.0, 70.0, current_mem_bandwidth_gbps=a100.mem_bandwidth_gbps)
    assert rec.recommended.canonical_name == "NVIDIA V100 16GB"


def test_recommendation_carries_expected_latency_factor():
    # A100 80GB at 10% -> T4 fits both resources, but the T4 has 6.4x less
    # memory bandwidth and 4.8x less compute: each request can be ~6.4x slower.
    a100 = _cap("NVIDIA A100 80GB")
    rec = right_sized_capability(a100.fp16_tflops, 10.0, 70.0, current_mem_bandwidth_gbps=a100.mem_bandwidth_gbps)
    assert rec.recommended.canonical_name == "NVIDIA T4"
    assert rec.expected_latency_factor == pytest.approx(2039.0 / 320.0)
    assert "6.4x longer" in rec.detail
    assert "interactive" in rec.detail


def test_target_at_least_as_fast_on_both_axes_reports_no_slowdown():
    from savings_estimator.ceiling import latency_note
    assert latency_note(1.0) == "no per-request slowdown expected"
    assert latency_note(None) == "no per-request slowdown expected"
    assert "1.6x longer" in latency_note(1.56)


def test_unknown_current_bandwidth_falls_back_to_tflops_and_says_so():
    rec = right_sized_capability(312.0, 10.0, 70.0, current_mem_bandwidth_gbps=None)
    assert rec.recommended.canonical_name == "NVIDIA T4"
    assert rec.required_mem_bandwidth_gbps == 0.0
    assert "memory bandwidth not checked" in rec.detail


def test_every_recommendation_fits_both_resources():
    for cap in _all_recommendable_and_consumer():
        for peak in (5.0, 10.0, 20.0, 29.0):
            rec = right_sized_capability(cap.fp16_tflops, peak, 70.0, current_mem_bandwidth_gbps=cap.mem_bandwidth_gbps)
            if rec.recommended is None:
                continue
            assert rec.recommended.fp16_tflops >= rec.required_fp16_tflops
            assert rec.recommended.mem_bandwidth_gbps >= rec.required_mem_bandwidth_gbps
            assert rec.recommended.recommendable


def _all_recommendable_and_consumer():
    from ingestion_normalization.capability import all_known_capabilities
    return [c for c in all_known_capabilities() if c.fp16_tflops and c.mem_bandwidth_gbps]


# --- memory capacity is not checked, so smaller-memory targets say so ---

def test_smaller_memory_target_carries_unchecked_fit_caution():
    a100 = _cap("NVIDIA A100 80GB")
    rec = right_sized_capability(a100.fp16_tflops, 10.0, 70.0, current_mem_bandwidth_gbps=a100.mem_bandwidth_gbps,
                                 current_mem_capacity_gb=a100.mem_capacity_gb)
    assert rec.recommended.canonical_name == "NVIDIA T4"
    assert rec.memory_fit_unchecked
    assert "memory fit not checked (no memory usage data for this workload) -- the target has 16 GB vs 80 GB now" in rec.detail


def test_same_or_more_memory_target_needs_no_caution():
    rtx3090 = _cap("NVIDIA GeForce RTX 3090")  # 24 GB -> A10 24 GB
    rec = right_sized_capability(rtx3090.fp16_tflops, 25.0, 70.0,
                                 current_mem_bandwidth_gbps=rtx3090.mem_bandwidth_gbps,
                                 current_mem_capacity_gb=rtx3090.mem_capacity_gb)
    assert rec.recommended.canonical_name == "NVIDIA A10"
    assert not rec.memory_fit_unchecked
    assert "memory fit" not in rec.detail


def test_unknown_current_memory_is_flagged_not_assumed():
    rec = right_sized_capability(312.0, 10.0, 70.0)
    assert rec.memory_fit_unchecked
    assert "memory fit not checked" in rec.detail



# --- memory capacity checked against peak memory used ---
A100_80_MIB = 81920.0  # what DCGM reports (used + free) for an A100 80GB


def _a100_rec(peak_mib, util=10.0, total_mib=A100_80_MIB):
    a100 = _cap("NVIDIA A100 80GB")
    return right_sized_capability(a100.fp16_tflops, util, 70.0,
                                  current_mem_bandwidth_gbps=a100.mem_bandwidth_gbps,
                                  current_mem_capacity_gb=a100.mem_capacity_gb,
                                  peak_memory_used_mib=peak_mib, current_memory_total_mib=total_mib)


def test_measured_peak_that_fits_removes_the_caution():
    rec = _a100_rec(peak_mib=10 * 1024)  # 10 GiB peak -> 11 GiB needed; a T4 has ~14.9 usable
    assert rec.recommended.canonical_name == "NVIDIA T4"
    assert not rec.memory_fit_unchecked
    assert "memory fit" not in rec.detail
    assert "11.0 GiB of memory (peak 10.0 GiB used + 10%)" in rec.detail


def test_measured_peak_too_big_skips_to_a_gpu_that_holds_it():
    # 20 GiB peak -> 22 GiB needed: a T4 can't hold it; L4 (24 GB) can, and
    # also meets the compute and bandwidth needs at a 10% peak.
    rec = _a100_rec(peak_mib=20 * 1024)
    assert rec.recommended.canonical_name == "NVIDIA L4"
    assert not rec.memory_fit_unchecked
    from savings_estimator.ceiling import _usable_mib
    assert _usable_mib(rec.recommended.mem_capacity_gb) >= rec.required_memory_mib


def test_peak_needing_more_than_any_smaller_gpu_keeps_a_big_one():
    rec = _a100_rec(peak_mib=50 * 1024)  # 55 GiB needed: only the 80 GB parts hold it
    assert rec.recommended.mem_capacity_gb >= 80.0


def test_preallocating_workload_keeps_the_caution_with_the_reason():
    # vLLM's default gpu_memory_utilization=0.9 shows as ~90% used.
    rec = _a100_rec(peak_mib=0.9 * A100_80_MIB)
    assert rec.recommended.canonical_name == "NVIDIA T4"  # memory not used to size
    assert rec.memory_fit_unchecked
    assert "holds 90% of GPU memory, typical of vLLM/TensorFlow pre-allocation" in rec.detail
    assert rec.required_memory_mib == 0.0


def test_mini_test_3090_run_was_measured_not_preallocated():
    # The RTX 3090 vLLM run used --gpu-memory-utilization 0.5: 12813 MiB of
    # 24576. Below the pre-allocation bar, so it is sized as measured --
    # 12.5 GiB x 1.1 fits the A10 (24 GB) the bandwidth check picks.
    rtx3090 = _cap("NVIDIA GeForce RTX 3090")
    rec = right_sized_capability(rtx3090.fp16_tflops, 25.0, 70.0,
                                 current_mem_bandwidth_gbps=rtx3090.mem_bandwidth_gbps,
                                 current_mem_capacity_gb=rtx3090.mem_capacity_gb,
                                 peak_memory_used_mib=12813.0, current_memory_total_mib=24576.0)
    assert rec.recommended.canonical_name == "NVIDIA A10"
    assert not rec.memory_fit_unchecked


def test_current_total_falls_back_to_spec_when_dcgm_total_missing():
    rec = _a100_rec(peak_mib=0.9 * A100_80_MIB, total_mib=None)
    assert rec.memory_fit_unchecked  # 72 GiB of ~74.4 usable is still pre-allocation


def test_every_recommendation_holds_the_measured_peak():
    for cap in _all_recommendable_and_consumer():
        if not cap.mem_capacity_gb:
            continue
        total = cap.mem_capacity_gb * 1024.0
        for frac in (0.1, 0.3, 0.6, 0.8):
            for peak in (5.0, 20.0, 29.0):
                rec = right_sized_capability(cap.fp16_tflops, peak, 70.0,
                                             current_mem_bandwidth_gbps=cap.mem_bandwidth_gbps,
                                             current_mem_capacity_gb=cap.mem_capacity_gb,
                                             peak_memory_used_mib=frac * total, current_memory_total_mib=total)
                if rec.recommended is None:
                    continue
                from savings_estimator.ceiling import _usable_mib
                assert _usable_mib(rec.recommended.mem_capacity_gb) >= frac * total * 1.10
                assert not rec.memory_fit_unchecked
