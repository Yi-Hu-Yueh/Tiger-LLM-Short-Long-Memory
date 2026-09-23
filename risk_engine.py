"""Dormant deterministic risk classifier for ontology action candidates.

Phase 4B is preview-only.  This module performs no provider call, state lookup,
routing, persistence, proposal creation, or commit.  Registry v1 keeps every
production auto-commit policy disabled, so benchmark-candidate metadata alone
can never authorize an automatic commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import ontology_compiler
import ontology_ir as ontology
import slot_registry as registry


PRODUCTION_ACTIVE = False


class RiskResult(str, Enum):
    AUTO_COMMIT_ALLOWED = "AUTO_COMMIT_ALLOWED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    NON_WRITE_OR_FAIL_CLOSED = "NON_WRITE_OR_FAIL_CLOSED"


class RiskReason(str, Enum):
    NON_EXECUTABLE = "NON_EXECUTABLE"
    DETERMINISTIC_NOOP = "DETERMINISTIC_NOOP"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    PRECONDITION_FAIL_CLOSED = "PRECONDITION_FAIL_CLOSED"
    UNKNOWN_SLOT = "UNKNOWN_SLOT"
    REGISTRY_SLOT_NOT_FOUND = "REGISTRY_SLOT_NOT_FOUND"
    REGISTRY_METADATA_MISMATCH = "REGISTRY_METADATA_MISMATCH"
    BENCHMARK_ONLY_NOT_PRODUCTION_ENABLED = "BENCHMARK_ONLY_NOT_PRODUCTION_ENABLED"
    STATIC_POLICY_REVIEW_REQUIRED = "STATIC_POLICY_REVIEW_REQUIRED"
    PRODUCTION_AUTO_COMMIT_DISABLED = "PRODUCTION_AUTO_COMMIT_DISABLED"
    OPERATION_NOT_RESOLVED = "OPERATION_NOT_RESOLVED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    ENTITY_OR_TARGET_NOT_RESOLVED = "ENTITY_OR_TARGET_NOT_RESOLVED"
    GROUNDING_NOT_EXACT = "GROUNDING_NOT_EXACT"
    DESTRUCTIVE_OPERATION = "DESTRUCTIVE_OPERATION"
    PRECONDITION_NOT_RESOLVED = "PRECONDITION_NOT_RESOLVED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    REPRESENTATION_TRANSITION = "REPRESENTATION_TRANSITION"
    STATE_FAMILY_TRANSITION = "STATE_FAMILY_TRANSITION"
    SEMANTIC_CORRECTION = "SEMANTIC_CORRECTION"
    ONTOLOGY_EXTENSION = "ONTOLOGY_EXTENSION"
    AUTHORITATIVE_STATE_CONFLICT = "AUTHORITATIVE_STATE_CONFLICT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNKNOWN_TARGET_OR_ENTITY = "UNKNOWN_TARGET_OR_ENTITY"
    ATOMIC_COMMIT_NOT_AVAILABLE = "ATOMIC_COMMIT_NOT_AVAILABLE"
    SLOT_VALIDATION_FAILED = "SLOT_VALIDATION_FAILED"
    ALL_LOW_RISK_CONDITIONS_PASS = "ALL_LOW_RISK_CONDITIONS_PASS"


@dataclass(frozen=True, slots=True)
class RiskPreconditionFacts:
    """Application-owned facts supplied only after authoritative preconditions."""

    resolved_operation: str
    typed_preconditions_pass: bool
    entity_target_unambiguous: bool
    representation_transition: bool
    state_family_transition: bool
    semantic_correction: bool
    ontology_extension: bool
    conflicting_authoritative_state: bool
    clarification_required: bool
    unknown_target_or_entity: bool
    atomic_commit_possible: bool
    slot_specific_validation_pass: bool
    precondition_outcome: str = "EXECUTABLE"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision: str
    reason_codes: tuple[str, ...]
    evaluated_slot_id: str | None
    evaluated_operation: str | None
    operation_candidates: tuple[str, ...]
    destructive: bool
    registry_version: int | None
    registry_risk_class: str | None
    registry_auto_commit_allowed: bool
    precondition_readiness: str
    required_conditions: tuple[str, ...]
    failed_conditions: tuple[str, ...]


_REQUIRED_CONDITIONS = (
    "EXECUTABLE_CANDIDATE",
    "REGISTRY_SLOT_VALID",
    "REGISTRY_VERSION_MATCH",
    "REGISTRY_METADATA_MATCH",
    "OPERATION_RESOLVED_AND_ALLOWED",
    "SLOT_OPERATION_PRODUCTION_AUTO_ENABLED",
    "ENTITY_TARGET_UNAMBIGUOUS",
    "EXACT_GROUNDING_PASS",
    "NON_DESTRUCTIVE",
    "NO_ONTOLOGY_EXTENSION",
    "NO_STATE_FAMILY_TRANSITION",
    "NO_COUNT_SET_REPRESENTATION_TRANSITION",
    "NO_SEMANTIC_CORRECTION",
    "TYPED_PRECONDITIONS_PASS",
    "NO_AUTHORITATIVE_STATE_CONFLICT",
    "NO_CLARIFICATION_REQUIRED",
    "NO_UNKNOWN_TARGET_OR_ENTITY",
    "ATOMIC_COMMIT_AVAILABLE",
    "SLOT_SPECIFIC_VALIDATION_PASS",
)


def _non_write(candidate: ontology_compiler.OntologyActionCandidate) -> RiskDecision:
    unknown = candidate.slot_id == registry.UNKNOWN_SLOT
    return RiskDecision(
        decision=RiskResult.NON_WRITE_OR_FAIL_CLOSED.value,
        reason_codes=((RiskReason.UNKNOWN_SLOT if unknown else RiskReason.NON_EXECUTABLE).value,),
        evaluated_slot_id=candidate.slot_id,
        evaluated_operation=None,
        operation_candidates=(),
        destructive=False,
        registry_version=None,
        registry_risk_class=None,
        registry_auto_commit_allowed=False,
        precondition_readiness="NOT_APPLICABLE",
        required_conditions=(),
        failed_conditions=(),
    )


def _resolved_non_write(
    candidate: ontology_compiler.OntologyActionCandidate,
    preconditions: RiskPreconditionFacts,
) -> RiskDecision:
    reasons = {
        "NOOP": RiskReason.DETERMINISTIC_NOOP,
        "TARGET_NOT_FOUND": RiskReason.TARGET_NOT_FOUND,
        "FAIL_CLOSED": RiskReason.PRECONDITION_FAIL_CLOSED,
    }
    reason = reasons[preconditions.precondition_outcome]
    definition = registry.get_slot(candidate.slot_id)
    return RiskDecision(
        decision=RiskResult.NON_WRITE_OR_FAIL_CLOSED.value,
        reason_codes=(reason.value,),
        evaluated_slot_id=candidate.slot_id,
        evaluated_operation=preconditions.resolved_operation or None,
        operation_candidates=candidate.operation_candidates,
        destructive=False,
        registry_version=None if definition is None else definition.registry_version,
        registry_risk_class=None if definition is None else definition.risk_class.value,
        registry_auto_commit_allowed=False if definition is None else definition.auto_commit_allowed,
        precondition_readiness="PASS",
        required_conditions=(),
        failed_conditions=(),
    )


def _grounding_exact(candidate: ontology_compiler.OntologyActionCandidate) -> bool:
    return bool(candidate.grounded_operands) and all(
        operand.resolution_status is ontology.LiteralResolutionStatus.RESOLVED_EXACT
        and operand.occurrence_count == 1
        and operand.source_start is not None
        and operand.source_end is not None
        and operand.exact_slice == operand.claimed_literal
        for operand in candidate.grounded_operands
    )


def evaluate_risk(
    candidate: ontology_compiler.OntologyActionCandidate,
    preconditions: RiskPreconditionFacts | None = None,
) -> RiskDecision:
    """Classify immutable application facts without routing or state access."""
    if not isinstance(candidate, ontology_compiler.OntologyActionCandidate):
        raise TypeError("Risk Engine accepts only OntologyActionCandidate")
    if preconditions is not None and not isinstance(preconditions, RiskPreconditionFacts):
        raise TypeError("preconditions must be RiskPreconditionFacts or None")
    if not candidate.executable:
        return _non_write(candidate)
    if preconditions is not None and preconditions.precondition_outcome in {
        "NOOP", "TARGET_NOT_FOUND", "FAIL_CLOSED"
    }:
        return _resolved_non_write(candidate, preconditions)

    reasons: list[str] = []
    failed: list[str] = []

    definition = registry.get_slot(candidate.slot_id)
    if definition is None:
        reasons.append(RiskReason.REGISTRY_SLOT_NOT_FOUND.value)
        failed.append("REGISTRY_SLOT_VALID")

    operation = (
        preconditions.resolved_operation
        if preconditions is not None
        else candidate.internal_operation
    )
    if operation is None:
        reasons.append(RiskReason.OPERATION_NOT_RESOLVED.value)
        failed.append("OPERATION_RESOLVED_AND_ALLOWED")

    if definition is not None:
        metadata_matches = (
            candidate.registry_version == definition.registry_version
            and candidate.semantic_key == definition.semantic_key
            and candidate.display_label == definition.display_label
            and candidate.typed_family == definition.typed_family.value
            and candidate.value_type == definition.value_type.value
            and candidate.entity_scope == definition.entity_scope.value
            and candidate.claim_shape in definition.allowed_claim_shapes
        )
        if candidate.registry_version != definition.registry_version:
            failed.append("REGISTRY_VERSION_MATCH")
        if not metadata_matches:
            reasons.append(RiskReason.REGISTRY_METADATA_MISMATCH.value)
            failed.append("REGISTRY_METADATA_MATCH")
        if operation is not None and operation not in definition.allowed_operations:
            reasons.append(RiskReason.UNSUPPORTED_OPERATION.value)
            failed.append("OPERATION_RESOLVED_AND_ALLOWED")

        if definition.risk_class is registry.RiskClass.BENCHMARK_AUTO_CANDIDATE:
            reasons.append(RiskReason.BENCHMARK_ONLY_NOT_PRODUCTION_ENABLED.value)
        else:
            reasons.append(RiskReason.STATIC_POLICY_REVIEW_REQUIRED.value)
        if not definition.auto_commit_allowed:
            reasons.append(RiskReason.PRODUCTION_AUTO_COMMIT_DISABLED.value)
            failed.append("SLOT_OPERATION_PRODUCTION_AUTO_ENABLED")

        if (
            definition.entity_scope is registry.EntityScope.ENTITY_SCOPED
            and candidate.entity_id is None
        ):
            reasons.append(RiskReason.ENTITY_OR_TARGET_NOT_RESOLVED.value)
            failed.append("ENTITY_TARGET_UNAMBIGUOUS")

    if not _grounding_exact(candidate):
        reasons.append(RiskReason.GROUNDING_NOT_EXACT.value)
        failed.append("EXACT_GROUNDING_PASS")
    if candidate.destructive or operation in {"REMOVE_ITEM", "DELETE_FIELD", "DELETE_MEMORY"}:
        reasons.append(RiskReason.DESTRUCTIVE_OPERATION.value)
        failed.append("NON_DESTRUCTIVE")

    if preconditions is None:
        reasons.append(RiskReason.PRECONDITION_NOT_RESOLVED.value)
        failed.extend(
            (
                "ENTITY_TARGET_UNAMBIGUOUS",
                "NO_ONTOLOGY_EXTENSION",
                "NO_STATE_FAMILY_TRANSITION",
                "NO_COUNT_SET_REPRESENTATION_TRANSITION",
                "NO_SEMANTIC_CORRECTION",
                "TYPED_PRECONDITIONS_PASS",
                "NO_AUTHORITATIVE_STATE_CONFLICT",
                "NO_CLARIFICATION_REQUIRED",
                "NO_UNKNOWN_TARGET_OR_ENTITY",
                "ATOMIC_COMMIT_AVAILABLE",
                "SLOT_SPECIFIC_VALIDATION_PASS",
            )
        )
        readiness = "NOT_PROVIDED"
    else:
        readiness = "PASS" if preconditions.typed_preconditions_pass else "FAIL"
        checks = (
            (not preconditions.typed_preconditions_pass, RiskReason.PRECONDITION_FAILED, "TYPED_PRECONDITIONS_PASS"),
            (not preconditions.entity_target_unambiguous, RiskReason.ENTITY_OR_TARGET_NOT_RESOLVED, "ENTITY_TARGET_UNAMBIGUOUS"),
            (preconditions.representation_transition, RiskReason.REPRESENTATION_TRANSITION, "NO_COUNT_SET_REPRESENTATION_TRANSITION"),
            (preconditions.state_family_transition, RiskReason.STATE_FAMILY_TRANSITION, "NO_STATE_FAMILY_TRANSITION"),
            (preconditions.semantic_correction, RiskReason.SEMANTIC_CORRECTION, "NO_SEMANTIC_CORRECTION"),
            (preconditions.ontology_extension, RiskReason.ONTOLOGY_EXTENSION, "NO_ONTOLOGY_EXTENSION"),
            (preconditions.conflicting_authoritative_state, RiskReason.AUTHORITATIVE_STATE_CONFLICT, "NO_AUTHORITATIVE_STATE_CONFLICT"),
            (preconditions.clarification_required, RiskReason.CLARIFICATION_REQUIRED, "NO_CLARIFICATION_REQUIRED"),
            (preconditions.unknown_target_or_entity, RiskReason.UNKNOWN_TARGET_OR_ENTITY, "NO_UNKNOWN_TARGET_OR_ENTITY"),
            (not preconditions.atomic_commit_possible, RiskReason.ATOMIC_COMMIT_NOT_AVAILABLE, "ATOMIC_COMMIT_AVAILABLE"),
            (not preconditions.slot_specific_validation_pass, RiskReason.SLOT_VALIDATION_FAILED, "SLOT_SPECIFIC_VALIDATION_PASS"),
        )
        for condition, reason, failed_condition in checks:
            if condition:
                reasons.append(reason.value)
                failed.append(failed_condition)

    failed_tuple = tuple(dict.fromkeys(failed))
    if not failed_tuple and definition is not None and definition.auto_commit_allowed:
        decision = RiskResult.AUTO_COMMIT_ALLOWED.value
        reasons = [RiskReason.ALL_LOW_RISK_CONDITIONS_PASS.value]
    else:
        decision = RiskResult.HUMAN_REVIEW_REQUIRED.value

    return RiskDecision(
        decision=decision,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evaluated_slot_id=candidate.slot_id,
        evaluated_operation=operation,
        operation_candidates=candidate.operation_candidates,
        destructive=candidate.destructive or operation in {"REMOVE_ITEM", "DELETE_FIELD", "DELETE_MEMORY"},
        registry_version=None if definition is None else definition.registry_version,
        registry_risk_class=None if definition is None else definition.risk_class.value,
        registry_auto_commit_allowed=False if definition is None else definition.auto_commit_allowed,
        precondition_readiness=readiness,
        required_conditions=_REQUIRED_CONDITIONS,
        failed_conditions=failed_tuple,
    )


def risk_preview(decision: RiskDecision) -> dict[str, object]:
    """Serialize only deterministic preview facts; never route the decision."""
    return {
        "preview_only": True,
        "decision": decision.decision,
        "reason_codes": list(decision.reason_codes),
        "slot_id": decision.evaluated_slot_id,
        "operation": decision.evaluated_operation,
        "operation_candidates": list(decision.operation_candidates),
        "destructive": decision.destructive,
        "registry_version": decision.registry_version,
        "registry_risk_class": decision.registry_risk_class,
        "registry_auto_commit_allowed": decision.registry_auto_commit_allowed,
        "precondition_readiness": decision.precondition_readiness,
        "required_conditions": list(decision.required_conditions),
        "failed_conditions": list(decision.failed_conditions),
        "routing_performed": False,
        "persistence_performed": False,
    }
