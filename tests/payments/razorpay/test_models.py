from typing import Any

import pytest
from pydantic import ValidationError

import clear_market.payments.razorpay as razorpay
from clear_market.domain import Currency, Money
from clear_market.payments.razorpay import (
    RAZORPAY_ORDER_CREATE_FINGERPRINT_V1_VERSION,
    RAZORPAY_ORDER_CREATE_INTENT_V1_VERSION,
    RAZORPAY_ORDER_RESULT_V1_VERSION,
    RAZORPAY_ORDER_V1_VERSION,
    RAZORPAY_TEST_ORDER_ADAPTER_V1_VERSION,
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    RazorpayOrderResultV1,
    RazorpayOrderStatusV1,
    RazorpayOrderV1,
)

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"


def _order(**changes: object) -> RazorpayOrderV1:
    values: dict[str, object] = {
        "execution_id": _EXECUTION_ID,
        "provider_order_id": "order_Review123",
        "amount": Money(amount_paise=2_700),
        "receipt": _EXECUTION_ID,
        "status": RazorpayOrderStatusV1.CREATED,
        **changes,
    }
    return RazorpayOrderV1(**values)


def test_versions_enums_and_public_api_are_exact() -> None:
    assert RAZORPAY_TEST_ORDER_ADAPTER_V1_VERSION == "razorpay-test-order-adapter-v1"
    assert RAZORPAY_ORDER_V1_VERSION == "razorpay-order-v1"
    assert RAZORPAY_ORDER_RESULT_V1_VERSION == "razorpay-order-result-v1"
    assert RAZORPAY_ORDER_CREATE_INTENT_V1_VERSION == "razorpay-order-create-intent-v1"
    assert RAZORPAY_ORDER_CREATE_FINGERPRINT_V1_VERSION == (
        "sha256-razorpay-order-create-intent-v1-clear-json-v1"
    )
    assert tuple(RazorpayOrderStatusV1) == (
        RazorpayOrderStatusV1.CREATED,
        RazorpayOrderStatusV1.ATTEMPTED,
        RazorpayOrderStatusV1.PAID,
    )
    assert tuple(member.value for member in RazorpayOrderResolutionV1) == (
        "CREATED",
        "EXISTING",
    )
    assert tuple(member.value for member in RazorpayOrderFailureCode) == (
        "LOCAL_PROVIDER_REFERENCE_CONFLICT",
        "LOCAL_IDEMPOTENCY_CONFLICT",
        "ORDER_CREATION_RECOVERY_REQUIRED",
        "EXISTING_ORDER_FETCH_FAILED",
        "INVALID_PROVIDER_RESPONSE",
        "PROVIDER_ORDER_MISMATCH",
    )
    assert razorpay.__all__ == (
        "RAZORPAY_TEST_ORDER_ADAPTER_V1_VERSION",
        "RAZORPAY_ORDER_V1_VERSION",
        "RAZORPAY_ORDER_RESULT_V1_VERSION",
        "RAZORPAY_ORDER_CREATE_INTENT_V1_VERSION",
        "RAZORPAY_ORDER_CREATE_FINGERPRINT_V1_VERSION",
        "RazorpayTestCredentialsV1",
        "RazorpayOrderStatusV1",
        "RazorpayOrderResolutionV1",
        "RazorpayOrderV1",
        "RazorpayOrderResultV1",
        "RazorpayOrderFailureCode",
        "RazorpayOrderError",
        "canonical_razorpay_order_create_intent_v1_bytes",
        "razorpay_order_create_fingerprint_v1",
        "create_razorpay_test_order_v1",
        "RAZORPAY_LINKED_ACCOUNT_BINDING_V1_VERSION",
        "RAZORPAY_ROUTE_MAPPING_REQUEST_V1_VERSION",
        "RAZORPAY_ROUTE_TRANSFER_LINE_V1_VERSION",
        "RAZORPAY_ROUTE_MAPPING_PLAN_V1_VERSION",
        "RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION",
        "RazorpayLinkedAccountBindingStateV1",
        "RazorpayLinkedAccountBindingV1",
        "RazorpayRouteMappingRequestV1",
        "RazorpayRouteTransferLineV1",
        "RazorpayRouteMappingPlanV1",
        "RazorpayRouteMappingFailureCode",
        "RazorpayRouteMappingError",
        "canonical_razorpay_route_mapping_request_v1_bytes",
        "razorpay_route_mapping_fingerprint_v1",
        "build_razorpay_route_mapping_v1",
    )


def test_provider_error_code_is_read_only_and_message_is_exact() -> None:
    error = RazorpayOrderError(RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH)
    assert error.code is RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH
    assert str(error) == "PROVIDER_ORDER_MISMATCH"
    with pytest.raises(AttributeError):
        error.code = RazorpayOrderFailureCode.INVALID_PROVIDER_RESPONSE  # type: ignore[misc]


def test_model_fields_config_and_sanitized_surface_are_exact() -> None:
    assert tuple(RazorpayOrderV1.model_fields) == (
        "schema_version",
        "razorpay_order_version",
        "execution_id",
        "provider_order_id",
        "amount",
        "currency",
        "receipt",
        "status",
    )
    assert tuple(RazorpayOrderResultV1.model_fields) == (
        "schema_version",
        "razorpay_order_result_version",
        "adapter_version",
        "resolution",
        "order",
    )
    for model in (RazorpayOrderV1, RazorpayOrderResultV1):
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
    forbidden = {
        "raw_response",
        "notes",
        "offers",
        "payments",
        "created_at",
        "credentials",
        "transfers",
        "settlement",
    }
    assert forbidden.isdisjoint(RazorpayOrderV1.model_fields)


@pytest.mark.parametrize(
    "provider_order_id",
    ["order_a", "order_A1", "order_" + "a" * 128],
)
def test_provider_order_id_exact_ascii_grammar_accepts_valid_values(
    provider_order_id: str,
) -> None:
    assert _order(provider_order_id=provider_order_id).provider_order_id == provider_order_id


@pytest.mark.parametrize(
    "provider_order_id",
    ["", "order_", " order_a", "order_a ", "ORDER_a", "order_a-b", "order_é", "order_" + "a" * 129],
)
def test_provider_order_id_rejects_invalid_values(provider_order_id: str) -> None:
    with pytest.raises(ValidationError):
        _order(provider_order_id=provider_order_id)


@pytest.mark.parametrize(
    "changes",
    [
        {"receipt": "e1000000-0000-4000-8000-000000000002"},
        {"currency": "USD"},
        {"amount": {"amount_paise": 2_700, "currency": "INR"}},
        {"amount": Money.model_construct(amount_paise="2700", currency=Currency.INR)},
        {"amount": Money.model_construct(amount_paise=2_700, currency="INR")},
        {"extra": "forbidden"},
    ],
)
def test_order_bindings_nested_money_and_extra_are_strict(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _order(**changes)


def test_models_are_frozen_and_nested_order_is_freshly_revalidated() -> None:
    order = _order()
    result = RazorpayOrderResultV1(
        resolution=RazorpayOrderResolutionV1.CREATED,
        order=order,
    )
    assert result.order == order
    with pytest.raises(ValidationError):
        order.status = RazorpayOrderStatusV1.PAID  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RazorpayOrderResultV1(
            resolution=RazorpayOrderResolutionV1.CREATED,
            order=RazorpayOrderV1.model_construct(),
        )
    with pytest.raises(ValidationError):
        RazorpayOrderResultV1(
            resolution=RazorpayOrderResolutionV1.CREATED,
            order={"not": "a model"},  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [1, True, "created"])
def test_status_is_strict(value: Any) -> None:
    with pytest.raises(ValidationError):
        _order(status=value)
