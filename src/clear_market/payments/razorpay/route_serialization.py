"""Canonical bytes and fingerprint for Razorpay Route mapping requests."""

import hashlib

from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    canonical_utc_datetime,
)
from clear_market.domain import Money
from clear_market.execution import ExecutionPlanV1, ExecutionTransferLineV1
from clear_market.payments.razorpay.route_models import (
    RazorpayLinkedAccountBindingV1,
    RazorpayRouteMappingRequestV1,
    _fresh_route_mapping_request,
)


def _money(value: Money) -> dict[str, object]:
    return {
        "amount_paise": value.amount_paise,
        "currency": value.currency.value,
    }


def _execution_transfer_line(value: ExecutionTransferLineV1) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "execution_transfer_line_version": value.execution_transfer_line_version,
        "allocation_line_index": value.allocation_line_index,
        "offer_id": value.offer_id,
        "merchant_id": value.merchant_id,
        "sku_id": value.sku_id,
        "recipient_authorization_id": value.recipient_authorization_id,
        "recipient_id": value.recipient_id,
        "allocated_quantity": value.allocated_quantity,
        "transfer_amount": _money(value.transfer_amount),
    }


def _execution_plan(value: ExecutionPlanV1) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "execution_plan_version": value.execution_plan_version,
        "money_governor_version": value.money_governor_version,
        "execution_id": value.execution_id,
        "certificate_digest_version": value.certificate_digest_version,
        "certificate_digest_sha256": value.certificate_digest_sha256,
        "market_id": value.market_id,
        "buyer_id": value.buyer_id,
        "market_execution_authorization_id": value.market_execution_authorization_id,
        "buyer_financial_authorization_id": value.buyer_financial_authorization_id,
        "execution_request_fingerprint_version": value.execution_request_fingerprint_version,
        "execution_request_fingerprint_sha256": value.execution_request_fingerprint_sha256,
        "idempotency_key": value.idempotency_key,
        "order_amount": _money(value.order_amount),
        "transfer_lines": [_execution_transfer_line(line) for line in value.transfer_lines],
    }


def _linked_account_binding(value: RazorpayLinkedAccountBindingV1) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "razorpay_linked_account_binding_version": (value.razorpay_linked_account_binding_version),
        "binding_id": value.binding_id,
        "merchant_id": value.merchant_id,
        "recipient_id": value.recipient_id,
        "razorpay_account_id": value.razorpay_account_id,
        "state": value.state.value,
        "valid_from": canonical_utc_datetime(value.valid_from),
        "valid_until": canonical_utc_datetime(value.valid_until),
    }


def canonical_razorpay_route_mapping_request_v1_bytes(
    request: RazorpayRouteMappingRequestV1,
) -> bytes:
    """Bind every execution-routing and application binding input explicitly."""
    value = _fresh_route_mapping_request(request)
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "razorpay_route_mapping_request_v1",
            "payload": {
                "schema_version": value.schema_version,
                "razorpay_route_mapping_request_version": (
                    value.razorpay_route_mapping_request_version
                ),
                "execution_plan": _execution_plan(value.execution_plan),
                "linked_account_bindings": [
                    _linked_account_binding(binding) for binding in value.linked_account_bindings
                ],
            },
        }
    )


def razorpay_route_mapping_fingerprint_v1(request: RazorpayRouteMappingRequestV1) -> str:
    """Hash the pure mapping request without time or provider-action state."""
    return hashlib.sha256(canonical_razorpay_route_mapping_request_v1_bytes(request)).hexdigest()
