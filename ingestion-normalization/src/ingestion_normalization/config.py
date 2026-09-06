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

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            raw_sqlite_path=os.environ.get(
                "RAW_TELEMETRY_SQLITE_PATH", "/data/raw/telemetry.db"
            ),
            normalized_sqlite_path=os.environ.get(
                "NORMALIZED_SQLITE_PATH", "/data/normalized/normalized.db"
            ),
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
        )
