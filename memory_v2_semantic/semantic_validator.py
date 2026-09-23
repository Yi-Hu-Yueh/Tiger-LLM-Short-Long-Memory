"""Strict, rejection-only validation of V2-1A dry-run scalar plans."""

from __future__ import annotations

import json

from .semantic_models import (
    Ambiguity, Intent, MODEL_FIELDS, ReasonCode, ScalarCandidate, SemanticPlan,
    TemporalRelation,
)


class PlanValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_TARGETED = frozenset((
    Intent.UPDATE_SCALAR, Intent.REASSERT_SCALAR, Intent.READ_CURRENT,
    Intent.READ_PREVIOUS, Intent.READ_TIMELINE,
))
_CHANGED = frozenset((Intent.UPDATE_SCALAR, Intent.REASSERT_SCALAR))
_TEMPORAL = {
    Intent.READ_CURRENT: TemporalRelation.CURRENT,
    Intent.READ_PREVIOUS: TemporalRelation.PREVIOUS,
    Intent.READ_TIMELINE: TemporalRelation.TIMELINE,
}
_NON_TARGET_REASON = {
    Intent.UNKNOWN_TARGET: (Ambiguity.UNKNOWN, ReasonCode.TARGET_NOT_FOUND),
    Intent.AMBIGUOUS_TARGET: (Ambiguity.MULTIPLE, ReasonCode.MULTIPLE_TARGETS),
}


def _enum(cls: type, value: object, code: str):
    if not isinstance(value, str):
        raise PlanValidationError(code)
    try:
        return cls(value)
    except ValueError as exc:
        raise PlanValidationError(code) from exc


def _unique_span(message: str, literal: str) -> tuple[int, int]:
    if not literal:
        raise PlanValidationError("LITERAL_EMPTY")
    start = message.find(literal)
    if start < 0:
        raise PlanValidationError("LITERAL_NOT_FOUND")
    if message.find(literal, start + 1) >= 0:
        raise PlanValidationError("LITERAL_AMBIGUOUS")
    return start, start + len(literal)


def validate_plan(raw: str | dict[str, object], message: str,
                  candidates: tuple[ScalarCandidate, ...]) -> SemanticPlan:
    """No SQLite access; candidate metadata comes only from the supplied catalog."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise PlanValidationError("INVALID_JSON") from exc
    if not isinstance(data, dict) or set(data) != MODEL_FIELDS:
        raise PlanValidationError("FIELD_SET_INVALID")
    intent = _enum(Intent, data["intent"], "INTENT_INVALID")
    temporal = _enum(TemporalRelation, data["temporal_relation"], "TEMPORAL_INVALID")
    ambiguity = _enum(Ambiguity, data["ambiguity"], "AMBIGUITY_INVALID")
    reason = _enum(ReasonCode, data["reason_code"], "REASON_INVALID")
    target_id = data["target_memory_id"]
    literal = data["claimed_literal"]
    if target_id is not None and (not isinstance(target_id, str) or not target_id):
        raise PlanValidationError("TARGET_ID_INVALID")
    if literal is not None and (not isinstance(literal, str) or not literal):
        raise PlanValidationError("LITERAL_INVALID")
    catalog = {c.memory_id: c for c in candidates}
    if len(catalog) != len(candidates):
        raise PlanValidationError("CATALOG_DUPLICATE_ID")
    if intent is Intent.CREATE_SCALAR:
        # The synthetic development domains are not in Registry v1. This
        # evaluation protocol cannot authorize a model-created canonical slot.
        raise PlanValidationError("GOVERNANCE_REQUIRED")
    if intent in _TARGETED:
        if target_id not in catalog:
            raise PlanValidationError("TARGET_NOT_OFFERED")
        if ambiguity is not Ambiguity.NONE or reason is not ReasonCode.NONE:
            raise PlanValidationError("TARGET_CONTROL_INVALID")
        if temporal is not _TEMPORAL.get(intent, TemporalRelation.NONE):
            raise PlanValidationError("TEMPORAL_MISMATCH")
        if intent in _CHANGED:
            if literal is None:
                raise PlanValidationError("LITERAL_REQUIRED")
            start, end = _unique_span(message, literal)
        else:
            if literal is not None:
                raise PlanValidationError("READ_LITERAL_FORBIDDEN")
            start = end = None
        chosen = catalog[target_id]
        return SemanticPlan(intent, target_id, chosen.entity_id, chosen.semantic_key,
                            literal, start, end, temporal, ambiguity, reason)
    if target_id is not None or temporal is not TemporalRelation.NONE:
        raise PlanValidationError("NON_TARGET_CONTROL_INVALID")
    if intent in _NON_TARGET_REASON:
        expected_ambiguity, expected_reason = _NON_TARGET_REASON[intent]
        if ambiguity is not expected_ambiguity or reason is not expected_reason:
            raise PlanValidationError("NON_TARGET_REASON_INVALID")
        if literal is not None:
            raise PlanValidationError("NON_TARGET_LITERAL_FORBIDDEN")
    elif intent is Intent.UNSUPPORTED:
        if ambiguity is not Ambiguity.NONE or reason not in (
            ReasonCode.GOVERNANCE_REQUIRED, ReasonCode.OUT_OF_SCOPE, ReasonCode.MIXED_READ
        ):
            raise PlanValidationError("UNSUPPORTED_REASON_INVALID")
        if literal is not None:
            start, end = _unique_span(message, literal)
        else:
            start = end = None
    else:
        raise PlanValidationError("INTENT_UNSUPPORTED")
    if intent in _NON_TARGET_REASON:
        start = end = None
    return SemanticPlan(intent, None, None, None, literal, start, end,
                        temporal, ambiguity, reason)
