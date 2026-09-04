"""Strict provider-neutral authorization inputs and immutable execution plans."""

import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_SELLERS,
    CanonicalUUID4,
    Currency,
    Money,
    PositiveQuantity,
    UTCDateTime,
)

MONEY_GOVERNOR_V1_VERSION: Final[str] = "money-governor-v1"
MARKET_EXECUTION_AUTHORIZATION_V1_VERSION: Final[str] = "market-execution-authorization-v1"
BUYER_FINANCIAL_AUTHORIZATION_V1_VERSION: Final[str] = "buyer-financial-authorization-v1"
MERCHANT_RECIPIENT_AUTHORIZATION_V1_VERSION: Final[str] = "merchant-recipient-authorization-v1"
EXECUTION_AUTHORIZATION_REQUEST_V1_VERSION: Final[str] = "execution-authorization-request-v1"
EXECUTION_TRANSFER_LINE_V1_VERSION: Final[str] = "execution-transfer-line-v1"
EXECUTION_PLAN_V1_VERSION: Final[str] = "execution-plan-v1"
EXECUTION_REQUEST_FINGERPRINT_V1_VERSION: Final[str] = "sha256-execution-request-v1-clear-json-v1"

_CERTIFICATE_DIGEST_VERSION: Final[str] = "sha256-allocation-certificate-v2-clear-json-v1"
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_RECIPIENT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_.:-]{0,127}", flags=re.ASCII)


def _validate_sha256_hex(value: object) -> str:
    if type(value) is not str or _SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("digest must be lowercase SHA-256 hex")
    return value


def _validate_recipient_id(value: object) -> str:
    if type(value) is not str or _RECIPIENT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("recipient ID is not canonical")
    return value


def _fresh_exact_model[ModelT: BaseModel](
    value: object,
    expected_type: type[ModelT],
    message: str,
) -> ModelT:
    if type(value) is not expected_type:
        raise ValueError(message)
    try:
        fields = {name: value.__dict__[name] for name in expected_type.model_fields}
        return expected_type.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(message) from None


def _fresh_exact_money(value: object) -> Money:
    if type(value) is not Money:
        raise ValueError("money must be a valid exact Money value")
    try:
        amount_paise = value.__dict__["amount_paise"]
        currency = value.__dict__["currency"]
    except (AttributeError, KeyError):
        raise ValueError("money must be a valid exact Money value") from None
    if type(amount_paise) is not int or type(currency) is not Currency:
        raise ValueError("money must be a valid exact Money value")
    try:
        return Money.model_validate(
            {
                "amount_paise": amount_paise,
                "currency": currency,
            }
        )
    except ValidationError:
        raise ValueError("money must be a valid exact Money value") from None


type _Sha256Hex = Annotated[str, BeforeValidator(_validate_sha256_hex)]
type _RecipientId = Annotated[str, BeforeValidator(_validate_recipient_id)]
type _ExactMoney = Annotated[Money, BeforeValidator(_fresh_exact_money)]


class MarketExecutionStateV1(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class MarketExecutionAuthorizationV1(BaseModel):
    """Trusted application authorization for executing one certificate-bound market."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    market_execution_authorization_version: Literal["market-execution-authorization-v1"] = (
        "market-execution-authorization-v1"
    )
    authorization_id: CanonicalUUID4
    market_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    state: MarketExecutionStateV1
    valid_from: UTCDateTime
    valid_until: UTCDateTime

    @model_validator(mode="after")
    def _validate_interval(self) -> Self:
        if self.valid_from > self.valid_until:
            raise ValueError("market authorization validity interval is inverted")
        return self


class BuyerFinancialAuthorizationV1(BaseModel):
    """Trusted application buyer authorization with an exact aggregate money ceiling."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    buyer_financial_authorization_version: Literal["buyer-financial-authorization-v1"] = (
        "buyer-financial-authorization-v1"
    )
    authorization_id: CanonicalUUID4
    buyer_id: CanonicalUUID4
    market_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    maximum_total_payment: _ExactMoney
    valid_from: UTCDateTime
    valid_until: UTCDateTime

    @model_validator(mode="after")
    def _validate_interval(self) -> Self:
        if self.valid_from > self.valid_until:
            raise ValueError("buyer authorization validity interval is inverted")
        return self


class MerchantRecipientAuthorizationV1(BaseModel):
    """Trusted application binding from one merchant to a provider-neutral recipient."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    merchant_recipient_authorization_version: Literal["merchant-recipient-authorization-v1"] = (
        "merchant-recipient-authorization-v1"
    )
    authorization_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    recipient_id: _RecipientId
    market_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    maximum_transfer: _ExactMoney
    valid_from: UTCDateTime
    valid_until: UTCDateTime

    @model_validator(mode="after")
    def _validate_interval(self) -> Self:
        if self.valid_from > self.valid_until:
            raise ValueError("recipient authorization validity interval is inverted")
        return self


def _fresh_market_authorization(value: object) -> MarketExecutionAuthorizationV1:
    return _fresh_exact_model(
        value,
        MarketExecutionAuthorizationV1,
        "market authorization must be a valid exact MarketExecutionAuthorizationV1",
    )


def _fresh_buyer_authorization(value: object) -> BuyerFinancialAuthorizationV1:
    return _fresh_exact_model(
        value,
        BuyerFinancialAuthorizationV1,
        "buyer authorization must be a valid exact BuyerFinancialAuthorizationV1",
    )


def _fresh_recipient_authorizations(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("recipient authorizations must be supplied as an exact tuple")
    return tuple(
        _fresh_exact_model(
            authorization,
            MerchantRecipientAuthorizationV1,
            "recipient authorizations must contain valid exact values",
        )
        for authorization in cast(tuple[object, ...], value)
    )


type _MarketAuthorization = Annotated[
    MarketExecutionAuthorizationV1,
    BeforeValidator(_fresh_market_authorization),
]
type _BuyerAuthorization = Annotated[
    BuyerFinancialAuthorizationV1,
    BeforeValidator(_fresh_buyer_authorization),
]
type _RecipientAuthorizations = Annotated[
    tuple[MerchantRecipientAuthorizationV1, ...],
    BeforeValidator(_fresh_recipient_authorizations),
    Field(min_length=1, max_length=MAX_SELLERS),
]


class ExecutionAuthorizationRequestV1(BaseModel):
    """Complete deterministic authorization input, excluding the caller's decision time.

    Slice 20B treats all three authorization objects as trusted explicit application inputs. It
    validates their deterministic consistency and limits but does not establish an external
    cryptographic identity or consent protocol for those authorization objects.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    execution_authorization_request_version: Literal["execution-authorization-request-v1"] = (
        "execution-authorization-request-v1"
    )
    execution_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    market_id: CanonicalUUID4
    market_execution_authorization: _MarketAuthorization
    buyer_financial_authorization: _BuyerAuthorization
    merchant_recipient_authorizations: _RecipientAuthorizations

    @field_validator("merchant_recipient_authorizations")
    @classmethod
    def _validate_and_normalize_recipients(
        cls,
        authorizations: tuple[MerchantRecipientAuthorizationV1, ...],
    ) -> tuple[MerchantRecipientAuthorizationV1, ...]:
        merchant_ids = tuple(value.merchant_id for value in authorizations)
        recipient_ids = tuple(value.recipient_id for value in authorizations)
        authorization_ids = tuple(value.authorization_id for value in authorizations)
        if len(set(merchant_ids)) != len(merchant_ids):
            raise ValueError("recipient authorization merchant IDs must be unique")
        if len(set(recipient_ids)) != len(recipient_ids):
            raise ValueError("recipient IDs must be unique")
        if len(set(authorization_ids)) != len(authorization_ids):
            raise ValueError("recipient authorization IDs must be unique")
        return tuple(sorted(authorizations, key=lambda value: value.merchant_id))

    @model_validator(mode="after")
    def _validate_nested_bindings(self) -> Self:
        if self.market_execution_authorization.market_id != self.market_id:
            raise ValueError("market authorization market does not match request")
        if self.buyer_financial_authorization.market_id != self.market_id:
            raise ValueError("buyer authorization market does not match request")
        if any(
            authorization.market_id != self.market_id
            for authorization in self.merchant_recipient_authorizations
        ):
            raise ValueError("recipient authorization market does not match request")

        nested: tuple[
            MarketExecutionAuthorizationV1
            | BuyerFinancialAuthorizationV1
            | MerchantRecipientAuthorizationV1,
            ...,
        ] = (
            self.market_execution_authorization,
            self.buyer_financial_authorization,
            *self.merchant_recipient_authorizations,
        )
        if any(
            authorization.certificate_digest_version != self.certificate_digest_version
            for authorization in nested
        ):
            raise ValueError("nested certificate digest version does not match request")
        if any(
            authorization.certificate_digest_sha256 != self.certificate_digest_sha256
            for authorization in nested
        ):
            raise ValueError("nested certificate digest does not match request")
        return self


def _fresh_transfer_lines(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("transfer lines must be supplied as an exact tuple")
    return tuple(
        _fresh_exact_model(
            line,
            ExecutionTransferLineV1,
            "transfer lines must contain valid exact ExecutionTransferLineV1 values",
        )
        for line in cast(tuple[object, ...], value)
    )


type _AllocationLineIndex = Annotated[int, Field(strict=True, ge=0)]


class ExecutionTransferLineV1(BaseModel):
    """One provider-neutral transfer obligation copied from a verified allocation line."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    execution_transfer_line_version: Literal["execution-transfer-line-v1"] = (
        "execution-transfer-line-v1"
    )
    allocation_line_index: _AllocationLineIndex
    offer_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    sku_id: CanonicalUUID4
    recipient_authorization_id: CanonicalUUID4
    recipient_id: _RecipientId
    allocated_quantity: PositiveQuantity
    transfer_amount: _ExactMoney


type _TransferLines = Annotated[
    tuple[ExecutionTransferLineV1, ...],
    BeforeValidator(_fresh_transfer_lines),
    Field(min_length=1),
]


class ExecutionPlanV1(BaseModel):
    """Immutable provider-neutral authority data produced by the Money Governor boundary.

    Direct construction is not a cryptographic attestation. The authorized system path is
    authorize_execution_v1, and future payment code must consume plans produced through that
    boundary.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    execution_plan_version: Literal["execution-plan-v1"] = "execution-plan-v1"
    money_governor_version: Literal["money-governor-v1"] = "money-governor-v1"
    execution_id: CanonicalUUID4
    certificate_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    market_id: CanonicalUUID4
    buyer_id: CanonicalUUID4
    market_execution_authorization_id: CanonicalUUID4
    buyer_financial_authorization_id: CanonicalUUID4
    execution_request_fingerprint_version: Literal["sha256-execution-request-v1-clear-json-v1"] = (
        "sha256-execution-request-v1-clear-json-v1"
    )
    execution_request_fingerprint_sha256: _Sha256Hex
    idempotency_key: str
    order_amount: _ExactMoney
    transfer_lines: _TransferLines

    @model_validator(mode="after")
    def _validate_plan(self) -> Self:
        if self.idempotency_key != f"clear.execution.v1:{self.execution_id}":
            raise ValueError("idempotency key does not match execution ID")
        indices = tuple(line.allocation_line_index for line in self.transfer_lines)
        if indices != tuple(range(len(self.transfer_lines))):
            raise ValueError("transfer line indices must be exact, contiguous, and ordered")

        offer_sku = tuple((line.offer_id, line.sku_id) for line in self.transfer_lines)
        merchant_sku = tuple((line.merchant_id, line.sku_id) for line in self.transfer_lines)
        if len(set(offer_sku)) != len(offer_sku):
            raise ValueError("transfer lines must use unique offer and SKU pairs")
        if len(set(merchant_sku)) != len(merchant_sku):
            raise ValueError("transfer lines must use unique merchant and SKU pairs")

        recipients_by_merchant: dict[str, set[str]] = {}
        authorizations_by_merchant: dict[str, set[str]] = {}
        total = 0
        for line in self.transfer_lines:
            recipients_by_merchant.setdefault(line.merchant_id, set()).add(line.recipient_id)
            authorizations_by_merchant.setdefault(line.merchant_id, set()).add(
                line.recipient_authorization_id
            )
            total += line.transfer_amount.amount_paise
            if total > MAX_MONEY_PAISE:
                raise ValueError("execution plan transfer total exceeds the money bound")
        if any(len(values) != 1 for values in recipients_by_merchant.values()):
            raise ValueError("one plan merchant must map to one recipient")
        if any(len(values) != 1 for values in authorizations_by_merchant.values()):
            raise ValueError("one plan merchant must map to one recipient authorization")
        if self.order_amount.amount_paise != total:
            raise ValueError("execution plan transfer total does not match order amount")
        return self


def _fresh_execution_authorization_request(value: object) -> ExecutionAuthorizationRequestV1:
    return _fresh_exact_model(
        value,
        ExecutionAuthorizationRequestV1,
        "request must be a valid exact ExecutionAuthorizationRequestV1",
    )
