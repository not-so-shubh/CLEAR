from datetime import timedelta
from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.payments.razorpay as razorpay
from clear_market.domain import MAX_MONEY_PAISE, MAX_SELLERS, Currency, Money
from clear_market.execution import ExecutionPlanV1
from clear_market.payments.razorpay import (
    RAZORPAY_LINKED_ACCOUNT_BINDING_V1_VERSION,
    RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION,
    RAZORPAY_ROUTE_MAPPING_PLAN_V1_VERSION,
    RAZORPAY_ROUTE_MAPPING_REQUEST_V1_VERSION,
    RAZORPAY_ROUTE_TRANSFER_LINE_V1_VERSION,
    RazorpayLinkedAccountBindingStateV1,
    RazorpayLinkedAccountBindingV1,
    RazorpayRouteMappingPlanV1,
    RazorpayRouteMappingRequestV1,
    RazorpayRouteTransferLineV1,
)
from tests.execution.test_models import (
    _TIME,
    _VALID_FROM,
    _VALID_UNTIL,
)
from tests.execution.test_models import _line as _execution_line
from tests.execution.test_models import _plan as _execution_plan

_CONFIG = {
    "frozen": True,
    "extra": "forbid",
    "strict": True,
    "revalidate_instances": "always",
}


def _binding(index: int, **changes: object) -> RazorpayLinkedAccountBindingV1:
    values: dict[str, object] = {
        "binding_id": f"e5000000-0000-4000-8000-{index:012x}",
        "merchant_id": f"b3000000-{index:04x}-4000-8000-000000000001",
        "recipient_id": f"clear.recipient.m{index}",
        "razorpay_account_id": f"acc_CLEAR{index:08d}",
        "state": RazorpayLinkedAccountBindingStateV1.ACTIVE,
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
        **changes,
    }
    return RazorpayLinkedAccountBindingV1(**values)


def _request(**changes: object) -> RazorpayRouteMappingRequestV1:
    values: dict[str, object] = {
        "execution_plan": _execution_plan(),
        "linked_account_bindings": (_binding(2), _binding(1)),
        **changes,
    }
    return RazorpayRouteMappingRequestV1(**values)


def _route_line(index: int, **changes: object) -> RazorpayRouteTransferLineV1:
    source = _execution_line(index)
    binding = _binding(index)
    values: dict[str, object] = {
        "allocation_line_index": source.allocation_line_index,
        "offer_id": source.offer_id,
        "merchant_id": source.merchant_id,
        "sku_id": source.sku_id,
        "recipient_authorization_id": source.recipient_authorization_id,
        "recipient_id": source.recipient_id,
        "linked_account_binding_id": binding.binding_id,
        "razorpay_account_id": binding.razorpay_account_id,
        "allocated_quantity": source.allocated_quantity,
        "transfer_amount": source.transfer_amount,
        **changes,
    }
    return RazorpayRouteTransferLineV1(**values)


def _route_plan(**changes: object) -> RazorpayRouteMappingPlanV1:
    execution = _execution_plan()
    values: dict[str, object] = {
        "execution_id": execution.execution_id,
        "certificate_digest_version": execution.certificate_digest_version,
        "certificate_digest_sha256": execution.certificate_digest_sha256,
        "execution_request_fingerprint_version": (execution.execution_request_fingerprint_version),
        "execution_request_fingerprint_sha256": (execution.execution_request_fingerprint_sha256),
        "razorpay_route_mapping_fingerprint_sha256": "b" * 64,
        "order_amount": execution.order_amount,
        "transfer_lines": (_route_line(1), _route_line(2)),
        **changes,
    }
    return RazorpayRouteMappingPlanV1(**values)


def _assert_invalid(model_type: type[BaseModel], **values: object) -> None:
    with pytest.raises(ValidationError):
        model_type(**values)


def test_versions_enum_and_public_api_extension_are_exact() -> None:
    assert RAZORPAY_LINKED_ACCOUNT_BINDING_V1_VERSION == ("razorpay-linked-account-binding-v1")
    assert RAZORPAY_ROUTE_MAPPING_REQUEST_V1_VERSION == "razorpay-route-mapping-request-v1"
    assert RAZORPAY_ROUTE_TRANSFER_LINE_V1_VERSION == "razorpay-route-transfer-line-v1"
    assert RAZORPAY_ROUTE_MAPPING_PLAN_V1_VERSION == "razorpay-route-mapping-plan-v1"
    assert RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION == (
        "sha256-razorpay-route-mapping-request-v1-clear-json-v1"
    )
    assert issubclass(RazorpayLinkedAccountBindingStateV1, StrEnum)
    assert tuple(RazorpayLinkedAccountBindingStateV1) == (
        RazorpayLinkedAccountBindingStateV1.ACTIVE,
        RazorpayLinkedAccountBindingStateV1.PAUSED,
        RazorpayLinkedAccountBindingStateV1.REVOKED,
    )
    assert tuple(member.value for member in RazorpayLinkedAccountBindingStateV1) == (
        "ACTIVE",
        "PAUSED",
        "REVOKED",
    )
    assert razorpay.__all__[15:30] == (
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


@pytest.mark.parametrize(
    ("model_type", "fields"),
    [
        (
            RazorpayLinkedAccountBindingV1,
            (
                "schema_version",
                "razorpay_linked_account_binding_version",
                "binding_id",
                "merchant_id",
                "recipient_id",
                "razorpay_account_id",
                "state",
                "valid_from",
                "valid_until",
            ),
        ),
        (
            RazorpayRouteMappingRequestV1,
            (
                "schema_version",
                "razorpay_route_mapping_request_version",
                "execution_plan",
                "linked_account_bindings",
            ),
        ),
        (
            RazorpayRouteTransferLineV1,
            (
                "schema_version",
                "razorpay_route_transfer_line_version",
                "allocation_line_index",
                "offer_id",
                "merchant_id",
                "sku_id",
                "recipient_authorization_id",
                "recipient_id",
                "linked_account_binding_id",
                "razorpay_account_id",
                "allocated_quantity",
                "transfer_amount",
            ),
        ),
        (
            RazorpayRouteMappingPlanV1,
            (
                "schema_version",
                "razorpay_route_mapping_plan_version",
                "execution_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "execution_request_fingerprint_version",
                "execution_request_fingerprint_sha256",
                "razorpay_route_mapping_fingerprint_version",
                "razorpay_route_mapping_fingerprint_sha256",
                "order_amount",
                "transfer_lines",
            ),
        ),
    ],
)
def test_model_fields_and_configuration_are_exact(
    model_type: type[BaseModel],
    fields: tuple[str, ...],
) -> None:
    assert tuple(model_type.model_fields) == fields
    assert model_type.model_config == _CONFIG


@pytest.mark.parametrize(
    "model",
    [_binding(1), _request(), _route_line(1), _route_plan()],
)
def test_models_are_frozen_and_forbid_extra(model: BaseModel) -> None:
    with pytest.raises(ValidationError):
        model.schema_version = "2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), "extra": True})


@pytest.mark.parametrize(
    ("factory", "version_field"),
    [
        (_binding, "razorpay_linked_account_binding_version"),
        (lambda _index, **changes: _request(**changes), "razorpay_route_mapping_request_version"),
        (_route_line, "razorpay_route_transfer_line_version"),
        (lambda _index, **changes: _route_plan(**changes), "razorpay_route_mapping_plan_version"),
    ],
)
def test_versions_are_exact(factory: Any, version_field: str) -> None:
    with pytest.raises(ValidationError):
        factory(1, **{version_field: "wrong"})


@pytest.mark.parametrize("field", ["binding_id", "merchant_id"])
@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "E5000000-0000-4000-8000-000000000001",
        "e5000000-0000-1000-8000-000000000001",
        "e5000000-0000-4000-c000-000000000001",
    ],
)
def test_binding_uuid_fields_are_strict(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _binding(1, **{field: value})


@pytest.mark.parametrize(
    "recipient_id",
    ["a", "clear.recipient:m-1", "a" * 128],
)
def test_recipient_id_grammar_accepts_exact_valid_values(recipient_id: str) -> None:
    assert _binding(1, recipient_id=recipient_id).recipient_id == recipient_id


@pytest.mark.parametrize(
    "recipient_id",
    ["", "A", " clear", "clear ", "clear/recipient", "é", "a" * 129],
)
def test_recipient_id_grammar_rejects_without_normalization(recipient_id: str) -> None:
    with pytest.raises(ValidationError):
        _binding(1, recipient_id=recipient_id)


@pytest.mark.parametrize(
    "account_id",
    ["acc_A", "acc_0123456789ABCD", "acc_CLEAR00000001"],
)
def test_razorpay_account_id_grammar_accepts_up_to_18_characters(
    account_id: str,
) -> None:
    assert len(account_id) <= 18
    assert _binding(1, razorpay_account_id=account_id).razorpay_account_id == account_id


@pytest.mark.parametrize(
    "account_id",
    [
        "acc_",
        "acc_0123456789ABCDE",
        "account_CLEAR1",
        "acc_CLEAR-1",
        " acc_CLEAR1",
        "acc_CLEAR1 ",
        "ACC_CLEAR1",
        "acc_é",
    ],
)
def test_razorpay_account_id_grammar_rejects_without_normalization(
    account_id: str,
) -> None:
    with pytest.raises(ValidationError):
        _binding(1, razorpay_account_id=account_id)


def test_binding_validity_interval_is_inclusive_and_not_inverted() -> None:
    instant = _TIME
    assert _binding(1, valid_from=instant, valid_until=instant).valid_from == instant
    with pytest.raises(ValidationError):
        _binding(1, valid_from=instant, valid_until=instant - timedelta(microseconds=1))


@pytest.mark.parametrize(
    "execution_plan",
    [
        _execution_plan().model_dump(mode="python"),
        type("ExecutionPlanSubclass", (ExecutionPlanV1,), {}).model_construct(
            **_execution_plan().__dict__
        ),
        ExecutionPlanV1.model_construct(),
    ],
)
def test_request_requires_fresh_exact_execution_plan(execution_plan: object) -> None:
    with pytest.raises(ValidationError):
        _request(execution_plan=execution_plan)


def test_request_requires_exact_nonempty_bounded_binding_tuple() -> None:
    with pytest.raises(ValidationError):
        _request(linked_account_bindings=[_binding(1), _binding(2)])
    with pytest.raises(ValidationError):
        _request(linked_account_bindings=())
    too_many = tuple(_binding(index) for index in range(1, MAX_SELLERS + 2))
    with pytest.raises(ValidationError):
        _request(linked_account_bindings=too_many)


def test_request_freshly_revalidates_exact_bindings() -> None:
    class BindingSubclass(RazorpayLinkedAccountBindingV1):
        pass

    malformed = RazorpayLinkedAccountBindingV1.model_construct()
    for bindings in (
        ({"merchant_id": _binding(1).merchant_id},),
        (BindingSubclass(**_binding(1).model_dump(mode="python")),),
        (malformed,),
    ):
        with pytest.raises(ValidationError):
            _request(linked_account_bindings=bindings)


@pytest.mark.parametrize(
    "bindings",
    [
        (_binding(1), _binding(2, binding_id=_binding(1).binding_id)),
        (_binding(1), _binding(2, merchant_id=_binding(1).merchant_id)),
        (_binding(1), _binding(2, recipient_id=_binding(1).recipient_id)),
    ],
)
def test_request_rejects_duplicate_binding_merchant_and_recipient_ids(
    bindings: tuple[RazorpayLinkedAccountBindingV1, ...],
) -> None:
    with pytest.raises(ValidationError):
        _request(linked_account_bindings=bindings)


def test_request_normalizes_bindings_by_merchant_and_allows_account_collision() -> None:
    shared_account = "acc_SHARED000001"
    request = _request(
        linked_account_bindings=(
            _binding(2, razorpay_account_id=shared_account),
            _binding(1, razorpay_account_id=shared_account),
        )
    )
    assert request.linked_account_bindings == (
        _binding(1, razorpay_account_id=shared_account),
        _binding(2, razorpay_account_id=shared_account),
    )


@pytest.mark.parametrize(
    "field",
    ["transfer_amount"],
)
def test_route_transfer_line_requires_fresh_exact_money(field: str) -> None:
    class MoneySubclass(Money):
        pass

    for value in (
        {"amount_paise": 1_500, "currency": "INR"},
        MoneySubclass(amount_paise=1_500, currency=Currency.INR),
        Money.model_construct(currency=Currency.INR),
        Money.model_construct(amount_paise="1500", currency=Currency.INR),
    ):
        with pytest.raises(ValidationError):
            _route_line(1, **{field: value})


@pytest.mark.parametrize("value", [-1, True, 1.0, "0"])
def test_route_transfer_line_index_is_strict_and_nonnegative(value: object) -> None:
    with pytest.raises(ValidationError):
        _route_line(1, allocation_line_index=value)


def test_route_plan_requires_exact_nonempty_fresh_transfer_line_tuple() -> None:
    class RouteLineSubclass(RazorpayRouteTransferLineV1):
        pass

    line = _route_line(1)
    for lines in (
        [],
        (),
        (line.model_dump(mode="python"),),
        (RouteLineSubclass.model_construct(**line.__dict__),),
        (RazorpayRouteTransferLineV1.model_construct(),),
    ):
        with pytest.raises(ValidationError):
            _route_plan(transfer_lines=lines)


def test_route_plan_requires_exact_contiguous_order() -> None:
    with pytest.raises(ValidationError):
        _route_plan(transfer_lines=(_route_line(2), _route_line(1)))
    with pytest.raises(ValidationError):
        _route_plan(
            transfer_lines=(
                _route_line(1),
                _route_line(2, allocation_line_index=2),
            )
        )


def test_route_plan_requires_checked_sum_equal_to_order_amount() -> None:
    with pytest.raises(ValidationError):
        _route_plan(order_amount=Money(amount_paise=2_699))
    large_first = _route_line(
        1,
        transfer_amount=Money(amount_paise=MAX_MONEY_PAISE),
    )
    large_second = _route_line(2, transfer_amount=Money(amount_paise=1))
    with pytest.raises(ValidationError):
        _route_plan(
            order_amount=Money(amount_paise=MAX_MONEY_PAISE),
            transfer_lines=(large_first, large_second),
        )


def test_route_plan_requires_one_provider_route_per_merchant() -> None:
    first = _route_line(1)
    second = _route_line(
        2,
        merchant_id=first.merchant_id,
        offer_id=first.offer_id,
    )
    with pytest.raises(ValidationError):
        _route_plan(transfer_lines=(first, second))


def test_route_plan_rejects_distinct_recipients_collapsing_to_one_account() -> None:
    with pytest.raises(ValidationError):
        _route_plan(
            transfer_lines=(
                _route_line(1, razorpay_account_id="acc_SHARED000001"),
                _route_line(2, razorpay_account_id="acc_SHARED000001"),
            )
        )


def test_direct_mapping_plan_construction_grants_no_provider_authority() -> None:
    plan = _route_plan()
    assert "not money-movement authority" in (RazorpayRouteMappingPlanV1.__doc__ or "")
    assert "Direct construction grants no provider authority" in (
        RazorpayRouteMappingPlanV1.__doc__ or ""
    )
    forbidden = {
        "provider_order_id",
        "payment_id",
        "transfer_id",
        "credentials",
        "captured",
    }
    assert forbidden.isdisjoint(type(plan).model_fields)


def test_binding_documents_explicit_application_trust_limit() -> None:
    doc = " ".join((RazorpayLinkedAccountBindingV1.__doc__ or "").split())
    assert "trusted explicit application routing inputs" in doc
    assert "does not establish an external cryptographic authorization protocol" in doc
    assert "does not prove that the Razorpay Linked Account exists" in doc
