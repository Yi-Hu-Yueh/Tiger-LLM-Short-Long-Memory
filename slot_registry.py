"""Dormant, application-owned Canonical Slot Registry version 1.

Phase 1 deliberately exposes immutable metadata and strict static validation
without participating in provider prompts, routing, persistence, or commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Iterator, Mapping


REGISTRY_VERSION = 1
PRODUCTION_ACTIVE = False
UNKNOWN_SLOT = "UNKNOWN_SLOT"


class RegistryValidationError(ValueError):
    """The static registry is invalid and must fail closed."""


class EntityScope(str, Enum):
    SELF_OR_SINGLETON = "SELF_OR_SINGLETON"
    ENTITY_SCOPED = "ENTITY_SCOPED"


class TypedFamily(str, Enum):
    SCALAR = "scalar"
    SET = "set"
    COUNT = "count"
    RECORD = "record"


class ValueType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    STRING_SET = "set_of_strings"
    REGISTERED_RECORD_FIELD_STRING = "registered_record_field_string"


class RiskClass(str, Enum):
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    BENCHMARK_AUTO_CANDIDATE = "BENCHMARK_AUTO_CANDIDATE"


# The current runtime represents claim shapes and typed operations as canonical
# strings/frozensets rather than reusable Enum classes. Keeping the same exact
# values here avoids importing app.py (and a future circular runtime dependency).
SCALAR_ASSERTION = "SCALAR_ASSERTION"
CARDINALITY_ASSERTION = "CARDINALITY_ASSERTION"
ENUMERATION_ASSERTION = "ENUMERATION_ASSERTION"
MEMBERSHIP_ASSERTION = "MEMBERSHIP_ASSERTION"
FIELD_ASSERTION = "FIELD_ASSERTION"

_CLAIMS_BY_FAMILY = MappingProxyType(
    {
        TypedFamily.SCALAR: frozenset((SCALAR_ASSERTION,)),
        TypedFamily.SET: frozenset((ENUMERATION_ASSERTION, MEMBERSHIP_ASSERTION)),
        TypedFamily.COUNT: frozenset((CARDINALITY_ASSERTION,)),
        TypedFamily.RECORD: frozenset((FIELD_ASSERTION,)),
    }
)
_OPERATIONS_BY_FAMILY = MappingProxyType(
    {
        TypedFamily.SCALAR: frozenset(
            ("CREATE_SCALAR", "SET_VALUE", "REASSERT_NOOP", "DELETE_MEMORY")
        ),
        TypedFamily.SET: frozenset(
            ("CREATE_SET", "ADD_ITEM", "REMOVE_ITEM", "REPLACE_SET", "DELETE_MEMORY")
        ),
        TypedFamily.COUNT: frozenset(("CREATE_COUNT", "SET_COUNT", "DELETE_MEMORY")),
        TypedFamily.RECORD: frozenset(
            ("CREATE_RECORD", "SET_FIELD", "DELETE_FIELD", "DELETE_MEMORY")
        ),
    }
)
_VALUE_TYPES_BY_FAMILY = MappingProxyType(
    {
        TypedFamily.SCALAR: frozenset((ValueType.STRING,)),
        TypedFamily.SET: frozenset((ValueType.STRING_SET,)),
        TypedFamily.COUNT: frozenset((ValueType.INTEGER,)),
        TypedFamily.RECORD: frozenset((ValueType.REGISTERED_RECORD_FIELD_STRING,)),
    }
)
_DESTRUCTIVE_OPERATIONS = frozenset(("REMOVE_ITEM", "DELETE_FIELD", "DELETE_MEMORY"))


@dataclass(frozen=True, slots=True)
class SlotDefinition:
    slot_id: str
    registry_version: int
    entity_scope: EntityScope
    typed_family: TypedFamily
    value_type: ValueType
    allowed_claim_shapes: frozenset[str]
    allowed_operations: frozenset[str]
    grounding_required: bool
    display_label: str
    risk_class: RiskClass
    auto_commit_allowed: bool

    @property
    def semantic_key(self) -> str:
        return self.slot_id


_APPROVED_LABELS = MappingProxyType(
    {
        "user.office.location": "辦公室位置",
        "vehicle.color": "車輛顏色",
        "pet.name": "寵物名字",
        "group.members": "群組成員",
        "group.member_count": "群組人數",
        "ownership.owner_profile.name": "所有權人姓名",
        "ownership.owner_profile.address": "所有權人地址",
        "user.favorite_drink": "最愛飲料",
        "user.birth_month": "出生月份",
        "desk.floor": "書桌所在樓層",
        "device.phone.model": "手機型號",
        "person.residence.location": "居住地點",
    }
)
REGISTRY_V1_SLOT_IDS = tuple(_APPROVED_LABELS)


def _slot(
    slot_id: str,
    entity_scope: EntityScope,
    typed_family: TypedFamily,
    value_type: ValueType,
    claim_shapes: frozenset[str],
    operations: frozenset[str],
    risk_class: RiskClass = RiskClass.HUMAN_REVIEW_REQUIRED,
) -> SlotDefinition:
    return SlotDefinition(
        slot_id=slot_id,
        registry_version=REGISTRY_VERSION,
        entity_scope=entity_scope,
        typed_family=typed_family,
        value_type=value_type,
        allowed_claim_shapes=claim_shapes,
        allowed_operations=operations,
        grounding_required=True,
        display_label=_APPROVED_LABELS[slot_id],
        risk_class=risk_class,
        auto_commit_allowed=False,
    )


_SINGLETON = EntityScope.SELF_OR_SINGLETON
_ENTITY = EntityScope.ENTITY_SCOPED
_SCALAR_CLAIMS = _CLAIMS_BY_FAMILY[TypedFamily.SCALAR]
_SET_CLAIMS = _CLAIMS_BY_FAMILY[TypedFamily.SET]
_COUNT_CLAIMS = _CLAIMS_BY_FAMILY[TypedFamily.COUNT]
_RECORD_CLAIMS = _CLAIMS_BY_FAMILY[TypedFamily.RECORD]
_SCALAR_OPERATIONS = _OPERATIONS_BY_FAMILY[TypedFamily.SCALAR]
_SET_OPERATIONS = _OPERATIONS_BY_FAMILY[TypedFamily.SET]
_COUNT_OPERATIONS = _OPERATIONS_BY_FAMILY[TypedFamily.COUNT]
_RECORD_OPERATIONS = _OPERATIONS_BY_FAMILY[TypedFamily.RECORD]
_BENCHMARK = RiskClass.BENCHMARK_AUTO_CANDIDATE

SLOT_DEFINITIONS = (
    _slot("user.office.location", _SINGLETON, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS, _BENCHMARK),
    _slot("vehicle.color", _ENTITY, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS),
    _slot("pet.name", _ENTITY, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS),
    _slot("group.members", _ENTITY, TypedFamily.SET, ValueType.STRING_SET,
          _SET_CLAIMS, _SET_OPERATIONS),
    _slot("group.member_count", _ENTITY, TypedFamily.COUNT, ValueType.INTEGER,
          _COUNT_CLAIMS, _COUNT_OPERATIONS),
    _slot("ownership.owner_profile.name", _ENTITY, TypedFamily.RECORD,
          ValueType.REGISTERED_RECORD_FIELD_STRING, _RECORD_CLAIMS, _RECORD_OPERATIONS),
    _slot("ownership.owner_profile.address", _ENTITY, TypedFamily.RECORD,
          ValueType.REGISTERED_RECORD_FIELD_STRING, _RECORD_CLAIMS, _RECORD_OPERATIONS),
    _slot("user.favorite_drink", _SINGLETON, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS, _BENCHMARK),
    _slot("user.birth_month", _SINGLETON, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS, _BENCHMARK),
    _slot("desk.floor", _ENTITY, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS),
    _slot("device.phone.model", _ENTITY, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS),
    _slot("person.residence.location", _ENTITY, TypedFamily.SCALAR, ValueType.STRING,
          _SCALAR_CLAIMS, _SCALAR_OPERATIONS),
)


def validate_registry(
    definitions: Iterable[SlotDefinition], *, registry_version: int = REGISTRY_VERSION
) -> tuple[SlotDefinition, ...]:
    """Validate a complete Registry-v1 definition set or fail closed."""
    if isinstance(registry_version, bool) or registry_version != REGISTRY_VERSION:
        raise RegistryValidationError("invalid registry version")

    checked = tuple(definitions)
    seen: set[str] = set()
    for definition in checked:
        if not isinstance(definition, SlotDefinition):
            raise RegistryValidationError("unsupported slot definition")
        if not isinstance(definition.slot_id, str) or not definition.slot_id:
            raise RegistryValidationError("empty slot_id")
        if definition.slot_id in seen:
            raise RegistryValidationError("duplicate slot_id")
        seen.add(definition.slot_id)
        if definition.registry_version != registry_version:
            raise RegistryValidationError("invalid registry version")
        if not isinstance(definition.display_label, str) or not definition.display_label:
            raise RegistryValidationError("missing display_label")
        if not isinstance(definition.entity_scope, EntityScope):
            raise RegistryValidationError("unsupported entity scope")
        if not isinstance(definition.typed_family, TypedFamily):
            raise RegistryValidationError("unsupported family")
        if not isinstance(definition.value_type, ValueType):
            raise RegistryValidationError("unsupported value type")
        if definition.value_type not in _VALUE_TYPES_BY_FAMILY[definition.typed_family]:
            raise RegistryValidationError("value type is incompatible with family")
        if not isinstance(definition.allowed_claim_shapes, frozenset) or not definition.allowed_claim_shapes:
            raise RegistryValidationError("empty allowed claim-shape set")
        if not definition.allowed_claim_shapes <= _CLAIMS_BY_FAMILY[definition.typed_family]:
            raise RegistryValidationError("family/claim-shape incompatibility")
        if not isinstance(definition.allowed_operations, frozenset) or not definition.allowed_operations:
            raise RegistryValidationError("empty allowed-operation set")
        if not definition.allowed_operations <= _OPERATIONS_BY_FAMILY[definition.typed_family]:
            raise RegistryValidationError("family/operation incompatibility")
        if not isinstance(definition.grounding_required, bool):
            raise RegistryValidationError("grounding_required must be boolean")
        if not isinstance(definition.risk_class, RiskClass):
            raise RegistryValidationError("unsupported risk class")
        if not isinstance(definition.auto_commit_allowed, bool):
            raise RegistryValidationError("auto_commit_allowed must be boolean")
        if definition.slot_id == UNKNOWN_SLOT:
            raise RegistryValidationError("UNKNOWN_SLOT cannot be registered")
        if definition.auto_commit_allowed and definition.slot_id in {
            "vehicle.color", "group.member_count"
        }:
            raise RegistryValidationError("slot is forbidden from auto-commit")
        if definition.auto_commit_allowed and definition.allowed_operations <= _DESTRUCTIVE_OPERATIONS:
            raise RegistryValidationError("destructive-only automatic slot is forbidden")
        if definition.auto_commit_allowed:
            raise RegistryValidationError("Phase 1 production auto-commit is disabled")

    if tuple(definition.slot_id for definition in checked) != REGISTRY_V1_SLOT_IDS:
        raise RegistryValidationError("Registry-v1 inventory or ordering is invalid")
    for definition in checked:
        if definition.display_label != _APPROVED_LABELS[definition.slot_id]:
            raise RegistryValidationError("Registry-v1 display_label mismatch")
        if definition.semantic_key != definition.slot_id:
            raise RegistryValidationError("semantic_key must equal slot_id")
    return checked


validate_registry(SLOT_DEFINITIONS)
REGISTRY_V1: Mapping[str, SlotDefinition] = MappingProxyType(
    {definition.slot_id: definition for definition in SLOT_DEFINITIONS}
)


def get_slot(slot_id: object) -> SlotDefinition | None:
    """Return an exact canonical match, or explicit not-found as ``None``."""
    if not isinstance(slot_id, str):
        return None
    return REGISTRY_V1.get(slot_id)


def canonical_semantic_key(slot_id: object) -> str | None:
    definition = get_slot(slot_id)
    return None if definition is None else definition.slot_id


def canonical_display_label(slot_id: object) -> str | None:
    definition = get_slot(slot_id)
    return None if definition is None else definition.display_label


def iter_slots() -> Iterator[SlotDefinition]:
    """Iterate in the governed deterministic Registry-v1 order."""
    return iter(SLOT_DEFINITIONS)
