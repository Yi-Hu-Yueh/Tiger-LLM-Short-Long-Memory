"""Offline structural gates for the dry-run scalar semantic adapter."""

from __future__ import annotations

import json
import unittest

from memory_v2_semantic.semantic_adapter import ScalarSemanticAdapter
from memory_v2_semantic.semantic_models import Intent, ReasonCode, ScalarCandidate, TemporalRelation
from memory_v2_semantic.semantic_validator import PlanValidationError, validate_plan
from v2_1a_cases import DEVELOPMENT_DOMAINS, HOLDOUT_DOMAINS, development_cases, holdout_cases


def _raw(**changes: object) -> str:
    data = {
        "intent": "UPDATE_SCALAR", "target_memory_id": "offered-1",
        "claimed_literal": "青銅", "temporal_relation": "NONE",
        "ambiguity": "NONE", "reason_code": "NONE",
    }
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


class StubProvider:
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return self.raw


class SemanticAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = (ScalarCandidate("offered-1", "entity-1", "東區鐘塔",
                                        "synthetic.clock.finish", "外殼材質", "石材"),)

    def test_exact_grounding_and_catalog_derived_metadata(self) -> None:
        plan = validate_plan(_raw(), "東區鐘塔的外殼材質換成青銅。", self.catalog)
        self.assertEqual(plan.intent, Intent.UPDATE_SCALAR)
        self.assertEqual(plan.target_entity_id, "entity-1")
        self.assertEqual(plan.semantic_key, "synthetic.clock.finish")
        self.assertEqual(plan.value_candidate, "青銅")
        self.assertEqual((plan.source_start, plan.source_end), (11, 13))
        self.assertEqual(plan.mutation_count, 0)

    def test_provider_adapter_stays_dry_run(self) -> None:
        provider = StubProvider(_raw())
        plan = ScalarSemanticAdapter(provider).propose(
            "東區鐘塔的外殼材質換成青銅。", self.catalog)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(plan.mutation_count, 0)

    def test_unoffered_id_rejected(self) -> None:
        with self.assertRaisesRegex(PlanValidationError, "TARGET_NOT_OFFERED"):
            validate_plan(_raw(target_memory_id="invented"), "材質是青銅", self.catalog)

    def test_extra_field_and_malformed_json_rejected(self) -> None:
        for raw in (_raw(sql="DELETE"), "{not json"):
            with self.assertRaises(PlanValidationError):
                validate_plan(raw, "材質是青銅", self.catalog)

    def test_grounding_missing_or_repeated_fails_closed(self) -> None:
        for message in ("材質是銀色", "青銅和青銅"):
            with self.assertRaises(PlanValidationError):
                validate_plan(_raw(), message, self.catalog)

    def test_previous_requires_exact_temporal_class(self) -> None:
        with self.assertRaisesRegex(PlanValidationError, "TEMPORAL_MISMATCH"):
            validate_plan(_raw(intent="READ_PREVIOUS", claimed_literal=None,
                               temporal_relation="CURRENT"), "之前是什麼？", self.catalog)
        plan = validate_plan(_raw(intent="READ_PREVIOUS", claimed_literal=None,
                                  temporal_relation="PREVIOUS"), "之前是什麼？", self.catalog)
        self.assertEqual(plan.temporal_relation, TemporalRelation.PREVIOUS)
        self.assertEqual(plan.mutation_count, 0)

    def test_ambiguous_and_unknown_controls(self) -> None:
        for intent, ambiguity, reason in (
            ("AMBIGUOUS_TARGET", "MULTIPLE", "MULTIPLE_TARGETS"),
            ("UNKNOWN_TARGET", "UNKNOWN", "TARGET_NOT_FOUND"),
        ):
            plan = validate_plan(_raw(intent=intent, target_memory_id=None,
                                      claimed_literal=None, ambiguity=ambiguity,
                                      reason_code=reason), "哪一個？", self.catalog)
            self.assertIsNone(plan.target_memory_id)
            self.assertEqual(plan.mutation_count, 0)

    def test_new_unapproved_slot_is_not_canonical_create(self) -> None:
        with self.assertRaisesRegex(PlanValidationError, "GOVERNANCE_REQUIRED"):
            validate_plan(_raw(intent="CREATE_SCALAR", target_memory_id=None),
                          "材質是青銅", ())
        plan = validate_plan(_raw(intent="UNSUPPORTED", target_memory_id=None,
                                  reason_code="GOVERNANCE_REQUIRED"), "材質是青銅", ())
        self.assertEqual(plan.reason_code, ReasonCode.GOVERNANCE_REQUIRED)

    def test_development_and_holdout_fixtures_are_distinct(self) -> None:
        development = development_cases()
        holdout = holdout_cases()
        self.assertEqual(len(DEVELOPMENT_DOMAINS), 30)
        self.assertGreaterEqual(len(development), 180)
        self.assertGreaterEqual(len(holdout), 20)
        self.assertEqual({c.case_id for c in development} & {c.case_id for c in holdout}, set())
        self.assertEqual({d[0] for d in DEVELOPMENT_DOMAINS} &
                         {d[0] for d in HOLDOUT_DOMAINS}, set())
        self.assertTrue(all(c.intent in Intent for c in development + holdout))


if __name__ == "__main__":
    unittest.main()
