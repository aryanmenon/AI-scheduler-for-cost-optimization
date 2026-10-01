from dashboard.aggregator import aggregate
from dashboard.render import render_report
from dashboard.report_reader import EstimateRow


def _row(id=1, category="idle", amount_inr=10.0, priceable=True, basis="observed_window",
         workload="bert-large", methodology="test methodology", **overrides) -> EstimateRow:
    defaults = dict(
        id=id, finding_id=id, category=category, node="gpu-node-1", gpu_index="0",
        gpu_instance_id=None, namespace="inference", workload=workload,
        window_start=0.0, window_end=3600.0, confidence=0.9, priceable=priceable,
        basis=basis if priceable else None, amount_inr=amount_inr if priceable else None,
        recommended_action="terminate this GPU", methodology=methodology, estimated_at=1000.0,
    )
    defaults.update(overrides)
    return EstimateRow(**defaults)


def test_renders_valid_html_document():
    summary = aggregate([_row()], top_n=10)
    html_out = render_report(summary)
    assert html_out.startswith("<!doctype html>")
    assert "</html>" in html_out


def test_includes_projected_and_observed_totals_separately():
    rows = [
        _row(id=1, category="idle", basis="observed_window", amount_inr=14.0),
        _row(id=2, category="over_provisioned", basis="projected_monthly", amount_inr=250.0),
    ]
    summary = aggregate(rows, top_n=10)
    html_out = render_report(summary)
    assert "₹14.00" in html_out
    assert "₹250.00" in html_out


def test_workload_and_namespace_appear_in_output():
    summary = aggregate([_row(workload="my-special-svc", namespace="prod-inference")], top_n=10)
    html_out = render_report(summary)
    assert "my-special-svc" in html_out
    assert "prod-inference" in html_out


def test_html_escapes_untrusted_workload_names():
    summary = aggregate([_row(workload="<script>alert(1)</script>")], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_html_escapes_untrusted_namespace():
    summary = aggregate([_row(namespace="<script>alert(2)</script>")], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(2)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_html_escapes_untrusted_node():
    summary = aggregate([_row(node="<script>alert(3)</script>")], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(3)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_html_escapes_untrusted_recommended_action():
    summary = aggregate([_row(recommended_action="<script>alert(4)</script>")], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(4)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_html_escapes_untrusted_methodology():
    summary = aggregate([_row(methodology="<script>alert(5)</script>")], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(5)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_html_escapes_untrusted_category():
    # category is never interpolated into an HTML attribute -- chip color
    # comes from a fixed category->hex lookup table, not the raw string --
    # so attribute breakout is structurally impossible regardless of
    # escaping. Its only appearance as visible text (the title-cased
    # fallback label for an unrecognized category) still goes through
    # html.escape; .lower() sidesteps the incidental case change .title()
    # applies to the injected text itself.
    summary = aggregate([_row(category='idle"><script>alert(6)</script>')], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(6)</script>" not in html_out
    assert '"><script>' not in html_out
    assert "&lt;script&gt;" in html_out.lower()


def test_unpriceable_section_shown_only_when_present():
    priced_only = aggregate([_row(priceable=True)], top_n=10)
    assert "Not priced" not in render_report(priced_only)

    with_unpriceable = aggregate([_row(priceable=True), _row(id=2, priceable=False)], top_n=10)
    assert "Not priced" in render_report(with_unpriceable)


def test_empty_summary_renders_without_error():
    summary = aggregate([], top_n=10)
    html_out = render_report(summary)
    assert "No findings yet" in html_out
    assert "No priceable findings yet" in html_out


def test_mig_gpu_identity_shown():
    summary = aggregate([_row(gpu_instance_id="1")], top_n=10)
    html_out = render_report(summary)
    assert "MIG 1" in html_out


def test_unattributed_workload_shown_as_such():
    summary = aggregate([_row(workload=None)], top_n=10)
    html_out = render_report(summary)
    assert "unattributed" in html_out


def test_category_breakdown_bar_orders_segments_by_fixed_category_not_by_size():
    # Regression: aggregate() sorts by_category by total_inr descending, so
    # a naive render would put whichever category happens to be biggest
    # this cycle first -- meaning a category's position (and hue) would
    # shift report to report. The stacked bar must instead use a fixed
    # category order so color always means the same thing.
    rows = [
        _row(id=1, category="recurring_pattern", basis="projected_monthly", amount_inr=999.0),
        _row(id=2, category="idle", basis="observed_window", amount_inr=1.0),
    ]
    summary = aggregate(rows, top_n=10)
    html_out = render_report(summary)

    idle_pos = html_out.index('title="Idle GPUs')
    recurring_pos = html_out.index('title="Recurring Low-Usage Pattern')
    assert idle_pos < recurring_pos  # idle first despite being far smaller


def test_category_breakdown_bar_segment_sized_by_amount():
    rows = [
        _row(id=1, category="idle", basis="observed_window", amount_inr=100.0),
        _row(id=2, category="over_provisioned", basis="projected_monthly", amount_inr=400.0),
    ]
    summary = aggregate(rows, top_n=10)
    html_out = render_report(summary)
    assert "flex-grow:100.0" in html_out
    assert "flex-grow:400.0" in html_out


def test_category_breakdown_unrecognized_category_gets_fallback_color_and_trailing_position():
    rows = [
        _row(id=1, category="idle", basis="observed_window", amount_inr=1.0),
        _row(id=2, category="future_detector_category", basis="observed_window", amount_inr=1.0),
    ]
    summary = aggregate(rows, top_n=10)
    html_out = render_report(summary)
    assert "#676761" in html_out  # neutral fallback, not an arbitrary cycled hue
    idle_pos = html_out.index('title="Idle GPUs')
    unknown_pos = html_out.index("Future Detector Category")
    assert idle_pos < unknown_pos


def test_overlap_note_shown_only_when_a_gpu_has_multiple_projected_estimates():
    single = aggregate([_row(category="over_provisioned", basis="projected_monthly", amount_inr=100.0)], top_n=10)
    assert "counted once" not in render_report(single)

    overlapping = aggregate([
        _row(id=1, category="over_provisioned", basis="projected_monthly", amount_inr=100.0),
        _row(id=2, category="fragmented", basis="projected_monthly", amount_inr=60.0),
    ], top_n=10)
    html_out = render_report(overlapping)
    assert "counted once" in html_out
    assert "1 GPU appears in more than one recommendation" in html_out
