"""Phase 3D append-only, user-scoped memory audit records and metrics."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from typing import Any, Mapping

from app import utc_now


class AuditEventType(StrEnum):
    MEMORY_CREATED = "MEMORY_CREATED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    MEMORY_REJECTED = "MEMORY_REJECTED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    PROPOSAL_CONFIRMED = "PROPOSAL_CONFIRMED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    audit_id: str
    timestamp: str
    user_id: str
    session_id: str
    event_type: AuditEventType
    source: str
    status: str
    entity_id: str
    details: tuple[tuple[str, str], ...]

    def details_dict(self) -> dict[str, str]:
        return dict(self.details)


COUNTER_NAMES = (
    "memory_write_success",
    "memory_write_failure",
    "proposal_created",
    "proposal_confirmed",
    "proposal_rejected",
    "proposal_expired",
    "validation_failed",
)
LATENCY_NAMES = ("extraction_latency", "validation_latency", "commit_latency")


class AuditMetrics:
    def __init__(self):
        self._lock = threading.RLock()
        self._counters = {name: 0 for name in COUNTER_NAMES}
        self._latencies = {
            name: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0}
            for name in LATENCY_NAMES
        }

    def increment(self, name: str) -> None:
        if name not in self._counters:
            raise ValueError("unknown audit counter")
        with self._lock:
            self._counters[name] += 1

    def observe_latency(self, name: str, seconds: float) -> None:
        if name not in self._latencies or isinstance(seconds, bool) or seconds < 0:
            raise ValueError("invalid latency observation")
        with self._lock:
            metric = self._latencies[name]
            metric["count"] += 1
            metric["total_seconds"] += float(seconds)
            metric["max_seconds"] = max(metric["max_seconds"], float(seconds))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "latencies": {name: dict(values) for name, values in self._latencies.items()},
            }


class MemoryAuditStore:
    """Append-only SQLite audit store; it never opens or mutates Memory Core DBs."""

    _SAFE_DETAIL = re.compile(r"[A-Za-z0-9_.:-]{1,120}\Z")

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_audit_events (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    user_id TEXT NOT NULL CHECK(user_id IN ('user1','user2')),
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_audit_scope
                    ON memory_audit_events(user_id,session_id,timestamp,audit_id);
                CREATE TRIGGER IF NOT EXISTS trg_memory_audit_immutable_update
                    BEFORE UPDATE ON memory_audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS trg_memory_audit_immutable_delete
                    BEFORE DELETE ON memory_audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
                """
            )
            conn.commit()

    def record(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: AuditEventType,
        source: str,
        status: str,
        entity_id: str,
        details: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        normalized = self._normalize_details(details or {})
        event = AuditEvent(
            audit_id=uuid.uuid4().hex,
            timestamp=utc_now(),
            user_id=user_id,
            session_id=session_id,
            event_type=AuditEventType(event_type),
            source=self._safe_token(source),
            status=self._safe_token(status),
            entity_id=self._safe_token(entity_id),
            details=tuple(sorted(normalized.items())),
        )
        with self._lock, closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "INSERT INTO memory_audit_events("
                "audit_id,timestamp,user_id,session_id,event_type,source,status,entity_id,details_json"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    event.audit_id,
                    event.timestamp,
                    event.user_id,
                    event.session_id,
                    event.event_type.value,
                    event.source,
                    event.status,
                    event.entity_id,
                    json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                ),
            )
            conn.commit()
        return event

    def list_events(self, *, user_id: str, session_id: str | None = None) -> list[AuditEvent]:
        sql = (
            "SELECT audit_id,timestamp,user_id,session_id,event_type,source,status,entity_id,details_json "
            "FROM memory_audit_events WHERE user_id = ?"
        )
        parameters: tuple[Any, ...] = (user_id,)
        if session_id is not None:
            sql += " AND session_id = ?"
            parameters += (session_id,)
        sql += " ORDER BY sequence_id"
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(sql, parameters).fetchall()
        return [
            AuditEvent(
                audit_id=row[0], timestamp=row[1], user_id=row[2], session_id=row[3],
                event_type=AuditEventType(row[4]), source=row[5], status=row[6], entity_id=row[7],
                details=tuple(sorted(json.loads(row[8]).items())),
            )
            for row in rows
        ]

    @classmethod
    def _safe_token(cls, value: Any) -> str:
        if not isinstance(value, str) or cls._SAFE_DETAIL.fullmatch(value) is None:
            raise ValueError("audit field must be a safe diagnostic token")
        return value

    @classmethod
    def _normalize_details(cls, details: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(details, Mapping) or len(details) > 12:
            raise ValueError("invalid audit details")
        normalized: dict[str, str] = {}
        for key, value in details.items():
            normalized[cls._safe_token(key)] = cls._safe_token(str(value))
        return normalized
