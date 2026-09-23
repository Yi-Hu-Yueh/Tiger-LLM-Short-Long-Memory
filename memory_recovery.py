"""Phase 3E deterministic backup, integrity, and restore validation."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
from typing import Any

from app import utc_now


_PROTECTED_NAMES = {"memory.db", "final_acceptance.db", "memory_after_restore_baseline.db", "real40_v2.db"}


@dataclass(frozen=True, slots=True)
class RecoveryPoint:
    recovery_id: str
    created_at: str
    core_backup: str
    audit_backup: str
    core_sha256: str
    audit_sha256: str
    revisions: tuple[tuple[str, int], ...]
    proposal_count: int
    audit_sequence: int


class MemoryRecoveryService:
    def __init__(self, *, core_db: str | Path, audit_db: str | Path, backup_dir: str | Path):
        self.core_db = Path(core_db).resolve()
        self.audit_db = Path(audit_db).resolve()
        self.backup_dir = Path(backup_dir).resolve()
        if self.core_db == self.audit_db:
            raise ValueError("core and audit databases must be separate")
        if self.core_db.name.lower() in _PROTECTED_NAMES or self.audit_db.name.lower() in _PROTECTED_NAMES:
            raise ValueError("protected production database is not admitted by recovery gate")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self) -> RecoveryPoint:
        live = self.verify_integrity()
        if not live["valid"]:
            raise ValueError("live database integrity check failed: " + ",".join(live["reasons"]))
        recovery_id = uuid.uuid4().hex
        core_backup = self.backup_dir / f"{recovery_id}.core.db"
        audit_backup = self.backup_dir / f"{recovery_id}.audit.db"
        self._sqlite_backup(self.core_db, core_backup)
        self._sqlite_backup(self.audit_db, audit_backup)
        inspection = self._inspect(core_backup, audit_backup)
        if not inspection["valid"]:
            core_backup.unlink(missing_ok=True)
            audit_backup.unlink(missing_ok=True)
            raise ValueError("backup integrity check failed")
        manifest = {
            "recovery_id": recovery_id,
            "created_at": utc_now(),
            "core_backup": core_backup.name,
            "audit_backup": audit_backup.name,
            "core_sha256": self._sha256(core_backup),
            "audit_sha256": self._sha256(audit_backup),
            "revisions": inspection["revisions"],
            "proposal_count": inspection["proposal_count"],
            "audit_sequence": inspection["audit_sequence"],
        }
        manifest_path = self.backup_dir / f"{recovery_id}.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return self._point_from_manifest(manifest)

    def restore_backup(self, recovery_id: str) -> RecoveryPoint:
        point = self._load_point(recovery_id)
        check = self.verify_integrity(recovery_id)
        if not check["valid"]:
            raise ValueError("recovery point integrity check failed: " + ",".join(check["reasons"]))
        core_source = self.backup_dir / point.core_backup
        audit_source = self.backup_dir / point.audit_backup
        core_stage = self.backup_dir / f".{recovery_id}.core.restore-stage"
        audit_stage = self.backup_dir / f".{recovery_id}.audit.restore-stage"
        core_rollback = self.backup_dir / f".{recovery_id}.core.rollback"
        audit_rollback = self.backup_dir / f".{recovery_id}.audit.rollback"
        for path in (core_stage, audit_stage, core_rollback, audit_rollback):
            path.unlink(missing_ok=True)
        self._sqlite_backup(core_source, core_stage)
        self._sqlite_backup(audit_source, audit_stage)
        staged = self._inspect(core_stage, audit_stage)
        if not staged["valid"]:
            core_stage.unlink(missing_ok=True)
            audit_stage.unlink(missing_ok=True)
            raise ValueError("staged restore integrity check failed")
        shutil.copy2(self.core_db, core_rollback)
        shutil.copy2(self.audit_db, audit_rollback)
        try:
            self._sqlite_backup(core_stage, self.core_db)
            self._sqlite_backup(audit_stage, self.audit_db)
            restored = self.verify_integrity()
            if not restored["valid"]:
                raise ValueError("restored database integrity check failed")
        except Exception:
            self._sqlite_backup(core_rollback, self.core_db)
            self._sqlite_backup(audit_rollback, self.audit_db)
            core_stage.unlink(missing_ok=True)
            audit_stage.unlink(missing_ok=True)
            raise
        core_stage.unlink(missing_ok=True)
        audit_stage.unlink(missing_ok=True)
        core_rollback.unlink(missing_ok=True)
        audit_rollback.unlink(missing_ok=True)
        return point

    def verify_integrity(self, recovery_id: str | None = None) -> dict[str, Any]:
        if recovery_id is None:
            return self._inspect(self.core_db, self.audit_db)
        try:
            point = self._load_point(recovery_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"valid": False, "reasons": ["manifest_invalid", type(exc).__name__]}
        core_path = self.backup_dir / point.core_backup
        audit_path = self.backup_dir / point.audit_backup
        reasons: list[str] = []
        if not core_path.is_file() or self._sha256(core_path) != point.core_sha256:
            reasons.append("core_hash_mismatch")
        if not audit_path.is_file() or self._sha256(audit_path) != point.audit_sha256:
            reasons.append("audit_hash_mismatch")
        if reasons:
            return {"valid": False, "reasons": reasons}
        result = self._inspect(core_path, audit_path)
        if result["valid"]:
            if tuple(sorted(result["revisions"].items())) != point.revisions:
                result["reasons"].append("revision_manifest_mismatch")
            if result["proposal_count"] != point.proposal_count:
                result["reasons"].append("proposal_manifest_mismatch")
            if result["audit_sequence"] != point.audit_sequence:
                result["reasons"].append("audit_sequence_manifest_mismatch")
            result["valid"] = not result["reasons"]
        return result

    def list_recovery_points(self) -> list[RecoveryPoint]:
        points: list[RecoveryPoint] = []
        for manifest in sorted(self.backup_dir.glob("*.json")):
            try:
                points.append(self._point_from_manifest(json.loads(manifest.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError, json.JSONDecodeError, TypeError):
                continue
        return sorted(points, key=lambda item: (item.created_at, item.recovery_id))

    @staticmethod
    def _sqlite_backup(source: Path, destination: Path) -> None:
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            dst.commit()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().upper()

    def _load_point(self, recovery_id: str) -> RecoveryPoint:
        if not isinstance(recovery_id, str) or re.fullmatch(r"[0-9a-f]{32}", recovery_id) is None:
            raise ValueError("invalid recovery id")
        manifest = self.backup_dir / f"{recovery_id}.json"
        return self._point_from_manifest(json.loads(manifest.read_text(encoding="utf-8")))

    @staticmethod
    def _point_from_manifest(manifest: dict[str, Any]) -> RecoveryPoint:
        return RecoveryPoint(
            recovery_id=str(manifest["recovery_id"]),
            created_at=str(manifest["created_at"]),
            core_backup=str(manifest["core_backup"]),
            audit_backup=str(manifest["audit_backup"]),
            core_sha256=str(manifest["core_sha256"]),
            audit_sha256=str(manifest["audit_sha256"]),
            revisions=tuple(sorted((str(key), int(value)) for key, value in manifest["revisions"].items())),
            proposal_count=int(manifest["proposal_count"]),
            audit_sequence=int(manifest["audit_sequence"]),
        )

    @staticmethod
    def _inspect(core_path: Path, audit_path: Path) -> dict[str, Any]:
        reasons: list[str] = []
        revisions: dict[str, int] = {}
        proposal_count = 0
        audit_sequence = 0
        try:
            with closing(sqlite3.connect(core_path)) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    reasons.append("core_integrity_failed")
                revisions = {str(row[0]): int(row[1]) for row in conn.execute("SELECT user_id,revision FROM memory_state")}
                if any(value < 0 for value in revisions.values()):
                    reasons.append("negative_revision")
                duplicate = conn.execute(
                    "SELECT 1 FROM memories WHERE semantic_key IS NOT NULL "
                    "GROUP BY user_id,state_type,semantic_key HAVING COUNT(*) > 1 LIMIT 1"
                ).fetchone()
                if duplicate is not None:
                    reasons.append("duplicate_current_state")
                invalid_user = conn.execute(
                    "SELECT 1 FROM (SELECT user_id FROM memories UNION ALL SELECT user_id FROM memory_history "
                    "UNION ALL SELECT user_id FROM pending_memory_proposals UNION ALL SELECT user_id FROM sessions) "
                    "WHERE user_id NOT IN ('user1','user2') LIMIT 1"
                ).fetchone()
                if invalid_user is not None:
                    reasons.append("invalid_user_scope")
                missing_revision = conn.execute(
                    "SELECT 1 FROM (SELECT user_id FROM memories UNION SELECT user_id FROM pending_memory_proposals "
                    "UNION SELECT user_id FROM sessions) u LEFT JOIN memory_state s ON s.user_id=u.user_id "
                    "WHERE s.user_id IS NULL LIMIT 1"
                ).fetchone()
                if missing_revision is not None:
                    reasons.append("revision_row_missing")
                invalid_target = conn.execute(
                    "SELECT 1 FROM pending_memory_proposals p LEFT JOIN memories m "
                    "ON m.memory_id=p.target_memory_id AND m.user_id=p.user_id "
                    "WHERE p.target_memory_id IS NOT NULL AND m.memory_id IS NULL LIMIT 1"
                ).fetchone()
                if invalid_target is not None:
                    reasons.append("proposal_target_invalid")
                proposal_count = int(conn.execute("SELECT COUNT(*) FROM pending_memory_proposals").fetchone()[0])
        except (sqlite3.DatabaseError, OSError, TypeError, ValueError):
            reasons.append("core_unreadable")
        try:
            with closing(sqlite3.connect(audit_path)) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    reasons.append("audit_integrity_failed")
                sequences = [int(row[0]) for row in conn.execute("SELECT sequence_id FROM memory_audit_events ORDER BY sequence_id")]
                if sequences != sorted(set(sequences)) or any(value <= 0 for value in sequences):
                    reasons.append("audit_sequence_invalid")
                invalid_audit_user = conn.execute(
                    "SELECT 1 FROM memory_audit_events WHERE user_id NOT IN ('user1','user2') LIMIT 1"
                ).fetchone()
                if invalid_audit_user is not None:
                    reasons.append("audit_user_scope_invalid")
                audit_sequence = sequences[-1] if sequences else 0
        except (sqlite3.DatabaseError, OSError, TypeError, ValueError):
            reasons.append("audit_unreadable")
        return {
            "valid": not reasons,
            "reasons": reasons,
            "revisions": revisions,
            "proposal_count": proposal_count,
            "audit_sequence": audit_sequence,
        }
