import json
from datetime import UTC, datetime
from typing import Final, cast

from clear_market.domain import BuyerPolicy

CANONICALIZATION_VERSION: Final[str] = "clear-json-v1"


class CanonicalizationError(ValueError):
    """Value cannot be represented by the CLEAR deterministic JSON contract."""


def _normalize_json_value(value: object) -> object:
    """Validate exact JSON types while preserving every defined sequence order."""
    if value is None:
        return None
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is str:
        return value
    if type(value) is list:
        list_items = cast(list[object], value)
        return [_normalize_json_value(item) for item in list_items]
    if type(value) is tuple:
        tuple_items = cast(tuple[object, ...], value)
        return [_normalize_json_value(item) for item in tuple_items]
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        normalized: dict[str, object] = {}
        for key, item in mapping.items():
            if type(key) is not str:
                raise CanonicalizationError
            normalized[key] = _normalize_json_value(item)
        return normalized
    raise CanonicalizationError


def canonical_json_bytes(value: object) -> bytes:
    """Serialize an already-projected JSON-like value using the frozen byte contract."""
    normalized = _normalize_json_value(value)
    try:
        serialized = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return serialized.encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CanonicalizationError from error


def canonical_utc_datetime(value: datetime) -> str:
    """Normalize an aware timestamp at the protocol boundary and emit fixed UTC text."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalizationError
    normalized = value.astimezone(UTC)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_buyer_policy_bytes(policy: BuyerPolicy) -> bytes:
    """Project every protected BuyerPolicy field into its versioned canonical envelope."""
    payload = {
        "schema_version": policy.schema_version,
        "market_spec": {
            "schema_version": policy.market_spec.schema_version,
            "market_id": policy.market_spec.market_id,
            "buyer_id": policy.market_spec.buyer_id,
            "requested_quantity": policy.market_spec.requested_quantity,
        },
        "max_total_payment": {
            "amount_paise": policy.max_total_payment.amount_paise,
            "currency": policy.max_total_payment.currency.value,
        },
        "reserve_unit_price": {
            "amount_paise": policy.reserve_unit_price.amount_paise,
            "currency": policy.reserve_unit_price.currency.value,
        },
        "eligible_merchants": [
            {
                "schema_version": merchant.schema_version,
                "merchant_id": merchant.merchant_id,
                "ed25519_public_key_hex": merchant.ed25519_public_key_hex,
            }
            for merchant in policy.eligible_merchants
        ],
        "bid_deadline": canonical_utc_datetime(policy.bid_deadline),
        "mechanism_version": policy.mechanism_version,
        "tie_break_rule": policy.tie_break_rule,
    }
    envelope = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload_type": "buyer_policy",
        "payload": payload,
    }
    return canonical_json_bytes(envelope)
