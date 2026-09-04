"""Governor-gated, GET-only Razorpay Test Mode order reconciliation."""

import base64
import http.client
import json
import re
import ssl
from datetime import datetime
from enum import StrEnum
from typing import Final, Never, cast
from urllib.parse import urlencode

from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.domain import Money
from clear_market.execution import (
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    authorize_execution_v1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderStatusV1,
    RazorpayOrderV1,
    RazorpayTestCredentialsV1,
    razorpay_order_create_fingerprint_v1,
)
from clear_market.payments.razorpay.credentials import _credential_pair
from clear_market.payments.recovery.models import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryResultV1,
)
from clear_market.persistence import (
    ProviderReferenceDispositionV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
)

_HOST: Final[str] = "api.razorpay.com"
_PORT: Final[int] = 443
_TIMEOUT_SECONDS: Final[int] = 10
_ORDERS_PATH: Final[str] = "/v1/orders"
_MAX_RESPONSE_BYTES: Final[int] = 262_144
_PROVIDER_NAME: Final[str] = "razorpay"
_REFERENCE_KIND: Final[str] = "order"
_PROVIDER_REFERENCE_PAGE_SIZE: Final[int] = 1_000
_IDEMPOTENCY_NAMESPACE: Final[str] = "razorpay.order.create.v1"
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"order_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)


class RazorpayOrderRecoveryFailureCode(StrEnum):
    LOCAL_PROVIDER_REFERENCE_CONFLICT = "LOCAL_PROVIDER_REFERENCE_CONFLICT"
    CREATE_INTENT_MISSING = "CREATE_INTENT_MISSING"
    CREATE_INTENT_CONFLICT = "CREATE_INTENT_CONFLICT"
    PROVIDER_ORDER_QUERY_FAILED = "PROVIDER_ORDER_QUERY_FAILED"
    PROVIDER_ORDER_AMBIGUOUS = "PROVIDER_ORDER_AMBIGUOUS"
    PROVIDER_ORDER_FETCH_FAILED = "PROVIDER_ORDER_FETCH_FAILED"
    PROVIDER_ORDER_MISMATCH = "PROVIDER_ORDER_MISMATCH"


class RazorpayOrderRecoveryError(RuntimeError):
    """Stable recovery failure without local, provider, financial, or credential detail."""

    __slots__ = ("_code",)

    def __init__(self, code: RazorpayOrderRecoveryFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> RazorpayOrderRecoveryFailureCode:
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


def _fail(code: RazorpayOrderRecoveryFailureCode) -> Never:
    raise RazorpayOrderRecoveryError(code)


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
        parsed = json.loads(
            data.decode("utf-8", errors="strict"),
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


def _authorization_header(credentials: RazorpayTestCredentialsV1) -> str:
    key_id, key_secret = _credential_pair(credentials)
    encoded = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode("ascii")
    return f"Basic {encoded}"


def _https_get(
    *,
    path: str,
    credentials: RazorpayTestCredentialsV1,
) -> tuple[int, bytes]:
    connection = http.client.HTTPSConnection(
        _HOST,
        _PORT,
        timeout=_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/json",
                "Authorization": _authorization_header(credentials),
            },
        )
        response = connection.getresponse()
        return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
    finally:
        try:
            connection.close()
        except OSError:
            pass


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


def _query_candidate(
    *,
    payload: dict[str, object],
    plan: ExecutionPlanV1,
) -> str | None:
    entity = _exact_str(payload, "entity")
    count = _exact_int(payload, "count")
    items = payload.get("items")
    if entity != "collection" or not 0 <= count <= 100 or type(items) is not list:
        raise _InvalidProviderPayload

    typed_items = cast(list[object], items)
    if count != len(typed_items):
        raise _InvalidProviderPayload

    provider_order_ids: list[str] = []
    for item in typed_items:
        if type(item) is not dict:
            raise _InvalidProviderPayload
        candidate = cast(dict[str, object], item)
        provider_order_id = _exact_str(candidate, "id")
        candidate_entity = _exact_str(candidate, "entity")
        amount = _exact_int(candidate, "amount")
        currency = _exact_str(candidate, "currency")
        receipt = _exact_str(candidate, "receipt")
        if (
            _ORDER_ID_PATTERN.fullmatch(provider_order_id) is None
            or candidate_entity != "order"
            or amount != plan.order_amount.amount_paise
            or currency != "INR"
            or receipt != plan.execution_id
        ):
            raise _ProviderOrderMismatch
        provider_order_ids.append(provider_order_id)

    if len(provider_order_ids) > 1:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_AMBIGUOUS)
    return provider_order_ids[0] if provider_order_ids else None


def _validated_provider_order(
    *,
    payload: dict[str, object],
    plan: ExecutionPlanV1,
    provider_order_id: str,
) -> RazorpayOrderV1:
    response_order_id = _exact_str(payload, "id")
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
    if "offers" in payload:
        offers = payload["offers"]
        if type(offers) is not list:
            raise _InvalidProviderPayload
        if offers:
            raise _ProviderOrderMismatch

    try:
        status = RazorpayOrderStatusV1(status_text)
    except ValueError:
        raise _ProviderOrderMismatch from None
    if (
        _ORDER_ID_PATTERN.fullmatch(response_order_id) is None
        or response_order_id != provider_order_id
        or entity != "order"
        or amount != plan.order_amount.amount_paise
        or amount_paid < 0
        or amount_due < 0
        or amount_paid > amount
        or amount_due > amount
        or amount_paid + amount_due != amount
        or currency != "INR"
        or receipt != plan.execution_id
        or attempts < 0
    ):
        raise _ProviderOrderMismatch

    return RazorpayOrderV1(
        execution_id=plan.execution_id,
        provider_order_id=response_order_id,
        amount=Money(amount_paise=amount),
        receipt=receipt,
        status=status,
    )


def _fetch_order(
    *,
    plan: ExecutionPlanV1,
    provider_order_id: str,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayOrderV1:
    if _ORDER_ID_PATTERN.fullmatch(provider_order_id) is None:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH)
    try:
        status, data = _https_get(
            path=f"{_ORDERS_PATH}/{provider_order_id}",
            credentials=credentials,
        )
    except _TRANSPORT_ERRORS:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED)
    if status != 200:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED)
    try:
        return _validated_provider_order(
            payload=_provider_object(data),
            plan=plan,
            provider_order_id=provider_order_id,
        )
    except _InvalidProviderPayload:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED)
    except _ProviderOrderMismatch:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH)


def _discover_order(
    *,
    plan: ExecutionPlanV1,
    credentials: RazorpayTestCredentialsV1,
) -> str | None:
    query = urlencode(
        (
            ("receipt", plan.execution_id),
            ("count", "100"),
            ("skip", "0"),
        )
    )
    try:
        status, data = _https_get(
            path=f"{_ORDERS_PATH}?{query}",
            credentials=credentials,
        )
    except _TRANSPORT_ERRORS:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED)
    if status != 200:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED)
    try:
        return _query_candidate(payload=_provider_object(data), plan=plan)
    except _InvalidProviderPayload:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED)
    except _ProviderOrderMismatch:
        _fail(RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH)


def _result(
    *,
    disposition: RazorpayOrderRecoveryDispositionV1,
    plan: ExecutionPlanV1,
    fingerprint: str,
    order: RazorpayOrderV1 | None,
) -> RazorpayOrderRecoveryResultV1:
    return RazorpayOrderRecoveryResultV1(
        disposition=disposition,
        execution_id=plan.execution_id,
        order_create_fingerprint_sha256=fingerprint,
        order=order,
    )


def recover_razorpay_test_order_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_request: ExecutionAuthorizationRequestV1,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayOrderRecoveryResultV1:
    """Authorize anew, then reconcile one prior order intent without provider mutation."""
    plan = authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=trusted_signing_identities,
        request=execution_request,
        decision_time=decision_time,
        ledger=ledger,
    )
    _credential_pair(credentials)
    fingerprint = razorpay_order_create_fingerprint_v1(plan)

    references = _razorpay_order_references(
        ledger=ledger,
        execution_id=plan.execution_id,
    )
    if len(references) > 1:
        _fail(RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT)
    if references:
        order = _fetch_order(
            plan=plan,
            provider_order_id=references[0].reference_id,
            credentials=credentials,
        )
        return _result(
            disposition=RazorpayOrderRecoveryDispositionV1.EXISTING,
            plan=plan,
            fingerprint=fingerprint,
            order=order,
        )

    create_intent = ledger.get_idempotency_record(
        namespace=_IDEMPOTENCY_NAMESPACE,
        idempotency_key=plan.execution_id,
    )
    if create_intent is None:
        _fail(RazorpayOrderRecoveryFailureCode.CREATE_INTENT_MISSING)
    if (
        create_intent.namespace != _IDEMPOTENCY_NAMESPACE
        or create_intent.idempotency_key != plan.execution_id
        or create_intent.request_fingerprint_sha256 != fingerprint
        or create_intent.execution_id != plan.execution_id
    ):
        _fail(RazorpayOrderRecoveryFailureCode.CREATE_INTENT_CONFLICT)

    provider_order_id = _discover_order(plan=plan, credentials=credentials)
    if provider_order_id is None:
        return _result(
            disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
            plan=plan,
            fingerprint=fingerprint,
            order=None,
        )

    order = _fetch_order(
        plan=plan,
        provider_order_id=provider_order_id,
        credentials=credentials,
    )
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
        _fail(RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT)
    if reference_result.disposition not in {
        ProviderReferenceDispositionV1.CREATED,
        ProviderReferenceDispositionV1.EXISTING_SAME,
    }:
        raise ValueError("unsupported provider reference disposition")

    persisted = _razorpay_order_references(
        ledger=ledger,
        execution_id=plan.execution_id,
    )
    if len(persisted) != 1 or persisted[0].reference_id != order.provider_order_id:
        _fail(RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT)
    return _result(
        disposition=RazorpayOrderRecoveryDispositionV1.RECOVERED,
        plan=plan,
        fingerprint=fingerprint,
        order=order,
    )
