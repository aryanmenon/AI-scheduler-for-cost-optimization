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
