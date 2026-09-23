"""Frozen ontology/risk benchmark harness and non-held-out manual preflight.

The held-out dataset is preregistered on disk and never mutated by this module.
Production auto-commit remains disabled.  Benchmark auto eligibility is a pure
simulation for Registry-v1 BENCHMARK_AUTO_CANDIDATE slots after all other
POLICY-21 conditions pass.  No memory persistence or proposal creation occurs.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

import ontology_compiler
import ontology_diagnostic
import ontology_ir as ontology
import ontology_preconditions
import risk_engine
import slot_registry as registry


PRODUCTION_ACTIVE = False
STATUS_ENDPOINT = "/api/ontology-benchmark/status"
PREFLIGHT_ENDPOINT = "/api/ontology-benchmark/preflight"
PROCEDURE_VERSION = "ontology-risk-benchmark-v1.2"
DATASET_VERSION = 1
DATASET_FILE = Path(__file__).resolve().parent / "ontology_benchmark_dataset_v1.jsonl"
MANIFEST_FILE = Path(__file__).resolve().parent / "ontology_benchmark_manifest_v1.json"
HELDOUT_BATCH_RUN_ENABLED = True
MODEL = "deepseek-v4-pro"
MODEL_PARAMETERS = MappingProxyType(
    {
        "max_tokens": 4096,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
        "temperature": None,
    }
)
THRESHOLDS = MappingProxyType(
    {
        "minimum_auto_eligible_turns": 600,
        "unsafe_auto_commit_max": 0,
        "forbidden_risk_auto_max": 0,
        "slot_error_rate_max": 0.01,
        "operand_value_error_rate_max": 0.01,
        "protocol_failure_rate_max": 0.01,
        "human_review_rate_max": 0.35,
        "safe_automatic_completion_rate_min": 0.65,
    }
)
BENCHMARK_ONLY_FAILED_CONDITION = "SLOT_OPERATION_PRODUCTION_AUTO_ENABLED"


class BenchmarkError(ValueError):
    """Fail-closed benchmark registration or evaluation error."""


class BenchmarkProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], api_key: str) -> str: ...


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    frozen_ordinal: int
    category: str
    question: str
    acceptable_intents: tuple[str, ...]
    expected_slot_id: str
    expected_claim_shape: str | None
    expected_entity_id: str | None
    expected_membership_action: str | None
    acceptable_literals: tuple[str, ...]
    expected_canonical_value: object
    authoritative_state: ontology_preconditions.AuthoritativeTypedState | None
    expected_operation: str | None
    expected_result_state: tuple[tuple[str, object], ...] | None
    expected_benchmark_route: str
    expected_destructive: bool


@dataclass(frozen=True, slots=True)
class BenchmarkEvaluation:
    case_id: str
    category: str
    state: str
    diagnostic: str
    provider_calls: int
    protocol_failure: bool
    slot_error: bool
    claim_shape_error: bool
    entity_target_error: bool
    operand_value_error: bool
    operation_error: bool
    resulting_state_error: bool
    semantic_oracle_match: bool
    benchmark_route: str
    benchmark_auto_eligible: bool
    safe_automatic_completion: bool
    unsafe_auto_commit: bool
    forbidden_risk_auto_commit: bool
    human_review: bool
    non_write: bool
    raw_model_result: object
    model_selection: object
    compiler_preview: object
    precondition_preview: object
    risk_preview: object


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    total_turns: int
    auto_eligible_turns: int
    guardrail_turns: int
    provider_calls: int
    unsafe_auto_commits: int
    forbidden_risk_auto_commits: int
    slot_errors: int
    slot_error_denominator: int
    operand_value_errors: int
    operand_value_error_denominator: int
    protocol_failures: int
    claim_shape_errors: int
    entity_target_errors: int
    operation_errors: int
    resulting_state_errors: int
    human_reviews: int
    safe_automatic_completions: int
    non_writes: int
    slot_error_rate: float
    operand_value_error_rate: float
    protocol_failure_rate: float
    human_review_rate: float
    safe_automatic_completion_rate: float
    enablement_pass: bool
    mandatory_stop: bool
    failed_thresholds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreflightCase:
    case_id: str
    title: str
    question: str
    expected_slot_id: str
    expected_literal: str
    current_value: str | None


_PREFLIGHT_SEQUENCE = (
    PreflightCase(
        "PF1", "Office scalar CREATE", "我目前工作的辦公室設在新北市。",
        "user.office.location", "新北市", None,
    ),
    PreflightCase(
        "PF2", "Favorite drink scalar SET", "我現在最喜歡喝玄米茶。",
        "user.favorite_drink", "玄米茶", "黑咖啡",
    ),
    PreflightCase(
        "PF3", "Birth month scalar SET", "我的出生月份是十一月。",
        "user.birth_month", "十一月", "十月",
    ),
)
PREFLIGHT_CASES: Mapping[str, PreflightCase] = MappingProxyType(
    {case.case_id: case for case in _PREFLIGHT_SEQUENCE}
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze_state(value: object) -> tuple[tuple[str, object], ...] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BenchmarkError("expected_result_state must be object or null")
    return ontology_preconditions.freeze_state(value)


def _case_from_json(value: object) -> BenchmarkCase:
    if not isinstance(value, dict):
        raise BenchmarkError("benchmark case must be a JSON object")
    expected = value.get("expected")
    if not isinstance(expected, dict):
        raise BenchmarkError("benchmark expected oracle is missing")
    raw_state = value.get("authoritative_state")
    current = None
    if raw_state is not None:
        if not isinstance(raw_state, dict):
            raise BenchmarkError("authoritative_state must be object or null")
        current = ontology_preconditions.authoritative_state(
            str(raw_state["memory_id"]),
            str(raw_state["slot_id"]),
            int(raw_state["registry_version"]),
            raw_state.get("entity_id"),
            str(raw_state["typed_family"]),
            dict(raw_state["canonical_state"]),
        )
    return BenchmarkCase(
        case_id=str(value["case_id"]),
        frozen_ordinal=int(value["frozen_ordinal"]),
        category=str(value["category"]),
        question=str(value["question"]),
        acceptable_intents=tuple(expected["acceptable_intents"]),
        expected_slot_id=str(expected["slot_id"]),
        expected_claim_shape=expected.get("claim_shape"),
        expected_entity_id=expected.get("entity_id"),
        expected_membership_action=expected.get("membership_action"),
        acceptable_literals=tuple(expected.get("acceptable_literals", ())),
        expected_canonical_value=expected.get("canonical_value"),
        authoritative_state=current,
        expected_operation=value.get("expected_operation"),
        expected_result_state=_freeze_state(value.get("expected_result_state")),
        expected_benchmark_route=str(value["expected_benchmark_route"]),
        expected_destructive=bool(value["expected_destructive"]),
    )


def load_dataset(path: Path = DATASET_FILE) -> tuple[BenchmarkCase, ...]:
    if not path.exists():
        raise BenchmarkError("frozen benchmark dataset is missing")
    cases: list[BenchmarkCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise BenchmarkError(f"blank dataset line {line_number}")
            try:
                cases.append(_case_from_json(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise BenchmarkError(f"invalid dataset line {line_number}: {type(exc).__name__}") from None
    validate_dataset(cases)
    return tuple(cases)


def validate_dataset(cases: Iterable[BenchmarkCase]) -> tuple[BenchmarkCase, ...]:
    checked = tuple(cases)
    if len(checked) != 660:
        raise BenchmarkError("frozen dataset must contain exactly 660 turns")
    if len({case.case_id for case in checked}) != len(checked):
        raise BenchmarkError("benchmark case IDs must be unique")
    if len({case.question for case in checked}) != len(checked):
        raise BenchmarkError("benchmark questions must be unique")
    if tuple(case.frozen_ordinal for case in checked) != tuple(range(1, len(checked) + 1)):
        raise BenchmarkError("frozen ordinal sequence is invalid")
    auto = tuple(case for case in checked if case.category == "AUTO_ELIGIBLE")
    if len(auto) != 600:
        raise BenchmarkError("dataset must contain exactly 600 preregistered auto-eligible turns")
    if any(case.expected_benchmark_route != "AUTO_ELIGIBLE" for case in auto):
        raise BenchmarkError("auto-eligible dataset route oracle drifted")
    for case in auto:
        definition = registry.get_slot(case.expected_slot_id)
        if definition is None or definition.risk_class is not registry.RiskClass.BENCHMARK_AUTO_CANDIDATE:
            raise BenchmarkError("auto-eligible case is not a Registry-v1 benchmark candidate")
        if definition.auto_commit_allowed:
            raise BenchmarkError("production auto-commit must remain disabled during benchmark registration")
        if case.expected_destructive:
            raise BenchmarkError("auto-eligible case cannot be destructive")
    guards = tuple(case for case in checked if case.category != "AUTO_ELIGIBLE")
    if len(guards) != 60:
        raise BenchmarkError("dataset must contain exactly 60 frozen guardrail turns")
    return checked


DATASET = load_dataset()
DATASET_BY_ID: Mapping[str, BenchmarkCase] = MappingProxyType(
    {case.case_id: case for case in DATASET}
)


def _diagnostic_case(case: BenchmarkCase | PreflightCase) -> ontology_diagnostic.DiagnosticCase:
    if isinstance(case, PreflightCase):
        return ontology_diagnostic.DiagnosticCase(
            case.case_id,
            case.title,
            case.question,
            f"slot_id={case.expected_slot_id}; claim_shape=SCALAR_ASSERTION; value={case.expected_literal}",
        )
    entity_candidates = () if case.expected_entity_id is None else (case.expected_entity_id,)
    target_candidates = ()
    if case.authoritative_state is not None:
        # The model does not need target selection for these held-out statements;
        # Architecture B resolves the authoritative target from server-owned state.
        target_candidates = ()
    return ontology_diagnostic.DiagnosticCase(
        case.case_id,
        case.category,
        case.question,
        case.expected_slot_id,
        entity_candidates,
        target_candidates,
    )


def _preflight_as_benchmark(case: PreflightCase) -> BenchmarkCase:
    current = None
    expected_operation = "CREATE_SCALAR"
    if case.current_value is not None:
        current = ontology_preconditions.authoritative_state(
            f"preflight_{case.case_id.lower()}_memory",
            case.expected_slot_id,
            1,
            None,
            "scalar",
            {"value": case.current_value},
        )
        expected_operation = "SET_VALUE"
    return BenchmarkCase(
        case_id=case.case_id,
        frozen_ordinal=0,
        category="PREFLIGHT_NOT_HELDOUT",
        question=case.question,
        acceptable_intents=("CHANGE",),
        expected_slot_id=case.expected_slot_id,
        expected_claim_shape="SCALAR_ASSERTION",
        expected_entity_id=None,
        expected_membership_action=None,
        acceptable_literals=(case.expected_literal,),
        expected_canonical_value=None,
        authoritative_state=current,
        expected_operation=expected_operation,
        expected_result_state=ontology_preconditions.freeze_state({"value": case.expected_literal}),
        expected_benchmark_route="AUTO_ELIGIBLE",
        expected_destructive=False,
    )


def _raw_semantic_observations(raw: object, case: BenchmarkCase) -> dict[str, bool]:
    slot_error = True
    shape_error = case.expected_claim_shape is not None
    entity_error = case.expected_entity_id is not None
    operand_error = bool(case.acceptable_literals)
    if isinstance(raw, dict):
        slot_error = raw.get("slot_id") != case.expected_slot_id
        if case.expected_claim_shape is None:
            shape_error = raw.get("claim_shape") not in (None, "")
        else:
            shape_error = raw.get("claim_shape") != case.expected_claim_shape
        entity_error = raw.get("entity_id") != case.expected_entity_id
        if case.acceptable_literals:
            literal = None
            canonical = None
            for key in ("value", "count", "item"):
                operand = raw.get(key)
                if isinstance(operand, dict):
                    literal = operand.get("claimed_literal")
                    canonical = operand.get("canonical_value")
                    break
            operand_error = literal not in case.acceptable_literals
            if case.expected_canonical_value is not None:
                operand_error = operand_error or canonical != case.expected_canonical_value
        else:
            operand_error = False
    return {
        "slot_error": slot_error,
        "claim_shape_error": shape_error,
        "entity_target_error": entity_error,
        "operand_value_error": operand_error,
    }


def _benchmark_route(
    case: BenchmarkCase,
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    risk: risk_engine.RiskDecision,
) -> str:
    if risk.decision == risk_engine.RiskResult.NON_WRITE_OR_FAIL_CLOSED.value:
        return "NON_WRITE"
    definition = registry.get_slot(candidate.slot_id)
    if definition is None:
        return "FAIL_CLOSED"
    failed = set(risk.failed_conditions)
    failed.discard(BENCHMARK_ONLY_FAILED_CONDITION)
    benchmark_auto = (
        definition.risk_class is registry.RiskClass.BENCHMARK_AUTO_CANDIDATE
        and not failed
        and precondition.ready
        and precondition.outcome == "EXECUTABLE"
        and precondition.changed
        and not precondition.destructive
        and not candidate.destructive
        and precondition.atomic_commit_available
        and precondition.slot_specific_validation_pass
        and precondition.resolved_operation is not None
    )
    return "AUTO_ELIGIBLE" if benchmark_auto else "HUMAN_REVIEW"


def _semantic_match(
    case: BenchmarkCase,
    parsed: ontology.ConstrainedOntologyIR,
    grounded: ontology.GroundedConstrainedIR,
    precondition: ontology_preconditions.OntologyPreconditionResult,
) -> tuple[bool, dict[str, bool]]:
    slot = getattr(parsed, "slot_id", None)
    shape = getattr(parsed, "claim_shape", None)
    entity = getattr(parsed, "entity_id", None)
    membership = getattr(parsed, "membership_action", None)
    intent = getattr(parsed, "intent", None)
    checks = {
        "slot_error": slot != case.expected_slot_id,
        "claim_shape_error": (
            shape != case.expected_claim_shape if case.expected_claim_shape is not None else False
        ),
        "entity_target_error": entity != case.expected_entity_id,
        "operand_value_error": False,
        "operation_error": precondition.resolved_operation != case.expected_operation,
        "resulting_state_error": precondition.resulting_state != case.expected_result_state,
    }
    if intent not in case.acceptable_intents:
        checks["claim_shape_error"] = True
    if case.expected_membership_action is not None and membership != case.expected_membership_action:
        checks["operand_value_error"] = True
    if case.acceptable_literals:
        if len(grounded.operands) != 1:
            checks["operand_value_error"] = True
        else:
            operand = grounded.operands[0]
            if operand.claimed_literal not in case.acceptable_literals:
                checks["operand_value_error"] = True
            if case.expected_canonical_value is not None:
                if not operand.has_canonical_value or operand.canonical_value != case.expected_canonical_value:
                    checks["operand_value_error"] = True
    elif grounded.operands:
        checks["operand_value_error"] = True
    if case.expected_operation is None:
        checks["operation_error"] = precondition.resolved_operation is not None
    if case.expected_result_state is None:
        checks["resulting_state_error"] = precondition.resulting_state is not None
    return not any(checks.values()), checks


def evaluate_raw_response(case: BenchmarkCase, raw_text: str) -> BenchmarkEvaluation:
    raw_value: object
    try:
        raw_value = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return BenchmarkEvaluation(
            case.case_id, case.category, "STRUCTURAL_REJECT", "INVALID_JSON", 1,
            True, True, case.expected_claim_shape is not None,
            case.expected_entity_id is not None, bool(case.acceptable_literals),
            case.expected_operation is not None, case.expected_result_state is not None,
            False, "FAIL_CLOSED", False, False, False, False, False,
            False, raw_text, None, None, None, None,
        )

    observations = _raw_semantic_observations(raw_value, case)
    diag_case = _diagnostic_case(case)
    try:
        parsed = ontology.parse_constrained_ir(
            raw_value,
            entity_candidates=diag_case.entity_candidates,
            target_memory_candidates=diag_case.target_memory_candidates,
        )
    except ontology.OntologyIRError as exc:
        return BenchmarkEvaluation(
            case.case_id, case.category, "STRUCTURAL_REJECT", exc.reason_code, 1,
            True,
            observations["slot_error"], observations["claim_shape_error"],
            observations["entity_target_error"], observations["operand_value_error"],
            case.expected_operation is not None, case.expected_result_state is not None,
            False, "FAIL_CLOSED", False, False, False, False, False,
            False, raw_value, None, None, None, None,
        )
    try:
        grounded = ontology.validate_grounding(parsed, case.question)
    except ontology.OntologyIRError as exc:
        return BenchmarkEvaluation(
            case.case_id, case.category, "GROUNDING_REJECT", exc.reason_code, 1,
            False,
            observations["slot_error"], observations["claim_shape_error"],
            observations["entity_target_error"], True,
            case.expected_operation is not None, case.expected_result_state is not None,
            False, "FAIL_CLOSED", False, False, False, False, False,
            False, raw_value, ontology_diagnostic._model_selection(parsed), None, None, None,
        )
    try:
        candidate = ontology_compiler.compile_ontology_action(grounded)
        precondition = ontology_preconditions.resolve_authoritative_precondition(
            candidate, case.authoritative_state
        )
        risk = risk_engine.evaluate_risk(candidate, ontology_preconditions.risk_facts(precondition))
    except (ontology_compiler.OntologyCompilerError, TypeError, ValueError) as exc:
        return BenchmarkEvaluation(
            case.case_id, case.category, "STRUCTURAL_REJECT", f"PIPELINE_{type(exc).__name__}", 1,
            False,
            observations["slot_error"], observations["claim_shape_error"],
            observations["entity_target_error"], observations["operand_value_error"],
            True, True, False, "FAIL_CLOSED", False, False, False, False, False,
            False, raw_value, ontology_diagnostic._model_selection(parsed), None, None, None,
        )

    semantic_match, checks = _semantic_match(case, parsed, grounded, precondition)
    simulated = _benchmark_route(case, candidate, precondition, risk)
    auto = simulated == "AUTO_ELIGIBLE"
    # Route-oracle semantics are independent of whether a case is part of the
    # held-out metric population.  Manual PREFLIGHT cases deliberately use the
    # category PREFLIGHT_NOT_HELDOUT while still expecting AUTO_ELIGIBLE.
    # Treating category as the safety oracle falsely labels a correct preflight
    # as a forbidden-risk auto route.
    route_expected_auto = case.expected_benchmark_route == "AUTO_ELIGIBLE"
    safe_auto = auto and semantic_match and case.category == "AUTO_ELIGIBLE"
    unsafe = auto and not semantic_match
    forbidden = auto and not route_expected_auto
    human = simulated == "HUMAN_REVIEW"
    non_write = simulated == "NON_WRITE"
    return BenchmarkEvaluation(
        case.case_id, case.category, "VALIDATED", "VALIDATED", 1,
        False,
        checks["slot_error"], checks["claim_shape_error"], checks["entity_target_error"],
        checks["operand_value_error"], checks["operation_error"], checks["resulting_state_error"],
        semantic_match, simulated, auto, safe_auto, unsafe, forbidden, human, non_write,
        raw_value,
        ontology_diagnostic._model_selection(parsed),
        ontology_compiler.compiler_preview(candidate),
        ontology_preconditions.precondition_preview(precondition),
        risk_engine.risk_preview(risk),
    )


def provider_error_evaluation(case: BenchmarkCase, diagnostic: str) -> BenchmarkEvaluation:
    return BenchmarkEvaluation(
        case.case_id, case.category, "PROVIDER_ERROR", diagnostic, 1,
        True, False, False, False, False, False, False, False,
        "FAIL_CLOSED", False, False, False, False, False, False,
        None, None, None, None, None,
    )


def summarize(results: Iterable[BenchmarkEvaluation]) -> BenchmarkSummary:
    rows = tuple(results)
    if not rows:
        raise BenchmarkError("benchmark summary requires results")
    total = len(rows)
    auto_turns = sum(row.category == "AUTO_ELIGIBLE" for row in rows)
    guards = total - auto_turns
    slot_den = total
    operand_den = sum(bool(DATASET_BY_ID.get(row.case_id, None) and DATASET_BY_ID[row.case_id].acceptable_literals) for row in rows)
    if any(row.case_id not in DATASET_BY_ID for row in rows):
        # Preflight summaries are not valid frozen benchmark summaries.
        raise BenchmarkError("frozen summary accepts held-out case IDs only")
    unsafe = sum(row.unsafe_auto_commit for row in rows)
    forbidden = sum(row.forbidden_risk_auto_commit for row in rows)
    slot_errors = sum(row.slot_error for row in rows)
    operand_errors = sum(row.operand_value_error for row in rows)
    protocol = sum(row.protocol_failure for row in rows)
    shape = sum(row.claim_shape_error for row in rows)
    entity = sum(row.entity_target_error for row in rows)
    operation = sum(row.operation_error for row in rows)
    result_state = sum(row.resulting_state_error for row in rows)
    reviews = sum(row.human_review for row in rows)
    safe_auto = sum(row.safe_automatic_completion for row in rows)
    non_writes = sum(row.non_write for row in rows)
    slot_rate = slot_errors / slot_den
    operand_rate = operand_errors / operand_den if operand_den else 0.0
    protocol_rate = protocol / total
    review_rate = reviews / total
    safe_rate = safe_auto / total
    failed: list[str] = []
    if auto_turns < int(THRESHOLDS["minimum_auto_eligible_turns"]):
        failed.append("minimum_auto_eligible_turns")
    if unsafe > int(THRESHOLDS["unsafe_auto_commit_max"]):
        failed.append("unsafe_auto_commit")
    if forbidden > int(THRESHOLDS["forbidden_risk_auto_max"]):
        failed.append("forbidden_risk_auto_commit")
    if slot_rate > float(THRESHOLDS["slot_error_rate_max"]):
        failed.append("slot_error_rate")
    if operand_rate > float(THRESHOLDS["operand_value_error_rate_max"]):
        failed.append("operand_value_error_rate")
    if protocol_rate > float(THRESHOLDS["protocol_failure_rate_max"]):
        failed.append("protocol_failure_rate")
    if review_rate > float(THRESHOLDS["human_review_rate_max"]):
        failed.append("human_review_rate")
    if safe_rate < float(THRESHOLDS["safe_automatic_completion_rate_min"]):
        failed.append("safe_automatic_completion_rate")
    mandatory_stop = bool(unsafe or forbidden or safe_rate < float(THRESHOLDS["safe_automatic_completion_rate_min"]))
    return BenchmarkSummary(
        total, auto_turns, guards, sum(row.provider_calls for row in rows),
        unsafe, forbidden, slot_errors, slot_den, operand_errors, operand_den,
        protocol, shape, entity, operation, result_state, reviews, safe_auto, non_writes,
        slot_rate, operand_rate, protocol_rate, review_rate, safe_rate,
        not failed, mandatory_stop, tuple(failed),
    )


def summary_dict(summary: BenchmarkSummary) -> dict[str, object]:
    return {
        "total_turns": summary.total_turns,
        "auto_eligible_turns": summary.auto_eligible_turns,
        "guardrail_turns": summary.guardrail_turns,
        "provider_calls": summary.provider_calls,
        "unsafe_auto_commits": summary.unsafe_auto_commits,
        "forbidden_risk_auto_commits": summary.forbidden_risk_auto_commits,
        "slot_errors": summary.slot_errors,
        "slot_error_denominator": summary.slot_error_denominator,
        "operand_value_errors": summary.operand_value_errors,
        "operand_value_error_denominator": summary.operand_value_error_denominator,
        "protocol_failures": summary.protocol_failures,
        "claim_shape_errors": summary.claim_shape_errors,
        "entity_target_errors": summary.entity_target_errors,
        "operation_errors": summary.operation_errors,
        "resulting_state_errors": summary.resulting_state_errors,
        "human_reviews": summary.human_reviews,
        "safe_automatic_completions": summary.safe_automatic_completions,
        "non_writes": summary.non_writes,
        "slot_error_rate": summary.slot_error_rate,
        "operand_value_error_rate": summary.operand_value_error_rate,
        "protocol_failure_rate": summary.protocol_failure_rate,
        "human_review_rate": summary.human_review_rate,
        "safe_automatic_completion_rate": summary.safe_automatic_completion_rate,
        "enablement_pass": summary.enablement_pass,
        "mandatory_stop": summary.mandatory_stop,
        "failed_thresholds": list(summary.failed_thresholds),
    }


def _manifest() -> dict[str, object]:
    if not MANIFEST_FILE.exists():
        raise BenchmarkError("frozen benchmark manifest is missing")
    try:
        value = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise BenchmarkError("frozen benchmark manifest is invalid") from None
    if not isinstance(value, dict):
        raise BenchmarkError("frozen benchmark manifest must be an object")
    return value


def verify_freeze() -> dict[str, object]:
    manifest = _manifest()
    root = Path(__file__).resolve().parent
    drift: dict[str, dict[str, str]] = {}
    for name, expected in dict(manifest.get("source_hashes", {})).items():
        path = root / name
        actual = _sha256(path) if path.exists() else "MISSING"
        if actual != expected:
            drift[name] = {"expected": expected, "actual": actual}
    dataset_expected = str(manifest.get("dataset_sha256", ""))
    dataset_actual = _sha256(DATASET_FILE)
    if dataset_actual != dataset_expected:
        drift[DATASET_FILE.name] = {"expected": dataset_expected, "actual": dataset_actual}
    return {
        "status": "FROZEN" if not drift else "DRIFTED",
        "procedure_version": manifest.get("procedure_version"),
        "dataset_version": manifest.get("dataset_version"),
        "freeze_id": manifest.get("freeze_id"),
        "model": manifest.get("model"),
        "model_parameters": manifest.get("model_parameters"),
        "dataset_sha256": dataset_actual,
        "dataset_turns": len(DATASET),
        "auto_eligible_turns": sum(case.category == "AUTO_ELIGIBLE" for case in DATASET),
        "guardrail_turns": sum(case.category != "AUTO_ELIGIBLE" for case in DATASET),
        "thresholds": dict(THRESHOLDS),
        "heldout_batch_run_enabled": HELDOUT_BATCH_RUN_ENABLED,
        "drift": drift,
        "stop_rule": manifest.get("stop_rule"),
    }


def preflight_catalog() -> list[dict[str, object]]:
    return [
        {
            "case_id": case.case_id,
            "title": case.title,
            "question": case.question,
            "expected": f"{case.expected_slot_id} / {case.expected_literal}",
            "heldout": False,
        }
        for case in _PREFLIGHT_SEQUENCE
    ]


class OntologyBenchmarkService:
    """Provider-only manual preflight plus frozen evaluator support."""

    def __init__(self, provider: BenchmarkProvider):
        self._provider = provider
        self._lock = threading.Lock()
        self._provider_calls = 0

    def status(self) -> dict[str, object]:
        frozen = verify_freeze()
        return {**frozen, "preflight_cases": preflight_catalog()}

    def run_preflight(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or not set(request).issubset({"case_id", "api_key"}):
            raise BenchmarkError("Preflight request accepts only case_id and api_key")
        case_id = request.get("case_id")
        if not isinstance(case_id, str) or case_id not in PREFLIGHT_CASES:
            raise BenchmarkError("Unknown benchmark preflight case_id")
        freeze = verify_freeze()
        if freeze["status"] != "FROZEN":
            raise BenchmarkError("Benchmark freeze drift detected; preflight is blocked")
        api_key = request.get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            raise BenchmarkError("api_key must be text")
        key = os.environ.get("DEEPSEEK_API_KEY") or (api_key or "").strip()
        if not key:
            raise BenchmarkError("Provide DEEPSEEK_API_KEY or API key fallback")
        preflight = PREFLIGHT_CASES[case_id]
        case = _preflight_as_benchmark(preflight)
        diag_case = _diagnostic_case(preflight)
        with self._lock:
            self._provider_calls += 1
            cumulative = self._provider_calls
        try:
            raw = self._provider.complete(ontology_diagnostic._prompt(diag_case), key)
            evaluation = evaluate_raw_response(case, raw)
        except Exception as exc:
            evaluation = provider_error_evaluation(case, f"Provider call failed ({type(exc).__name__})")
        preflight_pass = (
            evaluation.state == "VALIDATED"
            and evaluation.semantic_oracle_match
            and evaluation.benchmark_auto_eligible
            and not evaluation.unsafe_auto_commit
            and not evaluation.forbidden_risk_auto_commit
        )
        return {
            "preflight_only": True,
            "heldout_benchmark_case": False,
            "counted_in_heldout_metrics": False,
            "preflight_pass": preflight_pass,
            "case_id": preflight.case_id,
            "question": preflight.question,
            "expected_slot_id": preflight.expected_slot_id,
            "expected_literal": preflight.expected_literal,
            "provider_calls_this_run": 1,
            "cumulative_provider_calls": cumulative,
            "evaluation": evaluation_dict(evaluation),
            "zero_persistence": True,
            "freeze_id": freeze["freeze_id"],
        }


def evaluation_dict(value: BenchmarkEvaluation) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "category": value.category,
        "state": value.state,
        "diagnostic": value.diagnostic,
        "provider_calls": value.provider_calls,
        "protocol_failure": value.protocol_failure,
        "slot_error": value.slot_error,
        "claim_shape_error": value.claim_shape_error,
        "entity_target_error": value.entity_target_error,
        "operand_value_error": value.operand_value_error,
        "operation_error": value.operation_error,
        "resulting_state_error": value.resulting_state_error,
        "semantic_oracle_match": value.semantic_oracle_match,
        "benchmark_route": value.benchmark_route,
        "benchmark_auto_eligible": value.benchmark_auto_eligible,
        "safe_automatic_completion": value.safe_automatic_completion,
        "unsafe_auto_commit": value.unsafe_auto_commit,
        "forbidden_risk_auto_commit": value.forbidden_risk_auto_commit,
        "human_review": value.human_review,
        "non_write": value.non_write,
        "raw_model_result": value.raw_model_result,
        "model_selection": value.model_selection,
        "compiler_preview": value.compiler_preview,
        "precondition_preview": value.precondition_preview,
        "risk_preview": value.risk_preview,
    }
