"""Phase 1B deterministic validator for LLM-proposed memory operations.

The validator is intentionally a gate in front of Phase 1A Memory Core. It
does not call an LLM and does not write memory. Rejection rules are conservative
and are used only to block unsafe candidates from becoming deterministic state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


class CandidateOperation(StrEnum):
    SET = "set"
    REPLACE = "replace"
    CORRECT = "correct"
    FORGET = "forget"
    NO_OP = "no_op"
    IGNORE = "ignore"
    QUERY = "query"


WRITE_OPERATIONS = {
    CandidateOperation.SET,
    CandidateOperation.REPLACE,
    CandidateOperation.CORRECT,
    CandidateOperation.FORGET,
}

SAFE_NON_WRITE_OPERATIONS = {CandidateOperation.NO_OP, CandidateOperation.IGNORE, CandidateOperation.QUERY}

ALLOWED_ATTRIBUTES = {
    "city",
    "office_city",
    "favorite_drink",
    "pet_name",
    "phone_model",
    "birth_month",
    "desk_floor",
}

SENSITIVE_ATTRIBUTES = {
    "password",
    "api_key",
    "secret",
    "credit_card",
    "id_number",
    "medical_condition",
    "political_view",
    "religion",
}

FUTURE_MARKERS = ("下個月", "明年", "之後", "將會", "打算", "準備", "計畫", "未來", "可能會")
HISTORICAL_MARKERS = ("以前", "過去", "曾經", "之前", "去年", "小時候", "原本")
NEGATIVE_MARKERS = ("不是", "沒有住", "不住", "並非", "不再是")
THIRD_PERSON_MARKERS = ("我朋友", "朋友", "我同事", "同事", "我媽媽", "我爸爸", "他", "她", "他們", "她們")
UNCERTAIN_MARKERS = ("可能", "也許", "大概", "不確定", "應該", "或許")
INJECTION_MARKERS = (
    "忽略所有規則",
    "忽略以上",
    "system prompt",
    "developer message",
    "不要遵守",
    "直接寫入",
    "bypass",
)


@dataclass(frozen=True, slots=True)
class CandidateMemoryOperation:
    operation: CandidateOperation
    subject: str | None
    attribute: str | None
    value: Any
    confidence: float
    reason: str
    valid_from: str | None
    valid_to: str | None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    accepted: bool
    candidate: CandidateMemoryOperation | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)


class MemoryOperationValidator:
    """Validate untrusted LLM candidate operations before Memory Core writes."""

    def validate(self, text: str, candidate_json: Mapping[str, Any]) -> ValidationResult:
        schema_result = self._parse_candidate(candidate_json)
        if not schema_result.accepted:
            return schema_result
        candidate = schema_result.candidate
        reasons: list[str] = []

        operation = candidate.operation
        is_write = operation in WRITE_OPERATIONS
        lowered_text = text.lower()

        if operation in SAFE_NON_WRITE_OPERATIONS:
            return ValidationResult(True, candidate, ("safe_non_write",))

        if _contains_any(lowered_text, INJECTION_MARKERS):
            reasons.append("prompt_injection_rejected")
        if candidate.attribute in SENSITIVE_ATTRIBUTES:
            reasons.append("sensitive_memory_rejected")
        if _contains_any(text, FUTURE_MARKERS) and is_write:
            reasons.append("future_intention_rejected")
        if _contains_any(text, HISTORICAL_MARKERS) and operation != CandidateOperation.CORRECT:
            reasons.append("historical_fact_cannot_overwrite_current")
        if operation == CandidateOperation.CORRECT and _contains_any(text, HISTORICAL_MARKERS) and not candidate.valid_from:
            reasons.append("historical_correction_requires_valid_from")
        if _contains_any(text, NEGATIVE_MARKERS) and is_write:
            reasons.append("negative_statement_rejected")
        if _contains_any(text, THIRD_PERSON_MARKERS) and is_write:
            reasons.append("third_person_information_rejected")
        if _contains_any(text, UNCERTAIN_MARKERS) and is_write:
            reasons.append("uncertain_statement_rejected")

        if candidate.subject != "user":
            reasons.append("subject_must_be_user")
        if operation in {CandidateOperation.SET, CandidateOperation.REPLACE, CandidateOperation.CORRECT}:
            if candidate.attribute not in ALLOWED_ATTRIBUTES:
                reasons.append("unsupported_attribute")
            if candidate.value is None or candidate.value == "":
                reasons.append("write_requires_value")
        if operation == CandidateOperation.FORGET:
            if candidate.attribute not in ALLOWED_ATTRIBUTES:
                reasons.append("forget_requires_supported_attribute")
            if candidate.value is not None:
                reasons.append("forget_must_not_include_value")

        return ValidationResult(not reasons, candidate, tuple(reasons or ["validated"]))

    def _parse_candidate(self, candidate_json: Mapping[str, Any]) -> ValidationResult:
        if not isinstance(candidate_json, Mapping):
            return ValidationResult(False, reasons=("candidate_must_be_object",))

        operation_raw = candidate_json.get("operation")
        if not isinstance(operation_raw, str):
            return ValidationResult(False, reasons=("operation_must_be_string",))
        try:
            operation = CandidateOperation(operation_raw)
        except ValueError:
            return ValidationResult(False, reasons=("operation_not_allowed",))

        subject = candidate_json.get("subject")
        attribute = candidate_json.get("attribute")
        confidence = candidate_json.get("confidence")
        reason = candidate_json.get("reason")
        valid_time = candidate_json.get("valid_time", {"from": None, "to": None})

        if subject is not None and not isinstance(subject, str):
            return ValidationResult(False, reasons=("subject_must_be_string_or_null",))
        if attribute is not None and not isinstance(attribute, str):
            return ValidationResult(False, reasons=("attribute_must_be_string_or_null",))
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return ValidationResult(False, reasons=("confidence_must_be_number",))
        if not 0.0 <= float(confidence) <= 1.0:
            return ValidationResult(False, reasons=("confidence_out_of_range",))
        if not isinstance(reason, str):
            return ValidationResult(False, reasons=("reason_must_be_string",))
        if not isinstance(valid_time, Mapping):
            return ValidationResult(False, reasons=("valid_time_must_be_object",))

        valid_from = valid_time.get("from")
        valid_to = valid_time.get("to")
        if not _valid_time_value(valid_from):
            return ValidationResult(False, reasons=("valid_time_from_invalid",))
        if not _valid_time_value(valid_to):
            return ValidationResult(False, reasons=("valid_time_to_invalid",))

        return ValidationResult(
            True,
            CandidateMemoryOperation(
                operation=operation,
                subject=subject,
                attribute=attribute,
                value=candidate_json.get("value"),
                confidence=float(confidence),
                reason=reason,
                valid_from=valid_from,
                valid_to=valid_to,
            ),
            ("schema_valid",),
        )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _valid_time_value(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True
