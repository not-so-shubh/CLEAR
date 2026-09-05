"""Strict untrusted request models for the runtime product API."""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, MAX_SELLERS, MIN_SELLERS

_MAX_TEXT_CHARS = 256
_MAX_BUYER_TEXT_BYTES = 32_768

type PositiveQuantityInput = Annotated[int, Field(strict=True, ge=1, le=MAX_QUANTITY)]
type MoneyInput = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_PAISE)]
type WinnerCountInput = Annotated[int, Field(strict=True, ge=1, le=MAX_SELLERS)]


def _validate_text(value: str) -> str:
    if not value or len(value) > _MAX_TEXT_CHARS or "\x00" in value:
        raise ValueError("text is outside its accepted bound")
    return value


class CreateMerchantRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    display_name: str
    product_display_name: str
    merchant_sku: str
    inventory_quantity: PositiveQuantityInput
    unit_cost_basis_paise: MoneyInput
    minimum_margin_paise: MoneyInput
    max_quantity_per_offer: PositiveQuantityInput

    @field_validator("display_name", "product_display_name")
    @classmethod
    def _bounded_display_text(cls, value: str) -> str:
        return _validate_text(value)


class CreateMarketRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    requested_quantity: PositiveQuantityInput
    minimum_acceptable_quantity: PositiveQuantityInput
    max_winners: WinnerCountInput
    max_total_payment_paise: MoneyInput
    eligible_merchant_ids: Annotated[
        list[str], Field(min_length=MIN_SELLERS, max_length=MAX_SELLERS)
    ]
    offer_deadline: str

    @field_validator("eligible_merchant_ids")
    @classmethod
    def _unique_eligible_merchants(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("eligible merchant IDs must be unique")
        return value


class CreateBuyerDraftRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    buyer_text: str
    eligible_merchant_ids: Annotated[
        list[str], Field(min_length=MIN_SELLERS, max_length=MAX_SELLERS)
    ]
    offer_deadline: str

    @field_validator("buyer_text")
    @classmethod
    def _bounded_buyer_text(cls, value: str) -> str:
        if "\x00" in value or value.strip() == "":
            raise ValueError("buyer text must not contain NUL")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError("buyer text must be valid UTF-8") from error
        if not 1 <= len(encoded) <= _MAX_BUYER_TEXT_BYTES:
            raise ValueError("buyer text is outside its UTF-8 byte bound")
        return value

    @field_validator("eligible_merchant_ids")
    @classmethod
    def _unique_draft_merchants(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("eligible merchant IDs must be unique")
        return value


class SubmitOfferRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    merchant_id: str
    proposed_quantity: PositiveQuantityInput
    proposed_unit_price_paise: MoneyInput


class CloseMarketRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ProductRequestError(ValueError):
    """An untrusted request failed strict JSON or schema validation."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProductRequestError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> object:
    raise ProductRequestError(f"non-JSON number is not accepted: {value}")


def parse_product_json[RequestT: BaseModel](data: bytes, model_type: type[RequestT]) -> RequestT:
    """Parse one strict JSON object without duplicate keys or type coercion."""
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_json_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ProductRequestError) as error:
        raise ProductRequestError("request body must be strict JSON") from error
    if type(value) is not dict:
        raise ProductRequestError("request body must be a JSON object")
    try:
        return model_type.model_validate(value)
    except ValidationError as error:
        raise ProductRequestError("request body does not match the product API schema") from error
