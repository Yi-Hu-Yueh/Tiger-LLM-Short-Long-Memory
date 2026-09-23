from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory_core import SQLiteMemoryCore
from memory_extractor import MemoryExtractor, MockMemoryExtractor
from memory_runtime import CORE_SUBJECT, MemoryRuntimeService


def candidate(
    operation,
    attribute=None,
    value=None,
    *,
    subject="user",
    confidence=0.9,
    reason="runtime fixture",
    valid_from=None,
    valid_to=None,
):
    return {
        "operation": operation,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "confidence": confidence,
        "reason": reason,
        "valid_time": {"from": valid_from, "to": valid_to},
    }


def dt(day: int) -> str:
    return datetime(2026, 9, day, tzinfo=timezone.utc).isoformat()


class FailingExtractor(MemoryExtractor):
    last_metadata = {"request_count": 0, "latency_seconds": 0.0}

    def extract(self, text: str):
        raise RuntimeError("extractor unavailable")


@pytest.fixture()
def runtime(tmp_path):
    responses = {
        "我住台北": candidate("set", "city", "台北"),
        "我搬到新竹": candidate("replace", "city", "新竹"),
        "更正，我現在住台中": candidate("correct", "city", "台中", valid_from=dt(22)),
        "忘記我的地址": candidate("forget", "city", None),
        "我下個月搬去台南": candidate("replace", "city", "台南"),
        "我住哪裡?": candidate("query", "city", None),
        "我現在住哪?": candidate("query", "city", None),
    }
    core = SQLiteMemoryCore(tmp_path / "phase-1d-runtime.db")
    return MemoryRuntimeService(core=core, extractor=MockMemoryExtractor(responses))


def test_end_to_end_write_and_read(runtime):
    result = runtime.process_user_message("user1", "session-a", "我住台北")

    assert result["memory_written"] is True
    assert result["operation"] == "set"
    assert result["attribute"] == "city"
    assert result["value"] == "台北"
    assert runtime.get_memory_context("user1") == {"city": "台北"}


def test_cross_session_persistence(runtime):
    runtime.process_user_message("user1", "session-a", "我住台北")

    context = runtime.get_memory_context("user1")
    question_result = runtime.process_user_message("user1", "session-b", "我住哪裡?")

    assert context == {"city": "台北"}
    assert question_result["memory_written"] is False
    assert question_result["reason"] == "safe_non_write"


def test_state_replacement_preserves_history(runtime):
    runtime.process_user_message("user1", "session-a", "我住台北")
    runtime.process_user_message("user1", "session-a", "我搬到新竹")

    assert runtime.get_memory_context("user1") == {"city": "新竹"}
    history = runtime.core.get_fact_history("user1", CORE_SUBJECT, "city")
    values = [fact.value for fact in history]
    assert "台北" in values
    assert "新竹" in values


def test_correction_keeps_prior_history(runtime):
    runtime.process_user_message("user1", "session-a", "我住台北")
    runtime.process_user_message("user1", "session-a", "我搬到新竹")
    result = runtime.process_user_message("user1", "session-a", "更正，我現在住台中")

    assert result["memory_written"] is True
    assert runtime.get_memory_context("user1") == {"city": "台中"}
    values = [fact.value for fact in runtime.core.get_fact_history("user1", CORE_SUBJECT, "city")]
    assert "台北" in values
    assert "新竹" in values
    assert "台中" in values


def test_forget_removes_current_and_preserves_history(runtime):
    runtime.process_user_message("user1", "session-a", "我住台北")
    runtime.process_user_message("user1", "session-a", "我搬到新竹")
    result = runtime.process_user_message("user1", "session-a", "忘記我的地址")

    assert result["memory_written"] is True
    assert runtime.get_memory_context("user1") == {}
    values = [fact.value for fact in runtime.core.get_fact_history("user1", CORE_SUBJECT, "city")]
    assert "台北" in values
    assert "新竹" in values


def test_validator_rejected_write_never_reaches_memory_core(runtime):
    result = runtime.process_user_message("user1", "session-a", "我下個月搬去台南")

    assert result["memory_written"] is False
    assert result["reason"] == "validator_rejected"
    assert runtime.get_memory_context("user1") == {}
    assert runtime.core.get_fact_history("user1", CORE_SUBJECT, "city") == []


def test_extraction_failure_creates_no_memory_write(tmp_path):
    core = SQLiteMemoryCore(tmp_path / "phase-1d-extract-fail.db")
    service = MemoryRuntimeService(core=core, extractor=FailingExtractor())

    result = service.process_user_message("user1", "session-a", "我住台北")

    assert result["memory_written"] is False
    assert result["reason"] == "extraction_failed"
    assert service.get_memory_context("user1") == {}


def test_database_transaction_failure_rolls_back(runtime):
    runtime.fail_next_write_for_test = True

    result = runtime.process_user_message("user1", "session-a", "我住台北")

    assert result["memory_written"] is False
    assert result["reason"] == "database_write_failed"
    assert runtime.get_memory_context("user1") == {}
    assert runtime.core.get_fact_history("user1", CORE_SUBJECT, "city") == []


def test_duplicate_event_replay_does_not_duplicate_memory(runtime):
    first = runtime.process_user_message("user1", "session-a", "我住台北")
    second = runtime.process_user_message("user1", "session-a", "我住台北")

    history = runtime.core.get_fact_history("user1", CORE_SUBJECT, "city")
    assert first["memory_written"] is True
    assert second["memory_written"] is True
    assert second["idempotent"] is True
    assert len(history) == 1


def test_restart_sqlite_persistence(tmp_path):
    db_path = tmp_path / "phase-1d-restart.db"
    responses = {"我住台北": candidate("set", "city", "台北")}
    service = MemoryRuntimeService(
        core=SQLiteMemoryCore(db_path),
        extractor=MockMemoryExtractor(responses),
    )
    service.process_user_message("user1", "session-a", "我住台北")

    reopened = MemoryRuntimeService(
        core=SQLiteMemoryCore(db_path),
        extractor=MockMemoryExtractor(responses),
    )

    assert reopened.get_memory_context("user1") == {"city": "台北"}
