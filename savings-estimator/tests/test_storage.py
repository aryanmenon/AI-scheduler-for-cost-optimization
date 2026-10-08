import pytest

from savings_estimator.estimate import BASIS_OBSERVED_WINDOW, SavingsEstimate
from savings_estimator.storage import SavingsStorage


@pytest.fixture
def storage(tmp_path):
    s = SavingsStorage(str(tmp_path / "savings.db"))
    yield s
    s.close()


def _estimate(finding_id=1, amount_inr=14.0, priceable=True, **overrides) -> SavingsEstimate:
    defaults = dict(
        finding_id=finding_id,
        category="idle",
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        window_start=0.0,
        window_end=3600.0,
        confidence=0.9,
        priceable=priceable,
        basis=BASIS_OBSERVED_WINDOW if priceable else None,
        amount_inr=amount_inr if priceable else None,
        recommended_action="terminate",
        methodology="test",
    )
    defaults.update(overrides)
    return SavingsEstimate(**defaults)


def test_insert_and_count(storage):
    storage.insert_estimates([_estimate()], estimated_at=1000.0)
    assert storage.count() == 1


def test_reinserting_same_finding_replaces_not_duplicates(storage):
    storage.insert_estimates([_estimate(finding_id=1, amount_inr=10.0)], estimated_at=1000.0)
    storage.insert_estimates([_estimate(finding_id=1, amount_inr=20.0)], estimated_at=2000.0)
    assert storage.count() == 1
    assert storage.all_estimates()[0]["amount_inr"] == 20.0


def test_reinserting_same_finding_preserves_row_id(storage):
    # Regression: INSERT OR REPLACE against a secondary UNIQUE index (not
    # the primary key) makes SQLite delete-then-insert on conflict, which
    # hands the replaced row a brand-new autoincrement id every time --
    # same bug class as waste-detector's finding id churn, fixed for the
    # same defensive-consistency reason even though nothing currently
    # depends on this table's own id staying stable downstream.
    storage.insert_estimates([_estimate(finding_id=1, amount_inr=10.0)], estimated_at=1000.0)
    first_id = storage.all_estimates()[0]["id"]

    storage.insert_estimates([_estimate(finding_id=1, amount_inr=20.0)], estimated_at=2000.0)
    second_id = storage.all_estimates()[0]["id"]

    assert first_id == second_id


def test_prune_older_than_removes_stale_estimates_keeps_active(storage):
    # Regression: savings_estimates had no pruning -- a resolved finding's
    # estimate just stops being refreshed rather than being deleted, so
    # stale estimates accumulate forever without this.
    storage.insert_estimates([_estimate(finding_id=1, amount_inr=10.0)], estimated_at=1000.0)
    storage.insert_estimates([_estimate(finding_id=2, amount_inr=20.0)], estimated_at=2_000_000.0)

    deleted = storage.prune_older_than(cutoff=1_000_000.0)

    assert deleted == 1
    remaining = storage.all_estimates()
    assert len(remaining) == 1
    assert remaining[0]["finding_id"] == 2


def test_total_priceable_amount_excludes_unpriceable(storage):
    storage.insert_estimates(
        [
            _estimate(finding_id=1, amount_inr=10.0, priceable=True),
            _estimate(finding_id=2, priceable=False),
        ],
        estimated_at=1000.0,
    )
    assert storage.total_priceable_amount() == 10.0


def test_all_estimates_priceable_only_filter(storage):
    storage.insert_estimates(
        [
            _estimate(finding_id=1, priceable=True),
            _estimate(finding_id=2, priceable=False),
        ],
        estimated_at=1000.0,
    )
    assert len(storage.all_estimates()) == 2
    assert len(storage.all_estimates(priceable_only=True)) == 1


def test_ceiling_is_one_row_replaced_each_cycle_and_cleared_when_absent(tmp_path):
    from savings_estimator.recoverable import RecoverableCeiling
    s = SavingsStorage(str(tmp_path / "s.db"))
    first = RecoverableCeiling(0.0, 3600.0, 70.0, 1.0, 300.0, 300.0, 219000.0, 0.0)
    second = RecoverableCeiling(0.0, 7200.0, 70.0, 2.0, 600.0, 150.0, 219000.0, 1.0)
    s.save_ceiling(first, computed_at=1.0)
    s.save_ceiling(second, computed_at=2.0)
    row = s.ceiling()
    assert row["observed_gpu_hours"] == 2.0 and row["excluded_gpu_hours"] == 1.0 and row["computed_at"] == 2.0
    assert s._conn.execute("SELECT COUNT(*) FROM recoverable_ceiling").fetchone()[0] == 1
    s.save_ceiling(None, computed_at=3.0)
    assert s.ceiling() is None
    s.close()
