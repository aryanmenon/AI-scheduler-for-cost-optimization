"""The scrape -> correlate -> store loop.

kube-state-metrics is scraped alongside DCGM for future ingestion-layer use
(node/pod metadata, GPU resource requests) but a KSM failure must never
block storing the DCGM GPU metrics that did succeed -- utilization/power
data is the product's core value and shouldn't be held hostage by a
secondary source.
"""
from __future__ import annotations

import logging
import time

from telemetry_collector.config import Config
from telemetry_collector.correlator import correlate
from telemetry_collector.metrics_client import ScrapeError, scrape
from telemetry_collector.storage import Storage

logger = logging.getLogger(__name__)


def run_once(config: Config, storage: Storage) -> int:
    """Run a single scrape cycle. Returns the scrape_run id."""
    start = time.monotonic()
    error: str | None = None

    try:
        dcgm_samples = scrape(
            config.dcgm_exporter_url,
            timeout=config.http_timeout_seconds,
            max_retries=config.max_scrape_retries,
        )
    except ScrapeError as exc:
        logger.error("DCGM scrape failed: %s", exc)
        duration_ms = (time.monotonic() - start) * 1000
        return storage.record_scrape([], duration_ms, success=False, error=str(exc))

    try:
        scrape(
            config.kube_state_metrics_url,
            timeout=config.http_timeout_seconds,
            max_retries=config.max_scrape_retries,
        )
    except ScrapeError as exc:
        # Non-fatal: DCGM data is still stored below.
        logger.warning("kube-state-metrics scrape failed (continuing): %s", exc)
        error = f"kube-state-metrics unavailable: {exc}"

    records = correlate(dcgm_samples)
    duration_ms = (time.monotonic() - start) * 1000

    attributed = sum(1 for r in records if r.attributed)
    logger.info(
        "scraped %d GPUs (%d attributed, %d unattributed) in %.1fms",
        len(records), attributed, len(records) - attributed, duration_ms,
    )

    return storage.record_scrape(records, duration_ms, success=True, error=error)


def run_forever(config: Config, storage: Storage, stop_after: int | None = None) -> None:
    """Loop run_once at config.scrape_interval_seconds.

    stop_after bounds the number of cycles for tests; production callers
    leave it None and rely on the process being terminated by Kubernetes.
    """
    cycles = 0
    while stop_after is None or cycles < stop_after:
        cycle_start = time.monotonic()
        try:
            run_once(config, storage)
        except Exception:
            logger.exception("unexpected error during scrape cycle; will retry next interval")

        cycles += 1
        if stop_after is not None and cycles >= stop_after:
            break

        elapsed = time.monotonic() - cycle_start
        time.sleep(max(0.0, config.scrape_interval_seconds - elapsed))
