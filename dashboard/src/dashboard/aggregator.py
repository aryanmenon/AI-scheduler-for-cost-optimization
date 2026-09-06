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


def aggregate(rows: list[EstimateRow], top_n: int, generated_at: float | None = None) -> ReportSummary:
    generated_at = generated_at if generated_at is not None else time.time()

    priceable = [r for r in rows if r.priceable]
    unpriceable = [r for r in rows if not r.priceable]

    projected_total = sum(
        r.amount_inr for r in priceable if r.basis == BASIS_PROJECTED_MONTHLY and r.amount_inr is not None
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

    top_findings = sorted(
        priceable, key=lambda r: r.amount_inr if r.amount_inr is not None else 0.0, reverse=True
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
    )
