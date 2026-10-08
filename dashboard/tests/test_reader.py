import sqlite3

import pytest
from conftest import make_estimate, write_estimates

from dashboard.report_reader import ReportReader


def test_reads_real_savings_db(tmp_path):
    path = str(tmp_path / "savings.db")
    write_estimates(path, [make_estimate(1), make_estimate(2, category="idle")])

    reader = ReportReader(path)
    try:
        rows = reader.all_estimates()
        assert len(rows) == 2
        assert rows[0].category == "idle"
    finally:
        reader.close()


def test_reader_is_read_only(tmp_path):
    path = str(tmp_path / "savings.db")
    write_estimates(path, [make_estimate(1)])
    reader = ReportReader(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader._conn.execute("DELETE FROM savings_estimates")
    finally:
        reader.close()


def test_reads_unpriceable_rows_with_null_fields(tmp_path):
    path = str(tmp_path / "savings.db")
    write_estimates(path, [make_estimate(1, priceable=False)])

    reader = ReportReader(path)
    try:
        rows = reader.all_estimates()
        assert rows[0].priceable is False
        assert rows[0].amount_inr is None
        assert rows[0].basis is None
    finally:
        reader.close()


def test_ceiling_absent_on_a_savings_db_from_before_it_existed(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE savings_estimates (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    reader = ReportReader(path)
    try:
        assert reader.ceiling() is None
    finally:
        reader.close()


def test_reads_the_ceiling_row(tmp_path):
    from types import SimpleNamespace

    from savings_estimator.storage import SavingsStorage
    path = str(tmp_path / "savings.db")
    s = SavingsStorage(path)
    s.save_ceiling(SimpleNamespace(
        window_start=0.0, window_end=7200.0, target_utilization_pct=70.0, observed_gpu_hours=2.0,
        observed_spend_inr=600.0, recoverable_inr=270.0, monthly_spend_inr=219000.0,
        excluded_gpu_hours=0.0), computed_at=1.0)
    s.close()
    reader = ReportReader(path)
    try:
        c = reader.ceiling()
        assert c.fraction == 0.45
        assert c.monthly_recoverable_inr == 0.45 * 219000.0
    finally:
        reader.close()
