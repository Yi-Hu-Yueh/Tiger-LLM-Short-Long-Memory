"""S3 integration gate; every test owns an explicit disposable SQLite database."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from structured_app import RequestError, StructuredMemoryService
from structured_integrity import check_structured_integrity


class StructuredReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="_s3_", dir=Path(__file__).parent)
        self.db = Path(self.temp.name, "s3-release.db").resolve()
        self.assertTrue(self.db.is_relative_to(Path(__file__).resolve().parent))
        self.service = StructuredMemoryService(self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _snapshot(self) -> tuple[tuple[tuple[object, ...], ...], ...]:
        with closing(sqlite3.connect(self.db)) as conn:
            return tuple(tuple(tuple(row) for row in conn.execute(
                f"SELECT * FROM {table} ORDER BY rowid"))
                for table in ("scalar_lineages", "scalar_versions", "collections",
                              "membership_versions"))

    def _scalar(self, entity: str, key: str, value: str, user: str = "user1") -> str:
        prepared = self.service.prepare({"operation": "CREATE_SCALAR", "user_id": user,
                                         "entity_id": entity, "semantic_key": key,
                                         "value": value})
        self.assertEqual(prepared["mutation_count"], 0)
        result = self.service.confirm({"user_id": user, "token": prepared["preview"]["token"]})
        self.assertEqual(result["mutation_count"], 1)
        return result["memory_id"]

    def _update(self, memory_id: str, value: str, user: str = "user1") -> dict:
        prepared = self.service.prepare({"operation": "UPDATE_SCALAR", "user_id": user,
                                         "memory_id": memory_id, "value": value})
        self.assertEqual(prepared["mutation_count"], 0)
        result = self.service.confirm({"user_id": user, "token": prepared["preview"]["token"]})
        self.assertEqual(result["mutation_count"], 1)
        return result

    def _collection(self, entity: str, key: str, mode: str = "NAMED",
                    count: int | None = None, user: str = "user1") -> str:
        prepared = self.service.prepare_collection({
            "operation": "CREATE_COLLECTION", "user_id": user, "entity_id": entity,
            "semantic_key": key, "display_label": entity, "membership_mode": mode,
            "declared_count": count,
        })
        result = self.service.confirm_collection({"user_id": user,
                                                   "token": prepared["preview"]["token"]})
        self.assertEqual(result["mutation_count"], 1)
        return result["collection_id"]

    def _member(self, collection: str, member: str, operation: str,
                user: str = "user1") -> dict:
        payload = {"operation": operation, "user_id": user,
                   "collection_id": collection, "member_id": member}
        if operation != "REMOVE_MEMBER":
            payload["member_label"] = member
        prepared = self.service.prepare_collection(payload)
        if prepared["status"] == "NO_OP":
            self.assertEqual(prepared["mutation_count"], 0)
            return prepared
        result = self.service.confirm_collection({"user_id": user,
                                                   "token": prepared["preview"]["token"]})
        self.assertEqual(result["mutation_count"], 1)
        return result

    def test_end_to_end_reopen_integrity_and_zero_mutation_reads(self) -> None:
        main = self._scalar("workshop-a", "workshop.status", "A")
        self._update(main, "B")
        self._update(main, "C")
        second = self._scalar("workshop-b", "workshop.note", "unrelated")
        x = self._scalar("project-x", "project.state", "X-old")
        y = self._scalar("project-y", "project.state", "Y-only")
        self._update(x, "X-new")
        first = self._collection("atelier-one", "atelier.members")
        other = self._collection("atelier-two", "atelier.members")
        for member in ("shared", "one", "two"):
            self._member(first, member, "ADD_MEMBER")
        self._member(other, "shared", "ADD_MEMBER")
        self._member(first, "shared", "REMOVE_MEMBER")
        self.assertEqual(self.service.collection_detail("user1", other)["count"], 1)
        self._member(first, "shared", "READD_MEMBER")
        before_duplicate = self._snapshot()
        self.assertEqual(self._member(first, "shared", "ADD_MEMBER")["mutation_count"], 0)
        self.assertEqual(self._snapshot(), before_duplicate)
        count_only = self._collection("inventory-count", "inventory.count", "COUNT_ONLY", 4)
        self.assertEqual(check_structured_integrity(self.db)["status"], "PASS")

        # A fresh service instance is the server-restart equivalent for canonical state.
        self.service = StructuredMemoryService(self.db)
        before_reads = self._snapshot()
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": main,
                                             "operation": "READ_CURRENT"})["value"], "C")
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": main,
                                             "operation": "READ_PREVIOUS"})["value"], "B")
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": second,
                                             "operation": "READ_CURRENT"})["value"], "unrelated")
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": x,
                                             "operation": "READ_PREVIOUS"})["value"], "X-old")
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": y,
                                             "operation": "READ_CURRENT"})["value"], "Y-only")
        self.assertEqual(self.service.collection_detail("user1", first)["count"], 3)
        self.assertEqual(self.service.collection_detail("user1", other)["count"], 1)
        self.assertEqual(self.service.read_collection({"user_id": "user1",
                                                       "collection_id": first,
                                                       "operation": "LIST_MEMBERS"})
                         ["members"][0]["member_id"], "one")
        self.assertEqual(self.service.read_collection({"user_id": "user1",
                                                       "collection_id": first,
                                                       "operation": "COUNT_MEMBERS"})["count"], 3)
        declared = self.service.read_collection({"user_id": "user1",
                                                 "collection_id": count_only,
                                                 "operation": "READ_DECLARED_COUNT"})
        self.assertEqual((declared["count"], declared["members"]), (4, []))
        self.assertEqual(self.service.list_scalars("user1")["mutation_count"], 0)
        self.assertEqual(self.service.list_collections("user1")["mutation_count"], 0)
        self.assertEqual(self._snapshot(), before_reads)
        self.assertEqual(check_structured_integrity(self.db)["status"], "PASS")

    def test_tokens_pending_families_stale_rejection_and_user_isolation(self) -> None:
        scalar = self._scalar("shared-entity", "shared.key", "one")
        collection = self._collection("shared-entity", "shared.members")
        self._member(collection, "same-member", "ADD_MEMBER")
        foreign = self._scalar("shared-entity", "shared.key", "two", "user2")
        foreign_collection = self._collection("shared-entity", "shared.members", user="user2")
        self._member(foreign_collection, "same-member", "ADD_MEMBER", "user2")
        scalar_preview = self.service.prepare({"operation": "UPDATE_SCALAR",
                                               "user_id": "user1", "memory_id": scalar,
                                               "value": "next"})["preview"]
        self.assertEqual((scalar_preview["operation"], scalar_preview["memory_id"]),
                         ("UPDATE_SCALAR", scalar))
        scalar_pending = scalar_preview["token"]
        baseline = self._snapshot()
        with self.assertRaises(RequestError):
            self.service.confirm({"user_id": "user1", "token": scalar_pending,
                                  "memory_id": foreign})
        with self.assertRaises(RequestError):
            self.service.confirm_collection({"user_id": "user1", "token": scalar_pending})
        with self.assertRaises(RequestError):
            self.service.confirm({"user_id": "user2", "token": scalar_pending})
        self.assertEqual(self._snapshot(), baseline)
        self._member(collection, "extra", "ADD_MEMBER")
        self.assertEqual(self.service.confirm({"user_id": "user1",
                                               "token": scalar_pending})["mutation_count"], 1)
        baseline = self._snapshot()
        with self.assertRaises(RequestError):
            self.service.confirm({"user_id": "user1", "token": scalar_pending})
        self.assertEqual(self._snapshot(), baseline)

        remove_preview = self.service.prepare_collection({"operation": "REMOVE_MEMBER",
                                                          "user_id": "user1",
                                                          "collection_id": collection,
                                                          "member_id": "same-member"})["preview"]
        self.assertEqual((remove_preview["operation"], remove_preview["collection_id"],
                          remove_preview["member_id"]),
                         ("REMOVE_MEMBER", collection, "same-member"))
        remove = remove_preview["token"]
        baseline = self._snapshot()
        with self.assertRaises(RequestError):
            self.service.confirm_collection({"user_id": "user1", "token": remove,
                                             "collection_id": foreign_collection,
                                             "member_id": "same-member"})
        with self.assertRaises(RequestError):
            self.service.confirm_collection({"user_id": "user2", "token": remove})
        self.assertEqual(self._snapshot(), baseline)
        independent = self._scalar("another", "another.key", "ready")
        self.assertEqual(self.service.confirm_collection({"user_id": "user1",
                                                          "token": remove})["mutation_count"], 1)
        baseline = self._snapshot()
        with self.assertRaises(RequestError):
            self.service.confirm_collection({"user_id": "user1", "token": remove})
        self.assertEqual(self._snapshot(), baseline)
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": independent,
                                             "operation": "READ_CURRENT"})["value"], "ready")
        self.assertEqual(self.service.collection_detail("user2", foreign_collection)["count"], 1)

        stale = self.service.prepare({"operation": "UPDATE_SCALAR", "user_id": "user1",
                                      "memory_id": scalar, "value": "stale"})["preview"]["token"]
        self._update(scalar, "fresh")
        baseline = self._snapshot()
        with self.assertRaisesRegex(RequestError, "STALE_CONFIRMATION"):
            self.service.confirm({"user_id": "user1", "token": stale})
        self.assertEqual(self._snapshot(), baseline)
        cancelled = self.service.prepare({"operation": "UPDATE_SCALAR", "user_id": "user1",
                                          "memory_id": scalar, "value": "cancel"})["preview"]["token"]
        self.assertEqual(self.service.cancel({"user_id": "user1", "token": cancelled})
                         ["mutation_count"], 0)
        with self.assertRaises(RequestError):
            self.service.prepare_collection({"operation": "REMOVE_MEMBER", "user_id": "user1",
                                             "collection_id": foreign_collection,
                                             "member_id": "same-member"})
        with self.assertRaises(RequestError):
            self.service.prepare({"operation": "UPDATE_SCALAR", "user_id": "user1",
                                  "memory_id": foreign, "value": "intrusion"})
        self.assertEqual(self._snapshot(), baseline)
        self.assertEqual(check_structured_integrity(self.db)["status"], "PASS")

    def test_count_only_rejects_member_actions_and_checker_detects_corruption(self) -> None:
        count_only = self._collection("headcount", "headcount.count", "COUNT_ONLY", 4)
        baseline = self._snapshot()
        with self.assertRaisesRegex(RequestError, "UNSUPPORTED_OPERATION"):
            self.service.prepare_collection({"operation": "REMOVE_MEMBER", "user_id": "user1",
                                             "collection_id": count_only, "member_id": "invented"})
        self.assertEqual(self._snapshot(), baseline)
        self.assertEqual(check_structured_integrity(self.db)["status"], "PASS")
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO membership_versions "
                         "(collection_id,member_id,member_label,status,created_at) "
                         "VALUES (?,?,?,?,?)", (count_only, "invented", "invented",
                                                "CURRENT", "test"))
            conn.commit()
        checked = check_structured_integrity(self.db)
        self.assertEqual(checked["status"], "FAIL")
        self.assertIn("COUNT_ONLY_HAS_MEMBER_IDENTITY", checked["issues"])


if __name__ == "__main__":
    unittest.main()
