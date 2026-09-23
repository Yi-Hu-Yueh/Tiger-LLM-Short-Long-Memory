"""HR-P2 production ontology shadow over the real Normal Chat snapshot.

The shadow makes one constrained provider call against server-owned Registry-v1
and real ontology-managed Current candidates, then executes the pure ontology
validation/compiler/precondition/risk/routing pipeline.  It never creates a
proposal and never mutates Current, History, revision, session messages, or the
product routing configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from typing import Callable, Protocol

import ontology_compiler
import ontology_ir as ontology
import ontology_preconditions
import ontology_routing
import risk_engine
import slot_registry as registry


SHADOW_ENDPOINT = "/api/production-ontology-shadow"
PRODUCTION_ACTIVE = False
PRODUCT_MODE = "HUMAN_REVIEWED_MEMORY_ASSISTANT"
SHADOW_SOURCE = "REAL_NORMAL_CHAT_CURRENT"
RESIDUAL_RISK_WARNING = (
    "Exact grounding proves provenance, not semantic correctness. "
    "HR-P2 is shadow-only: no proposal, no commit, no mutation."
)


class ShadowInputError(ValueError):
    """Invalid product-shadow input or state."""


class ShadowProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], api_key: str) -> str: ...


SnapshotLoader = Callable[[str, str], dict[str, object]]


@dataclass(frozen=True, slots=True)
class ShadowCandidateContext:
    entity_candidates: tuple[str, ...]
    target_memory_candidates: tuple[str, ...]
    current_candidates: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ProductionReviewTicket:
    token: str
    user_id: str
    session_id: str
    question: str
    base_revision: int
    snapshot_digest: str
    route_plan: ontology_routing.OntologyRoutePlan


def _candidate_context(snapshot: dict[str, object]) -> ShadowCandidateContext:
    rows = tuple(snapshot.get("ontology_current", ()))
    entity_ids = sorted(
        {
            str(row["entity_id"])
            for row in rows
            if isinstance(row, dict) and row.get("entity_id") is not None
        }
    )
    target_ids = tuple(
        str(row["memory_id"])
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("memory_id"), str)
    )
    current = tuple(
        {
            "memory_id": row["memory_id"],
            "slot_id": row["slot_id"],
            "registry_version": row["registry_version"],
            "entity_id": row["entity_id"],
            "typed_family": row["typed_family"],
            "display_label": row["display_label"],
            "canonical_state": row["canonical_state"],
        }
        for row in rows
    )
    return ShadowCandidateContext(tuple(entity_ids), target_ids, current)


def _prompt(message: str, context: ShadowCandidateContext) -> list[dict[str, str]]:
    slot_ids = (*registry.REGISTRY_V1_SLOT_IDS, registry.UNKNOWN_SLOT)
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
        "slot_contracts": slot_contracts,
        "entity_candidates": context.entity_candidates,
        "target_memory_candidates": context.target_memory_candidates,
        "current_ontology_candidates": context.current_candidates,
    }
    system = (
        "You are the HR-P2 production ontology shadow semantic extractor. "
        "Return exactly one JSON object and no markdown. This is shadow-only; you cannot commit memory.\n"
        "Select slot_id only from allowed_slot_ids. UNKNOWN_SLOT is explicit and always available.\n"
        "For a known CHANGE, claim_shape MUST be one of slot_contracts[slot_id].allowed_claim_shapes.\n"
        "Select entity_id and target_memory_id only from the supplied candidate arrays; never invent IDs. "
        "When current_ontology_candidates contains an exact existing slot/entity target relevant to the user's change, "
        "select its target_memory_id. For a singleton slot with no ontology-managed current target, target_memory_id is null.\n"
        "For UNKNOWN_SLOT, safely use CLARIFY+UNKNOWN_SLOT with ambiguity=UNKNOWN_SLOT and question, "
        "or ABSTAIN+UNKNOWN_SLOT.\n"
        "CHANGE scalar/field fields: protocol_version,intent,slot_id,claim_shape,value, plus candidate IDs only when applicable.\n"
        "CHANGE cardinality fields: protocol_version,intent,slot_id,claim_shape,count, plus required candidate entity_id. "
        "count contains claimed_literal and integer canonical_value.\n"
        "CHANGE enumeration fields: protocol_version,intent,slot_id,claim_shape,items, plus candidate entity_id and optional asserted_count.\n"
        "CHANGE membership fields: protocol_version,intent,slot_id,claim_shape,membership_action,item, plus candidate entity_id.\n"
        "Each literal operand contains claimed_literal copied verbatim from the current user message. "
        "Do not emit source offsets; the application resolves them.\n"
        "Do not emit semantic_key, display_label, typed_family, value_type, risk_class, auto_commit_allowed, "
        "internal operation, revision, history, proposal policy, deterministic reply, confidence, or explanations.\n"
        "SERVER_OWNED_CONTRACT_JSON:\n"
        + json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": message}]


def _safe_raw(value: object) -> object:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def _model_selection(value: ontology.ConstrainedOntologyIR) -> dict[str, object]:
    result: dict[str, object] = {"protocol_version": value.protocol_version, "intent": value.intent}
    for name in ("slot_id", "claim_shape", "entity_id", "target_memory_id", "membership_action", "unknown", "ambiguity", "question", "reply"):
        if hasattr(value, name):
            item = getattr(value, name)
            result[name] = getattr(item, "value", item)
    if isinstance(value, ontology.ConstrainedChangeIR):
        result["operands"] = [
            {
                "role": role,
                "claimed_literal": operand.claimed_literal,
                **({"canonical_value": operand.canonical_value} if operand.has_canonical_value else {}),
            }
            for role, operand in value.operands
        ]
    return result


def _application_derivation(value: ontology.ConstrainedOntologyIR) -> dict[str, object] | None:
    slot_id = getattr(value, "slot_id", None)
    definition = registry.get_slot(slot_id)
    if definition is None:
        return None
    return {
        "slot_id": definition.slot_id,
        "semantic_key": definition.semantic_key,
        "display_label": definition.display_label,
        "typed_family": definition.typed_family.value,
        "entity_scope": definition.entity_scope.value,
        "value_type": definition.value_type.value,
        "registry_version": definition.registry_version,
        "risk_class": definition.risk_class.value,
        "auto_commit_allowed": definition.auto_commit_allowed,
    }


def _grounded_operands(value: ontology.GroundedConstrainedIR) -> list[dict[str, object]]:
    return [
        {
            "role": operand.role,
            "claimed_literal": operand.claimed_literal,
            "occurrence_count": operand.occurrence_count,
            "source_start": operand.source_start,
            "source_end": operand.source_end,
            "exact_slice": operand.exact_slice,
            "resolution_status": operand.resolution_status.value,
            "canonical_value": operand.canonical_value if operand.has_canonical_value else None,
            "canonical_value_ownership": "MODEL-SEMANTIC" if operand.has_canonical_value else None,
        }
        for operand in value.operands
    ]


def snapshot_digest(snapshot: dict[str, object]) -> str:
    """Deterministic digest used to bind an HR-P3 review ticket to one real snapshot."""
    safe = {
        "revision": snapshot.get("revision"),
        "ontology_current": snapshot.get("ontology_current", []),
        "legacy_unmanaged_current_count": snapshot.get("legacy_unmanaged_current_count", 0),
        "legacy_unmanaged_current": snapshot.get("legacy_unmanaged_current", []),
        "pending_proposal_id": snapshot.get("pending_proposal_id"),
        "history_guard": snapshot.get("history_guard", []),
        "message_count": snapshot.get("message_count", 0),
    }
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authoritative_current(
    candidate: ontology_compiler.OntologyActionCandidate,
    snapshot: dict[str, object],
) -> ontology_preconditions.AuthoritativeTypedState | None:
    if not candidate.executable:
        return None
    rows = [row for row in snapshot.get("ontology_current", []) if isinstance(row, dict)]
    if candidate.target_memory_id is not None:
        matches = [row for row in rows if row.get("memory_id") == candidate.target_memory_id]
    else:
        definition = registry.get_slot(candidate.slot_id)
        if definition is None:
            matches = []
        elif definition.entity_scope is registry.EntityScope.SELF_OR_SINGLETON:
            matches = [row for row in rows if row.get("slot_id") == candidate.slot_id]
        else:
            matches = [
                row for row in rows
                if row.get("slot_id") == candidate.slot_id and row.get("entity_id") == candidate.entity_id
            ]
    if len(matches) > 1:
        raise ShadowInputError("Real Current has multiple ontology targets for the same slot/entity")
    if not matches:
        return None
    row = matches[0]
    return ontology_preconditions.authoritative_state(
        str(row["memory_id"]),
        str(row["slot_id"]),
        int(row["registry_version"]),
        None if row.get("entity_id") is None else str(row["entity_id"]),
        str(row["typed_family"]),
        dict(row["canonical_state"]),
    )


class ProductionOntologyShadowService:
    """One-call HR-P2 preview against real Normal Chat Current; zero mutation."""

    def __init__(self, provider: ShadowProvider, snapshot_loader: SnapshotLoader):
        self._provider = provider
        self._snapshot_loader = snapshot_loader
        self._provider_calls = 0
        self._review_lock = threading.Lock()
        self._review_tickets: dict[str, ProductionReviewTicket] = {}

    @property
    def provider_calls(self) -> int:
        return self._provider_calls

    def claim_review_ticket(self, token: object) -> ProductionReviewTicket:
        """Consume one server-issued HR-P3 review ticket exactly once."""
        if not isinstance(token, str) or not token:
            raise ShadowInputError("Invalid HR-P3 review token")
        with self._review_lock:
            ticket = self._review_tickets.pop(token, None)
        if ticket is None:
            raise ShadowInputError("HR-P3 review token is missing, stale, or already consumed")
        return ticket

    def _issue_review_ticket(
        self,
        *,
        user_id: str,
        session_id: str,
        question: str,
        base_revision: int,
        snapshot_digest: str,
        route_plan: ontology_routing.OntologyRoutePlan,
    ) -> str:
        token = secrets.token_urlsafe(24)
        ticket = ProductionReviewTicket(
            token=token,
            user_id=user_id,
            session_id=session_id,
            question=question,
            base_revision=base_revision,
            snapshot_digest=snapshot_digest,
            route_plan=route_plan,
        )
        with self._review_lock:
            self._review_tickets[token] = ticket
        return token

    def run_request(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ShadowInputError("Shadow request must be a JSON object")
        if not set(request).issubset({"user_id", "session_id", "message", "api_key"}):
            raise ShadowInputError("Shadow request accepts only user_id, session_id, message, api_key")
        user_id = request.get("user_id")
        session_id = request.get("session_id")
        message = request.get("message")
        api_key = request.get("api_key")
        if not isinstance(user_id, str) or not user_id:
            raise ShadowInputError("user_id is required")
        if not isinstance(session_id, str) or not session_id:
            raise ShadowInputError("session_id is required")
        if not isinstance(message, str) or not message.strip():
            raise ShadowInputError("message is required")
        if len(message) > 4000:
            raise ShadowInputError("message is too long")
        if api_key is not None and not isinstance(api_key, str):
            raise ShadowInputError("api_key must be text")
        key = os.environ.get("DEEPSEEK_API_KEY") or (api_key or "").strip()
        if not key:
            raise ShadowInputError("Provide DEEPSEEK_API_KEY or API key fallback")

        before = self._snapshot_loader(user_id, session_id)
        if before.get("pending_proposal_id") is not None:
            raise ShadowInputError("Resolve the pending Normal Chat proposal before running production shadow")
        before_digest = snapshot_digest(before)
        context = _candidate_context(before)
        self._provider_calls += 1
        base = {
            "shadow_only": True,
            "product_mode": PRODUCT_MODE,
            "source": SHADOW_SOURCE,
            "provider_calls_this_run": 1,
            "cumulative_provider_calls": self._provider_calls,
            "user_id": user_id,
            "session_id": session_id,
            "question": message,
            "normal_chat_revision": before.get("revision"),
            "ontology_managed_current_count": len(before.get("ontology_current", [])),
            "legacy_unmanaged_current_count": int(before.get("legacy_unmanaged_current_count", 0)),
            "entity_candidates": list(context.entity_candidates),
            "target_memory_candidates": list(context.target_memory_candidates),
            "residual_semantic_risk": RESIDUAL_RISK_WARNING,
            "proposal_created": False,
            "persistence_performed": False,
            "current_changed": False,
            "history_changed": False,
            "revision_changed": False,
        }
        try:
            raw_text = self._provider.complete(_prompt(message.strip(), context), key)
        except Exception as exc:
            return {**base, "state": "PROVIDER_ERROR", "diagnostic": f"Provider call failed ({type(exc).__name__})"}
        try:
            raw = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            return {**base, "state": "STRUCTURAL_REJECT", "diagnostic": "INVALID_JSON", "raw_model_result": raw_text}
        try:
            parsed = ontology.parse_constrained_ir(
                raw,
                entity_candidates=context.entity_candidates,
                target_memory_candidates=context.target_memory_candidates,
            )
        except ontology.OntologyIRError as exc:
            return {**base, "state": "STRUCTURAL_REJECT", "diagnostic": exc.reason_code, "raw_model_result": _safe_raw(raw)}
        try:
            grounded = ontology.validate_grounding(parsed, message.strip())
            compiled = ontology_compiler.compile_ontology_action(grounded)
            current = _authoritative_current(compiled, before)
            precondition = ontology_preconditions.resolve_authoritative_precondition(compiled, current)
            risk = risk_engine.evaluate_risk(compiled, ontology_preconditions.risk_facts(precondition))
            route = ontology_routing.plan_route(compiled, precondition, risk)
        except ontology.OntologyIRError as exc:
            return {**base, "state": "GROUNDING_REJECT", "diagnostic": exc.reason_code, "raw_model_result": _safe_raw(raw), "model_selection": _model_selection(parsed)}
        except (ontology_compiler.OntologyCompilerError, ShadowInputError) as exc:
            reason = getattr(exc, "reason_code", type(exc).__name__)
            return {**base, "state": "FAIL_CLOSED", "diagnostic": str(reason), "raw_model_result": _safe_raw(raw), "model_selection": _model_selection(parsed)}

        after = self._snapshot_loader(user_id, session_id)
        after_digest = snapshot_digest(after)
        unchanged = before_digest == after_digest
        legacy_count = int(before.get("legacy_unmanaged_current_count", 0))
        cutover_gate = "NOT_APPLICABLE"
        if compiled.executable:
            cutover_gate = (
                "BLOCKED_BY_LEGACY_UNMANAGED_CURRENT"
                if legacy_count > 0 and current is None
                else "SHADOW_READY_FOR_HR_P3_REVIEW"
            )
        hr_p3_review_token = None
        if (
            cutover_gate == "SHADOW_READY_FOR_HR_P3_REVIEW"
            and route.route == ontology_routing.OntologyRoute.HUMAN_REVIEW_ROUTE.value
            and route.human_review_payload is not None
            and unchanged
        ):
            hr_p3_review_token = self._issue_review_ticket(
                user_id=user_id,
                session_id=session_id,
                question=message.strip(),
                base_revision=int(before.get("revision", 0)),
                snapshot_digest=before_digest,
                route_plan=route,
            )
        return {
            **base,
            "state": "VALIDATED",
            "diagnostic": "VALIDATED",
            "raw_model_result": _safe_raw(raw),
            "model_selection": _model_selection(parsed),
            "application_derivation": _application_derivation(parsed),
            "grounded_operands": _grounded_operands(grounded),
            "compiler_preview": ontology_compiler.compiler_preview(compiled),
            "precondition_preview": {
                **ontology_preconditions.precondition_preview(precondition),
                "fixture_source": SHADOW_SOURCE,
            },
            "risk_preview": risk_engine.risk_preview(risk),
            "routing_preview": ontology_routing.routing_preview(route),
            "human_review_payload_preview": ontology_routing.human_review_payload_preview(route.human_review_payload),
            "cutover_gate": cutover_gate,
            "hr_p3_review_available": hr_p3_review_token is not None,
            "hr_p3_review_token": hr_p3_review_token,
            "normal_chat_state_unchanged": unchanged,
            "revision_before": before.get("revision"),
            "revision_after": after.get("revision"),
            "pending_proposal_before": before.get("pending_proposal_id"),
            "pending_proposal_after": after.get("pending_proposal_id"),
            "proposal_created": False,
            "persistence_performed": False,
            "current_changed": not unchanged,
            "history_changed": False,
            "revision_changed": before.get("revision") != after.get("revision"),
        }
