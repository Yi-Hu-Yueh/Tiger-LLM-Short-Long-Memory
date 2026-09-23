"""Canonical attribute registry for Phase 1C memory extraction.

The registry is deterministic and conservative. It normalizes a small set of
reviewed aliases to canonical attributes and rejects ambiguous or unsupported
labels before a candidate can reach the validator or Memory Core.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


CANONICAL_ATTRIBUTES = frozenset(
    {
        "name",
        "city",
        "language",
        "preference",
        "environment",
        "tool",
        "occupation",
        "project",
        "model",
        "office_city",
        "favorite_drink",
        "pet_name",
        "phone_model",
        "birth_month",
        "desk_floor",
    }
)

ATTRIBUTE_ALIASES = {
    "residence_city": "city",
    "current_residence_city": "city",
    "current residence city": "city",
    "current city": "city",
    "home city": "city",
    "居住城市": "city",
    "目前居住城市": "city",
    "当前居住地": "city",
    "current_location": "city",
    "current location": "city",
    "residence": "city",
    "office location": "office_city",
    "office_location": "office_city",
    "office_city": "office_city",
    "辦公室城市": "office_city",
    "辦公室位置": "office_city",
    "favorite beverage": "favorite_drink",
    "favorite drink": "favorite_drink",
    "drink": "favorite_drink",
    "喜歡的飲料": "favorite_drink",
    "pet": "pet_name",
    "pet name": "pet_name",
    "寵物名字": "pet_name",
    "phone": "phone_model",
    "phone model": "phone_model",
    "手機型號": "phone_model",
    "birthday_month": "birth_month",
    "birthday month": "birth_month",
    "birth month": "birth_month",
    "生日月份": "birth_month",
    "desk floor": "desk_floor",
    "desk_floor": "desk_floor",
    "桌子樓層": "desk_floor",
}

AMBIGUOUS_ATTRIBUTES = frozenset(
    {
        "location",
        "place",
        "address",
        "desk_location",
        "desk location",
        "current place",
    }
)


@dataclass(frozen=True, slots=True)
class AttributeResolution:
    accepted: bool
    attribute: str | None
    reason: str


def normalize_attribute(attribute: Any) -> AttributeResolution:
    if attribute is None:
        return AttributeResolution(True, None, "attribute_null")
    if not isinstance(attribute, str):
        return AttributeResolution(False, None, "attribute_not_string")

    key = _canonicalize_label(attribute)
    if key in CANONICAL_ATTRIBUTES:
        return AttributeResolution(True, key, "canonical_attribute")
    if key in AMBIGUOUS_ATTRIBUTES:
        return AttributeResolution(False, None, "ambiguous_attribute")
    if key in ATTRIBUTE_ALIASES:
        return AttributeResolution(True, ATTRIBUTE_ALIASES[key], "normalized_attribute")
    return AttributeResolution(False, None, "unsupported_attribute")


def canonical_attributes_for_prompt() -> str:
    return ", ".join(sorted(CANONICAL_ATTRIBUTES))


def _canonicalize_label(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("-", "_")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized
