"""License key storage — minimal SQLite-backed store.

Design notes
------------
- SQLite file at `$HVAC_MCP_DATA_DIR/licenses.db` (default: ~/.hvac-mcp/licenses.db).
  In containers, mount a volume at /data and set HVAC_MCP_DATA_DIR=/data.
- One table, one row per license key issued. `status` ∈ {active, cancelled, refunded}.
- Inserts are idempotent on `stripe_session_id` so a retried webhook doesn't
  double-issue.
- No encryption at rest — keys are random opaque strings, not secrets by
  themselves (they grant access to premium tools, not money).

Why stdlib sqlite3 and not SQLAlchemy
--------------------------------------
This schema has two tables (future) and three columns we care about. SQLAlchemy
would be more dependency surface for no real benefit. Swap if it ever gets
complicated.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Tier = Literal["starter", "pro", "lifetime"]
Status = Literal["active", "cancelled", "refunded", "past_due"]

_DEFAULT_DATA_DIR = Path.home() / ".hvac-mcp"
LICENSE_KEY_PREFIX = "hvac_"


def _data_dir() -> Path:
    """Resolve the data directory, honoring HVAC_MCP_DATA_DIR env var."""
    raw = os.environ.get("HVAC_MCP_DATA_DIR")
    d = Path(raw) if raw else _DEFAULT_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_path() -> Path:
    return _data_dir() / "licenses.db"


@dataclass(frozen=True)
class License:
    key: str
    tier: Tier
    status: Status
    stripe_customer_id: str
    stripe_session_id: str
    issued_at: int  # unix seconds


class LicenseStore:
    """Thin SQLite wrapper. Stateless — each call opens/closes a connection.

    Safe to use from both sync webhook handlers and async tool-auth checks
    (SQLite handles concurrent readers fine; webhook writes are rare).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or _db_path()
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS licenses (
                    key TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stripe_customer_id TEXT NOT NULL,
                    stripe_session_id TEXT NOT NULL UNIQUE,
                    issued_at INTEGER NOT NULL
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_licenses_customer ON licenses(stripe_customer_id)"
            )

    @staticmethod
    def new_key() -> str:
        """Generate a fresh license key. 24 urlsafe chars + prefix = 29 total."""
        return LICENSE_KEY_PREFIX + secrets.token_urlsafe(18)

    def issue(
        self,
        *,
        tier: Tier,
        stripe_customer_id: str,
        stripe_session_id: str,
    ) -> License:
        """Issue a new license. Idempotent on stripe_session_id.

        If a license already exists for this session, return the existing one
        rather than creating a duplicate — Stripe retries webhooks on 5xx and
        network flakes, so the same event may arrive more than once.
        """
        existing = self.get_by_session(stripe_session_id)
        if existing is not None:
            return existing
        key = self.new_key()
        now = int(time.time())
        with self._conn() as c:
            c.execute(
                "INSERT INTO licenses (key, tier, status, stripe_customer_id, "
                "stripe_session_id, issued_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key, tier, "active", stripe_customer_id, stripe_session_id, now),
            )
        return License(
            key=key,
            tier=tier,
            status="active",
            stripe_customer_id=stripe_customer_id,
            stripe_session_id=stripe_session_id,
            issued_at=now,
        )

    def get(self, key: str) -> License | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM licenses WHERE key = ?", (key,)).fetchone()
        return _row_to_license(row) if row else None

    def get_by_session(self, session_id: str) -> License | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM licenses WHERE stripe_session_id = ?", (session_id,)
            ).fetchone()
        return _row_to_license(row) if row else None

    def set_status_for_customer(self, stripe_customer_id: str, status: Status) -> int:
        """Update status for every license tied to a Stripe customer. Returns row count."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE licenses SET status = ? WHERE stripe_customer_id = ?",
                (status, stripe_customer_id),
            )
            return cur.rowcount

    def is_active(self, key: str) -> bool:
        lic = self.get(key)
        return lic is not None and lic.status == "active"


def _row_to_license(row: sqlite3.Row) -> License:
    return License(
        key=row["key"],
        tier=row["tier"],
        status=row["status"],
        stripe_customer_id=row["stripe_customer_id"],
        stripe_session_id=row["stripe_session_id"],
        issued_at=row["issued_at"],
    )
