"""Strict JSON boundary for untrusted merchant-offer model output."""

import json
from enum import StrEnum
from typing import NoReturn

from pydantic import ValidationError

from clear_market.ai.merchant_offer import (
    MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES,
    MerchantOfferProposalDecision,
    MerchantOfferProposalV1,
)


class MerchantOfferProposalParseFailureCode(StrEnum):
    INPUT_TOO_LARGE = "input_too_large"
    INVALID_TEXT = "invalid_text"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_PROPOSAL = "invalid_proposal"


class MerchantOfferProposalParseError(ValueError):
    """Stable merchant-proposal failure without decoder or validation prose."""

    __slots__ = ("_code",)

    def __init__(self, code: MerchantOfferProposalParseFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> MerchantOfferProposalParseFailureCode:
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


def _convert_candidate_root(value: dict[str, object]) -> dict[str, object]:
    converted = dict(value)
    decision = converted.get("decision")
    if type(decision) is str:
        try:
            converted["decision"] = MerchantOfferProposalDecision(decision)
        except ValueError:
            pass
    lines = converted.get("lines")
    if type(lines) is list:
        converted["lines"] = tuple(lines)
    return converted


def parse_merchant_offer_proposal_v1(output_text: str) -> MerchantOfferProposalV1:
    """Parse bounded model JSON without repair, coercion, or canonical-byte requirements."""
    if type(output_text) is not str:
        raise TypeError("output_text must be exactly a string")
    if "\x00" in output_text:
        raise MerchantOfferProposalParseError(MerchantOfferProposalParseFailureCode.INVALID_TEXT)
    try:
        encoded = output_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise MerchantOfferProposalParseError(
            MerchantOfferProposalParseFailureCode.INVALID_TEXT
        ) from None
    if len(encoded) > MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES:
        raise MerchantOfferProposalParseError(MerchantOfferProposalParseFailureCode.INPUT_TOO_LARGE)

    try:
        parsed = json.loads(
            output_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKeyError:
        raise MerchantOfferProposalParseError(
            MerchantOfferProposalParseFailureCode.DUPLICATE_KEY
        ) from None
    except (ValueError, RecursionError):
        raise MerchantOfferProposalParseError(
            MerchantOfferProposalParseFailureCode.INVALID_JSON
        ) from None

    if type(parsed) is not dict:
        raise MerchantOfferProposalParseError(
            MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL
        )

    try:
        return MerchantOfferProposalV1.model_validate(_convert_candidate_root(parsed))
    except (ValidationError, RecursionError):
        raise MerchantOfferProposalParseError(
            MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL
        ) from None
