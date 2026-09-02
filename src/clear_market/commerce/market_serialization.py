from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    canonical_utc_datetime,
)
from clear_market.commerce.constraints import HardConstraint, SoftPreference
from clear_market.commerce.market import BuyerPolicyV2, MarketSpecV2
from clear_market.commerce.primitives import AttributeValue


def _attribute_value_payload(value: AttributeValue) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "attribute_value_version": value.attribute_value_version,
        "value_type": value.value_type.value,
        "value": value.value,
    }


def _hard_constraint_payload(value: HardConstraint) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "constraint_primitives_version": value.constraint_primitives_version,
        "constraint_id": value.constraint_id,
        "attribute_key": value.attribute_key,
        "operator": value.operator.value,
        "operand": _attribute_value_payload(value.operand),
        "allowed_provenance": [label.value for label in value.allowed_provenance],
    }


def _soft_preference_payload(value: SoftPreference) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "constraint_primitives_version": value.constraint_primitives_version,
        "preference_id": value.preference_id,
        "attribute_key": value.attribute_key,
        "operator": value.operator.value,
        "operand": _attribute_value_payload(value.operand),
        "allowed_provenance": [label.value for label in value.allowed_provenance],
    }


def _market_spec_v2_payload(value: MarketSpecV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "market_spec_version": value.market_spec_version,
        "market_id": value.market_id,
        "buyer_id": value.buyer_id,
        "requested_quantity": value.requested_quantity,
        "minimum_acceptable_quantity": value.minimum_acceptable_quantity,
        "max_winners": value.max_winners,
        "hard_constraints": [
            _hard_constraint_payload(constraint) for constraint in value.hard_constraints
        ],
        "soft_preferences": [
            _soft_preference_payload(preference) for preference in value.soft_preferences
        ],
    }


def canonical_market_spec_v2_bytes(value: MarketSpecV2) -> bytes:
    """Serialize every allocation-relevant MarketSpecV2 field explicitly."""
    if not isinstance(value, MarketSpecV2):
        raise TypeError("value must be a MarketSpecV2")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "market_spec_v2",
            "payload": _market_spec_v2_payload(value),
        }
    )


def canonical_buyer_policy_v2_bytes(value: BuyerPolicyV2) -> bytes:
    """Serialize every allocation-relevant BuyerPolicyV2 field explicitly."""
    if not isinstance(value, BuyerPolicyV2):
        raise TypeError("value must be a BuyerPolicyV2")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "buyer_policy_v2",
            "payload": {
                "schema_version": value.schema_version,
                "buyer_policy_version": value.buyer_policy_version,
                "market_spec": _market_spec_v2_payload(value.market_spec),
                "max_total_payment": {
                    "amount_paise": value.max_total_payment.amount_paise,
                    "currency": value.max_total_payment.currency.value,
                },
                "eligible_merchant_ids": list(value.eligible_merchant_ids),
                "offer_deadline": canonical_utc_datetime(value.offer_deadline),
                "mechanism_version": value.mechanism_version,
                "objective_version": value.objective_version,
            },
        }
    )
