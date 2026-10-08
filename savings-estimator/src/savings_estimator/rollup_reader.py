"""Read-only access to ingestion-normalization's rollups table.

Deliberately independent of waste_detector.rollup_reader (which reads the
same table) rather than a shared dependency between the two sidecars --
each component reads only the columns its own job needs, and this one
needs gpu_model/fp16_tflops (for pricing) that waste-detector's detection
logic has no use for. See
ingestion-normalization/src/ingestion_normalization/storage.py:SCHEMA for
the source of truth on the `rollups` table.
"""
from __future__ import annotations

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
    avg_utilization_pct: float | None
    max_utilization_pct: float | None
    avg_effective_tflops: float | None
    gpu_model: str | None
    fp16_tflops: float | None
    coverage_ratio: float
    # Peak memory used and the GPU's usable memory (DCGM used + free), MiB.
    # None for rows written before ingestion-normalization added them.
    max_memory_used_mb: float | None = None
    memory_total_mb: float | None = None


class RollupReader:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def fetch_for_gpu(
        self,
        granularity: str,
        node: str,
        gpu_index: str,
        gpu_instance_id: str | None,
        since: float,
        until: float,
    ) -> list[RollupRow]:
        query = (
            "SELECT * FROM rollups WHERE granularity = ? AND node = ? AND gpu_index = ? "
            "AND bucket_start >= ? AND bucket_start < ? AND "
        )
        params: list = [granularity, node, gpu_index, since, until]
        if gpu_instance_id is None:
            query += "gpu_instance_id IS NULL"
        else:
            query += "gpu_instance_id = ?"
            params.append(gpu_instance_id)
        query += " ORDER BY bucket_start"

        cur = self._conn.execute(query, params)
        return [self._row(r) for r in cur.fetchall()]

    def fetch_recent(self, granularity: str, window_hours: float) -> list[RollupRow]:
        """Every row in the last window_hours before the newest bucket.

        Anchored to the newest data rather than the wall clock, so a
        replayed or paused dataset still yields its own latest window."""
        try:
            newest = self._conn.execute(
                "SELECT MAX(bucket_start) FROM rollups WHERE granularity = ?", (granularity,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # Fresh install: ingestion hasn't created the table yet. Runs
            # every cycle (unlike fetch_for_gpu), so this must not fail it.
            return []
        if newest is None:
            return []
        since = newest - window_hours * 3600 + 3600
        cur = self._conn.execute(
            "SELECT * FROM rollups WHERE granularity = ? AND bucket_start >= ? ORDER BY bucket_start",
            (granularity, since),
        )
        return [self._row(r) for r in cur.fetchall()]

    @staticmethod
    def _row(row: sqlite3.Row) -> RollupRow:
        return RollupRow(
            id=row["id"],
            granularity=row["granularity"],
            bucket_start=row["bucket_start"],
            node=row["node"],
            gpu_index=row["gpu_index"],
            gpu_instance_id=row["gpu_instance_id"],
            namespace=row["namespace"],
            workload=row["workload"],
            avg_utilization_pct=row["avg_utilization_pct"],
            max_utilization_pct=row["max_utilization_pct"],
            avg_effective_tflops=row["avg_effective_tflops"],
            gpu_model=row["gpu_model"],
            fp16_tflops=row["fp16_tflops"],
            coverage_ratio=row["coverage_ratio"],
            max_memory_used_mb=row["max_memory_used_mb"] if "max_memory_used_mb" in row.keys() else None,
            memory_total_mb=row["memory_total_mb"] if "memory_total_mb" in row.keys() else None,
        )

    def close(self) -> None:
        self._conn.close()
