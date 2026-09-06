"""Environment-driven configuration for the collector.

Every knob a customer might need to change when running this against their
own cluster (endpoints, scrape cadence, storage path) is an env var so the
Helm chart can set it without touching code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    dcgm_exporter_url: str
    kube_state_metrics_url: str
    sqlite_path: str
    scrape_interval_seconds: float
    http_timeout_seconds: float
    max_scrape_retries: int
    # This runs unattended, scraping every ~30s, for weeks at a time (see
    # storage.py's module docstring) -- without a retention window,
    # gpu_metrics/scrape_runs grow without bound and eventually exhaust
    # disk. The default (14 days) must stay generous enough that
    # ingestion-normalization -- which reads this same file by
    # scrape_run_id, not by age -- has always caught up well before data
    # this old is pruned. 0 (or less) disables pruning.
    retention_hours: float = 14 * 24.0

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            dcgm_exporter_url=os.environ.get(
                "DCGM_EXPORTER_URL", "http://dcgm-exporter:9400/metrics"
            ),
            kube_state_metrics_url=os.environ.get(
                "KUBE_STATE_METRICS_URL", "http://kube-state-metrics:8080/metrics"
            ),
            sqlite_path=os.environ.get(
                "TELEMETRY_SQLITE_PATH", "/data/telemetry.db"
            ),
            scrape_interval_seconds=float(
                os.environ.get("SCRAPE_INTERVAL_SECONDS", "30")
            ),
            http_timeout_seconds=float(
                os.environ.get("HTTP_TIMEOUT_SECONDS", "10")
            ),
            max_scrape_retries=int(os.environ.get("MAX_SCRAPE_RETRIES", "3")),
            retention_hours=float(os.environ.get("TELEMETRY_RETENTION_HOURS", str(14 * 24))),
        )
