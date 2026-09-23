"""Dormant constrained ontology Semantic IR and exact structural validation.

This Phase 3B.1 module is pure and production-inactive.  It does not call a
provider, compile mutations, resolve entities, persist data, or select risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, TypeAlias

import semantic_ir_v2 as irv2
import slot_registry as registry


PROTOCOL_VERSION = "ontology-semantic-ir-v1"
PRODUCTION_ACTIVE = False
INTENTS = irv2.INTENTS


class ReasonCode(str, Enum):
    ROOT_TYPE_INVALID = "ROOT_TYPE_INVALID"
    PROTOCOL_VERSION_INVALID = "PROTOCOL_VERSION_INVALID"
    INTENT_INVALID = "INTENT_INVALID"
    FIELD_SET_INVALID = "FIELD_SET_INVALID"
    FIELD_TYPE_INVALID = "FIELD_TYPE_INVALID"
    SLOT_INVALID = "SLOT_INVALID"
    SLOT_CLAIM_INCOMPATIBLE = "SLOT_CLAIM_INCOMPATIBLE"
    ENTITY_SCOPE_INVALID = "ENTITY_SCOPE_INVALID"
    ENTITY_CANDIDATE_INVALID = "ENTITY_CANDIDATE_INVALID"
    TARGET_CANDIDATE_INVALID = "TARGET_CANDIDATE_INVALID"
    OPERAND_INVALID = "OPERAND_INVALID"
    SPAN_OUT_OF_RANGE = "SPAN_OUT_OF_RANGE"
    SPAN_EMPTY = "SPAN_EMPTY"
    SPAN_MISMATCH = "SPAN_MISMATCH"
    LITERAL_NOT_FOUND = "LITERAL_NOT_FOUND"
    LITERAL_AMBIGUOUS = "LITERAL_AMBIGUOUS"
    AMBIGUITY_INVALID = "AMBIGUITY_INVALID"


class OntologyIRError(ValueError):
    """Fail-closed structural or grounding validation error."""

    def __init__(
        self,
        reason_code: ReasonCode,
        message: str,
        *,
        resolutions: tuple["ResolvedLiteralOperand", ...] = (),
    ):
        super().__init__(message)
        self.reason_code = reason_code.value
        self.resolutions = resolutions


class Ambiguity(str, Enum):
    UNKNOWN_SLOT = "UNKNOWN_SLOT"
    ENTITY_AMBIGUOUS = "ENTITY_AMBIGUOUS"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    OPERAND_MISSING = "OPERAND_MISSING"


class LiteralResolutionStatus(str, Enum):
    RESOLVED_EXACT = "RESOLVED_EXACT"
    LITERAL_NOT_FOUND = "LITERAL_NOT_FOUND"
    LITERAL_AMBIGUOUS = "LITERAL_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ModelLiteralOperand:
    """Model-owned meaning plus optional non-authoritative legacy offsets."""

    claimed_literal: str
    canonical_value: object = None
    has_canonical_value: bool = False
    model_source_start: int | None = None
    model_source_end: int | None = None


@dataclass(frozen=True, slots=True)
class ExactLiteralResolution:
    claimed_literal: str
    occurrence_count: int
    resolution_status: LiteralResolutionStatus
    source_start: int | None = None
    source_end: int | None = None
    exact_slice: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedLiteralOperand:
    """Application-owned resolution; only RESOLVED_EXACT is executable."""

    role: str
    claimed_literal: str
    occurrence_count: int
    resolution_status: LiteralResolutionStatus
    source_start: int | None
    source_end: int | None
    exact_slice: str | None
    canonical_value: object = None
    has_canonical_value: bool = False
    canonical_value_verified: bool = False

    @property
    def source_literal(self) -> str | None:
        """Compatibility name for consumers of already-grounded operands."""
        return self.exact_slice


@dataclass(frozen=True, slots=True)
class ConstrainedChangeIR:
    slot_id: str
    claim_shape: str
    entity_id: str | None
    target_memory_id: str | None
    operands: tuple[tuple[str, ModelLiteralOperand], ...]
    membership_action: str | None = None
    intent: str = "CHANGE"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class ConstrainedReadIR:
    slot_id: str
    entity_id: str | None
    target_memory_id: str | None
    unknown: bool
    intent: str = "READ"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class ConstrainedClarifyIR:
    slot_id: str
    claim_shape: str | None
    ambiguity: Ambiguity
    question: str
    intent: str = "CLARIFY"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class ConstrainedFreeformIR:
    reply: str
    intent: str = "FREEFORM"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class ConstrainedStatusIR:
    intent: str
    slot_id: str | None = None
    protocol_version: str = PROTOCOL_VERSION


ConstrainedOntologyIR: TypeAlias = (
    ConstrainedChangeIR
    | ConstrainedReadIR
    | ConstrainedClarifyIR
    | ConstrainedFreeformIR
    | ConstrainedStatusIR
)


@dataclass(frozen=True, slots=True)
class GroundedConstrainedIR:
    semantic_ir: ConstrainedOntologyIR
    operands: tuple[ResolvedLiteralOperand, ...]


@dataclass(frozen=True, slots=True)
class SlotMetadataProjection:
    """Application-owned metadata derived after exact slot validation."""

    slot_id: str
    registry_version: int
    semantic_key: str
    display_label: str
    entity_scope: registry.EntityScope
    typed_family: registry.TypedFamily
    value_type: registry.ValueType
    allowed_claim_shapes: frozenset[str]
    allowed_operations: frozenset[str]
    grounding_required: bool
    risk_class: registry.RiskClass
    auto_commit_allowed: bool


def _error(
    reason: ReasonCode,
    message: str,
    *,
    resolutions: tuple[ResolvedLiteralOperand, ...] = (),
) -> None:
    raise OntologyIRError(reason, message, resolutions=resolutions)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be an object")
    return value


def _exact_keys(
    value: dict[str, object], required: set[str], optional: set[str], label: str
) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        _error(ReasonCode.FIELD_SET_INVALID, f"{label} fields are invalid")


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be non-empty exact text")
    return value


def _literal_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be non-empty text")
    return value


def _candidate_ids(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be an ID collection")
    try:
        result = tuple(_nonempty_string(value, f"{label} item") for value in values)
    except TypeError:
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be iterable")
    if len(set(result)) != len(result):
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must not contain duplicates")
    return result


def _known_slot(slot_id: object) -> registry.SlotDefinition:
    if slot_id == registry.UNKNOWN_SLOT:
        _error(ReasonCode.SLOT_INVALID, "UNKNOWN_SLOT is not executable")
    definition = registry.get_slot(slot_id)
    if definition is None:
        _error(ReasonCode.SLOT_INVALID, "slot_id is not an exact Registry-v1 slot")
    return definition


def _selected_id(
    value: object,
    candidates: tuple[str, ...],
    label: str,
    reason: ReasonCode,
) -> str:
    selected = _nonempty_string(value, label)
    if selected not in candidates:
        _error(reason, f"{label} is not an application-supplied candidate")
    return selected


def _validate_entity(
    definition: registry.SlotDefinition,
    value: object,
    candidates: tuple[str, ...],
    *,
    required_for_entity_scope: bool,
) -> str | None:
    if definition.entity_scope is registry.EntityScope.SELF_OR_SINGLETON:
        if value is not None:
            _error(ReasonCode.ENTITY_SCOPE_INVALID, "singleton slot must not carry entity_id")
        return None
    if value is None:
        if required_for_entity_scope:
            _error(ReasonCode.ENTITY_SCOPE_INVALID, "entity-scoped slot requires candidate selection")
        return None
    return _selected_id(value, candidates, "entity_id", ReasonCode.ENTITY_CANDIDATE_INVALID)


def _validate_target(value: object, candidates: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    return _selected_id(
        value,
        candidates,
        "target_memory_id",
        ReasonCode.TARGET_CANDIDATE_INVALID,
    )


def _operand(value: object, label: str, *, canonical_integer: bool = False) -> ModelLiteralOperand:
    operand = _object(value, label)
    required = {"claimed_literal"}
    optional = {"source_start", "source_end"}
    if canonical_integer:
        optional.add("canonical_value")
    _exact_keys(operand, required, optional, label)
    start = operand.get("source_start")
    end = operand.get("source_end")
    if isinstance(start, bool) or not isinstance(start, int):
        start = None
    if isinstance(end, bool) or not isinstance(end, int):
        end = None
    claimed = _literal_string(operand["claimed_literal"], f"{label}.claimed_literal")
    has_canonical = "canonical_value" in operand
    canonical_value = operand.get("canonical_value")
    if canonical_integer:
        if not has_canonical or isinstance(canonical_value, bool) or not isinstance(canonical_value, int):
            _error(ReasonCode.OPERAND_INVALID, f"{label} requires an integer canonical_value")
        if canonical_value < 0:
            _error(ReasonCode.OPERAND_INVALID, f"{label} canonical_value must not be negative")
    return ModelLiteralOperand(
        claimed,
        canonical_value,
        has_canonical,
        start,
        end,
    )


def _change(
    value: dict[str, object],
    entity_candidates: tuple[str, ...],
    target_candidates: tuple[str, ...],
) -> ConstrainedChangeIR:
    required = {"protocol_version", "intent", "slot_id", "claim_shape"}
    common_optional = {"entity_id", "target_memory_id"}
    shape = value.get("claim_shape")
    definition = _known_slot(value.get("slot_id"))
    if not isinstance(shape, str) or shape not in definition.allowed_claim_shapes:
        _error(ReasonCode.SLOT_CLAIM_INCOMPATIBLE, "claim_shape is incompatible with slot_id")

    entity_id = _validate_entity(
        definition,
        value.get("entity_id"),
        entity_candidates,
        required_for_entity_scope=True,
    )
    target_id = _validate_target(value.get("target_memory_id"), target_candidates)
    operands: tuple[tuple[str, ModelLiteralOperand], ...]
    membership_action = None
    if shape in (registry.SCALAR_ASSERTION, registry.FIELD_ASSERTION):
        _exact_keys(value, required | {"value"}, common_optional, "CHANGE")
        operands = (("value", _operand(value["value"], "value")),)
    elif shape == registry.CARDINALITY_ASSERTION:
        _exact_keys(value, required | {"count"}, common_optional, "CHANGE")
        operands = (("count", _operand(value["count"], "count", canonical_integer=True)),)
    elif shape == registry.ENUMERATION_ASSERTION:
        _exact_keys(value, required | {"items"}, common_optional | {"asserted_count"}, "CHANGE")
        raw_items = value["items"]
        if not isinstance(raw_items, list) or not raw_items:
            _error(ReasonCode.OPERAND_INVALID, "items must be a non-empty list")
        operands = tuple(
            (f"items[{index}]", _operand(item, f"items[{index}]"))
            for index, item in enumerate(raw_items)
        )
        if "asserted_count" in value:
            operands += ((
                "asserted_count",
                _operand(value["asserted_count"], "asserted_count", canonical_integer=True),
            ),)
    elif shape == registry.MEMBERSHIP_ASSERTION:
        _exact_keys(value, required | {"membership_action", "item"}, common_optional, "CHANGE")
        membership_action = value["membership_action"]
        if membership_action not in ("ADD", "REMOVE"):
            _error(ReasonCode.OPERAND_INVALID, "membership_action must be ADD or REMOVE")
        operands = (("item", _operand(value["item"], "item")),)
    else:  # Registry validation makes this unreachable, but fail closed.
        _error(ReasonCode.SLOT_CLAIM_INCOMPATIBLE, "unsupported claim shape")
    return ConstrainedChangeIR(
        definition.slot_id,
        shape,
        entity_id,
        target_id,
        operands,
        membership_action,
    )


def parse_constrained_ir(
    value: object,
    *,
    entity_candidates: Iterable[str] = (),
    target_memory_candidates: Iterable[str] = (),
) -> ConstrainedOntologyIR:
    """Parse only the strict, model-owned contract; derive no application metadata."""
    root = _object(value, "root")
    if root.get("protocol_version") != PROTOCOL_VERSION:
        _error(ReasonCode.PROTOCOL_VERSION_INVALID, "protocol_version is invalid")
    intent = root.get("intent")
    if not isinstance(intent, str) or intent not in INTENTS:
        _error(ReasonCode.INTENT_INVALID, "intent is unsupported")
    entities = _candidate_ids(entity_candidates, "entity_candidates")
    targets = _candidate_ids(target_memory_candidates, "target_memory_candidates")

    if intent == "CHANGE":
        return _change(root, entities, targets)
    if intent == "READ":
        _exact_keys(
            root,
            {"protocol_version", "intent", "slot_id", "unknown"},
            {"entity_id", "target_memory_id"},
            "READ",
        )
        definition = _known_slot(root["slot_id"])
        unknown = root["unknown"]
        if not isinstance(unknown, bool):
            _error(ReasonCode.FIELD_TYPE_INVALID, "unknown must be boolean")
        entity_id = _validate_entity(
            definition, root.get("entity_id"), entities, required_for_entity_scope=True
        )
        target_id = _validate_target(root.get("target_memory_id"), targets)
        if unknown and target_id is not None:
            _error(ReasonCode.TARGET_CANDIDATE_INVALID, "unknown READ cannot select a target")
        return ConstrainedReadIR(definition.slot_id, entity_id, target_id, unknown)
    if intent == "CLARIFY":
        _exact_keys(
            root,
            {"protocol_version", "intent", "slot_id", "ambiguity", "question"},
            {"claim_shape"},
            "CLARIFY",
        )
        slot_id = root["slot_id"]
        try:
            ambiguity = Ambiguity(root["ambiguity"])
        except (TypeError, ValueError):
            _error(ReasonCode.AMBIGUITY_INVALID, "ambiguity is invalid")
        question = _nonempty_string(root["question"], "question")
        shape = root.get("claim_shape")
        if slot_id == registry.UNKNOWN_SLOT:
            if ambiguity is not Ambiguity.UNKNOWN_SLOT or shape is not None:
                _error(ReasonCode.AMBIGUITY_INVALID, "UNKNOWN_SLOT clarification is inconsistent")
            return ConstrainedClarifyIR(registry.UNKNOWN_SLOT, None, ambiguity, question)
        definition = _known_slot(slot_id)
        if not isinstance(shape, str) or shape not in definition.allowed_claim_shapes:
            _error(ReasonCode.SLOT_CLAIM_INCOMPATIBLE, "clarification claim_shape is incompatible")
        if ambiguity is Ambiguity.UNKNOWN_SLOT:
            _error(ReasonCode.AMBIGUITY_INVALID, "known slot cannot use UNKNOWN_SLOT ambiguity")
        return ConstrainedClarifyIR(definition.slot_id, shape, ambiguity, question)
    if intent == "FREEFORM":
        _exact_keys(root, {"protocol_version", "intent", "reply"}, set(), "FREEFORM")
        return ConstrainedFreeformIR(_nonempty_string(root["reply"], "reply"))
    # Governance permits UNKNOWN_SLOT to decline safely as ABSTAIN as well as
    # to ask a CLARIFY question.  Keep ordinary status intents strict, but
    # allow the exact UNKNOWN_SLOT marker on ABSTAIN without turning it into an
    # executable ontology slot or accepting arbitrary slot strings.
    if intent == "ABSTAIN" and "slot_id" in root:
        _exact_keys(root, {"protocol_version", "intent", "slot_id"}, set(), intent)
        if root["slot_id"] != registry.UNKNOWN_SLOT:
            _error(
                ReasonCode.SLOT_INVALID,
                "ABSTAIN may carry only the explicit UNKNOWN_SLOT marker",
            )
        return ConstrainedStatusIR(intent, registry.UNKNOWN_SLOT)
    _exact_keys(root, {"protocol_version", "intent"}, set(), intent)
    return ConstrainedStatusIR(intent)


def resolve_exact_literal(source_text: object, claimed_literal: object) -> ExactLiteralResolution:
    """Resolve every overlapping Python-string occurrence without normalization."""
    if not isinstance(source_text, str):
        _error(ReasonCode.FIELD_TYPE_INVALID, "source text must be text")
    literal = _literal_string(claimed_literal, "claimed_literal")
    matches: list[int] = []
    search_from = 0
    while True:
        start = source_text.find(literal, search_from)
        if start < 0:
            break
        matches.append(start)
        search_from = start + 1
    if not matches:
        return ExactLiteralResolution(
            literal, 0, LiteralResolutionStatus.LITERAL_NOT_FOUND
        )
    if len(matches) > 1:
        return ExactLiteralResolution(
            literal, len(matches), LiteralResolutionStatus.LITERAL_AMBIGUOUS
        )
    start = matches[0]
    end = start + len(literal)
    return ExactLiteralResolution(
        literal,
        1,
        LiteralResolutionStatus.RESOLVED_EXACT,
        start,
        end,
        source_text[start:end],
    )


def resolve_literal_operands(
    semantic_ir: ConstrainedOntologyIR, canonical_turn_text: object
) -> tuple[ResolvedLiteralOperand, ...]:
    """Create immutable application-owned resolution data for every operand."""
    if not isinstance(canonical_turn_text, str):
        _error(ReasonCode.FIELD_TYPE_INVALID, "canonical current turn must be text")
    if canonical_turn_text != irv2.canonical_current_turn_text(canonical_turn_text):
        _error(ReasonCode.OPERAND_INVALID, "current turn must use canonical outer whitespace")
    pairs = semantic_ir.operands if isinstance(semantic_ir, ConstrainedChangeIR) else ()
    resolved: list[ResolvedLiteralOperand] = []
    for role, operand in pairs:
        result = resolve_exact_literal(canonical_turn_text, operand.claimed_literal)
        resolved.append(
            ResolvedLiteralOperand(
                role=role,
                claimed_literal=operand.claimed_literal,
                occurrence_count=result.occurrence_count,
                resolution_status=result.resolution_status,
                source_start=result.source_start,
                source_end=result.source_end,
                exact_slice=result.exact_slice,
                canonical_value=operand.canonical_value,
                has_canonical_value=operand.has_canonical_value,
                canonical_value_verified=False,
            )
        )
    return tuple(resolved)


def validate_grounding(
    semantic_ir: ConstrainedOntologyIR, canonical_turn_text: object
) -> GroundedConstrainedIR:
    """Accept only all-unique exact operands; no partial executable grounding."""
    resolved = resolve_literal_operands(semantic_ir, canonical_turn_text)
    for operand in resolved:
        if operand.resolution_status is LiteralResolutionStatus.LITERAL_NOT_FOUND:
            _error(
                ReasonCode.LITERAL_NOT_FOUND,
                "claimed literal does not occur in the current turn",
                resolutions=resolved,
            )
        if operand.resolution_status is LiteralResolutionStatus.LITERAL_AMBIGUOUS:
            _error(
                ReasonCode.LITERAL_AMBIGUOUS,
                "claimed literal occurs more than once in the current turn",
                resolutions=resolved,
            )
    return GroundedConstrainedIR(semantic_ir, resolved)


def validate_constrained_ir(
    value: object,
    canonical_turn_text: object,
    *,
    entity_candidates: Iterable[str] = (),
    target_memory_candidates: Iterable[str] = (),
) -> GroundedConstrainedIR:
    parsed = parse_constrained_ir(
        value,
        entity_candidates=entity_candidates,
        target_memory_candidates=target_memory_candidates,
    )
    return validate_grounding(parsed, canonical_turn_text)


def project_slot_metadata(value: ConstrainedOntologyIR) -> SlotMetadataProjection | None:
    """Derive immutable application metadata separately from model-authored fields."""
    slot_id = getattr(value, "slot_id", None)
    definition = registry.get_slot(slot_id)
    if definition is None:
        return None
    return SlotMetadataProjection(
        slot_id=definition.slot_id,
        registry_version=definition.registry_version,
        semantic_key=definition.semantic_key,
        display_label=definition.display_label,
        entity_scope=definition.entity_scope,
        typed_family=definition.typed_family,
        value_type=definition.value_type,
        allowed_claim_shapes=definition.allowed_claim_shapes,
        allowed_operations=definition.allowed_operations,
        grounding_required=definition.grounding_required,
        risk_class=definition.risk_class,
        auto_commit_allowed=definition.auto_commit_allowed,
    )
