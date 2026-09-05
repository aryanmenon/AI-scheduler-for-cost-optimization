"""SQLite-backed storage for scraped GPU telemetry.

WAL mode is used so a concurrent read (e.g. a dashboard query) never blocks
the write loop, and so the collector survives being killed mid-write
without corrupting the file -- both matter because this runs unattended,
scraping every ~30s, for weeks at a time on a customer's cluster.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager

from telemetry_collector.correlator import GPUMetricRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_at REAL NOT NULL,
    duration_ms REAL NOT NULL,
    gpu_count INTEGER NOT NULL,
    attributed_count INTEGER NOT NULL,
    success INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS gpu_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
    scraped_at REAL NOT NULL,
    node TEXT NOT NULL,
    gpu_index TEXT NOT NULL,
    gpu_uuid TEXT,
    gpu_model TEXT,
    namespace TEXT NOT NULL,
    pod TEXT,
    container TEXT,
    utilization_pct REAL,
    memory_used_mb REAL,
    memory_free_mb REAL,
    power_draw_w REAL,
    sm_clock_mhz REAL
);

CREATE INDEX IF NOT EXISTS idx_gpu_metrics_scraped_at ON gpu_metrics (scraped_at);
CREATE INDEX IF NOT EXISTS idx_gpu_metrics_node_gpu ON gpu_metrics (node, gpu_index);
CREATE INDEX IF NOT EXISTS idx_gpu_metrics_namespace ON gpu_metrics (namespace);
"""


class Storage:
    def __init__(self, path: str):
        if path != ":memory:":
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def _cursor(self):
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def record_scrape(
        self,
        records: list[GPUMetricRecord],
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        scraped_at: float | None = None,
    ) -> int:
        """Persist one scrape cycle's worth of GPU records as a single run.

        Each call is its own transaction, so a crash mid-loop leaves
        previously stored scrapes intact -- callers can invoke this once
        per cycle without worrying about partial writes across cycles.
        """
        scraped_at = scraped_at if scraped_at is not None else time.time()
        attributed_count = sum(1 for r in records if r.attributed)

        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO scrape_runs
                   (scraped_at, duration_ms, gpu_count, attributed_count, success, error)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (scraped_at, duration_ms, len(records), attributed_count, int(success), error),
            )
            run_id = cur.lastrowid

            cur.executemany(
                """INSERT INTO gpu_metrics
                   (scrape_run_id, scraped_at, node, gpu_index, gpu_uuid, gpu_model,
                    namespace, pod, container, utilization_pct, memory_used_mb,
                    memory_free_mb, power_draw_w, sm_clock_mhz)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        scraped_at,
                        r.node,
                        r.gpu_index,
                        r.gpu_uuid,
                        r.gpu_model,
                        r.namespace,
                        r.pod,
                        r.container,
                        r.utilization_pct,
                        r.memory_used_mb,
                        r.memory_free_mb,
                        r.power_draw_w,
                        r.sm_clock_mhz,
                    )
                    for r in records
                ],
            )
        return run_id

    def count_gpu_metrics(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM gpu_metrics")
        return cur.fetchone()[0]

    def count_scrape_runs(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM scrape_runs")
        return cur.fetchone()[0]

    def latest_metrics(self, limit: int = 100) -> list[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(
            "SELECT * FROM gpu_metrics ORDER BY scraped_at DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()
