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
    # And it should be the *smallest* such SKU, not an oversized one.
    from ingestion_normalization.capability import all_known_capabilities
    smaller_fits = [
        c for c in all_known_capabilities()
        if c.fp16_tflops is not None and rec.required_fp16_tflops <= c.fp16_tflops < rec.recommended.fp16_tflops
    ]
    assert smaller_fits == []
