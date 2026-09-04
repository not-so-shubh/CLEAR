"""Read-only deterministic Razorpay payment-state replay."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal, Never, cast

from pydantic import TypeAdapter, ValidationError

from clear_market.certificate.v2 import (
    ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    AllocationCertificateV2,
    AllocationClaimStatusV2,
    allocation_certificate_v2_digest,
)
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.domain import MAX_MONEY_PAISE, CanonicalUUID4, Money
from clear_market.payments.razorpay.webhook_models import (
    RazorpayWebhookEventTypeV1,
    RazorpayWebhookPaymentStatusV1,
)
from clear_market.payments.state.models import (
    ClearPaymentStateSnapshotV1,
    ClearPaymentStateV1,
    RazorpayPaymentEvidenceV1,
    _RelevantLedgerEventType,
)
from clear_market.persistence import (
    FinancialLedgerValueType,
    PersistedFinancialLedgerEventV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
)
from clear_market.verification.v2 import verify_allocation_certificate_v2

_PAGE_SIZE: Final[int] = 1_000
_PROVIDER_NAME: Final[str] = "razorpay"
_ORDER_REFERENCE_KIND: Final[str] = "order"
_PAYMENT_REFERENCE_KIND: Final[str] = "payment"
_RAW_BODY_DIGEST_VERSION: Final[str] = "sha256-razorpay-webhook-raw-body-v1"
type _CertificateDigestVersion = Literal["sha256-allocation-certificate-v2-clear-json-v1"]
type _RawBodyDigestVersion = Literal["sha256-razorpay-webhook-raw-body-v1"]
_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"acc_[A-Za-z0-9]{1,14}",
    flags=re.ASCII,
)
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"order_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_PAYMENT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"pay_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_EXECUTION_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(CanonicalUUID4)

_EVENT_TYPES: Final[
    dict[
        str,
        tuple[
            RazorpayWebhookEventTypeV1,
            RazorpayWebhookPaymentStatusV1,
            bool,
        ],
    ]
] = {
    "razorpay.webhook.payment_authorized.v1": (
        RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED,
        RazorpayWebhookPaymentStatusV1.AUTHORIZED,
        False,
    ),
    "razorpay.webhook.payment_captured.v1": (
        RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
        RazorpayWebhookPaymentStatusV1.CAPTURED,
        True,
    ),
    "razorpay.webhook.payment_failed.v1": (
        RazorpayWebhookEventTypeV1.PAYMENT_FAILED,
        RazorpayWebhookPaymentStatusV1.FAILED,
        False,
    ),
}

_FIELD_TYPES: Final[dict[str, FinancialLedgerValueType]] = {
    "amount_paise": FinancialLedgerValueType.INTEGER,
    "captured": FinancialLedgerValueType.BOOLEAN,
    "currency": FinancialLedgerValueType.STRING,
    "payment_status": FinancialLedgerValueType.STRING,
    "provider_account_id": FinancialLedgerValueType.STRING,
    "provider_event_created_at_unix": FinancialLedgerValueType.INTEGER,
    "provider_event_type": FinancialLedgerValueType.STRING,
    "provider_order_id": FinancialLedgerValueType.STRING,
    "provider_payment_created_at_unix": FinancialLedgerValueType.INTEGER,
    "provider_payment_id": FinancialLedgerValueType.STRING,
    "raw_body_digest_version": FinancialLedgerValueType.STRING,
    "raw_body_sha256": FinancialLedgerValueType.STRING,
}


class PaymentStateFailureCode(StrEnum):
    CERTIFICATE_NOT_VERIFIED = "CERTIFICATE_NOT_VERIFIED"
    ALLOCATION_NOT_EXECUTABLE = "ALLOCATION_NOT_EXECUTABLE"
    EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
    EXECUTION_BINDING_MISMATCH = "EXECUTION_BINDING_MISMATCH"
    ORDER_REFERENCE_MISSING = "ORDER_REFERENCE_MISSING"
    ORDER_REFERENCE_CONFLICT = "ORDER_REFERENCE_CONFLICT"
    PAYMENT_EVIDENCE_INVALID = "PAYMENT_EVIDENCE_INVALID"
    PAYMENT_ACCOUNT_MISMATCH = "PAYMENT_ACCOUNT_MISMATCH"
    PAYMENT_ORDER_MISMATCH = "PAYMENT_ORDER_MISMATCH"
    PAYMENT_ECONOMIC_MISMATCH = "PAYMENT_ECONOMIC_MISMATCH"
    PAYMENT_REFERENCE_MISSING = "PAYMENT_REFERENCE_MISSING"
    PAYMENT_REFERENCE_CONFLICT = "PAYMENT_REFERENCE_CONFLICT"
    INCOMPLETE_PAYMENT_INGRESS = "INCOMPLETE_PAYMENT_INGRESS"
    MULTIPLE_ACTIVE_PAYMENTS = "MULTIPLE_ACTIVE_PAYMENTS"


class PaymentStateError(ValueError):
    """Stable sanitized payment-state replay failure."""

    __slots__ = ("_code",)

    def __init__(self, code: PaymentStateFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> PaymentStateFailureCode:
        return self._code


class _EffectivePaymentState(StrEnum):
    FAILED = "FAILED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"


@dataclass(frozen=True, slots=True)
class _StoredPaymentFact:
    ledger_sequence_number: int
    ledger_event_id: str
    execution_id: str
    ledger_event_type: _RelevantLedgerEventType
    occurred_at: datetime
    raw_body_digest_version: str
    raw_body_sha256: str
    provider_account_id: str
    webhook_event_type: RazorpayWebhookEventTypeV1
    provider_order_id: str
    provider_payment_id: str
    amount_paise: int
    currency: str
    payment_status: RazorpayWebhookPaymentStatusV1
    captured: bool
    provider_payment_created_at_unix: int
    provider_event_created_at_unix: int


def _fail(code: PaymentStateFailureCode) -> Never:
    raise PaymentStateError(code)


def _execution_id(value: object) -> str:
    try:
        return _EXECUTION_ID_ADAPTER.validate_python(value)
    except ValidationError:
        raise ValueError("execution_id must be a canonical UUIDv4 string") from None


def _expected_account_id(value: object) -> str:
    if type(value) is not str or _ACCOUNT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("expected Razorpay account ID is not canonical")
    return value


def _fresh_certificate(value: AllocationCertificateV2) -> AllocationCertificateV2:
    try:
        fields = {name: value.__dict__[name] for name in AllocationCertificateV2.model_fields}
        return AllocationCertificateV2.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("certificate must remain a valid exact AllocationCertificateV2") from None


def _references(
    ledger: SQLiteFinancialLedgerV1,
    execution_id: str,
) -> tuple[tuple[ProviderReferenceV1, ...], tuple[ProviderReferenceV1, ...]]:
    orders: list[ProviderReferenceV1] = []
    payments: list[ProviderReferenceV1] = []
    offset = 0
    while True:
        page = ledger.list_provider_references(
            execution_id,
            limit=_PAGE_SIZE,
            offset=offset,
        )
        for reference in page:
            if reference.provider_name != _PROVIDER_NAME:
                continue
            if reference.reference_kind == _ORDER_REFERENCE_KIND:
                orders.append(reference)
            elif reference.reference_kind == _PAYMENT_REFERENCE_KIND:
                payments.append(reference)
        if len(page) < _PAGE_SIZE:
            return tuple(orders), tuple(payments)
        offset += len(page)


def _relevant_events(
    ledger: SQLiteFinancialLedgerV1,
    execution_id: str,
) -> tuple[PersistedFinancialLedgerEventV1, ...]:
    relevant: list[PersistedFinancialLedgerEventV1] = []
    cursor = 0
    while True:
        page = ledger.list_events(
            execution_id,
            after_sequence=cursor,
            limit=_PAGE_SIZE,
        )
        relevant.extend(item for item in page if item.event.event_type in _EVENT_TYPES)
        if len(page) < _PAGE_SIZE:
            return tuple(relevant)
        following_cursor = page[-1].sequence_number
        if following_cursor <= cursor:
            _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
        cursor = following_cursor


def _exact_str(value: object) -> str:
    if type(value) is not str:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    return value


def _exact_int(value: object) -> int:
    if type(value) is not int:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    return value


def _exact_bool(value: object) -> bool:
    if type(value) is not bool:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    return value


def _stored_fact(value: PersistedFinancialLedgerEventV1) -> _StoredPaymentFact:
    event = value.event
    fields = event.fields
    if len(fields) != len(_FIELD_TYPES):
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    by_key = {field.field_key: field for field in fields}
    if set(by_key) != set(_FIELD_TYPES):
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    if any(by_key[key].value_type is not expected for key, expected in _FIELD_TYPES.items()):
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)

    event_semantics = _EVENT_TYPES.get(event.event_type)
    if event_semantics is None:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    webhook_event_type, expected_status, expected_captured = event_semantics
    provider_event_type = _exact_str(by_key["provider_event_type"].value)
    payment_status_text = _exact_str(by_key["payment_status"].value)
    captured = _exact_bool(by_key["captured"].value)
    if provider_event_type != webhook_event_type.value:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    try:
        payment_status = RazorpayWebhookPaymentStatusV1(payment_status_text)
    except ValueError:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    if payment_status is not expected_status or captured is not expected_captured:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)

    provider_event_created_at = _exact_int(by_key["provider_event_created_at_unix"].value)
    provider_payment_created_at = _exact_int(by_key["provider_payment_created_at_unix"].value)
    if provider_event_created_at < 0 or provider_payment_created_at < 0:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    try:
        expected_occurred_at = datetime.fromtimestamp(provider_event_created_at, tz=UTC)
        datetime.fromtimestamp(provider_payment_created_at, tz=UTC)
    except (OSError, OverflowError, ValueError):
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    if event.occurred_at != expected_occurred_at:
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)

    raw_body_digest_version = _exact_str(by_key["raw_body_digest_version"].value)
    raw_body_sha256 = _exact_str(by_key["raw_body_sha256"].value)
    provider_account_id = _exact_str(by_key["provider_account_id"].value)
    provider_order_id = _exact_str(by_key["provider_order_id"].value)
    provider_payment_id = _exact_str(by_key["provider_payment_id"].value)
    amount_paise = _exact_int(by_key["amount_paise"].value)
    currency = _exact_str(by_key["currency"].value)
    if (
        raw_body_digest_version != _RAW_BODY_DIGEST_VERSION
        or _SHA256_PATTERN.fullmatch(raw_body_sha256) is None
        or _ACCOUNT_ID_PATTERN.fullmatch(provider_account_id) is None
        or _ORDER_ID_PATTERN.fullmatch(provider_order_id) is None
        or _PAYMENT_ID_PATTERN.fullmatch(provider_payment_id) is None
        or not 0 <= amount_paise <= MAX_MONEY_PAISE
    ):
        _fail(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)

    return _StoredPaymentFact(
        ledger_sequence_number=value.sequence_number,
        ledger_event_id=event.event_id,
        execution_id=event.execution_id,
        ledger_event_type=cast(_RelevantLedgerEventType, event.event_type),
        occurred_at=event.occurred_at,
        raw_body_digest_version=raw_body_digest_version,
        raw_body_sha256=raw_body_sha256,
        provider_account_id=provider_account_id,
        webhook_event_type=webhook_event_type,
        provider_order_id=provider_order_id,
        provider_payment_id=provider_payment_id,
        amount_paise=amount_paise,
        currency=currency,
        payment_status=payment_status,
        captured=captured,
        provider_payment_created_at_unix=provider_payment_created_at,
        provider_event_created_at_unix=provider_event_created_at,
    )


def _evidence(value: _StoredPaymentFact) -> RazorpayPaymentEvidenceV1:
    return RazorpayPaymentEvidenceV1(
        ledger_sequence_number=value.ledger_sequence_number,
        ledger_event_id=value.ledger_event_id,
        execution_id=value.execution_id,
        ledger_event_type=value.ledger_event_type,
        occurred_at=value.occurred_at,
        raw_body_digest_version=cast(
            _RawBodyDigestVersion,
            value.raw_body_digest_version,
        ),
        raw_body_sha256=value.raw_body_sha256,
        provider_account_id=value.provider_account_id,
        webhook_event_type=value.webhook_event_type,
        provider_order_id=value.provider_order_id,
        provider_payment_id=value.provider_payment_id,
        amount=Money(amount_paise=value.amount_paise),
        payment_status=value.payment_status,
        captured=value.captured,
        provider_payment_created_at_unix=value.provider_payment_created_at_unix,
        provider_event_created_at_unix=value.provider_event_created_at_unix,
    )


def _effective_state(
    evidence: tuple[RazorpayPaymentEvidenceV1, ...],
) -> _EffectivePaymentState:
    if any(
        item.webhook_event_type is RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED for item in evidence
    ):
        return _EffectivePaymentState.CAPTURED
    latest_timestamp = max(item.provider_event_created_at_unix for item in evidence)
    latest = tuple(
        item for item in evidence if item.provider_event_created_at_unix == latest_timestamp
    )
    if any(
        item.webhook_event_type is RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED for item in latest
    ):
        return _EffectivePaymentState.AUTHORIZED
    return _EffectivePaymentState.FAILED


def _state(
    evidence: tuple[RazorpayPaymentEvidenceV1, ...],
) -> tuple[ClearPaymentStateV1, str | None]:
    by_payment: dict[str, list[RazorpayPaymentEvidenceV1]] = {}
    for item in evidence:
        by_payment.setdefault(item.provider_payment_id, []).append(item)
    effective = {
        payment_id: _effective_state(tuple(items)) for payment_id, items in by_payment.items()
    }
    active = tuple(
        (payment_id, state)
        for payment_id, state in effective.items()
        if state in {_EffectivePaymentState.AUTHORIZED, _EffectivePaymentState.CAPTURED}
    )
    if len(active) > 1:
        _fail(PaymentStateFailureCode.MULTIPLE_ACTIVE_PAYMENTS)
    if active:
        payment_id, state = active[0]
        return (
            ClearPaymentStateV1.PAYMENT_CAPTURED
            if state is _EffectivePaymentState.CAPTURED
            else ClearPaymentStateV1.PAYMENT_AUTHORIZED,
            payment_id,
        )
    if evidence:
        return ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED, None
    return ClearPaymentStateV1.ORDER_CREATED, None


def derive_razorpay_payment_state_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_id: str,
    expected_razorpay_account_id: str,
    ledger: SQLiteFinancialLedgerV1,
) -> ClearPaymentStateSnapshotV1:
    """Independently verify and replay immutable observations without performing any side effect.

    ``expected_razorpay_account_id`` is trusted explicit application configuration used to bind
    authenticated ledger facts. It is not cryptographic proof of ownership of that provider
    account.
    """
    if type(certificate) is not AllocationCertificateV2:
        raise TypeError("certificate must be exactly an AllocationCertificateV2")
    if type(ledger) is not SQLiteFinancialLedgerV1:
        raise TypeError("ledger must be exactly a SQLiteFinancialLedgerV1")
    validated_execution_id = _execution_id(execution_id)
    expected_account = _expected_account_id(expected_razorpay_account_id)

    verification = verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=trusted_signing_identities,
    )
    if not verification.verified:
        _fail(PaymentStateFailureCode.CERTIFICATE_NOT_VERIFIED)
    validated_certificate = _fresh_certificate(certificate)

    allocation = validated_certificate.allocation
    if (
        allocation.status is not AllocationClaimStatusV2.FEASIBLE
        or allocation.fulfilled_quantity <= 0
        or allocation.total_payment.amount_paise <= 0
        or allocation.winner_count <= 0
        or not allocation.lines
    ):
        _fail(PaymentStateFailureCode.ALLOCATION_NOT_EXECUTABLE)

    digest = allocation_certificate_v2_digest(validated_certificate)
    market_id = validated_certificate.buyer_policy.market_spec.market_id
    reservation = ledger.get_execution_reservation(validated_execution_id)
    if reservation is None:
        _fail(PaymentStateFailureCode.EXECUTION_NOT_FOUND)
    if (
        reservation.execution_id != validated_execution_id
        or reservation.certificate_digest_version != ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION
        or reservation.certificate_digest_sha256 != digest
        or reservation.market_id != market_id
    ):
        _fail(PaymentStateFailureCode.EXECUTION_BINDING_MISMATCH)

    order_references, payment_references = _references(ledger, validated_execution_id)
    if not order_references:
        _fail(PaymentStateFailureCode.ORDER_REFERENCE_MISSING)
    if (
        len(order_references) != 1
        or _ORDER_ID_PATTERN.fullmatch(order_references[0].reference_id) is None
    ):
        _fail(PaymentStateFailureCode.ORDER_REFERENCE_CONFLICT)
    provider_order_id = order_references[0].reference_id

    stored_facts = tuple(
        _stored_fact(item) for item in _relevant_events(ledger, validated_execution_id)
    )
    if any(item.provider_account_id != expected_account for item in stored_facts):
        _fail(PaymentStateFailureCode.PAYMENT_ACCOUNT_MISMATCH)
    if any(item.provider_order_id != provider_order_id for item in stored_facts):
        _fail(PaymentStateFailureCode.PAYMENT_ORDER_MISMATCH)
    expected_amount = allocation.total_payment
    if any(
        item.amount_paise != expected_amount.amount_paise or item.currency != "INR"
        for item in stored_facts
    ):
        _fail(PaymentStateFailureCode.PAYMENT_ECONOMIC_MISMATCH)

    evidence_payment_ids = {item.provider_payment_id for item in stored_facts}
    for payment_id in evidence_payment_ids:
        reference = ledger.get_provider_reference(
            provider_name=_PROVIDER_NAME,
            reference_kind=_PAYMENT_REFERENCE_KIND,
            reference_id=payment_id,
        )
        if reference is None:
            _fail(PaymentStateFailureCode.PAYMENT_REFERENCE_MISSING)
        if reference.execution_id != validated_execution_id:
            _fail(PaymentStateFailureCode.PAYMENT_REFERENCE_CONFLICT)
    reference_payment_ids = {reference.reference_id for reference in payment_references}
    if reference_payment_ids - evidence_payment_ids:
        _fail(PaymentStateFailureCode.INCOMPLETE_PAYMENT_INGRESS)

    evidence = tuple(_evidence(item) for item in stored_facts)
    state, effective_payment_id = _state(evidence)
    return ClearPaymentStateSnapshotV1(
        execution_id=validated_execution_id,
        certificate_digest_version=cast(
            _CertificateDigestVersion,
            ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
        ),
        certificate_digest_sha256=digest,
        provider_account_id=expected_account,
        provider_order_id=provider_order_id,
        expected_amount=expected_amount,
        state=state,
        effective_payment_id=effective_payment_id,
        evidence=evidence,
    )
