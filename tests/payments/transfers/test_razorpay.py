import hashlib
import http.client
import inspect
import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import pytest

import clear_market.payments.transfers.razorpay as transfer_module
from clear_market.execution import (
    MoneyGovernorError,
    MoneyGovernorFailureCode,
    authorize_execution_v1,
)
from clear_market.payments.razorpay import (
    RazorpayLinkedAccountBindingStateV1,
    RazorpayLinkedAccountBindingV1,
    RazorpayRouteMappingError,
    RazorpayRouteMappingFailureCode,
    RazorpayRouteMappingRequestV1,
    build_razorpay_route_mapping_v1,
)
from clear_market.payments.transfers import (
    RazorpayTransferBatchDispositionV1,
    RazorpayTransferError,
    RazorpayTransferFailureCode,
    canonical_razorpay_payment_transfer_request_v1_bytes,
    create_or_reconcile_razorpay_test_transfers_v1,
    razorpay_payment_transfer_request_fingerprint_v1,
)
from clear_market.persistence import (
    IdempotencyRecordV1,
    PersistenceError,
    PersistenceErrorCode,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)
from tests.certificate.v2.test_serialization import (
    _catalog,
    _certificate,
    _evidence,
    _inventory,
    _offer,
    _policy,
    _validated_copy,
)
from tests.execution.test_governor import _request_for
from tests.execution.test_models import _TIME
from tests.payments.razorpay.test_orders import _credentials
from tests.payments.razorpay.test_route_models import _binding
from tests.payments.razorpay.test_webhooks import (
    _ACCOUNT_ID,
    _ingest,
)
from tests.payments.razorpay.test_webhooks import (
    _body as _webhook_body,
)
from tests.payments.razorpay.test_webhooks import (
    _signature as _webhook_signature,
)
from tests.verification.v2.test_verifier import _certificate_for as _verified_certificate_for
from tests.verification.v2.test_verifier import _tampered_allocation, _trusted

_ORDER_ID = "order_CLEARReview1"
_PAYMENT_ID = "pay_CLEARReview1"
_INTENT_NAMESPACE = "razorpay.payment.transfers.create.v1"
_TRANSFER_EVENT_TYPE = "razorpay.route.transfer_identity.v1"


@pytest.fixture
def ledger(tmp_path: Path):
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as value:
        yield value


def _bindings() -> tuple[RazorpayLinkedAccountBindingV1, ...]:
    return (_binding(2), _binding(1))


def _prepare(
    ledger: SQLiteFinancialLedgerV1,
    *,
    event_type: str = "payment.captured",
):
    certificate = _certificate()
    request = _request_for(certificate)
    plan = authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=_trusted(),
        request=request,
        decision_time=_TIME,
        ledger=ledger,
    )
    ledger.record_provider_reference(
        ProviderReferenceV1(
            provider_name="razorpay",
            reference_kind="order",
            reference_id=_ORDER_ID,
            execution_id=plan.execution_id,
            recorded_at=_TIME,
        )
    )
    if event_type == "payment.captured":
        _ingest(ledger)
    else:
        body = _webhook_body(event_type=event_type)
        _ingest(ledger, raw_body=body, signature_header=_webhook_signature(body))
    mapping = build_razorpay_route_mapping_v1(
        request=RazorpayRouteMappingRequestV1(
            execution_plan=plan,
            linked_account_bindings=_bindings(),
        ),
        decision_time=_TIME,
    )
    return certificate, request, plan, mapping


def _payment_response(**changes: object) -> bytes:
    value: dict[str, object] = {
        "id": _PAYMENT_ID,
        "entity": "payment",
        "amount": 2_700,
        "currency": "INR",
        "status": "captured",
        "order_id": _ORDER_ID,
        "captured": True,
        "amount_refunded": 0,
        "refund_status": None,
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _account_response(account_id: str, **changes: object) -> bytes:
    value: dict[str, object] = {"id": account_id, "type": "route", "status": "created"}
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _transfer_item(mapping: Any, index: int, **changes: object) -> dict[str, object]:
    line = mapping.transfer_lines[index]
    value: dict[str, object] = {
        "id": f"trf_CLEARReview{index + 1}",
        "entity": "transfer",
        "source": _PAYMENT_ID,
        "recipient": line.razorpay_account_id,
        "amount": line.transfer_amount.amount_paise,
        "currency": "INR",
        "amount_reversed": 0,
        "notes": {
            "clear_execution_id": mapping.execution_id,
            "clear_line_index": str(line.allocation_line_index),
            "clear_route_mapping_sha256": mapping.razorpay_route_mapping_fingerprint_sha256,
        },
        "status": "created",
        "settlement_status": None,
        "created_at": 1_788_262_300 + index,
    }
    value.update(changes)
    return value


def _collection(items: list[object], **changes: object) -> bytes:
    value: dict[str, object] = {
        "entity": "collection",
        "count": len(items),
        "items": items,
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class _Boundary:
    def __init__(
        self,
        mapping: Any,
        *,
        payment: tuple[int, bytes] | BaseException | None = None,
        accounts: dict[str, tuple[int, bytes] | BaseException] | None = None,
        transfers: list[dict[str, object]] | None = None,
        preflight: tuple[int, bytes] | BaseException | None = None,
        post: tuple[int, bytes] | BaseException | None = None,
    ) -> None:
        self.mapping = mapping
        self.payment = payment or (200, _payment_response())
        self.accounts = accounts or {
            line.razorpay_account_id: (200, _account_response(line.razorpay_account_id))
            for line in mapping.transfer_lines
        }
        self.transfers = transfers if transfers is not None else []
        self.preflight = preflight
        self.post = post
        self.calls: list[dict[str, object]] = []
        self._lock = Lock()

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        with self._lock:
            self.calls.append(kwargs)
            method = kwargs["method"]
            path = kwargs["path"]
            if path == f"/v1/payments/{_PAYMENT_ID}":
                outcome = self.payment
            elif isinstance(path, str) and path.startswith("/v2/accounts/"):
                outcome = self.accounts[path.removeprefix("/v2/accounts/")]
            elif path == f"/v1/payments/{_PAYMENT_ID}/transfers" and method == "GET":
                outcome = self.preflight or (200, _collection(self.transfers))
            elif path == f"/v1/payments/{_PAYMENT_ID}/transfers" and method == "POST":
                outcome = self.post or (
                    200,
                    _collection([_transfer_item(self.mapping, 0), _transfer_item(self.mapping, 1)]),
                )
                if not isinstance(outcome, BaseException) and 200 <= outcome[0] < 300:
                    try:
                        payload = json.loads(outcome[1])
                        if type(payload) is dict and type(payload.get("items")) is list:
                            self.transfers = payload["items"]
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
            else:
                raise AssertionError(f"unexpected provider request: {method} {path}")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @property
    def post_count(self) -> int:
        return sum(call["method"] == "POST" for call in self.calls)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(str(call["path"]) for call in self.calls)


def _install(monkeypatch: pytest.MonkeyPatch, boundary: _Boundary) -> None:
    monkeypatch.setattr(transfer_module, "_https_request", boundary)


def _call(
    ledger: SQLiteFinancialLedgerV1,
    *,
    certificate: Any | None = None,
    request: Any | None = None,
    trusted: Any | None = None,
    bindings: Any | None = None,
    decision_time: Any = _TIME,
):
    selected = certificate or _certificate()
    return create_or_reconcile_razorpay_test_transfers_v1(
        certificate=selected,
        trusted_signing_identities=_trusted() if trusted is None else trusted,
        execution_request=request or _request_for(selected),
        linked_account_bindings=_bindings() if bindings is None else bindings,
        expected_razorpay_account_id=_ACCOUNT_ID,
        decision_time=decision_time,
        ledger=ledger,
        credentials=_credentials(),
    )


def _assert_error(code: RazorpayTransferFailureCode, action: Any) -> RazorpayTransferError:
    with pytest.raises(RazorpayTransferError) as caught:
        action()
    assert caught.value.code is code
    assert str(caught.value) == code.value
    for secret in (_PAYMENT_ID, _ORDER_ID, "acc_CLEAR00000001", "2700", "Authorization"):
        assert secret not in str(caught.value)
    return caught.value


def test_public_api_requires_authority_inputs_and_not_preconstructed_artifacts() -> None:
    signature = inspect.signature(create_or_reconcile_razorpay_test_transfers_v1)
    assert tuple(signature.parameters) == (
        "certificate",
        "trusted_signing_identities",
        "execution_request",
        "linked_account_bindings",
        "expected_razorpay_account_id",
        "decision_time",
        "ledger",
        "credentials",
    )
    assert (
        not {"execution_plan", "payment_state", "route_mapping_plan"} & signature.parameters.keys()
    )
    assert tuple(item.value for item in RazorpayTransferFailureCode) == (
        "PAYMENT_NOT_CAPTURED",
        "EXECUTION_ARTIFACT_MISMATCH",
        "PAYMENT_PROVIDER_FETCH_FAILED",
        "PAYMENT_PROVIDER_MISMATCH",
        "LINKED_ACCOUNT_FETCH_FAILED",
        "LINKED_ACCOUNT_MISMATCH",
        "LINKED_ACCOUNT_NOT_ACTIVE",
        "PROVIDER_TRANSFER_AMOUNT_UNSUPPORTED",
        "TRANSFER_REQUEST_TOO_LARGE",
        "TRANSFER_INTENT_MISSING",
        "TRANSFER_INTENT_CONFLICT",
        "TRANSFER_PREFLIGHT_CONFLICT",
        "TRANSFER_CREATION_RECOVERY_REQUIRED",
        "PROVIDER_TRANSFER_SET_CONFLICT",
        "TRANSFER_REFERENCE_CONFLICT",
        "LOCAL_TRANSFER_REFERENCE_CONFLICT",
        "TRANSFER_LEDGER_CONFLICT",
    )


def test_request_bytes_and_fingerprint_are_exact_deterministic_and_authority_free(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    data = canonical_razorpay_payment_transfer_request_v1_bytes(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    assert data == (
        b'{"transfers":[{"account":"acc_CLEAR00000001","amount":1500,"currency":"INR",'
        b'"notes":{"clear_execution_id":"e1000000-0000-4000-8000-000000000001",'
        b'"clear_line_index":"0","clear_route_mapping_sha256":"'
        + mapping.razorpay_route_mapping_fingerprint_sha256.encode()
        + b'"},"on_hold":false},{"account":"acc_CLEAR00000002","amount":1200,'
        b'"currency":"INR","notes":{"clear_execution_id":'
        b'"e1000000-0000-4000-8000-000000000001","clear_line_index":"1",'
        b'"clear_route_mapping_sha256":"'
        + mapping.razorpay_route_mapping_fingerprint_sha256.encode()
        + b'"},"on_hold":false}]}'
    )
    assert len(data) < 262_144
    assert len(data) == 551
    assert hashlib.sha256(data).hexdigest() == (
        "ba4a3860cbc91bb14998a112800e681850e900d9b2716e77d9f19e1b556935b9"
    )
    assert data == canonical_razorpay_payment_transfer_request_v1_bytes(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    fingerprint = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    assert len(fingerprint) == 64
    assert fingerprint == "c066c28b1fbee85d4cb5b59beb357f11b21fe5c8a66798d8d4360a9ca95e4d71"
    assert fingerprint == razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    assert "review-secret-never-print" not in data.decode()
    assert "decision_time" not in data.decode()


def test_successful_creation_has_exact_http_order_and_durable_identity_facts(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    result = _call(ledger)
    assert result.disposition is RazorpayTransferBatchDispositionV1.CREATED
    assert result.execution_id == plan.execution_id
    assert tuple(item.amount.amount_paise for item in result.transfers) == (1_500, 1_200)
    assert tuple(item.razorpay_account_id for item in result.transfers) == (
        "acc_CLEAR00000001",
        "acc_CLEAR00000002",
    )
    assert boundary.paths == (
        f"/v1/payments/{_PAYMENT_ID}",
        "/v2/accounts/acc_CLEAR00000001",
        "/v2/accounts/acc_CLEAR00000002",
        f"/v1/payments/{_PAYMENT_ID}/transfers",
        f"/v1/payments/{_PAYMENT_ID}/transfers",
    )
    assert boundary.post_count == 1
    intent = ledger.get_idempotency_record(
        namespace=_INTENT_NAMESPACE,
        idempotency_key=plan.execution_id,
    )
    assert intent is not None
    assert intent.request_fingerprint_sha256 == result.transfer_request_fingerprint_sha256
    references = ledger.list_provider_references(plan.execution_id, limit=100)
    assert tuple(
        reference.reference_id
        for reference in references
        if reference.provider_name == "razorpay" and reference.reference_kind == "transfer"
    ) == ("trf_CLEARReview1", "trf_CLEARReview2")
    events = ledger.list_events(plan.execution_id, limit=100)
    identity_events = tuple(
        item.event for item in events if item.event.event_type == _TRANSFER_EVENT_TYPE
    )
    assert len(identity_events) == 2
    for event in identity_events:
        keys = tuple(field.field_key for field in event.fields)
        assert keys == (
            "allocation_line_index",
            "amount_paise",
            "currency",
            "provider_payment_id",
            "provider_transfer_id",
            "razorpay_account_id",
            "route_mapping_fingerprint_sha256",
            "transfer_request_fingerprint_sha256",
        )
        assert not {"transfer_status", "settlement_status", "amount_reversed"} & set(keys)


def test_second_call_uses_get_reconciliation_and_returns_existing(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, _plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    first = _call(ledger)
    second = _call(ledger)
    assert first.disposition is RazorpayTransferBatchDispositionV1.CREATED
    assert second.disposition is RazorpayTransferBatchDispositionV1.EXISTING
    assert boundary.post_count == 1
    assert boundary.paths[-1] == f"/v1/payments/{_PAYMENT_ID}/transfers"


@pytest.mark.parametrize("outcome", (TimeoutError(), ssl.SSLError(), (500, b"{}"), (200, b"{")))
def test_uncertain_post_keeps_intent_and_future_call_never_posts_blindly(
    outcome: tuple[int, bytes] | BaseException,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, post=outcome)
    _install(monkeypatch, boundary)
    _assert_error(
        RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
        lambda: _call(ledger),
    )
    assert boundary.post_count == 1
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is not None
    )
    _assert_error(
        RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
        lambda: _call(ledger),
    )
    assert boundary.post_count == 1


def test_uncertain_post_is_recovered_by_exact_get_without_second_post(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, _plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, post=TimeoutError())
    _install(monkeypatch, boundary)
    _assert_error(
        RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
        lambda: _call(ledger),
    )
    boundary.transfers = [_transfer_item(mapping, 0), _transfer_item(mapping, 1)]
    result = _call(ledger)
    assert result.disposition is RazorpayTransferBatchDispositionV1.RECOVERED
    assert boundary.post_count == 1


def test_new_attempt_preflight_get_requires_exact_http_200(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, preflight=(201, _collection([])))
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.TRANSFER_PREFLIGHT_CONFLICT, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


@pytest.mark.parametrize(
    ("status", "body"),
    (
        (201, "exact_collection"),
        (204, "empty_body"),
    ),
)
def test_existing_intent_recovery_get_requires_exact_http_200(
    status: int,
    body: str,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    fingerprint = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    intent = IdempotencyRecordV1(
        namespace=_INTENT_NAMESPACE,
        idempotency_key=plan.execution_id,
        request_fingerprint_sha256=fingerprint,
        execution_id=plan.execution_id,
        recorded_at=_TIME,
    )
    ledger.claim_idempotency(intent)
    response = (
        _collection([_transfer_item(mapping, 0), _transfer_item(mapping, 1)])
        if body == "exact_collection"
        else b""
    )
    boundary = _Boundary(mapping, preflight=(status, response))
    _install(monkeypatch, boundary)
    _assert_error(
        RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
        lambda: _call(ledger),
    )
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        == intent
    )


def test_post_http_201_with_exact_transfer_collection_is_created(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, _plan, mapping = _prepare(ledger)
    boundary = _Boundary(
        mapping,
        post=(
            201,
            _collection([_transfer_item(mapping, 0), _transfer_item(mapping, 1)]),
        ),
    )
    _install(monkeypatch, boundary)
    result = _call(ledger)
    assert result.disposition is RazorpayTransferBatchDispositionV1.CREATED
    assert boundary.post_count == 1


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({"status": "authorized"}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"captured": False}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"amount": 2_699}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"currency": "USD"}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"order_id": "order_other"}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"amount_refunded": 1}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"refund_status": "partial"}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_MISMATCH),
        ({"amount": True}, RazorpayTransferFailureCode.PAYMENT_PROVIDER_FETCH_FAILED),
    ),
)
def test_current_payment_contradictions_block_intent_and_post(
    changes: dict[str, object],
    expected: RazorpayTransferFailureCode,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, payment=(200, _payment_response(**changes)))
    _install(monkeypatch, boundary)
    _assert_error(expected, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({"status": "suspended"}, RazorpayTransferFailureCode.LINKED_ACCOUNT_NOT_ACTIVE),
        ({"id": "acc_CLEAROTHER001"}, RazorpayTransferFailureCode.LINKED_ACCOUNT_MISMATCH),
        ({"type": "merchant"}, RazorpayTransferFailureCode.LINKED_ACCOUNT_MISMATCH),
    ),
)
def test_linked_account_contradictions_block_intent_and_post(
    changes: dict[str, object],
    expected: RazorpayTransferFailureCode,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    first = mapping.transfer_lines[0].razorpay_account_id
    boundary = _Boundary(
        mapping,
        accounts={
            first: (200, _account_response(first, **changes)),
            mapping.transfer_lines[1].razorpay_account_id: (
                200,
                _account_response(mapping.transfer_lines[1].razorpay_account_id),
            ),
        },
    )
    _install(monkeypatch, boundary)
    _assert_error(expected, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


def test_provider_minimum_is_fail_closed_without_aggregating_lines(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy()
    catalog1 = _catalog(1)
    inventory1 = _inventory(1)
    offer1 = _offer(
        1,
        policy=policy,
        catalog=catalog1,
        inventory=inventory1,
        price=30,
    )
    evidence1 = _evidence(
        1,
        policy=policy,
        catalog=catalog1,
        inventory=inventory1,
        offer=offer1,
    )
    catalog2 = _catalog(2)
    inventory2 = _inventory(2)
    offer2 = _offer(
        2,
        policy=policy,
        catalog=catalog2,
        inventory=inventory2,
    )
    evidence2 = _evidence(
        2,
        policy=policy,
        catalog=catalog2,
        inventory=inventory2,
        offer=offer2,
    )
    certificate = _verified_certificate_for(
        policy=policy,
        evidence=(evidence1, evidence2),
        admitted_offers=(evidence1.signed_offer, evidence2.signed_offer),
    )
    request = _request_for(certificate)
    plan = authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=_trusted(),
        request=request,
        decision_time=_TIME,
        ledger=ledger,
    )
    assert tuple(line.transfer_amount.amount_paise for line in plan.transfer_lines) == (90, 1_200)
    ledger.record_provider_reference(
        ProviderReferenceV1(
            provider_name="razorpay",
            reference_kind="order",
            reference_id=_ORDER_ID,
            execution_id=plan.execution_id,
            recorded_at=_TIME,
        )
    )
    body = _webhook_body(amount=1_290)
    _ingest(ledger, raw_body=body, signature_header=_webhook_signature(body))
    mapping = build_razorpay_route_mapping_v1(
        request=RazorpayRouteMappingRequestV1(
            execution_plan=plan,
            linked_account_bindings=_bindings(),
        ),
        decision_time=_TIME,
    )
    boundary = _Boundary(mapping, payment=(200, _payment_response(amount=1_290)))
    _install(monkeypatch, boundary)
    _assert_error(
        RazorpayTransferFailureCode.PROVIDER_TRANSFER_AMOUNT_UNSUPPORTED,
        lambda: _call(ledger, certificate=certificate, request=request),
    )
    assert not boundary.calls
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


def test_existing_provider_transfer_before_clear_intent_fails_preflight(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, transfers=[_transfer_item(mapping, 0)])
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.TRANSFER_PREFLIGHT_CONFLICT, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


@pytest.mark.parametrize(
    "preflight",
    (
        (200, _collection([], count=1)),
        (200, _collection([{}], count=0)),
        (200, _collection([], entity="items")),
        (200, _collection([], count=True)),
    ),
)
def test_inconsistent_or_malformed_preflight_never_creates_intent_or_posts(
    preflight: tuple[int, bytes],
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, preflight=preflight)
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.TRANSFER_PREFLIGHT_CONFLICT, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


def test_authenticated_authorized_payment_is_not_transfer_authority(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(
        ledger,
        event_type="payment.authorized",
    )
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.PAYMENT_NOT_CAPTURED, lambda: _call(ledger))
    assert not boundary.calls
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


@pytest.mark.parametrize(
    "response",
    (
        (500, b"{}"),
        (200, b"{"),
        (200, b'{"id":"pay_CLEARReview1","id":"pay_CLEARReview1"}'),
        (200, b'{"id":NaN}'),
        (200, b"\x00{}"),
        (200, b"[1]"),
    ),
)
def test_malformed_payment_fetch_fails_without_intent_or_post(
    response: tuple[int, bytes],
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping, payment=response)
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.PAYMENT_PROVIDER_FETCH_FAILED, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


@pytest.mark.parametrize(
    "outcome",
    (
        TimeoutError(),
        ssl.SSLError(),
        (404, b"{}"),
        (200, b"{"),
        (200, b'{"id":"acc_CLEAR00000001","id":"acc_CLEAR00000001"}'),
    ),
)
def test_linked_account_fetch_failures_are_sanitized_and_block_post(
    outcome: tuple[int, bytes] | BaseException,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    first = mapping.transfer_lines[0].razorpay_account_id
    second = mapping.transfer_lines[1].razorpay_account_id
    boundary = _Boundary(
        mapping,
        accounts={
            first: outcome,
            second: (200, _account_response(second)),
        },
    )
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.LINKED_ACCOUNT_FETCH_FAILED, lambda: _call(ledger))
    assert boundary.post_count == 0
    assert (
        ledger.get_idempotency_record(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
        )
        is None
    )


@pytest.mark.parametrize(
    "mutator",
    (
        lambda item: item.update(amount=1),
        lambda item: item.update(recipient="acc_CLEAROTHER001"),
        lambda item: item.update(source="pay_other"),
        lambda item: item.update(currency="USD"),
        lambda item: item["notes"].update(clear_line_index="1"),
    ),
)
def test_uncertain_post_batch_mismatch_is_recovery_required(
    mutator: Any,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, _plan, mapping = _prepare(ledger)
    items = [_transfer_item(mapping, 0), _transfer_item(mapping, 1)]
    mutator(items[0])
    boundary = _Boundary(mapping, post=(200, _collection(items)))
    _install(monkeypatch, boundary)
    _assert_error(
        RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED,
        lambda: _call(ledger),
    )
    assert boundary.post_count == 1


def test_existing_intent_partial_or_extra_provider_set_fails_closed(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    fingerprint = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    ledger.claim_idempotency(
        IdempotencyRecordV1(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
            request_fingerprint_sha256=fingerprint,
            execution_id=plan.execution_id,
            recorded_at=_TIME,
        )
    )
    boundary = _Boundary(mapping, transfers=[_transfer_item(mapping, 0)])
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.PROVIDER_TRANSFER_SET_CONFLICT, lambda: _call(ledger))
    assert boundary.post_count == 0


def test_local_transfer_reference_without_intent_is_not_authority(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    ledger.record_provider_reference(
        ProviderReferenceV1(
            provider_name="razorpay",
            reference_kind="transfer",
            reference_id="trf_Injected",
            execution_id=plan.execution_id,
            recorded_at=_TIME,
        )
    )
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    _assert_error(RazorpayTransferFailureCode.TRANSFER_INTENT_MISSING, lambda: _call(ledger))
    assert not boundary.calls


def test_governor_failure_is_first_and_performs_no_provider_call(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate, _request, _plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    bad = _validated_copy(certificate, allocation=_tampered_allocation("payment"))
    with pytest.raises(MoneyGovernorError) as caught:
        _call(ledger, certificate=bad, request=_request_for(bad))
    assert caught.value.code is MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
    assert not boundary.calls


def test_expired_authorization_is_rejected_before_provider_call(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate, _request, _plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    request = _request_for(certificate)
    with pytest.raises(MoneyGovernorError):
        _call(ledger, request=request, decision_time=_TIME + timedelta(days=1))
    assert not boundary.calls


def test_invalid_route_binding_fails_before_provider_call(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, _plan, mapping = _prepare(ledger)
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    paused = _binding(1, state=RazorpayLinkedAccountBindingStateV1.PAUSED)
    with pytest.raises(RazorpayRouteMappingError) as caught:
        _call(ledger, bindings=(paused, _binding(2)))
    assert caught.value.code is RazorpayRouteMappingFailureCode.BINDING_NOT_EXECUTABLE
    assert not boundary.calls


def test_existing_intent_reconciliation_accepts_status_aliases_and_provider_facts(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    fingerprint = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    ledger.claim_idempotency(
        IdempotencyRecordV1(
            namespace=_INTENT_NAMESPACE,
            idempotency_key=plan.execution_id,
            request_fingerprint_sha256=fingerprint,
            execution_id=plan.execution_id,
            recorded_at=_TIME,
        )
    )
    first = _transfer_item(
        mapping,
        0,
        status="processed",
        transfer_status="processed",
        settlement_status="settled",
    )
    second = _transfer_item(mapping, 1, status="reversed", settlement_status="on_hold")
    boundary = _Boundary(mapping, transfers=[second, first])
    _install(monkeypatch, boundary)
    result = _call(ledger)
    assert result.disposition is RazorpayTransferBatchDispositionV1.RECOVERED
    assert tuple(item.transfer_status.value for item in result.transfers) == (
        "processed",
        "reversed",
    )
    assert tuple(item.settlement_status.value for item in result.transfers) == (
        "settled",
        "on_hold",
    )


def test_same_account_same_amount_lines_reconcile_by_line_index(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _certificate_value, _request, _plan, mapping = _prepare(ledger)
    first, second = mapping.transfer_lines
    second_values = {name: second.__dict__[name] for name in type(second).model_fields}
    second_values.update(
        merchant_id=first.merchant_id,
        recipient_authorization_id=first.recipient_authorization_id,
        recipient_id=first.recipient_id,
        linked_account_binding_id=first.linked_account_binding_id,
        razorpay_account_id=first.razorpay_account_id,
        transfer_amount=first.transfer_amount,
    )
    second = type(second).model_validate(second_values)
    mapping_values = {name: mapping.__dict__[name] for name in type(mapping).model_fields}
    mapping_values.update(
        order_amount=type(mapping.order_amount)(amount_paise=3_000),
        transfer_lines=(first, second),
    )
    same_account_mapping = type(mapping).model_validate(mapping_values)
    payload = transfer_module._provider_object(
        _collection(
            [
                _transfer_item(same_account_mapping, 1),
                _transfer_item(same_account_mapping, 0),
            ]
        )
    )
    observations = transfer_module._validated_transfer_set(
        payload=payload,
        mapping=same_account_mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    assert tuple(item.allocation_line_index for item in observations) == (0, 1)
    assert tuple(item.razorpay_account_id for item in observations) == (
        first.razorpay_account_id,
        first.razorpay_account_id,
    )
    assert tuple(item.amount.amount_paise for item in observations) == (1_500, 1_500)


def test_request_fingerprint_is_bound_to_payment_mapping_and_execution(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    original = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    assert original != razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id="pay_CLEARReview2",
    )
    assert (
        original
        != hashlib.sha256(
            canonical_razorpay_payment_transfer_request_v1_bytes(
                execution_plan=plan,
                route_mapping_plan=mapping,
                provider_payment_id=_PAYMENT_ID,
            )
        ).hexdigest()
    )


@pytest.mark.parametrize(
    ("crash_point", "expected_reference_count", "expected_event_count"),
    (
        ("first_reference", 0, 0),
        ("second_reference", 1, 1),
        ("first_identity_event", 1, 0),
        ("second_identity_event", 2, 1),
    ),
)
def test_post_success_persistence_crash_matrix_recovers_without_second_post(
    crash_point: str,
    expected_reference_count: int,
    expected_event_count: int,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _certificate_value, _request, plan, mapping = _prepare(ledger)
    expected_fingerprint = razorpay_payment_transfer_request_fingerprint_v1(
        execution_plan=plan,
        route_mapping_plan=mapping,
        provider_payment_id=_PAYMENT_ID,
    )
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)
    original_record_reference = SQLiteFinancialLedgerV1.record_provider_reference
    original_append_event = SQLiteFinancialLedgerV1.append_event
    reference_write_count = 0
    identity_event_write_count = 0

    def fail_selected_reference_write(
        self: SQLiteFinancialLedgerV1,
        reference: ProviderReferenceV1,
    ):
        nonlocal reference_write_count
        if reference.provider_name == "razorpay" and reference.reference_kind == "transfer":
            reference_write_count += 1
            if (crash_point, reference_write_count) in {
                ("first_reference", 1),
                ("second_reference", 2),
            }:
                raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED)
        return original_record_reference(self, reference)

    def fail_selected_identity_event_write(
        self: SQLiteFinancialLedgerV1,
        event: Any,
    ):
        nonlocal identity_event_write_count
        if event.event_type == _TRANSFER_EVENT_TYPE:
            identity_event_write_count += 1
            if (crash_point, identity_event_write_count) in {
                ("first_identity_event", 1),
                ("second_identity_event", 2),
            }:
                raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED)
        return original_append_event(self, event)

    monkeypatch.setattr(
        SQLiteFinancialLedgerV1,
        "record_provider_reference",
        fail_selected_reference_write,
    )
    monkeypatch.setattr(
        SQLiteFinancialLedgerV1,
        "append_event",
        fail_selected_identity_event_write,
    )
    with pytest.raises(PersistenceError) as caught:
        _call(ledger)
    assert caught.value.code is PersistenceErrorCode.DATABASE_OPERATION_FAILED
    assert boundary.post_count == 1
    intent = ledger.get_idempotency_record(
        namespace=_INTENT_NAMESPACE,
        idempotency_key=plan.execution_id,
    )
    assert intent is not None
    assert intent.request_fingerprint_sha256 == expected_fingerprint

    references = tuple(
        reference
        for reference in ledger.list_provider_references(plan.execution_id, limit=100)
        if reference.provider_name == "razorpay" and reference.reference_kind == "transfer"
    )
    identity_events = tuple(
        persisted.event
        for persisted in ledger.list_events(plan.execution_id, limit=100)
        if persisted.event.event_type == _TRANSFER_EVENT_TYPE
    )
    assert len(references) == expected_reference_count
    assert len(identity_events) == expected_event_count
    assert len({reference.reference_id for reference in references}) == len(references)
    assert len({event.event_id for event in identity_events}) == len(identity_events)

    monkeypatch.setattr(
        SQLiteFinancialLedgerV1,
        "record_provider_reference",
        original_record_reference,
    )
    monkeypatch.setattr(SQLiteFinancialLedgerV1, "append_event", original_append_event)
    retry_call_index = len(boundary.calls)
    recovered = _call(ledger)
    assert recovered.disposition is RazorpayTransferBatchDispositionV1.RECOVERED
    assert recovered.transfer_request_fingerprint_sha256 == expected_fingerprint
    assert boundary.post_count == 1
    assert tuple((call["method"], call["path"]) for call in boundary.calls[retry_call_index:]) == (
        ("GET", f"/v1/payments/{_PAYMENT_ID}/transfers"),
    )

    final_references = tuple(
        reference
        for reference in ledger.list_provider_references(plan.execution_id, limit=100)
        if reference.provider_name == "razorpay" and reference.reference_kind == "transfer"
    )
    assert tuple(reference.reference_id for reference in final_references) == (
        "trf_CLEARReview1",
        "trf_CLEARReview2",
    )
    assert len({reference.reference_id for reference in final_references}) == 2

    final_identity_events = tuple(
        persisted.event
        for persisted in ledger.list_events(plan.execution_id, limit=100)
        if persisted.event.event_type == _TRANSFER_EVENT_TYPE
    )
    assert len(final_identity_events) == 2
    assert len({event.event_id for event in final_identity_events}) == 2
    for observation in recovered.transfers:
        expected_event = transfer_module._identity_event(
            plan=plan,
            mapping=mapping,
            observation=observation,
            fingerprint=expected_fingerprint,
        )
        stored_event = ledger.get_event(expected_event.event_id)
        assert stored_event is not None
        assert stored_event.event == expected_event


def test_concurrent_calls_across_connections_perform_at_most_one_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "concurrent-ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as setup:
        _certificate_value, _request, _plan, mapping = _prepare(setup)
    boundary = _Boundary(mapping)
    _install(monkeypatch, boundary)

    def invoke() -> object:
        with open_sqlite_financial_ledger_v1(str(path)) as connection:
            try:
                return _call(connection)
            except RazorpayTransferError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _index: invoke(), range(2)))
    assert boundary.post_count <= 1
    assert any(
        getattr(value, "disposition", None)
        in {
            RazorpayTransferBatchDispositionV1.CREATED,
            RazorpayTransferBatchDispositionV1.RECOVERED,
            RazorpayTransferBatchDispositionV1.EXISTING,
        }
        for value in outcomes
    )
    assert all(
        not isinstance(value, RazorpayTransferFailureCode)
        or value is RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
        for value in outcomes
    )
    with open_sqlite_financial_ledger_v1(str(path)) as check:
        refs = check.list_provider_references(mapping.execution_id, limit=100)
        transfer_ids = tuple(
            reference.reference_id
            for reference in refs
            if reference.provider_name == "razorpay" and reference.reference_kind == "transfer"
        )
        assert transfer_ids == ("trf_CLEARReview1", "trf_CLEARReview2")


def test_https_boundary_uses_exact_host_tls_timeout_basic_auth_and_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = object()
    observed: dict[str, object] = {}

    class Response:
        status = 200

        def read(self, amount: int) -> bytes:
            observed["read"] = amount
            return b"{}"

    class Connection:
        def __init__(
            self,
            host: str,
            port: int,
            *,
            timeout: int,
            context: object,
        ) -> None:
            observed.update(host=host, port=port, timeout=timeout, context=context)

        def request(
            self,
            method: str,
            path: str,
            *,
            body: bytes | None,
            headers: dict[str, str],
        ) -> None:
            observed.update(method=method, path=path, body=body, headers=headers)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    status, body = transfer_module._https_request(
        method="POST",
        path=f"/v1/payments/{_PAYMENT_ID}/transfers",
        credentials=_credentials(),
        body=b"{}",
    )
    assert (status, body) == (200, b"{}")
    assert observed["host"] == "api.razorpay.com"
    assert observed["port"] == 443
    assert observed["timeout"] == 10
    assert observed["context"] is context
    assert observed["read"] == 262_145
    assert observed["closed"] is True
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"].startswith("Basic ")
    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
