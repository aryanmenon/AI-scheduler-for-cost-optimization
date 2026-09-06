import json

from conftest import make_rollup_record, write_rollups

from waste_detector.config import Config
from waste_detector.findings import IDLE, FindingsStorage
from waste_detector.main import run_forever
from waste_detector.pipeline import run_once
from waste_detector.rollup_reader import RollupReader


def _config(normalized_path: str, findings_path: str, **overrides) -> Config:
    defaults = dict(
        normalized_sqlite_path=normalized_path,
        findings_sqlite_path=findings_path,
        poll_interval_seconds=0,
        min_coverage_ratio=0.8,
        idle_threshold_pct=2.0,
        min_idle_streak_hours=4,
        over_provision_threshold_pct=30.0,
        over_provision_min_observation_hours=24,
        fragmentation_threshold_pct=50.0,
        fragmentation_min_underutilized_gpus=2,
        fragmentation_min_streak_hours=4,
        pattern_min_days_observed=7,
        pattern_idle_threshold_pct=5.0,
        pattern_min_consistent_fraction=0.8,
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_run_once_produces_idle_finding_from_real_rollups(tmp_path):
    normalized_path = str(tmp_path / "normalized.db")
    records = [
        make_rollup_record(bucket_start=float(i * 3600), avg_utilization_pct=0.0, max_utilization_pct=0.0)
        for i in range(6)
    ]
    write_rollups(normalized_path, "hourly", records)

    config = _config(normalized_path, str(tmp_path / "findings.db"))
    storage = FindingsStorage(config.findings_sqlite_path)
    reader = RollupReader(config.normalized_sqlite_path)

    count = run_once(config, reader, storage)

    assert count == 1
    findings = storage.all_findings(category=IDLE)
    assert len(findings) == 1
    reader.close()
    storage.close()


def test_run_once_emits_structured_cycle_complete_log(tmp_path, caplog):
    # Regression: an operator needs a consistent, parseable signal per
    # cycle without reading source code to learn what each service's
    # ad-hoc log message means. Schema shared across all five services:
    # event/component/duration_ms/rows_in/rows_out/errors.
    normalized_path = str(tmp_path / "normalized.db")
    records = [
        make_rollup_record(bucket_start=float(i * 3600), avg_utilization_pct=0.0, max_utilization_pct=0.0)
        for i in range(6)
    ]
    write_rollups(normalized_path, "hourly", records)

    config = _config(normalized_path, str(tmp_path / "findings.db"))
    storage = FindingsStorage(config.findings_sqlite_path)
    reader = RollupReader(config.normalized_sqlite_path)

    with caplog.at_level("INFO", logger="waste_detector.pipeline"):
        run_once(config, reader, storage)

    payloads = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    cycle_logs = [p for p in payloads if p.get("event") == "cycle_complete"]
    assert len(cycle_logs) == 1
    log = cycle_logs[0]
    assert log["component"] == "waste-detector"
    assert log["rows_in"] == 6
    assert log["rows_out"] == 1
    assert log["errors"] == 0
    reader.close()
    storage.close()


def test_run_once_is_idempotent_on_unchanged_rollups(tmp_path):
    normalized_path = str(tmp_path / "normalized.db")
    records = [
        make_rollup_record(bucket_start=float(i * 3600), avg_utilization_pct=0.0, max_utilization_pct=0.0)
        for i in range(6)
    ]
    write_rollups(normalized_path, "hourly", records)

    config = _config(normalized_path, str(tmp_path / "findings.db"))
    storage = FindingsStorage(config.findings_sqlite_path)

    reader1 = RollupReader(config.normalized_sqlite_path)
    run_once(config, reader1, storage)
    reader1.close()

    reader2 = RollupReader(config.normalized_sqlite_path)
    run_once(config, reader2, storage)
    reader2.close()

    assert storage.count() == 1  # re-running over the same data doesn't duplicate
    storage.close()


def test_run_once_does_not_flag_corrupted_peak_as_over_provisioned(tmp_path):
    # Regression: a corrupted, negative max_utilization_pct (a bad
    # driver/DCGM read) reads as "below threshold" just like a genuinely
    # idle peak would, and must be excluded as untrustworthy rather than
    # trusted into flagging the workload as over-provisioned on garbage
    # data.
    normalized_path = str(tmp_path / "normalized.db")
    records = [
        make_rollup_record(bucket_start=float(i * 3600), avg_utilization_pct=10.0, max_utilization_pct=-5.0)
        for i in range(24)
    ]
    write_rollups(normalized_path, "hourly", records)

    config = _config(normalized_path, str(tmp_path / "findings.db"))
    storage = FindingsStorage(config.findings_sqlite_path)
    reader = RollupReader(config.normalized_sqlite_path)

    run_once(config, reader, storage)

    from waste_detector.findings import OVER_PROVISIONED

    assert storage.all_findings(category=OVER_PROVISIONED) == []
    reader.close()
    storage.close()


def test_run_once_prunes_stale_findings_no_longer_redetected(tmp_path, monkeypatch):
    # Regression: waste_findings had no pruning -- once a condition
    # resolves (the workload is decommissioned, or simply stops being
    # idle), its last finding just stops being refreshed rather than
    # being deleted, so it would linger forever without this.
    normalized_path = str(tmp_path / "normalized.db")
    records = [
        make_rollup_record(bucket_start=float(i * 3600), avg_utilization_pct=0.0, max_utilization_pct=0.0)
        for i in range(6)
    ]
    write_rollups(normalized_path, "hourly", records)

    findings_path = str(tmp_path / "findings.db")
    config = _config(normalized_path, findings_path, findings_retention_hours=1.0)
    storage = FindingsStorage(findings_path)

    wall_clock = {"now": 1000.0}
    monkeypatch.setattr("waste_detector.pipeline.time.time", lambda: wall_clock["now"])

    reader1 = RollupReader(normalized_path)
    run_once(config, reader1, storage)
    reader1.close()
    assert storage.count() == 1

    # A later cycle's rollup data no longer includes this workload at all
    # -- nothing re-detects/refreshes the earlier finding -- and enough
    # wall-clock time has passed to exceed the 1h retention window.
    empty_normalized_path = str(tmp_path / "empty_normalized.db")
    write_rollups(empty_normalized_path, "hourly", [])
    wall_clock["now"] = 10_000.0

    reader2 = RollupReader(empty_normalized_path)
    run_once(config, reader2, storage)
    reader2.close()

    assert storage.count() == 0
    storage.close()


def test_run_once_with_no_rollups_yet(tmp_path):
    normalized_path = str(tmp_path / "normalized.db")
    write_rollups(normalized_path, "hourly", [])  # creates schema, no rows

    config = _config(normalized_path, str(tmp_path / "findings.db"))
    storage = FindingsStorage(config.findings_sqlite_path)
    reader = RollupReader(config.normalized_sqlite_path)

    count = run_once(config, reader, storage)

    assert count == 0
    assert storage.count() == 0
    reader.close()
    storage.close()


def test_run_forever_picks_up_new_rollups_across_cycles(tmp_path):
    normalized_path = str(tmp_path / "normalized.db")
    records = [
        make_rollup_record(bucket_start=float(i * 3600), avg_utilization_pct=0.0, max_utilization_pct=0.0)
        for i in range(6)
    ]
    write_rollups(normalized_path, "hourly", records)

    config = _config(normalized_path, str(tmp_path / "findings.db"))

    run_forever(config, stop_after=2)

    storage = FindingsStorage(config.findings_sqlite_path)
    assert storage.count() == 1  # same finding both cycles, replaced not duplicated
    storage.close()
