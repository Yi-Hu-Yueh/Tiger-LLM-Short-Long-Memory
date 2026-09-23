"""Evaluation-only scalar semantic plans; never an authorization to write."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    CREATE_SCALAR = "CREATE_SCALAR"
    UPDATE_SCALAR = "UPDATE_SCALAR"
    REASSERT_SCALAR = "REASSERT_SCALAR"
    READ_CURRENT = "READ_CURRENT"
    READ_PREVIOUS = "READ_PREVIOUS"
    READ_TIMELINE = "READ_TIMELINE"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNSUPPORTED = "UNSUPPORTED"


class TemporalRelation(StrEnum):
    CURRENT = "CURRENT"
    PREVIOUS = "PREVIOUS"
    TIMELINE = "TIMELINE"
    NONE = "NONE"


class Ambiguity(StrEnum):
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"
    MULTIPLE = "MULTIPLE"


class ReasonCode(StrEnum):
    NONE = "NONE"
    GOVERNANCE_REQUIRED = "GOVERNANCE_REQUIRED"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    MULTIPLE_TARGETS = "MULTIPLE_TARGETS"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    MIXED_READ = "MIXED_READ"


@dataclass(frozen=True, slots=True)
class ScalarCandidate:
    memory_id: str
    entity_id: str | None
    entity_name: str | None
    semantic_key: str
    display_label: str
    current_value: str


@dataclass(frozen=True, slots=True)
class SemanticPlan:
    intent: Intent
    target_memory_id: str | None
    target_entity_id: str | None
    semantic_key: str | None
    value_candidate: str | None
    source_start: int | None
    source_end: int | None
    temporal_relation: TemporalRelation
    ambiguity: Ambiguity
    reason_code: ReasonCode
    mutation_count: int = 0


MODEL_FIELDS = frozenset((
    "intent", "target_memory_id", "claimed_literal", "temporal_relation",
    "ambiguity", "reason_code",
))
