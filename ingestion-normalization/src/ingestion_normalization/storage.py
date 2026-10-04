"""SQLite storage for normalized samples and time-bucket rollups.

Kept as a separate database file from telemetry-collector's raw
telemetry.db (rather than writing into it) so this component stays a
read-only consumer of the collector's data -- a bug here can never corrupt
the raw feed that everything else depends on.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from ingestion_normalization.normalizer import NormalizedRecord
from ingestion_normalization.rollup import RollupRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_cursor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_raw_run_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rollup_recompute_state (
    granularity TEXT PRIMARY KEY,
    last_recomputed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id INTEGER NOT NULL,
    scraped_at REAL NOT NULL,
    node TEXT NOT NULL,
    gpu_index TEXT NOT NULL,
    gpu_instance_id TEXT,
    gpu_uuid TEXT,
    gpu_model TEXT,
    namespace TEXT NOT NULL,
    workload TEXT,
    pod TEXT,
    container TEXT,
    utilization_pct REAL,
    memory_used_mb REAL,
    memory_free_mb REAL,
    power_draw_w REAL,
    capability_known INTEGER NOT NULL,
    fp16_tflops REAL,
    effective_tflops REAL
);

CREATE INDEX IF NOT EXISTS idx_normalized_scraped_at ON normalized_samples (scraped_at);
CREATE INDEX IF NOT EXISTS idx_normalized_workload ON normalized_samples (namespace, workload);
CREATE UNIQUE INDEX IF NOT EXISTS uq_normalized_sample
    ON normalized_samples (scrape_run_id, node, gpu_index, COALESCE(gpu_instance_id, ''));

CREATE TABLE IF NOT EXISTS rollups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    granularity TEXT NOT NULL,
    bucket_start REAL NOT NULL,
    node TEXT NOT NULL,
    gpu_index TEXT NOT NULL,
    gpu_instance_id TEXT,
    namespace TEXT NOT NULL,
    workload TEXT,
    sample_count INTEGER NOT NULL,
    expected_sample_count REAL NOT NULL,
    coverage_ratio REAL NOT NULL,
    low_confidence INTEGER NOT NULL,
    avg_utilization_pct REAL,
    max_utilization_pct REAL,
    avg_memory_used_mb REAL,
    avg_power_draw_w REAL,
    avg_effective_tflops REAL,
    gpu_model TEXT,
    fp16_tflops REAL,
    max_memory_used_mb REAL,
    memory_total_mb REAL
);

-- One row per workload per GPU per bucket: a GPU whose pod changes within
-- a bucket (a job ends and another starts, or no pod -> pod) has one row per
-- workload, as compute_rollups groups them.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rollup_bucket_workload
    ON rollups (granularity, bucket_start, node, gpu_index, COALESCE(gpu_instance_id, ''),
                namespace, COALESCE(workload, ''));
CREATE INDEX IF NOT EXISTS idx_rollups_workload ON rollups (granularity, namespace, workload);
"""


# Columns added to `rollups` after its first release. CREATE TABLE IF NOT
# EXISTS leaves an existing table (a pilot's persistent volume) untouched,
# so each one is added in place on startup; old rows read back as NULL.
_ROLLUP_ADDED_COLUMNS = {
    "max_memory_used_mb": "REAL",
    "memory_total_mb": "REAL",
}


class NormalizedStorage:
    def __init__(self, path: str):
        if path != ":memory:":
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
        # The first release's unique index left out namespace/workload, so
        # every bucket in which a GPU changed workload failed to store
        # (found in the 2026-10-04 pilot install rehearsal). Drop it on
        # existing volumes; the replacement above is strictly looser, so
        # existing rows always satisfy it.
        self._conn.execute("DROP INDEX IF EXISTS uq_rollup_bucket")
        self._conn.executescript(SCHEMA)
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(rollups)")}
        for column, sql_type in _ROLLUP_ADDED_COLUMNS.items():
            if column not in existing:
                self._conn.execute(f"ALTER TABLE rollups ADD COLUMN {column} {sql_type}")
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

    def get_cursor(self) -> int:
        row = self._conn.execute(
            "SELECT last_raw_run_id FROM ingestion_cursor WHERE id = 1"
        ).fetchone()
        return row["last_raw_run_id"] if row else 0

    def set_cursor(self, last_raw_run_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO ingestion_cursor (id, last_raw_run_id) VALUES (1, ?)
                   ON CONFLICT (id) DO UPDATE SET last_raw_run_id = excluded.last_raw_run_id""",
                (last_raw_run_id,),
            )

    def get_last_rollup_recompute_at(self, granularity: str) -> float | None:
        row = self._conn.execute(
            "SELECT last_recomputed_at FROM rollup_recompute_state WHERE granularity = ?",
            (granularity,),
        ).fetchone()
        return row["last_recomputed_at"] if row else None

    def set_last_rollup_recompute_at(self, granularity: str, at: float) -> None:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO rollup_recompute_state (granularity, last_recomputed_at) VALUES (?, ?)
                   ON CONFLICT (granularity) DO UPDATE SET last_recomputed_at = excluded.last_recomputed_at""",
                (granularity, at),
            )

    def insert_normalized_samples(self, records: list[NormalizedRecord]) -> None:
        if not records:
            return
        with self._cursor() as cur:
            cur.executemany(
                """INSERT OR IGNORE INTO normalized_samples
                   (scrape_run_id, scraped_at, node, gpu_index, gpu_instance_id, gpu_uuid,
                    gpu_model, namespace, workload, pod, container, utilization_pct,
                    memory_used_mb, memory_free_mb, power_draw_w, capability_known,
                    fp16_tflops, effective_tflops)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        r.scrape_run_id, r.scraped_at, r.node, r.gpu_index, r.gpu_instance_id,
                        r.gpu_uuid, r.gpu_model, r.namespace, r.workload, r.pod, r.container,
                        r.utilization_pct, r.memory_used_mb, r.memory_free_mb, r.power_draw_w,
                        int(r.capability_known), r.fp16_tflops, r.effective_tflops,
                    )
                    for r in records
                ],
            )

    def normalized_samples_between(self, start_ts: float, end_ts: float) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM normalized_samples WHERE scraped_at >= ? AND scraped_at < ? "
            "ORDER BY scraped_at",
            (start_ts, end_ts),
        ).fetchall()

    def replace_rollups(self, granularity: str, start_ts: float, end_ts: float,
                         rollups: list[RollupRecord]) -> None:
        """Idempotently replace rollup rows for [start_ts, end_ts) at one granularity.

        Deleting the touched window before inserting makes re-running the
        pipeline over an overlapping time range safe -- a bucket recomputed
        from more complete data simply overwrites the earlier, partial one.
        """
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM rollups WHERE granularity = ? AND bucket_start >= ? AND bucket_start < ?",
                (granularity, start_ts, end_ts),
            )
            cur.executemany(
                """INSERT INTO rollups
                   (granularity, bucket_start, node, gpu_index, gpu_instance_id, namespace,
                    workload, sample_count, expected_sample_count, coverage_ratio,
                    low_confidence, avg_utilization_pct, max_utilization_pct,
                    avg_memory_used_mb, avg_power_draw_w, avg_effective_tflops,
                    gpu_model, fp16_tflops, max_memory_used_mb, memory_total_mb)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        granularity, r.bucket_start, r.node, r.gpu_index, r.gpu_instance_id,
                        r.namespace, r.workload, r.sample_count, r.expected_sample_count,
                        r.coverage_ratio, int(r.low_confidence), r.avg_utilization_pct,
                        r.max_utilization_pct, r.avg_memory_used_mb, r.avg_power_draw_w,
                        r.avg_effective_tflops, r.gpu_model, r.fp16_tflops,
                        r.max_memory_used_mb, r.memory_total_mb,
                    )
                    for r in rollups
                ],
            )

    def prune_normalized_samples_older_than(self, cutoff: float) -> int:
        """Delete normalized_samples rows with scraped_at < cutoff.

        This raw, per-scrape data is superseded by rollups almost
        immediately; kept only long enough to support the daily rollup
        recompute rescanning a full day's worth of it. Without pruning
        this grows unbounded, same as telemetry-collector's raw store.
        """
        with self._cursor() as cur:
            cur.execute("DELETE FROM normalized_samples WHERE scraped_at < ?", (cutoff,))
            return cur.rowcount

    def prune_rollups_older_than(self, cutoff: float) -> int:
        """Delete rollups rows with bucket_start < cutoff, across all
        granularities. Unlike normalized_samples, this is the durable
        historical record consumers rely on, so the cutoff is expected to
        be far more generous.
        """
        with self._cursor() as cur:
            cur.execute("DELETE FROM rollups WHERE bucket_start < ?", (cutoff,))
            return cur.rowcount

    def count_normalized_samples(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM normalized_samples").fetchone()[0]

    def rollups(self, granularity: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM rollups WHERE granularity = ? ORDER BY bucket_start", (granularity,)
        ).fetchall()

    def close(self) -> None:
        self._conn.close()
