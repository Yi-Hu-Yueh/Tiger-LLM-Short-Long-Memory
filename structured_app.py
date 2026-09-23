"""Separate localhost UI for explicit, human-confirmed V2 typed operations.

This runtime accepts structured fields only. It never imports the semantic
adapter, calls a model, or opens the existing chat application's databases.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any
from uuid import uuid4

from memory_v2 import MemoryV2Core, Status


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "structured_ui" / "structured_memory.db"
HTML = ROOT / "structured_ui" / "index.html"
PROTECTED_NAMES = frozenset((
    "memory.db", "final_acceptance.db", "memory_after_restore_baseline.db",
    "real40_v2.db",
))
USERS = frozenset(("user1", "user2"))


class RequestError(ValueError):
    def __init__(self, code: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(code)
        self.code = code
        self.status = status


def safe_db_path(db_path: str | Path) -> Path:
    path = Path(db_path).resolve()
    if path.name.casefold() in PROTECTED_NAMES:
        raise ValueError("protected database path is not allowed")
    return path


def _fields(payload: object, required: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != required:
        raise RequestError("INVALID_FIELDS")
    return payload


def _user(value: object) -> str:
    if not isinstance(value, str) or value not in USERS:
        raise RequestError("INVALID_USER")
    return value


def _id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise RequestError("INVALID_" + name.upper())
    return value


def _value(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequestError("INVALID_VALUE")
    if len(value) > 160:
        raise RequestError("VALUE_TOO_LONG")
    return value


def _count(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise RequestError("INVALID_DECLARED_COUNT")
    return value


@dataclass(frozen=True, slots=True)
class Preview:
    token: str
    user_id: str
    operation: str
    entity_id: str | None
    semantic_key: str | None
    memory_id: str | None
    old_value: str | None
    new_value: str
    base_version_id: int | None

    def public(self) -> dict[str, object]:
        return {
            "token": self.token, "operation": self.operation,
            "entity_id": self.entity_id, "semantic_key": self.semantic_key,
            "memory_id": self.memory_id, "old_value": self.old_value,
            "new_value": self.new_value,
        }


@dataclass(frozen=True, slots=True)
class CollectionPreview:
    token: str
    user_id: str
    operation: str
    collection_id: str
    entity_id: str
    semantic_key: str
    display_label: str
    membership_mode: str
    declared_count: int | None
    member_id: str | None
    member_label: str | None
    before: tuple[tuple[str, str], ...]
    after: tuple[tuple[str, str], ...]
    base_member_versions: tuple[tuple[str, int], ...]

    def public(self) -> dict[str, object]:
        return {
            "token": self.token, "operation": self.operation,
            "collection_id": self.collection_id, "entity_id": self.entity_id,
            "semantic_key": self.semantic_key, "display_label": self.display_label,
            "membership_mode": self.membership_mode, "declared_count": self.declared_count,
            "member_id": self.member_id, "member_label": self.member_label,
            "before": [{"member_id": key, "member_label": label} for key, label in self.before],
            "after": [{"member_id": key, "member_label": label} for key, label in self.after],
        }


class StructuredMemoryService:
    """Only Confirm can perform a changed V2 write; previews are ephemeral."""

    def __init__(self, db_path: str | Path):
        self.db_path = safe_db_path(db_path)
        self.core = MemoryV2Core(self.db_path)
        self._lock = RLock()
        self._pending: dict[str, Preview | CollectionPreview] = {}

    def list_scalars(self, user_id: str) -> dict[str, object]:
        user = _user(user_id)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(
                "SELECT l.memory_id,l.entity_id,l.semantic_key,v.value_json,v.version_id "
                "FROM scalar_lineages AS l JOIN scalar_versions AS v "
                "ON v.memory_id=l.memory_id AND v.status='CURRENT' "
                "WHERE l.user_id=? ORDER BY l.semantic_key,l.entity_id,l.memory_id",
                (user,),
            ).fetchall()
        return {"status": "FOUND", "operation": "LIST_SCALARS", "mutation_count": 0,
                "memories": [
                    {"memory_id": row["memory_id"], "entity_id": row["entity_id"],
                     "semantic_key": row["semantic_key"],
                     "current_value": json.loads(row["value_json"]),
                     "version_id": row["version_id"]}
                    for row in rows
                ]}

    def prepare(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise RequestError("INVALID_FIELDS")
        operation = payload.get("operation")
        if operation == "CREATE_SCALAR":
            fields = _fields(payload, {"operation", "user_id", "entity_id",
                                       "semantic_key", "value"})
            user = _user(fields["user_id"])
            entity = _id(fields["entity_id"], "entity_id")
            key = _id(fields["semantic_key"], "semantic_key")
            value = _value(fields["value"])
            old = None
            memory_id = None
            base_version = None
        elif operation == "UPDATE_SCALAR":
            fields = _fields(payload, {"operation", "user_id", "memory_id", "value"})
            user = _user(fields["user_id"])
            memory_id = _id(fields["memory_id"], "memory_id")
            value = _value(fields["value"])
            current = self.core.get_current_scalar(user, memory_id=memory_id)
            if current.status is Status.NOT_FOUND:
                raise RequestError("MEMORY_NOT_FOUND", HTTPStatus.NOT_FOUND)
            entity, key, old = current.entity_id, current.semantic_key, current.value
            base_version = current.version_id
            if value == old:
                return {"status": "NO_OP", "operation": operation,
                        "memory_id": memory_id, "mutation_count": 0,
                        "message": "No change / already current"}
        else:
            raise RequestError("INVALID_OPERATION")
        with self._lock:
            token = uuid4().hex
            preview = Preview(token, user, operation, entity, key, memory_id,
                              old, value, base_version)
            self._pending[token] = preview
        return {"status": "CONFIRMATION_REQUIRED", "mutation_count": 0,
                "preview": preview.public()}

    def confirm(self, payload: object) -> dict[str, object]:
        fields = _fields(payload, {"user_id", "token"})
        user = _user(fields["user_id"])
        token = _id(fields["token"], "token")
        with self._lock:
            preview = self._pending.get(token)
            if not isinstance(preview, Preview) or preview.user_id != user:
                raise RequestError("CONFIRMATION_NOT_FOUND", HTTPStatus.NOT_FOUND)
            if preview.operation == "CREATE_SCALAR":
                result = self.core.create_scalar(user, preview.semantic_key,
                                                 preview.new_value,
                                                 entity_id=preview.entity_id,
                                                 max_current=20)
            else:
                result = self.core.set_scalar(user, preview.new_value,
                                              memory_id=preview.memory_id,
                                              expected_version_id=preview.base_version_id)
            del self._pending[token]
        if result.status is Status.CONFLICT:
            if result.reason == "STALE_VERSION":
                raise RequestError("STALE_CONFIRMATION", HTTPStatus.CONFLICT)
            if result.reason == "USER_MEMORY_LIMIT":
                raise RequestError("MEMORY_LIMIT", HTTPStatus.CONFLICT)
            raise RequestError("TARGET_ALREADY_EXISTS", HTTPStatus.CONFLICT)
        if result.status is Status.NOT_FOUND:
            raise RequestError("MEMORY_NOT_FOUND", HTTPStatus.NOT_FOUND)
        if result.status is not Status.APPLIED:
            raise RequestError("CONFIRMATION_FAILED", HTTPStatus.CONFLICT)
        return {"status": "CREATED" if preview.operation == "CREATE_SCALAR" else "UPDATED",
                "operation": preview.operation, "memory_id": result.memory_id,
                "entity_id": result.entity_id, "semantic_key": result.semantic_key,
                "current_value": result.value, "mutation_count": result.mutation_count,
                "version_id": result.version_id}

    def cancel(self, payload: object) -> dict[str, object]:
        fields = _fields(payload, {"user_id", "token"})
        user = _user(fields["user_id"])
        token = _id(fields["token"], "token")
        with self._lock:
            preview = self._pending.get(token)
            if not isinstance(preview, Preview) or preview.user_id != user:
                raise RequestError("CONFIRMATION_NOT_FOUND", HTTPStatus.NOT_FOUND)
            del self._pending[token]
        return {"status": "CANCELLED", "operation": preview.operation,
                "mutation_count": 0}

    def read(self, payload: object) -> dict[str, object]:
        fields = _fields(payload, {"user_id", "memory_id", "operation"})
        user = _user(fields["user_id"])
        memory_id = _id(fields["memory_id"], "memory_id")
        operation = fields["operation"]
        if operation == "READ_CURRENT":
            result = self.core.get_current_scalar(user, memory_id=memory_id)
        elif operation == "READ_PREVIOUS":
            result = self.core.get_previous_scalar(user, memory_id=memory_id)
        else:
            raise RequestError("INVALID_OPERATION")
        if result.status is Status.NOT_FOUND:
            raise RequestError("MEMORY_NOT_FOUND", HTTPStatus.NOT_FOUND)
        return {"status": result.status.value, "operation": operation,
                "memory_id": result.memory_id, "value": result.value,
                "mutation_count": 0,
                "message": "No previous value" if result.status is Status.NO_PREVIOUS else None}

    def list_collections(self, user_id: str) -> dict[str, object]:
        user = _user(user_id)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(
                "SELECT c.collection_id,c.memory_id,c.entity_id,c.semantic_key,"
                "c.display_label,c.membership_mode,c.declared_count,"
                "(SELECT COUNT(*) FROM membership_versions AS m "
                "WHERE m.collection_id=c.collection_id AND m.status='CURRENT') AS member_count "
                "FROM collections AS c WHERE c.user_id=? "
                "ORDER BY c.semantic_key,c.entity_id,c.collection_id", (user,),
            ).fetchall()
        return {"status": "FOUND", "operation": "LIST_COLLECTIONS", "mutation_count": 0,
                "collections": [
                    {"collection_id": row["collection_id"], "memory_id": row["memory_id"],
                     "entity_id": row["entity_id"], "semantic_key": row["semantic_key"],
                     "display_label": row["display_label"] or row["entity_id"] or row["semantic_key"],
                     "membership_mode": row["membership_mode"],
                     "count": (row["member_count"] if row["membership_mode"] == "NAMED"
                               else row["declared_count"])} for row in rows]}

    def collection_detail(self, user_id: str, collection_id: str) -> dict[str, object]:
        user = _user(user_id)
        collection = _id(collection_id, "collection_id")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute(
                "SELECT collection_id,memory_id,entity_id,semantic_key,display_label,"
                "membership_mode,declared_count FROM collections "
                "WHERE user_id=? AND collection_id=?", (user, collection),
            ).fetchone()
        if row is None:
            raise RequestError("COLLECTION_NOT_FOUND", HTTPStatus.NOT_FOUND)
        if row["membership_mode"] == "NAMED":
            listed = self.core.list_collection_members(user, collection)
            members = [{"member_id": item.member_id, "member_label": item.member_label}
                       for item in listed.members]
            count = listed.count
            versions = tuple(sorted(zip((item.member_id for item in listed.members),
                                        listed.evidence_ids)))
        else:
            members = []
            count = self.core.get_collection_declared_count(user, collection).count
            versions = ()
        return {"status": "FOUND", "operation": "GET_COLLECTION", "mutation_count": 0,
                "collection_id": collection, "memory_id": row["memory_id"],
                "entity_id": row["entity_id"], "semantic_key": row["semantic_key"],
                "display_label": row["display_label"] or row["entity_id"] or row["semantic_key"],
                "membership_mode": row["membership_mode"], "declared_count": row["declared_count"],
                "count": count, "members": members, "member_versions": versions}

    def read_collection(self, payload: object) -> dict[str, object]:
        fields = _fields(payload, {"user_id", "collection_id", "operation"})
        detail = self.collection_detail(fields["user_id"], fields["collection_id"])
        operation = fields["operation"]
        if operation == "LIST_MEMBERS" and detail["membership_mode"] == "NAMED":
            return {"status": "FOUND", "operation": operation, "mutation_count": 0,
                    "collection_id": detail["collection_id"], "members": detail["members"]}
        if operation == "COUNT_MEMBERS" and detail["membership_mode"] == "NAMED":
            return {"status": "FOUND", "operation": operation, "mutation_count": 0,
                    "collection_id": detail["collection_id"], "count": detail["count"]}
        if operation == "READ_DECLARED_COUNT" and detail["membership_mode"] == "COUNT_ONLY":
            return {"status": "FOUND", "operation": operation, "mutation_count": 0,
                    "collection_id": detail["collection_id"], "count": detail["count"],
                    "members": [], "member_identities": "UNKNOWN"}
        raise RequestError("UNSUPPORTED_OPERATION", HTTPStatus.CONFLICT)

    def prepare_collection(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise RequestError("INVALID_FIELDS")
        operation = payload.get("operation")
        if operation == "CREATE_COLLECTION":
            fields = _fields(payload, {"operation", "user_id", "entity_id", "semantic_key",
                                       "display_label", "membership_mode", "declared_count"})
            user = _user(fields["user_id"])
            entity = _id(fields["entity_id"], "entity_id")
            key = _id(fields["semantic_key"], "semantic_key")
            label = _value(fields["display_label"])
            mode = fields["membership_mode"]
            if mode not in ("NAMED", "COUNT_ONLY"):
                raise RequestError("INVALID_MEMBERSHIP_MODE")
            declared = (_count(fields["declared_count"]) if mode == "COUNT_ONLY" else None)
            if mode == "NAMED" and fields["declared_count"] is not None:
                raise RequestError("INVALID_DECLARED_COUNT")
            collection = uuid4().hex
            member_id = member_label = None
            before = after = versions = ()
        elif operation in ("ADD_MEMBER", "REMOVE_MEMBER", "READD_MEMBER"):
            required = ({"operation", "user_id", "collection_id", "member_id", "member_label"}
                        if operation != "REMOVE_MEMBER" else
                        {"operation", "user_id", "collection_id", "member_id"})
            fields = _fields(payload, required)
            user = _user(fields["user_id"])
            collection = _id(fields["collection_id"], "collection_id")
            member_id = _id(fields["member_id"], "member_id")
            if len(member_id) > 160:
                raise RequestError("MEMBER_ID_TOO_LONG")
            detail = self.collection_detail(user, collection)
            if detail["membership_mode"] != "NAMED":
                raise RequestError("UNSUPPORTED_OPERATION", HTTPStatus.CONFLICT)
            entity, key, label = detail["entity_id"], detail["semantic_key"], detail["display_label"]
            mode, declared = "NAMED", None
            before = tuple((m["member_id"], m["member_label"]) for m in detail["members"])
            versions = tuple(tuple(pair) for pair in detail["member_versions"])
            prior = dict(before)
            if operation == "REMOVE_MEMBER":
                if member_id not in prior:
                    raise RequestError("MEMBERSHIP_NOT_FOUND", HTTPStatus.NOT_FOUND)
                member_label = prior[member_id]
                after = tuple((key_, val) for key_, val in before if key_ != member_id)
            else:
                member_label = _value(fields["member_label"])
                if member_id in prior:
                    return {"status": "NO_OP", "operation": operation,
                            "collection_id": collection, "mutation_count": 0}
                if len(before) >= 50:
                    raise RequestError("MEMBER_LIMIT", HTTPStatus.CONFLICT)
                after = tuple(sorted((*before, (member_id, member_label))))
            if len(json.dumps({"items": after}, ensure_ascii=False).encode("utf-8")) > 4096:
                raise RequestError("COLLECTION_SIZE_LIMIT", HTTPStatus.CONFLICT)
        else:
            raise RequestError("INVALID_OPERATION")
        with self._lock:
            token = uuid4().hex
            preview = CollectionPreview(token, user, operation, collection, entity, key, label,
                                        mode, declared, member_id, member_label,
                                        before, after, versions)
            self._pending[token] = preview
        return {"status": "CONFIRMATION_REQUIRED", "mutation_count": 0,
                "preview": preview.public()}

    def confirm_collection(self, payload: object) -> dict[str, object]:
        fields = _fields(payload, {"user_id", "token"})
        user = _user(fields["user_id"])
        token = _id(fields["token"], "token")
        with self._lock:
            preview = self._pending.get(token)
            if not isinstance(preview, CollectionPreview) or preview.user_id != user:
                raise RequestError("CONFIRMATION_NOT_FOUND", HTTPStatus.NOT_FOUND)
            if preview.operation == "CREATE_COLLECTION":
                result = self.core.create_collection(
                    user, preview.semantic_key, entity_id=preview.entity_id,
                    membership_mode=preview.membership_mode, declared_count=preview.declared_count,
                    display_label=preview.display_label, max_current=20,
                    collection_id=preview.collection_id,
                )
            elif preview.operation in ("ADD_MEMBER", "READD_MEMBER"):
                result = self.core.add_collection_member(
                    user, preview.collection_id, preview.member_id, preview.member_label,
                    expected_member_versions=preview.base_member_versions,
                )
            else:
                result = self.core.remove_collection_member(
                    user, preview.collection_id, preview.member_id,
                    expected_member_versions=preview.base_member_versions,
                )
            del self._pending[token]
        if result.status is Status.CONFLICT:
            raise RequestError("STALE_CONFIRMATION" if result.reason == "STALE_MEMBERSHIP"
                               else result.reason or "CONFLICT", HTTPStatus.CONFLICT)
        if result.status is Status.NOT_FOUND:
            raise RequestError("COLLECTION_OR_MEMBER_NOT_FOUND", HTTPStatus.NOT_FOUND)
        if result.status is not Status.APPLIED:
            raise RequestError("CONFIRMATION_FAILED", HTTPStatus.CONFLICT)
        return {"status": "CREATED" if preview.operation == "CREATE_COLLECTION" else "UPDATED",
                "operation": preview.operation, "collection_id": result.collection_id,
                "mutation_count": result.mutation_count}

    def cancel_collection(self, payload: object) -> dict[str, object]:
        fields = _fields(payload, {"user_id", "token"})
        user = _user(fields["user_id"])
        token = _id(fields["token"], "token")
        with self._lock:
            preview = self._pending.get(token)
            if not isinstance(preview, CollectionPreview) or preview.user_id != user:
                raise RequestError("CONFIRMATION_NOT_FOUND", HTTPStatus.NOT_FOUND)
            del self._pending[token]
        return {"status": "CANCELLED", "operation": preview.operation,
                "mutation_count": 0}


def make_handler(service: StructuredMemoryService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: HTTPStatus, body: dict[str, object],
                  content_type: str = "application/json; charset=utf-8") -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(int(code))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/":
                raw = HTML.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            if self.path.startswith(("/api/memories?", "/api/collections?", "/api/collection?")):
                from urllib.parse import parse_qs, urlsplit

                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, strict_parsing=True)
                try:
                    expected = ({"user_id", "collection_id"} if parsed.path == "/api/collection"
                                else {"user_id"})
                    if set(query) != expected or any(len(values) != 1 for values in query.values()):
                        raise RequestError("INVALID_USER")
                    if parsed.path == "/api/memories":
                        body = service.list_scalars(query["user_id"][0])
                    elif parsed.path == "/api/collections":
                        body = service.list_collections(query["user_id"][0])
                    elif parsed.path == "/api/collection":
                        body = service.collection_detail(query["user_id"][0],
                                                         query["collection_id"][0])
                    else:
                        raise RequestError("INVALID_ROUTE")
                    self._send(HTTPStatus.OK, body)
                except RequestError as exc:
                    self._send(exc.status, {"status": "ERROR", "reason": exc.code})
                return
            self._send(HTTPStatus.NOT_FOUND, {"status": "ERROR", "reason": "NOT_FOUND"})

        def do_POST(self) -> None:
            routes = {"/api/prepare": service.prepare, "/api/confirm": service.confirm,
                      "/api/cancel": service.cancel, "/api/read": service.read,
                      "/api/collections/prepare": service.prepare_collection,
                      "/api/collections/confirm": service.confirm_collection,
                      "/api/collections/cancel": service.cancel_collection,
                      "/api/collections/read": service.read_collection}
            action = routes.get(self.path)
            if action is None:
                self._send(HTTPStatus.NOT_FOUND, {"status": "ERROR", "reason": "NOT_FOUND"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16384:
                    raise RequestError("INVALID_BODY_SIZE")
                body = json.loads(self.rfile.read(length))
                result = action(body)
                self._send(HTTPStatus.OK, result)
            except (ValueError, json.JSONDecodeError) as exc:
                if isinstance(exc, RequestError):
                    self._send(exc.status, {"status": "ERROR", "reason": exc.code})
                else:
                    self._send(HTTPStatus.BAD_REQUEST,
                               {"status": "ERROR", "reason": "INVALID_REQUEST"})
            except sqlite3.Error:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"status": "ERROR", "reason": "DATABASE_FAILURE"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured Memory V2 (no LLM)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    service = StructuredMemoryService(args.db)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    print(f"Structured Memory V2: http://127.0.0.1:{server.server_port} ",
          f"DB={service.db_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
