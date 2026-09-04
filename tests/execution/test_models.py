from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.execution as execution
from clear_market.domain import MAX_MONEY_PAISE, MAX_SELLERS, Currency, Money
from clear_market.execution import (
    BUYER_FINANCIAL_AUTHORIZATION_V1_VERSION,
    EXECUTION_AUTHORIZATION_REQUEST_V1_VERSION,
    EXECUTION_PLAN_V1_VERSION,
    EXECUTION_REQUEST_FINGERPRINT_V1_VERSION,
    EXECUTION_TRANSFER_LINE_V1_VERSION,
    MARKET_EXECUTION_AUTHORIZATION_V1_VERSION,
    MERCHANT_RECIPIENT_AUTHORIZATION_V1_VERSION,
    MONEY_GOVERNOR_V1_VERSION,
    BuyerFinancialAuthorizationV1,
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    ExecutionTransferLineV1,
    MarketExecutionAuthorizationV1,
    MarketExecutionStateV1,
    MerchantRecipientAuthorizationV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
)

_DIGEST_VERSION = "sha256-allocation-certificate-v2-clear-json-v1"
_DIGEST = "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
_TIME = datetime(2026, 9, 1, 11, 30, tzinfo=UTC)
_VALID_FROM = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
_VALID_UNTIL = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)
_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_MARKET_AUTHORIZATION_ID = "e2000000-0000-4000-8000-000000000001"
_BUYER_AUTHORIZATION_ID = "e3000000-0000-4000-8000-000000000001"
_MARKET_ID = "b1000000-0000-4000-8000-000000000001"
_BUYER_ID = "b2000000-0000-4000-8000-000000000001"
_CERTIFICATE_ID = "ba000000-0000-4000-8000-000000000001"
_CONFIG = {
    "frozen": True,
    "extra": "forbid",
    "strict": True,
    "revalidate_instances": "always",
}


def _uuid(namespace: int, index: int) -> str:
    return f"e{namespace}000000-0000-4000-8000-{index:012x}"


def _validated_copy[ModelT: BaseModel](model: ModelT, **changes: object) -> ModelT:
    fields = {name: model.__dict__[name] for name in type(model).model_fields}
    fields.update(changes)
    return type(model).model_validate(fields)


def _market_authorization(**changes: object) -> MarketExecutionAuthorizationV1:
    values: dict[str, object] = {
        "authorization_id": _MARKET_AUTHORIZATION_ID,
        "market_id": _MARKET_ID,
        "certificate_digest_version": _DIGEST_VERSION,
        "certificate_digest_sha256": _DIGEST,
        "state": MarketExecutionStateV1.EXECUTABLE,
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
        **changes,
    }
    return MarketExecutionAuthorizationV1(**values)


def _buyer_authorization(**changes: object) -> BuyerFinancialAuthorizationV1:
    values: dict[str, object] = {
        "authorization_id": _BUYER_AUTHORIZATION_ID,
        "buyer_id": _BUYER_ID,
        "market_id": _MARKET_ID,
        "certificate_digest_version": _DIGEST_VERSION,
        "certificate_digest_sha256": _DIGEST,
        "maximum_total_payment": Money(amount_paise=2_700),
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
        **changes,
    }
    return BuyerFinancialAuthorizationV1(**values)


def _recipient_authorization(index: int, **changes: object) -> MerchantRecipientAuthorizationV1:
    values: dict[str, object] = {
        "authorization_id": _uuid(4, index),
        "merchant_id": f"b3000000-{index:04x}-4000-8000-000000000001",
        "recipient_id": f"clear.recipient.m{index}",
        "market_id": _MARKET_ID,
        "certificate_digest_version": _DIGEST_VERSION,
        "certificate_digest_sha256": _DIGEST,
        "maximum_transfer": Money(amount_paise=1_500 if index == 1 else 1_200),
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
        **changes,
    }
    return MerchantRecipientAuthorizationV1(**values)


def _request(**changes: object) -> ExecutionAuthorizationRequestV1:
    values: dict[str, object] = {
        "execution_id": _EXECUTION_ID,
        "certificate_digest_version": _DIGEST_VERSION,
        "certificate_digest_sha256": _DIGEST,
        "market_id": _MARKET_ID,
        "market_execution_authorization": _market_authorization(),
        "buyer_financial_authorization": _buyer_authorization(),
        "merchant_recipient_authorizations": (
            _recipient_authorization(2),
            _recipient_authorization(1),
        ),
        **changes,
    }
    return ExecutionAuthorizationRequestV1(**values)


def _line(index: int, **changes: object) -> ExecutionTransferLineV1:
    values: dict[str, object] = {
        "allocation_line_index": index - 1,
        "offer_id": f"b8000000-{index:04x}-4000-8000-000000000001",
        "merchant_id": f"b3000000-{index:04x}-4000-8000-000000000001",
        "sku_id": f"b6000000-{index:04x}-4000-8000-000000000001",
        "recipient_authorization_id": _uuid(4, index),
        "recipient_id": f"clear.recipient.m{index}",
        "allocated_quantity": 3 if index == 1 else 2,
        "transfer_amount": Money(amount_paise=1_500 if index == 1 else 1_200),
        **changes,
    }
    return ExecutionTransferLineV1(**values)


def _plan(**changes: object) -> ExecutionPlanV1:
    values: dict[str, object] = {
        "execution_id": _EXECUTION_ID,
        "certificate_id": _CERTIFICATE_ID,
        "certificate_digest_version": _DIGEST_VERSION,
        "certificate_digest_sha256": _DIGEST,
        "market_id": _MARKET_ID,
        "buyer_id": _BUYER_ID,
        "market_execution_authorization_id": _MARKET_AUTHORIZATION_ID,
        "buyer_financial_authorization_id": _BUYER_AUTHORIZATION_ID,
        "execution_request_fingerprint_sha256": "a" * 64,
        "idempotency_key": f"clear.execution.v1:{_EXECUTION_ID}",
        "order_amount": Money(amount_paise=2_700),
        "transfer_lines": (_line(1), _line(2)),
        **changes,
    }
    return ExecutionPlanV1(**values)


def test_versions_and_public_api_are_exact() -> None:
    assert MONEY_GOVERNOR_V1_VERSION == "money-governor-v1"
    assert MARKET_EXECUTION_AUTHORIZATION_V1_VERSION == "market-execution-authorization-v1"
    assert BUYER_FINANCIAL_AUTHORIZATION_V1_VERSION == "buyer-financial-authorization-v1"
    assert MERCHANT_RECIPIENT_AUTHORIZATION_V1_VERSION == "merchant-recipient-authorization-v1"
    assert EXECUTION_AUTHORIZATION_REQUEST_V1_VERSION == "execution-authorization-request-v1"
    assert EXECUTION_TRANSFER_LINE_V1_VERSION == "execution-transfer-line-v1"
    assert EXECUTION_PLAN_V1_VERSION == "execution-plan-v1"
    assert EXECUTION_REQUEST_FINGERPRINT_V1_VERSION == ("sha256-execution-request-v1-clear-json-v1")
    assert execution.__all__ == (
        "MONEY_GOVERNOR_V1_VERSION",
        "MARKET_EXECUTION_AUTHORIZATION_V1_VERSION",
        "BUYER_FINANCIAL_AUTHORIZATION_V1_VERSION",
        "MERCHANT_RECIPIENT_AUTHORIZATION_V1_VERSION",
        "EXECUTION_AUTHORIZATION_REQUEST_V1_VERSION",
        "EXECUTION_TRANSFER_LINE_V1_VERSION",
        "EXECUTION_PLAN_V1_VERSION",
        "EXECUTION_REQUEST_FINGERPRINT_V1_VERSION",
        "MarketExecutionStateV1",
        "MarketExecutionAuthorizationV1",
        "BuyerFinancialAuthorizationV1",
        "MerchantRecipientAuthorizationV1",
        "ExecutionAuthorizationRequestV1",
        "ExecutionTransferLineV1",
        "ExecutionPlanV1",
        "MoneyGovernorFailureCode",
        "MoneyGovernorError",
        "canonical_execution_authorization_request_v1_bytes",
        "execution_request_fingerprint_v1",
        "authorize_execution_v1",
    )


def test_enum_order_and_values_are_exact() -> None:
    assert tuple(MarketExecutionStateV1) == (
        MarketExecutionStateV1.EXECUTABLE,
        MarketExecutionStateV1.PAUSED,
        MarketExecutionStateV1.CLOSED,
    )
    expected_failures = (
        "CERTIFICATE_NOT_VERIFIED",
        "ALLOCATION_NOT_EXECUTABLE",
        "EXECUTION_REQUEST_MISMATCH",
        "MARKET_NOT_EXECUTABLE",
        "MARKET_AUTHORIZATION_NOT_ACTIVE",
        "BUYER_AUTHORIZATION_MISMATCH",
        "BUYER_AUTHORIZATION_NOT_ACTIVE",
        "BUYER_BUDGET_EXCEEDED",
        "RECIPIENT_SET_MISMATCH",
        "RECIPIENT_AUTHORIZATION_NOT_ACTIVE",
        "RECIPIENT_TRANSFER_LIMIT_EXCEEDED",
        "EXECUTION_ID_CONFLICT",
        "CERTIFICATE_ALREADY_EXECUTED",
        "MARKET_ALREADY_EXECUTED",
    )
    assert tuple(member.name for member in MoneyGovernorFailureCode) == expected_failures
    assert tuple(member.value for member in MoneyGovernorFailureCode) == expected_failures


@pytest.mark.parametrize(
    ("model_type", "fields"),
    [
        (
            MarketExecutionAuthorizationV1,
            (
                "schema_version",
                "market_execution_authorization_version",
                "authorization_id",
                "market_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "state",
                "valid_from",
                "valid_until",
            ),
        ),
        (
            BuyerFinancialAuthorizationV1,
            (
                "schema_version",
                "buyer_financial_authorization_version",
                "authorization_id",
                "buyer_id",
                "market_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "maximum_total_payment",
                "valid_from",
                "valid_until",
            ),
        ),
        (
            MerchantRecipientAuthorizationV1,
            (
                "schema_version",
                "merchant_recipient_authorization_version",
                "authorization_id",
                "merchant_id",
                "recipient_id",
                "market_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "maximum_transfer",
                "valid_from",
                "valid_until",
            ),
        ),
        (
            ExecutionAuthorizationRequestV1,
            (
                "schema_version",
                "execution_authorization_request_version",
                "execution_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "market_id",
                "market_execution_authorization",
                "buyer_financial_authorization",
                "merchant_recipient_authorizations",
            ),
        ),
        (
            ExecutionTransferLineV1,
            (
                "schema_version",
                "execution_transfer_line_version",
                "allocation_line_index",
                "offer_id",
                "merchant_id",
                "sku_id",
                "recipient_authorization_id",
                "recipient_id",
                "allocated_quantity",
                "transfer_amount",
            ),
        ),
        (
            ExecutionPlanV1,
            (
                "schema_version",
                "execution_plan_version",
                "money_governor_version",
                "execution_id",
                "certificate_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "market_id",
                "buyer_id",
                "market_execution_authorization_id",
                "buyer_financial_authorization_id",
                "execution_request_fingerprint_version",
                "execution_request_fingerprint_sha256",
                "idempotency_key",
                "order_amount",
                "transfer_lines",
            ),
        ),
    ],
)
def test_model_fields_and_config_are_exact(
    model_type: type[BaseModel],
    fields: tuple[str, ...],
) -> None:
    assert tuple(model_type.model_fields) == fields
    assert model_type.model_config == _CONFIG


@pytest.mark.parametrize(
    "builder",
    [_market_authorization, _buyer_authorization, _recipient_authorization, _request, _line, _plan],
)
def test_models_are_frozen_versioned_and_forbid_extra(builder: Any) -> None:
    model = builder(1) if builder in {_recipient_authorization, _line} else builder()
    assert model.schema_version == "1"
    with pytest.raises(ValidationError):
        model.schema_version = "2"
    with pytest.raises(ValidationError):
        if builder in {_recipient_authorization, _line}:
            builder(1, extra="forbidden")
        else:
            builder(extra="forbidden")


@pytest.mark.parametrize(
    "builder", [_market_authorization, _buyer_authorization, _recipient_authorization]
)
def test_authorization_interval_is_inclusive_and_cannot_be_inverted(builder: Any) -> None:
    authorization = (
        builder(1, valid_from=_TIME, valid_until=_TIME)
        if builder is (_recipient_authorization)
        else builder(valid_from=_TIME, valid_until=_TIME)
    )
    assert authorization.valid_from == authorization.valid_until == _TIME
    with pytest.raises(ValidationError):
        if builder is _recipient_authorization:
            builder(1, valid_from=_TIME, valid_until=_TIME - timedelta(microseconds=1))
        else:
            builder(valid_from=_TIME, valid_until=_TIME - timedelta(microseconds=1))


@pytest.mark.parametrize(
    "recipient_id",
    ["recipient", "clear.recipient:merchant-1", "a", "a" + "0" * 127],
)
def test_recipient_id_accepts_exact_provider_neutral_grammar(recipient_id: str) -> None:
    assert _recipient_authorization(1, recipient_id=recipient_id).recipient_id == recipient_id


@pytest.mark.parametrize(
    "recipient_id",
    ["", " Recipient", "recipient ", "Recipient", ".recipient", "recipient/value", "é", "a" * 129],
)
def test_recipient_id_rejects_invalid_input_without_normalization(recipient_id: str) -> None:
    with pytest.raises(ValidationError):
        _recipient_authorization(1, recipient_id=recipient_id)


@pytest.mark.parametrize(
    "changes",
    [
        {"authorization_id": "E2000000-0000-4000-8000-000000000001"},
        {"market_id": "not-a-uuid"},
        {"certificate_digest_version": "other"},
        {"certificate_digest_sha256": "A" * 64},
        {"certificate_digest_sha256": "a" * 63},
    ],
)
def test_identifiers_digest_and_version_are_strict(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _market_authorization(**changes)


class _MoneySubclass(Money):
    pass


@pytest.mark.parametrize(
    ("builder", "field"),
    [
        (_buyer_authorization, "maximum_total_payment"),
        (_recipient_authorization, "maximum_transfer"),
        (_line, "transfer_amount"),
        (_plan, "order_amount"),
    ],
)
def test_nested_money_requires_fresh_exact_uncorrupted_money(builder: Any, field: str) -> None:
    valid = Money(amount_paise=2_700)
    invalid_values = (
        valid.model_dump(),
        _MoneySubclass(amount_paise=2_700),
        Money.model_construct(currency=Currency.INR),
        Money.model_construct(amount_paise="2700", currency=Currency.INR),
        Money.model_construct(amount_paise=2_700, currency="INR"),
    )
    for invalid in invalid_values:
        with pytest.raises(ValidationError):
            if builder in {_recipient_authorization, _line}:
                builder(1, **{field: cast(Any, invalid)})
            else:
                builder(**{field: cast(Any, invalid)})


def test_request_requires_exact_tuple_unique_values_and_canonical_merchant_order() -> None:
    first = _recipient_authorization(1)
    second = _recipient_authorization(2)
    request = _request(merchant_recipient_authorizations=(second, first))
    assert request.merchant_recipient_authorizations == (first, second)
    with pytest.raises(ValidationError):
        _request(merchant_recipient_authorizations=cast(Any, [first, second]))
    with pytest.raises(ValidationError):
        _request(merchant_recipient_authorizations=())
    with pytest.raises(ValidationError):
        _request(
            merchant_recipient_authorizations=tuple(
                _recipient_authorization(1, authorization_id=_uuid(4, index + 1))
                for index in range(MAX_SELLERS + 1)
            )
        )

    for duplicate in (
        (first, _recipient_authorization(2, merchant_id=first.merchant_id)),
        (first, _recipient_authorization(2, recipient_id=first.recipient_id)),
        (first, _recipient_authorization(2, authorization_id=first.authorization_id)),
    ):
        with pytest.raises(ValidationError):
            _request(merchant_recipient_authorizations=duplicate)


def test_request_nested_models_require_exact_type_and_fresh_validation() -> None:
    market = _market_authorization()
    with pytest.raises(ValidationError):
        _request(market_execution_authorization=market.model_dump())

    class MarketSubclass(MarketExecutionAuthorizationV1):
        pass

    with pytest.raises(ValidationError):
        _request(market_execution_authorization=MarketSubclass(**market.__dict__))
    malformed = MarketExecutionAuthorizationV1.model_construct(
        authorization_id=market.authorization_id
    )
    with pytest.raises(ValidationError):
        _request(market_execution_authorization=malformed)


@pytest.mark.parametrize("binding", ["market", "digest_version", "digest"])
def test_request_cross_nested_binding_is_exact(binding: str) -> None:
    market = _market_authorization()
    buyer = _buyer_authorization()
    recipient = _recipient_authorization(1)
    if binding == "market":
        market = _market_authorization(market_id=_uuid(9, 1))
    elif binding == "digest_version":
        market = MarketExecutionAuthorizationV1.model_construct(
            **{**market.__dict__, "certificate_digest_version": "other"}
        )
    elif binding == "digest":
        buyer = _buyer_authorization(certificate_digest_sha256="f" * 64)
    else:
        raise AssertionError(binding)
    with pytest.raises(ValidationError):
        _request(
            market_execution_authorization=market,
            buyer_financial_authorization=buyer,
            merchant_recipient_authorizations=(recipient,),
        )


def test_transfer_line_strict_quantities_indices_and_exact_fields() -> None:
    assert _line(1).allocation_line_index == 0
    for value in (-1, True, 0.0, "0"):
        with pytest.raises(ValidationError):
            _line(1, allocation_line_index=value)
    for value in (0, True, 1.0, "1"):
        with pytest.raises(ValidationError):
            _line(1, allocated_quantity=value)


def test_plan_requires_nonempty_exact_ordered_contiguous_lines() -> None:
    first = _line(1)
    second = _line(2)
    assert _plan(transfer_lines=(first, second)).transfer_lines == (first, second)
    with pytest.raises(ValidationError):
        _plan(transfer_lines=())
    with pytest.raises(ValidationError):
        _plan(transfer_lines=cast(Any, [first, second]))
    with pytest.raises(ValidationError):
        _plan(transfer_lines=(second, first))
    with pytest.raises(ValidationError):
        _plan(transfer_lines=(first, _validated_copy(second, allocation_line_index=2)))


def test_plan_rejects_duplicate_allocation_references() -> None:
    first = _line(1)
    second = _line(2)
    with pytest.raises(ValidationError):
        _plan(
            transfer_lines=(
                first,
                _validated_copy(second, offer_id=first.offer_id, sku_id=first.sku_id),
            )
        )
    with pytest.raises(ValidationError):
        _plan(
            transfer_lines=(
                first,
                _validated_copy(second, merchant_id=first.merchant_id, sku_id=first.sku_id),
            )
        )


def test_plan_enforces_one_recipient_and_authorization_per_merchant() -> None:
    first = _line(1)
    same_merchant = _line(
        2,
        merchant_id=first.merchant_id,
        offer_id=first.offer_id,
        recipient_id=first.recipient_id,
        recipient_authorization_id=first.recipient_authorization_id,
    )
    assert _plan(transfer_lines=(first, same_merchant)).transfer_lines == (first, same_merchant)
    with pytest.raises(ValidationError):
        _plan(transfer_lines=(first, _validated_copy(same_merchant, recipient_id="other")))
    with pytest.raises(ValidationError):
        _plan(
            transfer_lines=(
                first,
                _validated_copy(same_merchant, recipient_authorization_id=_uuid(4, 9)),
            )
        )


def test_plan_enforces_exact_bounded_transfer_sum_and_idempotency_key() -> None:
    assert _plan().order_amount == Money(amount_paise=2_700)
    with pytest.raises(ValidationError):
        _plan(order_amount=Money(amount_paise=2_699))
    with pytest.raises(ValidationError):
        _plan(idempotency_key="clear.execution.v1:wrong")

    first = _line(1, transfer_amount=Money(amount_paise=MAX_MONEY_PAISE))
    second = _line(2, transfer_amount=Money(amount_paise=1))
    with pytest.raises(ValidationError):
        _plan(
            order_amount=Money(amount_paise=MAX_MONEY_PAISE),
            transfer_lines=(first, second),
        )


def test_plan_is_provider_neutral_and_direct_construction_is_not_attestation() -> None:
    plan = _plan()
    assert "approved_at" not in ExecutionPlanV1.model_fields
    assert "reserved_at" not in ExecutionPlanV1.model_fields
    assert "decision_time" not in ExecutionPlanV1.model_fields
    assert not hasattr(plan, "provider_account_id")
    assert not hasattr(plan, "razorpay_account_id")
    assert not hasattr(plan, "payment_state")
    documentation = ExecutionPlanV1.__doc__ or ""
    assert "not a cryptographic attestation" in documentation
    assert "authorize_execution_v1" in documentation


def test_trusted_application_authorization_limitation_is_explicit() -> None:
    documentation = " ".join((ExecutionAuthorizationRequestV1.__doc__ or "").split())
    assert "trusted explicit application inputs" in documentation
    assert "does not establish an external cryptographic identity or consent protocol" in (
        documentation
    )


def test_money_governor_error_is_exact_read_only_and_non_sensitive() -> None:
    error = MoneyGovernorError(MoneyGovernorFailureCode.BUYER_BUDGET_EXCEEDED)
    assert error.code is MoneyGovernorFailureCode.BUYER_BUDGET_EXCEEDED
    assert str(error) == "BUYER_BUDGET_EXCEEDED"
    with pytest.raises(AttributeError):
        error.code = MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
