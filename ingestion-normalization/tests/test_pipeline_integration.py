import json
import os

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
        # These tests use small synthetic timestamps (near epoch), not
        # real wall-clock time, and aren't testing retention -- pruning
        # against a real time.time() cutoff would delete every row they
        # write. Off by default here; retention-specific tests below
        # override these explicitly with a controlled `now`.
        normalized_samples_retention_hours=0,
        rollups_retention_hours=0,
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


def test_run_once_emits_structured_cycle_complete_log(tmp_path, raw_db_path, caplog):
    # Regression: an operator needs a consistent, parseable signal per
    # cycle without reading source code to learn what each service's
    # ad-hoc log message means. Schema shared across all five services:
    # event/component/duration_ms/rows_in/rows_out/errors.
    config = _config(raw_db_path, str(tmp_path / "normalized.db"))
    storage = NormalizedStorage(config.normalized_sqlite_path)
    reader = RawReader(config.raw_sqlite_path)

    with caplog.at_level("INFO", logger="ingestion_normalization.pipeline"):
        run_once(config, reader, storage)

    payloads = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    cycle_logs = [p for p in payloads if p.get("event") == "cycle_complete"]
    assert len(cycle_logs) == 1
    log = cycle_logs[0]
    assert log["component"] == "ingestion-normalization"
    assert log["rows_in"] == 5
    assert log["rows_out"] == 5
    assert log["errors"] == 0
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


def test_daily_rollup_recompute_is_throttled_across_cycles(tmp_path, dcgm_text, monkeypatch):
    # Regression: recomputing the whole daily bucket from scratch every
    # ingestion cycle makes per-cycle work grow with elapsed samples in the
    # day -- total work across a day is quadratic in cycle count. Daily
    # recompute must be throttled to a bounded cadence; 5m/hourly (whose
    # window size is naturally bounded) still recompute every cycle.
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, 0.0)])

    config = _config(
        raw_path, str(tmp_path / "normalized.db"),
        daily_rollup_min_recompute_interval_seconds=3600.0,
    )
    storage = NormalizedStorage(config.normalized_sqlite_path)

    wall_clock = {"now": 1_000_000.0}
    monkeypatch.setattr("ingestion_normalization.pipeline.time.time", lambda: wall_clock["now"])

    reader1 = RawReader(config.raw_sqlite_path)
    run_once(config, reader1, storage)
    reader1.close()
    for row in storage.rollups("daily"):
        assert row["sample_count"] == 1

    # A second cycle's worth of samples lands a minute later -- well
    # inside the same daily bucket and well under the throttle interval.
    populate_raw_db(raw_path, [(dcgm_text, 60.0)])
    wall_clock["now"] += 60.0

    reader2 = RawReader(config.raw_sqlite_path)
    run_once(config, reader2, storage)
    reader2.close()

    for row in storage.rollups("hourly"):
        assert row["sample_count"] == 2  # sees the new samples immediately
    for row in storage.rollups("daily"):
        assert row["sample_count"] == 1  # not re-scanned again this soon
    storage.close()


def test_daily_rollup_recompute_happens_again_after_interval_elapses(tmp_path, dcgm_text, monkeypatch):
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, 0.0)])

    config = _config(
        raw_path, str(tmp_path / "normalized.db"),
        daily_rollup_min_recompute_interval_seconds=3600.0,
    )
    storage = NormalizedStorage(config.normalized_sqlite_path)

    wall_clock = {"now": 1_000_000.0}
    monkeypatch.setattr("ingestion_normalization.pipeline.time.time", lambda: wall_clock["now"])

    reader1 = RawReader(config.raw_sqlite_path)
    run_once(config, reader1, storage)
    reader1.close()

    populate_raw_db(raw_path, [(dcgm_text, 60.0)])
    wall_clock["now"] += 3601.0  # past the throttle interval

    reader2 = RawReader(config.raw_sqlite_path)
    run_once(config, reader2, storage)
    reader2.close()

    for row in storage.rollups("daily"):
        assert row["sample_count"] == 2
    storage.close()


def test_run_once_prunes_old_normalized_samples_and_rollups(tmp_path, dcgm_text, monkeypatch):
    # Regression: normalized_samples and rollups had no pruning -- same
    # unbounded-growth risk telemetry-collector's raw store had. A short
    # retention window must actually get enforced by run_once.
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, 0.0)])  # ancient, pre-existing

    config = _config(
        raw_path, str(tmp_path / "normalized.db"),
        normalized_samples_retention_hours=1.0,
        rollups_retention_hours=1.0,
    )
    storage = NormalizedStorage(config.normalized_sqlite_path)

    wall_clock = {"now": 1000.0}
    monkeypatch.setattr("ingestion_normalization.pipeline.time.time", lambda: wall_clock["now"])

    reader1 = RawReader(config.raw_sqlite_path)
    run_once(config, reader1, storage)
    reader1.close()
    assert storage.count_normalized_samples() == 5  # well within the 1h retention window

    # A fresh cycle's worth of samples lands 2 hours later (wall clock
    # advances with it) -- now well past the 1h retention window for the
    # first cycle's data.
    populate_raw_db(raw_path, [(dcgm_text, 7200.0)])
    wall_clock["now"] = 7200.0

    reader2 = RawReader(config.raw_sqlite_path)
    run_once(config, reader2, storage)
    reader2.close()

    assert storage.count_normalized_samples() == 5  # only the fresh cycle's samples remain
    for row in storage.rollups("5m"):
        assert row["bucket_start"] >= 7200.0 - 300.0  # only the fresh bucket remains
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


def test_run_forever_writes_heartbeat_every_cycle_even_after_exception(
    tmp_path, dcgm_text, monkeypatch
):
    # Regression: run_once's own exceptions are caught inside run_forever
    # so the process never crashes on a bad cycle -- a plain "is the
    # process alive" Kubernetes liveness check can't detect a genuinely
    # stuck loop. The heartbeat file must be touched on every iteration
    # regardless of whether that cycle succeeded, so an exec probe
    # checking its mtime actually reflects loop liveness.
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, 0.0)])
    config = _config(
        raw_path, str(tmp_path / "normalized.db"),
        heartbeat_path=str(tmp_path / "heartbeat"),
    )

    calls = {"n": 0}
    import ingestion_normalization.main as main_module
    real_run_once = main_module.run_once

    def flaky_run_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom - simulated unexpected bug")
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(main_module, "run_once", flaky_run_once)

    main_module.run_forever(config, stop_after=1)

    # The very first (and only) cycle raised, yet the heartbeat must still
    # have been written -- it reflects loop liveness, not cycle success.
    assert os.path.exists(config.heartbeat_path)
    first_heartbeat = float(open(config.heartbeat_path).read())

    main_module.run_forever(config, stop_after=1)
    second_heartbeat = float(open(config.heartbeat_path).read())

    assert second_heartbeat > first_heartbeat


def test_run_forever_alerts_after_consecutive_failures_then_on_recovery(
    tmp_path, dcgm_text, monkeypatch
):
    # Regression: a structured cycle_complete log line only reaches an
    # operator who's already looking for it. Once failures cross the
    # configured threshold, a human-visible webhook alert must fire -- and
    # exactly once (edge-triggered), not on every cycle past the
    # threshold. A second alert must fire once the loop recovers.
    raw_path = str(tmp_path / "telemetry.db")
    populate_raw_db(raw_path, [(dcgm_text, 0.0)])
    config = _config(
        raw_path, str(tmp_path / "normalized.db"),
        heartbeat_path=str(tmp_path / "heartbeat"),
        alert_webhook_url="https://hooks.example.test/webhook",
    )

    posted = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        posted.append(json.loads(req.data.decode("utf-8"))["text"])
        return _FakeResponse()

    import ingestion_normalization.main as main_module

    monkeypatch.setattr(main_module.urllib.request, "urlopen", fake_urlopen)

    calls = {"n": 0}

    def flaky_run_once(*args, **kwargs):
        calls["n"] += 1
        # Cycles 1-4 fail (crossing the default threshold of 3 on cycle 3,
        # staying failed on cycle 4); cycle 5 recovers.
        if calls["n"] <= 4:
            raise ValueError("boom - simulated persistent failure")
        return 0

    monkeypatch.setattr(main_module, "run_once", flaky_run_once)

    main_module.run_forever(config, stop_after=5)

    # Cycle 3 crosses the threshold (one alert); cycle 4 stays failed past
    # it (no new alert); cycle 5 recovers (a second, distinct alert).
    assert len(posted) == 2
    assert "3 consecutive failed" in posted[0]
    assert "recovered" in posted[1]
