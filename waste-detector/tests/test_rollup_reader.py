from conftest import make_rollup_record, write_rollups

from waste_detector.rollup_reader import RollupReader


def test_fetch_returns_rows_for_granularity(tmp_path):
    path = str(tmp_path / "normalized.db")
    write_rollups(path, "hourly", [make_rollup_record(bucket_start=0.0)])

    reader = RollupReader(path)
    try:
        rows = reader.fetch("hourly")
        assert len(rows) == 1
        assert rows[0].node == "gpu-node-1"
        assert rows[0].avg_utilization_pct == 50.0
    finally:
        reader.close()


def test_fetch_filters_by_granularity(tmp_path):
    path = str(tmp_path / "normalized.db")
    write_rollups(path, "hourly", [make_rollup_record(bucket_start=0.0)])
    write_rollups(path, "daily", [make_rollup_record(bucket_start=0.0)])

    reader = RollupReader(path)
    try:
        assert len(reader.fetch("hourly")) == 1
        assert len(reader.fetch("daily")) == 1
        assert len(reader.fetch("5m")) == 0
    finally:
        reader.close()


def test_fetch_filters_by_time_range(tmp_path):
    path = str(tmp_path / "normalized.db")
    records = [make_rollup_record(bucket_start=float(i * 3600)) for i in range(5)]
    write_rollups(path, "hourly", records)

    reader = RollupReader(path)
    try:
        rows = reader.fetch("hourly", since=3600.0, until=10800.0)
        assert [r.bucket_start for r in rows] == [3600.0, 7200.0]
    finally:
        reader.close()


def test_latest_bucket_start(tmp_path):
    path = str(tmp_path / "normalized.db")
    records = [make_rollup_record(bucket_start=float(i * 3600)) for i in range(3)]
    write_rollups(path, "hourly", records)

    reader = RollupReader(path)
    try:
        assert reader.latest_bucket_start("hourly") == 7200.0
        assert reader.latest_bucket_start("daily") is None
    finally:
        reader.close()


def test_reader_is_read_only(tmp_path):
    import sqlite3

    import pytest

    path = str(tmp_path / "normalized.db")
    write_rollups(path, "hourly", [make_rollup_record(bucket_start=0.0)])

    reader = RollupReader(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader._conn.execute("DELETE FROM rollups")
    finally:
        reader.close()
