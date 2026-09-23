"""Phase 4E fail-closed operational lifecycle validation."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import gc
from pathlib import Path
import sqlite3
from typing import Any

from app import ALLOWED_USERS, MemoryStore, SCHEMA_VERSION
from memory_audit import MemoryAuditStore


PROTECTED_CORE_NAMES = frozenset(
    ("memory.db", "final_acceptance.db", "memory_after_restore_baseline.db", "real40_v2.db")
)
ENVIRONMENTS = frozenset(("development", "test", "production"))
CORE_TABLES = frozenset(
    ("memories", "memory_history", "memory_state", "sessions", "pending_memory_proposals")
)
AUDIT_TABLES = frozenset(("memory_audit_events",))


class OperationsStartupError(RuntimeError):
    """Raised before runtime activation when lifecycle validation fails."""


@dataclass(frozen=True, slots=True)
class RuntimeHandles:
    store: MemoryStore
    audit: MemoryAuditStore


class MemoryOperationsManager:
    def __init__(
        self,
        *,
        core_db: str | Path,
        audit_db: str | Path,
        environment: str,
        environment_marker: str | Path,
    ):
        self.core_db = Path(core_db).resolve()
        self.audit_db = Path(audit_db).resolve()
        self.environment = environment
        self.environment_marker = Path(environment_marker).resolve()
        self._runtime: RuntimeHandles | None = None
        self._last_validation: dict[str, Any] | None = None

    @property
    def runtime(self) -> RuntimeHandles:
        if self._runtime is None:
            raise OperationsStartupError("runtime is not initialized")
        return self._runtime

    def validate_environment(self) -> dict[str, Any]:
        reasons: list[str] = []
        if self.environment not in ENVIRONMENTS:
            reasons.append("environment_not_allowed")
        if not self.environment_marker.is_file():
            reasons.append("environment_marker_missing")
        else:
            try:
                marker = self.environment_marker.read_text(encoding="utf-8").strip()
            except OSError:
                marker = ""
            if marker != self.environment:
                reasons.append("environment_marker_mismatch")
        if self.core_db == self.audit_db:
            reasons.append("storage_paths_must_differ")
        core_name = self.core_db.name.lower()
        if self.environment != "production" and core_name in PROTECTED_CORE_NAMES:
            reasons.append("protected_database_in_nonproduction")
        if self.environment == "production" and core_name != "memory.db":
            reasons.append("production_core_name_mismatch")
        result = {
            "valid": not reasons,
            "environment": self.environment,
            "marker_valid": "environment_marker_missing" not in reasons
            and "environment_marker_mismatch" not in reasons,
            "path_separation_valid": "storage_paths_must_differ" not in reasons,
            "protected_name_policy_valid": not any(
                reason in reasons
                for reason in ("protected_database_in_nonproduction", "production_core_name_mismatch")
            ),
            "reasons": reasons,
        }
        return result

    def validate_storage(self) -> dict[str, Any]:
        reasons: list[str] = []
        if not self.core_db.is_file():
            reasons.append("core_database_missing")
        if not self.audit_db.is_file():
            reasons.append("audit_database_missing")
        if reasons:
            return self._storage_result(reasons)

        core_tables: set[str] = set()
        audit_tables: set[str] = set()
        schema_version: int | None = None
        users: set[str] = set()
        try:
            with closing(sqlite3.connect(self.core_db)) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    reasons.append("core_integrity_failed")
                schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if schema_version != SCHEMA_VERSION:
                    reasons.append("schema_version_unsupported")
                core_tables = {
                    str(row[0])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if not CORE_TABLES <= core_tables:
                    reasons.append("core_schema_incomplete")
                if CORE_TABLES <= core_tables:
                    users = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT user_id FROM memories UNION SELECT user_id FROM memory_history "
                            "UNION SELECT user_id FROM memory_state UNION SELECT user_id FROM sessions "
                            "UNION SELECT user_id FROM pending_memory_proposals"
                        )
                    }
                    if not users <= set(ALLOWED_USERS):
                        reasons.append("user_scope_invalid")
        except (sqlite3.DatabaseError, OSError, TypeError, ValueError):
            reasons.append("core_database_unreadable")
        try:
            with closing(sqlite3.connect(self.audit_db)) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    reasons.append("audit_integrity_failed")
                audit_tables = {
                    str(row[0])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if not AUDIT_TABLES <= audit_tables:
                    reasons.append("audit_schema_incomplete")
                if AUDIT_TABLES <= audit_tables:
                    invalid = conn.execute(
                        "SELECT 1 FROM memory_audit_events "
                        "WHERE user_id NOT IN ('user1','user2') LIMIT 1"
                    ).fetchone()
                    if invalid is not None:
                        reasons.append("audit_user_scope_invalid")
        except (sqlite3.DatabaseError, OSError, TypeError, ValueError):
            reasons.append("audit_database_unreadable")
        return {
            "valid": not reasons,
            "schema_version": schema_version,
            "schema_compatible": schema_version == SCHEMA_VERSION,
            "core_integrity": not any(reason.startswith("core_") and reason.endswith(("failed", "unreadable")) for reason in reasons),
            "audit_integrity": not any(reason.startswith("audit_") and reason.endswith(("failed", "unreadable")) for reason in reasons),
            "proposal_storage_available": "pending_memory_proposals" in core_tables,
            "audit_storage_available": "memory_audit_events" in audit_tables,
            "user_scope_valid": not any(reason in reasons for reason in ("user_scope_invalid", "audit_user_scope_invalid")),
            "reasons": reasons,
        }

    def initialize_runtime(self) -> RuntimeHandles:
        if self._runtime is not None:
            return self._runtime
        environment = self.validate_environment()
        storage = self.validate_storage()
        self._last_validation = {"environment": environment, "storage": storage}
        reasons = [*environment["reasons"], *storage["reasons"]]
        if reasons:
            raise OperationsStartupError("startup validation failed: " + ",".join(reasons))
        handles = RuntimeHandles(store=MemoryStore(self.core_db), audit=MemoryAuditStore(self.audit_db))
        post_storage = self.validate_storage()
        if not post_storage["valid"]:
            raise OperationsStartupError("post-initialization storage validation failed")
        self._runtime = handles
        self._last_validation = {"environment": environment, "storage": post_storage}
        return handles

    def shutdown_runtime(self) -> dict[str, Any]:
        if self._runtime is None:
            return {"status": "STOPPED", "transactions_clear": True, "audit_flushed": True, "cleanup": True}
        transactions_clear = self._probe_idle(self.core_db)
        audit_flushed = self._probe_idle(self.audit_db)
        if not transactions_clear or not audit_flushed:
            raise OperationsStartupError("shutdown validation failed")
        self._runtime = None
        gc.collect()
        return {
            "status": "STOPPED",
            "transactions_clear": True,
            "audit_flushed": True,
            "cleanup": True,
        }

    def generate_startup_report(self) -> dict[str, Any]:
        environment = self.validate_environment()
        storage = self.validate_storage()
        return {
            "environment": environment,
            "storage": storage,
            "runtime_state": "RUNNING" if self._runtime is not None else "STOPPED",
            "startup_ready": environment["valid"] and storage["valid"],
        }

    @staticmethod
    def _probe_idle(path: Path) -> bool:
        try:
            with closing(sqlite3.connect(path, timeout=1.0)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            return True
        except (sqlite3.DatabaseError, OSError):
            return False

    @staticmethod
    def _storage_result(reasons: list[str]) -> dict[str, Any]:
        return {
            "valid": False,
            "schema_version": None,
            "schema_compatible": False,
            "core_integrity": "core_database_missing" not in reasons,
            "audit_integrity": "audit_database_missing" not in reasons,
            "proposal_storage_available": False,
            "audit_storage_available": False,
            "user_scope_valid": True,
            "reasons": reasons,
        }
