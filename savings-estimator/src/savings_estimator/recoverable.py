"""Recoverable ceiling: the most any optimization could save on the observed
GPU fleet without running a GPU busier than the efficient-use target.

Every observed GPU-hour costs its rate; the share of it sitting below the
target (70% by default, the same ceiling right-sizing aims for) is capacity
paid for and not used. Summed over the fleet that gives one number per
cluster: "at most X% of this GPU spend is recoverable". It is a ceiling, not
a forecast -- reaching it would mean packing every workload perfectly, and
hourly averages hide bursts within the hour, so the real figure is lower.
What it is for: telling a customer how much room there is, next to what the
findings actually capture.

GPU-hours are weighted by coverage (a row covering 30 minutes of a GPU is
half a GPU-hour), so a GPU whose pod changed mid-hour is counted once in
total, and missing scrapes are simply not counted rather than read as idle.
MIG slices are excluded: each slice row would be charged the whole GPU's
rate, overstating spend. GPUs with no known model or rate are excluded too,
and reported as excluded rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingestion_normalization.capability import lookup_capability

from savings_estimator.pricing import lookup_price
from savings_estimator.rollup_reader import RollupRow

_BUCKET_SECONDS = 3600.0


@dataclass(frozen=True)
class RecoverableCeiling:
    window_start: float
    window_end: float
    target_utilization_pct: float
    observed_gpu_hours: float
    observed_spend_inr: float
    recoverable_inr: float
    # Observed spend scaled to a month at the observed run rate.
    monthly_spend_inr: float
    # GPU-hours left out: unknown GPU model, no rate, MIG slice, or no
    # utilization reading.
    excluded_gpu_hours: float

    @property
    def fraction(self) -> float:
        return self.recoverable_inr / self.observed_spend_inr if self.observed_spend_inr > 0 else 0.0

    @property
    def monthly_recoverable_inr(self) -> float:
        return self.fraction * self.monthly_spend_inr


def compute_recoverable_ceiling(
    rows: list[RollupRow],
    target_utilization_pct: float,
    hours_per_month: float,
    rate_overrides: dict[str, float],
) -> RecoverableCeiling | None:
    """None when there is no hourly data at all."""
    if not rows or target_utilization_pct <= 0:
        return None

    rates: dict[str | None, float | None] = {}
    gpu_hours = spend = recoverable = excluded = 0.0
    for row in rows:
        weight = max(0.0, min(1.0, row.coverage_ratio))
        if weight == 0.0:
            continue
        if row.gpu_instance_id is not None or row.avg_utilization_pct is None:
            excluded += weight
            continue
        if row.gpu_model not in rates:
            price = lookup_price(lookup_capability(row.gpu_model), rate_overrides)
            rates[row.gpu_model] = price.hourly_inr if price.known else None
        rate = rates[row.gpu_model]
        if rate is None:
            excluded += weight
            continue
        util = max(0.0, min(100.0, row.avg_utilization_pct))
        gpu_hours += weight
        spend += rate * weight
        recoverable += rate * weight * max(0.0, 1.0 - util / target_utilization_pct)

    window_start = min(r.bucket_start for r in rows)
    window_end = max(r.bucket_start for r in rows) + _BUCKET_SECONDS
    wall_hours = (window_end - window_start) / _BUCKET_SECONDS
    return RecoverableCeiling(
        window_start=window_start,
        window_end=window_end,
        target_utilization_pct=target_utilization_pct,
        observed_gpu_hours=gpu_hours,
        observed_spend_inr=spend,
        recoverable_inr=recoverable,
        monthly_spend_inr=spend / wall_hours * hours_per_month if wall_hours > 0 else 0.0,
        excluded_gpu_hours=excluded,
    )
