from conftest import make_rollup_record, write_rollups

from waste_detector.rollup_reader import RollupReader, _valid_pct, _valid_ratio


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


def test_valid_pct_rejects_nan():
    # Regression: NaN is neither > nor <= any threshold, so a raw NaN could
    # slip past a detector's "continue if above threshold" guard and get
    # flagged as waste on garbage data. It must be sanitized to missing.
    # (sqlite3 itself round-trips a stored NaN as NULL already -- see
    # test_out_of_range_utilization_sanitized_to_none for the reachable
    # case -- so this exercises the sanitizer directly as a hard invariant.)
    assert _valid_pct(float("nan")) is None


def test_valid_ratio_rejects_nan_and_negative():
    assert _valid_ratio(float("nan")) == 0.0
    assert _valid_ratio(-1.0) == 0.0
    assert _valid_ratio(1.5) == 1.0


def test_out_of_range_utilization_sanitized_to_none(tmp_path):
    path = str(tmp_path / "normalized.db")
    write_rollups(
        path,
        "hourly",
        [make_rollup_record(bucket_start=0.0, avg_utilization_pct=-5.0, max_utilization_pct=250.0)],
    )

    reader = RollupReader(path)
    try:
        row = reader.fetch("hourly")[0]
        assert row.avg_utilization_pct is None
        assert row.max_utilization_pct is None
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
