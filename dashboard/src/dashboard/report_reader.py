"""Read-only access to savings-estimator's savings_estimates table.

Same schema-contract pattern as every reader before this one in the
pipeline: see savings-estimator/src/savings_estimator/storage.py:SCHEMA
for the source of truth. savings_estimates already carries forward every
field a report needs (category, GPU/workload identity, window, confidence,
pricing basis and amount, recommended action, methodology) -- the
dashboard doesn't need to read any of the three earlier databases directly.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class EstimateRow:
    id: int
    finding_id: int
    category: str
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    namespace: str
    workload: str | None
    window_start: float
    window_end: float
    confidence: float
    priceable: bool
    basis: str | None
    amount_inr: float | None
    recommended_action: str
    methodology: str
    estimated_at: float


@dataclass
class CeilingRow:
    """savings-estimator's recoverable_ceiling row (see its recoverable.py)."""
    window_start: float
    window_end: float
    target_utilization_pct: float
    observed_gpu_hours: float
    observed_spend_inr: float
    recoverable_inr: float
    monthly_spend_inr: float
    excluded_gpu_hours: float

    @property
    def fraction(self) -> float:
        return self.recoverable_inr / self.observed_spend_inr if self.observed_spend_inr > 0 else 0.0

    @property
    def monthly_recoverable_inr(self) -> float:
        return self.fraction * self.monthly_spend_inr


class ReportReader:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def all_estimates(self) -> list[EstimateRow]:
        cur = self._conn.execute("SELECT * FROM savings_estimates ORDER BY amount_inr DESC")
        return [
            EstimateRow(
                id=row["id"],
                finding_id=row["finding_id"],
                category=row["category"],
                node=row["node"],
                gpu_index=row["gpu_index"],
                gpu_instance_id=row["gpu_instance_id"],
                namespace=row["namespace"],
                workload=row["workload"],
                window_start=row["window_start"],
                window_end=row["window_end"],
                confidence=row["confidence"],
                priceable=bool(row["priceable"]),
                basis=row["basis"],
                amount_inr=row["amount_inr"],
                recommended_action=row["recommended_action"],
                methodology=row["methodology"],
                estimated_at=row["estimated_at"],
            )
            for row in cur.fetchall()
        ]

    def ceiling(self) -> CeilingRow | None:
        # Absent on a savings database written before the ceiling existed.
        has_table = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'recoverable_ceiling'"
        ).fetchone()
        if not has_table:
            return None
        row = self._conn.execute("SELECT * FROM recoverable_ceiling WHERE id = 1").fetchone()
        if row is None:
            return None
        return CeilingRow(
            window_start=row["window_start"],
            window_end=row["window_end"],
            target_utilization_pct=row["target_utilization_pct"],
            observed_gpu_hours=row["observed_gpu_hours"],
            observed_spend_inr=row["observed_spend_inr"],
            recoverable_inr=row["recoverable_inr"],
            monthly_spend_inr=row["monthly_spend_inr"],
            excluded_gpu_hours=row["excluded_gpu_hours"],
        )

    def close(self) -> None:
        self._conn.close()
