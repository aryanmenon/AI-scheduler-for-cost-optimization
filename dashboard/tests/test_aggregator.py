from dashboard.aggregator import BASIS_OBSERVED_WINDOW, BASIS_PROJECTED_MONTHLY, aggregate
from dashboard.report_reader import EstimateRow


def _row(
    id=1, finding_id=1, category="idle", amount_usd=10.0, priceable=True,
    basis=BASIS_OBSERVED_WINDOW, confidence=0.9, workload="bert-large", **overrides
) -> EstimateRow:
    defaults = dict(
        id=id, finding_id=finding_id, category=category, node="gpu-node-1", gpu_index="0",
        gpu_instance_id=None, namespace="inference", workload=workload,
        window_start=0.0, window_end=3600.0, confidence=confidence, priceable=priceable,
        basis=basis if priceable else None, amount_usd=amount_usd if priceable else None,
        recommended_action="terminate", methodology="test", estimated_at=1000.0,
    )
    defaults.update(overrides)
    return EstimateRow(**defaults)


def test_observed_and_projected_totals_never_combined():
    rows = [
        _row(id=1, category="idle", basis=BASIS_OBSERVED_WINDOW, amount_usd=10.0),
        _row(id=2, category="over_provisioned", basis=BASIS_PROJECTED_MONTHLY, amount_usd=100.0),
    ]
    summary = aggregate(rows, top_n=10)
    assert summary.observed_window_total_usd == 10.0
    assert summary.projected_monthly_total_usd == 100.0


def test_unpriceable_findings_excluded_from_totals_but_counted():
    rows = [
        _row(id=1, amount_usd=10.0, priceable=True),
        _row(id=2, priceable=False),
    ]
    summary = aggregate(rows, top_n=10)
    assert summary.priceable_count == 1
    assert summary.unpriceable_count == 1
    assert summary.observed_window_total_usd == 10.0
    assert len(summary.unpriceable_samples) == 1


def test_by_category_breakdown_sorted_by_total_desc():
    rows = [
        _row(id=1, category="idle", amount_usd=5.0),
        _row(id=2, category="fragmented", basis=BASIS_PROJECTED_MONTHLY, amount_usd=50.0),
        _row(id=3, category="idle", amount_usd=5.0),
    ]
    summary = aggregate(rows, top_n=10)
    assert [c.category for c in summary.by_category] == ["fragmented", "idle"]
    idle_summary = next(c for c in summary.by_category if c.category == "idle")
    assert idle_summary.count == 2
    assert idle_summary.total_usd == 10.0


def test_top_findings_limited_and_sorted_by_amount():
    rows = [_row(id=i, amount_usd=float(i)) for i in range(1, 6)]
    summary = aggregate(rows, top_n=3)
    assert len(summary.top_findings) == 3
    assert [r.amount_usd for r in summary.top_findings] == [5.0, 4.0, 3.0]


def test_unpriceable_not_included_in_top_findings():
    rows = [_row(id=1, amount_usd=10.0), _row(id=2, priceable=False)]
    summary = aggregate(rows, top_n=10)
    assert all(r.priceable for r in summary.top_findings)


def test_empty_input_produces_zeroed_summary():
    summary = aggregate([], top_n=10)
    assert summary.total_estimates == 0
    assert summary.projected_monthly_total_usd == 0.0
    assert summary.observed_window_total_usd == 0.0
    assert summary.by_category == []
    assert summary.top_findings == []
