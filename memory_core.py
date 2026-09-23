"""Isolated deterministic Memory Core PoC.

This module intentionally does not integrate with the legacy chat runtime,
provider prompts, UI, or ontology pipeline. It provides a small SQLite-backed
structured fact store with immutable events and bi-temporal fact versions.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class MemoryCoreError(Exception):
    """Base error for Memory Core PoC failures."""


class IdempotencyConflict(MemoryCoreError):
    """Raised when an event_id is reused with a different request payload."""


class MemoryOperation(StrEnum):
    SET = "set"
    REPLACE = "replace"
    CORRECT = "correct"
    FORGET = "forget"


@dataclass(frozen=True, slots=True)
class FactVersion:
    fact_version_id: int
    event_id: str
    user_id: str
    subject: str
    attribute: str
    value: Any
    valid_from: datetime
    valid_to: datetime | None
    system_from: datetime
    system_to: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WriteResult:
    event_id: str
    operation: MemoryOperation
    idempotent: bool
    current_fact: FactVersion | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    if not isinstance(value, datetime):
        raise TypeError("datetime value is required")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _dt_to_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_dt(value).isoformat(timespec="microseconds")


def _dt_from_text(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _json_to_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_from_text(value: str) -> Any:
    return json.loads(value)


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = _json_to_text(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_to_fact(row: sqlite3.Row | None) -> FactVersion | None:
    if row is None:
        return None
    return FactVersion(
        fact_version_id=int(row["fact_version_id"]),
        event_id=str(row["event_id"]),
        user_id=str(row["user_id"]),
        subject=str(row["subject"]),
        attribute=str(row["attribute"]),
        value=_json_from_text(row["value_json"]),
        valid_from=_dt_from_text(row["valid_from"]),
        valid_to=_dt_from_text(row["valid_to"]),
        system_from=_dt_from_text(row["system_from"]),
        system_to=_dt_from_text(row["system_to"]),
        created_at=_dt_from_text(row["created_at"]),
    )


class SQLiteMemoryCore:
    """Small deterministic SQLite memory core with bi-temporal semantics."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            self._create_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                event_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT,
                subject TEXT NOT NULL,
                attribute TEXT NOT NULL,
                value_json TEXT,
                operation TEXT NOT NULL CHECK (operation IN ('set','replace','correct','forget')),
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                system_from TEXT NOT NULL,
                system_to TEXT,
                created_at TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                result_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS structured_facts (
                fact_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL REFERENCES memory_events(event_id),
                user_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                attribute TEXT NOT NULL,
                value_json TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                system_from TEXT NOT NULL,
                system_to TEXT,
                created_at TEXT NOT NULL,
                CHECK (valid_to IS NULL OR valid_to > valid_from),
                CHECK (system_to IS NULL OR system_to > system_from)
            );

            CREATE INDEX IF NOT EXISTS idx_facts_key_time
                ON structured_facts(user_id, subject, attribute, valid_from, valid_to, system_from, system_to);

            CREATE UNIQUE INDEX IF NOT EXISTS ux_one_open_current_fact
                ON structured_facts(user_id, subject, attribute)
                WHERE valid_to IS NULL AND system_to IS NULL;
            """
        )

    def get_current_fact(
        self,
        user_id: str,
        subject: str,
        attribute: str,
        as_of_valid_time: datetime | None = None,
    ) -> FactVersion | None:
        valid_time = _normalize_dt(as_of_valid_time)
        system_time = _utc_now()
        return self.get_fact_as_known_at(user_id, subject, attribute, valid_time, system_time)

    def get_fact_history(self, user_id: str, subject: str, attribute: str) -> list[FactVersion]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM structured_facts
                WHERE user_id = ? AND subject = ? AND attribute = ?
                ORDER BY system_from, valid_from, fact_version_id
                """,
                (user_id, subject, attribute),
            ).fetchall()
        return [_row_to_fact(row) for row in rows]

    def get_fact_as_known_at(
        self,
        user_id: str,
        subject: str,
        attribute: str,
        valid_time: datetime,
        system_time: datetime,
    ) -> FactVersion | None:
        valid_text = _dt_to_text(valid_time)
        system_text = _dt_to_text(system_time)
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM structured_facts
                WHERE user_id = ?
                  AND subject = ?
                  AND attribute = ?
                  AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to > ?)
                  AND system_from <= ?
                  AND (system_to IS NULL OR system_to > ?)
                ORDER BY system_from DESC, fact_version_id DESC
                LIMIT 1
                """,
                (user_id, subject, attribute, valid_text, valid_text, system_text, system_text),
            ).fetchone()
        return _row_to_fact(row)

    def append_or_replace_fact(
        self,
        *,
        event_id: str,
        user_id: str,
        session_id: str | None,
        subject: str,
        attribute: str,
        value: Any,
        valid_from: datetime | None = None,
        system_time: datetime | None = None,
        operation: MemoryOperation = MemoryOperation.REPLACE,
        fail_after_event_for_test: bool = False,
    ) -> WriteResult:
        if operation not in {MemoryOperation.SET, MemoryOperation.REPLACE}:
            raise ValueError("append_or_replace_fact requires set or replace")
        return self._write_fact(
            event_id=event_id,
            user_id=user_id,
            session_id=session_id,
            subject=subject,
            attribute=attribute,
            value=value,
            operation=operation,
            valid_from=valid_from,
            system_time=system_time,
            fail_after_event_for_test=fail_after_event_for_test,
        )

    def correct_fact(
        self,
        *,
        event_id: str,
        user_id: str,
        session_id: str | None,
        subject: str,
        attribute: str,
        value: Any,
        valid_from: datetime,
        system_time: datetime | None = None,
        fail_after_event_for_test: bool = False,
    ) -> WriteResult:
        return self._write_fact(
            event_id=event_id,
            user_id=user_id,
            session_id=session_id,
            subject=subject,
            attribute=attribute,
            value=value,
            operation=MemoryOperation.CORRECT,
            valid_from=valid_from,
            system_time=system_time,
            fail_after_event_for_test=fail_after_event_for_test,
        )

    def forget_fact(
        self,
        *,
        event_id: str,
        user_id: str,
        session_id: str | None,
        subject: str,
        attribute: str,
        valid_from: datetime | None = None,
        system_time: datetime | None = None,
        fail_after_event_for_test: bool = False,
    ) -> WriteResult:
        return self._write_fact(
            event_id=event_id,
            user_id=user_id,
            session_id=session_id,
            subject=subject,
            attribute=attribute,
            value=None,
            operation=MemoryOperation.FORGET,
            valid_from=valid_from,
            system_time=system_time,
            fail_after_event_for_test=fail_after_event_for_test,
        )

    def _write_fact(
        self,
        *,
        event_id: str,
        user_id: str,
        session_id: str | None,
        subject: str,
        attribute: str,
        value: Any,
        operation: MemoryOperation,
        valid_from: datetime | None,
        system_time: datetime | None,
        fail_after_event_for_test: bool,
    ) -> WriteResult:
        payload = {
            "event_id": event_id,
            "user_id": user_id,
            "session_id": session_id,
            "subject": subject,
            "attribute": attribute,
            "value": value,
            "operation": operation.value,
            "valid_from": _dt_to_text(valid_from) if valid_from is not None else None,
            "system_from": _dt_to_text(system_time) if system_time is not None else None,
        }
        request_hash = _request_hash(payload)
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                effective_system_time = _normalize_dt(system_time)
                effective_valid_from = (
                    _normalize_dt(valid_from) if valid_from is not None else effective_system_time
                )
                prior = conn.execute(
                    "SELECT request_hash, result_json FROM memory_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if prior is not None:
                    if prior["request_hash"] != request_hash:
                        raise IdempotencyConflict(f"event_id {event_id!r} was already used")
                    result = json.loads(prior["result_json"])
                    conn.execute("COMMIT")
                    return WriteResult(
                        event_id=event_id,
                        operation=MemoryOperation(result["operation"]),
                        idempotent=True,
                        current_fact=self._get_current_fact_on_connection(
                            conn, user_id, subject, attribute, _utc_now(), _utc_now()
                        ),
                    )

                result_json = _json_to_text({"operation": operation.value, "idempotent": False})
                conn.execute(
                    """
                    INSERT INTO memory_events(
                        event_id,user_id,session_id,subject,attribute,value_json,operation,
                        valid_from,valid_to,system_from,system_to,created_at,request_hash,result_json
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id,
                        user_id,
                        session_id,
                        subject,
                        attribute,
                        None if operation == MemoryOperation.FORGET else _json_to_text(value),
                        operation.value,
                        _dt_to_text(effective_valid_from),
                        None,
                        _dt_to_text(effective_system_time),
                        None,
                        _dt_to_text(effective_system_time),
                        request_hash,
                        result_json,
                    ),
                )
                if fail_after_event_for_test:
                    raise RuntimeError("injected transaction failure")

                self._close_overlapping_system_current_versions(
                    conn,
                    event_id=event_id,
                    user_id=user_id,
                    subject=subject,
                    attribute=attribute,
                    valid_from=effective_valid_from,
                    system_time=effective_system_time,
                )
                if operation != MemoryOperation.FORGET:
                    self._insert_fact_version(
                        conn,
                        event_id=event_id,
                        user_id=user_id,
                        subject=subject,
                        attribute=attribute,
                        value=value,
                        valid_from=effective_valid_from,
                        valid_to=None,
                        system_from=effective_system_time,
                    )
                current = self._get_current_fact_on_connection(
                    conn, user_id, subject, attribute, _utc_now(), effective_system_time
                )
                conn.execute("COMMIT")
                return WriteResult(event_id, operation, False, current)
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def _close_overlapping_system_current_versions(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        user_id: str,
        subject: str,
        attribute: str,
        valid_from: datetime,
        system_time: datetime,
    ) -> None:
        valid_text = _dt_to_text(valid_from)
        rows = conn.execute(
            """
            SELECT * FROM structured_facts
            WHERE user_id = ?
              AND subject = ?
              AND attribute = ?
              AND system_to IS NULL
              AND (valid_to IS NULL OR valid_to > ?)
            ORDER BY valid_from, fact_version_id
            """,
            (user_id, subject, attribute, valid_text),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE structured_facts SET system_to = ? WHERE fact_version_id = ?",
                (_dt_to_text(system_time), row["fact_version_id"]),
            )
            row_valid_from = _dt_from_text(row["valid_from"])
            if row_valid_from < valid_from:
                self._insert_fact_version(
                    conn,
                    event_id=event_id,
                    user_id=user_id,
                    subject=subject,
                    attribute=attribute,
                    value=_json_from_text(row["value_json"]),
                    valid_from=row_valid_from,
                    valid_to=valid_from,
                    system_from=system_time,
                )

    @staticmethod
    def _insert_fact_version(
        conn: sqlite3.Connection,
        *,
        event_id: str,
        user_id: str,
        subject: str,
        attribute: str,
        value: Any,
        valid_from: datetime,
        valid_to: datetime | None,
        system_from: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO structured_facts(
                event_id,user_id,subject,attribute,value_json,
                valid_from,valid_to,system_from,system_to,created_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                user_id,
                subject,
                attribute,
                _json_to_text(value),
                _dt_to_text(valid_from),
                _dt_to_text(valid_to),
                _dt_to_text(system_from),
                None,
                _dt_to_text(system_from),
            ),
        )

    @staticmethod
    def _get_current_fact_on_connection(
        conn: sqlite3.Connection,
        user_id: str,
        subject: str,
        attribute: str,
        valid_time: datetime,
        system_time: datetime,
    ) -> FactVersion | None:
        valid_text = _dt_to_text(valid_time)
        system_text = _dt_to_text(system_time)
        row = conn.execute(
            """
            SELECT * FROM structured_facts
            WHERE user_id = ?
              AND subject = ?
              AND attribute = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR valid_to > ?)
              AND system_from <= ?
              AND (system_to IS NULL OR system_to > ?)
            ORDER BY system_from DESC, fact_version_id DESC
            LIMIT 1
            """,
            (user_id, subject, attribute, valid_text, valid_text, system_text, system_text),
        ).fetchone()
        return _row_to_fact(row)
