"""Strict application-authorized Razorpay Route mapping artifacts."""

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
from clear_market.execution import ExecutionPlanV1

RAZORPAY_LINKED_ACCOUNT_BINDING_V1_VERSION: Final[str] = "razorpay-linked-account-binding-v1"
RAZORPAY_ROUTE_MAPPING_REQUEST_V1_VERSION: Final[str] = "razorpay-route-mapping-request-v1"
RAZORPAY_ROUTE_TRANSFER_LINE_V1_VERSION: Final[str] = "razorpay-route-transfer-line-v1"
RAZORPAY_ROUTE_MAPPING_PLAN_V1_VERSION: Final[str] = "razorpay-route-mapping-plan-v1"
RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION: Final[
    Literal["sha256-razorpay-route-mapping-request-v1-clear-json-v1"]
] = "sha256-razorpay-route-mapping-request-v1-clear-json-v1"

_RECIPIENT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_.:-]{0,127}", flags=re.ASCII)
_RAZORPAY_ACCOUNT_ID_PATTERN = re.compile(r"acc_[A-Za-z0-9]{1,14}", flags=re.ASCII)
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def _recipient_id(value: object) -> str:
    if type(value) is not str or _RECIPIENT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("recipient ID is not canonical")
    return value


def _razorpay_account_id(value: object) -> str:
    if type(value) is not str or _RAZORPAY_ACCOUNT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("Razorpay linked account ID is not canonical")
    return value


def _sha256_hex(value: object) -> str:
    if type(value) is not str or _SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("fingerprint must be lowercase SHA-256 hex")
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


def _fresh_money(value: object) -> Money:
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


def _fresh_execution_plan(value: object) -> ExecutionPlanV1:
    return _fresh_exact_model(
        value,
        ExecutionPlanV1,
        "execution_plan must be a valid exact ExecutionPlanV1",
    )


type _RecipientId = Annotated[str, BeforeValidator(_recipient_id)]
type _RazorpayAccountId = Annotated[str, BeforeValidator(_razorpay_account_id)]
type _Sha256Hex = Annotated[str, BeforeValidator(_sha256_hex)]
type _ExactMoney = Annotated[Money, BeforeValidator(_fresh_money)]
type _AllocationLineIndex = Annotated[int, Field(strict=True, ge=0)]
type _ExactExecutionPlan = Annotated[ExecutionPlanV1, BeforeValidator(_fresh_execution_plan)]


class RazorpayLinkedAccountBindingStateV1(StrEnum):
    """CLEAR application-routing state, not Razorpay provider account status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class RazorpayLinkedAccountBindingV1(BaseModel):
    """Trusted explicit application routing input, not provider-side account proof.

    Slice 21B treats recipient-to-Razorpay-linked-account bindings as trusted explicit application
    routing inputs. It validates deterministic identity, state, time, and one-to-one mapping
    constraints, but does not establish an external cryptographic authorization protocol for those
    bindings. It is not evidence of Money Governor approval.

    An accepted 21B mapping does not prove that the Razorpay Linked Account exists, belongs to the
    platform, has completed KYC or cooling-period requirements, is transfer-enabled, or is
    settlement-ready.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_linked_account_binding_version: Literal["razorpay-linked-account-binding-v1"] = (
        "razorpay-linked-account-binding-v1"
    )
    binding_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    recipient_id: _RecipientId
    razorpay_account_id: _RazorpayAccountId
    state: RazorpayLinkedAccountBindingStateV1
    valid_from: UTCDateTime
    valid_until: UTCDateTime

    @model_validator(mode="after")
    def _validate_interval(self) -> Self:
        if self.valid_from > self.valid_until:
            raise ValueError("linked account binding validity interval is inverted")
        return self


def _fresh_bindings(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("linked account bindings must be supplied as an exact tuple")
    return tuple(
        _fresh_exact_model(
            binding,
            RazorpayLinkedAccountBindingV1,
            "linked account bindings must contain valid exact values",
        )
        for binding in cast(tuple[object, ...], value)
    )


type _LinkedAccountBindings = Annotated[
    tuple[RazorpayLinkedAccountBindingV1, ...],
    BeforeValidator(_fresh_bindings),
    Field(min_length=1, max_length=MAX_SELLERS),
]


class RazorpayRouteMappingRequestV1(BaseModel):
    """Complete deterministic routing request without provider-action authority."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_route_mapping_request_version: Literal["razorpay-route-mapping-request-v1"] = (
        "razorpay-route-mapping-request-v1"
    )
    execution_plan: _ExactExecutionPlan
    linked_account_bindings: _LinkedAccountBindings

    @field_validator("linked_account_bindings")
    @classmethod
    def _validate_and_normalize_bindings(
        cls,
        bindings: tuple[RazorpayLinkedAccountBindingV1, ...],
    ) -> tuple[RazorpayLinkedAccountBindingV1, ...]:
        binding_ids = tuple(binding.binding_id for binding in bindings)
        merchant_ids = tuple(binding.merchant_id for binding in bindings)
        recipient_ids = tuple(binding.recipient_id for binding in bindings)
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("linked account binding IDs must be unique")
        if len(set(merchant_ids)) != len(merchant_ids):
            raise ValueError("linked account binding merchant IDs must be unique")
        if len(set(recipient_ids)) != len(recipient_ids):
            raise ValueError("linked account binding recipient IDs must be unique")
        return tuple(sorted(bindings, key=lambda binding: binding.merchant_id))


class RazorpayRouteTransferLineV1(BaseModel):
    """Provider-routing projection of one provider-neutral execution transfer line."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_route_transfer_line_version: Literal["razorpay-route-transfer-line-v1"] = (
        "razorpay-route-transfer-line-v1"
    )
    allocation_line_index: _AllocationLineIndex
    offer_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    sku_id: CanonicalUUID4
    recipient_authorization_id: CanonicalUUID4
    recipient_id: _RecipientId
    linked_account_binding_id: CanonicalUUID4
    razorpay_account_id: _RazorpayAccountId
    allocated_quantity: PositiveQuantity
    transfer_amount: _ExactMoney


def _fresh_route_transfer_lines(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("route transfer lines must be supplied as an exact tuple")
    return tuple(
        _fresh_exact_model(
            line,
            RazorpayRouteTransferLineV1,
            "route transfer lines must contain valid exact values",
        )
        for line in cast(tuple[object, ...], value)
    )


type _RouteTransferLines = Annotated[
    tuple[RazorpayRouteTransferLineV1, ...],
    BeforeValidator(_fresh_route_transfer_lines),
    Field(min_length=1),
]


class RazorpayRouteMappingPlanV1(BaseModel):
    """Deterministic provider-routing mapping artifact, not money-movement authority.

    A later transfer side-effect path must independently establish the required Money Governor
    authorization, authenticated captured-payment evidence, and provider-side linked-account
    validity before moving money. Direct construction grants no provider authority.

    A future captured-payment Route transfer would map each line's account to
    razorpay_account_id, amount to transfer_amount.amount_paise, and currency to INR. Slice 21B
    neither serializes nor sends that future provider request.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_route_mapping_plan_version: Literal["razorpay-route-mapping-plan-v1"] = (
        "razorpay-route-mapping-plan-v1"
    )
    execution_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    execution_request_fingerprint_version: Literal["sha256-execution-request-v1-clear-json-v1"]
    execution_request_fingerprint_sha256: _Sha256Hex
    razorpay_route_mapping_fingerprint_version: Literal[
        "sha256-razorpay-route-mapping-request-v1-clear-json-v1"
    ] = "sha256-razorpay-route-mapping-request-v1-clear-json-v1"
    razorpay_route_mapping_fingerprint_sha256: _Sha256Hex
    order_amount: _ExactMoney
    transfer_lines: _RouteTransferLines

    @model_validator(mode="after")
    def _validate_plan(self) -> Self:
        indices = tuple(line.allocation_line_index for line in self.transfer_lines)
        if indices != tuple(range(len(self.transfer_lines))):
            raise ValueError("route transfer line indices must be exact, contiguous, and ordered")

        routes_by_merchant: dict[str, set[tuple[str, str, str]]] = {}
        recipients_by_account: dict[str, set[str]] = {}
        total = 0
        for line in self.transfer_lines:
            routes_by_merchant.setdefault(line.merchant_id, set()).add(
                (
                    line.recipient_id,
                    line.linked_account_binding_id,
                    line.razorpay_account_id,
                )
            )
            recipients_by_account.setdefault(line.razorpay_account_id, set()).add(line.recipient_id)
            total += line.transfer_amount.amount_paise
            if total > MAX_MONEY_PAISE:
                raise ValueError("route transfer total exceeds the money bound")
        if any(len(routes) != 1 for routes in routes_by_merchant.values()):
            raise ValueError("one route-plan merchant must map to one provider route")
        if any(len(recipients) != 1 for recipients in recipients_by_account.values()):
            raise ValueError("distinct recipients must not share one Razorpay linked account")
        if total != self.order_amount.amount_paise:
            raise ValueError("route transfer total does not match order amount")
        return self


def _fresh_route_mapping_request(value: object) -> RazorpayRouteMappingRequestV1:
    return _fresh_exact_model(
        value,
        RazorpayRouteMappingRequestV1,
        "request must be a valid exact RazorpayRouteMappingRequestV1",
    )
