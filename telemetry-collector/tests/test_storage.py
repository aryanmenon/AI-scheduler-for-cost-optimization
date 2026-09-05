import pytest

from telemetry_collector.correlator import correlate
from telemetry_collector.metrics_client import parse_metrics
from telemetry_collector.storage import Storage


@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "telemetry.db"))
    yield s
    s.close()


def test_record_scrape_persists_all_gpus(storage, dcgm_text):
    records = correlate(parse_metrics(dcgm_text))
    run_id = storage.record_scrape(records, duration_ms=42.0)
    assert run_id == 1
    assert storage.count_gpu_metrics() == 5
    assert storage.count_scrape_runs() == 1


def test_record_scrape_tracks_attributed_count(storage, dcgm_text):
    records = correlate(parse_metrics(dcgm_text))
    storage.record_scrape(records, duration_ms=10.0)
    row = storage._conn.execute("SELECT attributed_count, gpu_count FROM scrape_runs").fetchone()
    assert row == (4, 5)  # 4 of 5 GPUs attributed in the fixture


def test_repeated_scrapes_accumulate_without_clobbering(storage, dcgm_text):
    records = correlate(parse_metrics(dcgm_text))
    for _ in range(5):
        storage.record_scrape(records, duration_ms=10.0)
    assert storage.count_scrape_runs() == 5
    assert storage.count_gpu_metrics() == 25


def test_failed_scrape_recorded_with_zero_gpus(storage):
    run_id = storage.record_scrape([], duration_ms=5.0, success=False, error="timeout")
    assert run_id == 1
    row = storage._conn.execute("SELECT success, error, gpu_count FROM scrape_runs").fetchone()
    assert row == (0, "timeout", 0)


def test_storage_survives_reopen_on_same_path(tmp_path, dcgm_text):
    path = str(tmp_path / "telemetry.db")
    records = correlate(parse_metrics(dcgm_text))

    s1 = Storage(path)
    s1.record_scrape(records, duration_ms=1.0)
    s1.close()

    s2 = Storage(path)
    assert s2.count_gpu_metrics() == 5
    s2.close()


def test_latest_metrics_returns_rows(storage, dcgm_text):
    records = correlate(parse_metrics(dcgm_text))
    storage.record_scrape(records, duration_ms=1.0)
    rows = storage.latest_metrics(limit=10)
    assert len(rows) == 5
    assert rows[0]["node"] in {"gpu-node-1", "gpu-node-2", "gpu-node-3"}
