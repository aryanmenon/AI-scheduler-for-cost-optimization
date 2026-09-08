"""SQLite storage for savings estimates -- the final output of the Phase 1
pipeline, ready for the (not yet built) dashboard/report to render.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from savings_estimator.estimate import SavingsEstimate

SCHEMA = """
CREATE TABLE IF NOT EXISTS savings_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    node TEXT NOT NULL,
    gpu_index TEXT NOT NULL,
    gpu_instance_id TEXT,
    namespace TEXT NOT NULL,
    workload TEXT,
    window_start REAL NOT NULL,
    window_end REAL NOT NULL,
    confidence REAL NOT NULL,
    priceable INTEGER NOT NULL,
    basis TEXT,
    amount_inr REAL,
    recommended_action TEXT NOT NULL,
    methodology TEXT NOT NULL,
    estimated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_savings_category ON savings_estimates (category);
CREATE INDEX IF NOT EXISTS idx_savings_workload ON savings_estimates (namespace, workload);
CREATE UNIQUE INDEX IF NOT EXISTS uq_savings_finding ON savings_estimates (finding_id);
"""


class SavingsStorage:
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

    def insert_estimates(self, estimates: list[SavingsEstimate], estimated_at: float) -> None:
        if not estimates:
            return
        with self._cursor() as cur:
            cur.executemany(
                """INSERT INTO savings_estimates
                   (finding_id, category, node, gpu_index, gpu_instance_id, namespace, workload,
                    window_start, window_end, confidence, priceable, basis, amount_inr,
                    recommended_action, methodology, estimated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (finding_id) DO UPDATE SET
                       category = excluded.category,
                       node = excluded.node,
                       gpu_index = excluded.gpu_index,
                       gpu_instance_id = excluded.gpu_instance_id,
                       namespace = excluded.namespace,
                       workload = excluded.workload,
                       window_start = excluded.window_start,
                       window_end = excluded.window_end,
                       confidence = excluded.confidence,
                       priceable = excluded.priceable,
                       basis = excluded.basis,
                       amount_inr = excluded.amount_inr,
                       recommended_action = excluded.recommended_action,
                       methodology = excluded.methodology,
                       estimated_at = excluded.estimated_at""",
                [
                    (
                        e.finding_id, e.category, e.node, e.gpu_index, e.gpu_instance_id,
                        e.namespace, e.workload, e.window_start, e.window_end, e.confidence,
                        int(e.priceable), e.basis, e.amount_inr, e.recommended_action,
                        e.methodology, estimated_at,
                    )
                    for e in estimates
                ],
            )

    def prune_older_than(self, cutoff: float) -> int:
        """Delete estimates whose estimated_at < cutoff.

        estimated_at is refreshed to "now" every cycle a finding is still
        present upstream (see insert_estimates' upsert), so a row that
        hasn't been refreshed in a long time corresponds to a finding
        that's gone (resolved or pruned in waste-detector), not just an
        old one. Without this, every finding ever priced accumulates
        forever with no way to know it's stale.
        """
        with self._cursor() as cur:
            cur.execute("DELETE FROM savings_estimates WHERE estimated_at < ?", (cutoff,))
            return cur.rowcount

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM savings_estimates").fetchone()[0]

    def all_estimates(self, priceable_only: bool = False) -> list[sqlite3.Row]:
        if priceable_only:
            return self._conn.execute(
                "SELECT * FROM savings_estimates WHERE priceable = 1 ORDER BY window_start"
            ).fetchall()
        return self._conn.execute("SELECT * FROM savings_estimates ORDER BY window_start").fetchall()

    def total_priceable_amount(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_inr), 0) FROM savings_estimates WHERE priceable = 1"
        ).fetchone()
        return row[0]

    def close(self) -> None:
        self._conn.close()
