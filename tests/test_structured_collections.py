"""S2 structured collection gate on disposable, explicitly scoped databases."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from memory_v2 import MemoryV2Core, Status
from structured_app import StructuredMemoryService


class StructuredCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="_s2_", dir=Path(__file__).parent)
        self.db = Path(self.temp.name, "s2-test.db").resolve()
        self.assertTrue(self.db.is_relative_to(Path(__file__).resolve().parent))
        self.service = StructuredMemoryService(self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare_create(self, entity="array-a", label="Array A", key="array.elements",
                       mode="NAMED", count=None, user="user1"):
        return self.service.prepare_collection({
            "operation": "CREATE_COLLECTION", "user_id": user,
            "entity_id": entity, "semantic_key": key, "display_label": label,
            "membership_mode": mode, "declared_count": count,
        })

    def confirm(self, prepared, user="user1"):
        return self.service.confirm_collection({"user_id": user,
                                                "token": prepared["preview"]["token"]})

    def create(self, **kwargs):
        return self.confirm(self.prepare_create(**kwargs), kwargs.get("user", "user1"))

    def prepare_add(self, collection, member, label=None, user="user1", operation="ADD_MEMBER"):
        return self.service.prepare_collection({
            "operation": operation, "user_id": user, "collection_id": collection,
            "member_id": member, "member_label": label or member,
        })

    def prepare_remove(self, collection, member, user="user1"):
        return self.service.prepare_collection({
            "operation": "REMOVE_MEMBER", "user_id": user,
            "collection_id": collection, "member_id": member,
        })

    def add(self, collection, member, label=None, user="user1", operation="ADD_MEMBER"):
        return self.confirm(self.prepare_add(collection, member, label, user, operation), user)

    def remove(self, collection, member, user="user1"):
        return self.confirm(self.prepare_remove(collection, member, user), user)

    def detail(self, collection, user="user1"):
        return self.service.collection_detail(user, collection)

    def read(self, collection, operation, user="user1"):
        return self.service.read_collection({"user_id": user, "collection_id": collection,
                                             "operation": operation})

    def test_01_create_named_requires_confirm(self):
        prepared = self.prepare_create()
        self.assertEqual(self.service.list_collections("user1")["collections"], [])
        made = self.confirm(prepared)
        self.assertEqual((made["status"], made["mutation_count"]), ("CREATED", 1))
        self.assertEqual(made["collection_id"], prepared["preview"]["collection_id"])

    def test_02_list_collections_uses_stable_identity_and_label(self):
        first = self.create()
        self.create(entity="array-b", label="Array A")
        rows = self.service.list_collections("user1")["collections"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["display_label"] for r in rows}, {"Array A"})
        self.assertIn(first["collection_id"], {r["collection_id"] for r in rows})

    def test_03_add_member_only_after_confirm(self):
        collection = self.create()["collection_id"]
        prepared = self.prepare_add(collection, "node-x", "Node X")
        self.assertEqual(self.detail(collection)["members"], [])
        self.assertEqual(self.confirm(prepared)["mutation_count"], 1)
        self.assertEqual(self.detail(collection)["members"],
                         [{"member_id": "node-x", "member_label": "Node X"}])

    def test_04_list_members(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-y")
        self.add(collection, "node-x")
        self.assertEqual([m["member_id"] for m in self.read(collection, "LIST_MEMBERS")["members"]],
                         ["node-x", "node-y"])

    def test_05_count_named_is_derived(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        self.add(collection, "node-y")
        self.assertEqual(self.read(collection, "COUNT_MEMBERS")["count"], 2)
        self.remove(collection, "node-x")
        self.assertEqual(self.read(collection, "COUNT_MEMBERS")["count"], 1)

    def test_06_duplicate_add_is_no_op(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        before = self.detail(collection)["member_versions"]
        result = self.prepare_add(collection, "node-x", "different label")
        self.assertEqual((result["status"], result["mutation_count"]), ("NO_OP", 0))
        self.assertEqual(self.detail(collection)["member_versions"], before)

    def test_07_remove_is_explicit_and_confirmed(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        prepared = self.prepare_remove(collection, "node-x")
        self.assertEqual(self.detail(collection)["count"], 1)
        self.confirm(prepared)
        self.assertEqual(self.detail(collection)["count"], 0)

    def test_08_readd_preserves_one_active_membership(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        self.remove(collection, "node-x")
        self.add(collection, "node-x", operation="READD_MEMBER")
        self.assertEqual(self.detail(collection)["count"], 1)
        with closing(sqlite3.connect(self.db)) as conn:
            active = conn.execute("SELECT COUNT(*) FROM membership_versions WHERE "
                                  "collection_id=? AND member_id=? AND status='CURRENT'",
                                  (collection, "node-x")).fetchone()[0]
            versions = conn.execute("SELECT COUNT(*) FROM membership_versions WHERE "
                                    "collection_id=? AND member_id=?",
                                    (collection, "node-x")).fetchone()[0]
        self.assertEqual((active, versions), (1, 2))

    def test_09_same_member_can_exist_in_two_collections(self):
        a = self.create()["collection_id"]
        b = self.create(entity="array-b")["collection_id"]
        self.add(a, "shared-node")
        self.add(b, "shared-node")
        self.assertEqual((self.detail(a)["count"], self.detail(b)["count"]), (1, 1))

    def test_10_remove_from_a_leaves_b_unchanged(self):
        a = self.create()["collection_id"]
        b = self.create(entity="array-b")["collection_id"]
        self.add(a, "shared-node")
        self.add(b, "shared-node")
        before_b = self.detail(b)
        self.remove(a, "shared-node")
        self.assertEqual(self.detail(a)["members"], [])
        self.assertEqual(self.detail(b), before_b)

    def test_11_same_member_id_is_user_scoped(self):
        one = self.create()["collection_id"]
        two = self.create(user="user2")["collection_id"]
        self.add(one, "shared-node")
        self.add(two, "shared-node", user="user2")
        self.remove(one, "shared-node")
        self.assertEqual(self.detail(two, "user2")["count"], 1)

    def test_12_create_count_only(self):
        prepared = self.prepare_create(entity="anonymous-a", mode="COUNT_ONLY", count=4)
        self.assertEqual(self.service.list_collections("user1")["collections"], [])
        made = self.confirm(prepared)
        self.assertEqual(self.detail(made["collection_id"])["membership_mode"], "COUNT_ONLY")

    def test_13_read_declared_count(self):
        collection = self.create(entity="anonymous-a", mode="COUNT_ONLY", count=4)["collection_id"]
        self.assertEqual(self.read(collection, "READ_DECLARED_COUNT")["count"], 4)

    def test_14_count_only_never_invents_identities(self):
        collection = self.create(entity="anonymous-a", mode="COUNT_ONLY", count=4)["collection_id"]
        result = self.read(collection, "READ_DECLARED_COUNT")
        self.assertEqual((result["members"], result["member_identities"]), ([], "UNKNOWN"))
        self.assertEqual(self.detail(collection)["members"], [])

    def test_15_count_only_remove_is_zero_mutation(self):
        collection = self.create(entity="anonymous-a", mode="COUNT_ONLY", count=4)["collection_id"]
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_OPERATION"):
            self.prepare_remove(collection, "unknown-node")
        self.assertEqual(self.read(collection, "READ_DECLARED_COUNT")["count"], 4)

    def test_16_cancel_create(self):
        prepared = self.prepare_create()
        result = self.service.cancel_collection({"user_id": "user1",
                                                 "token": prepared["preview"]["token"]})
        self.assertEqual(result["mutation_count"], 0)
        self.assertEqual(self.service.list_collections("user1")["collections"], [])

    def test_17_cancel_add(self):
        collection = self.create()["collection_id"]
        prepared = self.prepare_add(collection, "node-x")
        self.service.cancel_collection({"user_id": "user1", "token": prepared["preview"]["token"]})
        self.assertEqual(self.detail(collection)["count"], 0)

    def test_18_cancel_remove(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        prepared = self.prepare_remove(collection, "node-x")
        self.service.cancel_collection({"user_id": "user1", "token": prepared["preview"]["token"]})
        self.assertEqual(self.detail(collection)["count"], 1)

    def test_19_duplicate_confirm_is_rejected(self):
        prepared = self.prepare_create()
        self.confirm(prepared)
        with self.assertRaisesRegex(ValueError, "CONFIRMATION_NOT_FOUND"):
            self.confirm(prepared)
        self.assertEqual(len(self.service.list_collections("user1")["collections"]), 1)

    def test_20_stale_confirmation_after_external_writer(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        stale = self.prepare_remove(collection, "node-x")
        external = MemoryV2Core(self.db)
        self.assertEqual(external.add_collection_member(
            "user1", collection, "node-y", "node-y").status, Status.APPLIED)
        with self.assertRaisesRegex(ValueError, "STALE_CONFIRMATION"):
            self.confirm(stale)
        self.assertEqual(self.detail(collection)["count"], 2)

    def test_21_collection_token_cannot_confirm_scalar(self):
        prepared = self.prepare_create()
        with self.assertRaisesRegex(ValueError, "CONFIRMATION_NOT_FOUND"):
            self.service.confirm({"user_id": "user1", "token": prepared["preview"]["token"]})
        self.assertEqual(self.service.list_scalars("user1")["memories"], [])
        self.confirm(prepared)

    def test_22_scalar_token_cannot_confirm_collection(self):
        scalar = self.service.prepare({"operation": "CREATE_SCALAR", "user_id": "user1",
                                       "entity_id": "scalar-x", "semantic_key": "scalar.option",
                                       "value": "narrow"})
        with self.assertRaisesRegex(ValueError, "CONFIRMATION_NOT_FOUND"):
            self.service.confirm_collection({"user_id": "user1",
                                             "token": scalar["preview"]["token"]})
        self.assertEqual(self.service.list_collections("user1")["collections"], [])
        self.service.confirm({"user_id": "user1", "token": scalar["preview"]["token"]})

    def test_23_reads_create_zero_mutation(self):
        collection = self.create()["collection_id"]
        self.add(collection, "node-x")
        before = self.detail(collection)["member_versions"]
        self.service.list_collections("user1")
        self.detail(collection)
        self.read(collection, "LIST_MEMBERS")
        self.read(collection, "COUNT_MEMBERS")
        self.assertEqual(self.detail(collection)["member_versions"], before)

    def test_24_user_ownership_violations_fail(self):
        collection = self.create(user="user2")["collection_id"]
        self.assertEqual(self.service.list_collections("user1")["collections"], [])
        for action in (lambda: self.detail(collection),
                       lambda: self.prepare_add(collection, "node-x"),
                       lambda: self.prepare_remove(collection, "node-x")):
            with self.assertRaisesRegex(ValueError, "COLLECTION_NOT_FOUND"):
                action()
        self.assertEqual(self.detail(collection, "user2")["count"], 0)

    def test_25_scalar_s1_workflow_still_functions(self):
        self.create()
        scalar = self.service.prepare({"operation": "CREATE_SCALAR", "user_id": "user1",
                                       "entity_id": "scalar-x", "semantic_key": "scalar.option",
                                       "value": "narrow"})
        made = self.service.confirm({"user_id": "user1", "token": scalar["preview"]["token"]})
        update = self.service.prepare({"operation": "UPDATE_SCALAR", "user_id": "user1",
                                       "memory_id": made["memory_id"], "value": "wide"})
        self.service.confirm({"user_id": "user1", "token": update["preview"]["token"]})
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                                            "operation": "READ_PREVIOUS"})["value"], "narrow")

    def test_26_generated_ten_collection_generalization(self):
        collections = [self.create(entity=f"rack-{n:02d}", label=f"Rack {n:02d}")["collection_id"]
                       for n in range(10)]
        for index, collection in enumerate(collections):
            for member in ("shared-1", "shared-2", "shared-3", f"local-{index}-a",
                           f"local-{index}-b"):
                self.add(collection, member)
            self.assertEqual(self.prepare_add(collection, "shared-1")["status"], "NO_OP")
        baseline = [self.detail(collection) for collection in collections]
        self.remove(collections[0], "shared-1")
        self.add(collections[0], "shared-1", operation="READD_MEMBER")
        self.assertEqual(self.read(collections[0], "COUNT_MEMBERS")["count"], 5)
        self.assertEqual(len(self.read(collections[0], "LIST_MEMBERS")["members"]), 5)
        self.assertEqual([self.detail(collection) for collection in collections[1:]], baseline[1:])


if __name__ == "__main__":
    unittest.main()
