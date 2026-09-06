"""The scrape -> correlate -> store loop.

kube-state-metrics is scraped alongside DCGM for future ingestion-layer use
(node/pod metadata, GPU resource requests) but a KSM failure must never
block storing the DCGM GPU metrics that did succeed -- utilization/power
data is the product's core value and shouldn't be held hostage by a
secondary source.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

from telemetry_collector.config import Config
from telemetry_collector.correlator import correlate
from telemetry_collector.metrics_client import ScrapeError, scrape
from telemetry_collector.storage import Storage

logger = logging.getLogger(__name__)


def _log_cycle(duration_ms: float, rows_in: int, rows_out: int, errors: int, **extra) -> None:
    """One structured summary line per cycle, same core schema across all
    five services (component/event/duration_ms/rows_in/rows_out/errors) so
    an operator can query cycle health without reading source code to
    learn what each service's ad-hoc log message meant.
    """
    payload = {
        "event": "cycle_complete",
        "component": "telemetry-collector",
        "duration_ms": round(duration_ms, 1),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "errors": errors,
        **extra,
    }
    logger.info(json.dumps(payload))


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
        run_id = storage.record_scrape([], duration_ms, success=False, error=str(exc))
        _prune(config, storage)
        _log_cycle(duration_ms, rows_in=0, rows_out=0, errors=1)
        return run_id

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
    run_id = storage.record_scrape(records, duration_ms, success=True, error=error)
    _prune(config, storage)
    _log_cycle(
        duration_ms,
        rows_in=len(dcgm_samples),
        rows_out=len(records),
        errors=1 if error else 0,
        attributed=attributed,
        unattributed=len(records) - attributed,
    )
    return run_id


def _write_heartbeat(path: str) -> None:
    try:
        with open(path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        logger.warning("failed to write heartbeat file %s", path)


def _send_alert(webhook_url: str | None, message: str) -> None:
    """Best-effort POST to a Slack-compatible incoming webhook (a plain
    {"text": ...} JSON body). A structured log line only reaches someone
    who's already looking; this is for the case where nobody is. Alerting
    must never be allowed to take down the pipeline it's watching, so any
    failure here is logged and swallowed, never raised. Stdlib-only
    (urllib, not requests) so services with no runtime dependencies don't
    gain one just for this.
    """
    if not webhook_url:
        return
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"text": message}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        logger.warning("failed to send alert webhook", exc_info=True)


def _prune(config: Config, storage: Storage) -> None:
    if config.retention_hours <= 0:
        return
    cutoff = time.time() - config.retention_hours * 3600
    deleted = storage.prune_older_than(cutoff)
    if deleted:
        logger.info("pruned %d gpu_metrics rows older than %.1fh", deleted, config.retention_hours)


def run_forever(config: Config, storage: Storage, stop_after: int | None = None) -> None:
    """Loop run_once at config.scrape_interval_seconds.

    stop_after bounds the number of cycles for tests; production callers
    leave it None and rely on the process being terminated by Kubernetes.
    """
    cycles = 0
    consecutive_failures = 0
    while stop_after is None or cycles < stop_after:
        cycle_start = time.monotonic()
        try:
            run_once(config, storage)
        except Exception:
            logger.exception("unexpected error during scrape cycle; will retry next interval")
            consecutive_failures += 1
            # Edge-triggered, not level-triggered: fires once on crossing
            # the threshold, not on every cycle after -- a structured log
            # line already exists per cycle for anyone polling; this is
            # for getting a human's attention once, not paging them
            # every interval for the same ongoing problem.
            if consecutive_failures == config.alert_consecutive_failure_threshold:
                _send_alert(
                    config.alert_webhook_url,
                    f"[gpu-cost-optimizer] telemetry-collector: "
                    f"{consecutive_failures} consecutive failed scrape cycles -- investigate.",
                )
        else:
            if consecutive_failures >= config.alert_consecutive_failure_threshold:
                _send_alert(
                    config.alert_webhook_url,
                    f"[gpu-cost-optimizer] telemetry-collector: "
                    f"recovered after {consecutive_failures} consecutive failed cycles.",
                )
            consecutive_failures = 0
        finally:
            # Written whether or not the cycle above succeeded -- this
            # proves the loop itself is iterating, not that scrapes are
            # succeeding (that's what the cycle_complete log's "errors"
            # field is for).
            _write_heartbeat(config.heartbeat_path)

        cycles += 1
        if stop_after is not None and cycles >= stop_after:
            break

        elapsed = time.monotonic() - cycle_start
        time.sleep(max(0.0, config.scrape_interval_seconds - elapsed))
