"""Generic SQLite execution of already-resolved, authorized typed commands.

This is not a model-facing writer. A caller must perform the governed semantic,
registry, risk, and human-confirmation checks before invoking changed writes.
Neither semantic keys nor entity IDs replace the stable memory lineage ID.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator
from uuid import uuid4


ALLOWED_USERS = frozenset(("user1", "user2"))


class Status(StrEnum):
    APPLIED = "APPLIED"
    FOUND = "FOUND"
    NO_OP = "NO_OP"
    NOT_FOUND = "NOT_FOUND"
    NO_PREVIOUS = "NO_PREVIOUS"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class ScalarVersion:
    version_id: int
    memory_id: str
    value: Any
    predecessor_version_id: int | None
    status: str


@dataclass(frozen=True, slots=True)
class Member:
    member_id: str
    member_label: str


@dataclass(frozen=True, slots=True)
class Result:
    status: Status
    operation: str
    user_id: str
    mutation_count: int = 0
    memory_id: str | None = None
    collection_id: str | None = None
    entity_id: str | None = None
    semantic_key: str | None = None
    version_id: int | None = None
    evidence_ids: tuple[int, ...] = ()
    value: Any = None
    timeline: tuple[ScalarVersion, ...] = ()
    members: tuple[Member, ...] = ()
    count: int | None = None
    reason: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _identifier(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty exact string")
    return value


def _scalar_json(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple)):
        raise ValueError("scalar value must be a non-null JSON scalar")
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("scalar value must be a JSON scalar") from exc


def _version(row: sqlite3.Row) -> ScalarVersion:
    return ScalarVersion(
        int(row["version_id"]), str(row["memory_id"]),
        json.loads(row["value_json"]), row["predecessor_version_id"],
        str(row["status"]),
    )


class MemoryV2Core:
    """SQLite-backed generic algebra, deliberately separate from the old runtime."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scalar_lineages (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    entity_id TEXT,
                    semantic_key TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_scalar_lookup
                    ON scalar_lineages(user_id, semantic_key, entity_id);
                CREATE TABLE IF NOT EXISTS scalar_versions (
                    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL REFERENCES scalar_lineages(memory_id),
                    value_json TEXT NOT NULL,
                    predecessor_version_id INTEGER REFERENCES scalar_versions(version_id),
                    status TEXT NOT NULL CHECK(status IN ('CURRENT','HISTORICAL')),
                    created_at TEXT NOT NULL,
                    superseded_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_scalar_current
                    ON scalar_versions(memory_id) WHERE status='CURRENT';
                CREATE TABLE IF NOT EXISTS collections (
                    collection_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    entity_id TEXT,
                    semantic_key TEXT NOT NULL,
                    membership_mode TEXT NOT NULL CHECK(membership_mode IN ('NAMED','COUNT_ONLY')),
                    declared_count INTEGER,
                    display_label TEXT,
                    created_at TEXT NOT NULL,
                    CHECK ((membership_mode='NAMED' AND declared_count IS NULL)
                        OR (membership_mode='COUNT_ONLY' AND declared_count >= 0))
                );
                CREATE INDEX IF NOT EXISTS ix_collection_lookup
                    ON collections(user_id, semantic_key, entity_id);
                CREATE TABLE IF NOT EXISTS membership_versions (
                    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_id TEXT NOT NULL REFERENCES collections(collection_id),
                    member_id TEXT NOT NULL,
                    member_label TEXT NOT NULL,
                    predecessor_version_id INTEGER REFERENCES membership_versions(version_id),
                    status TEXT NOT NULL CHECK(status IN ('CURRENT','HISTORICAL')),
                    created_at TEXT NOT NULL,
                    superseded_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_active_membership
                    ON membership_versions(collection_id,member_id) WHERE status='CURRENT';
                """
            )
            if "display_label" not in {row[1] for row in conn.execute("PRAGMA table_info(collections)")}:
                conn.execute("ALTER TABLE collections ADD COLUMN display_label TEXT")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _user(user_id: str) -> str:
        if user_id not in ALLOWED_USERS:
            raise ValueError("user is outside approved prototype scope")
        return user_id

    @staticmethod
    def _lineages(
        conn: sqlite3.Connection, user_id: str, memory_id: str | None,
        entity_id: str | None, semantic_key: str | None,
    ) -> list[sqlite3.Row]:
        if memory_id is not None:
            rows = conn.execute(
                "SELECT * FROM scalar_lineages WHERE user_id=? AND memory_id=?",
                (user_id, memory_id),
            ).fetchall()
            return [r for r in rows if (entity_id is None or r["entity_id"] == entity_id)
                    and (semantic_key is None or r["semantic_key"] == semantic_key)]
        if semantic_key is None:
            return []
        if entity_id is None:
            return conn.execute(
                "SELECT * FROM scalar_lineages WHERE user_id=? AND semantic_key=?",
                (user_id, semantic_key),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM scalar_lineages WHERE user_id=? AND semantic_key=? AND entity_id=?",
            (user_id, semantic_key, entity_id),
        ).fetchall()

    @staticmethod
    def _current(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM scalar_versions WHERE memory_id=? AND status='CURRENT'",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("scalar lineage has no Current version")
        return row

    @staticmethod
    def _scalar_result(
        status: Status, operation: str, user_id: str, row: sqlite3.Row | None = None,
        **kwargs: Any,
    ) -> Result:
        return Result(
            status, operation, user_id,
            memory_id=row["memory_id"] if row is not None else kwargs.pop("memory_id", None),
            entity_id=row["entity_id"] if row is not None else kwargs.pop("entity_id", None),
            semantic_key=row["semantic_key"] if row is not None else kwargs.pop("semantic_key", None),
            **kwargs,
        )

    def _create_scalar(
        self, conn: sqlite3.Connection, user_id: str, entity_id: str | None,
        semantic_key: str, value_json: str, operation: str,
    ) -> Result:
        memory_id = uuid4().hex
        now = _now()
        conn.execute(
            "INSERT INTO scalar_lineages VALUES (?,?,?,?,?)",
            (memory_id, user_id, entity_id, semantic_key, now),
        )
        cursor = conn.execute(
            "INSERT INTO scalar_versions(memory_id,value_json,predecessor_version_id,status,created_at) "
            "VALUES (?,?,NULL,'CURRENT',?)",
            (memory_id, value_json, now),
        )
        version_id = int(cursor.lastrowid)
        return Result(
            Status.APPLIED, operation, user_id, mutation_count=1,
            memory_id=memory_id, entity_id=entity_id, semantic_key=semantic_key,
            version_id=version_id, evidence_ids=(version_id,), value=json.loads(value_json),
        )

    def create_scalar(
        self, user_id: str, semantic_key: str, value: Any,
        *, entity_id: str | None = None, max_current: int | None = None,
    ) -> Result:
        self._user(user_id)
        _identifier(semantic_key, "semantic_key")
        if entity_id is not None:
            _identifier(entity_id, "entity_id")
        if max_current is not None and (type(max_current) is not int or max_current < 1):
            raise ValueError("max_current must be a positive integer")
        value_json = _scalar_json(value)
        with self._write() as conn:
            # An explicit duplicate target is a conflict, not an invented new lineage.
            rows = self._lineages(conn, user_id, None, entity_id, semantic_key)
            if any(r["entity_id"] == entity_id for r in rows):
                return Result(Status.CONFLICT, "CREATE_SCALAR", user_id, entity_id=entity_id,
                              semantic_key=semantic_key, reason="TARGET_ALREADY_EXISTS")
            if max_current is not None:
                current_count = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM scalar_lineages WHERE user_id=?) + "
                    "(SELECT COUNT(*) FROM collections WHERE user_id=?)",
                    (user_id, user_id),
                ).fetchone()[0]
                if current_count >= max_current:
                    return Result(Status.CONFLICT, "CREATE_SCALAR", user_id,
                                  entity_id=entity_id, semantic_key=semantic_key,
                                  reason="USER_MEMORY_LIMIT")
            return self._create_scalar(conn, user_id, entity_id, semantic_key, value_json,
                                       "CREATE_SCALAR")

    def set_scalar(
        self, user_id: str, value: Any, *, memory_id: str | None = None,
        entity_id: str | None = None, semantic_key: str | None = None,
        expected_version_id: int | None = None,
    ) -> Result:
        self._user(user_id)
        if memory_id is not None:
            _identifier(memory_id, "memory_id")
        if entity_id is not None:
            _identifier(entity_id, "entity_id")
        if semantic_key is not None:
            _identifier(semantic_key, "semantic_key")
        if expected_version_id is not None and (
            type(expected_version_id) is not int or expected_version_id <= 0
        ):
            raise ValueError("expected_version_id must be a positive integer")
        if memory_id is None and semantic_key is None:
            return Result(Status.AMBIGUOUS_TARGET, "SET_SCALAR", user_id,
                          reason="MISSING_TARGET")
        value_json = _scalar_json(value)
        with self._write() as conn:
            rows = self._lineages(conn, user_id, memory_id, entity_id, semantic_key)
            if len(rows) > 1:
                return Result(Status.AMBIGUOUS_TARGET, "SET_SCALAR", user_id,
                              semantic_key=semantic_key, reason="MULTIPLE_LINEAGES")
            if not rows:
                if memory_id is not None or expected_version_id is not None:
                    return Result(Status.NOT_FOUND, "SET_SCALAR", user_id,
                                  memory_id=memory_id, reason="LINEAGE_NOT_FOUND")
                return self._create_scalar(conn, user_id, entity_id, semantic_key,
                                           value_json, "SET_SCALAR")
            lineage = rows[0]
            current = self._current(conn, lineage["memory_id"])
            if expected_version_id is not None and current["version_id"] != expected_version_id:
                return self._scalar_result(
                    Status.CONFLICT, "SET_SCALAR", user_id, lineage,
                    version_id=int(current["version_id"]), reason="STALE_VERSION",
                )
            if current["value_json"] == value_json:
                return self._scalar_result(
                    Status.NO_OP, "SET_SCALAR", user_id, lineage,
                    version_id=int(current["version_id"]),
                    evidence_ids=(int(current["version_id"]),),
                    value=json.loads(value_json),
                )
            now = _now()
            conn.execute(
                "UPDATE scalar_versions SET status='HISTORICAL',superseded_at=? "
                "WHERE version_id=? AND status='CURRENT'",
                (now, current["version_id"]),
            )
            cursor = conn.execute(
                "INSERT INTO scalar_versions(memory_id,value_json,predecessor_version_id,status,created_at) "
                "VALUES (?,?,?,'CURRENT',?)",
                (lineage["memory_id"], value_json, current["version_id"], now),
            )
            version_id = int(cursor.lastrowid)
            return self._scalar_result(
                Status.APPLIED, "SET_SCALAR", user_id, lineage,
                mutation_count=1, version_id=version_id,
                evidence_ids=(int(current["version_id"]), version_id),
                value=json.loads(value_json),
            )

    def _read_scalar(
        self, operation: str, user_id: str, memory_id: str | None,
        entity_id: str | None, semantic_key: str | None,
    ) -> Result:
        self._user(user_id)
        if memory_id is not None:
            _identifier(memory_id, "memory_id")
        if entity_id is not None:
            _identifier(entity_id, "entity_id")
        if semantic_key is not None:
            _identifier(semantic_key, "semantic_key")
        if memory_id is None and semantic_key is None:
            return Result(Status.AMBIGUOUS_TARGET, operation, user_id,
                          reason="MISSING_TARGET")
        with self._connection() as conn:
            rows = self._lineages(conn, user_id, memory_id, entity_id, semantic_key)
            if len(rows) > 1:
                return Result(Status.AMBIGUOUS_TARGET, operation, user_id,
                              semantic_key=semantic_key, reason="MULTIPLE_LINEAGES")
            if not rows:
                return Result(Status.NOT_FOUND, operation, user_id,
                              memory_id=memory_id, entity_id=entity_id,
                              semantic_key=semantic_key)
            lineage = rows[0]
            current = self._current(conn, lineage["memory_id"])
            if operation == "GET_PREVIOUS_SCALAR":
                predecessor_id = current["predecessor_version_id"]
                if predecessor_id is None:
                    return self._scalar_result(Status.NO_PREVIOUS, operation, user_id,
                                               lineage, reason="NO_PREDECESSOR")
                previous = conn.execute(
                    "SELECT * FROM scalar_versions WHERE version_id=? AND memory_id=?",
                    (predecessor_id, lineage["memory_id"]),
                ).fetchone()
                if previous is None:
                    raise RuntimeError("broken predecessor chain")
                chosen = previous
            else:
                chosen = current
            if operation == "GET_SCALAR_TIMELINE":
                versions = tuple(_version(r) for r in conn.execute(
                    "SELECT * FROM scalar_versions WHERE memory_id=? ORDER BY version_id",
                    (lineage["memory_id"],),
                ).fetchall())
                return self._scalar_result(
                    Status.FOUND, operation, user_id, lineage,
                    version_id=int(current["version_id"]),
                    evidence_ids=tuple(v.version_id for v in versions), timeline=versions,
                )
            return self._scalar_result(
                Status.FOUND, operation, user_id, lineage,
                version_id=int(chosen["version_id"]),
                evidence_ids=(int(chosen["version_id"]),),
                value=json.loads(chosen["value_json"]),
            )

    def get_current_scalar(
        self, user_id: str, *, memory_id: str | None = None,
        entity_id: str | None = None, semantic_key: str | None = None,
    ) -> Result:
        return self._read_scalar("GET_CURRENT_SCALAR", user_id, memory_id, entity_id,
                                 semantic_key)

    def get_previous_scalar(
        self, user_id: str, *, memory_id: str | None = None,
        entity_id: str | None = None, semantic_key: str | None = None,
    ) -> Result:
        if memory_id is None:
            self._user(user_id)
            return Result(Status.AMBIGUOUS_TARGET, "GET_PREVIOUS_SCALAR", user_id,
                          reason="MEMORY_ID_REQUIRED")
        return self._read_scalar("GET_PREVIOUS_SCALAR", user_id, memory_id, entity_id,
                                 semantic_key)

    def get_scalar_timeline(
        self, user_id: str, *, memory_id: str | None = None,
        entity_id: str | None = None, semantic_key: str | None = None,
    ) -> Result:
        return self._read_scalar("GET_SCALAR_TIMELINE", user_id, memory_id, entity_id,
                                 semantic_key)

    def no_op(self, user_id: str, *, reason: str = "EXPLICIT_NO_OP") -> Result:
        self._user(user_id)
        return Result(Status.NO_OP, "NO_OP", user_id, reason=reason)

    def create_collection(
        self, user_id: str, semantic_key: str, *, entity_id: str | None = None,
        membership_mode: str = "NAMED", declared_count: int | None = None,
        display_label: str | None = None, max_current: int | None = None,
        collection_id: str | None = None,
    ) -> Result:
        self._user(user_id)
        _identifier(semantic_key, "semantic_key")
        if entity_id is not None:
            _identifier(entity_id, "entity_id")
        if membership_mode not in ("NAMED", "COUNT_ONLY"):
            raise ValueError("unsupported membership mode")
        if membership_mode == "NAMED" and declared_count is not None:
            raise ValueError("named membership count is derived")
        if membership_mode == "COUNT_ONLY" and (
            type(declared_count) is not int or not 0 <= declared_count <= 1_000_000_000
        ):
            raise ValueError("count-only collection requires bounded declared count")
        if display_label is not None:
            _identifier(display_label, "display_label")
            if len(display_label) > 160:
                raise ValueError("display_label exceeds limit")
        if max_current is not None and (type(max_current) is not int or max_current < 1):
            raise ValueError("max_current must be a positive integer")
        if collection_id is not None:
            _identifier(collection_id, "collection_id")
        with self._write() as conn:
            if collection_id is not None and conn.execute(
                "SELECT 1 FROM collections WHERE collection_id=?", (collection_id,)
            ).fetchone():
                return Result(Status.CONFLICT, "CREATE_COLLECTION", user_id,
                              collection_id=collection_id, reason="TARGET_ALREADY_EXISTS")
            if entity_id is None:
                prior = conn.execute(
                    "SELECT 1 FROM collections WHERE user_id=? AND semantic_key=? AND entity_id IS NULL",
                    (user_id, semantic_key),
                ).fetchone()
            else:
                prior = conn.execute(
                    "SELECT 1 FROM collections WHERE user_id=? AND semantic_key=? AND entity_id=?",
                    (user_id, semantic_key, entity_id),
                ).fetchone()
            if prior:
                return Result(Status.CONFLICT, "CREATE_COLLECTION", user_id,
                              entity_id=entity_id, semantic_key=semantic_key,
                              reason="TARGET_ALREADY_EXISTS")
            if max_current is not None:
                current_count = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM scalar_lineages WHERE user_id=?) + "
                    "(SELECT COUNT(*) FROM collections WHERE user_id=?)",
                    (user_id, user_id),
                ).fetchone()[0]
                if current_count >= max_current:
                    return Result(Status.CONFLICT, "CREATE_COLLECTION", user_id,
                                  reason="USER_MEMORY_LIMIT")
            collection_id = collection_id or uuid4().hex
            # The collection handle is also its stable memory lineage ID;
            # membership rows cannot become a separate memory authority.
            conn.execute(
                "INSERT INTO collections "
                "(collection_id,memory_id,user_id,entity_id,semantic_key,membership_mode,"
                "declared_count,display_label,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (collection_id, collection_id, user_id, entity_id, semantic_key, membership_mode,
                 declared_count, display_label, _now()),
            )
            return Result(Status.APPLIED, "CREATE_COLLECTION", user_id,
                          mutation_count=1, memory_id=collection_id,
                          collection_id=collection_id,
                          entity_id=entity_id, semantic_key=semantic_key,
                          count=declared_count if membership_mode == "COUNT_ONLY" else 0)

    @staticmethod
    def _collection(conn: sqlite3.Connection, user_id: str, collection_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM collections WHERE user_id=? AND collection_id=?",
            (user_id, collection_id),
        ).fetchone()

    @staticmethod
    def _active_members(conn: sqlite3.Connection, collection_id: str) -> dict[str, sqlite3.Row]:
        rows = conn.execute(
            "SELECT * FROM membership_versions WHERE collection_id=? AND status='CURRENT'",
            (collection_id,),
        ).fetchall()
        return {str(r["member_id"]): r for r in rows}

    @staticmethod
    def _member_versions(active: dict[str, sqlite3.Row]) -> tuple[tuple[str, int], ...]:
        return tuple(sorted((member_id, int(row["version_id"]))
                            for member_id, row in active.items()))

    @staticmethod
    def _collection_result(
        status: Status, operation: str, user_id: str, row: sqlite3.Row | None = None,
        **kwargs: Any,
    ) -> Result:
        return Result(
            status, operation, user_id,
            memory_id=row["memory_id"] if row is not None else None,
            collection_id=row["collection_id"] if row is not None else kwargs.pop("collection_id", None),
            entity_id=row["entity_id"] if row is not None else None,
            semantic_key=row["semantic_key"] if row is not None else None,
            **kwargs,
        )

    @staticmethod
    def _archive_member(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        conn.execute(
            "UPDATE membership_versions SET status='HISTORICAL',superseded_at=? "
            "WHERE version_id=? AND status='CURRENT'",
            (_now(), row["version_id"]),
        )

    @staticmethod
    def _insert_member(
        conn: sqlite3.Connection, collection_id: str, member_id: str,
        member_label: str,
    ) -> int:
        predecessor = conn.execute(
            "SELECT version_id FROM membership_versions WHERE collection_id=? AND member_id=? "
            "ORDER BY version_id DESC LIMIT 1",
            (collection_id, member_id),
        ).fetchone()
        cursor = conn.execute(
            "INSERT INTO membership_versions "
            "(collection_id,member_id,member_label,predecessor_version_id,status,created_at) "
            "VALUES (?,?,?,?,'CURRENT',?)",
            (collection_id, member_id, member_label,
             predecessor["version_id"] if predecessor else None, _now()),
        )
        return int(cursor.lastrowid)

    def add_collection_member(
        self, user_id: str, collection_id: str, member_id: str | None,
        member_label: str | None = None,
        *, expected_member_versions: tuple[tuple[str, int], ...] | None = None,
    ) -> Result:
        self._user(user_id)
        _identifier(collection_id, "collection_id")
        if member_id is None:
            return Result(Status.AMBIGUOUS_TARGET, "ADD_COLLECTION_MEMBER", user_id,
                          collection_id=collection_id, reason="MISSING_MEMBER_ID")
        _identifier(member_id, "member_id")
        _identifier(member_label, "member_label")
        if len(member_id) > 160 or len(member_label) > 160:
            raise ValueError("member exceeds limit")
        with self._write() as conn:
            row = self._collection(conn, user_id, collection_id)
            if row is None:
                return Result(Status.NOT_FOUND, "ADD_COLLECTION_MEMBER", user_id,
                              collection_id=collection_id)
            if row["membership_mode"] != "NAMED":
                return self._collection_result(Status.UNSUPPORTED, "ADD_COLLECTION_MEMBER",
                                               user_id, row, reason="COUNT_ONLY")
            active = self._active_members(conn, collection_id)
            if (expected_member_versions is not None and
                    self._member_versions(active) != expected_member_versions):
                return self._collection_result(Status.CONFLICT, "ADD_COLLECTION_MEMBER",
                                               user_id, row, reason="STALE_MEMBERSHIP")
            if member_id in active:
                return self._collection_result(
                    Status.NO_OP, "ADD_COLLECTION_MEMBER", user_id, row,
                    evidence_ids=(int(active[member_id]["version_id"]),),
                )
            if len(active) >= 50:
                return self._collection_result(Status.CONFLICT, "ADD_COLLECTION_MEMBER",
                                               user_id, row, reason="MEMBER_LIMIT")
            version_id = self._insert_member(conn, collection_id, member_id, member_label)
            return self._collection_result(
                Status.APPLIED, "ADD_COLLECTION_MEMBER", user_id, row,
                mutation_count=1, version_id=version_id, evidence_ids=(version_id,),
            )

    def remove_collection_member(
        self, user_id: str, collection_id: str, member_id: str | None,
        *, expected_member_versions: tuple[tuple[str, int], ...] | None = None,
    ) -> Result:
        self._user(user_id)
        _identifier(collection_id, "collection_id")
        if member_id is None:
            return Result(Status.AMBIGUOUS_TARGET, "REMOVE_COLLECTION_MEMBER", user_id,
                          collection_id=collection_id, reason="MISSING_MEMBER_ID")
        _identifier(member_id, "member_id")
        with self._write() as conn:
            row = self._collection(conn, user_id, collection_id)
            if row is None:
                return Result(Status.NOT_FOUND, "REMOVE_COLLECTION_MEMBER", user_id,
                              collection_id=collection_id)
            if row["membership_mode"] != "NAMED":
                return self._collection_result(Status.NOT_FOUND, "REMOVE_COLLECTION_MEMBER",
                                               user_id, row, reason="NO_NAMED_MEMBERS")
            members = self._active_members(conn, collection_id)
            if (expected_member_versions is not None and
                    self._member_versions(members) != expected_member_versions):
                return self._collection_result(Status.CONFLICT, "REMOVE_COLLECTION_MEMBER",
                                               user_id, row, reason="STALE_MEMBERSHIP")
            active = members.get(member_id)
            if active is None:
                return self._collection_result(Status.NOT_FOUND, "REMOVE_COLLECTION_MEMBER",
                                               user_id, row, reason="MEMBERSHIP_NOT_FOUND")
            self._archive_member(conn, active)
            return self._collection_result(
                Status.APPLIED, "REMOVE_COLLECTION_MEMBER", user_id, row,
                mutation_count=1, evidence_ids=(int(active["version_id"]),),
            )

    def replace_collection_members(
        self, user_id: str, collection_id: str, members: Iterable[Member],
    ) -> Result:
        self._user(user_id)
        _identifier(collection_id, "collection_id")
        proposed: dict[str, str] = {}
        for member in members:
            if not isinstance(member, Member):
                raise ValueError("members must be typed Member values")
            _identifier(member.member_id, "member_id")
            _identifier(member.member_label, "member_label")
            if member.member_id in proposed:
                return Result(Status.CONFLICT, "REPLACE_COLLECTION_MEMBERS", user_id,
                              collection_id=collection_id, reason="DUPLICATE_MEMBER_ID")
            proposed[member.member_id] = member.member_label
        with self._write() as conn:
            row = self._collection(conn, user_id, collection_id)
            if row is None:
                return Result(Status.NOT_FOUND, "REPLACE_COLLECTION_MEMBERS", user_id,
                              collection_id=collection_id)
            if row["membership_mode"] != "NAMED":
                return self._collection_result(Status.UNSUPPORTED, "REPLACE_COLLECTION_MEMBERS",
                                               user_id, row, reason="COUNT_ONLY")
            active = self._active_members(conn, collection_id)
            if {k: r["member_label"] for k, r in active.items()} == proposed:
                return self._collection_result(Status.NO_OP, "REPLACE_COLLECTION_MEMBERS",
                                               user_id, row)
            evidence: list[int] = []
            for member_id, old in active.items():
                if proposed.get(member_id) != old["member_label"]:
                    self._archive_member(conn, old)
                    evidence.append(int(old["version_id"]))
            for member_id, label in proposed.items():
                if member_id not in active or active[member_id]["member_label"] != label:
                    evidence.append(self._insert_member(conn, collection_id, member_id, label))
            return self._collection_result(
                Status.APPLIED, "REPLACE_COLLECTION_MEMBERS", user_id, row,
                mutation_count=1, evidence_ids=tuple(evidence),
            )

    def list_collection_members(self, user_id: str, collection_id: str) -> Result:
        self._user(user_id)
        _identifier(collection_id, "collection_id")
        with self._connection() as conn:
            row = self._collection(conn, user_id, collection_id)
            if row is None:
                return Result(Status.NOT_FOUND, "LIST_COLLECTION_MEMBERS", user_id,
                              collection_id=collection_id)
            if row["membership_mode"] != "NAMED":
                return self._collection_result(Status.UNSUPPORTED, "LIST_COLLECTION_MEMBERS",
                                               user_id, row, reason="COUNT_ONLY")
            active = self._active_members(conn, collection_id)
            ordered = sorted(active.items())
            return self._collection_result(
                Status.FOUND, "LIST_COLLECTION_MEMBERS", user_id, row,
                members=tuple(Member(k, str(v["member_label"])) for k, v in ordered),
                evidence_ids=tuple(int(v["version_id"]) for _, v in ordered),
                count=len(ordered),
            )

    def count_collection_members(self, user_id: str, collection_id: str) -> Result:
        listed = self.list_collection_members(user_id, collection_id)
        return Result(
            listed.status, "COUNT_COLLECTION_MEMBERS", user_id,
            memory_id=listed.memory_id, collection_id=listed.collection_id,
            entity_id=listed.entity_id,
            semantic_key=listed.semantic_key, evidence_ids=listed.evidence_ids,
            count=listed.count, reason=listed.reason,
        )

    def get_collection_declared_count(self, user_id: str, collection_id: str) -> Result:
        self._user(user_id)
        _identifier(collection_id, "collection_id")
        with self._connection() as conn:
            row = self._collection(conn, user_id, collection_id)
            if row is None:
                return Result(Status.NOT_FOUND, "GET_COLLECTION_DECLARED_COUNT", user_id,
                              collection_id=collection_id)
            if row["membership_mode"] != "COUNT_ONLY":
                return self._collection_result(Status.UNSUPPORTED,
                                               "GET_COLLECTION_DECLARED_COUNT", user_id, row,
                                               reason="NAMED_MEMBERSHIP")
            return self._collection_result(Status.FOUND, "GET_COLLECTION_DECLARED_COUNT",
                                           user_id, row, count=int(row["declared_count"]))
