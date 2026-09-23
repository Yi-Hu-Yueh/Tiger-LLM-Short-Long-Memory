"""Phase 1D runtime integration gate.

This service connects the untrusted memory extractor, deterministic validator,
and Phase 1A Memory Core. It is intentionally small: no UI, RAG, vectors,
summaries, agents, or Memory Core redesign.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Any, Mapping

from memory_core import MemoryOperation, SQLiteMemoryCore
from memory_extractor import MemoryExtractor, create_memory_extractor_from_env
from memory_validator import CandidateOperation, MemoryOperationValidator


CORE_SUBJECT = "profile"


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    memory_written: bool
    candidate_json: Mapping[str, Any] | None = None
    validator_accepted: bool | None = None
    operation: str | None = None
    attribute: str | None = None
    value: Any = None
    reason: str | None = None
    validator_reasons: tuple[str, ...] = ()
    event_id: str | None = None
    idempotent: bool = False
    latency_seconds: float = 0.0
    api_calls: int = 0
    token_usage: Mapping[str, int] | None = None
    failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_written": self.memory_written,
            "candidate_json": self.candidate_json,
            "validator_accepted": self.validator_accepted,
            "operation": self.operation,
            "attribute": self.attribute,
            "value": self.value,
            "reason": self.reason,
            "validator_reasons": self.validator_reasons,
            "event_id": self.event_id,
            "idempotent": self.idempotent,
            "latency_seconds": self.latency_seconds,
            "api_calls": self.api_calls,
            "token_usage": self.token_usage or {},
            "failure": self.failure,
        }


class MemoryRuntimeService:
    """Service layer proving extractor -> validator -> Memory Core integration."""

    def __init__(
        self,
        *,
        core: SQLiteMemoryCore,
        extractor: MemoryExtractor | None = None,
        validator: MemoryOperationValidator | None = None,
    ):
        self.core = core
        self.extractor = extractor or create_memory_extractor_from_env()
        self.validator = validator or MemoryOperationValidator()
        self.fail_next_write_for_test = False
        self._last_system_time: datetime | None = None
        self._event_system_times: dict[str, datetime] = {}

    def process_user_message(self, user_id: str, session_id: str, message: str) -> dict[str, Any]:
        try:
            current_context = self.get_memory_context(user_id)
            if hasattr(self.extractor, "extract_with_context"):
                candidate_json = self.extractor.extract_with_context(message, current_context)
            else:
                candidate_json = self.extractor.extract(message)
        except Exception as exc:
            return RuntimeResult(
                memory_written=False,
                reason="extraction_failed",
                failure=type(exc).__name__ + ": " + str(exc),
            ).to_dict()

        metadata = getattr(self.extractor, "last_metadata", {}) or {}
        latency = float(metadata.get("latency_seconds") or 0.0)
        api_calls = int(metadata.get("request_count") or 0)
        token_usage = metadata.get("usage") or {}

        validation = self.validator.validate(message, candidate_json)
        if not validation.accepted:
            return RuntimeResult(
                memory_written=False,
                candidate_json=candidate_json,
                validator_accepted=False,
                operation=str(candidate_json.get("operation")),
                attribute=candidate_json.get("attribute") if isinstance(candidate_json, Mapping) else None,
                value=candidate_json.get("value") if isinstance(candidate_json, Mapping) else None,
                reason="validator_rejected",
                validator_reasons=validation.reasons,
                latency_seconds=latency,
                api_calls=api_calls,
                token_usage=token_usage,
            ).to_dict()

        candidate = validation.candidate
        if candidate is None or candidate.operation in {
            CandidateOperation.IGNORE,
            CandidateOperation.QUERY,
            CandidateOperation.NO_OP,
        }:
            return RuntimeResult(
                memory_written=False,
                candidate_json=candidate_json,
                validator_accepted=True,
                operation=candidate.operation.value if candidate else None,
                attribute=candidate.attribute if candidate else None,
                value=candidate.value if candidate else None,
                reason="safe_non_write",
                validator_reasons=validation.reasons,
                latency_seconds=latency,
                api_calls=api_calls,
                token_usage=token_usage,
            ).to_dict()

        event_id = _event_id(user_id, session_id, message, candidate_json)
        valid_from = _parse_valid_from(candidate.valid_from)
        try:
            write = self._write_candidate(
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                candidate=candidate,
                valid_from=valid_from,
            )
        except Exception as exc:
            return RuntimeResult(
                memory_written=False,
                candidate_json=candidate_json,
                validator_accepted=True,
                operation=candidate.operation.value,
                attribute=candidate.attribute,
                value=candidate.value,
                reason="database_write_failed",
                validator_reasons=validation.reasons,
                event_id=event_id,
                latency_seconds=latency,
                api_calls=api_calls,
                token_usage=token_usage,
                failure=type(exc).__name__ + ": " + str(exc),
            ).to_dict()

        return RuntimeResult(
            memory_written=True,
            candidate_json=candidate_json,
            validator_accepted=True,
            operation=candidate.operation.value,
            attribute=candidate.attribute,
            value=candidate.value,
            reason="committed",
            validator_reasons=validation.reasons,
            event_id=event_id,
            idempotent=write.idempotent,
            latency_seconds=latency,
            api_calls=api_calls,
            token_usage=token_usage,
        ).to_dict()

    def get_memory_context(self, user_id: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self.core.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT attribute, value_json
                FROM structured_facts
                WHERE user_id = ?
                  AND subject = ?
                  AND valid_to IS NULL
                  AND system_to IS NULL
                ORDER BY attribute
                """,
                (user_id, CORE_SUBJECT),
            ).fetchall()
        return {str(attribute): json.loads(value_json) for attribute, value_json in rows}

    def _write_candidate(
        self,
        *,
        event_id: str,
        user_id: str,
        session_id: str,
        candidate,
        valid_from: datetime | None,
    ):
        fail = self.fail_next_write_for_test
        self.fail_next_write_for_test = False
        operation = MemoryOperation(candidate.operation.value)
        system_time = self._event_system_times.setdefault(event_id, self._next_system_time())
        if operation in {MemoryOperation.SET, MemoryOperation.REPLACE}:
            return self.core.append_or_replace_fact(
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                subject=CORE_SUBJECT,
                attribute=candidate.attribute,
                value=candidate.value,
                valid_from=valid_from,
                system_time=system_time,
                operation=operation,
                fail_after_event_for_test=fail,
            )
        if operation == MemoryOperation.CORRECT:
            return self.core.correct_fact(
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                subject=CORE_SUBJECT,
                attribute=candidate.attribute,
                value=candidate.value,
                valid_from=valid_from or datetime.now(timezone.utc),
                system_time=system_time,
                fail_after_event_for_test=fail,
            )
        if operation == MemoryOperation.FORGET:
            return self.core.forget_fact(
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                subject=CORE_SUBJECT,
                attribute=candidate.attribute,
                valid_from=valid_from,
                system_time=system_time,
                fail_after_event_for_test=fail,
            )
        raise ValueError(f"unsupported write operation: {operation}")

    def _next_system_time(self) -> datetime:
        now = datetime.now(timezone.utc)
        if self._last_system_time is not None and now <= self._last_system_time:
            now = self._last_system_time + timedelta(microseconds=1)
        self._last_system_time = now
        return now


def _event_id(user_id: str, session_id: str, message: str, candidate_json: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "candidate": candidate_json,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "runtime-" + hashlib.sha256(payload).hexdigest()


def _parse_valid_from(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
