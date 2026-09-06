from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    findings_sqlite_path: str
    normalized_sqlite_path: str
    savings_sqlite_path: str
    poll_interval_seconds: float

    # A finding below this confidence isn't priced at all -- an estimate
    # built on shaky evidence is worse than no estimate, per the same
    # false-positive-cost principle the detector itself applies.
    min_finding_confidence: float

    # The utilization ceiling a right-sized allocation should aim for:
    # low enough to leave headroom for latency/traffic spikes (the "SLA"
    # in "SLA-aware"), high enough to actually capture savings. This is a
    # starting default, not a validated number -- real SLA requirements
    # vary per workload.
    sla_target_utilization_pct: float

    # Standard cloud-billing convention (~365*24/12) for projecting an
    # hourly rate to a monthly figure.
    hours_per_month: float

    # Fragmentation's underutilized capacity isn't fully reclaimable
    # without real bin-packing/migration work -- this discounts the naive
    # "sum of idle capacity" figure to a more conservative, defensible one.
    fragmentation_capture_fraction: float

    # JSON object mapping a GPU capability's canonical_name (see
    # ingestion_normalization.capability) to a ₹/hour rate. Overrides the
    # illustrative defaults in pricing.py -- always prefer a customer's
    # actual contracted rate over the Indian GPU-cloud on-demand list-price
    # approximations shipped as fallbacks.
    gpu_hourly_rates_json: str | None

    # savings_estimates has no natural cap: every cycle re-prices all
    # findings currently in waste-detector's database, and a resolved
    # finding's estimate just stops being refreshed rather than being
    # deleted. Kept as long as the dashboard might reasonably want
    # historical estimates for. 0 disables pruning.
    savings_estimates_retention_hours: float = 2160.0  # 90 days

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            findings_sqlite_path=os.environ.get(
                "FINDINGS_SQLITE_PATH", "/data/findings/findings.db"
            ),
            normalized_sqlite_path=os.environ.get(
                "NORMALIZED_SQLITE_PATH", "/data/normalized/normalized.db"
            ),
            savings_sqlite_path=os.environ.get(
                "SAVINGS_SQLITE_PATH", "/data/savings/savings.db"
            ),
            poll_interval_seconds=float(os.environ.get("ESTIMATOR_POLL_INTERVAL_SECONDS", "300")),
            min_finding_confidence=float(os.environ.get("MIN_FINDING_CONFIDENCE", "0.7")),
            sla_target_utilization_pct=float(
                os.environ.get("SLA_TARGET_UTILIZATION_PCT", "70.0")
            ),
            hours_per_month=float(os.environ.get("HOURS_PER_MONTH", "730.0")),
            fragmentation_capture_fraction=float(
                os.environ.get("FRAGMENTATION_CAPTURE_FRACTION", "0.5")
            ),
            gpu_hourly_rates_json=os.environ.get("GPU_HOURLY_RATES_JSON"),
            savings_estimates_retention_hours=float(
                os.environ.get("SAVINGS_ESTIMATES_RETENTION_HOURS", "2160")
            ),
        )
