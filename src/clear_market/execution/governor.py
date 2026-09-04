"""Deterministic Money Governor for verified V2 allocation certificates."""

from datetime import datetime
from enum import StrEnum
from typing import Never

from pydantic import TypeAdapter, ValidationError

from clear_market.certificate.v2 import (
    ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    AllocationCertificateV2,
    AllocationClaimStatusV2,
    allocation_certificate_v2_digest,
)
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.domain import MAX_MONEY_PAISE, UTCDateTime
from clear_market.execution.models import (
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    ExecutionTransferLineV1,
    MarketExecutionStateV1,
    MerchantRecipientAuthorizationV1,
    _fresh_execution_authorization_request,
)
from clear_market.execution.serialization import execution_request_fingerprint_v1
from clear_market.persistence import (
    ExecutionReservationDispositionV1,
    ExecutionReservationV1,
    SQLiteFinancialLedgerV1,
)
from clear_market.verification.v2 import verify_allocation_certificate_v2

_UTC_DATETIME_ADAPTER: TypeAdapter[datetime] = TypeAdapter(UTCDateTime)


class MoneyGovernorFailureCode(StrEnum):
    CERTIFICATE_NOT_VERIFIED = "CERTIFICATE_NOT_VERIFIED"
    ALLOCATION_NOT_EXECUTABLE = "ALLOCATION_NOT_EXECUTABLE"
    EXECUTION_REQUEST_MISMATCH = "EXECUTION_REQUEST_MISMATCH"
    MARKET_NOT_EXECUTABLE = "MARKET_NOT_EXECUTABLE"
    MARKET_AUTHORIZATION_NOT_ACTIVE = "MARKET_AUTHORIZATION_NOT_ACTIVE"
    BUYER_AUTHORIZATION_MISMATCH = "BUYER_AUTHORIZATION_MISMATCH"
    BUYER_AUTHORIZATION_NOT_ACTIVE = "BUYER_AUTHORIZATION_NOT_ACTIVE"
    BUYER_BUDGET_EXCEEDED = "BUYER_BUDGET_EXCEEDED"
    RECIPIENT_SET_MISMATCH = "RECIPIENT_SET_MISMATCH"
    RECIPIENT_AUTHORIZATION_NOT_ACTIVE = "RECIPIENT_AUTHORIZATION_NOT_ACTIVE"
    RECIPIENT_TRANSFER_LIMIT_EXCEEDED = "RECIPIENT_TRANSFER_LIMIT_EXCEEDED"
    EXECUTION_ID_CONFLICT = "EXECUTION_ID_CONFLICT"
    CERTIFICATE_ALREADY_EXECUTED = "CERTIFICATE_ALREADY_EXECUTED"
    MARKET_ALREADY_EXECUTED = "MARKET_ALREADY_EXECUTED"


class MoneyGovernorError(ValueError):
    """Stable financial-authorization failure without identity or amount disclosure."""

    __slots__ = ("_code",)

    def __init__(self, code: MoneyGovernorFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> MoneyGovernorFailureCode:
        return self._code


def _fail(code: MoneyGovernorFailureCode) -> Never:
    raise MoneyGovernorError(code)


def _decision_time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("decision_time must be an aware datetime")
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError:
        raise ValueError("decision_time must be an aware datetime") from None


def _certificate_after_verification(value: AllocationCertificateV2) -> AllocationCertificateV2:
    try:
        fields = {name: value.__dict__[name] for name in AllocationCertificateV2.model_fields}
        return AllocationCertificateV2.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("certificate must remain a valid exact AllocationCertificateV2") from None


def _build_plan(
    *,
    certificate: AllocationCertificateV2,
    request: ExecutionAuthorizationRequestV1,
    fingerprint: str,
    transfer_lines: tuple[ExecutionTransferLineV1, ...],
) -> ExecutionPlanV1:
    return ExecutionPlanV1(
        execution_id=request.execution_id,
        certificate_id=certificate.certificate_id,
        certificate_digest_version=request.certificate_digest_version,
        certificate_digest_sha256=request.certificate_digest_sha256,
        market_id=request.market_id,
        buyer_id=certificate.buyer_policy.market_spec.buyer_id,
        market_execution_authorization_id=(request.market_execution_authorization.authorization_id),
        buyer_financial_authorization_id=(request.buyer_financial_authorization.authorization_id),
        execution_request_fingerprint_sha256=fingerprint,
        idempotency_key=f"clear.execution.v1:{request.execution_id}",
        order_amount=certificate.allocation.total_payment,
        transfer_lines=transfer_lines,
    )


def _transfer_lines(
    certificate: AllocationCertificateV2,
    recipients: dict[str, MerchantRecipientAuthorizationV1],
) -> tuple[ExecutionTransferLineV1, ...]:
    return tuple(
        ExecutionTransferLineV1(
            allocation_line_index=index,
            offer_id=line.offer_id,
            merchant_id=line.merchant_id,
            sku_id=line.sku_id,
            recipient_authorization_id=recipients[line.merchant_id].authorization_id,
            recipient_id=recipients[line.merchant_id].recipient_id,
            allocated_quantity=line.allocated_quantity,
            transfer_amount=line.line_payment,
        )
        for index, line in enumerate(certificate.allocation.lines)
    )


def authorize_execution_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    request: ExecutionAuthorizationRequestV1,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
) -> ExecutionPlanV1:
    """Verify, authorize, reserve, and return provider-neutral execution authority.

    Slice 20B treats market, buyer, and recipient authorization objects as trusted explicit
    application inputs. It validates their deterministic consistency and limits but does not
    establish an external cryptographic identity or consent protocol for those authorization
    objects. decision_time is a trusted explicit application time input. The Money Governor
    validates authorization windows against that supplied time but does not independently
    establish current wall-clock truth.
    """
    if type(certificate) is not AllocationCertificateV2:
        raise TypeError("certificate must be exactly an AllocationCertificateV2")
    if type(request) is not ExecutionAuthorizationRequestV1:
        raise TypeError("request must be exactly an ExecutionAuthorizationRequestV1")
    if type(ledger) is not SQLiteFinancialLedgerV1:
        raise TypeError("ledger must be exactly a SQLiteFinancialLedgerV1")
    validated_request = _fresh_execution_authorization_request(request)
    now = _decision_time(decision_time)

    verification = verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=trusted_signing_identities,
    )
    if not verification.verified:
        _fail(MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED)

    certificate = _certificate_after_verification(certificate)

    allocation = certificate.allocation
    if (
        allocation.status is not AllocationClaimStatusV2.FEASIBLE
        or allocation.fulfilled_quantity <= 0
        or allocation.total_payment.amount_paise <= 0
        or allocation.winner_count <= 0
        or not allocation.lines
    ):
        _fail(MoneyGovernorFailureCode.ALLOCATION_NOT_EXECUTABLE)

    digest = allocation_certificate_v2_digest(certificate)
    market_id = certificate.buyer_policy.market_spec.market_id
    if (
        validated_request.certificate_digest_version != ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION
        or validated_request.certificate_digest_sha256 != digest
        or validated_request.market_id != market_id
        or allocation.market_id != market_id
    ):
        _fail(MoneyGovernorFailureCode.EXECUTION_REQUEST_MISMATCH)

    market_authorization = validated_request.market_execution_authorization
    if market_authorization.state is not MarketExecutionStateV1.EXECUTABLE:
        _fail(MoneyGovernorFailureCode.MARKET_NOT_EXECUTABLE)
    if not market_authorization.valid_from <= now <= market_authorization.valid_until:
        _fail(MoneyGovernorFailureCode.MARKET_AUTHORIZATION_NOT_ACTIVE)

    buyer_authorization = validated_request.buyer_financial_authorization
    if buyer_authorization.buyer_id != certificate.buyer_policy.market_spec.buyer_id:
        _fail(MoneyGovernorFailureCode.BUYER_AUTHORIZATION_MISMATCH)
    if not buyer_authorization.valid_from <= now <= buyer_authorization.valid_until:
        _fail(MoneyGovernorFailureCode.BUYER_AUTHORIZATION_NOT_ACTIVE)

    amount = allocation.total_payment.amount_paise
    if (
        amount > certificate.buyer_policy.max_total_payment.amount_paise
        or amount > buyer_authorization.maximum_total_payment.amount_paise
    ):
        _fail(MoneyGovernorFailureCode.BUYER_BUDGET_EXCEEDED)

    winner_ids = {line.merchant_id for line in allocation.lines}
    recipients = {
        authorization.merchant_id: authorization
        for authorization in validated_request.merchant_recipient_authorizations
    }
    if set(recipients) != winner_ids:
        _fail(MoneyGovernorFailureCode.RECIPIENT_SET_MISMATCH)
    if not winner_ids <= set(certificate.buyer_policy.eligible_merchant_ids):
        raise ValueError("verified allocation contains an ineligible paid merchant")

    if any(
        not authorization.valid_from <= now <= authorization.valid_until
        for authorization in recipients.values()
    ):
        _fail(MoneyGovernorFailureCode.RECIPIENT_AUTHORIZATION_NOT_ACTIVE)

    aggregate_by_merchant = {merchant_id: 0 for merchant_id in winner_ids}
    checked_total = 0
    for line in allocation.lines:
        checked_total += line.line_payment.amount_paise
        aggregate_by_merchant[line.merchant_id] += line.line_payment.amount_paise
        if checked_total > MAX_MONEY_PAISE:
            raise ValueError("verified allocation payment total exceeds the money bound")
    if checked_total != amount:
        raise ValueError("verified allocation line payments do not match total payment")
    if any(
        aggregate_by_merchant[merchant_id] > recipients[merchant_id].maximum_transfer.amount_paise
        for merchant_id in winner_ids
    ):
        _fail(MoneyGovernorFailureCode.RECIPIENT_TRANSFER_LIMIT_EXCEEDED)

    transfer_lines = _transfer_lines(certificate, recipients)
    _build_plan(
        certificate=certificate,
        request=validated_request,
        fingerprint="0" * 64,
        transfer_lines=transfer_lines,
    )
    fingerprint = execution_request_fingerprint_v1(validated_request)
    reservation = ExecutionReservationV1(
        execution_id=validated_request.execution_id,
        certificate_digest_version=validated_request.certificate_digest_version,
        certificate_digest_sha256=digest,
        market_id=validated_request.market_id,
        execution_request_fingerprint_sha256=fingerprint,
        reserved_at=now,
    )
    reservation_result = ledger.reserve_execution(reservation)
    disposition = reservation_result.disposition
    if disposition is ExecutionReservationDispositionV1.EXECUTION_ID_CONFLICT:
        _fail(MoneyGovernorFailureCode.EXECUTION_ID_CONFLICT)
    if disposition is ExecutionReservationDispositionV1.CERTIFICATE_ALREADY_RESERVED:
        _fail(MoneyGovernorFailureCode.CERTIFICATE_ALREADY_EXECUTED)
    if disposition is ExecutionReservationDispositionV1.MARKET_ALREADY_RESERVED:
        _fail(MoneyGovernorFailureCode.MARKET_ALREADY_EXECUTED)
    if disposition not in {
        ExecutionReservationDispositionV1.CREATED,
        ExecutionReservationDispositionV1.EXISTING_SAME,
    }:
        raise ValueError("unsupported execution reservation disposition")

    return _build_plan(
        certificate=certificate,
        request=validated_request,
        fingerprint=fingerprint,
        transfer_lines=transfer_lines,
    )
