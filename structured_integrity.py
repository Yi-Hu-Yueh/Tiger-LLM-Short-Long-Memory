"""Read-only integrity gate for the explicit Structured Memory V2 database."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from pathlib import Path
import sqlite3

from memory_v2.core import ALLOWED_USERS
from structured_app import safe_db_path


REQUIRED_TABLES = frozenset((
    "scalar_lineages", "scalar_versions", "collections", "membership_versions",
))
REQUIRED_INDEXES = frozenset((
    "ix_scalar_lookup", "ux_scalar_current", "ix_collection_lookup",
    "ux_active_membership",
))


def _check_chain(rows: list[sqlite3.Row], *, active_required: bool) -> list[str]:
    if not rows:
        return ["EMPTY_CHAIN"]
    by_id = {row["version_id"]: row for row in rows}
    if len(by_id) != len(rows):
        return ["DUPLICATE_VERSION_ID"]
    roots = [row for row in rows if row["predecessor_version_id"] is None]
    if len(roots) != 1:
        return ["INVALID_ROOT_COUNT"]
    successors: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        predecessor = row["predecessor_version_id"]
        if predecessor is None:
            continue
        if predecessor == row["version_id"]:
            return ["SELF_PREDECESSOR"]
        if predecessor not in by_id:
            return ["BROKEN_PREDECESSOR"]
        successors[predecessor].append(row["version_id"])
    if any(len(children) != 1 for children in successors.values()):
        return ["FORKED_CHAIN"]
    visited: set[int] = set()
    cursor = roots[0]["version_id"]
    while cursor not in visited:
        visited.add(cursor)
        children = successors.get(cursor, [])
        if not children:
            break
        cursor = children[0]
    if len(visited) != len(rows):
        return ["BROKEN_CHAIN"]
    current = [row for row in rows if row["status"] == "CURRENT"]
    if len(current) > 1 or (active_required and len(current) != 1):
        return ["INVALID_CURRENT_COUNT"]
    if current and current[0]["version_id"] != cursor:
        return ["CURRENT_NOT_CHAIN_TIP"]
    if any(row["status"] != "HISTORICAL" for row in rows
           if row["version_id"] != cursor):
        return ["NONHISTORICAL_PREDECESSOR"]
    if not current and by_id[cursor]["status"] != "HISTORICAL":
        return ["INVALID_CHAIN_TIP"]
    return []


def check_structured_integrity(db_path: str | Path) -> dict[str, object]:
    """Inspect one existing, non-protected DB without creating or writing it."""
    path = safe_db_path(db_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    issues: list[str] = []
    counts: dict[str, int] = {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                issues.append("SQLITE_INTEGRITY")
            objects = conn.execute(
                "SELECT type,name FROM sqlite_master WHERE type IN ('table','index')"
            ).fetchall()
            tables = {row["name"] for row in objects if row["type"] == "table"}
            indexes = {row["name"] for row in objects if row["type"] == "index"}
            if not REQUIRED_TABLES.issubset(tables):
                issues.append("MISSING_REQUIRED_TABLE")
            if not REQUIRED_INDEXES.issubset(indexes):
                issues.append("MISSING_REQUIRED_INDEX")
            if not REQUIRED_TABLES.issubset(tables):
                return {"status": "FAIL", "issues": sorted(set(issues)), "counts": counts}
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                issues.append("FOREIGN_KEY_VIOLATION")

            lineages = conn.execute(
                "SELECT memory_id,user_id,entity_id,semantic_key FROM scalar_lineages"
            ).fetchall()
            versions = conn.execute(
                "SELECT version_id,memory_id,predecessor_version_id,status "
                "FROM scalar_versions"
            ).fetchall()
            collections = conn.execute(
                "SELECT collection_id,memory_id,user_id,entity_id,semantic_key,"
                "membership_mode,declared_count FROM collections"
            ).fetchall()
            memberships = conn.execute(
                "SELECT version_id,collection_id,member_id,predecessor_version_id,status "
                "FROM membership_versions"
            ).fetchall()
            counts.update(scalar_lineages=len(lineages), scalar_versions=len(versions),
                          collections=len(collections), membership_versions=len(memberships),
                          active_memberships=sum(r["status"] == "CURRENT" for r in memberships))

            scalar_groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
            for row in versions:
                scalar_groups[row["memory_id"]].append(row)
            scalar_ids = {row["memory_id"] for row in lineages}
            if set(scalar_groups) - scalar_ids:
                issues.append("ORPHAN_SCALAR_VERSION")
            for lineage in lineages:
                if lineage["user_id"] not in ALLOWED_USERS:
                    issues.append("INVALID_SCALAR_OWNER")
                issues.extend(_check_chain(scalar_groups[lineage["memory_id"]],
                                           active_required=True))

            collection_groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
            for row in memberships:
                collection_groups[(row["collection_id"], row["member_id"])].append(row)
            collection_ids = {row["collection_id"] for row in collections}
            if {row["collection_id"] for row in memberships} - collection_ids:
                issues.append("ORPHAN_MEMBERSHIP")
            scalar_identity = {(r["user_id"], r["entity_id"], r["semantic_key"])
                               for r in lineages}
            if len(scalar_identity) != len(lineages):
                issues.append("DUPLICATE_SCALAR_IDENTITY")
            collection_identity = {(r["user_id"], r["entity_id"], r["semantic_key"])
                                   for r in collections}
            if len(collection_identity) != len(collections):
                issues.append("DUPLICATE_COLLECTION_IDENTITY")
            if scalar_ids & {row["memory_id"] for row in collections}:
                issues.append("CROSS_FAMILY_MEMORY_ID_COLLISION")
            for collection in collections:
                if collection["user_id"] not in ALLOWED_USERS:
                    issues.append("INVALID_COLLECTION_OWNER")
                if collection["collection_id"] != collection["memory_id"]:
                    issues.append("COLLECTION_MEMORY_ID_MISMATCH")
                related = [rows for (collection_id, _), rows in collection_groups.items()
                           if collection_id == collection["collection_id"]]
                active = sum(row["status"] == "CURRENT" for rows in related for row in rows)
                if collection["membership_mode"] == "COUNT_ONLY":
                    if related:
                        issues.append("COUNT_ONLY_HAS_MEMBER_IDENTITY")
                    if collection["declared_count"] is None or collection["declared_count"] < 0:
                        issues.append("INVALID_DECLARED_COUNT")
                elif collection["membership_mode"] == "NAMED":
                    if collection["declared_count"] is not None:
                        issues.append("NAMED_HAS_DECLARED_COUNT")
                    if active != sum(bool(any(row["status"] == "CURRENT" for row in rows))
                                     for rows in related):
                        issues.append("NAMED_COUNT_MISMATCH")
                else:
                    issues.append("INVALID_MEMBERSHIP_MODE")
                for rows in related:
                    issues.extend(_check_chain(rows, active_required=False))
        finally:
            conn.rollback()
    return {"status": "PASS" if not issues else "FAIL",
            "issues": sorted(set(issues)), "counts": counts}
