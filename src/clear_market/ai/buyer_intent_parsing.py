"""Strict JSON boundary for untrusted buyer-intent model output."""

import json
from enum import StrEnum
from typing import NoReturn

from pydantic import ValidationError

from clear_market.ai.buyer_intent import (
    MAX_BUYER_INTENT_JSON_BYTES,
    BuyerIntentCandidateV1,
)
from clear_market.commerce import AttributeValueType, ComparisonOperator, ProvenanceLabel


class BuyerIntentParseFailureCode(StrEnum):
    INPUT_TOO_LARGE = "input_too_large"
    INVALID_TEXT = "invalid_text"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_CANDIDATE = "invalid_candidate"


class BuyerIntentParseError(ValueError):
    """Stable buyer-intent parse failure without raw decoder or validation prose."""

    __slots__ = ("_code",)

    def __init__(self, code: BuyerIntentParseFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> BuyerIntentParseFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_json_constant(_: str) -> NoReturn:
    raise _InvalidJsonConstantError


def _convert_operator(value: object) -> object:
    if type(value) is str:
        try:
            return ComparisonOperator(value)
        except ValueError:
            pass
    return value


def _convert_value_type(value: object) -> object:
    if type(value) is str:
        try:
            return AttributeValueType(value)
        except ValueError:
            pass
    return value


def _convert_provenance(value: object) -> object:
    if type(value) is str:
        try:
            return ProvenanceLabel(value)
        except ValueError:
            pass
    return value


def _convert_rule(value: object) -> object:
    if type(value) is not dict:
        return value
    converted: dict[str, object] = dict(value)
    converted["operator"] = _convert_operator(converted.get("operator"))
    converted["value_type"] = _convert_value_type(converted.get("value_type"))

    allowed_provenance = converted.get("allowed_provenance")
    if type(allowed_provenance) is list:
        converted["allowed_provenance"] = tuple(
            _convert_provenance(label) for label in allowed_provenance
        )
    return converted


def _convert_candidate_root(value: dict[str, object]) -> dict[str, object]:
    converted = dict(value)
    for field_name in ("hard_constraints", "soft_preferences"):
        rules = converted.get(field_name)
        if type(rules) is list:
            converted[field_name] = tuple(_convert_rule(rule) for rule in rules)
    return converted


def parse_buyer_intent_candidate_v1(output_text: str) -> BuyerIntentCandidateV1:
    """Parse bounded model JSON without repair, coercion, or canonical-byte requirements."""
    if type(output_text) is not str:
        raise TypeError("output_text must be exactly a string")
    if "\x00" in output_text:
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.INVALID_TEXT)
    try:
        encoded = output_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.INVALID_TEXT) from None
    if len(encoded) > MAX_BUYER_INTENT_JSON_BYTES:
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.INPUT_TOO_LARGE)

    try:
        parsed = json.loads(
            output_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKeyError:
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.DUPLICATE_KEY) from None
    except (ValueError, RecursionError):
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.INVALID_JSON) from None

    if type(parsed) is not dict:
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.INVALID_CANDIDATE)

    try:
        return BuyerIntentCandidateV1.model_validate(_convert_candidate_root(parsed))
    except (ValidationError, RecursionError):
        raise BuyerIntentParseError(BuyerIntentParseFailureCode.INVALID_CANDIDATE) from None
