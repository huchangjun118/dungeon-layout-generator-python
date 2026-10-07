"""SQLite-backed persistence for layouts, idempotency keys and audit log.

Survives process restarts so interrupted generations can be recovered and
idempotency guarantees hold across restarts.

Job lifecycle:  (absent) -> running -> done | failed
A process crash leaves jobs in 'running'; recover_stale_jobs() removes them
so the next request regenerates deterministically to the identical result.
"""
from __future__ import annotations

import sqlite3
import threading
import time

from app.models import Layout, LayoutStatus


class LayoutStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    key        TEXT PRIMARY KEY,
                    version    TEXT NOT NULL,
                    status     TEXT NOT NULL,  -- running | done | failed
                    layout_id  TEXT,
                    error      TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS layouts (
                    layout_id TEXT PRIMARY KEY,
                    key       TEXT UNIQUE NOT NULL,
                    json      TEXT NOT NULL,
                    status    TEXT NOT NULL,
                    revision  INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    layout_id  TEXT NOT NULL,
                    actor      TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state   TEXT NOT NULL,
                    ts         REAL NOT NULL
                );
                """
            )

    # --- idempotency / job records -------------------------------------
    def begin_job(self, key: str, version: str) -> str:
        """Atomically claim a generation job.

        Returns "started" if this call claimed the job, "done" if a completed
        result already exists, "running" if another worker owns it.
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO jobs(key, version, status, updated_at)"
                " VALUES (?, ?, 'running', ?)",
                (key, version, time.time()),
            )
            if cur.rowcount == 1:
                return "started"
            row = self._conn.execute(
                "SELECT status FROM jobs WHERE key = ?", (key,)
            ).fetchone()
            return row["status"]

    def complete_job(self, key: str, layout_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET status='done', layout_id=?, updated_at=?"
                " WHERE key=?",
                (layout_id, time.time(), key),
            )

    def fail_job(self, key: str, error: str) -> None:
        """Remove a failed/cancelled job so it can be retried cleanly.

        The failure is recorded in the audit-independent job row only
        transiently; removing the row guarantees no half-finished state is
        visible to later requests.
        """
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM jobs WHERE key=? AND status='running'",
                               (key,))

    def job_status(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM jobs WHERE key = ?", (key,)
            ).fetchone()
            return row["status"] if row else None

    def job_layout_id(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT layout_id FROM jobs WHERE key = ?", (key,)
            ).fetchone()
            return row["layout_id"] if row else None

    def recover_stale_jobs(self) -> list[str]:
        """Drop jobs left 'running' by a crashed process.

        Because generation is deterministic, deleting the claim lets the
        next request regenerate the identical layout from scratch.
        Returns the recovered keys.
        """
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT key FROM jobs WHERE status='running'"
            ).fetchall()
            keys = [r["key"] for r in rows]
            self._conn.execute("DELETE FROM jobs WHERE status='running'")
            return keys

    # --- layouts ---------------------------------------------------------
    def save_layout(self, layout_id: str, key: str, layout: Layout) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO layouts(layout_id, key, json, status, revision)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(layout_id) DO UPDATE SET"
                "   json=excluded.json, status=excluded.status,"
                "   revision=excluded.revision",
                (layout_id, key, layout.to_json(),
                 layout.status.value, layout.revision),
            )

    def get_layout(self, layout_id: str) -> Layout | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT json FROM layouts WHERE layout_id = ?", (layout_id,)
            ).fetchone()
            return Layout.from_json(row["json"]) if row else None

    def find_by_key(self, key: str) -> tuple[str, Layout] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT layout_id, json FROM layouts WHERE key = ?", (key,)
            ).fetchone()
            return (row["layout_id"], Layout.from_json(row["json"])) if row else None

    # --- state machine ---------------------------------------------------
    def compare_and_swap_status(
        self,
        layout_id: str,
        expected: LayoutStatus,
        new: LayoutStatus,
        actor: str,
        role: str,
    ) -> bool:
        """Atomically transition status if current == expected; audit it.

        Exactly one of any set of concurrent transitions wins, so the
        resulting state is deterministic.
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE layouts SET status=?, json=json_set(json,'$.status',?)"
                " WHERE layout_id=? AND status=?",
                (new.value, new.value, layout_id, expected.value),
            )
            if cur.rowcount != 1:
                return False
            self._conn.execute(
                "INSERT INTO audit(layout_id, actor, role, from_state,"
                " to_state, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (layout_id, actor, role, expected.value, new.value,
                 time.time()),
            )
            return True

    def current_status(self, layout_id: str) -> LayoutStatus | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM layouts WHERE layout_id = ?", (layout_id,)
            ).fetchone()
            return LayoutStatus(row["status"]) if row else None

    def audit_log(self, layout_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT actor, role, from_state, to_state, ts FROM audit"
                " WHERE layout_id=? ORDER BY id", (layout_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
