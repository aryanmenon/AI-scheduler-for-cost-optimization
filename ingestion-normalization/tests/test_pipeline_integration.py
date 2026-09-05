import pytest

from ingestion_normalization.config import Config
from ingestion_normalization.main import run_forever
from ingestion_normalization.pipeline import run_once
from ingestion_normalization.raw_reader import RawReader
from ingestion_normalization.storage import NormalizedStorage

from conftest import populate_raw_db


def _config(raw_path: str, normalized_path: str, **overrides) -> Config:
    defaults = dict(
        raw_sqlite_path=raw_path,
        normalized_sqlite_path=normalized_path,
        poll_interval_seconds=0,
        source_scrape_interval_seconds=30,
        low_confidence_coverage_threshold=0.5,
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_run_once_ingests_and_advances_cursor(tmp_path, raw_db_path):
    config = _config(raw_db_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)
    reader = RawReader(config.raw_sqlite_path)

    ingested = run_once(config, reader, storage)

    assert ingested == 5
    assert storage.count_normalized_samples() == 5
    assert storage.get_cursor() == 1
    reader.close()
    storage.close()


def test_run_once_is_a_noop_when_no_new_raw_data(tmp_path, raw_db_path):
    config = _config(raw_db_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)

    reader1 = RawReader(config.raw_sqlite_path)
    run_once(config, reader1, storage)
    reader1.close()

    reader2 = RawReader(config.raw_sqlite_path)
    second_ingested = run_once(config, reader2, storage)
    reader2.close()

    assert second_ingested == 0
    assert storage.count_normalized_samples() == 5  # no duplicates
    storage.close()


def test_run_once_produces_rollups_for_ingested_window(tmp_path, raw_db_path):
    config = _config(raw_db_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)
    reader = RawReader(config.raw_sqlite_path)

    run_once(config, reader, storage)

    five_min = storage.rollups("5m")
    assert len(five_min) == 5  # one per GPU (each its own workload/node/gpu_index)
    for row in five_min:
        assert row["sample_count"] == 1
        assert row["coverage_ratio"] == pytest.approx(1 / 10)
    reader.close()
    storage.close()


def test_gap_across_scrape_cycles_flags_low_confidence(tmp_path, dcgm_text):
    raw_path = str(tmp_path / "telemetry.db")
    # Only 3 of the 10 scrapes a full 5-minute bucket would expect at a
    # 30s cadence -- simulates a collector outage covering most of the window.
    populate_raw_db(raw_path, [(dcgm_text, t) for t in (0.0, 30.0, 60.0)])

    config = _config(raw_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)
    reader = RawReader(config.raw_sqlite_path)

    run_once(config, reader, storage)

    five_min = storage.rollups("5m")
    assert len(five_min) == 5  # still one row per GPU
    for row in five_min:
        assert row["sample_count"] == 3
        assert row["coverage_ratio"] == 0.3
        assert bool(row["low_confidence"]) is True
    reader.close()
    storage.close()


def test_full_coverage_bucket_not_flagged_low_confidence(tmp_path, dcgm_text):
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, i * 30.0) for i in range(10)])

    config = _config(raw_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)
    reader = RawReader(config.raw_sqlite_path)

    run_once(config, reader, storage)

    five_min = storage.rollups("5m")
    for row in five_min:
        assert row["sample_count"] == 10
        assert row["coverage_ratio"] == 1.0
        assert bool(row["low_confidence"]) is False
    reader.close()
    storage.close()


def test_mig_samples_normalize_to_distinct_workloads(tmp_path, dcgm_mig_text):
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_mig_text, 0.0)])

    config = _config(raw_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)
    reader = RawReader(config.raw_sqlite_path)

    run_once(config, reader, storage)

    rows = storage.normalized_samples_between(-1, 1)
    assert len(rows) == 2
    workloads = {row["workload"] for row in rows}
    assert workloads == {"small-model-a", "small-model-b"}
    instance_ids = {row["gpu_instance_id"] for row in rows}
    assert instance_ids == {"1", "2"}
    reader.close()
    storage.close()


def test_run_forever_ingests_across_multiple_polling_cycles(tmp_path, dcgm_text):
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, 0.0), (dcgm_text, 30.0)])

    config = _config(raw_path, str(tmp_path / "normalized.db"))

    run_forever(config, stop_after=2)

    storage = NormalizedStorage(config.normalized_sqlite_path)
    assert storage.count_normalized_samples() == 10  # 2 runs x 5 GPUs
    assert storage.get_cursor() == 2
    storage.close()
