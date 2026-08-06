"""store.py — sqlite persistence: dedupe, watermark, audit log, dead-letter.

Execution semantics per SPEC.md §12. The `audit` table is append-only: no code
path here issues UPDATE or DELETE against it, and database-level triggers abort
any attempt to do so.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models import Classification


def _to_iso(dt: datetime) -> str:
    """Serialise an aware datetime to a UTC ISO-8601 string. Naive datetimes are refused."""
    if dt.tzinfo is None:
        raise ValueError("refusing to store a naive datetime; a timezone is required")
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string into an aware UTC datetime. Accepts a trailing 'Z'.

    Naive inputs (e.g. a bare date) are assumed to be UTC.
    """
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    """Thin wrapper over a sqlite connection. One instance per run."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = str(db_path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed (
                announcement_id TEXT PRIMARY KEY,
                exchange        TEXT NOT NULL,
                ticker          TEXT NOT NULL,
                published_at    TEXT NOT NULL,
                processed_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watermark (
                exchange          TEXT PRIMARY KEY,
                last_processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id TEXT NOT NULL,
                decided_at      TEXT NOT NULL,
                materiality     TEXT,
                confidence      REAL,
                prompt_version  TEXT,
                model_id        TEXT,
                escalated       INTEGER,
                guardrail_flags TEXT,
                input_tokens    INTEGER,
                output_tokens   INTEGER,
                cost_nzd        REAL
            );

            CREATE TABLE IF NOT EXISTS dead_letter (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id TEXT,
                error           TEXT NOT NULL,
                raw_payload     TEXT,
                failed_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS classification_cache (
                announcement_id TEXT NOT NULL,
                prompt_version  TEXT NOT NULL,
                result_json     TEXT NOT NULL,
                cached_at       TEXT NOT NULL,
                PRIMARY KEY (announcement_id, prompt_version)
            );

            -- Enforce append-only audit at the database level (SPEC.md §12):
            -- these triggers abort any UPDATE or DELETE against the audit table.
            CREATE TRIGGER IF NOT EXISTS audit_no_update
                BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;

            CREATE TRIGGER IF NOT EXISTS audit_no_delete
                BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
            """
        )
        self.conn.commit()

    # --- dedupe (processed) --------------------------------------------------

    def is_processed(self, announcement_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM processed WHERE announcement_id = ?", (announcement_id,)
        ).fetchone()
        return row is not None

    def mark_processed(
        self, announcement_id: str, exchange: str, ticker: str, published_at: datetime
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO processed "
            "(announcement_id, exchange, ticker, published_at, processed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                announcement_id,
                exchange,
                ticker,
                _to_iso(published_at),
                _to_iso(datetime.now(timezone.utc)),
            ),
        )
        self.conn.commit()

    # --- watermark -----------------------------------------------------------

    def get_watermark(self, exchange: str) -> Optional[datetime]:
        row = self.conn.execute(
            "SELECT last_processed_at FROM watermark WHERE exchange = ?", (exchange,)
        ).fetchone()
        return parse_iso(row["last_processed_at"]) if row else None

    def set_watermark(self, exchange: str, last_processed_at: datetime) -> None:
        """Advance the watermark. Refuses to move it backwards (monotonic guard,
        defence-in-depth): a caller that races or replays an older window is a
        silent no-op here rather than a watermark regression."""
        if last_processed_at.tzinfo is None:
            raise ValueError("refusing to store a naive datetime; a timezone is required")
        current = self.get_watermark(exchange)
        if current is not None and last_processed_at < current:
            return
        self.conn.execute(
            "INSERT INTO watermark (exchange, last_processed_at) VALUES (?, ?) "
            "ON CONFLICT(exchange) DO UPDATE SET last_processed_at = excluded.last_processed_at",
            (exchange, _to_iso(last_processed_at)),
        )
        self.conn.commit()

    # --- audit (APPEND-ONLY: INSERT only, never UPDATE/DELETE) ---------------

    def append_audit(
        self,
        *,
        announcement_id: str,
        decided_at: datetime,
        materiality: Optional[str] = None,
        confidence: Optional[float] = None,
        prompt_version: Optional[str] = None,
        model_id: Optional[str] = None,
        escalated: Optional[bool] = None,
        guardrail_flags: Optional[list[str]] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_nzd: Optional[float] = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO audit "
            "(announcement_id, decided_at, materiality, confidence, prompt_version, "
            " model_id, escalated, guardrail_flags, input_tokens, output_tokens, cost_nzd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                announcement_id,
                _to_iso(decided_at),
                materiality,
                confidence,
                prompt_version,
                model_id,
                None if escalated is None else int(escalated),
                json.dumps(guardrail_flags or []),
                input_tokens,
                output_tokens,
                cost_nzd,
            ),
        )
        self.conn.commit()

    def is_audited(self, announcement_id: str) -> bool:
        """True if this announcement already has an audit row (classify→brief done).

        The pipeline (run.py) uses this for idempotency: re-running any window must
        be safe, so an already-decided announcement is skipped (SPEC §12).
        """
        row = self.conn.execute(
            "SELECT 1 FROM audit WHERE announcement_id = ? LIMIT 1", (announcement_id,)
        ).fetchone()
        return row is not None

    # --- classification cache (reuse across overlapping windows / reruns) ----

    def get_cached_classification(
        self, announcement_id: str, prompt_version: str
    ) -> Optional[Classification]:
        """A fully-verified `Classification` cached from a prior run, or None on a miss.

        Keyed on (announcement_id, prompt_version): a prompt-version bump is a
        cache miss by construction, so no separate invalidation is needed.
        """
        row = self.conn.execute(
            "SELECT result_json FROM classification_cache WHERE announcement_id = ? AND prompt_version = ?",
            (announcement_id, prompt_version),
        ).fetchone()
        if row is None:
            return None
        return Classification.model_validate_json(row["result_json"])

    def put_cached_classification(
        self, announcement_id: str, prompt_version: str, classification: Classification
    ) -> None:
        """Cache a fully-verified `Classification` (post-verify(), never pre-verify —
        verify() is not idempotent, so only the exact object that was audited/ranked
        this pass may be rehydrated on a future cache hit)."""
        self.conn.execute(
            "INSERT INTO classification_cache (announcement_id, prompt_version, result_json, cached_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(announcement_id, prompt_version) DO UPDATE SET "
            "result_json = excluded.result_json, cached_at = excluded.cached_at",
            (
                announcement_id,
                prompt_version,
                classification.model_dump_json(),
                _to_iso(datetime.now(timezone.utc)),
            ),
        )
        self.conn.commit()

    # --- dead-letter ---------------------------------------------------------

    def add_dead_letter(
        self,
        error: str,
        raw_payload: Optional[object] = None,
        announcement_id: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO dead_letter (announcement_id, error, raw_payload, failed_at) "
            "VALUES (?, ?, ?, ?)",
            (
                announcement_id,
                error,
                None if raw_payload is None else json.dumps(raw_payload, default=str),
                _to_iso(datetime.now(timezone.utc)),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
