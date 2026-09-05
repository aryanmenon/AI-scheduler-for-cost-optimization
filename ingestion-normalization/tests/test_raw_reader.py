import sqlite3

import pytest

from ingestion_normalization.raw_reader import RawReader


def test_fetch_since_zero_returns_all_rows(raw_db_path):
    reader = RawReader(raw_db_path)
    try:
        samples = reader.fetch_since(0)
        assert len(samples) == 5  # dcgm_sample.prom has 5 GPUs
        assert reader.latest_run_id() == 1
    finally:
        reader.close()


def test_fetch_since_excludes_already_processed_run(raw_db_path):
    reader = RawReader(raw_db_path)
    try:
        samples = reader.fetch_since(1)
        assert samples == []
    finally:
        reader.close()


def test_reader_cannot_write_to_raw_db(raw_db_path):
    reader = RawReader(raw_db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader._conn.execute("DELETE FROM gpu_metrics")
    finally:
        reader.close()
