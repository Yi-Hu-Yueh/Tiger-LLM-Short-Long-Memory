"""Focused S1 structured UI/service gates on disposable SQLite databases."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from memory_v2 import MemoryV2Core, Status
from structured_app import StructuredMemoryService, make_handler, safe_db_path
from http.server import ThreadingHTTPServer


class StructuredAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="_structured_", dir=Path(__file__).resolve().parent)
        self.db = Path(self.temp.name, "s1-test.db").resolve()
        self.assertTrue(self.db.is_relative_to(Path(__file__).resolve().parent))
        self.service = StructuredMemoryService(self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare_create(self, user: str = "user1", entity: str = "scope-x",
                       key: str = "optics.aperture", value: str = "narrow") -> dict:
        return self.service.prepare({"operation": "CREATE_SCALAR", "user_id": user,
                                     "entity_id": entity, "semantic_key": key,
                                     "value": value})

    def create(self, **kwargs: str) -> dict:
        preview = self.prepare_create(**kwargs)
        return self.service.confirm({"user_id": kwargs.get("user", "user1"),
                                     "token": preview["preview"]["token"]})

    def prepare_update(self, memory_id: str, value: str, user: str = "user1") -> dict:
        return self.service.prepare({"operation": "UPDATE_SCALAR", "user_id": user,
                                     "memory_id": memory_id, "value": value})

    def confirm(self, preview: dict, user: str = "user1") -> dict:
        return self.service.confirm({"user_id": user, "token": preview["preview"]["token"]})

    def test_01_prepare_create_then_confirm_once(self) -> None:
        preview = self.prepare_create()
        self.assertEqual(preview["status"], "CONFIRMATION_REQUIRED")
        self.assertEqual(self.service.list_scalars("user1")["memories"], [])
        result = self.confirm(preview)
        self.assertEqual((result["status"], result["mutation_count"]), ("CREATED", 1))
        self.assertEqual(self.service.list_scalars("user1")["memories"][0]["memory_id"],
                         result["memory_id"])

    def test_02_read_current(self) -> None:
        made = self.create()
        result = self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                                    "operation": "READ_CURRENT"})
        self.assertEqual((result["value"], result["mutation_count"]), ("narrow", 0))

    def test_03_update_preserves_identity_and_previous(self) -> None:
        made = self.create()
        change = self.confirm(self.prepare_update(made["memory_id"], "wide"))
        self.assertEqual(change["memory_id"], made["memory_id"])
        self.assertEqual(self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                                            "operation": "READ_PREVIOUS"})["value"], "narrow")

    def test_04_three_value_lineage_current_and_previous(self) -> None:
        made = self.create()
        self.confirm(self.prepare_update(made["memory_id"], "medium"))
        self.confirm(self.prepare_update(made["memory_id"], "wide"))
        current = self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                                     "operation": "READ_CURRENT"})
        previous = self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                                      "operation": "READ_PREVIOUS"})
        self.assertEqual((current["value"], previous["value"]), ("wide", "medium"))
        self.assertEqual([v.value for v in self.service.core.get_scalar_timeline(
            "user1", memory_id=made["memory_id"]).timeline], ["narrow", "medium", "wide"])

    def test_05_no_previous_never_falls_back_to_current(self) -> None:
        made = self.create()
        result = self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                                    "operation": "READ_PREVIOUS"})
        self.assertEqual(result["status"], "NO_PREVIOUS")
        self.assertIsNone(result["value"])
        self.assertEqual(result["message"], "No previous value")

    def test_06_reassertion_no_op_and_no_version(self) -> None:
        made = self.create()
        before = self.service.core.get_scalar_timeline("user1", memory_id=made["memory_id"])
        result = self.prepare_update(made["memory_id"], "narrow")
        after = self.service.core.get_scalar_timeline("user1", memory_id=made["memory_id"])
        self.assertEqual((result["status"], result["mutation_count"]), ("NO_OP", 0))
        self.assertEqual(before.timeline, after.timeline)

    def test_07_user_selector_lists_only_selected_user(self) -> None:
        one = self.create()
        two = self.create(user="user2", entity="scope-y", value="broad")
        self.assertEqual([m["memory_id"] for m in self.service.list_scalars("user1")["memories"]],
                         [one["memory_id"]])
        self.assertEqual([m["memory_id"] for m in self.service.list_scalars("user2")["memories"]],
                         [two["memory_id"]])

    def test_08_same_semantic_key_two_entities_isolated(self) -> None:
        first = self.create(entity="scope-x", key="optics.aperture", value="narrow")
        second = self.create(entity="scope-y", key="optics.aperture", value="broad")
        self.assertNotEqual(first["memory_id"], second["memory_id"])
        self.confirm(self.prepare_update(first["memory_id"], "medium"))
        self.assertEqual(self.service.core.get_current_scalar(
            "user1", memory_id=first["memory_id"]).value, "medium")
        self.assertEqual(self.service.core.get_previous_scalar(
            "user1", memory_id=first["memory_id"]).value, "narrow")
        self.assertEqual(self.service.core.get_current_scalar(
            "user1", memory_id=second["memory_id"]).value, "broad")

    def test_09_foreign_memory_update_and_read_rejected(self) -> None:
        made = self.create(user="user2")
        with self.assertRaisesRegex(ValueError, "MEMORY_NOT_FOUND"):
            self.prepare_update(made["memory_id"], "wide", user="user1")
        with self.assertRaisesRegex(ValueError, "MEMORY_NOT_FOUND"):
            self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                               "operation": "READ_CURRENT"})
        self.assertEqual(self.service.core.get_current_scalar(
            "user2", memory_id=made["memory_id"]).value, "narrow")

    def test_10_malformed_inputs_create_no_memory(self) -> None:
        invalid = (
            {"operation": "CREATE_SCALAR", "user_id": "", "entity_id": "x",
             "semantic_key": "k", "value": "v"},
            {"operation": "CREATE_SCALAR", "user_id": "user1", "entity_id": "",
             "semantic_key": "k", "value": "v"},
            {"operation": "CREATE_SCALAR", "user_id": "user1", "entity_id": "x",
             "semantic_key": "", "value": "v"},
            {"operation": "CREATE_SCALAR", "user_id": "user1", "entity_id": "x",
             "semantic_key": "k", "value": "   "},
            {"operation": "CREATE_SCALAR", "user_id": "user1", "entity_id": "x",
             "semantic_key": "k", "value": "v", "extra": "bad"},
        )
        for payload in invalid:
            with self.assertRaises(ValueError):
                self.service.prepare(payload)
        self.assertEqual(self.service.list_scalars("user1")["memories"], [])

    def test_11_cancel_confirmation_has_zero_mutation(self) -> None:
        preview = self.prepare_create()
        cancelled = self.service.cancel({"user_id": "user1", "token": preview["preview"]["token"]})
        self.assertEqual((cancelled["status"], cancelled["mutation_count"]), ("CANCELLED", 0))
        self.assertEqual(self.service.list_scalars("user1")["memories"], [])

    def test_12_duplicate_confirm_safely_rejected(self) -> None:
        preview = self.prepare_create()
        made = self.confirm(preview)
        with self.assertRaisesRegex(ValueError, "CONFIRMATION_NOT_FOUND"):
            self.confirm(preview)
        self.assertEqual(len(self.service.core.get_scalar_timeline(
            "user1", memory_id=made["memory_id"]).timeline), 1)

    def test_13_stale_update_preview_rejected(self) -> None:
        made = self.create()
        stale = self.prepare_update(made["memory_id"], "very-wide")
        current = self.prepare_update(made["memory_id"], "medium")
        self.confirm(current)
        with self.assertRaisesRegex(ValueError, "STALE_CONFIRMATION"):
            self.confirm(stale)
        self.assertEqual(self.service.core.get_current_scalar(
            "user1", memory_id=made["memory_id"]).value, "medium")

    def test_14_reads_do_not_create_versions(self) -> None:
        made = self.create()
        before = self.service.core.get_scalar_timeline("user1", memory_id=made["memory_id"])
        self.service.list_scalars("user1")
        for operation in ("READ_CURRENT", "READ_PREVIOUS"):
            self.service.read({"user_id": "user1", "memory_id": made["memory_id"],
                               "operation": operation})
        after = self.service.core.get_scalar_timeline("user1", memory_id=made["memory_id"])
        self.assertEqual(before.timeline, after.timeline)

    def test_15_http_ui_and_api_are_independent(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/") as response:
                html = response.read().decode("utf-8")
            self.assertIn("Structured Memory V2", html)
            self.assertIn("Read Previous", html)
            body = json.dumps({"operation": "CREATE_SCALAR", "user_id": "user1",
                               "entity_id": "scope-x", "semantic_key": "optics.aperture",
                               "value": "narrow"}).encode("utf-8")
            request = Request(base + "/api/prepare", data=body,
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request) as response:
                prepared = json.load(response)
            self.assertEqual(prepared["status"], "CONFIRMATION_REQUIRED")
            self.assertEqual(self.service.list_scalars("user1")["memories"], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_16_protected_database_names_rejected(self) -> None:
        for name in ("memory.db", "final_acceptance.db", "real40_v2.db"):
            with self.assertRaises(ValueError):
                safe_db_path(Path(self.temp.name, name))

    def test_17_external_writer_cannot_race_stale_confirm(self) -> None:
        made = self.create()
        pending = self.prepare_update(made["memory_id"], "very-wide")
        external = MemoryV2Core(self.db)
        self.assertEqual(external.set_scalar(
            "user1", "medium", memory_id=made["memory_id"]).status, Status.APPLIED)
        with self.assertRaisesRegex(ValueError, "STALE_CONFIRMATION"):
            self.confirm(pending)
        self.assertEqual(self.service.core.get_current_scalar(
            "user1", memory_id=made["memory_id"]).value, "medium")

    def test_18_governed_scalar_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "VALUE_TOO_LONG"):
            self.prepare_create(value="x" * 161)
        for number in range(20):
            self.create(entity=f"scope-{number:02d}", key=f"optics.mode_{number:02d}")
        extra = self.prepare_create(entity="scope-extra", key="optics.extra")
        with self.assertRaisesRegex(ValueError, "MEMORY_LIMIT"):
            self.confirm(extra)
        self.assertEqual(len(self.service.list_scalars("user1")["memories"]), 20)

    def test_19_database_failure_rolls_back_and_preview_can_cancel(self) -> None:
        preview = self.prepare_create()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TRIGGER fail_s1_insert BEFORE INSERT ON scalar_versions "
                         "BEGIN SELECT RAISE(ABORT, 'injected'); END")
            conn.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.confirm(preview)
        self.assertEqual(self.service.list_scalars("user1")["memories"], [])
        cancelled = self.service.cancel({"user_id": "user1",
                                         "token": preview["preview"]["token"]})
        self.assertEqual(cancelled["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
