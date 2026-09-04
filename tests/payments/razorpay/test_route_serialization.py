import hashlib
import json
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from clear_market.canonical import CANONICALIZATION_VERSION
from clear_market.domain import Money
from clear_market.payments.razorpay import (
    RazorpayLinkedAccountBindingStateV1,
    RazorpayRouteMappingRequestV1,
    canonical_razorpay_route_mapping_request_v1_bytes,
    razorpay_route_mapping_fingerprint_v1,
)
from tests.execution.test_models import _validated_copy
from tests.payments.razorpay.test_route_models import _binding, _request

_CANDIDATE_ROUTE_MAPPING_REQUEST_BYTE_LENGTH = 2_851
_CANDIDATE_ROUTE_MAPPING_REQUEST_SHA256 = (
    "5b98613dda70323df06b530e4f5f53cfbe802b319a41edda65037460c46bc65d"
)


def _money(amount_paise: int) -> dict[str, object]:
    return {"amount_paise": amount_paise, "currency": "INR"}


def _expected_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "razorpay_route_mapping_request_version": "razorpay-route-mapping-request-v1",
        "execution_plan": {
            "schema_version": "1",
            "execution_plan_version": "execution-plan-v1",
            "money_governor_version": "money-governor-v1",
            "execution_id": "e1000000-0000-4000-8000-000000000001",
            "certificate_digest_version": ("sha256-allocation-certificate-v2-clear-json-v1"),
            "certificate_digest_sha256": (
                "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
            ),
            "market_id": "b1000000-0000-4000-8000-000000000001",
            "buyer_id": "b2000000-0000-4000-8000-000000000001",
            "market_execution_authorization_id": ("e2000000-0000-4000-8000-000000000001"),
            "buyer_financial_authorization_id": ("e3000000-0000-4000-8000-000000000001"),
            "execution_request_fingerprint_version": ("sha256-execution-request-v1-clear-json-v1"),
            "execution_request_fingerprint_sha256": "a" * 64,
            "idempotency_key": ("clear.execution.v1:e1000000-0000-4000-8000-000000000001"),
            "order_amount": _money(2_700),
            "transfer_lines": [
                {
                    "schema_version": "1",
                    "execution_transfer_line_version": "execution-transfer-line-v1",
                    "allocation_line_index": 0,
                    "offer_id": "b8000000-0001-4000-8000-000000000001",
                    "merchant_id": "b3000000-0001-4000-8000-000000000001",
                    "sku_id": "b6000000-0001-4000-8000-000000000001",
                    "recipient_authorization_id": ("e4000000-0000-4000-8000-000000000001"),
                    "recipient_id": "clear.recipient.m1",
                    "allocated_quantity": 3,
                    "transfer_amount": _money(1_500),
                },
                {
                    "schema_version": "1",
                    "execution_transfer_line_version": "execution-transfer-line-v1",
                    "allocation_line_index": 1,
                    "offer_id": "b8000000-0002-4000-8000-000000000001",
                    "merchant_id": "b3000000-0002-4000-8000-000000000001",
                    "sku_id": "b6000000-0002-4000-8000-000000000001",
                    "recipient_authorization_id": ("e4000000-0000-4000-8000-000000000002"),
                    "recipient_id": "clear.recipient.m2",
                    "allocated_quantity": 2,
                    "transfer_amount": _money(1_200),
                },
            ],
        },
        "linked_account_bindings": [
            {
                "schema_version": "1",
                "razorpay_linked_account_binding_version": ("razorpay-linked-account-binding-v1"),
                "binding_id": "e5000000-0000-4000-8000-000000000001",
                "merchant_id": "b3000000-0001-4000-8000-000000000001",
                "recipient_id": "clear.recipient.m1",
                "razorpay_account_id": "acc_CLEAR00000001",
                "state": "ACTIVE",
                "valid_from": "2026-09-01T11:00:00.000000Z",
                "valid_until": "2026-09-01T13:00:00.000000Z",
            },
            {
                "schema_version": "1",
                "razorpay_linked_account_binding_version": ("razorpay-linked-account-binding-v1"),
                "binding_id": "e5000000-0000-4000-8000-000000000002",
                "merchant_id": "b3000000-0002-4000-8000-000000000001",
                "recipient_id": "clear.recipient.m2",
                "razorpay_account_id": "acc_CLEAR00000002",
                "state": "ACTIVE",
                "valid_from": "2026-09-01T11:00:00.000000Z",
                "valid_until": "2026-09-01T13:00:00.000000Z",
            },
        ],
    }


def _request_with_plan_changes(**changes: object) -> RazorpayRouteMappingRequestV1:
    request = _request()
    plan = _validated_copy(request.execution_plan, **changes)
    return _request(execution_plan=plan)


def _request_with_line_changes(
    index: int,
    **changes: object,
) -> RazorpayRouteMappingRequestV1:
    request = _request()
    lines = list(request.execution_plan.transfer_lines)
    lines[index] = _validated_copy(lines[index], **changes)
    plan = _validated_copy(request.execution_plan, transfer_lines=tuple(lines))
    return _request(execution_plan=plan)


def _request_with_binding_changes(
    index: int,
    **changes: object,
) -> RazorpayRouteMappingRequestV1:
    bindings = list(_request().linked_account_bindings)
    bindings[index] = _validated_copy(bindings[index], **changes)
    return _request(linked_account_bindings=tuple(bindings))


def test_canonical_request_envelope_and_full_explicit_projection_are_exact() -> None:
    encoded = canonical_razorpay_route_mapping_request_v1_bytes(_request())
    assert json.loads(encoded) == {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload_type": "razorpay_route_mapping_request_v1",
        "payload": _expected_payload(),
    }


def test_canonical_request_is_compact_deterministic_utf8_without_floats() -> None:
    first = canonical_razorpay_route_mapping_request_v1_bytes(_request())
    second = canonical_razorpay_route_mapping_request_v1_bytes(_request())
    assert first == second
    assert first.decode("utf-8").encode("utf-8") == first
    assert b"\n" not in first
    assert b": " not in first
    assert b", " not in first

    def reject_floats(value: object) -> None:
        assert type(value) is not float
        if type(value) is dict:
            for nested in value.values():
                reject_floats(nested)
        elif type(value) is list:
            for nested in value:
                reject_floats(nested)

    reject_floats(json.loads(first))


def test_binding_order_is_canonical_and_execution_transfer_order_is_preserved() -> None:
    normal = _request(linked_account_bindings=(_binding(1), _binding(2)))
    reversed_bindings = _request(linked_account_bindings=(_binding(2), _binding(1)))
    assert canonical_razorpay_route_mapping_request_v1_bytes(normal) == (
        canonical_razorpay_route_mapping_request_v1_bytes(reversed_bindings)
    )
    payload = json.loads(canonical_razorpay_route_mapping_request_v1_bytes(reversed_bindings))[
        "payload"
    ]
    assert [binding["merchant_id"] for binding in payload["linked_account_bindings"]] == [
        _binding(1).merchant_id,
        _binding(2).merchant_id,
    ]
    assert [
        line["allocation_line_index"] for line in payload["execution_plan"]["transfer_lines"]
    ] == [0, 1]


def test_projection_contains_canonical_time_and_money_and_no_authority_secrets() -> None:
    encoded = canonical_razorpay_route_mapping_request_v1_bytes(_request())
    text = encoded.decode("utf-8")
    assert '"valid_from":"2026-09-01T11:00:00.000000Z"' in text
    assert '"valid_until":"2026-09-01T13:00:00.000000Z"' in text
    assert '"order_amount":{"amount_paise":2700,"currency":"INR"}' in text
    for forbidden in (
        "decision_time",
        "credentials",
        "provider_order_id",
        "payment_id",
        "transfer_id",
        "api_key",
        "secret",
    ):
        assert forbidden not in text


def _material_mutations() -> tuple[RazorpayRouteMappingRequestV1, ...]:
    request = _request()
    changed_lines = (
        _validated_copy(
            request.execution_plan.transfer_lines[0],
            transfer_amount=Money(amount_paise=1_501),
        ),
        _validated_copy(
            request.execution_plan.transfer_lines[1],
            transfer_amount=Money(amount_paise=1_199),
        ),
    )
    changed_total_plan = _validated_copy(
        request.execution_plan,
        order_amount=Money(amount_paise=2_701),
        transfer_lines=(
            _validated_copy(
                request.execution_plan.transfer_lines[0],
                transfer_amount=Money(amount_paise=1_501),
            ),
            request.execution_plan.transfer_lines[1],
        ),
    )
    return (
        _request_with_plan_changes(
            execution_id="e1000000-0000-4000-8000-000000000002",
            idempotency_key=("clear.execution.v1:e1000000-0000-4000-8000-000000000002"),
        ),
        _request_with_plan_changes(certificate_digest_sha256="c" * 64),
        _request_with_plan_changes(execution_request_fingerprint_sha256="d" * 64),
        _request(execution_plan=changed_total_plan),
        _request_with_line_changes(
            0,
            merchant_id="b3000000-0003-4000-8000-000000000001",
        ),
        _request_with_line_changes(0, recipient_id="clear.recipient.changed"),
        _request(
            execution_plan=_validated_copy(
                request.execution_plan,
                transfer_lines=changed_lines,
            )
        ),
        _request_with_binding_changes(
            0,
            binding_id="e5000000-0000-4000-8000-000000000003",
        ),
        _request_with_binding_changes(
            0,
            merchant_id="b3000000-0003-4000-8000-000000000001",
        ),
        _request_with_binding_changes(0, recipient_id="clear.recipient.changed"),
        _request_with_binding_changes(0, razorpay_account_id="acc_CHANGED000001"),
        _request_with_binding_changes(
            0,
            state=RazorpayLinkedAccountBindingStateV1.PAUSED,
        ),
        _request_with_binding_changes(
            0,
            valid_from=request.linked_account_bindings[0].valid_from + timedelta(microseconds=1),
        ),
        _request_with_binding_changes(
            0,
            valid_until=request.linked_account_bindings[0].valid_until + timedelta(microseconds=1),
        ),
    )


@pytest.mark.parametrize("mutated", _material_mutations())
def test_every_material_execution_and_binding_change_changes_bytes_and_hash(
    mutated: RazorpayRouteMappingRequestV1,
) -> None:
    baseline = _request()
    assert canonical_razorpay_route_mapping_request_v1_bytes(mutated) != (
        canonical_razorpay_route_mapping_request_v1_bytes(baseline)
    )
    assert razorpay_route_mapping_fingerprint_v1(mutated) != (
        razorpay_route_mapping_fingerprint_v1(baseline)
    )


def test_serializer_requires_a_fresh_exact_request() -> None:
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
            canonical_razorpay_route_mapping_request_v1_bytes(value)


def test_candidate_golden_length_and_sha256_are_exact() -> None:
    encoded = canonical_razorpay_route_mapping_request_v1_bytes(_request())
    assert len(encoded) == _CANDIDATE_ROUTE_MAPPING_REQUEST_BYTE_LENGTH
    assert hashlib.sha256(encoded).hexdigest() == (_CANDIDATE_ROUTE_MAPPING_REQUEST_SHA256)
    assert razorpay_route_mapping_fingerprint_v1(_request()) == (
        _CANDIDATE_ROUTE_MAPPING_REQUEST_SHA256
    )
