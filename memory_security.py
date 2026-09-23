"""Phase 4D read-only security and privacy evaluation over existing policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Iterable, Mapping, Sequence

from memory_audit import AuditEvent
from memory_validator import MemoryOperationValidator


ALLOWED_USERS = frozenset(("user1", "user2"))
SENSITIVE_ATTRIBUTE_NAMES = frozenset(
    (
        "api_key",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "credential",
        "credentials",
        "secret",
        "private_secret",
        "credit_card",
        "id_number",
    )
)


class SecurityPolicy(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class SecurityScan:
    accepted_by_validator: bool
    sensitive: bool
    prompt_injection: bool
    reasons: tuple[str, ...]


class MemorySecurityEvaluator:
    """Classify validation evidence without logging or retaining raw payloads."""

    def __init__(self, *, validator: MemoryOperationValidator | None = None):
        self.validator = validator or MemoryOperationValidator()

    def scan_candidate(self, text: str, candidate: Mapping[str, Any]) -> SecurityScan:
        if not isinstance(text, str) or not isinstance(candidate, Mapping):
            return SecurityScan(False, False, False, ("invalid_security_input",))
        attribute = candidate.get("attribute")
        sensitive = isinstance(attribute, str) and attribute.lower() in SENSITIVE_ATTRIBUTE_NAMES
        validation = self.validator.validate(text, candidate)
        reasons = list(validation.reasons)
        if sensitive and "sensitive_memory_rejected" not in reasons:
            reasons.append("sensitive_memory_rejected")
        injection = "prompt_injection_rejected" in reasons
        accepted = validation.accepted and not sensitive and not injection
        return SecurityScan(accepted, sensitive, injection, tuple(sorted(set(reasons))))

    @staticmethod
    def evaluate_policy(scan: SecurityScan) -> SecurityPolicy:
        if not isinstance(scan, SecurityScan):
            return SecurityPolicy.BLOCK
        return SecurityPolicy.ALLOW if scan.accepted_by_validator else SecurityPolicy.BLOCK

    @staticmethod
    def check_isolation(*, requesting_user: str, owning_user: str) -> bool:
        if requesting_user not in ALLOWED_USERS or owning_user not in ALLOWED_USERS:
            return False
        return requesting_user == owning_user

    def generate_security_report(
        self,
        *,
        scans: Sequence[SecurityScan],
        isolation_checks: Sequence[bool],
        audit_events: Iterable[AuditEvent],
        forbidden_values: Iterable[str] = (),
    ) -> dict[str, Any]:
        events = tuple(audit_events)
        forbidden = tuple(value for value in forbidden_values if isinstance(value, str) and value)
        audit_text = self._audit_text(events)
        violations = sum(value in audit_text for value in forbidden)
        blocked = sum(self.evaluate_policy(scan) is SecurityPolicy.BLOCK for scan in scans)
        sensitive = sum(scan.sensitive for scan in scans)
        injections = sum(scan.prompt_injection for scan in scans)
        isolation_failures = sum(not result for result in isolation_checks)
        overall = "PASS" if violations == 0 and isolation_failures == 0 else "FAIL"
        return {
            "candidate_policy": {
                "scanned": len(scans),
                "allowed": len(scans) - blocked,
                "blocked": blocked,
                "sensitive_blocked": sensitive,
                "injection_blocked": injections,
            },
            "isolation": {
                "checks": len(isolation_checks),
                "failures": isolation_failures,
            },
            "audit_privacy": {
                "events_checked": len(events),
                "secret_leak_count": violations,
            },
            "overall": overall,
        }

    @staticmethod
    def render_report(report: Mapping[str, Any]) -> str:
        return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _audit_text(events: Sequence[AuditEvent]) -> str:
        safe_rows = [
            {
                "audit_id": event.audit_id,
                "timestamp": event.timestamp,
                "user_id": event.user_id,
                "session_id": event.session_id,
                "event_type": event.event_type.value,
                "source": event.source,
                "status": event.status,
                "entity_id": event.entity_id,
                "details": event.details_dict(),
            }
            for event in events
        ]
        return json.dumps(safe_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
