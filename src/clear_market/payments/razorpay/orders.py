"""Governor-gated Razorpay Test Mode Order creation and retrieval."""

import base64
import hashlib
import http.client
import json
import re
import ssl
from datetime import datetime
from enum import StrEnum
from typing import Final, Never, cast

from pydantic import ValidationError

from clear_market.canonical import CANONICALIZATION_VERSION, canonical_json_bytes
from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.domain import Money
from clear_market.execution import (
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    authorize_execution_v1,
)
from clear_market.payments.razorpay.credentials import (
    RazorpayTestCredentialsV1,
    _credential_pair,
)
from clear_market.payments.razorpay.models import (
    RazorpayOrderResolutionV1,
    RazorpayOrderResultV1,
    RazorpayOrderStatusV1,
    RazorpayOrderV1,
)
from clear_market.persistence import (
    IdempotencyDispositionV1,
    IdempotencyRecordV1,
    ProviderReferenceDispositionV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
)

_HOST: Final[str] = "api.razorpay.com"
_PORT: Final[int] = 443
_TIMEOUT_SECONDS: Final[int] = 10
_ORDERS_PATH: Final[str] = "/v1/orders"
_MAX_REQUEST_BYTES: Final[int] = 8_192
_MAX_RESPONSE_BYTES: Final[int] = 262_144
_PROVIDER_NAME: Final[str] = "razorpay"
_REFERENCE_KIND: Final[str] = "order"
_PROVIDER_REFERENCE_PAGE_SIZE: Final[int] = 1_000
_IDEMPOTENCY_NAMESPACE: Final[str] = "razorpay.order.create.v1"
_ORDER_ID_PATTERN = re.compile(r"order_[A-Za-z0-9]{1,128}", flags=re.ASCII)


class RazorpayOrderFailureCode(StrEnum):
    LOCAL_PROVIDER_REFERENCE_CONFLICT = "LOCAL_PROVIDER_REFERENCE_CONFLICT"
    LOCAL_IDEMPOTENCY_CONFLICT = "LOCAL_IDEMPOTENCY_CONFLICT"
    ORDER_CREATION_RECOVERY_REQUIRED = "ORDER_CREATION_RECOVERY_REQUIRED"
    EXISTING_ORDER_FETCH_FAILED = "EXISTING_ORDER_FETCH_FAILED"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    PROVIDER_ORDER_MISMATCH = "PROVIDER_ORDER_MISMATCH"


class RazorpayOrderError(RuntimeError):
    """Stable sanitized provider-boundary failure."""

    __slots__ = ("_code",)

    def __init__(self, code: RazorpayOrderFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> RazorpayOrderFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _NonStandardConstantError(ValueError):
    pass


class _InvalidProviderPayload(ValueError):
    pass


class _ProviderOrderMismatch(ValueError):
    pass


_TRANSPORT_ERRORS = (TimeoutError, ssl.SSLError, http.client.HTTPException, OSError)


def _fail(code: RazorpayOrderFailureCode) -> Never:
    raise RazorpayOrderError(code)


def _fresh_plan(value: object) -> ExecutionPlanV1:
    if type(value) is not ExecutionPlanV1:
        raise TypeError("plan must be exactly an ExecutionPlanV1")
    try:
        fields = {name: value.__dict__[name] for name in ExecutionPlanV1.model_fields}
        return ExecutionPlanV1.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("plan must be a valid exact ExecutionPlanV1") from None


def canonical_razorpay_order_create_intent_v1_bytes(plan: ExecutionPlanV1) -> bytes:
    """Bind a potential order action; direct plan construction grants no provider authority."""
    value = _fresh_plan(plan)
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "razorpay_order_create_intent_v1",
            "payload": {
                "schema_version": value.schema_version,
                "razorpay_order_create_intent_version": "razorpay-order-create-intent-v1",
                "execution_id": value.execution_id,
                "certificate_digest_version": value.certificate_digest_version,
                "certificate_digest_sha256": value.certificate_digest_sha256,
                "execution_request_fingerprint_version": (
                    value.execution_request_fingerprint_version
                ),
                "execution_request_fingerprint_sha256": (
                    value.execution_request_fingerprint_sha256
                ),
                "amount_paise": value.order_amount.amount_paise,
                "currency": value.order_amount.currency.value,
                "receipt": value.execution_id,
            },
        }
    )


def razorpay_order_create_fingerprint_v1(plan: ExecutionPlanV1) -> str:
    """Hash the pure create intent; this helper does not authorize or perform provider I/O."""
    return hashlib.sha256(canonical_razorpay_order_create_intent_v1_bytes(plan)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise _NonStandardConstantError


def _provider_object(data: bytes) -> dict[str, object]:
    if len(data) > _MAX_RESPONSE_BYTES or b"\x00" in data:
        raise _InvalidProviderPayload
    try:
        text = data.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
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
        raise _InvalidProviderPayload from None
    if type(parsed) is not dict:
        raise _InvalidProviderPayload
    return cast(dict[str, object], parsed)


def _exact_str(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if type(value) is not str:
        raise _InvalidProviderPayload
    return value


def _exact_int(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise _InvalidProviderPayload
    return value


def _validated_provider_order(
    *,
    payload: dict[str, object],
    plan: ExecutionPlanV1,
    stored_provider_order_id: str | None,
    creation: bool,
) -> RazorpayOrderV1:
    provider_order_id = _exact_str(payload, "id")
    entity = _exact_str(payload, "entity")
    amount = _exact_int(payload, "amount")
    amount_paid = _exact_int(payload, "amount_paid")
    amount_due = _exact_int(payload, "amount_due")
    currency = _exact_str(payload, "currency")
    receipt = _exact_str(payload, "receipt")
    status_text = _exact_str(payload, "status")
    attempts = _exact_int(payload, "attempts")
    if "partial_payment" in payload:
        partial_payment = payload["partial_payment"]
        if type(partial_payment) is not bool:
            raise _InvalidProviderPayload
        if partial_payment:
            raise _ProviderOrderMismatch
    if "offer_id" in payload and payload["offer_id"] is not None:
        raise _ProviderOrderMismatch
    if _ORDER_ID_PATTERN.fullmatch(provider_order_id) is None:
        raise _InvalidProviderPayload
    try:
        status = RazorpayOrderStatusV1(status_text)
    except ValueError:
        raise _InvalidProviderPayload from None

    expected_amount = plan.order_amount.amount_paise
    if creation:
        if (
            entity != "order"
            or amount != expected_amount
            or amount_paid != 0
            or amount_due != expected_amount
            or currency != "INR"
            or receipt != plan.execution_id
            or status is not RazorpayOrderStatusV1.CREATED
            or attempts != 0
        ):
            raise _ProviderOrderMismatch
    elif (
        provider_order_id != stored_provider_order_id
        or entity != "order"
        or amount != expected_amount
        or currency != "INR"
        or receipt != plan.execution_id
        or amount_paid < 0
        or amount_due < 0
        or amount_paid > amount
        or amount_due > amount
        or amount_paid + amount_due != amount
        or attempts < 0
    ):
        raise _ProviderOrderMismatch

    return RazorpayOrderV1(
        execution_id=plan.execution_id,
        provider_order_id=provider_order_id,
        amount=Money(amount_paise=amount),
        receipt=receipt,
        status=status,
    )


def _authorization_header(credentials: RazorpayTestCredentialsV1) -> str:
    key_id, key_secret = _credential_pair(credentials)
    encoded = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode("ascii")
    return f"Basic {encoded}"


def _https_request(
    *,
    method: str,
    path: str,
    credentials: RazorpayTestCredentialsV1,
    body: bytes | None,
) -> tuple[int, bytes]:
    connection = http.client.HTTPSConnection(
        _HOST,
        _PORT,
        timeout=_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        headers = {
            "Accept": "application/json",
            "Authorization": _authorization_header(credentials),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _request_body(plan: ExecutionPlanV1) -> bytes:
    body = json.dumps(
        {
            "amount": plan.order_amount.amount_paise,
            "currency": "INR",
            "partial_payment": False,
            "receipt": plan.execution_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(body) > _MAX_REQUEST_BYTES:
        raise ValueError("Razorpay order request exceeds the byte limit")
    return body


def _existing_order(
    *,
    plan: ExecutionPlanV1,
    provider_order_id: str,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayOrderResultV1:
    if _ORDER_ID_PATTERN.fullmatch(provider_order_id) is None:
        _fail(RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH)
    try:
        status, data = _https_request(
            method="GET",
            path=f"{_ORDERS_PATH}/{provider_order_id}",
            credentials=credentials,
            body=None,
        )
    except _TRANSPORT_ERRORS:
        _fail(RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED)
    if status != 200:
        _fail(RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED)
    try:
        order = _validated_provider_order(
            payload=_provider_object(data),
            plan=plan,
            stored_provider_order_id=provider_order_id,
            creation=False,
        )
    except _InvalidProviderPayload:
        _fail(RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED)
    except _ProviderOrderMismatch:
        _fail(RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH)
    return RazorpayOrderResultV1(
        resolution=RazorpayOrderResolutionV1.EXISTING,
        order=order,
    )


def _razorpay_order_references(
    *,
    ledger: SQLiteFinancialLedgerV1,
    execution_id: str,
) -> tuple[ProviderReferenceV1, ...]:
    matches: list[ProviderReferenceV1] = []
    offset = 0
    while True:
        page = ledger.list_provider_references(
            execution_id,
            limit=_PROVIDER_REFERENCE_PAGE_SIZE,
            offset=offset,
        )
        matches.extend(
            reference
            for reference in page
            if reference.provider_name == _PROVIDER_NAME
            and reference.reference_kind == _REFERENCE_KIND
        )
        if len(matches) > 1 or len(page) < _PROVIDER_REFERENCE_PAGE_SIZE:
            return tuple(matches)
        offset += len(page)


def create_razorpay_test_order_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_request: ExecutionAuthorizationRequestV1,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayOrderResultV1:
    """Authorize first, then create at most one Razorpay Test Mode order attempt."""
    plan = authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=trusted_signing_identities,
        request=execution_request,
        decision_time=decision_time,
        ledger=ledger,
    )
    _credential_pair(credentials)

    references = _razorpay_order_references(
        ledger=ledger,
        execution_id=plan.execution_id,
    )
    if len(references) > 1:
        _fail(RazorpayOrderFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT)
    if references:
        return _existing_order(
            plan=plan,
            provider_order_id=references[0].reference_id,
            credentials=credentials,
        )

    fingerprint = razorpay_order_create_fingerprint_v1(plan)
    claim = ledger.claim_idempotency(
        IdempotencyRecordV1(
            namespace=_IDEMPOTENCY_NAMESPACE,
            idempotency_key=plan.execution_id,
            request_fingerprint_sha256=fingerprint,
            execution_id=plan.execution_id,
            recorded_at=decision_time,
        )
    )
    if claim.disposition is IdempotencyDispositionV1.EXISTING_SAME:
        _fail(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)
    if claim.disposition is IdempotencyDispositionV1.CONFLICT:
        _fail(RazorpayOrderFailureCode.LOCAL_IDEMPOTENCY_CONFLICT)
    if claim.disposition is not IdempotencyDispositionV1.CREATED:
        raise ValueError("unsupported idempotency disposition")

    try:
        status, data = _https_request(
            method="POST",
            path=_ORDERS_PATH,
            credentials=credentials,
            body=_request_body(plan),
        )
    except _TRANSPORT_ERRORS:
        _fail(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)
    if status != 200:
        _fail(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)
    try:
        order = _validated_provider_order(
            payload=_provider_object(data),
            plan=plan,
            stored_provider_order_id=None,
            creation=True,
        )
    except (_InvalidProviderPayload, _ProviderOrderMismatch):
        _fail(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)

    reference_result = ledger.record_provider_reference(
        ProviderReferenceV1(
            provider_name=_PROVIDER_NAME,
            reference_kind=_REFERENCE_KIND,
            reference_id=order.provider_order_id,
            execution_id=plan.execution_id,
            recorded_at=decision_time,
        )
    )
    if reference_result.disposition is ProviderReferenceDispositionV1.REFERENCE_CONFLICT:
        _fail(RazorpayOrderFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT)
    if reference_result.disposition not in {
        ProviderReferenceDispositionV1.CREATED,
        ProviderReferenceDispositionV1.EXISTING_SAME,
    }:
        raise ValueError("unsupported provider reference disposition")
    persisted_order_references = _razorpay_order_references(
        ledger=ledger,
        execution_id=plan.execution_id,
    )
    if (
        len(persisted_order_references) != 1
        or persisted_order_references[0].reference_id != order.provider_order_id
    ):
        _fail(RazorpayOrderFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT)
    return RazorpayOrderResultV1(
        resolution=RazorpayOrderResolutionV1.CREATED,
        order=order,
    )
