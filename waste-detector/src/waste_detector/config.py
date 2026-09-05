from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    normalized_sqlite_path: str
    findings_sqlite_path: str
    poll_interval_seconds: float

    # Shared confidence gate: a rollup bucket below this coverage_ratio is
    # excluded from every detector -- a bad recommendation built on
    # incomplete data costs more customer trust than a missed one.
    min_coverage_ratio: float

    # Idle detection (streak-based, tuned for bursty inference traffic).
    idle_threshold_pct: float
    min_idle_streak_hours: int

    # Over-provisioning (single-snapshot peak comparison).
    over_provision_threshold_pct: float
    over_provision_min_observation_hours: int

    # Fragmentation.
    fragmentation_threshold_pct: float
    fragmentation_min_underutilized_gpus: int
    fragmentation_min_streak_hours: int

    # Daily/weekly recurring pattern detection.
    pattern_min_days_observed: int
    pattern_idle_threshold_pct: float
    pattern_min_consistent_fraction: float

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            normalized_sqlite_path=os.environ.get(
                "NORMALIZED_SQLITE_PATH", "/data/normalized/normalized.db"
            ),
            findings_sqlite_path=os.environ.get(
                "FINDINGS_SQLITE_PATH", "/data/findings/findings.db"
            ),
            poll_interval_seconds=float(os.environ.get("DETECTOR_POLL_INTERVAL_SECONDS", "300")),
            min_coverage_ratio=float(os.environ.get("MIN_COVERAGE_RATIO", "0.8")),
            idle_threshold_pct=float(os.environ.get("IDLE_THRESHOLD_PCT", "2.0")),
            min_idle_streak_hours=int(os.environ.get("MIN_IDLE_STREAK_HOURS", "4")),
            over_provision_threshold_pct=float(
                os.environ.get("OVER_PROVISION_THRESHOLD_PCT", "30.0")
            ),
            over_provision_min_observation_hours=int(
                os.environ.get("OVER_PROVISION_MIN_OBSERVATION_HOURS", "24")
            ),
            fragmentation_threshold_pct=float(
                os.environ.get("FRAGMENTATION_THRESHOLD_PCT", "50.0")
            ),
            fragmentation_min_underutilized_gpus=int(
                os.environ.get("FRAGMENTATION_MIN_UNDERUTILIZED_GPUS", "2")
            ),
            fragmentation_min_streak_hours=int(
                os.environ.get("FRAGMENTATION_MIN_STREAK_HOURS", "4")
            ),
            pattern_min_days_observed=int(os.environ.get("PATTERN_MIN_DAYS_OBSERVED", "7")),
            pattern_idle_threshold_pct=float(
                os.environ.get("PATTERN_IDLE_THRESHOLD_PCT", "5.0")
            ),
            pattern_min_consistent_fraction=float(
                os.environ.get("PATTERN_MIN_CONSISTENT_FRACTION", "0.8")
            ),
        )
