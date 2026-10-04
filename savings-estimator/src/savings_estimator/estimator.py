"""Per-category rupee impact calculation.

The categories split into two fundamentally different kinds of evidence,
and conflating them would overclaim:

- IDLE findings are a single, already-observed streak. Its own idle
  fraction is 100% by construction (that's what makes it a streak) --
  projecting that rate across a full month would imply the GPU is idle
  ALL the time, which the finding says nothing about outside its own
  window. So idle is priced as money already spent with zero value during
  exactly the observed window: a lower bound on real waste, not a forecast.
- OVER_PROVISIONED, FRAGMENTED, and RECURRING_PATTERN all require a
  minimum sustained observation before they fire at all (24h+, a 4h+
  streak, or many observed calendar days respectively) specifically
  because they're meant to represent a persistent state. Projecting their
  observed rate forward to a monthly figure is the standard, defensible
  basis for a right-sizing ROI calculation -- as long as it's labeled as
  a projection, which every estimate here does via `basis`.
- UNDERUTILIZED and UNATTRIBUTED_GPU_TIME are waste with no reliable
  recommendation. They're priced like idle -- capacity below the
  efficient-use target that was paid for during the observed window, not
  projected -- on BASIS_DETECTED_NO_RECOMMENDATION, which the dashboard
  shows beneath the actionable findings and never adds to a headline.
- MULTI_GPU_OVERSIZED is projected the same way but on its own basis,
  BASIS_VISIBILITY_UPPER_BOUND: it's sized from hourly averages with no
  memory check, so it shows the scale of an opportunity rather than a
  savings figure to stand behind, and the dashboard keeps it out of the
  headline total.
"""
from __future__ import annotations

from ingestion_normalization.capability import lookup_capability

from savings_estimator.ceiling import recommendation_cautions, right_sized_capability
from savings_estimator.config import Config
from savings_estimator.estimate import (
    BASIS_OBSERVED_WINDOW,
    BASIS_PROJECTED_MONTHLY,
    BASIS_DETECTED_NO_RECOMMENDATION,
    BASIS_VISIBILITY_UPPER_BOUND,
    SavingsEstimate,
)
from savings_estimator.findings_reader import FindingRow
from savings_estimator.pricing import lookup_price
from savings_estimator.rollup_reader import RollupRow
from waste_detector.findings import (
    FRAGMENTED,
    IDLE,
    MULTI_GPU_OVERSIZED,
    OVER_PROVISIONED,
    OVERSIZED_BY_AVERAGE,
    RECURRING_PATTERN,
    UNATTRIBUTED_GPU_TIME,
    UNDERUTILIZED,
)

_SECONDS_PER_HOUR = 3600
_DAYS_PER_MONTH = 30.0


def _unpriceable(finding: FindingRow, reason: str) -> SavingsEstimate:
    return SavingsEstimate(
        finding_id=finding.id,
        category=finding.category,
        node=finding.node,
        gpu_index=finding.gpu_index,
        gpu_instance_id=finding.gpu_instance_id,
        namespace=finding.namespace,
        workload=finding.workload,
        window_start=finding.window_start,
        window_end=finding.window_end,
        confidence=finding.confidence,
        priceable=False,
        basis=None,
        amount_inr=None,
        recommended_action="none -- not priceable",
        methodology=reason,
    )


def _avg_utilization(rollup_rows: list[RollupRow]) -> float | None:
    # Weighted by coverage_ratio: an unweighted mean would let a bucket
    # built from a handful of real samples (low coverage, possibly reading
    # near zero because most of the window is simply missing) count the
    # same as one built from a full window of trustworthy samples --
    # silently undermining the confidence-scoring this estimate is
    # supposed to reflect.
    weighted = [
        (r.avg_utilization_pct, r.coverage_ratio)
        for r in rollup_rows
        if r.avg_utilization_pct is not None and r.coverage_ratio > 0
    ]
    if not weighted:
        return None
    total_weight = sum(weight for _, weight in weighted)
    return sum(value * weight for value, weight in weighted) / total_weight


def estimate_for_finding(
    finding: FindingRow,
    rollup_rows: list[RollupRow],
    config: Config,
    rate_overrides: dict[str, float],
) -> SavingsEstimate:
    if not rollup_rows:
        return _unpriceable(finding, "no matching rollup data found for this finding's window")

    gpu_model = next((r.gpu_model for r in rollup_rows if r.gpu_model), None)
    capability = lookup_capability(gpu_model)
    price = lookup_price(capability, rate_overrides)

    if not capability.known:
        return _unpriceable(finding, f"unrecognized GPU model {gpu_model!r} -- no capability data")
    if not price.known:
        return _unpriceable(finding, f"no ₹/hour rate available for {capability.canonical_name!r}")

    if finding.category == IDLE:
        return _estimate_idle(finding, price)
    if finding.category == OVER_PROVISIONED:
        return _estimate_over_provisioned(finding, capability, price, config, rate_overrides,
                                          rollup_rows=rollup_rows)
    if finding.category == OVERSIZED_BY_AVERAGE:
        return _estimate_over_provisioned(
            finding, capability, price, config, rate_overrides,
            rollup_rows=rollup_rows,
            target_pct=config.avg_load_target_utilization_pct,
            load_basis="busiest-hour average utilization (bursts within an hour aren't visible, "
                       "hence the stricter target)",
        )
    if finding.category == FRAGMENTED:
        return _estimate_fragmented(finding, rollup_rows, price, config)
    if finding.category == RECURRING_PATTERN:
        return _estimate_recurring_pattern(finding, price, config)
    if finding.category == MULTI_GPU_OVERSIZED:
        return _estimate_multi_gpu_oversized(finding, price, config)
    if finding.category in (UNDERUTILIZED, UNATTRIBUTED_GPU_TIME):
        return _estimate_unrecommended(finding, price)

    return _unpriceable(finding, f"unknown finding category {finding.category!r}")


def _base_kwargs(finding: FindingRow) -> dict:
    return dict(
        finding_id=finding.id,
        category=finding.category,
        node=finding.node,
        gpu_index=finding.gpu_index,
        gpu_instance_id=finding.gpu_instance_id,
        namespace=finding.namespace,
        workload=finding.workload,
        window_start=finding.window_start,
        window_end=finding.window_end,
        confidence=finding.confidence,
        priceable=True,
    )


def _estimate_idle(finding: FindingRow, price) -> SavingsEstimate:
    window_hours = (finding.window_end - finding.window_start) / _SECONDS_PER_HOUR
    if window_hours < 0:
        # A corrupted or clock-skewed upstream finding (window_end before
        # window_start) must not silently produce a negative rupee figure
        # -- admit we can't price this rather than show a customer a
        # nonsensical "negative savings" number.
        return _unpriceable(finding, "finding window is invalid (window_end precedes window_start)")
    amount = price.hourly_inr * window_hours
    return SavingsEstimate(
        **_base_kwargs(finding),
        basis=BASIS_OBSERVED_WINDOW,
        amount_inr=amount,
        recommended_action="terminate or reclaim this idle GPU allocation",
        methodology=(
            f"{window_hours:.1f}h idle at ₹{price.hourly_inr:.2f}/hr "
            f"({price.source}) -- already-incurred cost for this observed window only, not projected"
        ),
    )


def _memory_evidence(rollup_rows: list[RollupRow]) -> tuple[float | None, float | None]:
    """(peak memory used, GPU usable memory) in MiB across the finding's
    window. The peak only counts when every row carries one: a window that
    mixes in pre-upgrade rows (NULL) could hide a bigger peak, and an
    understated peak is exactly the error that causes an OOM."""
    peaks = [r.max_memory_used_mb for r in rollup_rows]
    if not peaks or any(p is None for p in peaks):
        return None, None
    totals = [r.memory_total_mb for r in rollup_rows if r.memory_total_mb is not None]
    return max(peaks), (max(totals) if totals else None)


def _estimate_over_provisioned(
    finding: FindingRow, capability, price, config: Config, rate_overrides: dict[str, float],
    target_pct: float | None = None, load_basis: str = "peak utilization",
    rollup_rows: list[RollupRow] | None = None,
) -> SavingsEstimate:
    # Shared by OVER_PROVISIONED (metric_value = peak utilization %, sized
    # to the SLA target) and OVERSIZED_BY_AVERAGE (metric_value = busiest
    # hour's average utilization %, sized to a stricter target).
    target_pct = config.sla_target_utilization_pct if target_pct is None else target_pct
    if finding.gpu_instance_id is not None:
        # capability.fp16_tflops here is the *physical* GPU's full capacity
        # (capability is re-derived from gpu_model alone, upstream of any
        # MIG awareness), but finding.metric_value -- the observed peak
        # utilization -- is relative to this MIG slice, not the whole GPU.
        # DCGM carries no MIG profile/fraction label to translate between
        # the two, so sizing a recommendation from full-GPU TFLOPS against
        # slice-relative utilization mixes two different bases and can
        # recommend a "smaller" SKU that's actually bigger than the slice
        # already is. Same "admit unknown" choice as ingestion-normalization
        # makes for MIG effective_tflops, rather than a misleading number.
        return _unpriceable(
            finding,
            "right-sizing needs this workload's share of the physical GPU's capacity, but MIG "
            "slice sizing data isn't available -- computing it against the full GPU's TFLOPS "
            "would misprice the recommendation",
        )

    peak_mem, total_mem = _memory_evidence(rollup_rows or [])
    rec = right_sized_capability(
        capability.fp16_tflops, finding.metric_value, target_pct,
        current_mem_bandwidth_gbps=capability.mem_bandwidth_gbps,
        current_mem_capacity_gb=capability.mem_capacity_gb,
        peak_memory_used_mib=peak_mem,
        current_memory_total_mib=total_mem,
    )

    if rec.recommended is None:
        return SavingsEstimate(
            **_base_kwargs(finding),
            basis=BASIS_PROJECTED_MONTHLY,
            amount_inr=0.0,
            recommended_action="none -- no smaller known SKU meets the SLA ceiling",
            methodology=rec.detail,
        )

    recommended_price = lookup_price(rec.recommended, rate_overrides)
    if not recommended_price.known:
        return _unpriceable(
            finding,
            f"right-sizing recommends {rec.recommended.canonical_name!r} but it has no known ₹/hour rate",
        )

    monthly_savings = max(0.0, (price.hourly_inr - recommended_price.hourly_inr) * config.hours_per_month)
    return SavingsEstimate(
        **_base_kwargs(finding),
        basis=BASIS_PROJECTED_MONTHLY,
        amount_inr=monthly_savings,
        recommended_action=(
            f"right-size to {rec.recommended.canonical_name} ({recommendation_cautions(rec)})"
        ),
        methodology=(
            f"sized on {load_basis} {finding.metric_value:.1f}%: {rec.detail}; "
            f"₹{price.hourly_inr:.2f}/hr -> ₹{recommended_price.hourly_inr:.2f}/hr, "
            f"projected over {config.hours_per_month:.0f}h/month if this profile continues"
        ),
    )


def _estimate_fragmented(finding: FindingRow, rollup_rows: list[RollupRow], price, config: Config) -> SavingsEstimate:
    avg_util = _avg_utilization(rollup_rows)
    if avg_util is None:
        return _unpriceable(finding, "no utilization data available to size fragmentation waste")

    wasted_fraction = max(0.0, 1 - avg_util / 100.0) * config.fragmentation_capture_fraction
    monthly_savings = price.hourly_inr * wasted_fraction * config.hours_per_month

    return SavingsEstimate(
        **_base_kwargs(finding),
        basis=BASIS_PROJECTED_MONTHLY,
        amount_inr=monthly_savings,
        recommended_action=(
            "review whether this workload can share a GPU with the other underutilized workloads "
            "on this node (needs GPU sharing via time-slicing, MPS, or MIG; memory fit not checked)"
        ),
        methodology=(
            f"avg utilization {avg_util:.1f}% -> {wasted_fraction * 100:.0f}% of capacity reclaimable "
            f"(discounted to {config.fragmentation_capture_fraction:.0%} of theoretical, since real "
            f"consolidation needs migration work), projected over {config.hours_per_month:.0f}h/month; "
            f"an upper-bound estimate for a consolidation candidate -- GPU memory fit, combined "
            f"compute, and cluster GPU-sharing support were not verified, so the real figure may be "
            f"lower, including zero"
        ),
    )


def _estimate_recurring_pattern(finding: FindingRow, price, config: Config) -> SavingsEstimate:
    # metric_value for this category IS the consistent_fraction (see
    # waste_detector.patterns): the share of observed days this hour-of-day
    # slot ran low, so it must be a fraction in [0, 1]. A corrupted upstream
    # finding with a value outside that range would otherwise inflate (or
    # invert) the monthly projection without limit -- admit we can't price
    # it rather than show a wrong number.
    if not (0.0 <= finding.metric_value <= 1.0):
        return _unpriceable(finding, f"metric_value {finding.metric_value!r} is not a valid fraction in [0, 1]")

    monthly_wasted_hours = finding.metric_value * _DAYS_PER_MONTH
    monthly_savings = price.hourly_inr * monthly_wasted_hours

    return SavingsEstimate(
        **_base_kwargs(finding),
        basis=BASIS_PROJECTED_MONTHLY,
        amount_inr=monthly_savings,
        recommended_action="scale down or scale to zero during this recurring low-usage window",
        methodology=(
            f"{finding.metric_value:.0%} of observed days quiet at this hour -> "
            f"~{monthly_wasted_hours:.1f}h/month at ₹{price.hourly_inr:.2f}/hr, "
            f"projected if the pattern continues"
        ),
    )


def _estimate_multi_gpu_oversized(finding: FindingRow, price, config: Config) -> SavingsEstimate:
    # metric_value for this category IS the fraction of the job's GPUs that
    # could be released (see waste_detector.multi_gpu). Every GPU of the job
    # gets its own finding, so pricing each at that fraction of its own
    # cost sums to the releasable GPUs' cost across the job.
    if not (0.0 < finding.metric_value < 1.0):
        return _unpriceable(finding, f"metric_value {finding.metric_value!r} is not a valid fraction in (0, 1)")

    monthly = price.hourly_inr * finding.metric_value * config.multi_gpu_capture_fraction * config.hours_per_month
    return SavingsEstimate(
        **_base_kwargs(finding),
        basis=BASIS_VISIBILITY_UPPER_BOUND,
        amount_inr=monthly,
        recommended_action=(
            "review whether this multi-GPU job can run on fewer GPUs (check memory fit, batch size and "
            "run time; for training, a data-loading or communication bottleneck may be the cheaper fix)"
        ),
        methodology=(
            f"{finding.metric_value:.0%} of the job's GPUs releasable on hourly-average busy time, "
            f"discounted to {config.multi_gpu_capture_fraction:.0%} since shrinking a job's GPU count "
            f"takes engineering work; ₹{price.hourly_inr:.2f}/hr ({price.source}) projected over "
            f"{config.hours_per_month:.0f}h/month. Upper bound for visibility, not included in the "
            f"headline total: bursts above the hourly average and GPU memory fit were not checked"
        ),
    )


def _estimate_unrecommended(finding: FindingRow, price) -> SavingsEstimate:
    # metric_value for these categories IS the average shortfall below the
    # efficient-use target as a fraction of the GPU (see
    # waste_detector.unrecommended), so the unused capacity's cost over the
    # observed window is rate x fraction x hours.
    window_hours = (finding.window_end - finding.window_start) / _SECONDS_PER_HOUR
    if window_hours < 0:
        return _unpriceable(finding, "finding window is invalid (window_end precedes window_start)")
    if not (0.0 < finding.metric_value <= 1.0):
        return _unpriceable(finding, f"metric_value {finding.metric_value!r} is not a valid fraction in (0, 1]")

    amount = price.hourly_inr * finding.metric_value * window_hours
    return SavingsEstimate(
        **_base_kwargs(finding),
        basis=BASIS_DETECTED_NO_RECOMMENDATION,
        amount_inr=amount,
        recommended_action="none yet -- detected waste without a reliable recommendation; review manually",
        methodology=(
            f"{finding.metric_value:.0%} of the GPU below the efficient-use target over {window_hours:.1f}h "
            f"at ₹{price.hourly_inr:.2f}/hr ({price.source}) -- cost of unused capacity already incurred in "
            f"this observed window, not projected; shown below actionable findings, not in the headline"
        ),
    )
