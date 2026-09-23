"""Deterministic V2 algebra gates using only generated, isolated test data."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from memory_v2 import Member, MemoryV2Core, Status


class GenericMemoryV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="_v2_", dir=Path(__file__).resolve().parent
        )
        self.db_path = Path(self.temp.name, "core-test.db").resolve()
        self.assertTrue(self.db_path.is_relative_to(Path(__file__).resolve().parent))
        self.core = MemoryV2Core(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _sql(self, statement: str, parameters: tuple = ()) -> list[tuple]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(statement, parameters).fetchall()

    def test_scalar_lineage_previous_reassert_and_no_fallback(self) -> None:
        initial = self.core.create_scalar("user1", "observatory.mount", "polar", entity_id="scope-1")
        self.assertEqual(initial.status, Status.APPLIED)
        self.assertEqual(self.core.get_previous_scalar("user1", memory_id=initial.memory_id).status,
                         Status.NO_PREVIOUS)
        self.assertEqual(self.core.get_previous_scalar(
            "user1", semantic_key="observatory.mount", entity_id="scope-1"
        ).status, Status.AMBIGUOUS_TARGET)
        second = self.core.set_scalar("user1", "azimuth", memory_id=initial.memory_id)
        third = self.core.set_scalar("user1", "gimbal", memory_id=initial.memory_id)
        self.assertEqual(second.memory_id, initial.memory_id)
        self.assertEqual(third.memory_id, initial.memory_id)
        self.assertEqual(self.core.get_current_scalar("user1", memory_id=initial.memory_id).value,
                         "gimbal")
        self.assertEqual(self.core.get_previous_scalar("user1", memory_id=initial.memory_id).value,
                         "azimuth")
        timeline = self.core.get_scalar_timeline("user1", memory_id=initial.memory_id)
        self.assertEqual([v.value for v in timeline.timeline], ["polar", "azimuth", "gimbal"])
        self.assertEqual([v.predecessor_version_id for v in timeline.timeline],
                         [None, timeline.timeline[0].version_id, timeline.timeline[1].version_id])
        reassert = self.core.set_scalar("user1", "gimbal", memory_id=initial.memory_id)
        self.assertEqual((reassert.status, reassert.mutation_count), (Status.NO_OP, 0))
        self.assertEqual(self.core.get_scalar_timeline("user1", memory_id=initial.memory_id).timeline,
                         timeline.timeline)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM scalar_versions WHERE memory_id=? AND status='CURRENT'",
                                   (initial.memory_id,)), [(1,)])

    def test_generated_fifty_lineages_shared_keys_entities_and_users(self) -> None:
        identities = []
        for number in range(50):
            user = "user1" if number % 2 == 0 else "user2"
            # Same keys on many entities; several keys also share one entity.
            key = f"synthetic.dimension_{number % 7:02d}"
            entity = f"specimen_{number // 7:02d}"
            a, b, c = (f"v{number}-{step}" for step in "ABC")
            first = self.core.set_scalar(user, a, semantic_key=key, entity_id=entity)
            self.assertEqual(first.status, Status.APPLIED)
            self.core.set_scalar(user, b, memory_id=first.memory_id)
            self.core.set_scalar(user, c, memory_id=first.memory_id)
            identities.append((user, entity, key, first.memory_id, a, b, c))
        self.assertEqual(len({row[3] for row in identities}), 50)
        self.assertLess(len({row[2] for row in identities}), 50)
        self.assertLess(len({(row[0], row[1]) for row in identities}), 50)
        for user, entity, key, memory_id, a, b, c in identities:
            current = self.core.get_current_scalar(user, memory_id=memory_id)
            previous = self.core.get_previous_scalar(user, memory_id=memory_id)
            timeline = self.core.get_scalar_timeline(user, memory_id=memory_id)
            self.assertEqual((current.value, previous.value), (c, b))
            self.assertEqual((current.entity_id, current.semantic_key), (entity, key))
            self.assertEqual([v.value for v in timeline.timeline], [a, b, c])
            self.assertEqual(self.core.set_scalar(user, c, memory_id=memory_id).status,
                             Status.NO_OP)
            self.assertEqual(len(self.core.get_scalar_timeline(user, memory_id=memory_id).timeline), 3)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM scalar_versions WHERE status='CURRENT'"),
                         [(50,)])

    def test_same_key_distinct_entities_and_ambiguous_key_only(self) -> None:
        left = self.core.create_scalar("user1", "instrument.finish", "matte", entity_id="unit-x")
        right = self.core.create_scalar("user1", "instrument.finish", "gloss", entity_id="unit-y")
        self.assertNotEqual(left.memory_id, right.memory_id)
        self.assertEqual(left.semantic_key, right.semantic_key)
        ambiguous = self.core.set_scalar("user1", "satin", semantic_key="instrument.finish")
        self.assertEqual((ambiguous.status, ambiguous.mutation_count),
                         (Status.AMBIGUOUS_TARGET, 0))
        self.assertEqual(self.core.get_previous_scalar("user1", semantic_key="instrument.finish").status,
                         Status.AMBIGUOUS_TARGET)
        changed = self.core.set_scalar("user1", "satin", memory_id=left.memory_id)
        self.assertEqual(changed.memory_id, left.memory_id)
        self.assertEqual(self.core.get_previous_scalar("user1", memory_id=left.memory_id).value,
                         "matte")
        self.assertEqual(self.core.get_current_scalar("user1", memory_id=right.memory_id).value,
                         "gloss")
        self.assertEqual(self.core.get_current_scalar("user1", semantic_key="instrument.finish",
                                                      entity_id="unit-y").memory_id, right.memory_id)

    def test_unknown_no_previous_and_explicit_no_op(self) -> None:
        self.assertEqual(self.core.get_current_scalar("user1", semantic_key="absent.factor").status,
                         Status.NOT_FOUND)
        first = self.core.create_scalar("user1", "absent.factor", "seed", entity_id="object-q")
        previous = self.core.get_previous_scalar("user1", memory_id=first.memory_id)
        self.assertEqual((previous.status, previous.value, previous.mutation_count),
                         (Status.NO_PREVIOUS, None, 0))
        self.assertEqual(self.core.no_op("user1").mutation_count, 0)
        self.assertEqual(self.core.create_scalar("user1", "absent.factor", "other",
                                                 entity_id="object-q").status, Status.CONFLICT)

    def test_generated_ten_collections_shared_members_and_lifecycle(self) -> None:
        collections = []
        for number in range(10):
            made = self.core.create_collection("user1", f"assembly.set_{number:02d}",
                                               entity_id=f"assembly-{number:02d}")
            self.assertEqual(made.status, Status.APPLIED)
            self.assertEqual(made.memory_id, made.collection_id)
            collections.append(made.collection_id)
            members = [Member("shared-node", "shared node")]
            members += [Member(f"item-{number}-{idx}", f"label {number}/{idx}")
                        for idx in range(4)]
            self.assertEqual(self.core.replace_collection_members("user1", made.collection_id,
                                                                    members).status, Status.APPLIED)
            self.assertEqual(self.core.count_collection_members("user1", made.collection_id).count, 5)
        left, right = collections[:2]
        self.assertEqual(self.core.add_collection_member("user1", left, "shared-node",
                                                         "shared node").status, Status.NO_OP)
        self.assertEqual(self.core.remove_collection_member("user1", left, "shared-node").status,
                         Status.APPLIED)
        self.assertEqual(self.core.count_collection_members("user1", left).count, 4)
        self.assertEqual(self.core.count_collection_members("user1", right).count, 5)
        self.assertEqual(self.core.add_collection_member("user1", left, "shared-node",
                                                         "shared node").status, Status.APPLIED)
        self.assertEqual(self.core.count_collection_members("user1", left).count, 5)
        self.assertEqual(self.core.remove_collection_member("user1", left, "nonmember").status,
                         Status.NOT_FOUND)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM membership_versions WHERE status='CURRENT' "
                                   "AND collection_id=? AND member_id='shared-node'", (left,)), [(1,)])
        self.assertEqual(self.core.list_collection_members("user1", right).count, 5)

    def test_count_only_ambiguity_does_not_invent_members_or_decrement(self) -> None:
        made = self.core.create_collection("user1", "inventory.unknown_units",
                                           entity_id="lot-8", membership_mode="COUNT_ONLY",
                                           declared_count=4)
        result = self.core.remove_collection_member("user1", made.collection_id, None)
        self.assertEqual((result.status, result.mutation_count), (Status.AMBIGUOUS_TARGET, 0))
        self.assertEqual(self.core.get_collection_declared_count("user1", made.collection_id).count, 4)
        self.assertEqual(self.core.count_collection_members("user1", made.collection_id).status,
                         Status.UNSUPPORTED)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM membership_versions WHERE collection_id=?",
                                   (made.collection_id,)), [(0,)])

    def test_user_isolation_on_same_entity_key_and_collection_id(self) -> None:
        a = self.core.create_scalar("user1", "sensor.range", 1, entity_id="sensor-common")
        b = self.core.create_scalar("user2", "sensor.range", 9, entity_id="sensor-common")
        self.assertEqual(self.core.get_current_scalar("user1", memory_id=b.memory_id).status,
                         Status.NOT_FOUND)
        self.assertEqual(self.core.set_scalar("user1", 4, memory_id=b.memory_id).status,
                         Status.NOT_FOUND)
        self.assertEqual(self.core.get_current_scalar("user2", memory_id=b.memory_id).value, 9)
        self.assertEqual(self.core.get_current_scalar("user1", memory_id=a.memory_id).value, 1)
        collection = self.core.create_collection("user2", "rack.members", entity_id="rack-1")
        self.assertEqual(self.core.list_collection_members("user1", collection.collection_id).status,
                         Status.NOT_FOUND)
        self.assertEqual(self.core.add_collection_member("user1", collection.collection_id,
                                                         "item", "item").status, Status.NOT_FOUND)

    def test_scalar_transaction_failure_rolls_back_supersession(self) -> None:
        made = self.core.create_scalar("user1", "heater.setting", "low", entity_id="heater-a")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TRIGGER fail_version_insert BEFORE INSERT ON scalar_versions "
                         "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
            conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.core.set_scalar("user1", "high", memory_id=made.memory_id)
        self.assertEqual(self.core.get_current_scalar("user1", memory_id=made.memory_id).value,
                         "low")
        self.assertEqual(self.core.get_previous_scalar("user1", memory_id=made.memory_id).status,
                         Status.NO_PREVIOUS)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM scalar_versions WHERE memory_id=?",
                                   (made.memory_id,)), [(1,)])

    def test_collection_replace_failure_rolls_back_all_memberships(self) -> None:
        collection = self.core.create_collection("user1", "archive.operators", entity_id="archive-b")
        self.core.replace_collection_members("user1", collection.collection_id,
                                             [Member("one", "one"), Member("two", "two")])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TRIGGER fail_member_insert BEFORE INSERT ON membership_versions "
                         "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
            conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.core.replace_collection_members("user1", collection.collection_id,
                                                 [Member("three", "three")])
        self.assertEqual([m.member_id for m in self.core.list_collection_members(
            "user1", collection.collection_id).members], ["one", "two"])

    def test_concurrent_scalar_corrections_reassertions_and_same_key_entities(self) -> None:
        left = self.core.create_scalar("user1", "apparatus.phase", "A", entity_id="node-L")
        right = self.core.create_scalar("user1", "apparatus.phase", "X", entity_id="node-R")
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda value: self.core.set_scalar(
                "user1", value, memory_id=left.memory_id), ["B", "C", "C", "C"]))
            list(pool.map(lambda value: self.core.set_scalar(
                "user1", value, memory_id=right.memory_id), ["Y", "Z"]))
        self.assertTrue(all(o.status in (Status.APPLIED, Status.NO_OP) for o in outcomes))
        for memory_id in (left.memory_id, right.memory_id):
            timeline = self.core.get_scalar_timeline("user1", memory_id=memory_id).timeline
            self.assertEqual(len([v for v in timeline if v.status == "CURRENT"]), 1)
            for before, after in zip(timeline, timeline[1:]):
                self.assertEqual(after.predecessor_version_id, before.version_id)
        self.assertIn(self.core.get_current_scalar("user1", memory_id=right.memory_id).value,
                      ("Y", "Z"))
        self.assertEqual({v.value for v in self.core.get_scalar_timeline(
            "user1", memory_id=right.memory_id).timeline}, {"X", "Y", "Z"})

    def test_concurrent_membership_actions_preserve_unique_active_state(self) -> None:
        first = self.core.create_collection("user1", "panel.contacts", entity_id="panel-a")
        second = self.core.create_collection("user1", "panel.contacts", entity_id="panel-b")
        self.core.add_collection_member("user1", second.collection_id, "common", "common")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.core.add_collection_member(
                "user1", first.collection_id, "common", "common"), range(4)))
            list(pool.map(lambda _: self.core.remove_collection_member(
                "user1", first.collection_id, "common"), range(4)))
        self.assertEqual(self.core.count_collection_members("user1", first.collection_id).count, 0)
        self.assertEqual(self.core.count_collection_members("user1", second.collection_id).count, 1)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM membership_versions WHERE "
                                   "collection_id=? AND member_id='common' AND status='CURRENT'",
                                   (first.collection_id,)), [(0,)])

    def test_static_no_domain_branches_or_provider_dependency(self) -> None:
        package = Path(__file__).resolve().parents[1] / "memory_v2"
        sources = [path.read_text(encoding="utf-8") for path in package.glob("*.py")]
        forbidden = (
            "office", "car", "drink", "pet", "birthday", "desk", "phone", "printer",
            "vehicle", "research group", "lab", "study group", "team", "band",
            "hiking group", "photography club", "project alpha",
        )
        for source in sources:
            tree = ast.parse(source)
            literals = [node.value.casefold() for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            for literal in literals:
                for domain in forbidden:
                    self.assertIsNone(re.search(r"(?<![a-z])" + re.escape(domain)
                                                + r"(?![a-z])", literal),
                                      f"domain literal {domain} found in production core")
            self.assertNotIn("deepseek", source.casefold())


if __name__ == "__main__":
    unittest.main()
