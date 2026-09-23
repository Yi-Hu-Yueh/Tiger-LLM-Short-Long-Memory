from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

import pytest

from memory_core import MemoryOperation, SQLiteMemoryCore


def dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


@pytest.fixture()
def core(tmp_path):
    return SQLiteMemoryCore(tmp_path / "memory-core-poc.db")


def active_current_count(db_path, user_id="user1", subject="profile", attribute="city"):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            """
            SELECT COUNT(*) FROM structured_facts
            WHERE user_id = ?
              AND subject = ?
              AND attribute = ?
              AND valid_to IS NULL
              AND system_to IS NULL
            """,
            (user_id, subject, attribute),
        ).fetchone()[0]


def ledger_count(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0]


def fact_count(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM structured_facts").fetchone()[0]


def test_set_city_current_returns_taipei(core):
    core.append_or_replace_fact(
        event_id="evt-set-city",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )

    current = core.get_current_fact("user1", "profile", "city")

    assert current.value == "Taipei"
    assert current.valid_from == dt(1)
    assert current.system_from == dt(1)


def test_replace_city_preserves_history_and_current(core):
    core.append_or_replace_fact(
        event_id="evt-city-taipei",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )
    core.append_or_replace_fact(
        event_id="evt-city-hsinchu",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Hsinchu",
        valid_from=dt(10),
        system_time=dt(10),
    )

    current = core.get_current_fact("user1", "profile", "city")
    history_values = [fact.value for fact in core.get_fact_history("user1", "profile", "city")]

    assert current.value == "Hsinchu"
    assert "Taipei" in history_values
    assert "Hsinchu" in history_values
    assert active_current_count(core.db_path) == 1


def test_backdated_correction_keeps_valid_and_system_time_distinct(core):
    core.append_or_replace_fact(
        event_id="evt-original-city",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )
    core.correct_fact(
        event_id="evt-correct-city",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Hsinchu",
        valid_from=dt(15),
        system_time=dt(22),
    )

    before_correction_known = core.get_fact_as_known_at(
        "user1", "profile", "city", valid_time=dt(20), system_time=dt(21, 23)
    )
    after_correction_known = core.get_fact_as_known_at(
        "user1", "profile", "city", valid_time=dt(20), system_time=dt(22, 1)
    )
    before_move_after_correction = core.get_fact_as_known_at(
        "user1", "profile", "city", valid_time=dt(10), system_time=dt(22, 1)
    )

    assert before_correction_known.value == "Taipei"
    assert after_correction_known.value == "Hsinchu"
    assert before_move_after_correction.value == "Taipei"


def test_idempotent_event_replay_commits_one_logical_mutation(core):
    kwargs = dict(
        event_id="evt-idempotent",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )

    first = core.append_or_replace_fact(**kwargs)
    second = core.append_or_replace_fact(**kwargs)
    third = core.append_or_replace_fact(**kwargs)

    assert first.idempotent is False
    assert second.idempotent is True
    assert third.idempotent is True
    assert ledger_count(core.db_path) == 1
    assert fact_count(core.db_path) == 1


def test_competing_updates_keep_single_current_state(tmp_path):
    db_path = tmp_path / "concurrency.db"
    SQLiteMemoryCore(db_path).append_or_replace_fact(
        event_id="evt-initial",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )

    def write_city(index):
        service = SQLiteMemoryCore(db_path)
        return service.append_or_replace_fact(
            event_id=f"evt-concurrent-{index}",
            user_id="user1",
            session_id=f"s{index}",
            subject="profile",
            attribute="city",
            value=f"City-{index}",
            valid_from=dt(10, index),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write_city, [1, 2]))

    reopened = SQLiteMemoryCore(db_path)
    current = reopened.get_current_fact("user1", "profile", "city")

    assert {result.current_fact.value for result in results} <= {"City-1", "City-2"}
    assert current.value in {"City-1", "City-2"}
    assert active_current_count(db_path) == 1


def test_write_exception_rolls_back_event_and_fact(core):
    with pytest.raises(RuntimeError, match="injected transaction failure"):
        core.append_or_replace_fact(
            event_id="evt-fail",
            user_id="user1",
            session_id="s1",
            subject="profile",
            attribute="city",
            value="Taipei",
            valid_from=dt(1),
            system_time=dt(1),
            operation=MemoryOperation.SET,
            fail_after_event_for_test=True,
        )

    assert ledger_count(core.db_path) == 0
    assert fact_count(core.db_path) == 0
    assert core.get_current_fact("user1", "profile", "city") is None


def test_reopen_sqlite_preserves_state(tmp_path):
    db_path = tmp_path / "restart.db"
    SQLiteMemoryCore(db_path).append_or_replace_fact(
        event_id="evt-before-restart",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )

    reopened = SQLiteMemoryCore(db_path)

    assert reopened.get_current_fact("user1", "profile", "city").value == "Taipei"
    assert ledger_count(db_path) == 1


def test_forget_closes_current_but_keeps_history(core):
    core.append_or_replace_fact(
        event_id="evt-city",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        value="Taipei",
        valid_from=dt(1),
        system_time=dt(1),
        operation=MemoryOperation.SET,
    )
    core.forget_fact(
        event_id="evt-forget-city",
        user_id="user1",
        session_id="s1",
        subject="profile",
        attribute="city",
        valid_from=dt(12),
        system_time=dt(12),
    )

    current = core.get_current_fact("user1", "profile", "city")
    history = core.get_fact_history("user1", "profile", "city")
    before_forget = core.get_fact_as_known_at(
        "user1", "profile", "city", valid_time=dt(5), system_time=dt(13)
    )

    assert current is None
    assert [fact.value for fact in history].count("Taipei") >= 2
    assert before_forget.value == "Taipei"
    assert ledger_count(core.db_path) == 2
