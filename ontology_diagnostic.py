"""Isolated, non-persistent real-provider ontology extraction diagnostic.

This module deliberately depends only on the provider boundary, Registry v1,
the Phase-3B.1 parser/literal resolver, dormant Phase-4A compiler, server-owned
synthetic Architecture B preconditions, dormant Phase-4B Risk Engine, and the
Phase-4D deterministic routing-plan preview.  It has no database, user-memory,
proposal persistence, production routing, or commit dependency.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol

import ontology_ir as ontology
import ontology_compiler
import ontology_preconditions
import risk_engine
import ontology_routing
import slot_registry as registry


DIAGNOSTIC_ENDPOINT = "/api/ontology-diagnostic/extract"
MAX_RAW_OUTPUT_CHARS = 8_000
RESULT_STATES = frozenset(
    ("VALIDATED", "STRUCTURAL_REJECT", "GROUNDING_REJECT", "PROVIDER_ERROR")
)
RESIDUAL_RISK_WARNING = (
    "Exact grounding proves provenance, not semantic correctness. "
    "Wrong-but-exact literals may pass grounding."
)
MODEL_OFFSETS_WARNING = "NON-AUTHORITATIVE MODEL OFFSETS"


class DiagnosticInputError(ValueError):
    """The browser request is not one of the server-owned diagnostic cases."""


class DiagnosticProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], api_key: str) -> str: ...


@dataclass(frozen=True, slots=True)
class ValidatedDiagnosticRun:
    run_id: str
    case_id: str
    question: str
    route_plan: ontology_routing.OntologyRoutePlan


@dataclass(frozen=True, slots=True)
class DiagnosticCase:
    case_id: str
    title: str
    question: str
    expected_semantic_meaning: str
    entity_candidates: tuple[str, ...] = ()
    target_memory_candidates: tuple[str, ...] = ()
    review_persistence_supported: bool = False


_CASE_SEQUENCE = (
    DiagnosticCase(
        "D1",
        "Simple singleton scalar",
        "我的辦公室在台北。",
        "slot_id=user.office.location; claim_shape=SCALAR_ASSERTION; value=台北",
        review_persistence_supported=True,
    ),
    DiagnosticCase(
        "D2",
        "R05 critical boundary case",
        "我的車是白色。",
        "slot_id=vehicle.color; claim_shape=SCALAR_ASSERTION; value span=白色",
        ("vehicle:test-car-001",),
        review_persistence_supported=True,
    ),
    DiagnosticCase(
        "D3",
        "Count / R21 critical case",
        "現在讀書會一共有五位成員。",
        "slot_id=group.member_count; claim_shape=CARDINALITY_ASSERTION; numeric source=五 or 五位; canonical numeric value=5",
        ("group:test-book-club-001",),
        review_persistence_supported=True,
    ),
    DiagnosticCase(
        "D4",
        "Known Set membership",
        "讀書會新增小王。",
        "slot_id=group.members; claim_shape=MEMBERSHIP_ASSERTION; member=小王; membership_action=ADD",
        ("group:test-book-club-001",),
        review_persistence_supported=True,
    ),
    DiagnosticCase(
        "D5",
        "Unknown ontology fact",
        "我最喜歡的電影導演是王家衛。",
        "UNKNOWN_SLOT because Registry v1 has no director-preference slot",
    ),
    DiagnosticCase(
        "D6",
        "Destructive Set REMOVE existing member",
        "讀書會移除小王。",
        "slot_id=group.members; claim_shape=MEMBERSHIP_ASSERTION; member=小王; membership_action=REMOVE; existing member",
        ("group:test-book-club-001",),
        review_persistence_supported=True,
    ),
    DiagnosticCase(
        "D7",
        "Duplicate Set ADD → NOOP",
        "讀書會新增小王。",
        "slot_id=group.members; claim_shape=MEMBERSHIP_ASSERTION; member=小王; membership_action=ADD; deterministic NOOP",
        ("group:test-book-club-001",),
    ),
    DiagnosticCase(
        "D8",
        "Remove absent member → TARGET_NOT_FOUND",
        "讀書會移除小王。",
        "slot_id=group.members; claim_shape=MEMBERSHIP_ASSERTION; member=小王; membership_action=REMOVE; deterministic TARGET_NOT_FOUND",
        ("group:test-book-club-001",),
    ),
)
DIAGNOSTIC_CASES: Mapping[str, DiagnosticCase] = MappingProxyType(
    {item.case_id: item for item in _CASE_SEQUENCE}
)
SYNTHETIC_AUTHORITATIVE_STATE: Mapping[
    str, ontology_preconditions.AuthoritativeTypedState | None
] = MappingProxyType(
    {
        "D1": None,
        "D2": ontology_preconditions.authoritative_state(
            "memory_test_vehicle_color_001", "vehicle.color", 1,
            "vehicle:test-car-001", "scalar", {"value": "黑色"},
        ),
        "D3": ontology_preconditions.authoritative_state(
            "memory_test_group_count_001", "group.member_count", 1,
            "group:test-book-club-001", "count", {"value": 4},
        ),
        "D4": ontology_preconditions.authoritative_state(
            "memory_test_group_members_001", "group.members", 1,
            "group:test-book-club-001", "set", {"items": ["小李"]},
        ),
        "D5": None,
        "D6": ontology_preconditions.authoritative_state(
            "memory_test_group_members_remove_present_001", "group.members", 1,
            "group:test-book-club-001", "set", {"items": ["小李", "小王"]},
        ),
        "D7": ontology_preconditions.authoritative_state(
            "memory_test_group_members_duplicate_add_001", "group.members", 1,
            "group:test-book-club-001", "set", {"items": ["小李", "小王"]},
        ),
        "D8": ontology_preconditions.authoritative_state(
            "memory_test_group_members_remove_absent_001", "group.members", 1,
            "group:test-book-club-001", "set", {"items": ["小李"]},
        ),
    }
)


def diagnostic_catalog() -> list[dict[str, object]]:
    """Return safe display data; candidate IDs remain server-side."""
    return [
        {
            "case_id": item.case_id,
            "title": item.title,
            "question": item.question,
            "expected_semantic_meaning": item.expected_semantic_meaning,
            "review_persistence_supported": item.review_persistence_supported,
        }
        for item in _CASE_SEQUENCE
    ]


def _prompt(case: DiagnosticCase) -> list[dict[str, str]]:
    slot_ids = (*registry.REGISTRY_V1_SLOT_IDS, registry.UNKNOWN_SLOT)
    claim_shapes = sorted(
        {shape for definition in registry.iter_slots() for shape in definition.allowed_claim_shapes}
    )
    slot_contracts = {
        definition.slot_id: {
            "allowed_claim_shapes": sorted(definition.allowed_claim_shapes),
            "entity_scope": definition.entity_scope.value,
        }
        for definition in registry.iter_slots()
    }
    contract = {
        "protocol_version": ontology.PROTOCOL_VERSION,
        "allowed_intents": sorted(ontology.INTENTS),
        "allowed_slot_ids": slot_ids,
        "allowed_claim_shapes": claim_shapes,
        "slot_contracts": slot_contracts,
        "entity_candidates": case.entity_candidates,
        "target_memory_candidates": case.target_memory_candidates,
    }
    system = (
        "You are an isolated constrained semantic extractor. Return exactly one JSON object and no markdown.\n"
        "Select slot_id only from allowed_slot_ids. UNKNOWN_SLOT is explicit and always available.\n"
        "Select entity_id and target_memory_id only from the supplied candidate arrays; never invent IDs.\n"
        "For a known change use intent CHANGE. After selecting slot_id, claim_shape MUST be "
        "exactly one of SERVER_OWNED_CONTRACT_JSON.slot_contracts[slot_id].allowed_claim_shapes. "
        "Do not infer a different shape from surface wording; incompatible slot/shape pairs fail closed.\n"
        "For an unknown ontology fact, either safely clarify with exactly: protocol_version, "
        "intent=CLARIFY, slot_id=UNKNOWN_SLOT, ambiguity=UNKNOWN_SLOT, and a non-empty question; "
        "or safely decline with exactly: protocol_version, intent=ABSTAIN, slot_id=UNKNOWN_SLOT.\n"
        "CHANGE scalar/field JSON fields: protocol_version,intent,slot_id,claim_shape,value, "
        "plus entity_id/target_memory_id only when applicable.\n"
        "CHANGE cardinality fields: protocol_version,intent,slot_id,claim_shape,count, "
        "plus required entity_id. count must also include integer canonical_value.\n"
        "CHANGE enumeration fields: protocol_version,intent,slot_id,claim_shape,items, "
        "plus required entity_id and optional asserted_count.\n"
        "CHANGE membership fields: protocol_version,intent,slot_id,claim_shape,membership_action,item, "
        "plus required entity_id. membership_action is ADD or REMOVE.\n"
        "Each literal operand is exactly {claimed_literal}; a numeric operand also has canonical_value. "
        "Copy each non-empty claimed_literal verbatim from the exact current user message. "
        "Do not calculate or emit source_start or source_end; the application resolves authoritative offsets.\n"
        "Do not emit semantic_key, display_label, typed_family, value_type, risk_class, "
        "auto_commit_allowed, internal operation, revision, history, proposal policy, deterministic reply, "
        "confidence, or explanations. Extra fields fail validation.\n"
        "SERVER_OWNED_CONTRACT_JSON:\n"
        + json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": case.question}]


def _enum_value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _model_selection(value: ontology.ConstrainedOntologyIR) -> dict[str, object]:
    result: dict[str, object] = {
        "protocol_version": value.protocol_version,
        "intent": value.intent,
    }
    for name in (
        "slot_id",
        "claim_shape",
        "entity_id",
        "target_memory_id",
        "membership_action",
        "unknown",
        "ambiguity",
        "question",
        "reply",
    ):
        if hasattr(value, name):
            result[name] = _enum_value(getattr(value, name))
    if isinstance(value, ontology.ConstrainedChangeIR):
        result["operands"] = [
            {
                "role": role,
                "claimed_literal": operand.claimed_literal,
                **(
                    {"canonical_value": operand.canonical_value}
                    if operand.has_canonical_value
                    else {}
                ),
            }
            for role, operand in value.operands
        ]
    return result


def _application_derivation(
    value: ontology.ConstrainedOntologyIR,
) -> dict[str, object] | None:
    metadata = ontology.project_slot_metadata(value)
    if metadata is None:
        return None
    return {
        "slot_id": metadata.slot_id,
        "semantic_key": metadata.semantic_key,
        "display_label": metadata.display_label,
        "typed_family": metadata.typed_family.value,
        "entity_scope": metadata.entity_scope.value,
        "value_type": metadata.value_type.value,
        "registry_version": metadata.registry_version,
        "risk_class": metadata.risk_class.value,
        "auto_commit_allowed": metadata.auto_commit_allowed,
    }


def _resolved_operands(
    operands: tuple[ontology.ResolvedLiteralOperand, ...],
) -> list[dict[str, object]]:
    return [
        {
            "model_selected_role": operand.role,
            "model_selected_claimed_literal": operand.claimed_literal,
            "occurrence_count": operand.occurrence_count,
            "application_source_start": operand.source_start,
            "application_source_end": operand.source_end,
            "application_exact_slice": operand.exact_slice,
            "resolution_status": operand.resolution_status.value,
            "canonical_value": operand.canonical_value if operand.has_canonical_value else None,
            "canonical_value_ownership": (
                "MODEL-SEMANTIC" if operand.has_canonical_value else None
            ),
            "grounding_result": (
                "GROUNDING PASS"
                if operand.resolution_status
                is ontology.LiteralResolutionStatus.RESOLVED_EXACT
                else "GROUNDING FAIL"
            ),
            "semantic_correctness": "NOT PROVEN",
        }
        for operand in operands
    ]


def _grounded_operands(value: ontology.GroundedConstrainedIR) -> list[dict[str, object]]:
    return _resolved_operands(value.operands)


def _safe_raw(raw: object) -> object:
    if isinstance(raw, (dict, list, str, int, float, bool)) or raw is None:
        if isinstance(raw, str) and len(raw) > MAX_RAW_OUTPUT_CHARS:
            return raw[:MAX_RAW_OUTPUT_CHARS] + "…"
        return raw
    return str(raw)[:MAX_RAW_OUTPUT_CHARS]


class OntologyDiagnosticService:
    """One-call, zero-persistence provider/validator orchestration."""

    def __init__(self, provider: DiagnosticProvider):
        self._provider = provider
        self._provider_calls = 0
        self._lock = threading.Lock()
        self._validated_runs: dict[str, ValidatedDiagnosticRun] = {}

    @property
    def provider_calls(self) -> int:
        with self._lock:
            return self._provider_calls

    def catalog(self) -> list[dict[str, object]]:
        return diagnostic_catalog()

    def get_validated_run(self, run_id: object) -> ValidatedDiagnosticRun:
        if not isinstance(run_id, str) or not run_id:
            raise DiagnosticInputError("run_id is required")
        with self._lock:
            result = self._validated_runs.get(run_id)
        if result is None:
            raise DiagnosticInputError("Validated diagnostic run not found")
        return result

    def _remember_validated_run(
        self, case: DiagnosticCase, route_plan: ontology_routing.OntologyRoutePlan
    ) -> str:
        run_id = uuid.uuid4().hex
        record = ValidatedDiagnosticRun(run_id, case.case_id, case.question, route_plan)
        with self._lock:
            self._validated_runs[run_id] = record
            while len(self._validated_runs) > 32:
                oldest = next(iter(self._validated_runs))
                self._validated_runs.pop(oldest, None)
        return run_id

    def run_request(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise DiagnosticInputError("Diagnostic request must be a JSON object")
        if not set(request).issubset({"case_id", "api_key"}):
            raise DiagnosticInputError("Diagnostic request accepts only case_id and api_key")
        return self.run(request.get("case_id"), request.get("api_key"))

    def run(self, case_id: object, api_key: object = None) -> dict[str, object]:
        if not isinstance(case_id, str) or case_id not in DIAGNOSTIC_CASES:
            raise DiagnosticInputError("Unknown diagnostic case_id")
        if api_key is not None and not isinstance(api_key, str):
            raise DiagnosticInputError("api_key must be text")
        key = os.environ.get("DEEPSEEK_API_KEY") or (api_key or "").strip()
        if not key:
            raise DiagnosticInputError("Provide DEEPSEEK_API_KEY or API key fallback")

        case = DIAGNOSTIC_CASES[case_id]
        with self._lock:
            self._provider_calls += 1
            cumulative_calls = self._provider_calls
        base = {
            "case_id": case.case_id,
            "question": case.question,
            "expected_semantic_meaning": case.expected_semantic_meaning,
            "provider_calls_this_run": 1,
            "cumulative_provider_calls": cumulative_calls,
            "residual_semantic_risk": RESIDUAL_RISK_WARNING,
            "model_offsets_authority": MODEL_OFFSETS_WARNING,
            "compiler_preview": None,
            "precondition_preview": None,
            "risk_preview": None,
            "routing_preview": None,
            "human_review_payload_preview": None,
            "run_id": None,
            "zero_persistence": {
                "current_changed": "NO",
                "history_changed": "NO",
                "revision_changed": "NO",
                "proposal_created": "NO",
            },
        }
        try:
            raw_text = self._provider.complete(_prompt(case), key)
        except Exception as exc:
            return {
                **base,
                "state": "PROVIDER_ERROR",
                "diagnostic": f"Provider call failed ({type(exc).__name__})",
                "raw_model_result": None,
                "model_selection": None,
                "application_derivation": None,
                "grounded_operands": [],
                "grounding_status": "NOT RUN",
            }

        try:
            raw_value = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            return {
                **base,
                "state": "STRUCTURAL_REJECT",
                "diagnostic": "INVALID_JSON",
                "raw_model_result": _safe_raw(raw_text),
                "model_selection": None,
                "application_derivation": None,
                "grounded_operands": [],
                "grounding_status": "NOT RUN",
            }

        try:
            parsed = ontology.parse_constrained_ir(
                raw_value,
                entity_candidates=case.entity_candidates,
                target_memory_candidates=case.target_memory_candidates,
            )
        except ontology.OntologyIRError as exc:
            return {
                **base,
                "state": "STRUCTURAL_REJECT",
                "diagnostic": exc.reason_code,
                "raw_model_result": _safe_raw(raw_value),
                "model_selection": None,
                "application_derivation": None,
                "grounded_operands": [],
                "grounding_status": "NOT RUN",
            }

        try:
            grounded = ontology.validate_grounding(parsed, case.question)
        except ontology.OntologyIRError as exc:
            return {
                **base,
                "state": "GROUNDING_REJECT",
                "diagnostic": exc.reason_code,
                "raw_model_result": _safe_raw(raw_value),
                "model_selection": _model_selection(parsed),
                "application_derivation": _application_derivation(parsed),
                "grounded_operands": _resolved_operands(exc.resolutions),
                "grounding_status": "GROUNDING REJECT",
            }

        try:
            compiled = ontology_compiler.compile_ontology_action(grounded)
        except ontology_compiler.OntologyCompilerError as exc:
            return {
                **base,
                "state": "STRUCTURAL_REJECT",
                "diagnostic": f"COMPILER_{exc.reason_code}",
                "raw_model_result": _safe_raw(raw_value),
                "model_selection": _model_selection(parsed),
                "application_derivation": _application_derivation(parsed),
                "grounded_operands": _grounded_operands(grounded),
                "grounding_status": "GROUNDING PASS",
            }

        precondition = ontology_preconditions.resolve_authoritative_precondition(
            compiled, SYNTHETIC_AUTHORITATIVE_STATE[case.case_id]
        )
        risk = risk_engine.evaluate_risk(
            compiled, ontology_preconditions.risk_facts(precondition)
        )
        route_plan = ontology_routing.plan_route(compiled, precondition, risk)
        run_id = self._remember_validated_run(case, route_plan)
        return {
            **base,
            "run_id": run_id,
            "state": "VALIDATED",
            "diagnostic": "VALIDATED",
            "raw_model_result": _safe_raw(raw_value),
            "model_selection": _model_selection(parsed),
            "application_derivation": _application_derivation(parsed),
            "grounded_operands": _grounded_operands(grounded),
            "grounding_status": "GROUNDING PASS",
            "compiler_preview": ontology_compiler.compiler_preview(compiled),
            "precondition_preview": ontology_preconditions.precondition_preview(
                precondition
            ),
            "risk_preview": risk_engine.risk_preview(risk),
            "routing_preview": ontology_routing.routing_preview(route_plan),
            "human_review_payload_preview": ontology_routing.human_review_payload_preview(
                route_plan.human_review_payload
            ),
        }
