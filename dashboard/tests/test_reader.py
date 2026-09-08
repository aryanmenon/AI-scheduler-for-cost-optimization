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
