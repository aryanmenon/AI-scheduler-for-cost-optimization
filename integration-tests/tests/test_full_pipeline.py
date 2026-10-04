"""End-to-end pipeline test: telemetry-collector -> ingestion-normalization
-> waste-detector -> savings-estimator -> dashboard, wired together with
each module's own real run_once/entrypoint functions against real, on-disk
SQLite files -- not a fixture standing in for a neighbor's schema.

Every module's own test suite tests it against hand-built inputs that
*assume* a particular shape for its upstream neighbor's database. This
proves those assumptions actually hold when the real producer writes the
data, not just when a test fixture imitates it.
"""
from __future__ import annotations

from dashboard.aggregator import aggregate
from dashboard.render import render_report
from dashboard.report_reader import ReportReader
from ingestion_normalization.config import Config as IngestionConfig
from ingestion_normalization.pipeline import run_once as ingestion_run_once
from ingestion_normalization.raw_reader import RawReader
from ingestion_normalization.storage import NormalizedStorage
from savings_estimator.config import Config as SavingsConfig
from savings_estimator.findings_reader import FindingsReader
from savings_estimator.pipeline import run_once as savings_run_once
from savings_estimator.rollup_reader import RollupReader as SavingsRollupReader
from savings_estimator.storage import SavingsStorage
from telemetry_collector.correlator import correlate
from telemetry_collector.metrics_client import parse_metrics
from telemetry_collector.storage import Storage as TelemetryStorage
from waste_detector.config import Config as WasteConfig
from waste_detector.findings import FindingsStorage
from waste_detector.pipeline import run_once as waste_run_once
from waste_detector.rollup_reader import RollupReader as WasteRollupReader

_DCGM_TEXT_TEMPLATE = """# HELP DCGM_FI_DEV_GPU_UTIL GPU utilization (in %).
# TYPE DCGM_FI_DEV_GPU_UTIL gauge
DCGM_FI_DEV_GPU_UTIL{{gpu="0",device="nvidia0",modelName="NVIDIA A100-SXM4-80GB",Hostname="gpu-node-1",namespace="inference",pod="bert-large-7d4f-xk2p9",container="model-server"}} {util}
"""

_HOUR = 3600.0


def _scrape(storage: TelemetryStorage, util_pct: float, scraped_at: float) -> None:
    samples = parse_metrics(_DCGM_TEXT_TEMPLATE.format(util=util_pct))
    records = correlate(samples)
    storage.record_scrape(records, duration_ms=5.0, success=True, scraped_at=scraped_at)


def test_sustained_idle_gpu_flows_from_raw_scrape_to_a_priced_rupee_figure(tmp_path):
    telemetry_path = str(tmp_path / "telemetry.db")
    normalized_path = str(tmp_path / "normalized.db")
    findings_path = str(tmp_path / "findings.db")
    savings_path = str(tmp_path / "savings.db")

    # --- telemetry-collector: 4 hourly scrapes of one idle (0%) A100 ---
    telemetry_storage = TelemetryStorage(telemetry_path)
    for hour in range(4):
        _scrape(telemetry_storage, util_pct=0.0, scraped_at=hour * _HOUR)
    telemetry_storage.close()

    # --- ingestion-normalization: normalize the raw scrapes and roll them
    # up into hourly buckets. One sample per hour == full coverage per
    # bucket at this scrape interval.
    ingestion_config = IngestionConfig(
        raw_sqlite_path=telemetry_path,
        normalized_sqlite_path=normalized_path,
        poll_interval_seconds=0,
        source_scrape_interval_seconds=_HOUR,
        low_confidence_coverage_threshold=0.5,
        normalized_samples_retention_hours=0,
        rollups_retention_hours=0,
    )
    normalized_storage = NormalizedStorage(normalized_path)
    raw_reader = RawReader(telemetry_path)
    ingested = ingestion_run_once(ingestion_config, raw_reader, normalized_storage)
    raw_reader.close()
    normalized_storage.close()
    assert ingested == 4  # one GPU, one sample per scrape, four scrapes

    # --- waste-detector: a 4h idle streak should be flagged ---
    waste_config = WasteConfig(
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
        findings_retention_hours=0,
    )
    findings_storage = FindingsStorage(findings_path)
    waste_rollup_reader = WasteRollupReader(normalized_path)
    found = waste_run_once(waste_config, waste_rollup_reader, findings_storage)
    waste_rollup_reader.close()
    findings_storage.close()
    assert found == 1

    # --- savings-estimator: price the idle finding ---
    savings_config = SavingsConfig(
        findings_sqlite_path=findings_path,
        normalized_sqlite_path=normalized_path,
        savings_sqlite_path=savings_path,
        poll_interval_seconds=0,
        min_finding_confidence=0.7,
        sla_target_utilization_pct=70.0,
        hours_per_month=730.0,
        fragmentation_capture_fraction=0.5,
        gpu_hourly_rates_json=None,
        savings_estimates_retention_hours=0,
    )
    savings_storage = SavingsStorage(savings_path)
    findings_reader = FindingsReader(findings_path)
    savings_rollup_reader = SavingsRollupReader(normalized_path)
    priced = savings_run_once(savings_config, findings_reader, savings_rollup_reader, savings_storage)
    findings_reader.close()
    savings_rollup_reader.close()
    savings_storage.close()
    assert priced == 1

    verify_storage = SavingsStorage(savings_path)
    estimates = verify_storage.all_estimates()
    verify_storage.close()
    assert len(estimates) == 1
    assert bool(estimates[0]["priceable"]) is True
    # 4 hours idle at the A100 default illustrative rate (Rs 300.00/hr).
    assert estimates[0]["amount_inr"] == 4 * 300.00

    # --- dashboard: read the real savings.db, aggregate, render ---
    report_reader = ReportReader(savings_path)
    rows = report_reader.all_estimates()
    summary = aggregate(rows, top_n=10)
    html_out = render_report(summary)

    assert "₹1,200.00" in html_out
    assert "bert-large" in html_out
    assert "Idle GPUs" in html_out


def test_second_cycle_with_no_new_data_does_not_duplicate_anything(tmp_path):
    # The whole pipeline re-run over unchanged upstream data, at every
    # layer, must be a no-op -- not a source of duplicate findings,
    # duplicate estimates, or a changed rendered total.
    telemetry_path = str(tmp_path / "telemetry.db")
    normalized_path = str(tmp_path / "normalized.db")
    findings_path = str(tmp_path / "findings.db")
    savings_path = str(tmp_path / "savings.db")

    telemetry_storage = TelemetryStorage(telemetry_path)
    for hour in range(4):
        _scrape(telemetry_storage, util_pct=0.0, scraped_at=hour * _HOUR)
    telemetry_storage.close()

    ingestion_config = IngestionConfig(
        raw_sqlite_path=telemetry_path,
        normalized_sqlite_path=normalized_path,
        poll_interval_seconds=0,
        source_scrape_interval_seconds=_HOUR,
        low_confidence_coverage_threshold=0.5,
        normalized_samples_retention_hours=0,
        rollups_retention_hours=0,
    )
    waste_config = WasteConfig(
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
        findings_retention_hours=0,
    )
    savings_config = SavingsConfig(
        findings_sqlite_path=findings_path,
        normalized_sqlite_path=normalized_path,
        savings_sqlite_path=savings_path,
        poll_interval_seconds=0,
        min_finding_confidence=0.7,
        sla_target_utilization_pct=70.0,
        hours_per_month=730.0,
        fragmentation_capture_fraction=0.5,
        gpu_hourly_rates_json=None,
        savings_estimates_retention_hours=0,
    )

    normalized_storage = NormalizedStorage(normalized_path)
    findings_storage = FindingsStorage(findings_path)
    savings_storage = SavingsStorage(savings_path)

    def _run_cycle():
        raw_reader = RawReader(telemetry_path)
        ingestion_run_once(ingestion_config, raw_reader, normalized_storage)
        raw_reader.close()

        waste_rollup_reader = WasteRollupReader(normalized_path)
        waste_run_once(waste_config, waste_rollup_reader, findings_storage)
        waste_rollup_reader.close()

        findings_reader = FindingsReader(findings_path)
        savings_rollup_reader = SavingsRollupReader(normalized_path)
        savings_run_once(savings_config, findings_reader, savings_rollup_reader, savings_storage)
        findings_reader.close()
        savings_rollup_reader.close()

    _run_cycle()
    _run_cycle()  # identical rerun -- nothing new upstream

    assert findings_storage.count() == 1
    assert savings_storage.count() == 1

    normalized_storage.close()
    findings_storage.close()
    savings_storage.close()


_DCGM_MEMORY_TEXT = """# TYPE DCGM_FI_DEV_GPU_UTIL gauge
DCGM_FI_DEV_GPU_UTIL{{gpu="0",device="nvidia0",modelName="NVIDIA A100-SXM4-80GB",Hostname="gpu-node-1",namespace="inference",pod="bert-large-7d4f-xk2p9",container="model-server"}} {util}
# TYPE DCGM_FI_DEV_FB_USED gauge
DCGM_FI_DEV_FB_USED{{gpu="0",device="nvidia0",modelName="NVIDIA A100-SXM4-80GB",Hostname="gpu-node-1",namespace="inference",pod="bert-large-7d4f-xk2p9",container="model-server"}} {used}
# TYPE DCGM_FI_DEV_FB_FREE gauge
DCGM_FI_DEV_FB_FREE{{gpu="0",device="nvidia0",modelName="NVIDIA A100-SXM4-80GB",Hostname="gpu-node-1",namespace="inference",pod="bert-large-7d4f-xk2p9",container="model-server"}} {free}
"""


def test_right_sizing_respects_peak_gpu_memory_end_to_end(tmp_path):
    # An A100 80GB peaking at 10% busy would be sent to a T4 on compute and
    # bandwidth alone, but it once used 20 GiB of memory (x1.1 = 22 GiB):
    # the T4 can't hold that, so the pipeline must land on an L4 (24 GB).
    telemetry_path = str(tmp_path / "telemetry.db")
    normalized_path = str(tmp_path / "normalized.db")
    findings_path = str(tmp_path / "findings.db")
    savings_path = str(tmp_path / "savings.db")

    telemetry_storage = TelemetryStorage(telemetry_path)
    for hour in range(24):
        used = 20480.0 if hour == 7 else 8192.0
        text = _DCGM_MEMORY_TEXT.format(util=10.0, used=used, free=81920.0 - used)
        telemetry_storage.record_scrape(correlate(parse_metrics(text)), duration_ms=5.0, success=True,
                                        scraped_at=hour * _HOUR)
    telemetry_storage.close()

    normalized_storage = NormalizedStorage(normalized_path)
    raw_reader = RawReader(telemetry_path)
    ingestion_run_once(
        IngestionConfig(raw_sqlite_path=telemetry_path, normalized_sqlite_path=normalized_path,
                        poll_interval_seconds=0, source_scrape_interval_seconds=_HOUR,
                        low_confidence_coverage_threshold=0.5, normalized_samples_retention_hours=0,
                        rollups_retention_hours=0),
        raw_reader, normalized_storage)
    raw_reader.close()
    normalized_storage.close()

    findings_storage = FindingsStorage(findings_path)
    waste_rollup_reader = WasteRollupReader(normalized_path)
    waste_run_once(
        WasteConfig(normalized_sqlite_path=normalized_path, findings_sqlite_path=findings_path,
                    poll_interval_seconds=0, min_coverage_ratio=0.8, idle_threshold_pct=2.0,
                    min_idle_streak_hours=4, over_provision_threshold_pct=30.0,
                    over_provision_min_observation_hours=24, fragmentation_threshold_pct=50.0,
                    fragmentation_min_underutilized_gpus=2, fragmentation_min_streak_hours=4,
                    pattern_min_days_observed=7, pattern_idle_threshold_pct=5.0,
                    pattern_min_consistent_fraction=0.8, findings_retention_hours=0),
        waste_rollup_reader, findings_storage)
    waste_rollup_reader.close()
    findings_storage.close()

    savings_storage = SavingsStorage(savings_path)
    findings_reader = FindingsReader(findings_path)
    savings_rollup_reader = SavingsRollupReader(normalized_path)
    savings_run_once(
        SavingsConfig(findings_sqlite_path=findings_path, normalized_sqlite_path=normalized_path,
                      savings_sqlite_path=savings_path, poll_interval_seconds=0, min_finding_confidence=0.7,
                      sla_target_utilization_pct=70.0, hours_per_month=730.0,
                      fragmentation_capture_fraction=0.5, gpu_hourly_rates_json=None,
                      savings_estimates_retention_hours=0),
        findings_reader, savings_rollup_reader, savings_storage)
    findings_reader.close()
    savings_rollup_reader.close()
    estimates = [e for e in savings_storage.all_estimates() if e["category"] == "over_provisioned"]
    savings_storage.close()

    assert len(estimates) == 1
    assert estimates[0]["recommended_action"].startswith("right-size to NVIDIA L4 (")
    assert "memory fit not checked" not in estimates[0]["recommended_action"]
    assert "peak 20.0 GiB used" in estimates[0]["methodology"]
