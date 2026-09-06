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
    # category also lands inside an unquoted-looking CSS class attribute
    # (badge-{category}), so this also guards against attribute breakout --
    # html.escape's default quote=True escapes the quote characters too.
    summary = aggregate([_row(category='idle"><script>alert(6)</script>')], top_n=10)
    html_out = render_report(summary)
    assert "<script>alert(6)</script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert '"><script>' not in html_out


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
