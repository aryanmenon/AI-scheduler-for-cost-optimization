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
        )
