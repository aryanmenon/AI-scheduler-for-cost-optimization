"""Read-only access to ingestion-normalization's rollups table.

Same architectural choice as telemetry-collector <-> ingestion-normalization:
the boundary between components is the stored SQLite schema, not shared
Python code, so each stays independently deployable. See
ingestion-normalization/src/ingestion_normalization/storage.py:SCHEMA for
the source of truth on the `rollups` table this reads.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass


@dataclass
class RollupRow:
    id: int
    granularity: str
    bucket_start: float
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    namespace: str
    workload: str | None
    sample_count: int
    expected_sample_count: float
    coverage_ratio: float
    low_confidence: bool
    avg_utilization_pct: float | None
    max_utilization_pct: float | None
    avg_memory_used_mb: float | None
    avg_power_draw_w: float | None
    avg_effective_tflops: float | None

    @property
    def attributed(self) -> bool:
        return self.workload is not None


def _valid_pct(value: float | None) -> float | None:
    """A corrupted utilization reading (NaN, negative, or >100%) is worse
    than a missing one: every detector's threshold comparisons treat NaN as
    neither above nor below any threshold (IEEE 754 semantics), which lets
    it slip past a "continue if above threshold" guard and get flagged as
    waste on garbage data instead of being excluded. Sanitize at this one
    shared boundary so all four detectors see it as absent, not trusted.
    """
    if value is None or math.isnan(value) or value < 0.0 or value > 100.0:
        return None
    return value


def _valid_ratio(value: float) -> float:
    if math.isnan(value) or value < 0.0:
        return 0.0
    return min(value, 1.0)


class RollupReader:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def fetch(
        self,
        granularity: str,
        since: float | None = None,
        until: float | None = None,
    ) -> list[RollupRow]:
        query = "SELECT * FROM rollups WHERE granularity = ?"
        params: list = [granularity]
        if since is not None:
            query += " AND bucket_start >= ?"
            params.append(since)
        if until is not None:
            query += " AND bucket_start < ?"
            params.append(until)
        query += " ORDER BY bucket_start"

        cur = self._conn.execute(query, params)
        return [
            RollupRow(
                id=row["id"],
                granularity=row["granularity"],
                bucket_start=row["bucket_start"],
                node=row["node"],
                gpu_index=row["gpu_index"],
                gpu_instance_id=row["gpu_instance_id"],
                namespace=row["namespace"],
                workload=row["workload"],
                sample_count=row["sample_count"],
                expected_sample_count=row["expected_sample_count"],
                coverage_ratio=_valid_ratio(row["coverage_ratio"]),
                low_confidence=bool(row["low_confidence"]),
                avg_utilization_pct=_valid_pct(row["avg_utilization_pct"]),
                max_utilization_pct=_valid_pct(row["max_utilization_pct"]),
                avg_memory_used_mb=row["avg_memory_used_mb"],
                avg_power_draw_w=row["avg_power_draw_w"],
                avg_effective_tflops=row["avg_effective_tflops"],
            )
            for row in cur.fetchall()
        ]

    def latest_bucket_start(self, granularity: str) -> float | None:
        row = self._conn.execute(
            "SELECT MAX(bucket_start) AS m FROM rollups WHERE granularity = ?", (granularity,)
        ).fetchone()
        return row["m"] if row and row["m"] is not None else None

    def close(self) -> None:
        self._conn.close()
