"""Authenticated Razorpay webhook ingress with durable body and event-ID dedupe."""

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Never, cast
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from clear_market.domain import MAX_MONEY_PAISE, Money, UTCDateTime
from clear_market.payments.razorpay.webhook_config import (
    RazorpayWebhookVerificationConfigV1,
    _verification_material,
)
from clear_market.payments.razorpay.webhook_models import (
    RazorpayWebhookDispositionV1,
    RazorpayWebhookEventTypeV1,
    RazorpayWebhookEventV1,
    RazorpayWebhookPaymentStatusV1,
    RazorpayWebhookResultV1,
)
from clear_market.persistence import (
    FinancialLedgerEventAppendDispositionV1,
    FinancialLedgerEventV1,
    FinancialLedgerFieldV1,
    FinancialLedgerValueType,
    IdempotencyRecordV1,
    ProviderReferenceDispositionV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
)
from clear_market.persistence.sqlite import _IdempotencyPairConflict

_MAX_RAW_BODY_BYTES: Final[int] = 1_048_576
_SIGNATURE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Fa-f]{64}", flags=re.ASCII)
_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"acc_[A-Za-z0-9]{1,14}", flags=re.ASCII)
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"order_[A-Za-z0-9]{1,128}", flags=re.ASCII)
_PAYMENT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"pay_[A-Za-z0-9]{1,128}", flags=re.ASCII)
_PROVIDER_NAME: Final[str] = "razorpay"
_ORDER_REFERENCE_KIND: Final[str] = "order"
_PAYMENT_REFERENCE_KIND: Final[str] = "payment"
_EVENT_ID_NAMESPACE: Final[str] = "razorpay.webhook.event-id.v1"
_RAW_BODY_NAMESPACE: Final[str] = "razorpay.webhook.raw-body.v1"
_EVENT_ID_SEPARATOR: Final[bytes] = b"clear.razorpay.webhook.financial-event.v1\x00"
_UTC_DATETIME_ADAPTER: TypeAdapter[datetime] = TypeAdapter(UTCDateTime)


class RazorpayWebhookFailureCode(StrEnum):
    RAW_BODY_TOO_LARGE = "RAW_BODY_TOO_LARGE"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    INVALID_EVENT_ID = "INVALID_EVENT_ID"
    INVALID_WEBHOOK_PAYLOAD = "INVALID_WEBHOOK_PAYLOAD"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    UNSUPPORTED_EVENT = "UNSUPPORTED_EVENT"
    UNKNOWN_ORDER_REFERENCE = "UNKNOWN_ORDER_REFERENCE"
    PAYMENT_REFERENCE_CONFLICT = "PAYMENT_REFERENCE_CONFLICT"
    EVENT_ID_CONFLICT = "EVENT_ID_CONFLICT"
    WEBHOOK_BODY_CONFLICT = "WEBHOOK_BODY_CONFLICT"
    LOCAL_EVENT_CONFLICT = "LOCAL_EVENT_CONFLICT"


class RazorpayWebhookError(ValueError):
    """Stable sanitized webhook-ingress failure."""

    __slots__ = ("_code",)

    def __init__(self, code: RazorpayWebhookFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> RazorpayWebhookFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _NonStandardConstantError(ValueError):
    pass


def _fail(code: RazorpayWebhookFailureCode) -> Never:
    raise RazorpayWebhookError(code)


def _raw_body(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 1:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    if len(value) > _MAX_RAW_BODY_BYTES:
        _fail(RazorpayWebhookFailureCode.RAW_BODY_TOO_LARGE)
    return value


def razorpay_webhook_raw_body_digest_v1(raw_body: bytes) -> str:
    """Hash exact bounded transport bytes; the digest alone grants no authentication."""
    return hashlib.sha256(_raw_body(raw_body)).hexdigest()


def _signature_bytes(value: object) -> bytes:
    if type(value) is not str or _SIGNATURE_PATTERN.fullmatch(value) is None:
        _fail(RazorpayWebhookFailureCode.INVALID_SIGNATURE)
    try:
        return bytes.fromhex(value)
    except ValueError:
        _fail(RazorpayWebhookFailureCode.INVALID_SIGNATURE)


def _authenticate(raw_body: bytes, signature: bytes, secrets: tuple[str, ...]) -> None:
    matches = tuple(
        hmac.compare_digest(
            hmac.digest(secret.encode("utf-8"), raw_body, "sha256"),
            signature,
        )
        for secret in secrets
    )
    if not any(matches):
        _fail(RazorpayWebhookFailureCode.INVALID_SIGNATURE)


def _event_id(value: object) -> str:
    if type(value) is not str or "\x00" in value:
        _fail(RazorpayWebhookFailureCode.INVALID_EVENT_ID)
    try:
        length = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        _fail(RazorpayWebhookFailureCode.INVALID_EVENT_ID)
    if not 1 <= length <= 512:
        _fail(RazorpayWebhookFailureCode.INVALID_EVENT_ID)
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise _NonStandardConstantError


def _parse_json_object(raw_body: bytes) -> dict[str, object]:
    if b"\x00" in raw_body:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    try:
        parsed = json.loads(
            raw_body.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        _DuplicateKeyError,
        _NonStandardConstantError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ):
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    if type(parsed) is not dict:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return cast(dict[str, object], parsed)


def _exact_str(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if type(value) is not str:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return value


def _exact_int(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return value


def _exact_bool(payload: dict[str, object], name: str) -> bool:
    value = payload.get(name)
    if type(value) is not bool:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return value


def _dict(payload: dict[str, object], name: str) -> dict[str, object]:
    value = payload.get(name)
    if type(value) is not dict:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return cast(dict[str, object], value)


def _unix_time(value: int) -> tuple[int, datetime]:
    if value < 0:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    try:
        converted = datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError):
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return value, converted


def _received_at(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("received_at must be an aware datetime")
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError:
        raise ValueError("received_at must be an aware datetime") from None


def _root_fields(
    payload: dict[str, object],
) -> tuple[str, str, dict[str, object], int, datetime]:
    entity = _exact_str(payload, "entity")
    account_id = _exact_str(payload, "account_id")
    event = _exact_str(payload, "event")
    contains = payload.get("contains")
    nested = _dict(payload, "payload")
    created_at, occurred_at = _unix_time(_exact_int(payload, "created_at"))
    if (
        entity != "event"
        or _ACCOUNT_ID_PATTERN.fullmatch(account_id) is None
        or type(contains) is not list
        or "payment" not in contains
    ):
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return account_id, event, nested, created_at, occurred_at


def _payment_fields(
    payload: dict[str, object],
) -> tuple[str, str, int, RazorpayWebhookPaymentStatusV1, bool, int]:
    payment_container = _dict(payload, "payment")
    payment = _dict(payment_container, "entity")
    provider_payment_id = _exact_str(payment, "id")
    entity = _exact_str(payment, "entity")
    amount = _exact_int(payment, "amount")
    currency = _exact_str(payment, "currency")
    status_text = _exact_str(payment, "status")
    provider_order_id = _exact_str(payment, "order_id")
    captured = _exact_bool(payment, "captured")
    created_at, _created = _unix_time(_exact_int(payment, "created_at"))
    if (
        entity != "payment"
        or _PAYMENT_ID_PATTERN.fullmatch(provider_payment_id) is None
        or _ORDER_ID_PATTERN.fullmatch(provider_order_id) is None
        or not 1 <= amount <= MAX_MONEY_PAISE
        or currency != "INR"
    ):
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    try:
        status = RazorpayWebhookPaymentStatusV1(status_text)
    except ValueError:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)
    return provider_payment_id, provider_order_id, amount, status, captured, created_at


def _event_type(value: str) -> RazorpayWebhookEventTypeV1:
    try:
        return RazorpayWebhookEventTypeV1(value)
    except ValueError:
        _fail(RazorpayWebhookFailureCode.UNSUPPORTED_EVENT)


def _require_event_semantics(
    event_type: RazorpayWebhookEventTypeV1,
    status: RazorpayWebhookPaymentStatusV1,
    captured: bool,
) -> None:
    expected = {
        RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED: (
            RazorpayWebhookPaymentStatusV1.AUTHORIZED,
            False,
        ),
        RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED: (
            RazorpayWebhookPaymentStatusV1.CAPTURED,
            True,
        ),
        RazorpayWebhookEventTypeV1.PAYMENT_FAILED: (
            RazorpayWebhookPaymentStatusV1.FAILED,
            False,
        ),
    }[event_type]
    if (status, captured) != expected:
        _fail(RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD)


def _body_event_id(digest: str) -> str:
    identifier = bytearray(
        hashlib.sha256(_EVENT_ID_SEPARATOR + digest.encode("ascii")).digest()[:16]
    )
    identifier[6] = (identifier[6] & 0x0F) | 0x40
    identifier[8] = (identifier[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(identifier)))


def _field(
    key: str,
    value_type: FinancialLedgerValueType,
    value: str | int | bool,
) -> FinancialLedgerFieldV1:
    return FinancialLedgerFieldV1(field_key=key, value_type=value_type, value=value)


def _ledger_event(
    event: RazorpayWebhookEventV1,
    occurred_at: datetime,
) -> FinancialLedgerEventV1:
    event_type = {
        RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED: ("razorpay.webhook.payment_authorized.v1"),
        RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED: "razorpay.webhook.payment_captured.v1",
        RazorpayWebhookEventTypeV1.PAYMENT_FAILED: "razorpay.webhook.payment_failed.v1",
    }[event.event_type]
    return FinancialLedgerEventV1(
        event_id=_body_event_id(event.raw_body_sha256),
        execution_id=event.execution_id,
        event_type=event_type,
        occurred_at=occurred_at,
        fields=(
            _field(
                "amount_paise",
                FinancialLedgerValueType.INTEGER,
                event.amount.amount_paise,
            ),
            _field("captured", FinancialLedgerValueType.BOOLEAN, event.captured),
            _field("currency", FinancialLedgerValueType.STRING, event.amount.currency.value),
            _field(
                "payment_status",
                FinancialLedgerValueType.STRING,
                event.payment_status.value,
            ),
            _field(
                "provider_account_id",
                FinancialLedgerValueType.STRING,
                event.provider_account_id,
            ),
            _field(
                "provider_event_created_at_unix",
                FinancialLedgerValueType.INTEGER,
                event.provider_event_created_at_unix,
            ),
            _field(
                "provider_event_type",
                FinancialLedgerValueType.STRING,
                event.event_type.value,
            ),
            _field(
                "provider_order_id",
                FinancialLedgerValueType.STRING,
                event.provider_order_id,
            ),
            _field(
                "provider_payment_created_at_unix",
                FinancialLedgerValueType.INTEGER,
                event.provider_payment_created_at_unix,
            ),
            _field(
                "provider_payment_id",
                FinancialLedgerValueType.STRING,
                event.provider_payment_id,
            ),
            _field(
                "raw_body_digest_version",
                FinancialLedgerValueType.STRING,
                event.raw_body_digest_version,
            ),
            _field(
                "raw_body_sha256",
                FinancialLedgerValueType.STRING,
                event.raw_body_sha256,
            ),
        ),
    )


def authenticate_and_record_razorpay_webhook_v1(
    *,
    raw_body: bytes,
    signature_header: str,
    event_id_header: str,
    verification_config: RazorpayWebhookVerificationConfigV1,
    received_at: datetime,
    ledger: SQLiteFinancialLedgerV1,
) -> RazorpayWebhookResultV1:
    """Authenticate exact raw bytes and durably record facts without deriving payment state."""
    body = _raw_body(raw_body)
    signature = _signature_bytes(signature_header)
    expected_account_id, secrets = _verification_material(verification_config)
    _authenticate(body, signature, secrets)
    provider_event_id = _event_id(event_id_header)
    parsed = _parse_json_object(body)
    provider_account_id, event_text, payload, root_created_at, occurred_at = _root_fields(parsed)
    if provider_account_id != expected_account_id:
        _fail(RazorpayWebhookFailureCode.ACCOUNT_MISMATCH)
    event_type = _event_type(event_text)
    (
        provider_payment_id,
        provider_order_id,
        amount_paise,
        payment_status,
        captured,
        payment_created_at,
    ) = _payment_fields(payload)
    _require_event_semantics(event_type, payment_status, captured)
    observed_at = _received_at(received_at)
    digest = razorpay_webhook_raw_body_digest_v1(body)

    order_reference = ledger.get_provider_reference(
        provider_name=_PROVIDER_NAME,
        reference_kind=_ORDER_REFERENCE_KIND,
        reference_id=provider_order_id,
    )
    if order_reference is None:
        _fail(RazorpayWebhookFailureCode.UNKNOWN_ORDER_REFERENCE)
    execution_id = order_reference.execution_id

    existing_payment = ledger.get_provider_reference(
        provider_name=_PROVIDER_NAME,
        reference_kind=_PAYMENT_REFERENCE_KIND,
        reference_id=provider_payment_id,
    )
    if existing_payment is not None and existing_payment.execution_id != execution_id:
        _fail(RazorpayWebhookFailureCode.PAYMENT_REFERENCE_CONFLICT)

    try:
        ledger.claim_idempotency_pair(
            IdempotencyRecordV1(
                namespace=_EVENT_ID_NAMESPACE,
                idempotency_key=provider_event_id,
                request_fingerprint_sha256=digest,
                execution_id=execution_id,
                recorded_at=observed_at,
            ),
            IdempotencyRecordV1(
                namespace=_RAW_BODY_NAMESPACE,
                idempotency_key=digest,
                request_fingerprint_sha256=digest,
                execution_id=execution_id,
                recorded_at=observed_at,
            ),
        )
    except _IdempotencyPairConflict as error:
        _fail(
            RazorpayWebhookFailureCode.EVENT_ID_CONFLICT
            if error.index == 0
            else RazorpayWebhookFailureCode.WEBHOOK_BODY_CONFLICT
        )

    reference_result = ledger.record_provider_reference(
        ProviderReferenceV1(
            provider_name=_PROVIDER_NAME,
            reference_kind=_PAYMENT_REFERENCE_KIND,
            reference_id=provider_payment_id,
            execution_id=execution_id,
            recorded_at=observed_at,
        )
    )
    if reference_result.disposition is ProviderReferenceDispositionV1.REFERENCE_CONFLICT:
        _fail(RazorpayWebhookFailureCode.PAYMENT_REFERENCE_CONFLICT)
    if reference_result.disposition not in {
        ProviderReferenceDispositionV1.CREATED,
        ProviderReferenceDispositionV1.EXISTING_SAME,
    }:
        raise ValueError("unsupported provider reference disposition")

    event = RazorpayWebhookEventV1(
        raw_body_sha256=digest,
        provider_event_id=provider_event_id,
        provider_account_id=provider_account_id,
        event_type=event_type,
        execution_id=execution_id,
        provider_order_id=provider_order_id,
        provider_payment_id=provider_payment_id,
        amount=Money(amount_paise=amount_paise),
        payment_status=payment_status,
        captured=captured,
        provider_payment_created_at_unix=payment_created_at,
        provider_event_created_at_unix=root_created_at,
    )
    append_result = ledger.append_event(_ledger_event(event, occurred_at))
    if append_result.disposition is FinancialLedgerEventAppendDispositionV1.EVENT_ID_CONFLICT:
        _fail(RazorpayWebhookFailureCode.LOCAL_EVENT_CONFLICT)
    if append_result.disposition is FinancialLedgerEventAppendDispositionV1.CREATED:
        disposition = RazorpayWebhookDispositionV1.RECORDED
    elif append_result.disposition is FinancialLedgerEventAppendDispositionV1.EXISTING_SAME:
        disposition = RazorpayWebhookDispositionV1.DUPLICATE
    else:
        raise ValueError("unsupported event append disposition")
    return RazorpayWebhookResultV1(
        disposition=disposition,
        event=event,
        ledger_sequence_number=append_result.persisted_event.sequence_number,
    )
