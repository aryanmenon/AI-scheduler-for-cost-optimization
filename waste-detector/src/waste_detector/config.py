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

    # waste_findings has no natural cap: every cycle re-derives the full
    # findings set from all rollup history (see pipeline.py), and a
    # resolved condition's last finding just stops being refreshed rather
    # than being deleted -- so old, no-longer-active findings accumulate
    # forever without this. Kept as long as savings-estimator/dashboard
    # might reasonably want historical findings for. 0 disables pruning.
    findings_retention_hours: float = 2160.0  # 90 days
    # Touched with the current time at the end of every run_forever
    # iteration, success or failure -- run_once's own exceptions are caught
    # and logged (see main.py) so the process itself never crashes on a bad
    # cycle, which means a plain "is the process alive" liveness check
    # can't catch a genuinely stuck loop. A Kubernetes exec probe checking
    # this file's mtime can. Defaults next to findings_sqlite_path (this
    # component's own write target) so it lands on that writable volume
    # without needing its own mount.
    heartbeat_path: str = "/data/findings/.heartbeat"
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
        findings_sqlite_path = os.environ.get(
            "FINDINGS_SQLITE_PATH", "/data/findings/findings.db"
        )
        return cls(
            normalized_sqlite_path=os.environ.get(
                "NORMALIZED_SQLITE_PATH", "/data/normalized/normalized.db"
            ),
            findings_sqlite_path=findings_sqlite_path,
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
            findings_retention_hours=float(
                os.environ.get("FINDINGS_RETENTION_HOURS", "2160")
            ),
            heartbeat_path=os.environ.get(
                "HEARTBEAT_PATH",
                os.path.join(os.path.dirname(findings_sqlite_path) or ".", ".heartbeat"),
            ),
            alert_webhook_url=os.environ.get("ALERT_WEBHOOK_URL") or None,
            alert_consecutive_failure_threshold=int(
                os.environ.get("ALERT_CONSECUTIVE_FAILURE_THRESHOLD", "3")
            ),
        )
