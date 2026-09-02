import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    ComparisonOperator,
    HardConstraint,
    MarketSpecV2,
    ProvenanceLabel,
    SoftPreference,
    canonical_buyer_policy_v2_bytes,
    canonical_market_spec_v2_bytes,
)
from clear_market.domain import Money

_MARKET_ID = "25000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "25000000-0000-4000-8000-000000000002"
_BUYER_ID = "26000000-0000-4000-8000-000000000001"
_OTHER_BUYER_ID = "26000000-0000-4000-8000-000000000002"
_HARD_ID = "27000000-0000-4000-8000-000000000001"
_OTHER_HARD_ID = "27000000-0000-4000-8000-000000000002"
_SOFT_ID = "27000000-0000-4000-8000-000000000003"
_OTHER_SOFT_ID = "27000000-0000-4000-8000-000000000004"
_DEADLINE = datetime(2027, 1, 2, 12, 0, 0, 123_456, tzinfo=UTC)

_GOLDEN_MARKET_SPEC_V2_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"buyer_id":'
    b'"26000000-0000-4000-8000-000000000001","hard_constraints":[{'
    b'"allowed_provenance":["ATTESTED","VERIFIED"],"attribute_key":"ram_gb",'
    b'"constraint_id":"27000000-0000-4000-8000-000000000001",'
    b'"constraint_primitives_version":"constraint-primitives-v1","operand":{'
    b'"attribute_value_version":"attribute-value-v1","schema_version":"1","value":16,'
    b'"value_type":"integer"},"operator":"gte","schema_version":"1"}],"market_id":'
    b'"25000000-0000-4000-8000-000000000001","market_spec_version":"market-spec-v2",'
    b'"max_winners":2,"minimum_acceptable_quantity":6,"requested_quantity":10,'
    b'"schema_version":"2","soft_preferences":[{"allowed_provenance":'
    b'["CLAIMED","VERIFIED"],"attribute_key":"brand","constraint_primitives_version":'
    b'"constraint-primitives-v1","operand":{"attribute_value_version":'
    b'"attribute-value-v1","schema_version":"1","value":"clear","value_type":"string"},'
    b'"operator":"eq","preference_id":"27000000-0000-4000-8000-000000000003",'
    b'"schema_version":"1"}]},"payload_type":"market_spec_v2"}'
)
_GOLDEN_BUYER_POLICY_V2_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"buyer_policy_version":'
    b'"buyer-policy-v2","eligible_merchant_ids":['
    b'"28000000-0000-4000-8000-000000000001",'
    b'"28000000-0000-4000-8000-000000000002",'
    b'"28000000-0000-4000-8000-000000000003"],"market_spec":{"buyer_id":'
    b'"26000000-0000-4000-8000-000000000001","hard_constraints":[{'
    b'"allowed_provenance":["ATTESTED","VERIFIED"],"attribute_key":"ram_gb",'
    b'"constraint_id":"27000000-0000-4000-8000-000000000001",'
    b'"constraint_primitives_version":"constraint-primitives-v1","operand":{'
    b'"attribute_value_version":"attribute-value-v1","schema_version":"1","value":16,'
    b'"value_type":"integer"},"operator":"gte","schema_version":"1"}],"market_id":'
    b'"25000000-0000-4000-8000-000000000001","market_spec_version":"market-spec-v2",'
    b'"max_winners":2,"minimum_acceptable_quantity":6,"requested_quantity":10,'
    b'"schema_version":"2","soft_preferences":[{"allowed_provenance":'
    b'["CLAIMED","VERIFIED"],"attribute_key":"brand","constraint_primitives_version":'
    b'"constraint-primitives-v1","operand":{"attribute_value_version":'
    b'"attribute-value-v1","schema_version":"1","value":"clear","value_type":"string"},'
    b'"operator":"eq","preference_id":"27000000-0000-4000-8000-000000000003",'
    b'"schema_version":"1"}]},"max_total_payment":{"amount_paise":500000,'
    b'"currency":"INR"},"mechanism_version":"heterogeneous-mechanism-test-v1",'
    b'"objective_version":"heterogeneous-objective-test-v1","offer_deadline":'
    b'"2027-01-02T12:00:00.123456Z","schema_version":"2"},'
    b'"payload_type":"buyer_policy_v2"}'
)

_GOLDEN_MARKET_SPEC_V2_SHA256 = "435cd2518a1b38a4855b8985ecd1ecfc2883444bd9ffa9cd889edf6468218ff5"
_GOLDEN_BUYER_POLICY_V2_SHA256 = "67aeacb34e65648d2ee031d8f83a59f2d85618635a29a1d0a7c2f710a691827d"


def _merchant_id(index: int) -> str:
    return f"28000000-0000-4000-8000-{index:012x}"


def _hard_constraint(
    constraint_id: str = _HARD_ID,
    *,
    value: int = 16,
    provenance: tuple[ProvenanceLabel, ...] = (
        ProvenanceLabel.VERIFIED,
        ProvenanceLabel.ATTESTED,
    ),
) -> HardConstraint:
    return HardConstraint(
        constraint_id=constraint_id,
        attribute_key="ram_gb",
        operator=ComparisonOperator.GTE,
        operand=AttributeValue(value_type=AttributeValueType.INTEGER, value=value),
        allowed_provenance=provenance,
    )


def _soft_preference(
    preference_id: str = _SOFT_ID,
    *,
    value: str = "clear",
    provenance: tuple[ProvenanceLabel, ...] = (
        ProvenanceLabel.VERIFIED,
        ProvenanceLabel.CLAIMED,
    ),
) -> SoftPreference:
    return SoftPreference(
        preference_id=preference_id,
        attribute_key="brand",
        operator=ComparisonOperator.EQ,
        operand=AttributeValue(value_type=AttributeValueType.STRING, value=value),
        allowed_provenance=provenance,
    )


def _market(**changes: object) -> MarketSpecV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_id": _BUYER_ID,
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 6,
        "max_winners": 2,
        "hard_constraints": (_hard_constraint(),),
        "soft_preferences": (_soft_preference(),),
        **changes,
    }
    return MarketSpecV2(**values)


def _policy(**changes: object) -> BuyerPolicyV2:
    values: dict[str, object] = {
        "market_spec": _market(),
        "max_total_payment": Money(amount_paise=500_000),
        "eligible_merchant_ids": (_merchant_id(3), _merchant_id(1), _merchant_id(2)),
        "offer_deadline": _DEADLINE,
        "mechanism_version": "heterogeneous-mechanism-test-v1",
        "objective_version": "heterogeneous-objective-test-v1",
        **changes,
    }
    return BuyerPolicyV2(**values)


def test_golden_market_spec_v2_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_market_spec_v2_bytes(_market())

    assert encoded == _GOLDEN_MARKET_SPEC_V2_BYTES
    assert len(encoded) == 1_040
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_MARKET_SPEC_V2_SHA256


def test_golden_buyer_policy_v2_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_buyer_policy_v2_bytes(_policy())

    assert encoded == _GOLDEN_BUYER_POLICY_V2_BYTES
    assert len(encoded) == 1_478
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_BUYER_POLICY_V2_SHA256


@pytest.mark.parametrize(
    ("encoded", "payload_type"),
    [
        (_GOLDEN_MARKET_SPEC_V2_BYTES, "market_spec_v2"),
        (_GOLDEN_BUYER_POLICY_V2_BYTES, "buyer_policy_v2"),
    ],
)
def test_v2_envelopes_are_exact_compact_utf8(encoded: bytes, payload_type: str) -> None:
    envelope = json.loads(encoded)

    assert set(envelope) == {"canonicalization_version", "payload", "payload_type"}
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == payload_type
    assert envelope["payload"]["schema_version"] == "2"
    assert encoded.decode("utf-8").encode("utf-8") == encoded
    assert b" " not in encoded
    assert b"\n" not in encoded


def test_market_projection_is_explicit_and_nested_without_envelopes() -> None:
    payload = json.loads(canonical_market_spec_v2_bytes(_market()))["payload"]

    assert set(payload) == {
        "schema_version",
        "market_spec_version",
        "market_id",
        "buyer_id",
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "hard_constraints",
        "soft_preferences",
    }
    assert set(payload["hard_constraints"][0]) == {
        "schema_version",
        "constraint_primitives_version",
        "constraint_id",
        "attribute_key",
        "operator",
        "operand",
        "allowed_provenance",
    }
    assert set(payload["soft_preferences"][0]) == {
        "schema_version",
        "constraint_primitives_version",
        "preference_id",
        "attribute_key",
        "operator",
        "operand",
        "allowed_provenance",
    }
    assert set(payload["hard_constraints"][0]["operand"]) == {
        "schema_version",
        "attribute_value_version",
        "value_type",
        "value",
    }
    assert "canonicalization_version" not in payload["hard_constraints"][0]
    assert "payload_type" not in payload["soft_preferences"][0]


def test_policy_projection_is_explicit_with_exact_money_and_deadline() -> None:
    payload = json.loads(canonical_buyer_policy_v2_bytes(_policy()))["payload"]

    assert set(payload) == {
        "schema_version",
        "buyer_policy_version",
        "market_spec",
        "max_total_payment",
        "eligible_merchant_ids",
        "offer_deadline",
        "mechanism_version",
        "objective_version",
    }
    assert payload["buyer_policy_version"] == "buyer-policy-v2"
    assert payload["market_spec"]["market_spec_version"] == "market-spec-v2"
    assert payload["max_total_payment"] == {"amount_paise": 500_000, "currency": "INR"}
    assert payload["offer_deadline"] == "2027-01-02T12:00:00.123456Z"


def test_market_serialization_preserves_utf8() -> None:
    market = _market(soft_preferences=(_soft_preference(value="café"),))
    encoded = canonical_market_spec_v2_bytes(market)

    assert "café".encode() in encoded
    assert b"\\u00e9" not in encoded


def test_market_serialization_is_deterministic() -> None:
    market = _market()

    assert canonical_market_spec_v2_bytes(market) == canonical_market_spec_v2_bytes(market)


def test_policy_serialization_is_deterministic() -> None:
    policy = _policy()

    assert canonical_buyer_policy_v2_bytes(policy) == canonical_buyer_policy_v2_bytes(policy)


def test_semantically_unordered_market_inputs_produce_identical_bytes() -> None:
    hard_a = _hard_constraint(_HARD_ID)
    hard_b = _hard_constraint(_OTHER_HARD_ID, provenance=tuple(reversed(hard_a.allowed_provenance)))
    soft_a = _soft_preference(_SOFT_ID)
    soft_b = _soft_preference(
        _OTHER_SOFT_ID,
        provenance=tuple(reversed(soft_a.allowed_provenance)),
    )
    forward = _market(
        hard_constraints=(hard_a, hard_b),
        soft_preferences=(soft_a, soft_b),
    )
    reverse = _market(
        hard_constraints=(hard_b, hard_a),
        soft_preferences=(soft_b, soft_a),
    )

    assert canonical_market_spec_v2_bytes(forward) == canonical_market_spec_v2_bytes(reverse)


def test_merchant_input_order_does_not_change_policy_bytes() -> None:
    forward = (_merchant_id(1), _merchant_id(2), _merchant_id(3))
    reverse = tuple(reversed(forward))

    assert canonical_buyer_policy_v2_bytes(
        _policy(eligible_merchant_ids=forward)
    ) == canonical_buyer_policy_v2_bytes(_policy(eligible_merchant_ids=reverse))


def test_nested_provenance_is_serialized_in_canonical_label_order() -> None:
    payload = json.loads(canonical_market_spec_v2_bytes(_market()))["payload"]

    assert payload["hard_constraints"][0]["allowed_provenance"] == ["ATTESTED", "VERIFIED"]
    assert payload["soft_preferences"][0]["allowed_provenance"] == ["CLAIMED", "VERIFIED"]


def test_every_market_allocation_field_changes_bytes() -> None:
    original = canonical_market_spec_v2_bytes(_market())
    changed = (
        _market(market_id=_OTHER_MARKET_ID),
        _market(buyer_id=_OTHER_BUYER_ID),
        _market(requested_quantity=11),
        _market(minimum_acceptable_quantity=5),
        _market(max_winners=3),
        _market(hard_constraints=(_hard_constraint(value=32),)),
        _market(soft_preferences=(_soft_preference(value="other"),)),
    )

    assert all(canonical_market_spec_v2_bytes(value) != original for value in changed)


def test_every_policy_allocation_field_changes_bytes() -> None:
    original = canonical_buyer_policy_v2_bytes(_policy())
    changed = (
        _policy(market_spec=_market(market_id=_OTHER_MARKET_ID)),
        _policy(max_total_payment=Money(amount_paise=500_001)),
        _policy(eligible_merchant_ids=(_merchant_id(1), _merchant_id(2), _merchant_id(4))),
        _policy(offer_deadline=_DEADLINE + timedelta(microseconds=1)),
        _policy(mechanism_version="different-mechanism-test-v1"),
        _policy(objective_version="different-objective-test-v1"),
    )

    assert all(canonical_buyer_policy_v2_bytes(value) != original for value in changed)


@pytest.mark.parametrize(
    ("serializer", "wrong_value"),
    [
        (canonical_market_spec_v2_bytes, _policy()),
        (canonical_market_spec_v2_bytes, None),
        (canonical_buyer_policy_v2_bytes, _market()),
        (canonical_buyer_policy_v2_bytes, {}),
    ],
)
def test_v2_serializers_reject_wrong_python_object_type(
    serializer: Callable[..., bytes],
    wrong_value: object,
) -> None:
    with pytest.raises(TypeError):
        serializer(wrong_value)
