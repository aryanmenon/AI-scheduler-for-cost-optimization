import json

from conftest import make_finding, make_rollup_record, write_findings, write_rollups

from savings_estimator.config import Config
from savings_estimator.findings_reader import FindingsReader
from savings_estimator.main import run_forever
from savings_estimator.pipeline import run_once
from savings_estimator.rollup_reader import RollupReader
from savings_estimator.storage import SavingsStorage


def _config(findings_path, normalized_path, savings_path, **overrides) -> Config:
    defaults = dict(
        findings_sqlite_path=findings_path,
        normalized_sqlite_path=normalized_path,
        savings_sqlite_path=savings_path,
        poll_interval_seconds=0,
        min_finding_confidence=0.7,
        sla_target_utilization_pct=70.0,
        hours_per_month=730.0,
        fragmentation_capture_fraction=0.5,
        gpu_hourly_rates_json=None,
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_run_once_prices_a_real_idle_finding(tmp_path):
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(findings_path, [make_finding("idle", window_start=0.0, window_end=4 * 3600.0, confidence=0.9)])
    write_rollups(normalized_path, "hourly", [make_rollup_record(bucket_start=float(i * 3600)) for i in range(4)])

    config = _config(findings_path, normalized_path, savings_path)
    storage = SavingsStorage(config.savings_sqlite_path)
    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)

    count = run_once(config, findings_reader, rollup_reader, storage)

    assert count == 1
    estimates = storage.all_estimates()
    assert len(estimates) == 1
    assert estimates[0]["priceable"] == 1
    assert estimates[0]["amount_inr"] == 4 * 300.00

    findings_reader.close()
    rollup_reader.close()
    storage.close()


def test_run_once_emits_structured_cycle_complete_log(tmp_path, caplog):
    # Regression: an operator needs a consistent, parseable signal per
    # cycle without reading source code to learn what each service's
    # ad-hoc log message means. Schema shared across all five services:
    # event/component/duration_ms/rows_in/rows_out/errors.
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(findings_path, [make_finding("idle", window_start=0.0, window_end=4 * 3600.0, confidence=0.9)])
    write_rollups(normalized_path, "hourly", [make_rollup_record(bucket_start=float(i * 3600)) for i in range(4)])

    config = _config(findings_path, normalized_path, savings_path)
    storage = SavingsStorage(config.savings_sqlite_path)
    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)

    with caplog.at_level("INFO", logger="savings_estimator.pipeline"):
        run_once(config, findings_reader, rollup_reader, storage)

    payloads = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    cycle_logs = [p for p in payloads if p.get("event") == "cycle_complete"]
    assert len(cycle_logs) == 1
    log = cycle_logs[0]
    assert log["component"] == "savings-estimator"
    assert log["rows_in"] == 1
    assert log["rows_out"] == 1
    assert log["priceable"] == 1
    assert log["errors"] == 0
    findings_reader.close()
    rollup_reader.close()
    storage.close()


def test_run_once_skips_findings_below_min_confidence(tmp_path):
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(
        findings_path,
        [
            make_finding("idle", gpu_index="0", confidence=0.9),
            make_finding("idle", gpu_index="1", confidence=0.2),
        ],
    )
    write_rollups(
        normalized_path,
        "hourly",
        [
            make_rollup_record(bucket_start=0.0, gpu_index="0"),
            make_rollup_record(bucket_start=0.0, gpu_index="1"),
        ],
    )

    config = _config(findings_path, normalized_path, savings_path, min_finding_confidence=0.7)
    storage = SavingsStorage(config.savings_sqlite_path)
    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)

    count = run_once(config, findings_reader, rollup_reader, storage)

    assert count == 1  # only the 0.9-confidence finding
    findings_reader.close()
    rollup_reader.close()
    storage.close()


def test_ongoing_finding_across_cycles_does_not_double_count(tmp_path):
    # Regression: waste-detector's own findings.db previously churned a
    # finding's id every time an ONGOING condition was re-detected with a
    # growing window (INSERT OR REPLACE against a secondary unique index
    # resets SQLite's autoincrement id). SavingsEstimate.finding_id is
    # sourced from that id, so the churn meant savings-estimator's own
    # dedup (keyed on finding_id) never matched -- a fresh estimate row
    # was inserted every pricing cycle for the same still-active finding,
    # double-counting its savings. This writes findings.db via the real
    # waste_detector.FindingsStorage.insert_findings across two cycles
    # (as waste-detector's own pipeline does for an ongoing condition),
    # not a static fixture, so it actually exercises that code path.
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_rollups(normalized_path, "hourly", [make_rollup_record(bucket_start=0.0)])
    config = _config(findings_path, normalized_path, savings_path)
    storage = SavingsStorage(config.savings_sqlite_path)

    write_findings(findings_path, [make_finding("idle", window_end=3600.0)], detected_at=1000.0)
    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)
    run_once(config, findings_reader, rollup_reader, storage)
    findings_reader.close()
    rollup_reader.close()

    # A second waste-detector cycle re-detects the same ongoing streak
    # with a grown window_end -- same identity, updated evidence.
    write_findings(findings_path, [make_finding("idle", window_end=7200.0)], detected_at=2000.0)
    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)
    run_once(config, findings_reader, rollup_reader, storage)
    findings_reader.close()
    rollup_reader.close()

    assert storage.count() == 1
    storage.close()


def test_run_once_is_idempotent(tmp_path):
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(findings_path, [make_finding("idle")])
    write_rollups(normalized_path, "hourly", [make_rollup_record(bucket_start=0.0)])

    config = _config(findings_path, normalized_path, savings_path)
    storage = SavingsStorage(config.savings_sqlite_path)

    for _ in range(2):
        findings_reader = FindingsReader(config.findings_sqlite_path)
        rollup_reader = RollupReader(config.normalized_sqlite_path)
        run_once(config, findings_reader, rollup_reader, storage)
        findings_reader.close()
        rollup_reader.close()

    assert storage.count() == 1
    storage.close()


def test_run_once_prunes_stale_estimates_no_longer_priced(tmp_path, monkeypatch):
    # Regression: savings_estimates had no pruning -- once a finding
    # resolves (or is pruned upstream in waste-detector), its estimate
    # just stops being refreshed rather than being deleted, so it would
    # linger forever without this.
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(findings_path, [make_finding("idle")], detected_at=1000.0)
    write_rollups(normalized_path, "hourly", [make_rollup_record(bucket_start=0.0)])

    config = _config(findings_path, normalized_path, savings_path, savings_estimates_retention_hours=1.0)
    storage = SavingsStorage(config.savings_sqlite_path)

    wall_clock = {"now": 1000.0}
    monkeypatch.setattr("savings_estimator.pipeline.time.time", lambda: wall_clock["now"])

    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)
    run_once(config, findings_reader, rollup_reader, storage)
    findings_reader.close()
    rollup_reader.close()
    assert storage.count() == 1

    # The finding is gone upstream (resolved, or pruned in waste-detector)
    # -- nothing re-prices/refreshes the earlier estimate -- and enough
    # wall-clock time has passed to exceed the 1h retention window.
    write_findings(str(tmp_path / "empty_findings.db"), [])
    wall_clock["now"] = 10_000.0

    findings_reader = FindingsReader(str(tmp_path / "empty_findings.db"))
    rollup_reader = RollupReader(config.normalized_sqlite_path)
    run_once(config, findings_reader, rollup_reader, storage)
    findings_reader.close()
    rollup_reader.close()

    assert storage.count() == 0
    storage.close()


def test_run_once_with_no_findings_yet(tmp_path):
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(findings_path, [])
    write_rollups(normalized_path, "hourly", [])

    config = _config(findings_path, normalized_path, savings_path)
    storage = SavingsStorage(config.savings_sqlite_path)
    findings_reader = FindingsReader(config.findings_sqlite_path)
    rollup_reader = RollupReader(config.normalized_sqlite_path)

    count = run_once(config, findings_reader, rollup_reader, storage)

    assert count == 0
    findings_reader.close()
    rollup_reader.close()
    storage.close()


def test_run_forever_produces_stable_output_across_cycles(tmp_path):
    findings_path = str(tmp_path / "findings.db")
    normalized_path = str(tmp_path / "normalized.db")
    savings_path = str(tmp_path / "savings.db")

    write_findings(findings_path, [make_finding("idle", window_start=0.0, window_end=3600.0)])
    write_rollups(normalized_path, "hourly", [make_rollup_record(bucket_start=0.0)])

    config = _config(findings_path, normalized_path, savings_path)

    run_forever(config, stop_after=3)

    storage = SavingsStorage(config.savings_sqlite_path)
    assert storage.count() == 1
    storage.close()
