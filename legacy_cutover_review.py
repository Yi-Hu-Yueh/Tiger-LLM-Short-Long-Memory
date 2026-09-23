"""HR-P2L legacy cutover review and explicit same-lineage scalar adoption.

The service exposes exact legacy Current rows from the real Normal Chat snapshot.  It
never parses legacy prose, guesses a slot, or derives a canonical value.  The human
selects one exact legacy row, one canonical singleton-scalar Registry-v1 slot, and
enters the canonical value.  Preview is read-only.  Apply requires the exact one-time
server-issued review token and an explicit confirmation; the injected store callback
performs the revision-bound same-lineage transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import threading
from typing import Callable

import slot_registry as registry


INVENTORY_ENDPOINT = "/api/legacy-cutover/inventory"
PREVIEW_ENDPOINT = "/api/legacy-cutover/preview"
APPLY_ENDPOINT = "/api/legacy-cutover/apply"
PRODUCTION_ACTIVE = True
PRODUCT_PHASE_PREVIEW = "HR_P2L1_LEGACY_CUTOVER_REVIEW_PREVIEW"
PRODUCT_PHASE_APPLY = "HR_P2L2_HUMAN_CONFIRMED_LEGACY_CUTOVER"
SOURCE = "REAL_NORMAL_CHAT_LEGACY_CURRENT"


class LegacyCutoverReviewError(ValueError):
    """Invalid human-reviewed legacy-cutover input/state."""


SnapshotLoader = Callable[[str, str], dict[str, object]]
ApplyCallback = Callable[..., dict[str, object]]


@dataclass(frozen=True, slots=True)
class LegacyScalarAdoptionPlan:
    review_token: str
    user_id: str
    session_id: str
    memory_id: str
    legacy_content: str
    slot_id: str
    registry_version: int
    semantic_key: str
    display_label: str
    state_type: str
    operation: str
    canonical_value: str
    base_revision: int


@dataclass(frozen=True, slots=True)
class LegacyScalarAdoptionPreview:
    memory_id: str
    legacy_content: str
    slot_id: str
    registry_version: int
    semantic_key: str
    display_label: str
    state_type: str
    operation: str
    canonical_value: str
    revision: int

    def as_dict(self) -> dict[str, object]:
        return {
            "preview_only": True,
            "product_phase": PRODUCT_PHASE_PREVIEW,
            "source": SOURCE,
            "migration_kind": "LEGACY_TO_ONTOLOGY_SCALAR_SAME_LINEAGE",
            "memory_id": self.memory_id,
            "legacy_content": self.legacy_content,
            "slot_id": self.slot_id,
            "registry_version": self.registry_version,
            "entity_id": None,
            "semantic_key": self.semantic_key,
            "display_label": self.display_label,
            "state_type": self.state_type,
            "operation": self.operation,
            "canonical_arguments": {"value": self.canonical_value},
            "human_entered_canonical_value": self.canonical_value,
            "value_source": "HUMAN_ENTERED_CANONICAL_VALUE",
            "base_revision": self.revision,
            "same_memory_id_preserved": True,
            "would_archive_legacy_predecessor": True,
            "would_increment_revision": True,
            "would_set_slot_id": self.slot_id,
            "would_set_registry_version": self.registry_version,
            "would_set_entity_id": None,
            "provider_calls_added": 0,
            "proposal_created": False,
            "mutation_performed": False,
            "current_changed": False,
            "history_changed": False,
            "revision_changed": False,
            "warning": (
                "Preview only. The application did not parse legacy prose or infer the value. "
                "The human-entered canonical value must be reviewed against the exact legacy content."
            ),
        }


class LegacyCutoverReviewService:
    """Human-reviewed legacy cutover service over real Normal Chat Current."""

    def __init__(
        self,
        snapshot_loader: SnapshotLoader,
        apply_callback: ApplyCallback | None = None,
    ):
        self._snapshot_loader = snapshot_loader
        self._apply_callback = apply_callback
        self._plans: dict[str, LegacyScalarAdoptionPlan] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _validate_scope(request: object) -> tuple[str, str]:
        if not isinstance(request, dict):
            raise LegacyCutoverReviewError("Legacy cutover request must be a JSON object")
        user_id = request.get("user_id")
        session_id = request.get("session_id")
        if not isinstance(user_id, str) or not user_id:
            raise LegacyCutoverReviewError("user_id is required")
        if not isinstance(session_id, str) or not session_id:
            raise LegacyCutoverReviewError("session_id is required")
        return user_id, session_id

    @staticmethod
    def _eligible_slots() -> list[dict[str, object]]:
        result = []
        for definition in registry.iter_slots():
            if (
                definition.entity_scope is registry.EntityScope.SELF_OR_SINGLETON
                and definition.typed_family is registry.TypedFamily.SCALAR
            ):
                result.append({
                    "slot_id": definition.slot_id,
                    "display_label": definition.display_label,
                    "typed_family": definition.typed_family.value,
                    "value_type": definition.value_type.value,
                    "registry_version": definition.registry_version,
                })
        return result

    def inventory(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or not set(request).issubset({"user_id", "session_id"}):
            raise LegacyCutoverReviewError("Inventory accepts only user_id and session_id")
        user_id, session_id = self._validate_scope(request)
        snapshot = self._snapshot_loader(user_id, session_id)
        legacy_rows = snapshot.get("legacy_unmanaged_current", [])
        if not isinstance(legacy_rows, list):
            raise LegacyCutoverReviewError("Legacy Current inventory is unavailable")
        return {
            "preview_only": True,
            "product_phase": PRODUCT_PHASE_PREVIEW,
            "source": SOURCE,
            "user_id": user_id,
            "session_id": session_id,
            "revision": snapshot.get("revision"),
            "ontology_managed_current_count": len(snapshot.get("ontology_current", [])),
            "legacy_unmanaged_current_count": len(legacy_rows),
            "legacy_rows": legacy_rows,
            "eligible_slots": self._eligible_slots(),
            "provider_calls_added": 0,
            "mutation_performed": False,
            "warning": (
                "No slot/value is inferred from legacy prose. Select one exact legacy memory, "
                "one canonical singleton scalar slot, and type the canonical value manually."
            ),
        }

    def _build_preview(self, request: object) -> tuple[dict[str, object], LegacyScalarAdoptionPlan]:
        allowed = {"user_id", "session_id", "memory_id", "slot_id", "canonical_value"}
        if not isinstance(request, dict) or set(request) != allowed:
            raise LegacyCutoverReviewError(
                "Preview requires exactly user_id, session_id, memory_id, slot_id, canonical_value"
            )
        user_id, session_id = self._validate_scope(request)
        memory_id = request.get("memory_id")
        slot_id = request.get("slot_id")
        canonical_value = request.get("canonical_value")
        if not isinstance(memory_id, str) or not memory_id:
            raise LegacyCutoverReviewError("memory_id is required")
        if not isinstance(slot_id, str) or not slot_id:
            raise LegacyCutoverReviewError("slot_id is required")
        if not isinstance(canonical_value, str) or not canonical_value.strip():
            raise LegacyCutoverReviewError("canonical_value must be non-empty text")
        canonical_value = canonical_value.strip()
        if len(canonical_value) > 160:
            raise LegacyCutoverReviewError("canonical_value is too long")

        definition = registry.get_slot(slot_id)
        if definition is None:
            raise LegacyCutoverReviewError("Unknown canonical slot_id")
        if not (
            definition.entity_scope is registry.EntityScope.SELF_OR_SINGLETON
            and definition.typed_family is registry.TypedFamily.SCALAR
        ):
            raise LegacyCutoverReviewError(
                "HR-P2L currently supports only singleton scalar Registry-v1 slots"
            )

        snapshot = self._snapshot_loader(user_id, session_id)
        if snapshot.get("pending_proposal_id") is not None:
            raise LegacyCutoverReviewError("Resolve the pending Normal Chat proposal first")
        legacy_rows = [
            row for row in snapshot.get("legacy_unmanaged_current", [])
            if isinstance(row, dict) and row.get("memory_id") == memory_id
        ]
        if len(legacy_rows) != 1:
            raise LegacyCutoverReviewError("Selected memory is not exactly one current legacy row")
        legacy_row = legacy_rows[0]

        collisions = [
            row for row in snapshot.get("ontology_current", [])
            if isinstance(row, dict) and row.get("slot_id") == slot_id
        ]
        if collisions:
            raise LegacyCutoverReviewError(
                "An ontology-managed Current already exists for this singleton slot"
            )

        revision = snapshot.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise LegacyCutoverReviewError("Current revision is invalid")
        content = legacy_row.get("content")
        if not isinstance(content, str) or not content:
            raise LegacyCutoverReviewError("Legacy content is invalid")

        preview = LegacyScalarAdoptionPreview(
            memory_id=memory_id,
            legacy_content=content,
            slot_id=definition.slot_id,
            registry_version=definition.registry_version,
            semantic_key=definition.semantic_key,
            display_label=definition.display_label,
            state_type=definition.typed_family.value,
            operation="CREATE_SCALAR",
            canonical_value=canonical_value,
            revision=revision,
        ).as_dict()
        preview["current_ontology_count_before"] = len(snapshot.get("ontology_current", []))
        preview["legacy_count_before"] = len(snapshot.get("legacy_unmanaged_current", []))
        preview["current_ontology_count_after_if_applied"] = preview["current_ontology_count_before"] + 1
        preview["legacy_count_after_if_applied"] = preview["legacy_count_before"] - 1

        token = secrets.token_urlsafe(24)
        plan = LegacyScalarAdoptionPlan(
            review_token=token,
            user_id=user_id,
            session_id=session_id,
            memory_id=memory_id,
            legacy_content=content,
            slot_id=definition.slot_id,
            registry_version=definition.registry_version,
            semantic_key=definition.semantic_key,
            display_label=definition.display_label,
            state_type=definition.typed_family.value,
            operation="CREATE_SCALAR",
            canonical_value=canonical_value,
            base_revision=revision,
        )
        preview["review_token"] = token
        preview["apply_available"] = self._apply_callback is not None
        preview["explicit_confirmation_required"] = True
        return preview, plan

    def preview(self, request: object) -> dict[str, object]:
        preview, plan = self._build_preview(request)
        with self._lock:
            self._plans[plan.review_token] = plan
        return preview

    def apply(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or set(request) != {
            "user_id", "session_id", "review_token", "confirmed"
        }:
            raise LegacyCutoverReviewError(
                "Apply requires exactly user_id, session_id, review_token, confirmed"
            )
        user_id, session_id = self._validate_scope(request)
        token = request.get("review_token")
        if not isinstance(token, str) or not token:
            raise LegacyCutoverReviewError("review_token is required")
        if request.get("confirmed") is not True:
            raise LegacyCutoverReviewError("Explicit human confirmation is required")
        if self._apply_callback is None:
            raise LegacyCutoverReviewError("Legacy cutover apply is not available")

        with self._lock:
            plan = self._plans.get(token)
        if plan is None:
            raise LegacyCutoverReviewError("Review token is invalid, expired, or already consumed")
        if plan.user_id != user_id or plan.session_id != session_id:
            raise LegacyCutoverReviewError("Review token is not bound to this user/session")

        try:
            result = self._apply_callback(
                user_id=plan.user_id,
                session_id=plan.session_id,
                memory_id=plan.memory_id,
                expected_legacy_content=plan.legacy_content,
                slot_id=plan.slot_id,
                registry_version=plan.registry_version,
                semantic_key=plan.semantic_key,
                display_label=plan.display_label,
                canonical_value=plan.canonical_value,
                expected_revision=plan.base_revision,
            )
        except Exception:
            # Preserve the token on failure so the caller can inspect/resolve a transient
            # error.  Any stale revision or changed row will continue to fail closed.
            raise
        with self._lock:
            self._plans.pop(token, None)

        return {
            "preview_only": False,
            "product_phase": PRODUCT_PHASE_APPLY,
            "source": SOURCE,
            "human_confirmed": True,
            "review_token_consumed": True,
            "provider_calls_added": 0,
            **result,
        }
