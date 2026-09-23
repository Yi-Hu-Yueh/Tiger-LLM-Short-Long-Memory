"""Pure Architecture B precondition adapter for dormant ontology previews.

The adapter consumes an immutable ontology action candidate plus an explicit
server-owned synthetic Current fixture.  It reuses ``app.resolve_typed_precondition``
and never reads SQLite, routes a decision, creates a proposal, or persists state.
"""

from __future__ import annotations

from dataclasses import dataclass

import ontology_compiler
import risk_engine


PRODUCTION_ACTIVE = False
FIXTURE_SOURCE = "SERVER_OWNED_SYNTHETIC_TEST_STATE"


FrozenState = tuple[tuple[str, object], ...]


def _architecture_b():
    # Lazy import avoids app -> diagnostic -> adapter -> partially initialized app.
    import app
    return app


def freeze_state(state: dict[str, object]) -> FrozenState:
    if set(state) == {"items"}:
        return (("items", tuple(state["items"])),)
    if set(state) == {"fields"}:
        return (("fields", tuple(sorted(dict(state["fields"]).items()))),)
    return tuple(state.items())


def state_dict(state: FrozenState | None) -> dict[str, object] | None:
    if state is None:
        return None
    result = dict(state)
    if "items" in result:
        result["items"] = list(result["items"])
    if "fields" in result:
        result["fields"] = dict(result["fields"])
    return result


@dataclass(frozen=True, slots=True)
class AuthoritativeTypedState:
    memory_id: str
    slot_id: str
    registry_version: int
    entity_id: str | None
    typed_family: str
    canonical_state: FrozenState


@dataclass(frozen=True, slots=True)
class OntologyPreconditionResult:
    fixture_source: str
    ready: bool
    outcome: str
    changed: bool
    resolved_operation: str | None
    target_memory_id: str | None
    current_exists: bool
    current_typed_family: str | None
    current_state: FrozenState | None
    resulting_state: FrozenState | None
    noop: bool
    target_not_found: bool
    conflict: bool
    representation_transition: bool
    state_family_transition: bool
    semantic_correction: bool
    atomic_commit_available: bool
    slot_specific_validation_pass: bool
    destructive: bool
    reason_codes: tuple[str, ...]


def authoritative_state(
    memory_id: str,
    slot_id: str,
    registry_version: int,
    entity_id: str | None,
    typed_family: str,
    canonical_state: dict[str, object],
) -> AuthoritativeTypedState:
    """Construct one immutable server-owned synthetic authoritative fixture."""
    return AuthoritativeTypedState(
        memory_id,
        slot_id,
        registry_version,
        entity_id,
        typed_family,
        freeze_state(canonical_state),
    )


def _arguments(candidate: ontology_compiler.OntologyActionCandidate, operation: str) -> dict[str, object]:
    arguments = ontology_compiler.arguments_dict(candidate)
    if operation in ("CREATE_SET", "REPLACE_SET"):
        return {"items": list(arguments["items"])}
    if operation == "CREATE_RECORD":
        return {"fields": {arguments["field"]: arguments["value"]}}
    if operation == "DELETE_FIELD":
        return {"field": arguments["field"]}
    if operation == "DELETE_MEMORY":
        return {}
    return arguments


def canonical_arguments_for_operation(
    candidate: ontology_compiler.OntologyActionCandidate, operation: str
) -> dict[str, object]:
    """Return a fresh canonical argument payload for one resolved operation."""
    if not isinstance(candidate, ontology_compiler.OntologyActionCandidate):
        raise TypeError("candidate must be OntologyActionCandidate")
    if not isinstance(operation, str) or not operation:
        raise TypeError("operation must be non-empty text")
    return _arguments(candidate, operation)


def _result(
    *,
    ready: bool,
    outcome: str,
    changed: bool,
    operation: str | None,
    target_memory_id: str | None,
    current: AuthoritativeTypedState | None,
    resulting_state: dict[str, object] | None,
    conflict: bool = False,
    representation_transition: bool = False,
    state_family_transition: bool = False,
    atomic_commit_available: bool = False,
    slot_specific_validation_pass: bool = False,
    destructive: bool = False,
    reason_codes: tuple[str, ...] = (),
) -> OntologyPreconditionResult:
    return OntologyPreconditionResult(
        fixture_source=FIXTURE_SOURCE,
        ready=ready,
        outcome=outcome,
        changed=changed,
        resolved_operation=operation,
        target_memory_id=target_memory_id,
        current_exists=current is not None,
        current_typed_family=None if current is None else current.typed_family,
        current_state=None if current is None else current.canonical_state,
        resulting_state=None if resulting_state is None else freeze_state(resulting_state),
        noop=outcome == "NOOP",
        target_not_found=outcome == "TARGET_NOT_FOUND",
        conflict=conflict,
        representation_transition=representation_transition,
        state_family_transition=state_family_transition,
        semantic_correction=False,
        atomic_commit_available=atomic_commit_available,
        slot_specific_validation_pass=slot_specific_validation_pass,
        destructive=destructive,
        reason_codes=reason_codes,
    )


def resolve_authoritative_precondition(
    candidate: ontology_compiler.OntologyActionCandidate,
    current: AuthoritativeTypedState | None,
) -> OntologyPreconditionResult:
    """Resolve CREATE/mutation/NOOP controls using existing Architecture B rules."""
    if not isinstance(candidate, ontology_compiler.OntologyActionCandidate):
        raise TypeError("candidate must be OntologyActionCandidate")
    if current is not None and not isinstance(current, AuthoritativeTypedState):
        raise TypeError("current must be AuthoritativeTypedState or None")
    if not candidate.executable:
        return _result(
            ready=True,
            outcome="NON_WRITE",
            changed=False,
            operation=None,
            target_memory_id=None,
            current=None,
            resulting_state=None,
            reason_codes=("NON_EXECUTABLE",),
        )

    count_to_set_pair = bool(
        current is not None
        and current.typed_family == "count"
        and candidate.typed_family == "set"
        and candidate.claim_shape == "ENUMERATION_ASSERTION"
        and current.entity_id == candidate.entity_id
    )
    if current is not None and (
        (current.slot_id != candidate.slot_id and not count_to_set_pair)
        or current.registry_version != candidate.registry_version
        or current.entity_id != candidate.entity_id
        or (
            candidate.target_memory_id is not None
            and candidate.target_memory_id != current.memory_id
        )
    ):
        return _result(
            ready=False,
            outcome="FAIL_CLOSED",
            changed=False,
            operation=None,
            target_memory_id=current.memory_id,
            current=current,
            resulting_state=None,
            conflict=True,
            reason_codes=("AUTHORITATIVE_TARGET_MISMATCH",),
        )

    if current is None:
        create_operations = tuple(
            operation for operation in candidate.operation_candidates
            if operation.startswith("CREATE_")
        )
        if len(create_operations) != 1:
            return _result(
                ready=False,
                outcome="FAIL_CLOSED",
                changed=False,
                operation=None,
                target_memory_id=None,
                current=None,
                resulting_state=None,
                conflict=True,
                reason_codes=("CREATE_OPERATION_UNRESOLVED",),
            )
        operation = create_operations[0]
        target_memory_id = None
    else:
        if current.typed_family != candidate.typed_family:
            if (
                current.typed_family == "count"
                and candidate.typed_family == "set"
                and candidate.claim_shape == "ENUMERATION_ASSERTION"
            ):
                try:
                    architecture_b = _architecture_b()
                    architecture_b.validate_typed_state(
                        "count", state_dict(current.canonical_state)
                    )
                    resulting = architecture_b.validate_typed_state(
                        "set", _arguments(candidate, "REPLACE_SET")
                    )
                except (architecture_b.AppError, KeyError, TypeError, ValueError):
                    return _result(
                        ready=False,
                        outcome="FAIL_CLOSED",
                        changed=False,
                        operation="REPLACE_SET",
                        target_memory_id=current.memory_id,
                        current=current,
                        resulting_state=None,
                        conflict=True,
                        reason_codes=("REPRESENTATION_TRANSITION_INVALID",),
                    )
                return _result(
                    ready=True,
                    outcome="REPRESENTATION_TRANSITION_REQUIRED",
                    changed=True,
                    operation="REPLACE_SET",
                    target_memory_id=current.memory_id,
                    current=current,
                    resulting_state=resulting,
                    representation_transition=True,
                    atomic_commit_available=True,
                    slot_specific_validation_pass=True,
                    reason_codes=("COUNT_TO_SET_REPRESENTATION_TRANSITION",),
                )
            return _result(
                ready=True,
                outcome="STATE_FAMILY_TRANSITION_REQUIRED",
                changed=True,
                operation=None,
                target_memory_id=current.memory_id,
                current=current,
                resulting_state=None,
                state_family_transition=True,
                atomic_commit_available=True,
                slot_specific_validation_pass=True,
                reason_codes=("STATE_FAMILY_TRANSITION",),
            )
        if candidate.internal_operation is not None:
            operation = candidate.internal_operation
        else:
            existing_operations = tuple(
                operation for operation in candidate.operation_candidates
                if not operation.startswith("CREATE_")
            )
            if len(existing_operations) != 1:
                return _result(
                    ready=False,
                    outcome="FAIL_CLOSED",
                    changed=False,
                    operation=None,
                    target_memory_id=current.memory_id,
                    current=current,
                    resulting_state=None,
                    conflict=True,
                    reason_codes=("MUTATION_OPERATION_UNRESOLVED",),
                )
            operation = existing_operations[0]
        target_memory_id = current.memory_id

    try:
        architecture_b = _architecture_b()
        arguments = _arguments(candidate, operation)
        decision = architecture_b.TypedDecision(
            kind="PROPOSE" if operation in architecture_b.TYPED_DESTRUCTIVE_OPERATIONS else "MUTATE",
            state_type=candidate.typed_family,
            memory_id=target_memory_id,
            operation=operation,
            arguments=arguments,
            evidence="EXPLICIT",
            current_memory_ids=(),
            history_ids=(),
            unknown=False,
            clarification=None,
            semantic_key=candidate.semantic_key if current is None else None,
            display_label=candidate.display_label if current is None else None,
            clarification_id=None,
        )
        current_state = None if current is None else state_dict(current.canonical_state)
        resolved = architecture_b.resolve_typed_precondition(decision, current_state)
    except (architecture_b.AppError, KeyError, TypeError, ValueError):
        return _result(
            ready=False,
            outcome="FAIL_CLOSED",
            changed=False,
            operation=operation,
            target_memory_id=target_memory_id,
            current=current,
            resulting_state=None,
            conflict=True,
            reason_codes=("ARCHITECTURE_B_PRECONDITION_INVALID",),
        )

    transition = resolved.transition
    changed = transition is not None and transition.changed
    destructive = operation in architecture_b.TYPED_DESTRUCTIVE_OPERATIONS
    return _result(
        ready=True,
        outcome=resolved.outcome,
        changed=changed,
        operation=operation,
        target_memory_id=target_memory_id,
        current=current,
        resulting_state=None if transition is None else transition.next_state,
        atomic_commit_available=resolved.outcome == "EXECUTABLE",
        slot_specific_validation_pass=True,
        destructive=destructive,
        reason_codes=(resolved.reason_code,),
    )


def risk_facts(result: OntologyPreconditionResult) -> risk_engine.RiskPreconditionFacts:
    """Adapt the immutable precondition result to the existing Risk Engine input."""
    if not isinstance(result, OntologyPreconditionResult):
        raise TypeError("result must be OntologyPreconditionResult")
    return risk_engine.RiskPreconditionFacts(
        resolved_operation=result.resolved_operation or "",
        typed_preconditions_pass=result.ready and result.outcome in {
            "EXECUTABLE", "NOOP", "TARGET_NOT_FOUND",
            "REPRESENTATION_TRANSITION_REQUIRED", "STATE_FAMILY_TRANSITION_REQUIRED",
        },
        entity_target_unambiguous=not result.conflict,
        representation_transition=result.representation_transition,
        state_family_transition=result.state_family_transition,
        semantic_correction=result.semantic_correction,
        ontology_extension=False,
        conflicting_authoritative_state=result.conflict,
        clarification_required=False,
        unknown_target_or_entity=result.conflict,
        atomic_commit_possible=result.atomic_commit_available,
        slot_specific_validation_pass=result.slot_specific_validation_pass,
        precondition_outcome=result.outcome,
    )


def precondition_preview(result: OntologyPreconditionResult) -> dict[str, object]:
    """Serialize synthetic state explicitly as test-only, never user memory."""
    return {
        "fixture_source": result.fixture_source,
        "precondition_readiness": "PASS" if result.ready else "FAIL",
        "outcome": result.outcome,
        "current_exists": result.current_exists,
        "target_memory_id": result.target_memory_id,
        "current_typed_family": result.current_typed_family,
        "current_canonical_state": state_dict(result.current_state),
        "resolved_operation": result.resolved_operation,
        "changed": result.changed,
        "noop": result.noop,
        "target_not_found": result.target_not_found,
        "conflict": result.conflict,
        "representation_transition": result.representation_transition,
        "state_family_transition": result.state_family_transition,
        "semantic_correction": result.semantic_correction,
        "atomic_commit_available": result.atomic_commit_available,
        "slot_specific_validation_pass": result.slot_specific_validation_pass,
        "destructive": result.destructive,
        "resulting_canonical_state": state_dict(result.resulting_state),
        "reason_codes": list(result.reason_codes),
        "routing_performed": False,
        "persistence_performed": False,
    }
