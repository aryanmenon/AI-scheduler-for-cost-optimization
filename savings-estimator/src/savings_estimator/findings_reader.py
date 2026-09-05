"""Read-only access to waste-detector's findings table.

Same schema-contract pattern as every reader before this one in the
pipeline: see waste_detector/src/waste_detector/findings.py:SCHEMA for the
source of truth on the `waste_findings` table this reads.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class FindingRow:
    id: int
    category: str
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    namespace: str
    workload: str | None
    window_start: float
    window_end: float
    confidence: float
    metric_value: float
    detail: str
    detected_at: float


class FindingsReader:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def all_findings(self, min_confidence: float = 0.0) -> list[FindingRow]:
        cur = self._conn.execute(
            "SELECT * FROM waste_findings WHERE confidence >= ? ORDER BY window_start",
            (min_confidence,),
        )
        return [
            FindingRow(
                id=row["id"],
                category=row["category"],
                node=row["node"],
                gpu_index=row["gpu_index"],
                gpu_instance_id=row["gpu_instance_id"],
                namespace=row["namespace"],
                workload=row["workload"],
                window_start=row["window_start"],
                window_end=row["window_end"],
                confidence=row["confidence"],
                metric_value=row["metric_value"],
                detail=row["detail"],
                detected_at=row["detected_at"],
            )
            for row in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()
