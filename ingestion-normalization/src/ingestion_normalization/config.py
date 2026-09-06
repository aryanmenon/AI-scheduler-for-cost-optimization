from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    raw_sqlite_path: str
    normalized_sqlite_path: str
    poll_interval_seconds: float
    # Must match the telemetry-collector's scrape interval -- it's how
    # rollups compute how many samples a bucket *should* contain in order
    # to report coverage_ratio honestly. A mismatch here doesn't crash
    # anything; it just makes every bucket look falsely under- or
    # over-covered, so treat it as a value to keep in sync with the
    # collector's own SCRAPE_INTERVAL_SECONDS, not a free variable.
    source_scrape_interval_seconds: float
    low_confidence_coverage_threshold: float
    # A daily bucket accumulates samples across the whole day, so fully
    # recomputing it (see pipeline.py's module docstring on why full
    # recompute, not incremental update) means every ingestion cycle
    # re-scans an ever-larger fraction of that day's data -- total work
    # across a day grows quadratically with cycle count. 5m/hourly buckets
    # don't have this problem (their window size caps the rescan cost
    # regardless of how long the bucket has been accumulating), so only
    # daily recompute is throttled to at most once per this interval. 0
    # disables throttling (recompute daily every cycle, like before).
    daily_rollup_min_recompute_interval_seconds: float = 3600.0
    # normalized_samples is per-scrape raw data, superseded by rollups
    # almost immediately -- kept only long enough to support the daily
    # rollup recompute above, which rescans a full day's worth of it. Must
    # stay well above 24h or a late daily recompute could rescan a window
    # whose raw samples have already been pruned. 0 disables pruning.
    normalized_samples_retention_hours: float = 72.0
    # rollups are the durable historical record: waste-detector's
    # recurring-pattern detector wants many observed calendar days, and
    # the dashboard's report draws on this history too. Kept far longer
    # than the raw samples above. 0 disables pruning.
    rollups_retention_hours: float = 2160.0  # 90 days
    # Touched with the current time at the end of every run_forever
    # iteration, success or failure -- run_once's own exceptions are caught
    # and logged (see main.py) so the process itself never crashes on a bad
    # cycle, which means a plain "is the process alive" liveness check
    # can't catch a genuinely stuck loop. A Kubernetes exec probe checking
    # this file's mtime can. Defaults next to normalized_sqlite_path (this
    # component's own write target) so it lands on that writable volume
    # without needing its own mount.
    heartbeat_path: str = "/data/normalized/.heartbeat"
    # A Slack-compatible incoming webhook URL to POST a human-visible
    # alert to once a chronic failure is detected -- a structured log line
    # only reaches someone already looking. Unset (the default) disables
    # alerting entirely.
    alert_webhook_url: str | None = None
    # How many *consecutive* failed cycles trigger an alert. Edge-
    # triggered (fires once on crossing this, once again on recovery), not
    # on every cycle past it -- one transient blip shouldn't page anyone.
    alert_consecutive_failure_threshold: int = 3

    @classmethod
    def from_env(cls) -> "Config":
        normalized_sqlite_path = os.environ.get(
            "NORMALIZED_SQLITE_PATH", "/data/normalized/normalized.db"
        )
        return cls(
            raw_sqlite_path=os.environ.get(
                "RAW_TELEMETRY_SQLITE_PATH", "/data/raw/telemetry.db"
            ),
            normalized_sqlite_path=normalized_sqlite_path,
            poll_interval_seconds=float(
                os.environ.get("INGESTION_POLL_INTERVAL_SECONDS", "60")
            ),
            source_scrape_interval_seconds=float(
                os.environ.get("SOURCE_SCRAPE_INTERVAL_SECONDS", "30")
            ),
            low_confidence_coverage_threshold=float(
                os.environ.get("LOW_CONFIDENCE_COVERAGE_THRESHOLD", "0.5")
            ),
            daily_rollup_min_recompute_interval_seconds=float(
                os.environ.get("DAILY_ROLLUP_MIN_RECOMPUTE_INTERVAL_SECONDS", "3600")
            ),
            normalized_samples_retention_hours=float(
                os.environ.get("NORMALIZED_SAMPLES_RETENTION_HOURS", "72")
            ),
            rollups_retention_hours=float(
                os.environ.get("ROLLUPS_RETENTION_HOURS", "2160")
            ),
            heartbeat_path=os.environ.get(
                "HEARTBEAT_PATH",
                os.path.join(os.path.dirname(normalized_sqlite_path) or ".", ".heartbeat"),
            ),
            alert_webhook_url=os.environ.get("ALERT_WEBHOOK_URL") or None,
            alert_consecutive_failure_threshold=int(
                os.environ.get("ALERT_CONSECUTIVE_FAILURE_THRESHOLD", "3")
            ),
        )
