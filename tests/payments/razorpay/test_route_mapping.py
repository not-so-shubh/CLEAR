from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from clear_market.domain import Money
from clear_market.payments.razorpay import (
    RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION,
    RazorpayLinkedAccountBindingStateV1,
    RazorpayRouteMappingError,
    RazorpayRouteMappingFailureCode,
    RazorpayRouteMappingPlanV1,
    RazorpayRouteMappingRequestV1,
    build_razorpay_route_mapping_v1,
    razorpay_route_mapping_fingerprint_v1,
)
from tests.execution.test_models import (
    _TIME,
    _VALID_FROM,
    _VALID_UNTIL,
    _validated_copy,
)
from tests.payments.razorpay.test_route_models import _binding, _request


def _assert_mapping_error(
    code: RazorpayRouteMappingFailureCode,
    *,
    request: RazorpayRouteMappingRequestV1,
    decision_time: object = _TIME,
) -> RazorpayRouteMappingError:
    with pytest.raises(RazorpayRouteMappingError) as caught:
        build_razorpay_route_mapping_v1(
            request=request,
            decision_time=decision_time,  # type: ignore[arg-type]
        )
    assert caught.value.code is code
    assert str(caught.value) == code.value
    return caught.value


def test_failure_codes_order_values_and_error_surface_are_exact() -> None:
    expected = (
        "BINDING_SET_MISMATCH",
        "BINDING_NOT_EXECUTABLE",
        "BINDING_NOT_ACTIVE",
        "LINKED_ACCOUNT_COLLISION",
    )
    assert tuple(member.name for member in RazorpayRouteMappingFailureCode) == expected
    assert tuple(member.value for member in RazorpayRouteMappingFailureCode) == expected
    error = RazorpayRouteMappingError(RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH)
    assert error.code is RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH
    assert str(error) == "BINDING_SET_MISMATCH"
    with pytest.raises(AttributeError):
        error.code = RazorpayRouteMappingFailureCode.BINDING_NOT_ACTIVE  # type: ignore[misc]


def test_successful_mapping_preserves_exact_execution_lines_and_amounts() -> None:
    request = _request()
    plan = build_razorpay_route_mapping_v1(request=request, decision_time=_TIME)
    assert plan.model_dump(mode="json") == {
        "schema_version": "1",
        "razorpay_route_mapping_plan_version": "razorpay-route-mapping-plan-v1",
        "execution_id": "e1000000-0000-4000-8000-000000000001",
        "certificate_digest_version": ("sha256-allocation-certificate-v2-clear-json-v1"),
        "certificate_digest_sha256": (
            "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
        ),
        "execution_request_fingerprint_version": ("sha256-execution-request-v1-clear-json-v1"),
        "execution_request_fingerprint_sha256": "a" * 64,
        "razorpay_route_mapping_fingerprint_version": (
            "sha256-razorpay-route-mapping-request-v1-clear-json-v1"
        ),
        "razorpay_route_mapping_fingerprint_sha256": (
            "5b98613dda70323df06b530e4f5f53cfbe802b319a41edda65037460c46bc65d"
        ),
        "order_amount": {"amount_paise": 2_700, "currency": "INR"},
        "transfer_lines": [
            {
                "schema_version": "1",
                "razorpay_route_transfer_line_version": ("razorpay-route-transfer-line-v1"),
                "allocation_line_index": 0,
                "offer_id": "b8000000-0001-4000-8000-000000000001",
                "merchant_id": "b3000000-0001-4000-8000-000000000001",
                "sku_id": "b6000000-0001-4000-8000-000000000001",
                "recipient_authorization_id": ("e4000000-0000-4000-8000-000000000001"),
                "recipient_id": "clear.recipient.m1",
                "linked_account_binding_id": ("e5000000-0000-4000-8000-000000000001"),
                "razorpay_account_id": "acc_CLEAR00000001",
                "allocated_quantity": 3,
                "transfer_amount": {"amount_paise": 1_500, "currency": "INR"},
            },
            {
                "schema_version": "1",
                "razorpay_route_transfer_line_version": ("razorpay-route-transfer-line-v1"),
                "allocation_line_index": 1,
                "offer_id": "b8000000-0002-4000-8000-000000000001",
                "merchant_id": "b3000000-0002-4000-8000-000000000001",
                "sku_id": "b6000000-0002-4000-8000-000000000001",
                "recipient_authorization_id": ("e4000000-0000-4000-8000-000000000002"),
                "recipient_id": "clear.recipient.m2",
                "linked_account_binding_id": ("e5000000-0000-4000-8000-000000000002"),
                "razorpay_account_id": "acc_CLEAR00000002",
                "allocated_quantity": 2,
                "transfer_amount": {"amount_paise": 1_200, "currency": "INR"},
            },
        ],
    }
    assert plan.order_amount == Money(amount_paise=2_700)
    assert tuple(line.transfer_amount.amount_paise for line in plan.transfer_lines) == (
        1_500,
        1_200,
    )
    assert plan.razorpay_route_mapping_fingerprint_version == (
        RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION
    )
    assert plan.razorpay_route_mapping_fingerprint_sha256 == (
        razorpay_route_mapping_fingerprint_v1(request)
    )


@pytest.mark.parametrize(
    "bindings",
    [
        (_binding(1),),
        (_binding(1), _binding(2), _binding(3)),
        (
            _binding(1),
            _binding(2, recipient_id="clear.recipient.wrong"),
        ),
    ],
)
def test_binding_set_must_exactly_match_winner_merchant_recipient_pairs(
    bindings: tuple[object, ...],
) -> None:
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH,
        request=_request(linked_account_bindings=bindings),
    )


@pytest.mark.parametrize(
    "state",
    [
        RazorpayLinkedAccountBindingStateV1.PAUSED,
        RazorpayLinkedAccountBindingStateV1.REVOKED,
    ],
)
def test_nonactive_application_binding_state_is_not_executable(
    state: RazorpayLinkedAccountBindingStateV1,
) -> None:
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_NOT_EXECUTABLE,
        request=_request(linked_account_bindings=(_binding(1, state=state), _binding(2))),
    )


def test_one_paused_binding_fails_without_fallback() -> None:
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_NOT_EXECUTABLE,
        request=_request(
            linked_account_bindings=(
                _binding(1),
                _binding(2, state=RazorpayLinkedAccountBindingStateV1.PAUSED),
            )
        ),
    )


@pytest.mark.parametrize("decision_time", [_VALID_FROM, _VALID_UNTIL])
def test_binding_validity_window_is_inclusive(decision_time: datetime) -> None:
    plan = build_razorpay_route_mapping_v1(
        request=_request(),
        decision_time=decision_time,
    )
    assert type(plan) is RazorpayRouteMappingPlanV1


@pytest.mark.parametrize(
    "decision_time",
    [
        _VALID_FROM - timedelta(microseconds=1),
        _VALID_UNTIL + timedelta(microseconds=1),
    ],
)
def test_binding_outside_inclusive_window_is_not_active(
    decision_time: datetime,
) -> None:
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_NOT_ACTIVE,
        request=_request(),
        decision_time=decision_time,
    )


@pytest.mark.parametrize(
    "decision_time",
    [datetime(2026, 9, 1, 11, 30), "2026-09-01T11:30:00Z", None],
)
def test_decision_time_must_be_an_aware_datetime(decision_time: object) -> None:
    with pytest.raises(ValueError, match=r"^decision_time must be an aware datetime$"):
        build_razorpay_route_mapping_v1(
            request=_request(),
            decision_time=decision_time,  # type: ignore[arg-type]
        )


def test_distinct_recipient_bindings_cannot_collapse_to_one_linked_account() -> None:
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.LINKED_ACCOUNT_COLLISION,
        request=_request(
            linked_account_bindings=(
                _binding(1, razorpay_account_id="acc_SHARED000001"),
                _binding(2, razorpay_account_id="acc_SHARED000001"),
            )
        ),
    )


def test_same_merchant_multiple_sku_lines_reuse_one_binding_and_keep_amounts() -> None:
    request = _request()
    first = request.execution_plan.transfer_lines[0]
    second = _validated_copy(
        request.execution_plan.transfer_lines[1],
        offer_id=first.offer_id,
        merchant_id=first.merchant_id,
        recipient_authorization_id=first.recipient_authorization_id,
        recipient_id=first.recipient_id,
    )
    execution_plan = _validated_copy(
        request.execution_plan,
        transfer_lines=(first, second),
    )
    binding = _binding(1)
    single_binding_request = _request(
        execution_plan=execution_plan,
        linked_account_bindings=(binding,),
    )
    plan = build_razorpay_route_mapping_v1(
        request=single_binding_request,
        decision_time=_TIME,
    )
    assert len(plan.transfer_lines) == 2
    assert tuple(line.linked_account_binding_id for line in plan.transfer_lines) == (
        binding.binding_id,
        binding.binding_id,
    )
    assert tuple(line.razorpay_account_id for line in plan.transfer_lines) == (
        binding.razorpay_account_id,
        binding.razorpay_account_id,
    )
    assert tuple(line.transfer_amount.amount_paise for line in plan.transfer_lines) == (
        1_500,
        1_200,
    )


def test_semantic_failure_precedence_is_exact() -> None:
    mismatched_and_paused_and_colliding = _request(
        linked_account_bindings=(
            _binding(
                1,
                state=RazorpayLinkedAccountBindingStateV1.PAUSED,
                razorpay_account_id="acc_SHARED000001",
            ),
            _binding(
                3,
                state=RazorpayLinkedAccountBindingStateV1.PAUSED,
                razorpay_account_id="acc_SHARED000001",
            ),
        )
    )
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH,
        request=mismatched_and_paused_and_colliding,
        decision_time=_VALID_UNTIL + timedelta(days=1),
    )
    paused_and_expired_and_colliding = _request(
        linked_account_bindings=(
            _binding(
                1,
                state=RazorpayLinkedAccountBindingStateV1.PAUSED,
                razorpay_account_id="acc_SHARED000001",
            ),
            _binding(2, razorpay_account_id="acc_SHARED000001"),
        )
    )
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_NOT_EXECUTABLE,
        request=paused_and_expired_and_colliding,
        decision_time=_VALID_UNTIL + timedelta(days=1),
    )
    expired_and_colliding = _request(
        linked_account_bindings=(
            _binding(1, razorpay_account_id="acc_SHARED000001"),
            _binding(2, razorpay_account_id="acc_SHARED000001"),
        )
    )
    _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_NOT_ACTIVE,
        request=expired_and_colliding,
        decision_time=_VALID_UNTIL + timedelta(days=1),
    )


def test_mapping_requires_a_fresh_exact_request() -> None:
    class RequestSubclass(RazorpayRouteMappingRequestV1):
        pass

    request = _request()
    invalid: tuple[Any, ...] = (
        request.model_dump(mode="python"),
        RequestSubclass.model_construct(**request.__dict__),
        RazorpayRouteMappingRequestV1.model_construct(),
    )
    for value in invalid:
        with pytest.raises((TypeError, ValueError, ValidationError)):
            build_razorpay_route_mapping_v1(request=value, decision_time=_TIME)


def test_decision_time_is_not_plan_data_or_fingerprint_material() -> None:
    request = _request()
    first = build_razorpay_route_mapping_v1(request=request, decision_time=_TIME)
    second = build_razorpay_route_mapping_v1(
        request=request,
        decision_time=_TIME + timedelta(minutes=1),
    )
    assert first == second
    assert first.razorpay_route_mapping_fingerprint_sha256 == (
        second.razorpay_route_mapping_fingerprint_sha256
    )
    assert "decision_time" not in type(first).model_fields


def test_mapping_has_no_order_payment_transfer_or_credential_dependency() -> None:
    plan = build_razorpay_route_mapping_v1(request=_request(), decision_time=_TIME)
    forbidden = {
        "provider_order_id",
        "payment_id",
        "transfer_id",
        "credentials",
        "captured_payment",
    }
    assert forbidden.isdisjoint(type(plan).model_fields)
    assert all(forbidden.isdisjoint(type(line).model_fields) for line in plan.transfer_lines)


def test_mapping_does_not_invoke_the_21a_https_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    import clear_market.payments.razorpay.orders as orders

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("21B must not call the 21A HTTPS boundary")

    monkeypatch.setattr(orders, "_https_request", fail_if_called)
    plan = build_razorpay_route_mapping_v1(request=_request(), decision_time=_TIME)
    assert type(plan) is RazorpayRouteMappingPlanV1


def test_error_text_never_discloses_routing_or_financial_values() -> None:
    error = _assert_mapping_error(
        RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH,
        request=_request(linked_account_bindings=(_binding(1),)),
    )
    message = str(error)
    for secret in (
        _binding(1).merchant_id,
        _binding(1).recipient_id,
        _binding(1).razorpay_account_id,
        _binding(1).binding_id,
        "1500",
        "2700",
    ):
        assert secret not in message
