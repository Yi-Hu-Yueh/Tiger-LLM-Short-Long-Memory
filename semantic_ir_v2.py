"""Default-off Architecture D Semantic IR v2 structures and validators.

The application imports this module only on the explicitly enabled v2 route.
Provider transport remains in ``app.py``; this module owns strict validation,
grounding, compilation, typed preconditions, and the Count-to-Set transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TypeAlias


PROTOCOL_VERSION = "semantic-ir-v2"
PRODUCTION_ACTIVE = False

INTENTS = frozenset(
    ("CHANGE", "READ", "CLARIFY", "FREEFORM", "TARGET_NOT_FOUND", "ABSTAIN")
)
CONTROL_INTENTS = frozenset(("READ", "CLARIFY", "FREEFORM", "TARGET_NOT_FOUND", "ABSTAIN"))
CLAIM_SHAPES = frozenset(
    (
        "SCALAR_ASSERTION",
        "CARDINALITY_ASSERTION",
        "ENUMERATION_ASSERTION",
        "MEMBERSHIP_ASSERTION",
        "FIELD_ASSERTION",
        "EXPLICIT_DELTA",
        "FORGET",
    )
)


class ReasonCode(str, Enum):
    SPAN_MISSING = "SPAN_MISSING"
    SPAN_TYPE_INVALID = "SPAN_TYPE_INVALID"
    SPAN_OUT_OF_RANGE = "SPAN_OUT_OF_RANGE"
    SPAN_EMPTY = "SPAN_EMPTY"
    SPAN_MISMATCH = "SPAN_MISMATCH"
    REQUIRED_OPERAND_UNGROUNDED = "REQUIRED_OPERAND_UNGROUNDED"
    CLAIM_SHAPE_GROUNDING_VIOLATION = "CLAIM_SHAPE_GROUNDING_VIOLATION"
    ROOT_TYPE_INVALID = "ROOT_TYPE_INVALID"
    PROTOCOL_VERSION_INVALID = "PROTOCOL_VERSION_INVALID"
    INTENT_INVALID = "INTENT_INVALID"
    FIELD_SET_INVALID = "FIELD_SET_INVALID"
    FIELD_TYPE_INVALID = "FIELD_TYPE_INVALID"
    TARGET_INVALID = "TARGET_INVALID"
    COMPILER_INPUT_INVALID = "COMPILER_INPUT_INVALID"
    TARGET_MODE_INVALID = "TARGET_MODE_INVALID"
    CANONICAL_VALUE_REQUIRED = "CANONICAL_VALUE_REQUIRED"
    DUPLICATE_ENUMERATION_ITEM = "DUPLICATE_ENUMERATION_ITEM"
    ASSERTED_COUNT_MISMATCH = "ASSERTED_COUNT_MISMATCH"
    UNSUPPORTED_CLAIM_MAPPING = "UNSUPPORTED_CLAIM_MAPPING"
    TYPED_PRECONDITION_INVALID = "TYPED_PRECONDITION_INVALID"
    TARGET_UNAUTHORIZED_OR_MISMATCH = "TARGET_UNAUTHORIZED_OR_MISMATCH"
    CREATE_SLOT_CONFLICT = "CREATE_SLOT_CONFLICT"
    REPRESENTATION_TRANSITION_REQUIRED = "REPRESENTATION_TRANSITION_REQUIRED"
    REPRESENTATION_TRANSITION_COMMITTED = "REPRESENTATION_TRANSITION_COMMITTED"
    REPRESENTATION_TRANSITION_ENTRY_INVALID = "REPRESENTATION_TRANSITION_ENTRY_INVALID"
    REPRESENTATION_TRANSITION_REJECTED = "REPRESENTATION_TRANSITION_REJECTED"
    COUNT_MATCHES_SET = "COUNT_MATCHES_SET"
    COUNT_CONFLICTS_WITH_SET = "COUNT_CONFLICTS_WITH_SET"


class SemanticIRV2Error(ValueError):
    """Fail-closed v2 validation error with a non-sensitive stable code."""

    def __init__(self, reason_code: ReasonCode, message: str):
        super().__init__(message)
        self.reason_code = reason_code.value


@dataclass(frozen=True)
class SourceSpanV2:
    source_start: int
    source_end: int


@dataclass(frozen=True)
class LiteralOperandV2:
    """Source provenance plus an optional, explicitly unverified semantic value."""

    span: SourceSpanV2
    claimed_literal: str | None = None
    canonical_value: object = None
    has_canonical_value: bool = False


@dataclass(frozen=True)
class SemanticTargetV2:
    memory_id: str | None = None
    semantic_key: str | None = None


@dataclass(frozen=True)
class ScalarAssertionV2:
    target: SemanticTargetV2
    value: LiteralOperandV2
    claim_shape: str = "SCALAR_ASSERTION"


@dataclass(frozen=True)
class CardinalityAssertionV2:
    target: SemanticTargetV2
    count: LiteralOperandV2
    claim_shape: str = "CARDINALITY_ASSERTION"


@dataclass(frozen=True)
class EnumerationAssertionV2:
    target: SemanticTargetV2
    items: tuple[LiteralOperandV2, ...]
    asserted_count: LiteralOperandV2 | None = None
    claim_shape: str = "ENUMERATION_ASSERTION"


@dataclass(frozen=True)
class MembershipAssertionV2:
    target: SemanticTargetV2
    action: str
    item: LiteralOperandV2
    claim_shape: str = "MEMBERSHIP_ASSERTION"


@dataclass(frozen=True)
class FieldAssertionV2:
    target: SemanticTargetV2
    field_key: str
    value: LiteralOperandV2
    claim_shape: str = "FIELD_ASSERTION"


@dataclass(frozen=True)
class ExplicitDeltaV2:
    target: SemanticTargetV2
    direction: str
    amount: LiteralOperandV2
    claim_shape: str = "EXPLICIT_DELTA"


@dataclass(frozen=True)
class ForgetV2:
    target: SemanticTargetV2
    claim_shape: str = "FORGET"


ChangeClaimV2: TypeAlias = (
    ScalarAssertionV2
    | CardinalityAssertionV2
    | EnumerationAssertionV2
    | MembershipAssertionV2
    | FieldAssertionV2
    | ExplicitDeltaV2
    | ForgetV2
)


@dataclass(frozen=True)
class ChangeIRV2:
    claim: ChangeClaimV2
    intent: str = "CHANGE"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True)
class ReadIRV2:
    current_memory_ids: tuple[str, ...]
    history_memory_ids: tuple[str, ...]
    unknown: bool
    intent: str = "READ"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True)
class ClarifyCandidateV2:
    claim_shape: str
    target: SemanticTargetV2
    action: str | None = None
    field_key: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class ClarifyIRV2:
    candidate: ClarifyCandidateV2
    missing: tuple[str, ...]
    question: str
    intent: str = "CLARIFY"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True)
class FreeformIRV2:
    reply: str
    intent: str = "FREEFORM"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True)
class TargetNotFoundIRV2:
    intent: str = "TARGET_NOT_FOUND"
    protocol_version: str = PROTOCOL_VERSION


@dataclass(frozen=True)
class AbstainIRV2:
    intent: str = "ABSTAIN"
    protocol_version: str = PROTOCOL_VERSION


SemanticIRV2: TypeAlias = (
    ChangeIRV2 | ReadIRV2 | ClarifyIRV2 | FreeformIRV2 | TargetNotFoundIRV2 | AbstainIRV2
)


@dataclass(frozen=True)
class GroundedOperandV2:
    role: str
    source_start: int
    source_end: int
    source_literal: str
    canonical_value: object = None
    has_canonical_value: bool = False
    canonical_value_verified: bool = False


@dataclass(frozen=True)
class GroundedSemanticIRV2:
    semantic_ir: SemanticIRV2
    operands: tuple[GroundedOperandV2, ...]
    diagnostic: dict[str, object]


@dataclass(frozen=True)
class CompiledOperandV2:
    """A grounded literal and any separate, model-semantic canonical value."""

    role: str
    grounded_literal: str
    canonical_value: object = None
    has_canonical_value: bool = False
    canonical_value_verified: bool = False

    @property
    def effective_value(self) -> object:
        return self.canonical_value if self.has_canonical_value else self.grounded_literal


@dataclass(frozen=True)
class CompiledMutationV2:
    """One dormant authoritative mutation request; never a persistence result."""

    claim_shape: str
    typed_family: str
    action: str
    evidence: str
    target_memory_id: str | None
    create_semantic_key: str | None
    operands: tuple[CompiledOperandV2, ...]
    field_key: str | None = None
    protocol_version: str = PROTOCOL_VERSION
    intent: str = "CHANGE"


@dataclass(frozen=True)
class CompiledControlV2:
    """Explicit non-mutation outcome for dormant control intents."""

    intent: str
    protocol_version: str = PROTOCOL_VERSION


CompiledSemanticIRV2: TypeAlias = CompiledMutationV2 | CompiledControlV2


@dataclass(frozen=True)
class AuthoritativeCurrentV2:
    """Explicit authoritative typed Current fixture for dormant resolution."""

    memory_id: str
    typed_family: str
    state: dict[str, object]
    authorized: bool = True


@dataclass(frozen=True)
class TypedPreconditionOutcomeV2:
    """Persistence-free Architecture B precondition result for one v2 request."""

    outcome: str
    reason_code: str
    typed_family: str | None
    action: str | None
    target_memory_id: str | None
    target_present: bool
    next_state: dict[str, object] | None
    destructive_candidate: bool
    protocol_version: str = PROTOCOL_VERSION
    downstream_control: str | None = None


@dataclass(frozen=True)
class RepresentationTransitionOutcomeV2:
    """Atomic dormant Count-to-Set commit result without operand values."""

    status: str
    reason_code: str
    revision_before: int | None
    revision_after: int | None
    history_written: bool
    same_memory_id: bool
    protocol_version: str = PROTOCOL_VERSION


def canonical_current_turn_text(message: object) -> str:
    """Mirror the existing production outer-whitespace handling without normalization."""

    if not isinstance(message, str):
        raise SemanticIRV2Error(ReasonCode.FIELD_TYPE_INVALID, "current turn must be text")
    return message.strip()


def _error(reason: ReasonCode, message: str) -> None:
    raise SemanticIRV2Error(reason, message)


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
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be non-empty canonical text")
    return value


def _id_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be a list")
    checked = tuple(_nonempty_string(item, f"{label} item") for item in value)
    if len(set(checked)) != len(checked):
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must not contain duplicates")
    return checked


def _target(value: object) -> SemanticTargetV2:
    target = _object(value, "target")
    _exact_keys(target, set(), {"memory_id", "semantic_key"}, "target")
    memory_id = target.get("memory_id")
    semantic_key = target.get("semantic_key")
    if memory_id is not None:
        memory_id = _nonempty_string(memory_id, "target.memory_id")
    if semantic_key is not None:
        semantic_key = _nonempty_string(semantic_key, "target.semantic_key")
    if (memory_id is None) == (semantic_key is None):
        _error(ReasonCode.TARGET_INVALID, "target requires exactly one semantic selector")
    return SemanticTargetV2(memory_id=memory_id, semantic_key=semantic_key)


def _json_scalar(value: object, label: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    _error(ReasonCode.FIELD_TYPE_INVALID, f"{label} must be a finite JSON scalar")


def _operand(
    value: object,
    label: str,
    *,
    canonical_required: bool = False,
    canonical_integer: bool = False,
    allow_canonical: bool = True,
) -> LiteralOperandV2:
    operand = _object(value, label)
    _exact_keys(
        operand,
        set(),
        (
            {"source_start", "source_end", "claimed_literal", "canonical_value"}
            if allow_canonical
            else {"source_start", "source_end", "claimed_literal"}
        ),
        label,
    )
    start = operand.get("source_start")
    end = operand.get("source_end")
    if start is None or end is None:
        _error(ReasonCode.SPAN_MISSING, f"{label} source span is required")
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        _error(ReasonCode.SPAN_TYPE_INVALID, f"{label} source span must use integer offsets")
    claimed = operand.get("claimed_literal")
    if claimed is not None and not isinstance(claimed, str):
        _error(ReasonCode.FIELD_TYPE_INVALID, f"{label}.claimed_literal must be text")
    has_canonical = "canonical_value" in operand
    if canonical_required and not has_canonical:
        _error(ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION, f"{label} requires canonical_value")
    canonical = _json_scalar(operand.get("canonical_value"), f"{label}.canonical_value") if has_canonical else None
    if canonical_integer and (isinstance(canonical, bool) or not isinstance(canonical, int)):
        _error(ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION, f"{label} canonical_value must be an integer")
    return LiteralOperandV2(SourceSpanV2(start, end), claimed, canonical, has_canonical)


def _claim(value: object) -> ChangeClaimV2:
    claim = _object(value, "claim")
    shape = claim.get("claim_shape")
    if not isinstance(shape, str) or shape not in CLAIM_SHAPES:
        _error(ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION, "claim_shape is unsupported")

    if shape == "SCALAR_ASSERTION":
        _exact_keys(claim, {"claim_shape", "target", "value"}, set(), shape)
        return ScalarAssertionV2(_target(claim["target"]), _operand(claim["value"], "value"))
    if shape == "CARDINALITY_ASSERTION":
        _exact_keys(claim, {"claim_shape", "target", "count"}, set(), shape)
        return CardinalityAssertionV2(
            _target(claim["target"]),
            _operand(claim["count"], "count", canonical_required=True, canonical_integer=True),
        )
    if shape == "ENUMERATION_ASSERTION":
        _exact_keys(claim, {"claim_shape", "target", "items"}, {"asserted_count"}, shape)
        items = claim["items"]
        if not isinstance(items, list) or not items:
            _error(ReasonCode.REQUIRED_OPERAND_UNGROUNDED, "enumeration requires grounded item operands")
        checked_items = tuple(
            _operand(item, f"items[{index}]", allow_canonical=False)
            for index, item in enumerate(items)
        )
        asserted_count = None
        if "asserted_count" in claim:
            asserted_count = _operand(
                claim["asserted_count"],
                "asserted_count",
                canonical_required=True,
                canonical_integer=True,
            )
        return EnumerationAssertionV2(_target(claim["target"]), checked_items, asserted_count)
    if shape == "MEMBERSHIP_ASSERTION":
        _exact_keys(claim, {"claim_shape", "target", "action", "item"}, set(), shape)
        action = claim["action"]
        if action not in ("ADD", "REMOVE"):
            _error(ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION, "membership action must be ADD or REMOVE")
        return MembershipAssertionV2(
            _target(claim["target"]), str(action), _operand(claim["item"], "item", allow_canonical=False)
        )
    if shape == "FIELD_ASSERTION":
        _exact_keys(claim, {"claim_shape", "target", "field_key", "value"}, set(), shape)
        return FieldAssertionV2(
            _target(claim["target"]),
            _nonempty_string(claim["field_key"], "field_key"),
            _operand(claim["value"], "value"),
        )
    if shape == "EXPLICIT_DELTA":
        _exact_keys(claim, {"claim_shape", "target", "direction", "amount"}, set(), shape)
        direction = claim["direction"]
        if direction not in ("INCREMENT", "DECREMENT"):
            _error(ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION, "delta direction is invalid")
        amount = _operand(
            claim["amount"], "amount", canonical_required=True, canonical_integer=True
        )
        if amount.canonical_value <= 0:  # type: ignore[operator]
            _error(ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION, "delta amount must be positive")
        return ExplicitDeltaV2(_target(claim["target"]), str(direction), amount)

    _exact_keys(claim, {"claim_shape", "target"}, set(), shape)
    return ForgetV2(_target(claim["target"]))


def _clarify_candidate(value: object) -> tuple[ClarifyCandidateV2, tuple[str, ...]]:
    candidate = _object(value, "candidate")
    shape = candidate.get("claim_shape")
    if not isinstance(shape, str) or shape not in CLAIM_SHAPES or shape == "FORGET":
        _error(
            ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION,
            "clarification candidate claim_shape is unsupported",
        )
    target = _target(candidate.get("target"))
    if shape == "MEMBERSHIP_ASSERTION":
        _exact_keys(candidate, {"claim_shape", "target", "action"}, set(), "candidate")
        action = candidate["action"]
        if action not in ("ADD", "REMOVE"):
            _error(
                ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION,
                "clarification membership action is invalid",
            )
        return ClarifyCandidateV2(shape, target, action=str(action)), ("item",)
    if shape == "FIELD_ASSERTION":
        _exact_keys(candidate, {"claim_shape", "target", "field_key"}, set(), "candidate")
        field_key = _nonempty_string(candidate["field_key"], "candidate.field_key")
        return ClarifyCandidateV2(shape, target, field_key=field_key), ("value",)
    if shape == "EXPLICIT_DELTA":
        _exact_keys(candidate, {"claim_shape", "target", "direction"}, set(), "candidate")
        direction = candidate["direction"]
        if direction not in ("INCREMENT", "DECREMENT"):
            _error(
                ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION,
                "clarification delta direction is invalid",
            )
        return ClarifyCandidateV2(shape, target, direction=str(direction)), ("amount",)
    _exact_keys(candidate, {"claim_shape", "target"}, set(), "candidate")
    missing = {
        "SCALAR_ASSERTION": ("value",),
        "CARDINALITY_ASSERTION": ("count",),
        "ENUMERATION_ASSERTION": ("items",),
    }.get(shape)
    if missing is None:
        _error(
            ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION,
            "clarification candidate cannot be compiled safely",
        )
    return ClarifyCandidateV2(shape, target), missing


def validate_semantic_ir_v2(value: object) -> SemanticIRV2:
    """Strictly validate the dormant discriminated v2 structure only."""

    if not isinstance(value, dict):
        _error(ReasonCode.ROOT_TYPE_INVALID, "v2 root must be an object")
    protocol_version = value.get("protocol_version")
    if protocol_version != PROTOCOL_VERSION:
        _error(ReasonCode.PROTOCOL_VERSION_INVALID, "v2 protocol_version is invalid")
    intent = value.get("intent")
    if not isinstance(intent, str) or intent not in INTENTS:
        _error(ReasonCode.INTENT_INVALID, "v2 intent is unsupported")

    if intent == "CHANGE":
        _exact_keys(value, {"protocol_version", "intent", "claim"}, set(), "CHANGE")
        return ChangeIRV2(_claim(value["claim"]))
    if intent == "READ":
        _exact_keys(
            value,
            {"protocol_version", "intent", "current_memory_ids", "history_memory_ids", "unknown"},
            set(),
            "READ",
        )
        current = _id_list(value["current_memory_ids"], "current_memory_ids")
        history = _id_list(value["history_memory_ids"], "history_memory_ids")
        unknown = value["unknown"]
        if not isinstance(unknown, bool) or unknown == bool(current or history):
            _error(ReasonCode.FIELD_TYPE_INVALID, "READ must select IDs or unknown, but not both")
        return ReadIRV2(current, history, unknown)
    if intent == "CLARIFY":
        _exact_keys(
            value,
            {"protocol_version", "intent", "candidate", "missing", "question"},
            set(),
            "CLARIFY",
        )
        candidate, expected_missing = _clarify_candidate(value["candidate"])
        missing = _id_list(value["missing"], "missing")
        if missing != expected_missing:
            _error(
                ReasonCode.FIELD_SET_INVALID,
                "clarification missing fields do not match candidate",
            )
        return ClarifyIRV2(
            candidate,
            missing,
            _nonempty_string(value["question"], "question"),
        )
    if intent == "FREEFORM":
        _exact_keys(value, {"protocol_version", "intent", "reply"}, set(), "FREEFORM")
        return FreeformIRV2(_nonempty_string(value["reply"], "reply"))
    _exact_keys(value, {"protocol_version", "intent"}, set(), intent)
    return TargetNotFoundIRV2() if intent == "TARGET_NOT_FOUND" else AbstainIRV2()


def _operands(value: SemanticIRV2) -> tuple[tuple[str, LiteralOperandV2], ...]:
    if not isinstance(value, ChangeIRV2):
        return ()
    claim = value.claim
    if isinstance(claim, ScalarAssertionV2):
        return (("value", claim.value),)
    if isinstance(claim, CardinalityAssertionV2):
        return (("count", claim.count),)
    if isinstance(claim, EnumerationAssertionV2):
        result = tuple((f"items[{index}]", item) for index, item in enumerate(claim.items))
        if claim.asserted_count is not None:
            result += (("asserted_count", claim.asserted_count),)
        return result
    if isinstance(claim, MembershipAssertionV2):
        return (("item", claim.item),)
    if isinstance(claim, FieldAssertionV2):
        return (("value", claim.value),)
    if isinstance(claim, ExplicitDeltaV2):
        return (("amount", claim.amount),)
    return ()


def grounding_diagnostic(
    semantic_ir: SemanticIRV2,
    *,
    grounding: str,
    reason_code: str | None = None,
) -> dict[str, object]:
    """Return metadata only; never include text, values, slices, secrets, or payloads."""

    if grounding not in ("PASS", "FAIL"):
        raise ValueError("grounding must be PASS or FAIL")
    operands = _operands(semantic_ir)
    spans = tuple(operand.span for _, operand in operands)
    claim_shape = semantic_ir.claim.claim_shape if isinstance(semantic_ir, ChangeIRV2) else None
    return {
        "protocol_version": PROTOCOL_VERSION,
        "intent": semantic_ir.intent,
        "claim_shape": claim_shape,
        "operand_count": len(operands),
        "span_count": len(spans),
        "span_lengths": [max(span.source_end - span.source_start, 0) for span in spans],
        "grounding": grounding,
        "reason_code": reason_code,
    }


def validate_grounding(
    semantic_ir: SemanticIRV2, canonical_turn_text: object
) -> GroundedSemanticIRV2:
    """Validate exact spans only; do not infer, normalize, search, or interpret."""

    if not isinstance(canonical_turn_text, str):
        _error(ReasonCode.FIELD_TYPE_INVALID, "canonical current turn must be text")
    if canonical_turn_text != canonical_current_turn_text(canonical_turn_text):
        _error(
            ReasonCode.CLAIM_SHAPE_GROUNDING_VIOLATION,
            "grounding input must already use canonical outer-whitespace handling",
        )

    grounded: list[GroundedOperandV2] = []
    for role, operand in _operands(semantic_ir):
        start = operand.span.source_start
        end = operand.span.source_end
        if end == start:
            _error(ReasonCode.SPAN_EMPTY, "source span must not be empty")
        if start < 0 or end < start or end > len(canonical_turn_text):
            _error(ReasonCode.SPAN_OUT_OF_RANGE, "source span is outside the current turn")
        source_literal = canonical_turn_text[start:end]
        if operand.claimed_literal is not None and source_literal != operand.claimed_literal:
            _error(ReasonCode.SPAN_MISMATCH, "source span does not exactly match claimed literal")
        grounded.append(
            GroundedOperandV2(
                role=role,
                source_start=start,
                source_end=end,
                source_literal=source_literal,
                canonical_value=operand.canonical_value,
                has_canonical_value=operand.has_canonical_value,
                canonical_value_verified=False,
            )
        )

    diagnostic = grounding_diagnostic(semantic_ir, grounding="PASS")
    return GroundedSemanticIRV2(semantic_ir, tuple(grounded), diagnostic)


def _compiled_operands(grounded: GroundedSemanticIRV2) -> tuple[CompiledOperandV2, ...]:
    return tuple(
        CompiledOperandV2(
            role=operand.role,
            grounded_literal=operand.source_literal,
            canonical_value=operand.canonical_value,
            has_canonical_value=operand.has_canonical_value,
            canonical_value_verified=False,
        )
        for operand in grounded.operands
    )


def _compiled_target(target: SemanticTargetV2) -> tuple[str | None, str | None]:
    return target.memory_id, target.semantic_key


def _create_or_existing_action(
    target: SemanticTargetV2, create_action: str, existing_action: str
) -> str:
    return create_action if target.semantic_key is not None else existing_action


def _existing_target(target: SemanticTargetV2, label: str) -> None:
    if target.memory_id is None:
        _error(ReasonCode.TARGET_MODE_INVALID, f"{label} requires an existing target")


def _require_grounded_compiler_input(value: object) -> GroundedSemanticIRV2:
    if not isinstance(value, GroundedSemanticIRV2):
        _error(
            ReasonCode.COMPILER_INPUT_INVALID,
            "claim-shape compiler accepts only GroundedSemanticIRV2",
        )
    if value.diagnostic.get("grounding") != "PASS":
        _error(ReasonCode.COMPILER_INPUT_INVALID, "grounding must have passed")
    expected_roles = tuple(role for role, _ in _operands(value.semantic_ir))
    actual_roles = tuple(operand.role for operand in value.operands)
    if actual_roles != expected_roles:
        _error(ReasonCode.COMPILER_INPUT_INVALID, "grounded operands are incomplete")
    return value


def compile_claim_shape(value: object) -> CompiledSemanticIRV2:
    """Compile grounded v2 structure without prose, persistence, policy, or repair."""

    grounded = _require_grounded_compiler_input(value)
    semantic_ir = grounded.semantic_ir
    if not isinstance(semantic_ir, ChangeIRV2):
        return CompiledControlV2(intent=semantic_ir.intent)

    claim = semantic_ir.claim
    operands = _compiled_operands(grounded)
    target_id, create_key = _compiled_target(claim.target)

    if isinstance(claim, ScalarAssertionV2):
        return CompiledMutationV2(
            claim.claim_shape,
            "SCALAR",
            _create_or_existing_action(claim.target, "CREATE_SCALAR", "SET_VALUE"),
            "EXPLICIT_ASSERTION",
            target_id,
            create_key,
            operands,
        )

    if isinstance(claim, CardinalityAssertionV2):
        count_operand = operands[0]
        if not count_operand.has_canonical_value or isinstance(count_operand.canonical_value, bool) or not isinstance(count_operand.canonical_value, int):
            _error(ReasonCode.CANONICAL_VALUE_REQUIRED, "cardinality requires canonical integer")
        return CompiledMutationV2(
            claim.claim_shape,
            "COUNT",
            _create_or_existing_action(claim.target, "CREATE_COUNT", "SET_COUNT"),
            "EXPLICIT_ASSERTION",
            target_id,
            create_key,
            operands,
        )

    if isinstance(claim, EnumerationAssertionV2):
        item_operands = tuple(item for item in operands if item.role.startswith("items["))
        item_values = tuple(item.grounded_literal for item in item_operands)
        if len(set(item_values)) != len(item_values):
            _error(
                ReasonCode.DUPLICATE_ENUMERATION_ITEM,
                "enumeration contains duplicate authoritative items",
            )
        asserted_count = next(
            (item for item in operands if item.role == "asserted_count"), None
        )
        if asserted_count is not None:
            count_value = asserted_count.canonical_value
            if (
                not asserted_count.has_canonical_value
                or isinstance(count_value, bool)
                or not isinstance(count_value, int)
            ):
                _error(
                    ReasonCode.CANONICAL_VALUE_REQUIRED,
                    "asserted enumeration count requires canonical integer",
                )
            if count_value != len(item_values):
                _error(
                    ReasonCode.ASSERTED_COUNT_MISMATCH,
                    "asserted count does not match unique grounded item count",
                )
        return CompiledMutationV2(
            claim.claim_shape,
            "SET",
            _create_or_existing_action(claim.target, "CREATE_SET", "REPLACE_SET"),
            "EXPLICIT_COMPLETE_STATE",
            target_id,
            create_key,
            operands,
        )

    if isinstance(claim, MembershipAssertionV2):
        _existing_target(claim.target, "membership assertion")
        return CompiledMutationV2(
            claim.claim_shape,
            "SET",
            "ADD_ITEM" if claim.action == "ADD" else "REMOVE_ITEM",
            "EXPLICIT_TARGET_ITEM",
            target_id,
            None,
            operands,
        )

    if isinstance(claim, FieldAssertionV2):
        return CompiledMutationV2(
            claim.claim_shape,
            "RECORD",
            _create_or_existing_action(claim.target, "CREATE_RECORD", "SET_FIELD"),
            "EXPLICIT_FIELD_VALUE",
            target_id,
            create_key,
            operands,
            field_key=claim.field_key,
        )

    if isinstance(claim, ExplicitDeltaV2):
        _existing_target(claim.target, "explicit delta")
        amount = operands[0]
        if not amount.has_canonical_value or isinstance(amount.canonical_value, bool) or not isinstance(amount.canonical_value, int):
            _error(ReasonCode.CANONICAL_VALUE_REQUIRED, "delta requires canonical integer")
        return CompiledMutationV2(
            claim.claim_shape,
            "COUNT",
            claim.direction,
            "EXPLICIT_DELTA",
            target_id,
            None,
            operands,
        )

    if isinstance(claim, ForgetV2):
        _existing_target(claim.target, "forget")
        return CompiledMutationV2(
            claim.claim_shape,
            "TARGET_MEMORY",
            "DELETE_MEMORY",
            "EXPLICIT_FORGET",
            target_id,
            None,
            (),
        )

    _error(ReasonCode.UNSUPPORTED_CLAIM_MAPPING, "claim shape has no approved mapping")


_FAMILY_TO_ARCHITECTURE_B_STATE = {
    "SCALAR": "scalar",
    "SET": "set",
    "COUNT": "count",
    "RECORD": "record",
}
_CREATE_ACTIONS = frozenset(("CREATE_SCALAR", "CREATE_SET", "CREATE_COUNT", "CREATE_RECORD"))
_DESTRUCTIVE_ACTIONS = frozenset(("REMOVE_ITEM", "DELETE_FIELD", "DELETE_MEMORY"))


def _precondition_result(
    compiled: CompiledMutationV2,
    outcome: str,
    reason_code: str,
    *,
    current: AuthoritativeCurrentV2 | None,
    next_state: dict[str, object] | None = None,
    destructive_candidate: bool = False,
    downstream_control: str | None = None,
) -> TypedPreconditionOutcomeV2:
    return TypedPreconditionOutcomeV2(
        outcome=outcome,
        reason_code=reason_code,
        typed_family=compiled.typed_family,
        action=compiled.action,
        target_memory_id=compiled.target_memory_id,
        target_present=current is not None,
        next_state=next_state,
        destructive_candidate=destructive_candidate,
        downstream_control=downstream_control,
    )


def _operand_by_role(compiled: CompiledMutationV2, role: str) -> CompiledOperandV2:
    matches = tuple(operand for operand in compiled.operands if operand.role == role)
    if len(matches) != 1:
        raise ValueError(f"compiled action requires exactly one {role} operand")
    return matches[0]


def _architecture_b_arguments(compiled: CompiledMutationV2) -> dict[str, object]:
    """Adapt compiled operands to canonical Architecture B arguments without prose."""

    action = compiled.action
    if action in ("CREATE_SCALAR", "SET_VALUE", "REASSERT_NOOP"):
        return {"value": _operand_by_role(compiled, "value").effective_value}
    if action in ("CREATE_COUNT", "SET_COUNT"):
        return {"value": _operand_by_role(compiled, "count").effective_value}
    if action in ("INCREMENT", "DECREMENT"):
        return {"amount": _operand_by_role(compiled, "amount").effective_value}
    if action in ("CREATE_SET", "REPLACE_SET"):
        item_operands = tuple(
            operand for operand in compiled.operands if operand.role.startswith("items[")
        )
        item_roles = tuple(operand.role for operand in item_operands)
        expected_roles = tuple(f"items[{index}]" for index in range(len(item_operands)))
        asserted_counts = tuple(
            operand for operand in compiled.operands if operand.role == "asserted_count"
        )
        if (
            not item_operands
            or item_roles != expected_roles
            or len(asserted_counts) > 1
            or len(item_operands) + len(asserted_counts) != len(compiled.operands)
        ):
            raise ValueError("compiled set replacement requires sequential item operands")
        return {"items": [operand.grounded_literal for operand in item_operands]}
    if action in ("ADD_ITEM", "REMOVE_ITEM"):
        return {"item": _operand_by_role(compiled, "item").grounded_literal}
    if action == "CREATE_RECORD":
        if compiled.field_key is None:
            raise ValueError("compiled record creation requires a field key")
        return {
            "fields": {
                compiled.field_key: _operand_by_role(compiled, "value").effective_value
            }
        }
    if action == "SET_FIELD":
        if compiled.field_key is None:
            raise ValueError("compiled field update requires a field key")
        return {
            "field": compiled.field_key,
            "value": _operand_by_role(compiled, "value").effective_value,
        }
    if action == "DELETE_FIELD":
        if compiled.field_key is None or compiled.operands:
            raise ValueError("compiled field deletion requires only a field key")
        return {"field": compiled.field_key}
    if action == "DELETE_MEMORY":
        if compiled.operands:
            raise ValueError("compiled memory deletion must not contain operands")
        return {}
    raise ValueError("compiled action is unsupported by Architecture B")


def architecture_b_mutation_decision(
    compiled: CompiledMutationV2,
    current: AuthoritativeCurrentV2 | None,
):
    """Build the existing internal decision after v2 compilation."""

    import app as architecture_b

    if not isinstance(compiled, CompiledMutationV2):
        raise SemanticIRV2Error(
            ReasonCode.COMPILER_INPUT_INVALID, "compiled mutation is required"
        )
    arguments = _architecture_b_arguments(compiled)
    if compiled.typed_family == "TARGET_MEMORY":
        if current is None:
            raise SemanticIRV2Error(
                ReasonCode.TARGET_INVALID, "target-memory operation requires Current"
            )
        state_type = _FAMILY_TO_ARCHITECTURE_B_STATE.get(current.typed_family)
    else:
        state_type = _FAMILY_TO_ARCHITECTURE_B_STATE.get(compiled.typed_family)
    if state_type is None:
        raise SemanticIRV2Error(
            ReasonCode.UNSUPPORTED_CLAIM_MAPPING, "typed family is unsupported"
        )
    return architecture_b.TypedDecision(
        kind="PROPOSE" if compiled.action in _DESTRUCTIVE_ACTIONS else "MUTATE",
        state_type=state_type,
        memory_id=compiled.target_memory_id,
        operation=compiled.action,
        arguments=arguments,
        evidence=compiled.evidence,
        current_memory_ids=(),
        history_ids=(),
        unknown=False,
        clarification=None,
        semantic_key=compiled.create_semantic_key,
        display_label=compiled.create_semantic_key,
        clarification_id=None,
    )


def architecture_b_control_decision(semantic_ir: SemanticIRV2):
    """Map one validated v2 control variant to the existing internal control."""

    import app as architecture_b

    if isinstance(semantic_ir, ReadIRV2):
        return architecture_b.TypedDecision(
            "READ", None, None, None, {}, "READ_SELECTION",
            semantic_ir.current_memory_ids, semantic_ir.history_memory_ids,
            semantic_ir.unknown, None, None, None, None,
        )
    if isinstance(semantic_ir, ClarifyIRV2):
        candidate = semantic_ir.candidate
        if candidate.target.memory_id is None:
            raise SemanticIRV2Error(
                ReasonCode.TARGET_MODE_INVALID,
                "Phase 2A clarification requires an existing target",
            )
        mapping = {
            "SCALAR_ASSERTION": ("scalar", "SET_VALUE", {}, ("value",)),
            "CARDINALITY_ASSERTION": ("count", "SET_COUNT", {}, ("value",)),
            "ENUMERATION_ASSERTION": ("set", "REPLACE_SET", {}, ("items",)),
            "MEMBERSHIP_ASSERTION": (
                "set",
                "ADD_ITEM" if candidate.action == "ADD" else "REMOVE_ITEM",
                {},
                ("item",),
            ),
            "FIELD_ASSERTION": (
                "record", "SET_FIELD", {"field": candidate.field_key}, ("value",)
            ),
            "EXPLICIT_DELTA": (
                "count", str(candidate.direction), {}, ("amount",)
            ),
        }
        state_type, operation, arguments, missing = mapping[candidate.claim_shape]
        return architecture_b.TypedDecision(
            "CLARIFY", state_type, candidate.target.memory_id, operation,
            arguments, "INSUFFICIENT", (), (), False,
            {"missing_fields": list(missing)}, None, None, None,
        )
    kind = {
        FreeformIRV2: "FREEFORM",
        TargetNotFoundIRV2: "TARGET_NOT_FOUND",
        AbstainIRV2: "ABSTAIN",
    }.get(type(semantic_ir))
    if kind is None:
        raise SemanticIRV2Error(
            ReasonCode.COMPILER_INPUT_INVALID, "control variant is unsupported"
        )
    return architecture_b.TypedDecision(
        kind, None, None, None, {}, "NONE", (), (), False, None, None, None, None
    )


def resolve_compiled_precondition(
    compiled: CompiledSemanticIRV2,
    current: AuthoritativeCurrentV2 | None,
) -> TypedPreconditionOutcomeV2:
    """Resolve one dormant v2 request through Architecture B without persistence."""

    if not isinstance(compiled, CompiledMutationV2):
        return TypedPreconditionOutcomeV2(
            "FAIL_CLOSED",
            ReasonCode.TYPED_PRECONDITION_INVALID.value,
            None,
            None,
            None,
            current is not None,
            None,
            False,
        )
    if compiled.protocol_version != PROTOCOL_VERSION or compiled.intent != "CHANGE":
        return _precondition_result(
            compiled,
            "FAIL_CLOSED",
            ReasonCode.TYPED_PRECONDITION_INVALID.value,
            current=current,
        )

    is_create = compiled.action in _CREATE_ACTIONS
    if is_create:
        if (
            compiled.target_memory_id is not None
            or not isinstance(compiled.create_semantic_key, str)
            or not compiled.create_semantic_key
        ):
            return _precondition_result(
                compiled,
                "FAIL_CLOSED",
                ReasonCode.TYPED_PRECONDITION_INVALID.value,
                current=current,
            )
        if current is not None:
            return _precondition_result(
                compiled,
                "FAIL_CLOSED",
                ReasonCode.CREATE_SLOT_CONFLICT.value,
                current=current,
            )
    else:
        if (
            not isinstance(compiled.target_memory_id, str)
            or not compiled.target_memory_id
            or compiled.create_semantic_key is not None
            or current is None
            or not isinstance(current.memory_id, str)
            or current.memory_id != compiled.target_memory_id
            or not current.authorized
        ):
            return _precondition_result(
                compiled,
                "FAIL_CLOSED",
                ReasonCode.TARGET_UNAUTHORIZED_OR_MISMATCH.value,
                current=current,
            )

    try:
        import app as architecture_b

        arguments = _architecture_b_arguments(compiled)
        if current is not None and compiled.claim_shape == "ENUMERATION_ASSERTION" and (
            compiled.typed_family == "SET" and current.typed_family == "COUNT"
        ):
            architecture_b.validate_typed_state("count", current.state)
            return _precondition_result(
                compiled,
                "REPRESENTATION_TRANSITION_REQUIRED",
                ReasonCode.REPRESENTATION_TRANSITION_REQUIRED.value,
                current=current,
            )

        if current is not None and compiled.claim_shape == "CARDINALITY_ASSERTION" and (
            compiled.typed_family == "COUNT" and current.typed_family == "SET"
        ):
            canonical_set = architecture_b.validate_typed_state("set", current.state)
            count = arguments["value"]
            architecture_b.validate_typed_state("count", {"value": count})
            if count == len(canonical_set["items"]):
                return _precondition_result(
                    compiled,
                    "NOOP",
                    ReasonCode.COUNT_MATCHES_SET.value,
                    current=current,
                    next_state=canonical_set,
                )
            return _precondition_result(
                compiled,
                "FAIL_CLOSED",
                ReasonCode.COUNT_CONFLICTS_WITH_SET.value,
                current=current,
                downstream_control="CLARIFY",
            )

        if compiled.typed_family == "TARGET_MEMORY":
            if compiled.action != "DELETE_MEMORY" or current is None:
                raise ValueError("target-memory action requires an authoritative target")
            state_type = _FAMILY_TO_ARCHITECTURE_B_STATE.get(current.typed_family)
        else:
            state_type = _FAMILY_TO_ARCHITECTURE_B_STATE.get(compiled.typed_family)
            if current is not None and current.typed_family != compiled.typed_family:
                raise ValueError("compiled family does not match authoritative Current")
        if state_type is None:
            raise ValueError("compiled typed family is unsupported")

        decision = architecture_b.TypedDecision(
            kind="PROPOSE" if compiled.action in _DESTRUCTIVE_ACTIONS else "MUTATE",
            state_type=state_type,
            memory_id=compiled.target_memory_id,
            operation=compiled.action,
            arguments=arguments,
            evidence=compiled.evidence,
            current_memory_ids=(),
            history_ids=(),
            unknown=False,
            clarification=None,
            semantic_key=compiled.create_semantic_key,
            display_label=None,
            clarification_id=None,
        )
        resolved = architecture_b.resolve_typed_precondition(
            decision,
            None if current is None else current.state,
        )
        transition = resolved.transition
        return _precondition_result(
            compiled,
            resolved.outcome,
            resolved.reason_code,
            current=current,
            next_state=None if transition is None else transition.next_state,
            destructive_candidate=(
                transition is not None and transition.requires_proposal
            ),
        )
    except (architecture_b.AppError, KeyError, TypeError, ValueError):
        return _precondition_result(
            compiled,
            "FAIL_CLOSED",
            ReasonCode.TYPED_PRECONDITION_INVALID.value,
            current=current,
        )


def commit_count_to_set_transition(
    store: object,
    user_id: object,
    compiled: CompiledSemanticIRV2,
    current: AuthoritativeCurrentV2 | None,
    precondition: TypedPreconditionOutcomeV2,
    expected_revision: object,
    *,
    session_id: str | None = None,
    user_message: str | None = None,
    reply: str | None = None,
) -> RepresentationTransitionOutcomeV2:
    """Persist one approved dormant same-lineage Count-to-Set transition."""

    import app as architecture_b

    valid_entry = (
        isinstance(store, architecture_b.MemoryStore)
        and isinstance(user_id, str)
        and isinstance(compiled, CompiledMutationV2)
        and compiled.protocol_version == PROTOCOL_VERSION
        and compiled.intent == "CHANGE"
        and compiled.claim_shape == "ENUMERATION_ASSERTION"
        and compiled.typed_family == "SET"
        and compiled.action == "REPLACE_SET"
        and isinstance(compiled.target_memory_id, str)
        and bool(compiled.target_memory_id)
        and compiled.create_semantic_key is None
        and isinstance(current, AuthoritativeCurrentV2)
        and current.authorized
        and current.memory_id == compiled.target_memory_id
        and current.typed_family == "COUNT"
        and isinstance(precondition, TypedPreconditionOutcomeV2)
        and precondition.outcome == "REPRESENTATION_TRANSITION_REQUIRED"
        and precondition.reason_code
        == ReasonCode.REPRESENTATION_TRANSITION_REQUIRED.value
        and precondition.typed_family == "SET"
        and precondition.action == "REPLACE_SET"
        and precondition.target_memory_id == compiled.target_memory_id
        and precondition.target_present
        and isinstance(expected_revision, int)
        and not isinstance(expected_revision, bool)
        and expected_revision >= 0
    )
    if not valid_entry:
        return RepresentationTransitionOutcomeV2(
            "FAIL_CLOSED",
            ReasonCode.REPRESENTATION_TRANSITION_ENTRY_INVALID.value,
            None,
            None,
            False,
            False,
        )

    try:
        count_state = architecture_b.validate_typed_state("count", current.state)
        set_arguments = _architecture_b_arguments(compiled)
        set_state = architecture_b.validate_typed_state("set", set_arguments)
    except (architecture_b.AppError, KeyError, TypeError, ValueError):
        return RepresentationTransitionOutcomeV2(
            "FAIL_CLOSED",
            ReasonCode.REPRESENTATION_TRANSITION_ENTRY_INVALID.value,
            None,
            None,
            False,
            False,
        )

    try:
        revision_before, revision_after = store._commit_count_to_set_representation(
            user_id,
            compiled.target_memory_id,
            set_state["items"],
            expected_revision,
            count_state["value"],
            session_id=session_id,
            user_message=user_message,
            reply=reply,
        )
    except architecture_b.AppError:
        return RepresentationTransitionOutcomeV2(
            "FAIL_CLOSED",
            ReasonCode.REPRESENTATION_TRANSITION_REJECTED.value,
            None,
            None,
            False,
            True,
        )
    return RepresentationTransitionOutcomeV2(
        "COMMITTED",
        ReasonCode.REPRESENTATION_TRANSITION_COMMITTED.value,
        revision_before,
        revision_after,
        True,
        True,
    )


def precondition_diagnostic(
    compiled: CompiledSemanticIRV2,
    resolved: TypedPreconditionOutcomeV2,
) -> dict[str, object]:
    """Return privacy-safe metadata for the dormant typed-precondition stage."""

    if not isinstance(resolved, TypedPreconditionOutcomeV2):
        raise TypeError("resolved must be a TypedPreconditionOutcomeV2")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "stage": "TYPED_PRECONDITION_RESOLVED",
        "typed_family": resolved.typed_family,
        "action": resolved.action,
        "outcome": resolved.outcome,
        "reason_code": resolved.reason_code,
        "target_present": resolved.target_present,
        "operand_count": len(compiled.operands) if isinstance(compiled, CompiledMutationV2) else 0,
    }


def representation_transition_diagnostic(
    resolved: RepresentationTransitionOutcomeV2,
) -> dict[str, object]:
    """Return privacy-safe metadata for one dormant representation transition."""

    if not isinstance(resolved, RepresentationTransitionOutcomeV2):
        raise TypeError("resolved must be a RepresentationTransitionOutcomeV2")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "stage": "REPRESENTATION_TRANSITION",
        "from_state_type": "COUNT",
        "to_state_type": "SET",
        "status": resolved.status,
        "reason_code": resolved.reason_code,
        "revision_before": resolved.revision_before,
        "revision_after": resolved.revision_after,
        "history_written": resolved.history_written,
        "same_memory_id": resolved.same_memory_id,
    }


def compiler_diagnostic(
    value: GroundedSemanticIRV2 | CompiledSemanticIRV2,
    *,
    compile_status: str,
    reason_code: str | None = None,
) -> dict[str, object]:
    """Return privacy-safe dormant compiler metadata only."""

    if compile_status not in ("PASS", "FAIL"):
        raise ValueError("compile_status must be PASS or FAIL")
    if isinstance(value, CompiledMutationV2):
        intent = value.intent
        claim_shape = value.claim_shape
        typed_family = value.typed_family
        action = value.action
        operand_count = len(value.operands)
    elif isinstance(value, CompiledControlV2):
        intent = value.intent
        claim_shape = None
        typed_family = None
        action = None
        operand_count = 0
    elif isinstance(value, GroundedSemanticIRV2):
        intent = value.semantic_ir.intent
        claim_shape = (
            value.semantic_ir.claim.claim_shape
            if isinstance(value.semantic_ir, ChangeIRV2)
            else None
        )
        typed_family = None
        action = None
        operand_count = len(value.operands)
    else:
        raise TypeError("compiler diagnostics require dormant v2 objects")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "stage": "CLAIM_SHAPE_COMPILED",
        "intent": intent,
        "claim_shape": claim_shape,
        "typed_family": typed_family,
        "action": action,
        "operand_count": operand_count,
        "grounding": "PASS",
        "compile_status": compile_status,
        "reason_code": reason_code,
    }
