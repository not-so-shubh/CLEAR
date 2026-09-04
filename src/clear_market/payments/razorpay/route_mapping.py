"""Pure deterministic mapping from execution recipients to Razorpay Linked Accounts."""

from datetime import datetime
from enum import StrEnum
from typing import Never

from pydantic import TypeAdapter, ValidationError

from clear_market.domain import UTCDateTime
from clear_market.payments.razorpay.route_models import (
    RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION,
    RazorpayLinkedAccountBindingStateV1,
    RazorpayLinkedAccountBindingV1,
    RazorpayRouteMappingPlanV1,
    RazorpayRouteMappingRequestV1,
    RazorpayRouteTransferLineV1,
    _fresh_route_mapping_request,
)
from clear_market.payments.razorpay.route_serialization import (
    razorpay_route_mapping_fingerprint_v1,
)

_UTC_DATETIME_ADAPTER: TypeAdapter[datetime] = TypeAdapter(UTCDateTime)


class RazorpayRouteMappingFailureCode(StrEnum):
    BINDING_SET_MISMATCH = "BINDING_SET_MISMATCH"
    BINDING_NOT_EXECUTABLE = "BINDING_NOT_EXECUTABLE"
    BINDING_NOT_ACTIVE = "BINDING_NOT_ACTIVE"
    LINKED_ACCOUNT_COLLISION = "LINKED_ACCOUNT_COLLISION"


class RazorpayRouteMappingError(ValueError):
    """Stable sanitized routing failure without financial identity disclosure."""

    __slots__ = ("_code",)

    def __init__(self, code: RazorpayRouteMappingFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> RazorpayRouteMappingFailureCode:
        return self._code


def _fail(code: RazorpayRouteMappingFailureCode) -> Never:
    raise RazorpayRouteMappingError(code)


def _decision_time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("decision_time must be an aware datetime")
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError:
        raise ValueError("decision_time must be an aware datetime") from None


def build_razorpay_route_mapping_v1(
    *,
    request: RazorpayRouteMappingRequestV1,
    decision_time: datetime,
) -> RazorpayRouteMappingPlanV1:
    """Build a pure routing artifact without provider, persistence, or money-movement authority."""
    value = _fresh_route_mapping_request(request)
    now = _decision_time(decision_time)

    winner_pairs = {
        (line.merchant_id, line.recipient_id) for line in value.execution_plan.transfer_lines
    }
    binding_pairs = {
        (binding.merchant_id, binding.recipient_id) for binding in value.linked_account_bindings
    }
    if binding_pairs != winner_pairs:
        _fail(RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH)
    if any(
        binding.state is not RazorpayLinkedAccountBindingStateV1.ACTIVE
        for binding in value.linked_account_bindings
    ):
        _fail(RazorpayRouteMappingFailureCode.BINDING_NOT_EXECUTABLE)
    if any(
        not binding.valid_from <= now <= binding.valid_until
        for binding in value.linked_account_bindings
    ):
        _fail(RazorpayRouteMappingFailureCode.BINDING_NOT_ACTIVE)
    account_ids = tuple(binding.razorpay_account_id for binding in value.linked_account_bindings)
    if len(set(account_ids)) != len(account_ids):
        _fail(RazorpayRouteMappingFailureCode.LINKED_ACCOUNT_COLLISION)

    bindings: dict[tuple[str, str], RazorpayLinkedAccountBindingV1] = {
        (binding.merchant_id, binding.recipient_id): binding
        for binding in value.linked_account_bindings
    }
    fingerprint = razorpay_route_mapping_fingerprint_v1(value)
    transfer_lines = tuple(
        RazorpayRouteTransferLineV1(
            allocation_line_index=line.allocation_line_index,
            offer_id=line.offer_id,
            merchant_id=line.merchant_id,
            sku_id=line.sku_id,
            recipient_authorization_id=line.recipient_authorization_id,
            recipient_id=line.recipient_id,
            linked_account_binding_id=(bindings[(line.merchant_id, line.recipient_id)].binding_id),
            razorpay_account_id=(
                bindings[(line.merchant_id, line.recipient_id)].razorpay_account_id
            ),
            allocated_quantity=line.allocated_quantity,
            transfer_amount=line.transfer_amount,
        )
        for line in value.execution_plan.transfer_lines
    )
    return RazorpayRouteMappingPlanV1(
        execution_id=value.execution_plan.execution_id,
        certificate_digest_version=value.execution_plan.certificate_digest_version,
        certificate_digest_sha256=value.execution_plan.certificate_digest_sha256,
        execution_request_fingerprint_version=(
            value.execution_plan.execution_request_fingerprint_version
        ),
        execution_request_fingerprint_sha256=(
            value.execution_plan.execution_request_fingerprint_sha256
        ),
        razorpay_route_mapping_fingerprint_version=(RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION),
        razorpay_route_mapping_fingerprint_sha256=fingerprint,
        order_amount=value.execution_plan.order_amount,
        transfer_lines=transfer_lines,
    )
