from clear_market.canonical import CANONICALIZATION_VERSION, canonical_json_bytes
from clear_market.commerce.constraints import HardConstraint, SoftPreference
from clear_market.commerce.primitives import AttributeValue


def _attribute_value_payload(value: AttributeValue) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "attribute_value_version": value.attribute_value_version,
        "value_type": value.value_type.value,
        "value": value.value,
    }


def canonical_attribute_value_bytes(value: AttributeValue) -> bytes:
    """Serialize every protected AttributeValue field in a versioned envelope."""
    if not isinstance(value, AttributeValue):
        raise TypeError("value must be an AttributeValue")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "attribute_value_v1",
            "payload": _attribute_value_payload(value),
        }
    )


def canonical_hard_constraint_bytes(value: HardConstraint) -> bytes:
    """Serialize every protected HardConstraint field in a versioned envelope."""
    if not isinstance(value, HardConstraint):
        raise TypeError("value must be a HardConstraint")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "hard_constraint_v1",
            "payload": {
                "schema_version": value.schema_version,
                "constraint_primitives_version": value.constraint_primitives_version,
                "constraint_id": value.constraint_id,
                "attribute_key": value.attribute_key,
                "operator": value.operator.value,
                "operand": _attribute_value_payload(value.operand),
                "allowed_provenance": [label.value for label in value.allowed_provenance],
            },
        }
    )


def canonical_soft_preference_bytes(value: SoftPreference) -> bytes:
    """Serialize every protected SoftPreference field in a versioned envelope."""
    if not isinstance(value, SoftPreference):
        raise TypeError("value must be a SoftPreference")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "soft_preference_v1",
            "payload": {
                "schema_version": value.schema_version,
                "constraint_primitives_version": value.constraint_primitives_version,
                "preference_id": value.preference_id,
                "attribute_key": value.attribute_key,
                "operator": value.operator.value,
                "operand": _attribute_value_payload(value.operand),
                "allowed_provenance": [label.value for label in value.allowed_provenance],
            },
        }
    )
