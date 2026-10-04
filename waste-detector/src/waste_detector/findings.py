"""The waste-category finding every detector emits, and its SQLite storage.

A shared shape across detectors is what lets the (not yet built) savings
estimator treat "idle", "over_provisioned", and "fragmented" findings
uniformly rather than special-casing each detector's own output.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

IDLE = "idle"
OVER_PROVISIONED = "over_provisioned"
# Peak too high for OVER_PROVISIONED but the busiest hour's *average* load
# is low -- the shape of a lightly used LLM-serving workload, whose busy %
# reads near 100% whenever any request is in flight (see
# over_provisioning.detect_oversized_by_average).
OVERSIZED_BY_AVERAGE = "oversized_by_average"
FRAGMENTED = "fragmented"
RECURRING_PATTERN = "recurring_pattern"
MULTI_GPU_OVERSIZED = "multi_gpu_oversized"
# "Below actionable recommendations": waste that is detected and measured
# but has no reliable recommendation attached (see unrecommended.py).
UNDERUTILIZED = "underutilized"
UNATTRIBUTED_GPU_TIME = "unattributed_gpu_time"


@dataclass
class WasteFinding:
    category: str
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    namespace: str
    workload: str | None
    window_start: float
    window_end: float
    # 0-1: how much of the analysis window had trustworthy (high-coverage)
    # data behind it. Detectors compute this from the rollups they used;
    # it's what lets a consumer decide whether to act on or just log a
    # finding built on sparse data.
    confidence: float
    # A short, detector-specific number (idle streak hours, peak
    # utilization %, count of concurrently underutilized GPUs, ...) so a
    # human or the savings estimator can see the evidence, not just the
    # verdict.
    metric_value: float
    detail: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS waste_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    node TEXT NOT NULL,
    gpu_index TEXT NOT NULL,
    gpu_instance_id TEXT,
    namespace TEXT NOT NULL,
    workload TEXT,
    window_start REAL NOT NULL,
    window_end REAL NOT NULL,
    confidence REAL NOT NULL,
    metric_value REAL NOT NULL,
    detail TEXT NOT NULL,
    detected_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_findings_category ON waste_findings (category);
CREATE INDEX IF NOT EXISTS idx_findings_workload ON waste_findings (namespace, workload);
-- Keyed on window_start (not window_end): every detector computes
-- window_start as the stable start of a streak/observation window that
-- only grows monotonically while the underlying condition persists (see
-- idle.py, over_provisioning.py, fragmentation.py, patterns.py). Each
-- detection cycle re-derives the *entire* history from scratch, so an
-- ongoing waste condition produces a growing window_end every cycle;
-- keying on window_end too would make each cycle's row fail to match the
-- previous one and insert a duplicate instead of replacing it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_findings_window
    ON waste_findings (
        category, node, gpu_index, COALESCE(gpu_instance_id, ''),
        namespace, COALESCE(workload, ''), window_start
    );
"""


class FindingsStorage:
    def __init__(self, path: str):
        if path != ":memory:":
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
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

    def insert_findings(self, findings: list[WasteFinding], detected_at: float) -> None:
        if not findings:
            return
        with self._cursor() as cur:
            cur.executemany(
                """INSERT INTO waste_findings
                   (category, node, gpu_index, gpu_instance_id, namespace, workload,
                    window_start, window_end, confidence, metric_value, detail, detected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (
                       category, node, gpu_index, COALESCE(gpu_instance_id, ''),
                       namespace, COALESCE(workload, ''), window_start
                   ) DO UPDATE SET
                       window_end = excluded.window_end,
                       confidence = excluded.confidence,
                       metric_value = excluded.metric_value,
                       detail = excluded.detail,
                       detected_at = excluded.detected_at""",
                [
                    (
                        f.category, f.node, f.gpu_index, f.gpu_instance_id, f.namespace,
                        f.workload, f.window_start, f.window_end, f.confidence,
                        f.metric_value, f.detail, detected_at,
                    )
                    for f in findings
                ],
            )

    def prune_older_than(self, cutoff: float) -> int:
        """Delete findings whose detected_at < cutoff.

        detected_at is refreshed to "now" every cycle a finding is still
        active (see insert_findings' INSERT OR REPLACE), so a finding that
        hasn't been refreshed in a long time is one whose condition ended
        -- it's stale, not just old. Without this, every category ever
        detected accumulates forever with no way to know it's resolved.
        """
        with self._cursor() as cur:
            cur.execute("DELETE FROM waste_findings WHERE detected_at < ?", (cutoff,))
            return cur.rowcount

    def all_findings(self, category: str | None = None) -> list[sqlite3.Row]:
        if category is None:
            return self._conn.execute("SELECT * FROM waste_findings ORDER BY window_start").fetchall()
        return self._conn.execute(
            "SELECT * FROM waste_findings WHERE category = ? ORDER BY window_start", (category,)
        ).fetchall()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM waste_findings").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
