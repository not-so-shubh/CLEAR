"""Strict persistence boundary for canonical production BuyerPolicyV2 bytes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import NoReturn, cast

from pydantic import ValidationError

from clear_market.canonical import CANONICALIZATION_VERSION, canonical_utc_datetime
from clear_market.commerce import (
    AttributeValueType,
    BuyerPolicyV2,
    ComparisonOperator,
    ProvenanceLabel,
    canonical_buyer_policy_v2_bytes,
)
from clear_market.domain import Currency


class CanonicalBuyerPolicyError(ValueError):
    """Persisted policy bytes failed strict canonical reconstruction."""


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonstandard_constant(_value: str) -> NoReturn:
    raise CanonicalBuyerPolicyError


def _canonical_timestamp(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise CanonicalBuyerPolicyError
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00").astimezone(UTC)
    except ValueError:
        raise CanonicalBuyerPolicyError from None
    if canonical_utc_datetime(parsed) != value:
        raise CanonicalBuyerPolicyError
    return parsed


def _attribute_value(value: object) -> object:
    if type(value) is not dict:
        return value
    converted = dict(value)
    value_type = converted.get("value_type")
    if type(value_type) is str:
        try:
            converted["value_type"] = AttributeValueType(value_type)
        except ValueError:
            pass
    return converted


def _rule(value: object, *, identifier: str) -> object:
    if type(value) is not dict:
        return value
    converted = dict(value)
    if identifier not in converted:
        return converted
    operator = converted.get("operator")
    if type(operator) is str:
        try:
            converted["operator"] = ComparisonOperator(operator)
        except ValueError:
            pass
    converted["operand"] = _attribute_value(converted.get("operand"))
    allowed = converted.get("allowed_provenance")
    if type(allowed) is list:
        normalized = []
        for label in allowed:
            if type(label) is str:
                try:
                    label = ProvenanceLabel(label)
                except ValueError:
                    pass
            normalized.append(label)
        converted["allowed_provenance"] = tuple(normalized)
    return converted


def _market_spec(value: object) -> object:
    if type(value) is not dict:
        return value
    converted = dict(value)
    hard = converted.get("hard_constraints")
    if type(hard) is list:
        converted["hard_constraints"] = tuple(
            _rule(item, identifier="constraint_id") for item in hard
        )
    soft = converted.get("soft_preferences")
    if type(soft) is list:
        converted["soft_preferences"] = tuple(
            _rule(item, identifier="preference_id") for item in soft
        )
    return converted


def _policy_payload(value: dict[str, object]) -> dict[str, object]:
    converted = dict(value)
    converted["market_spec"] = _market_spec(converted.get("market_spec"))
    money = converted.get("max_total_payment")
    if type(money) is dict:
        normalized_money = dict(money)
        currency = normalized_money.get("currency")
        if type(currency) is str:
            try:
                normalized_money["currency"] = Currency(currency)
            except ValueError:
                pass
        converted["max_total_payment"] = normalized_money
    eligible = converted.get("eligible_merchant_ids")
    if type(eligible) is list:
        converted["eligible_merchant_ids"] = tuple(eligible)
    converted["offer_deadline"] = _canonical_timestamp(converted.get("offer_deadline"))
    return converted


def parse_canonical_buyer_policy_v2(data: bytes) -> BuyerPolicyV2:
    """Reconstruct a policy and require exact canonical byte equality."""
    if type(data) is not bytes:
        raise TypeError("data must be exactly bytes")
    try:
        parsed = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateKeyError,
        CanonicalBuyerPolicyError,
        RecursionError,
        ValueError,
    ):
        raise CanonicalBuyerPolicyError from None
    if type(parsed) is not dict or set(parsed) != {
        "canonicalization_version",
        "payload_type",
        "payload",
    }:
        raise CanonicalBuyerPolicyError
    envelope = cast(dict[str, object], parsed)
    if (
        envelope["canonicalization_version"] != CANONICALIZATION_VERSION
        or envelope["payload_type"] != "buyer_policy_v2"
        or type(envelope["payload"]) is not dict
    ):
        raise CanonicalBuyerPolicyError
    try:
        policy = BuyerPolicyV2.model_validate(
            _policy_payload(cast(dict[str, object], envelope["payload"]))
        )
    except (CanonicalBuyerPolicyError, ValidationError, RecursionError):
        raise CanonicalBuyerPolicyError from None
    if canonical_buyer_policy_v2_bytes(policy) != data:
        raise CanonicalBuyerPolicyError
    return policy
