"""Governor-gated Razorpay Test Mode payment-transfer execution and reconciliation."""

import base64
import hashlib
import http.client
import json
import re
import ssl
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Never, cast

from pydantic import BaseModel, ValidationError

from clear_market.canonical import CANONICALIZATION_VERSION, canonical_json_bytes
from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.domain import Money
from clear_market.execution import (
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    authorize_execution_v1,
)
from clear_market.payments.razorpay import (
    RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION,
    RazorpayLinkedAccountBindingV1,
    RazorpayRouteMappingPlanV1,
    RazorpayRouteMappingRequestV1,
    RazorpayTestCredentialsV1,
    build_razorpay_route_mapping_v1,
)
from clear_market.payments.razorpay.credentials import _credential_pair
from clear_market.payments.state import ClearPaymentStateV1, derive_razorpay_payment_state_v1
from clear_market.payments.transfers.models import (
    RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION,
    RazorpaySettlementStatusV1,
    RazorpayTransferBatchDispositionV1,
    RazorpayTransferBatchResultV1,
    RazorpayTransferObservationV1,
    RazorpayTransferStatusV1,
)
from clear_market.persistence import (
    FinancialLedgerEventAppendDispositionV1,
    FinancialLedgerEventV1,
    FinancialLedgerFieldV1,
    FinancialLedgerValueType,
    IdempotencyDispositionV1,
    IdempotencyRecordV1,
    ProviderReferenceDispositionV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
)

_HOST: Final[str] = "api.razorpay.com"
_PORT: Final[int] = 443
_TIMEOUT_SECONDS: Final[int] = 10
_MAX_REQUEST_BYTES: Final[int] = 262_144
_MAX_RESPONSE_BYTES: Final[int] = 262_144
_PAGE_SIZE: Final[int] = 1_000
_PROVIDER_NAME: Final[str] = "razorpay"
_REFERENCE_KIND: Final[str] = "transfer"
_INTENT_NAMESPACE: Final[str] = "razorpay.payment.transfers.create.v1"
_IDENTITY_EVENT_TYPE: Final[str] = "razorpay.route.transfer_identity.v1"
_IDENTITY_EVENT_DOMAIN: Final[bytes] = b"clear.razorpay.route.transfer-identity.v1\x00"
_PAYMENT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"pay_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_TRANSFER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"trf_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_TRANSPORT_ERRORS = (TimeoutError, ssl.SSLError, http.client.HTTPException, OSError)


class RazorpayTransferFailureCode(StrEnum):
    PAYMENT_NOT_CAPTURED = "PAYMENT_NOT_CAPTURED"
    EXECUTION_ARTIFACT_MISMATCH = "EXECUTION_ARTIFACT_MISMATCH"
    PAYMENT_PROVIDER_FETCH_FAILED = "PAYMENT_PROVIDER_FETCH_FAILED"
    PAYMENT_PROVIDER_MISMATCH = "PAYMENT_PROVIDER_MISMATCH"
    LINKED_ACCOUNT_FETCH_FAILED = "LINKED_ACCOUNT_FETCH_FAILED"
    LINKED_ACCOUNT_MISMATCH = "LINKED_ACCOUNT_MISMATCH"
    LINKED_ACCOUNT_NOT_ACTIVE = "LINKED_ACCOUNT_NOT_ACTIVE"
    PROVIDER_TRANSFER_AMOUNT_UNSUPPORTED = "PROVIDER_TRANSFER_AMOUNT_UNSUPPORTED"
    TRANSFER_REQUEST_TOO_LARGE = "TRANSFER_REQUEST_TOO_LARGE"
    TRANSFER_INTENT_MISSING = "TRANSFER_INTENT_MISSING"
    TRANSFER_INTENT_CONFLICT = "TRANSFER_INTENT_CONFLICT"
    TRANSFER_PREFLIGHT_CONFLICT = "TRANSFER_PREFLIGHT_CONFLICT"
    TRANSFER_CREATION_RECOVERY_REQUIRED = "TRANSFER_CREATION_RECOVERY_REQUIRED"
    PROVIDER_TRANSFER_SET_CONFLICT = "PROVIDER_TRANSFER_SET_CONFLICT"
    TRANSFER_REFERENCE_CONFLICT = "TRANSFER_REFERENCE_CONFLICT"
    LOCAL_TRANSFER_REFERENCE_CONFLICT = "LOCAL_TRANSFER_REFERENCE_CONFLICT"
    TRANSFER_LEDGER_CONFLICT = "TRANSFER_LEDGER_CONFLICT"


class RazorpayTransferError(RuntimeError):
    """Stable transfer failure without financial, provider, or credential detail."""

    __slots__ = ("_code",)

    def __init__(self, code: RazorpayTransferFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> RazorpayTransferFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _NonStandardConstantError(ValueError):
    pass


class _InvalidProviderPayload(ValueError):
    pass


class _ProviderMismatch(ValueError):
    pass


class _EmptyProviderTransferSet(ValueError):
    pass


def _fail(code: RazorpayTransferFailureCode) -> Never:
    raise RazorpayTransferError(code)


def _fresh_exact_model[ModelT: BaseModel](
    value: object,
    expected_type: type[ModelT],
    message: str,
) -> ModelT:
    if type(value) is not expected_type:
        raise TypeError(message)
    try:
        fields = {name: value.__dict__[name] for name in expected_type.model_fields}
        return expected_type.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(message) from None


def _payment_id(value: object) -> str:
    if type(value) is not str or _PAYMENT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("provider_payment_id is not canonical")
    return value


def _request_artifacts(
    *,
    execution_plan: ExecutionPlanV1,
    route_mapping_plan: RazorpayRouteMappingPlanV1,
    provider_payment_id: str,
) -> tuple[ExecutionPlanV1, RazorpayRouteMappingPlanV1, str]:
    plan = _fresh_exact_model(
        execution_plan,
        ExecutionPlanV1,
        "execution_plan must be a valid exact ExecutionPlanV1",
    )
    mapping = _fresh_exact_model(
        route_mapping_plan,
        RazorpayRouteMappingPlanV1,
        "route_mapping_plan must be a valid exact RazorpayRouteMappingPlanV1",
    )
    payment_id = _payment_id(provider_payment_id)
    if (
        mapping.execution_id != plan.execution_id
        or mapping.certificate_digest_version != plan.certificate_digest_version
        or mapping.certificate_digest_sha256 != plan.certificate_digest_sha256
        or mapping.execution_request_fingerprint_version
        != plan.execution_request_fingerprint_version
        or mapping.execution_request_fingerprint_sha256 != plan.execution_request_fingerprint_sha256
        or mapping.order_amount != plan.order_amount
        or len(mapping.transfer_lines) != len(plan.transfer_lines)
    ):
        _fail(RazorpayTransferFailureCode.EXECUTION_ARTIFACT_MISMATCH)
    for execution_line, route_line in zip(plan.transfer_lines, mapping.transfer_lines, strict=True):
        if (
            route_line.allocation_line_index != execution_line.allocation_line_index
            or route_line.offer_id != execution_line.offer_id
            or route_line.merchant_id != execution_line.merchant_id
            or route_line.sku_id != execution_line.sku_id
            or route_line.recipient_authorization_id != execution_line.recipient_authorization_id
            or route_line.recipient_id != execution_line.recipient_id
            or route_line.allocated_quantity != execution_line.allocated_quantity
            or route_line.transfer_amount != execution_line.transfer_amount
        ):
            _fail(RazorpayTransferFailureCode.EXECUTION_ARTIFACT_MISMATCH)
    return plan, mapping, payment_id


def _provider_request_projection(
    plan: ExecutionPlanV1,
    mapping: RazorpayRouteMappingPlanV1,
) -> dict[str, object]:
    return {
        "transfers": [
            {
                "account": line.razorpay_account_id,
                "amount": line.transfer_amount.amount_paise,
                "currency": "INR",
                "notes": {
                    "clear_execution_id": plan.execution_id,
                    "clear_line_index": str(line.allocation_line_index),
                    "clear_route_mapping_sha256": (
                        mapping.razorpay_route_mapping_fingerprint_sha256
                    ),
                },
                "on_hold": False,
            }
            for line in mapping.transfer_lines
        ]
    }


def canonical_razorpay_payment_transfer_request_v1_bytes(
    *,
    execution_plan: ExecutionPlanV1,
    route_mapping_plan: RazorpayRouteMappingPlanV1,
    provider_payment_id: str,
) -> bytes:
    """Return exact provider request bytes without granting transfer authority."""
    plan, mapping, _payment = _request_artifacts(
        execution_plan=execution_plan,
        route_mapping_plan=route_mapping_plan,
        provider_payment_id=provider_payment_id,
    )
    try:
        data = json.dumps(
            _provider_request_projection(plan, mapping),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (UnicodeEncodeError, ValueError):
        _fail(RazorpayTransferFailureCode.TRANSFER_REQUEST_TOO_LARGE)
    if len(data) > _MAX_REQUEST_BYTES:
        _fail(RazorpayTransferFailureCode.TRANSFER_REQUEST_TOO_LARGE)
    return data


def razorpay_payment_transfer_request_fingerprint_v1(
    *,
    execution_plan: ExecutionPlanV1,
    route_mapping_plan: RazorpayRouteMappingPlanV1,
    provider_payment_id: str,
) -> str:
    """Bind exact transfer intent without credentials, time, or provider-created IDs."""
    plan, mapping, payment_id = _request_artifacts(
        execution_plan=execution_plan,
        route_mapping_plan=route_mapping_plan,
        provider_payment_id=provider_payment_id,
    )
    provider_request = _provider_request_projection(plan, mapping)
    envelope = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload_type": "razorpay_payment_transfer_request_v1",
        "payload": {
            "schema_version": "1",
            "razorpay_payment_transfer_execution_version": (
                RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION
            ),
            "provider_payment_id": payment_id,
            "execution_id": plan.execution_id,
            "certificate_digest_version": plan.certificate_digest_version,
            "certificate_digest_sha256": plan.certificate_digest_sha256,
            "execution_request_fingerprint_version": (plan.execution_request_fingerprint_version),
            "execution_request_fingerprint_sha256": (plan.execution_request_fingerprint_sha256),
            "route_mapping_fingerprint_version": (
                mapping.razorpay_route_mapping_fingerprint_version
            ),
            "route_mapping_fingerprint_sha256": (mapping.razorpay_route_mapping_fingerprint_sha256),
            "transfer_lines": [
                {
                    "schema_version": line.schema_version,
                    "razorpay_route_transfer_line_version": (
                        line.razorpay_route_transfer_line_version
                    ),
                    "allocation_line_index": line.allocation_line_index,
                    "offer_id": line.offer_id,
                    "merchant_id": line.merchant_id,
                    "sku_id": line.sku_id,
                    "recipient_authorization_id": line.recipient_authorization_id,
                    "recipient_id": line.recipient_id,
                    "linked_account_binding_id": line.linked_account_binding_id,
                    "razorpay_account_id": line.razorpay_account_id,
                    "allocated_quantity": line.allocated_quantity,
                    "transfer_amount": {
                        "amount_paise": line.transfer_amount.amount_paise,
                        "currency": line.transfer_amount.currency.value,
                    },
                }
                for line in mapping.transfer_lines
            ],
            "provider_request_body": provider_request,
        },
    }
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


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


def _get_provider_object(
    *,
    path: str,
    credentials: RazorpayTestCredentialsV1,
    failure: RazorpayTransferFailureCode,
) -> dict[str, object]:
    try:
        status, data = _https_request(
            method="GET",
            path=path,
            credentials=credentials,
            body=None,
        )
    except _TRANSPORT_ERRORS:
        _fail(failure)
    if status != 200:
        _fail(failure)
    try:
        return _provider_object(data)
    except _InvalidProviderPayload:
        _fail(failure)


def _validate_provider_payment(
    *,
    plan: ExecutionPlanV1,
    provider_payment_id: str,
    provider_order_id: str,
    credentials: RazorpayTestCredentialsV1,
) -> None:
    payload = _get_provider_object(
        path=f"/v1/payments/{provider_payment_id}",
        credentials=credentials,
        failure=RazorpayTransferFailureCode.PAYMENT_PROVIDER_FETCH_FAILED,
    )
    try:
        payment_id = _exact_str(payload, "id")
        entity = _exact_str(payload, "entity")
        amount = _exact_int(payload, "amount")
        currency = _exact_str(payload, "currency")
        status = _exact_str(payload, "status")
        order_id = _exact_str(payload, "order_id")
        captured = payload.get("captured")
        amount_refunded = _exact_int(payload, "amount_refunded")
        if type(captured) is not bool:
            raise _InvalidProviderPayload
        if (
            payment_id != provider_payment_id
            or entity != "payment"
            or amount != plan.order_amount.amount_paise
            or currency != "INR"
            or status != "captured"
            or captured is not True
            or order_id != provider_order_id
            or amount_refunded != 0
            or ("refund_status" in payload and payload["refund_status"] is not None)
        ):
            raise _ProviderMismatch
    except _InvalidProviderPayload:
        _fail(RazorpayTransferFailureCode.PAYMENT_PROVIDER_FETCH_FAILED)
    except _ProviderMismatch:
        _fail(RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH)


def _validate_linked_account(
    *,
    account_id: str,
    credentials: RazorpayTestCredentialsV1,
) -> None:
    payload = _get_provider_object(
        path=f"/v2/accounts/{account_id}",
        credentials=credentials,
        failure=RazorpayTransferFailureCode.LINKED_ACCOUNT_FETCH_FAILED,
    )
    try:
        response_id = _exact_str(payload, "id")
        account_type = _exact_str(payload, "type")
        status = _exact_str(payload, "status")
    except _InvalidProviderPayload:
        _fail(RazorpayTransferFailureCode.LINKED_ACCOUNT_FETCH_FAILED)
    if response_id != account_id or account_type != "route":
        _fail(RazorpayTransferFailureCode.LINKED_ACCOUNT_MISMATCH)
    if status != "created":
        _fail(RazorpayTransferFailureCode.LINKED_ACCOUNT_NOT_ACTIVE)


def _collection_items(payload: dict[str, object]) -> list[object]:
    entity = _exact_str(payload, "entity")
    count = _exact_int(payload, "count")
    items = payload.get("items")
    if entity != "collection" or count < 0 or type(items) is not list:
        raise _InvalidProviderPayload
    typed_items = cast(list[object], items)
    if count != len(typed_items):
        raise _ProviderMismatch
    return typed_items


def _line_index(notes: dict[str, object]) -> int:
    text = _exact_str(notes, "clear_line_index")
    if not text.isascii() or not text.isdecimal():
        raise _ProviderMismatch
    value = int(text)
    if str(value) != text:
        raise _ProviderMismatch
    return value


def _transfer_status(payload: dict[str, object]) -> RazorpayTransferStatusV1:
    has_status = "status" in payload
    has_transfer_status = "transfer_status" in payload
    if not has_status and not has_transfer_status:
        raise _InvalidProviderPayload
    status = _exact_str(payload, "status") if has_status else None
    transfer_status = _exact_str(payload, "transfer_status") if has_transfer_status else None
    if status is not None and transfer_status is not None and status != transfer_status:
        raise _ProviderMismatch
    try:
        return RazorpayTransferStatusV1(cast(str, status or transfer_status))
    except ValueError:
        raise _ProviderMismatch from None


def _settlement_status(payload: dict[str, object]) -> RazorpaySettlementStatusV1 | None:
    if "settlement_status" not in payload or payload["settlement_status"] is None:
        return None
    value = payload["settlement_status"]
    if type(value) is not str:
        raise _InvalidProviderPayload
    try:
        return RazorpaySettlementStatusV1(value)
    except ValueError:
        raise _ProviderMismatch from None


def _validated_transfer_set(
    *,
    payload: dict[str, object],
    mapping: RazorpayRouteMappingPlanV1,
    provider_payment_id: str,
) -> tuple[RazorpayTransferObservationV1, ...]:
    items = _collection_items(payload)
    if not items:
        raise _EmptyProviderTransferSet
    if len(items) != len(mapping.transfer_lines):
        raise _ProviderMismatch
    expected = {line.allocation_line_index: line for line in mapping.transfer_lines}
    observations: dict[int, RazorpayTransferObservationV1] = {}
    transfer_ids: set[str] = set()
    for item in items:
        if type(item) is not dict:
            raise _InvalidProviderPayload
        value = cast(dict[str, object], item)
        notes_value = value.get("notes")
        if type(notes_value) is not dict:
            raise _InvalidProviderPayload
        notes = cast(dict[str, object], notes_value)
        index = _line_index(notes)
        line = expected.get(index)
        if line is None or index in observations:
            raise _ProviderMismatch
        provider_transfer_id = _exact_str(value, "id")
        entity = _exact_str(value, "entity")
        source = _exact_str(value, "source")
        recipient = _exact_str(value, "recipient")
        amount = _exact_int(value, "amount")
        currency = _exact_str(value, "currency")
        amount_reversed = _exact_int(value, "amount_reversed")
        created_at = _exact_int(value, "created_at")
        if (
            _TRANSFER_ID_PATTERN.fullmatch(provider_transfer_id) is None
            or provider_transfer_id in transfer_ids
            or entity != "transfer"
            or source != provider_payment_id
            or recipient != line.razorpay_account_id
            or amount != line.transfer_amount.amount_paise
            or currency != "INR"
            or amount_reversed < 0
            or amount_reversed > amount
            or created_at < 0
            or _exact_str(notes, "clear_execution_id") != mapping.execution_id
            or _exact_str(notes, "clear_route_mapping_sha256")
            != mapping.razorpay_route_mapping_fingerprint_sha256
        ):
            raise _ProviderMismatch
        try:
            datetime.fromtimestamp(created_at, tz=UTC)
        except (OSError, OverflowError, ValueError):
            raise _ProviderMismatch from None
        transfer_ids.add(provider_transfer_id)
        observations[index] = RazorpayTransferObservationV1(
            allocation_line_index=index,
            provider_transfer_id=provider_transfer_id,
            provider_payment_id=provider_payment_id,
            razorpay_account_id=line.razorpay_account_id,
            amount=Money(amount_paise=amount),
            transfer_status=_transfer_status(value),
            settlement_status=_settlement_status(value),
            amount_reversed=amount_reversed,
            created_at_unix=created_at,
        )
    if set(observations) != set(expected):
        raise _ProviderMismatch
    return tuple(observations[index] for index in range(len(observations)))


def _transfer_collection(
    *,
    method: str,
    path: str,
    credentials: RazorpayTestCredentialsV1,
    body: bytes | None,
    transport_failure: RazorpayTransferFailureCode,
) -> dict[str, object]:
    if method not in {"GET", "POST"}:
        raise ValueError("unsupported transfer collection method")
    try:
        status, data = _https_request(
            method=method,
            path=path,
            credentials=credentials,
            body=body,
        )
    except _TRANSPORT_ERRORS:
        _fail(transport_failure)
    if (method == "GET" and status != 200) or (method == "POST" and not 200 <= status < 300):
        _fail(transport_failure)
    try:
        return _provider_object(data)
    except _InvalidProviderPayload:
        _fail(transport_failure)


def _transfer_references(
    *,
    ledger: SQLiteFinancialLedgerV1,
    execution_id: str,
) -> tuple[ProviderReferenceV1, ...]:
    matches: list[ProviderReferenceV1] = []
    offset = 0
    while True:
        page = ledger.list_provider_references(
            execution_id,
            limit=_PAGE_SIZE,
            offset=offset,
        )
        matches.extend(
            reference
            for reference in page
            if reference.provider_name == _PROVIDER_NAME
            and reference.reference_kind == _REFERENCE_KIND
        )
        if len(page) < _PAGE_SIZE:
            return tuple(matches)
        offset += len(page)


def _identity_event_id(provider_transfer_id: str, fingerprint: str) -> str:
    digest = hashlib.sha256(
        _IDENTITY_EVENT_DOMAIN
        + provider_transfer_id.encode("ascii")
        + b"\x00"
        + fingerprint.encode("ascii")
    ).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _field(
    key: str,
    value_type: FinancialLedgerValueType,
    value: str | int | bool,
) -> FinancialLedgerFieldV1:
    return FinancialLedgerFieldV1(field_key=key, value_type=value_type, value=value)


def _identity_event(
    *,
    plan: ExecutionPlanV1,
    mapping: RazorpayRouteMappingPlanV1,
    observation: RazorpayTransferObservationV1,
    fingerprint: str,
) -> FinancialLedgerEventV1:
    return FinancialLedgerEventV1(
        event_id=_identity_event_id(observation.provider_transfer_id, fingerprint),
        execution_id=plan.execution_id,
        event_type=_IDENTITY_EVENT_TYPE,
        occurred_at=datetime.fromtimestamp(observation.created_at_unix, tz=UTC),
        fields=(
            _field(
                "allocation_line_index",
                FinancialLedgerValueType.INTEGER,
                observation.allocation_line_index,
            ),
            _field(
                "amount_paise",
                FinancialLedgerValueType.INTEGER,
                observation.amount.amount_paise,
            ),
            _field("currency", FinancialLedgerValueType.STRING, "INR"),
            _field(
                "provider_payment_id",
                FinancialLedgerValueType.STRING,
                observation.provider_payment_id,
            ),
            _field(
                "provider_transfer_id",
                FinancialLedgerValueType.STRING,
                observation.provider_transfer_id,
            ),
            _field(
                "razorpay_account_id",
                FinancialLedgerValueType.STRING,
                observation.razorpay_account_id,
            ),
            _field(
                "route_mapping_fingerprint_sha256",
                FinancialLedgerValueType.STRING,
                mapping.razorpay_route_mapping_fingerprint_sha256,
            ),
            _field(
                "transfer_request_fingerprint_sha256",
                FinancialLedgerValueType.STRING,
                fingerprint,
            ),
        ),
    )


def _local_batch_complete(
    *,
    plan: ExecutionPlanV1,
    mapping: RazorpayRouteMappingPlanV1,
    observations: tuple[RazorpayTransferObservationV1, ...],
    fingerprint: str,
    references: tuple[ProviderReferenceV1, ...],
    ledger: SQLiteFinancialLedgerV1,
) -> bool:
    expected_ids = {item.provider_transfer_id for item in observations}
    actual_ids = {item.reference_id for item in references}
    if actual_ids - expected_ids:
        _fail(RazorpayTransferFailureCode.LOCAL_TRANSFER_REFERENCE_CONFLICT)
    if actual_ids != expected_ids:
        return False
    for observation in observations:
        expected = _identity_event(
            plan=plan,
            mapping=mapping,
            observation=observation,
            fingerprint=fingerprint,
        )
        stored = ledger.get_event(expected.event_id)
        if stored is None:
            return False
        if stored.event != expected:
            _fail(RazorpayTransferFailureCode.TRANSFER_LEDGER_CONFLICT)
    return True


def _persist_batch(
    *,
    plan: ExecutionPlanV1,
    mapping: RazorpayRouteMappingPlanV1,
    observations: tuple[RazorpayTransferObservationV1, ...],
    fingerprint: str,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    for observation in observations:
        reference = ProviderReferenceV1(
            provider_name=_PROVIDER_NAME,
            reference_kind=_REFERENCE_KIND,
            reference_id=observation.provider_transfer_id,
            execution_id=plan.execution_id,
            recorded_at=decision_time,
        )
        reference_result = ledger.record_provider_reference(reference)
        if reference_result.disposition is ProviderReferenceDispositionV1.REFERENCE_CONFLICT:
            _fail(RazorpayTransferFailureCode.TRANSFER_REFERENCE_CONFLICT)
        if reference_result.disposition not in {
            ProviderReferenceDispositionV1.CREATED,
            ProviderReferenceDispositionV1.EXISTING_SAME,
        }:
            raise ValueError("unsupported provider reference disposition")

        event = _identity_event(
            plan=plan,
            mapping=mapping,
            observation=observation,
            fingerprint=fingerprint,
        )
        event_result = ledger.append_event(event)
        if event_result.disposition is FinancialLedgerEventAppendDispositionV1.EVENT_ID_CONFLICT:
            _fail(RazorpayTransferFailureCode.TRANSFER_LEDGER_CONFLICT)
        if event_result.disposition not in {
            FinancialLedgerEventAppendDispositionV1.CREATED,
            FinancialLedgerEventAppendDispositionV1.EXISTING_SAME,
        }:
            raise ValueError("unsupported financial event disposition")

    persisted = _transfer_references(ledger=ledger, execution_id=plan.execution_id)
    expected_ids = {item.provider_transfer_id for item in observations}
    if {item.reference_id for item in persisted} != expected_ids:
        _fail(RazorpayTransferFailureCode.LOCAL_TRANSFER_REFERENCE_CONFLICT)
    for observation in observations:
        expected = _identity_event(
            plan=plan,
            mapping=mapping,
            observation=observation,
            fingerprint=fingerprint,
        )
        stored = ledger.get_event(expected.event_id)
        if stored is None or stored.event != expected:
            _fail(RazorpayTransferFailureCode.TRANSFER_LEDGER_CONFLICT)


def _result(
    *,
    disposition: RazorpayTransferBatchDispositionV1,
    plan: ExecutionPlanV1,
    state_order_id: str,
    provider_payment_id: str,
    mapping: RazorpayRouteMappingPlanV1,
    fingerprint: str,
    observations: tuple[RazorpayTransferObservationV1, ...],
) -> RazorpayTransferBatchResultV1:
    if sum(item.amount.amount_paise for item in observations) != plan.order_amount.amount_paise:
        _fail(RazorpayTransferFailureCode.EXECUTION_ARTIFACT_MISMATCH)
    return RazorpayTransferBatchResultV1(
        disposition=disposition,
        execution_id=plan.execution_id,
        provider_order_id=state_order_id,
        provider_payment_id=provider_payment_id,
        transfer_request_fingerprint_sha256=fingerprint,
        route_mapping_fingerprint_version=RAZORPAY_ROUTE_MAPPING_FINGERPRINT_V1_VERSION,
        route_mapping_fingerprint_sha256=(mapping.razorpay_route_mapping_fingerprint_sha256),
        transfers=observations,
    )


def _reconcile(
    *,
    plan: ExecutionPlanV1,
    state_order_id: str,
    provider_payment_id: str,
    mapping: RazorpayRouteMappingPlanV1,
    fingerprint: str,
    references: tuple[ProviderReferenceV1, ...],
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayTransferBatchResultV1:
    path = f"/v1/payments/{provider_payment_id}/transfers"
    payload = _transfer_collection(
        method="GET",
        path=path,
        credentials=credentials,
        body=None,
        transport_failure=RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
    )
    try:
        observations = _validated_transfer_set(
            payload=payload,
            mapping=mapping,
            provider_payment_id=provider_payment_id,
        )
    except _EmptyProviderTransferSet:
        _fail(RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED)
    except _InvalidProviderPayload:
        _fail(RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED)
    except _ProviderMismatch:
        _fail(RazorpayTransferFailureCode.PROVIDER_TRANSFER_SET_CONFLICT)
    complete = _local_batch_complete(
        plan=plan,
        mapping=mapping,
        observations=observations,
        fingerprint=fingerprint,
        references=references,
        ledger=ledger,
    )
    _persist_batch(
        plan=plan,
        mapping=mapping,
        observations=observations,
        fingerprint=fingerprint,
        decision_time=decision_time,
        ledger=ledger,
    )
    return _result(
        disposition=(
            RazorpayTransferBatchDispositionV1.EXISTING
            if complete
            else RazorpayTransferBatchDispositionV1.RECOVERED
        ),
        plan=plan,
        state_order_id=state_order_id,
        provider_payment_id=provider_payment_id,
        mapping=mapping,
        fingerprint=fingerprint,
        observations=observations,
    )


def create_or_reconcile_razorpay_test_transfers_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_request: ExecutionAuthorizationRequestV1,
    linked_account_bindings: tuple[RazorpayLinkedAccountBindingV1, ...],
    expected_razorpay_account_id: str,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayTransferBatchResultV1:
    """Authorize, require captured evidence, then create once or reconcile with GET only.

    Provider transfer creation and reconciliation do not prove recipient bank settlement,
    fulfillment, irreversibility, or the impossibility of a future refund or reversal.
    """
    plan = authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=trusted_signing_identities,
        request=execution_request,
        decision_time=decision_time,
        ledger=ledger,
    )
    state = derive_razorpay_payment_state_v1(
        certificate=certificate,
        trusted_signing_identities=trusted_signing_identities,
        execution_id=plan.execution_id,
        expected_razorpay_account_id=expected_razorpay_account_id,
        ledger=ledger,
    )
    if (
        state.state is not ClearPaymentStateV1.PAYMENT_CAPTURED
        or state.effective_payment_id is None
    ):
        _fail(RazorpayTransferFailureCode.PAYMENT_NOT_CAPTURED)

    mapping = build_razorpay_route_mapping_v1(
        request=RazorpayRouteMappingRequestV1(
            execution_plan=plan,
            linked_account_bindings=linked_account_bindings,
        ),
        decision_time=decision_time,
    )
    payment_id = state.effective_payment_id
    _request_artifacts(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=payment_id,
    )
    if (
        state.execution_id != plan.execution_id
        or state.certificate_digest_version != plan.certificate_digest_version
        or state.certificate_digest_sha256 != plan.certificate_digest_sha256
        or state.expected_amount != plan.order_amount
        or mapping.execution_id != plan.execution_id
        or mapping.order_amount != plan.order_amount
    ):
        _fail(RazorpayTransferFailureCode.EXECUTION_ARTIFACT_MISMATCH)
    if any(line.transfer_amount.amount_paise < 100 for line in mapping.transfer_lines):
        _fail(RazorpayTransferFailureCode.PROVIDER_TRANSFER_AMOUNT_UNSUPPORTED)

    _credential_pair(credentials)
    request_body = canonical_razorpay_payment_transfer_request_v1_bytes(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=payment_id,
    )
    fingerprint = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=payment_id,
    )
    references = _transfer_references(ledger=ledger, execution_id=plan.execution_id)
    intent = ledger.get_idempotency_record(
        namespace=_INTENT_NAMESPACE,
        idempotency_key=plan.execution_id,
    )
    if intent is not None:
        if (
            intent.request_fingerprint_sha256 != fingerprint
            or intent.execution_id != plan.execution_id
        ):
            _fail(RazorpayTransferFailureCode.TRANSFER_INTENT_CONFLICT)
        return _reconcile(
            plan=plan,
            state_order_id=state.provider_order_id,
            provider_payment_id=payment_id,
            mapping=mapping,
            fingerprint=fingerprint,
            references=references,
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
        )
    if references:
        _fail(RazorpayTransferFailureCode.TRANSFER_INTENT_MISSING)

    _validate_provider_payment(
        plan=plan,
        provider_payment_id=payment_id,
        provider_order_id=state.provider_order_id,
        credentials=credentials,
    )
    for account_id in sorted({line.razorpay_account_id for line in mapping.transfer_lines}):
        _validate_linked_account(account_id=account_id, credentials=credentials)

    transfer_path = f"/v1/payments/{payment_id}/transfers"
    preflight = _transfer_collection(
        method="GET",
        path=transfer_path,
        credentials=credentials,
        body=None,
        transport_failure=RazorpayTransferFailureCode.TRANSFER_PREFLIGHT_CONFLICT,
    )
    try:
        if _collection_items(preflight):
            _fail(RazorpayTransferFailureCode.TRANSFER_PREFLIGHT_CONFLICT)
    except (_InvalidProviderPayload, _ProviderMismatch):
        _fail(RazorpayTransferFailureCode.TRANSFER_PREFLIGHT_CONFLICT)

    claim = ledger.claim_idempotency(
        IdempotencyRecordV1(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
            request_fingerprint_sha256=fingerprint,
            execution_id=plan.execution_id,
            recorded_at=decision_time,
        )
    )
    if claim.disposition is IdempotencyDispositionV1.CONFLICT:
        _fail(RazorpayTransferFailureCode.TRANSFER_INTENT_CONFLICT)
    if claim.disposition is IdempotencyDispositionV1.EXISTING_SAME:
        return _reconcile(
            plan=plan,
            state_order_id=state.provider_order_id,
            provider_payment_id=payment_id,
            mapping=mapping,
            fingerprint=fingerprint,
            references=_transfer_references(ledger=ledger, execution_id=plan.execution_id),
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
        )
    if claim.disposition is not IdempotencyDispositionV1.CREATED:
        raise ValueError("unsupported idempotency disposition")

    payload = _transfer_collection(
        method="POST",
        path=transfer_path,
        credentials=credentials,
        body=request_body,
        transport_failure=RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
    )
    try:
        observations = _validated_transfer_set(
            payload=payload,
            mapping=mapping,
            provider_payment_id=payment_id,
        )
    except (_EmptyProviderTransferSet, _InvalidProviderPayload, _ProviderMismatch):
        _fail(RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED)
    _persist_batch(
        plan=plan,
        mapping=mapping,
        observations=observations,
        fingerprint=fingerprint,
        decision_time=decision_time,
        ledger=ledger,
    )
    return _result(
        disposition=RazorpayTransferBatchDispositionV1.CREATED,
        plan=plan,
        state_order_id=state.provider_order_id,
        provider_payment_id=payment_id,
        mapping=mapping,
        fingerprint=fingerprint,
        observations=observations,
    )
