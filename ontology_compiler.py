"""Dormant deterministic compiler bridge for grounded ontology IR.

Phase 4A derives registry-owned typed action facts only.  It performs no
provider call, risk routing, authoritative-state lookup, persistence, proposal
creation, or commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import ontology_ir as ontology
import slot_registry as registry


PRODUCTION_ACTIVE = False


class CompilerReason(str, Enum):
    ACTION_CANDIDATE = "ACTION_CANDIDATE"
    NON_WRITE_INTENT = "NON_WRITE_INTENT"
    UNKNOWN_SLOT = "UNKNOWN_SLOT"
    INPUT_INVALID = "INPUT_INVALID"
    SLOT_INVALID = "SLOT_INVALID"
    CLAIM_FAMILY_MISMATCH = "CLAIM_FAMILY_MISMATCH"
    OPERAND_INVALID = "OPERAND_INVALID"
    OPERATION_INVALID = "OPERATION_INVALID"
    ENUMERATION_INVALID = "ENUMERATION_INVALID"


class OntologyCompilerError(ValueError):
    """Fail-closed compiler error with a deterministic reason code."""

    def __init__(self, reason: CompilerReason, message: str):
        super().__init__(message)
        self.reason_code = reason.value


@dataclass(frozen=True, slots=True)
class OntologyActionCandidate:
    """Immutable application-owned facts awaiting typed preconditions and risk."""

    executable: bool
    classification: str
    reason_code: str
    source_intent: str
    slot_id: str | None
    registry_version: int | None
    entity_id: str | None
    target_memory_id: str | None
    semantic_key: str | None
    display_label: str | None
    typed_family: str | None
    value_type: str | None
    entity_scope: str | None
    claim_shape: str | None
    grounded_operands: tuple[ontology.ResolvedLiteralOperand, ...]
    internal_operation: str | None
    operation_candidates: tuple[str, ...]
    canonical_arguments: tuple[tuple[str, object], ...]
    destructive: bool
    protocol_version: str = ontology.PROTOCOL_VERSION


_DESTRUCTIVE_OPERATIONS = frozenset(("REMOVE_ITEM", "DELETE_FIELD", "DELETE_MEMORY"))


def _error(reason: CompilerReason, message: str) -> None:
    raise OntologyCompilerError(reason, message)


def _arguments(**values: object) -> tuple[tuple[str, object], ...]:
    return tuple(values.items())


def arguments_dict(candidate: OntologyActionCandidate) -> dict[str, object]:
    """Return a display-only copy of immutable canonical arguments."""
    return dict(candidate.canonical_arguments)


def _metadata_fields(
    semantic_ir: ontology.ConstrainedOntologyIR,
) -> tuple[
    ontology.SlotMetadataProjection | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    metadata = ontology.project_slot_metadata(semantic_ir)
    if metadata is None:
        return None, None, None, None, None, None
    return (
        metadata,
        metadata.semantic_key,
        metadata.display_label,
        metadata.typed_family.value,
        metadata.value_type.value,
        metadata.entity_scope.value,
    )


def _non_executable(
    grounded: ontology.GroundedConstrainedIR,
    reason: CompilerReason,
) -> OntologyActionCandidate:
    semantic_ir = grounded.semantic_ir
    metadata, semantic_key, label, family, value_type, entity_scope = (
        _metadata_fields(semantic_ir)
    )
    slot_id = getattr(semantic_ir, "slot_id", None)
    if slot_id == registry.UNKNOWN_SLOT:
        slot_id = registry.UNKNOWN_SLOT
        metadata = None
        semantic_key = label = family = value_type = entity_scope = None
    return OntologyActionCandidate(
        executable=False,
        classification="NON_EXECUTABLE",
        reason_code=reason.value,
        source_intent=semantic_ir.intent,
        slot_id=slot_id,
        registry_version=None if metadata is None else metadata.registry_version,
        entity_id=getattr(semantic_ir, "entity_id", None),
        target_memory_id=getattr(semantic_ir, "target_memory_id", None),
        semantic_key=semantic_key,
        display_label=label,
        typed_family=family,
        value_type=value_type,
        entity_scope=entity_scope,
        claim_shape=getattr(semantic_ir, "claim_shape", None),
        grounded_operands=(),
        internal_operation=None,
        operation_candidates=(),
        canonical_arguments=(),
        destructive=False,
    )


def _validate_grounded_operands(
    grounded: ontology.GroundedConstrainedIR,
) -> dict[str, ontology.ResolvedLiteralOperand]:
    semantic_ir = grounded.semantic_ir
    expected = semantic_ir.operands if isinstance(semantic_ir, ontology.ConstrainedChangeIR) else ()
    expected_roles = tuple(role for role, _ in expected)
    actual_roles = tuple(operand.role for operand in grounded.operands)
    if actual_roles != expected_roles:
        _error(CompilerReason.OPERAND_INVALID, "grounded operands are incomplete")
    resolved: dict[str, ontology.ResolvedLiteralOperand] = {}
    for operand in grounded.operands:
        if (
            operand.resolution_status
            is not ontology.LiteralResolutionStatus.RESOLVED_EXACT
            or operand.occurrence_count != 1
            or operand.source_start is None
            or operand.source_end is None
            or operand.exact_slice is None
            or operand.exact_slice != operand.claimed_literal
        ):
            _error(CompilerReason.OPERAND_INVALID, "operand is not uniquely exact-grounded")
        resolved[operand.role] = operand
    return resolved


def _operation_boundary(
    target_memory_id: str | None,
    create_operation: str,
    existing_operation: str,
) -> tuple[str | None, tuple[str, ...]]:
    if target_memory_id is not None:
        return existing_operation, (existing_operation,)
    return None, (create_operation, existing_operation)


def _compile_change(
    grounded: ontology.GroundedConstrainedIR,
) -> OntologyActionCandidate:
    semantic_ir = grounded.semantic_ir
    if not isinstance(semantic_ir, ontology.ConstrainedChangeIR):
        _error(CompilerReason.INPUT_INVALID, "CHANGE compiler input is invalid")
    metadata = ontology.project_slot_metadata(semantic_ir)
    if metadata is None:
        _error(CompilerReason.SLOT_INVALID, "known-slot CHANGE requires Registry v1 metadata")
    if semantic_ir.claim_shape not in metadata.allowed_claim_shapes:
        _error(CompilerReason.CLAIM_FAMILY_MISMATCH, "claim shape conflicts with registry family")
    if (
        metadata.entity_scope is registry.EntityScope.ENTITY_SCOPED
        and semantic_ir.entity_id is None
    ):
        _error(CompilerReason.INPUT_INVALID, "entity-scoped action requires supplied entity_id")

    operands = _validate_grounded_operands(grounded)
    operation: str | None
    operation_candidates: tuple[str, ...]
    arguments: tuple[tuple[str, object], ...]

    if semantic_ir.claim_shape == registry.SCALAR_ASSERTION:
        operation, operation_candidates = _operation_boundary(
            semantic_ir.target_memory_id, "CREATE_SCALAR", "SET_VALUE"
        )
        arguments = _arguments(value=operands["value"].exact_slice)
    elif semantic_ir.claim_shape == registry.CARDINALITY_ASSERTION:
        count = operands["count"]
        if (
            not count.has_canonical_value
            or isinstance(count.canonical_value, bool)
            or not isinstance(count.canonical_value, int)
        ):
            _error(CompilerReason.OPERAND_INVALID, "Count requires model-semantic integer")
        operation, operation_candidates = _operation_boundary(
            semantic_ir.target_memory_id, "CREATE_COUNT", "SET_COUNT"
        )
        arguments = _arguments(value=count.canonical_value)
    elif semantic_ir.claim_shape == registry.ENUMERATION_ASSERTION:
        item_roles = tuple(
            role for role in operands if role.startswith("items[")
        )
        items = tuple(operands[role].exact_slice for role in item_roles)
        if not items or len(set(items)) != len(items):
            _error(CompilerReason.ENUMERATION_INVALID, "Set items must be unique")
        asserted = operands.get("asserted_count")
        if asserted is not None and (
            not asserted.has_canonical_value
            or asserted.canonical_value != len(items)
        ):
            _error(
                CompilerReason.ENUMERATION_INVALID,
                "asserted Count conflicts with grounded Set membership",
            )
        operation, operation_candidates = _operation_boundary(
            semantic_ir.target_memory_id, "CREATE_SET", "REPLACE_SET"
        )
        arguments = _arguments(items=items)
    elif semantic_ir.claim_shape == registry.MEMBERSHIP_ASSERTION:
        operation = "ADD_ITEM" if semantic_ir.membership_action == "ADD" else "REMOVE_ITEM"
        operation_candidates = (operation,)
        arguments = _arguments(item=operands["item"].exact_slice)
    elif semantic_ir.claim_shape == registry.FIELD_ASSERTION:
        operation, operation_candidates = _operation_boundary(
            semantic_ir.target_memory_id, "CREATE_RECORD", "SET_FIELD"
        )
        arguments = _arguments(
            field=metadata.slot_id,
            value=operands["value"].exact_slice,
        )
    else:
        _error(CompilerReason.CLAIM_FAMILY_MISMATCH, "claim shape has no mapping")

    if not set(operation_candidates).issubset(metadata.allowed_operations):
        _error(CompilerReason.OPERATION_INVALID, "derived operation is not registry-allowed")
    destructive = operation is not None and operation in _DESTRUCTIVE_OPERATIONS
    return OntologyActionCandidate(
        executable=True,
        classification="ACTION_CANDIDATE",
        reason_code=CompilerReason.ACTION_CANDIDATE.value,
        source_intent=semantic_ir.intent,
        slot_id=metadata.slot_id,
        registry_version=metadata.registry_version,
        entity_id=semantic_ir.entity_id,
        target_memory_id=semantic_ir.target_memory_id,
        semantic_key=metadata.semantic_key,
        display_label=metadata.display_label,
        typed_family=metadata.typed_family.value,
        value_type=metadata.value_type.value,
        entity_scope=metadata.entity_scope.value,
        claim_shape=semantic_ir.claim_shape,
        grounded_operands=grounded.operands,
        internal_operation=operation,
        operation_candidates=operation_candidates,
        canonical_arguments=arguments,
        destructive=destructive,
    )


def compile_ontology_action(value: object) -> OntologyActionCandidate:
    """Compile only validated grounded ontology IR into dormant typed facts."""
    if not isinstance(value, ontology.GroundedConstrainedIR):
        _error(
            CompilerReason.INPUT_INVALID,
            "ontology compiler accepts only GroundedConstrainedIR",
        )
    semantic_ir = value.semantic_ir
    if isinstance(semantic_ir, ontology.ConstrainedChangeIR):
        return _compile_change(value)
    if getattr(semantic_ir, "slot_id", None) == registry.UNKNOWN_SLOT:
        return _non_executable(value, CompilerReason.UNKNOWN_SLOT)
    return _non_executable(value, CompilerReason.NON_WRITE_INTENT)


def compiler_preview(candidate: OntologyActionCandidate) -> dict[str, object]:
    """Serialize safe preview fields without risk or persistence output."""
    return {
        "executable": candidate.executable,
        "classification": candidate.classification,
        "reason_code": candidate.reason_code,
        "source_intent": candidate.source_intent,
        "slot_id": candidate.slot_id,
        "registry_version": candidate.registry_version,
        "entity_id": candidate.entity_id,
        "target_memory_id": candidate.target_memory_id,
        "semantic_key": candidate.semantic_key,
        "display_label": candidate.display_label,
        "typed_family": candidate.typed_family,
        "value_type": candidate.value_type,
        "entity_scope": candidate.entity_scope,
        "claim_shape": candidate.claim_shape,
        "internal_operation": candidate.internal_operation,
        "operation_candidates": list(candidate.operation_candidates),
        "canonical_arguments": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in candidate.canonical_arguments
        },
        "destructive": candidate.destructive,
        "grounded_values_used": [
            {
                "role": operand.role,
                "claimed_literal": operand.claimed_literal,
                "source_start": operand.source_start,
                "source_end": operand.source_end,
                "exact_slice": operand.exact_slice,
                "occurrence_count": operand.occurrence_count,
                "resolution_status": operand.resolution_status.value,
                "canonical_value": (
                    operand.canonical_value if operand.has_canonical_value else None
                ),
                "canonical_value_ownership": (
                    "MODEL-SEMANTIC" if operand.has_canonical_value else None
                ),
            }
            for operand in candidate.grounded_operands
        ],
    }
