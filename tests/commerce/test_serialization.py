import hashlib
import json
from collections.abc import Callable

import pytest

from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    ComparisonOperator,
    HardConstraint,
    ProvenanceLabel,
    SoftPreference,
    canonical_attribute_value_bytes,
    canonical_hard_constraint_bytes,
    canonical_soft_preference_bytes,
)

_CONSTRAINT_ID = "15000000-0000-4000-8000-000000000001"
_OTHER_CONSTRAINT_ID = "15000000-0000-4000-8000-000000000002"
_PREFERENCE_ID = "16000000-0000-4000-8000-000000000001"
_OTHER_PREFERENCE_ID = "16000000-0000-4000-8000-000000000002"

_GOLDEN_ATTRIBUTE_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"attribute_value_version":'
    b'"attribute-value-v1","schema_version":"1","value":"clear","value_type":"string"},'
    b'"payload_type":"attribute_value_v1"}'
)
_GOLDEN_HARD_CONSTRAINT_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"allowed_provenance":'
    b'["ATTESTED","PREDICTED","VERIFIED"],"attribute_key":"ram_gb","constraint_id":'
    b'"15000000-0000-4000-8000-000000000001","constraint_primitives_version":'
    b'"constraint-primitives-v1","operand":{"attribute_value_version":"attribute-value-v1",'
    b'"schema_version":"1","value":16,"value_type":"integer"},"operator":"gte",'
    b'"schema_version":"1"},"payload_type":"hard_constraint_v1"}'
)
_GOLDEN_SOFT_PREFERENCE_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"allowed_provenance":'
    b'["CLAIMED","VERIFIED"],"attribute_key":"brand","constraint_primitives_version":'
    b'"constraint-primitives-v1","operand":{"attribute_value_version":"attribute-value-v1",'
    b'"schema_version":"1","value":"clear","value_type":"string"},"operator":"eq",'
    b'"preference_id":"16000000-0000-4000-8000-000000000001","schema_version":"1"},'
    b'"payload_type":"soft_preference_v1"}'
)

_GOLDEN_ATTRIBUTE_SHA256 = "441e9c53cf0f5f0f330df55a87d2e67a9f0bb27dafb1e1dff990e87fd9d9dba5"
_GOLDEN_HARD_CONSTRAINT_SHA256 = "bcbf4090ab105c994f94ea0cbd0568b321ec6c24b19e569b5978d37088189b9d"
_GOLDEN_SOFT_PREFERENCE_SHA256 = "6b67126c392b8f638962b7b988aa0f598cc7d21a1670753aecedb62d0957c879"


def _attribute(
    value_type: AttributeValueType = AttributeValueType.STRING,
    value: str | int | bool = "clear",
) -> AttributeValue:
    return AttributeValue(value_type=value_type, value=value)


def _golden_hard_constraint() -> HardConstraint:
    return HardConstraint(
        constraint_id=_CONSTRAINT_ID,
        attribute_key="ram_gb",
        operator=ComparisonOperator.GTE,
        operand=_attribute(AttributeValueType.INTEGER, 16),
        allowed_provenance=(
            ProvenanceLabel.VERIFIED,
            ProvenanceLabel.ATTESTED,
            ProvenanceLabel.PREDICTED,
        ),
    )


def _golden_soft_preference() -> SoftPreference:
    return SoftPreference(
        preference_id=_PREFERENCE_ID,
        attribute_key="brand",
        operator=ComparisonOperator.EQ,
        operand=_attribute(),
        allowed_provenance=(ProvenanceLabel.VERIFIED, ProvenanceLabel.CLAIMED),
    )


def _binding_hard_constraint(**changes: object) -> HardConstraint:
    values: dict[str, object] = {
        "constraint_id": _CONSTRAINT_ID,
        "attribute_key": "ram_gb",
        "operator": ComparisonOperator.EQ,
        "operand": _attribute(AttributeValueType.INTEGER, 16),
        "allowed_provenance": (ProvenanceLabel.VERIFIED,),
        **changes,
    }
    return HardConstraint(**values)


def _binding_soft_preference(**changes: object) -> SoftPreference:
    values: dict[str, object] = {
        "preference_id": _PREFERENCE_ID,
        "attribute_key": "brand",
        "operator": ComparisonOperator.EQ,
        "operand": _attribute(),
        "allowed_provenance": (ProvenanceLabel.CLAIMED,),
        **changes,
    }
    return SoftPreference(**values)


def test_golden_attribute_value_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_attribute_value_bytes(_attribute())

    assert encoded == _GOLDEN_ATTRIBUTE_BYTES
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_ATTRIBUTE_SHA256


def test_golden_hard_constraint_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_hard_constraint_bytes(_golden_hard_constraint())

    assert encoded == _GOLDEN_HARD_CONSTRAINT_BYTES
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_HARD_CONSTRAINT_SHA256


def test_golden_soft_preference_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_soft_preference_bytes(_golden_soft_preference())

    assert encoded == _GOLDEN_SOFT_PREFERENCE_BYTES
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_SOFT_PREFERENCE_SHA256


@pytest.mark.parametrize(
    ("encoded", "payload_type"),
    [
        (_GOLDEN_ATTRIBUTE_BYTES, "attribute_value_v1"),
        (_GOLDEN_HARD_CONSTRAINT_BYTES, "hard_constraint_v1"),
        (_GOLDEN_SOFT_PREFERENCE_BYTES, "soft_preference_v1"),
    ],
)
def test_canonical_envelopes_are_exact_compact_utf8(
    encoded: bytes,
    payload_type: str,
) -> None:
    envelope = json.loads(encoded)

    assert set(envelope) == {"canonicalization_version", "payload", "payload_type"}
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == payload_type
    assert envelope["payload"]["schema_version"] == "1"
    assert encoded.decode("utf-8").encode("utf-8") == encoded
    assert b" " not in encoded
    assert b"\n" not in encoded


def test_attribute_value_projection_binds_every_field() -> None:
    envelope = json.loads(canonical_attribute_value_bytes(_attribute()))

    assert envelope["payload"] == {
        "attribute_value_version": "attribute-value-v1",
        "schema_version": "1",
        "value": "clear",
        "value_type": "string",
    }


def test_constraint_projections_bind_nested_attribute_and_uppercase_provenance() -> None:
    hard_payload = json.loads(canonical_hard_constraint_bytes(_golden_hard_constraint()))["payload"]
    soft_payload = json.loads(canonical_soft_preference_bytes(_golden_soft_preference()))["payload"]

    assert hard_payload["operand"] == {
        "attribute_value_version": "attribute-value-v1",
        "schema_version": "1",
        "value": 16,
        "value_type": "integer",
    }
    assert hard_payload["allowed_provenance"] == ["ATTESTED", "PREDICTED", "VERIFIED"]
    assert soft_payload["operand"] == {
        "attribute_value_version": "attribute-value-v1",
        "schema_version": "1",
        "value": "clear",
        "value_type": "string",
    }
    assert soft_payload["allowed_provenance"] == ["CLAIMED", "VERIFIED"]


def test_attribute_value_serialization_is_deterministic_and_preserves_utf8() -> None:
    attribute = _attribute(AttributeValueType.STRING, "café")

    first = canonical_attribute_value_bytes(attribute)
    second = canonical_attribute_value_bytes(attribute)

    assert first == second
    assert "café".encode() in first
    assert b"\\u00e9" not in first


def test_provenance_input_order_does_not_change_constraint_bytes() -> None:
    forward = (ProvenanceLabel.ATTESTED, ProvenanceLabel.VERIFIED)
    reverse = tuple(reversed(forward))

    assert canonical_hard_constraint_bytes(
        _binding_hard_constraint(allowed_provenance=forward)
    ) == canonical_hard_constraint_bytes(_binding_hard_constraint(allowed_provenance=reverse))
    assert canonical_soft_preference_bytes(
        _binding_soft_preference(allowed_provenance=forward)
    ) == canonical_soft_preference_bytes(_binding_soft_preference(allowed_provenance=reverse))


def test_every_hard_constraint_decision_field_changes_bytes() -> None:
    original = canonical_hard_constraint_bytes(_binding_hard_constraint())
    changed = (
        _binding_hard_constraint(constraint_id=_OTHER_CONSTRAINT_ID),
        _binding_hard_constraint(attribute_key="memory_gb"),
        _binding_hard_constraint(operator=ComparisonOperator.NE),
        _binding_hard_constraint(operand=_attribute(AttributeValueType.STRING, "16")),
        _binding_hard_constraint(operand=_attribute(AttributeValueType.INTEGER, 17)),
        _binding_hard_constraint(allowed_provenance=(ProvenanceLabel.ATTESTED,)),
    )

    assert all(canonical_hard_constraint_bytes(value) != original for value in changed)


def test_every_soft_preference_decision_field_changes_bytes() -> None:
    original = canonical_soft_preference_bytes(_binding_soft_preference())
    changed = (
        _binding_soft_preference(preference_id=_OTHER_PREFERENCE_ID),
        _binding_soft_preference(attribute_key="manufacturer"),
        _binding_soft_preference(operator=ComparisonOperator.NE),
        _binding_soft_preference(operand=_attribute(AttributeValueType.BOOLEAN, True)),
        _binding_soft_preference(operand=_attribute(AttributeValueType.STRING, "other")),
        _binding_soft_preference(allowed_provenance=(ProvenanceLabel.VERIFIED,)),
    )

    assert all(canonical_soft_preference_bytes(value) != original for value in changed)


@pytest.mark.parametrize(
    ("serializer", "wrong_value"),
    [
        (canonical_attribute_value_bytes, _golden_hard_constraint()),
        (canonical_hard_constraint_bytes, _attribute()),
        (canonical_soft_preference_bytes, _golden_hard_constraint()),
        (canonical_attribute_value_bytes, None),
        (canonical_hard_constraint_bytes, {}),
        (canonical_soft_preference_bytes, "preference"),
    ],
)
def test_serializers_reject_wrong_python_object_type(
    serializer: Callable[..., bytes],
    wrong_value: object,
) -> None:
    with pytest.raises(TypeError):
        serializer(wrong_value)
