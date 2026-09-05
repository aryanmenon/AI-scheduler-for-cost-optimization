"""Read-only access to the telemetry-collector's raw SQLite database.

This intentionally does not import the telemetry_collector package -- the
two components are meant to be independently deployable (this one could
run as a CronJob against a read-only mount of the collector's PVC), so the
contract between them is the stored SQLite schema, not shared Python code.
If that schema changes, it should change here too; see
telemetry-collector/src/telemetry_collector/storage.py:SCHEMA for the
source of truth.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class RawGPUSample:
    id: int
    scrape_run_id: int
    scraped_at: float
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    gpu_uuid: str | None
    gpu_model: str | None
    namespace: str
    pod: str | None
    container: str | None
    utilization_pct: float | None
    memory_used_mb: float | None
    memory_free_mb: float | None
    power_draw_w: float | None
    sm_clock_mhz: float | None


class RawReader:
    def __init__(self, path: str):
        # Read-only connection: this component must never be able to
        # mutate the collector's data, even by accident.
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def latest_run_id(self) -> int:
        cur = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM scrape_runs")
        return cur.fetchone()[0]

    def fetch_since(self, after_run_id: int) -> list[RawGPUSample]:
        cur = self._conn.execute(
            "SELECT * FROM gpu_metrics WHERE scrape_run_id > ? ORDER BY scrape_run_id, id",
            (after_run_id,),
        )
        return [
            RawGPUSample(
                id=row["id"],
                scrape_run_id=row["scrape_run_id"],
                scraped_at=row["scraped_at"],
                node=row["node"],
                gpu_index=row["gpu_index"],
                gpu_instance_id=row["gpu_instance_id"],
                gpu_uuid=row["gpu_uuid"],
                gpu_model=row["gpu_model"],
                namespace=row["namespace"],
                pod=row["pod"],
                container=row["container"],
                utilization_pct=row["utilization_pct"],
                memory_used_mb=row["memory_used_mb"],
                memory_free_mb=row["memory_free_mb"],
                power_draw_w=row["power_draw_w"],
                sm_clock_mhz=row["sm_clock_mhz"],
            )
            for row in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()
