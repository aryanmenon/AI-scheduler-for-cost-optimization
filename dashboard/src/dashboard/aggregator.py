"""Turn raw savings-estimate rows into the numbers a report actually shows.

The observed/projected split from savings-estimator (see its estimator.py)
is preserved here rather than collapsed into one number: an idle finding's
already-spent rupees and a right-sizing recommendation's projected
monthly savings are different units of claim, and adding them together
would produce a figure that overstates both -- a sales report that can't
be defended line-by-line to a skeptical customer champion isn't worth
having.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from dashboard.report_reader import EstimateRow

BASIS_OBSERVED_WINDOW = "observed_window"
BASIS_PROJECTED_MONTHLY = "projected_monthly"
# Visibility-only upper bounds (multi-GPU jobs that may need fewer GPUs):
# shown as their own figure, never added to the headline projection.
BASIS_VISIBILITY_UPPER_BOUND = "visibility_upper_bound"
# Detected waste with no reliable recommendation (underutilized GPU time,
# GPU time with no pod): observed cost, shown below the actionable
# findings, never added to a headline total.
BASIS_DETECTED_NO_RECOMMENDATION = "detected_no_recommendation"

# Sort order for the top-findings table: actionable first, then the
# visibility upper bound, then waste with no recommendation at all.
_TIER_RANK = {BASIS_VISIBILITY_UPPER_BOUND: 1, BASIS_DETECTED_NO_RECOMMENDATION: 2}


@dataclass
class CategorySummary:
    category: str
    count: int
    total_inr: float
    avg_confidence: float
    basis: str | None


@dataclass
class ReportSummary:
    generated_at: float
    total_estimates: int
    priceable_count: int
    unpriceable_count: int
    projected_monthly_total_inr: float
    observed_window_total_inr: float
    by_category: list[CategorySummary]
    top_findings: list[EstimateRow]
    unpriceable_samples: list[EstimateRow]
    # GPUs whose projected savings appear in more than one estimate (e.g.
    # flagged both over-provisioned and fragmented, or fragmented in two
    # separate streaks). The headline counts each such GPU once; the
    # by-category totals don't, so they can add up to more than it.
    projected_gpus_with_overlapping_estimates: int = 0
    # Kept separate from projected_monthly_total_inr on purpose: an upper
    # bound sized from hourly averages with no memory check, not a savings
    # figure to stand behind. Counted once per GPU like the headline.
    visibility_upper_bound_total_inr: float = 0.0
    # Observed cost of GPU time below the efficient-use target that no
    # actionable finding explains. Its hours never overlap an actionable or
    # multi-GPU finding's (the detector excludes them), so it's a plain sum.
    detected_no_recommendation_total_inr: float = 0.0


def _total_counting_each_gpu_once(priceable: list[EstimateRow], basis: str) -> tuple[float, int]:
    """Projected-monthly recommendations for the same physical GPU are
    alternatives, not additive: you can right-size a GPU or consolidate it
    away, not both, and two findings for the same GPU project the same
    month of its cost twice. Summing them overstated the headline. Take
    each GPU's largest projected estimate instead -- what the single best
    action on it could save.

    Observed-window (idle) amounts are left summed: they're cost already
    incurred during distinct observed windows, which genuinely add up.
    """
    best_by_gpu: dict[tuple, float] = {}
    estimates_per_gpu: dict[tuple, int] = defaultdict(int)
    for r in priceable:
        if r.basis != basis or r.amount_inr is None:
            continue
        key = (r.node, r.gpu_index, r.gpu_instance_id)
        estimates_per_gpu[key] += 1
        best_by_gpu[key] = max(best_by_gpu.get(key, 0.0), r.amount_inr)
    overlapping = sum(1 for n in estimates_per_gpu.values() if n > 1)
    return sum(best_by_gpu.values()), overlapping


def aggregate(rows: list[EstimateRow], top_n: int, generated_at: float | None = None) -> ReportSummary:
    generated_at = generated_at if generated_at is not None else time.time()

    priceable = [r for r in rows if r.priceable]
    unpriceable = [r for r in rows if not r.priceable]

    projected_total, overlapping_gpus = _total_counting_each_gpu_once(priceable, BASIS_PROJECTED_MONTHLY)
    visibility_total, _ = _total_counting_each_gpu_once(priceable, BASIS_VISIBILITY_UPPER_BOUND)
    no_recommendation_total = sum(
        r.amount_inr for r in priceable
        if r.basis == BASIS_DETECTED_NO_RECOMMENDATION and r.amount_inr is not None
    )
    observed_total = sum(
        r.amount_inr for r in priceable if r.basis == BASIS_OBSERVED_WINDOW and r.amount_inr is not None
    )

    by_category_rows: dict[str, list[EstimateRow]] = defaultdict(list)
    for r in priceable:
        by_category_rows[r.category].append(r)

    by_category = [
        CategorySummary(
            category=category,
            count=len(category_rows),
            total_inr=sum(r.amount_inr for r in category_rows if r.amount_inr is not None),
            avg_confidence=sum(r.confidence for r in category_rows) / len(category_rows),
            basis=category_rows[0].basis,
        )
        for category, category_rows in by_category_rows.items()
    ]
    by_category.sort(key=lambda c: c.total_inr, reverse=True)

    # Actionable findings first, largest first; then the visibility-only
    # upper bounds; then waste with no recommendation -- so the
    # biggest-looking number is never the least verified one.
    top_findings = sorted(
        priceable,
        key=lambda r: (
            _TIER_RANK.get(r.basis, 0),
            -(r.amount_inr if r.amount_inr is not None else 0.0),
        ),
    )[:top_n]

    return ReportSummary(
        generated_at=generated_at,
        total_estimates=len(rows),
        priceable_count=len(priceable),
        unpriceable_count=len(unpriceable),
        projected_monthly_total_inr=projected_total,
        observed_window_total_inr=observed_total,
        by_category=by_category,
        top_findings=top_findings,
        unpriceable_samples=unpriceable[:5],
        projected_gpus_with_overlapping_estimates=overlapping_gpus,
        visibility_upper_bound_total_inr=visibility_total,
        detected_no_recommendation_total_inr=no_recommendation_total,
    )
