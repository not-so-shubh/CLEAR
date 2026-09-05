import base64
import hashlib
import hmac
import inspect
import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import pytest

import clear_market.payments.razorpay as razorpay
import clear_market.payments.razorpay.orders as orders_module
from clear_market.certificate.v2 import allocation_certificate_v2_digest
from clear_market.execution import (
    ExecutionPlanV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
    authorize_execution_v1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    RazorpayOrderStatusV1,
    RazorpayOrderTransportV1,
    RazorpayTestCredentialsV1,
    canonical_razorpay_order_create_intent_v1_bytes,
    create_razorpay_test_order_v1,
    razorpay_order_create_fingerprint_v1,
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
    _certificate,
    _identity,
    _validated_copy,
)
from tests.execution.test_governor import _request_for
from tests.execution.test_models import _TIME, _VALID_FROM
from tests.verification.v2.test_verifier import _tampered_allocation, _trusted

_KEY_ID = "rzp_test_review_key"
_KEY_SECRET = "review-secret-never-print"
_ORDER_ID = "order_CLEARReview1"
_IDEMPOTENCY_NAMESPACE = "razorpay.order.create.v1"
_ABSENT = object()


def _credentials() -> RazorpayTestCredentialsV1:
    return RazorpayTestCredentialsV1(key_id=_KEY_ID, key_secret=_KEY_SECRET)


def _response(
    *,
    provider_order_id: str = _ORDER_ID,
    amount: object = 2_700,
    amount_paid: object = 0,
    amount_due: object = 2_700,
    currency: object = "INR",
    receipt: object = "e1000000-0000-4000-8000-000000000001",
    entity: object = "order",
    status: object = "created",
    attempts: object = 0,
    partial_payment: object = False,
    offer_id: object = None,
    extra: object | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "id": provider_order_id,
        "entity": entity,
        "amount": amount,
        "amount_paid": amount_paid,
        "amount_due": amount_due,
        "currency": currency,
        "receipt": receipt,
        "status": status,
        "attempts": attempts,
    }
    if partial_payment is not _ABSENT:
        payload["partial_payment"] = partial_payment
    if offer_id is not _ABSENT:
        payload["offer_id"] = offer_id
    if extra is not None:
        payload["extra"] = extra
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class _Boundary:
    def __init__(self, outcome: tuple[int, bytes] | BaseException) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []
        self._lock = Lock()

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        with self._lock:
            self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    @property
    def post_count(self) -> int:
        return sum(call["method"] == "POST" for call in self.calls)

    @property
    def get_count(self) -> int:
        return sum(call["method"] == "GET" for call in self.calls)


def _install_boundary(
    monkeypatch: pytest.MonkeyPatch,
    outcome: tuple[int, bytes] | BaseException,
) -> _Boundary:
    boundary = _Boundary(outcome)
    monkeypatch.setattr(orders_module, "_https_request", boundary)
    return boundary


def _call(
    ledger: SQLiteFinancialLedgerV1,
    *,
    certificate: Any | None = None,
    trusted: Any | None = None,
    request: Any | None = None,
    decision_time: Any = _TIME,
    transport: RazorpayOrderTransportV1 | None = None,
) -> Any:
    selected_certificate = certificate or _certificate()
    return create_razorpay_test_order_v1(
        certificate=selected_certificate,
        trusted_signing_identities=_trusted() if trusted is None else trusted,
        execution_request=request or _request_for(selected_certificate),
        decision_time=decision_time,
        ledger=ledger,
        credentials=_credentials(),
        transport=transport,
    )


def _authorized_plan(ledger: SQLiteFinancialLedgerV1) -> ExecutionPlanV1:
    certificate = _certificate()
    return authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=_trusted(),
        request=_request_for(certificate),
        decision_time=_TIME,
        ledger=ledger,
    )


def _record_reference(
    ledger: SQLiteFinancialLedgerV1,
    provider_order_id: str = _ORDER_ID,
) -> ProviderReferenceV1:
    plan = _authorized_plan(ledger)
    reference = ProviderReferenceV1(
        provider_name="razorpay",
        reference_kind="order",
        reference_id=provider_order_id,
        execution_id=plan.execution_id,
        recorded_at=_TIME,
    )
    ledger.record_provider_reference(reference)
    return reference


def _record_filler_references(
    ledger: SQLiteFinancialLedgerV1,
    *,
    count: int = 1_000,
) -> ExecutionPlanV1:
    plan = _authorized_plan(ledger)
    for index in range(count):
        ledger.record_provider_reference(
            ProviderReferenceV1(
                provider_name="a-filler",
                reference_kind="reference",
                reference_id=f"filler-{index:04d}",
                execution_id=plan.execution_id,
                recorded_at=_TIME,
            )
        )
    return plan


def _assert_order_error(
    expected: RazorpayOrderFailureCode,
    action: Any,
) -> RazorpayOrderError:
    with pytest.raises(RazorpayOrderError) as caught:
        action()
    assert caught.value.code is expected
    assert str(caught.value) == expected.value
    assert _KEY_SECRET not in str(caught.value)
    return caught.value


def test_create_intent_is_exact_deterministic_and_excludes_non_action_fields() -> None:
    from tests.execution.test_models import _plan

    plan = _plan()
    data = canonical_razorpay_order_create_intent_v1_bytes(plan)
    expected = {
        "canonicalization_version": "clear-json-v1",
        "payload_type": "razorpay_order_create_intent_v1",
        "payload": {
            "schema_version": "1",
            "razorpay_order_create_intent_version": "razorpay-order-create-intent-v1",
            "execution_id": plan.execution_id,
            "certificate_digest_version": plan.certificate_digest_version,
            "certificate_digest_sha256": plan.certificate_digest_sha256,
            "execution_request_fingerprint_version": (plan.execution_request_fingerprint_version),
            "execution_request_fingerprint_sha256": (plan.execution_request_fingerprint_sha256),
            "amount_paise": 2_700,
            "currency": "INR",
            "receipt": plan.execution_id,
        },
    }
    assert data == json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert data == canonical_razorpay_order_create_intent_v1_bytes(plan)
    assert razorpay_order_create_fingerprint_v1(plan) == (
        razorpay_order_create_fingerprint_v1(plan)
    )
    assert all(
        token not in data
        for token in (
            b"decision_time",
            b"credentials",
            b"recipient_id",
            b"transfer_lines",
            b"provider_order_id",
        )
    )


def test_successful_governor_plan_create_intent_candidate_length_and_hash(
    tmp_path: Path,
) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        plan = _authorized_plan(ledger)
    data = canonical_razorpay_order_create_intent_v1_bytes(plan)
    assert len(data) == 702
    assert hashlib.sha256(data).hexdigest() == (
        "9a5897d3c79273ee2e5a331f3a36bb65093f41f7ed9b1c6e5d898af555ebd45c"
    )


def test_create_intent_requires_fresh_exact_plan() -> None:
    from tests.execution.test_models import _plan

    class _PlanSubclass(ExecutionPlanV1):
        pass

    with pytest.raises(TypeError):
        canonical_razorpay_order_create_intent_v1_bytes(
            _PlanSubclass.model_construct(**_plan().__dict__)
        )
    with pytest.raises(ValueError):
        canonical_razorpay_order_create_intent_v1_bytes(ExecutionPlanV1.model_construct())


def test_public_network_surface_requires_governor_inputs_and_has_no_naked_plan_api() -> None:
    signature = inspect.signature(create_razorpay_test_order_v1)
    assert tuple(signature.parameters) == (
        "certificate",
        "trusted_signing_identities",
        "execution_request",
        "decision_time",
        "ledger",
        "credentials",
        "transport",
    )
    assert "plan" not in signature.parameters
    assert signature.parameters["transport"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["transport"].default is None
    network_names = tuple(name for name in razorpay.__all__ if name.startswith("create_"))
    assert network_names == ("create_razorpay_test_order_v1",)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("empty_trust", MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ("altered_key", MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ("false_allocation", MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ("expired_buyer", MoneyGovernorFailureCode.BUYER_AUTHORIZATION_NOT_ACTIVE),
    ],
)
def test_governor_failures_propagate_before_http_or_payment_intent(
    kind: str,
    expected: MoneyGovernorFailureCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = _certificate()
    trusted = _trusted()
    if kind == "empty_trust":
        trusted = ()
    elif kind == "altered_key":
        trusted = (
            _identity(1, public_key_hex=_identity(2).ed25519_public_key_hex),
            _identity(2),
        )
    elif kind == "false_allocation":
        certificate = _validated_copy(
            certificate,
            allocation=_tampered_allocation("soft_score"),
        )
    request = _request_for(
        certificate,
        **(
            {"buyer_valid_until": _TIME - timedelta(microseconds=1)}
            if kind == "expired_buyer"
            else {}
        ),
    )
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(MoneyGovernorError) as caught:
            _call(
                ledger,
                certificate=certificate,
                trusted=trusted,
                request=request,
            )
        assert caught.value.code is expected
        assert boundary.calls == []
        assert (
            ledger.get_idempotency_record(
                namespace=_IDEMPOTENCY_NAMESPACE,
                idempotency_key=request.execution_id,
            )
            is None
        )
        assert ledger.get_execution_reservation(request.execution_id) is None


def test_successful_create_has_exact_request_result_and_durable_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response(extra={"future": True})))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        result = _call(ledger)
        references = ledger.list_provider_references(result.order.execution_id, limit=1_000)
        claim = ledger.get_idempotency_record(
            namespace=_IDEMPOTENCY_NAMESPACE,
            idempotency_key=result.order.execution_id,
        )

    assert result.resolution is RazorpayOrderResolutionV1.CREATED
    assert result.order.amount.amount_paise == 2_700
    assert result.order.status is RazorpayOrderStatusV1.CREATED
    assert boundary.post_count == 1
    assert boundary.get_count == 0
    call = boundary.calls[0]
    assert call["path"] == "/v1/orders"
    assert call["body"] == (
        b'{"amount":2700,"currency":"INR","partial_payment":false,'
        b'"receipt":"e1000000-0000-4000-8000-000000000001"}'
    )
    assert b"transfers" not in call["body"]
    assert b"notes" not in call["body"]
    assert references == (
        ProviderReferenceV1(
            provider_name="razorpay",
            reference_kind="order",
            reference_id=_ORDER_ID,
            execution_id=result.order.execution_id,
            recorded_at=_TIME,
        ),
    )
    assert claim is not None
    assert claim == IdempotencyRecordV1(
        namespace=_IDEMPOTENCY_NAMESPACE,
        idempotency_key=result.order.execution_id,
        request_fingerprint_sha256=claim.request_fingerprint_sha256,
        execution_id=result.order.execution_id,
        recorded_at=_TIME,
    )


def test_injected_transport_controls_creation_and_existing_order_rerun(
    tmp_path: Path,
) -> None:
    transport = _Boundary((200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        created = _call(ledger, transport=transport)
        existing = _call(ledger, transport=transport)

    assert created.resolution is RazorpayOrderResolutionV1.CREATED
    assert existing.resolution is RazorpayOrderResolutionV1.EXISTING
    assert transport.post_count == 1
    assert transport.get_count == 1
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["path"] == "/v1/orders"
    assert transport.calls[0]["body"] == (
        b'{"amount":2700,"currency":"INR","partial_payment":false,'
        b'"receipt":"e1000000-0000-4000-8000-000000000001"}'
    )
    assert transport.calls[1]["method"] == "GET"
    assert transport.calls[1]["path"] == f"/v1/orders/{_ORDER_ID}"
    assert transport.calls[1]["body"] is None


def test_injected_transport_never_falls_back_to_private_https(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(**_kwargs: object) -> tuple[int, bytes]:
        raise AssertionError("private HTTPS fallback was called")

    monkeypatch.setattr(orders_module, "_https_request", fail_if_called)
    transport = _Boundary((200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        created = _call(ledger, transport=transport)
        existing = _call(ledger, transport=transport)

    assert created.resolution is RazorpayOrderResolutionV1.CREATED
    assert existing.resolution is RazorpayOrderResolutionV1.EXISTING
    assert transport.post_count == 1
    assert transport.get_count == 1


def test_injected_transport_is_not_reached_for_tampered_certificate(
    tmp_path: Path,
) -> None:
    certificate = _validated_copy(
        _certificate(),
        allocation=_tampered_allocation("soft_score"),
    )
    request = _request_for(certificate)
    transport = _Boundary((200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(MoneyGovernorError) as caught:
            _call(ledger, certificate=certificate, request=request, transport=transport)
        assert caught.value.code is MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
        assert transport.calls == []
        assert (
            ledger.get_idempotency_record(
                namespace=_IDEMPOTENCY_NAMESPACE,
                idempotency_key=request.execution_id,
            )
            is None
        )
        assert ledger.get_execution_reservation(request.execution_id) is None


def test_injected_transport_is_not_reached_for_expired_buyer_authorization(
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(
        certificate,
        buyer_valid_until=_TIME - timedelta(microseconds=1),
    )
    transport = _Boundary((200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(MoneyGovernorError) as caught:
            _call(ledger, request=request, transport=transport)
        assert caught.value.code is MoneyGovernorFailureCode.BUYER_AUTHORIZATION_NOT_ACTIVE
        assert transport.calls == []
        assert ledger.get_execution_reservation(request.execution_id) is None


def test_invalid_injected_creation_response_keeps_strict_failure_mapping(
    tmp_path: Path,
) -> None:
    transport = _Boundary((200, _response(amount=2_701, amount_due=2_701)))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger, transport=transport),
        )
    assert transport.post_count == 1
    assert transport.get_count == 0


def test_injected_existing_order_response_mismatch_keeps_stable_failure(
    tmp_path: Path,
) -> None:
    transport = _Boundary((200, _response(amount=2_701, amount_due=2_701)))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_reference(ledger)
        _assert_order_error(
            RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH,
            lambda: _call(ledger, transport=transport),
        )
    assert transport.post_count == 0
    assert transport.get_count == 1


def test_injected_post_transport_timeout_maps_to_recovery_required(
    tmp_path: Path,
) -> None:
    transport = _Boundary(TimeoutError("provider secret must stay private"))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger, transport=transport),
        )
    assert transport.post_count == 1
    assert transport.get_count == 0


def test_injected_get_transport_timeout_maps_to_fetch_failed(
    tmp_path: Path,
) -> None:
    transport = _Boundary(TimeoutError("provider secret must stay private"))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_reference(ledger)
        _assert_order_error(
            RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED,
            lambda: _call(ledger, transport=transport),
        )
    assert transport.post_count == 0
    assert transport.get_count == 1


def test_transport_none_preserves_default_private_https_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        result = _call(ledger, transport=None)
    assert result.resolution is RazorpayOrderResolutionV1.CREATED
    assert boundary.post_count == 1
    assert boundary.get_count == 0


def test_provider_response_may_omit_optional_binding_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        (200, _response(partial_payment=_ABSENT, offer_id=_ABSENT)),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        created = _call(ledger)
        existing = _call(ledger)
    assert created.resolution is RazorpayOrderResolutionV1.CREATED
    assert existing.resolution is RazorpayOrderResolutionV1.EXISTING
    assert boundary.post_count == 1
    assert boundary.get_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("partial_payment", True),
        ("partial_payment", 1),
        ("partial_payment", "false"),
        ("offer_id", "offer_unexpected"),
        ("offer_id", ""),
    ],
)
def test_incompatible_create_provider_binding_is_claimed_once_and_never_retried(
    field: str,
    value: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = (
        _response(partial_payment=value)
        if field == "partial_payment"
        else _response(offer_id=value)
    )
    boundary = _install_boundary(monkeypatch, (200, response))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger),
        )
        assert boundary.post_count == 1
        assert (
            ledger.get_idempotency_record(
                namespace=_IDEMPOTENCY_NAMESPACE,
                idempotency_key="e1000000-0000-4000-8000-000000000001",
            )
            is not None
        )
        assert (
            ledger.list_provider_references(
                "e1000000-0000-4000-8000-000000000001",
                limit=1_000,
            )
            == ()
        )
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger),
        )
    assert boundary.post_count == 1


@pytest.mark.parametrize(
    ("status", "amount_paid", "amount_due", "attempts"),
    [
        ("created", 0, 2_700, 0),
        ("attempted", 500, 2_200, 1),
        ("paid", 2_700, 0, 2),
    ],
)
def test_existing_reference_is_get_validated_and_statuses_are_provider_facts(
    status: str,
    amount_paid: int,
    amount_due: int,
    attempts: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        (
            200,
            _response(
                status=status,
                amount_paid=amount_paid,
                amount_due=amount_due,
                attempts=attempts,
                partial_payment=False,
                offer_id=None,
            ),
        ),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_reference(ledger)
        result = _call(ledger)
        references = ledger.list_provider_references(result.order.execution_id, limit=1_000)
    assert result.resolution is RazorpayOrderResolutionV1.EXISTING
    assert result.order.status.value == status
    assert boundary.get_count == 1
    assert boundary.post_count == 0
    assert boundary.calls[0]["path"] == f"/v1/orders/{_ORDER_ID}"
    assert len(references) == 1


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (
            "partial_payment",
            True,
            RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH,
        ),
        (
            "offer_id",
            "offer_unexpected",
            RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH,
        ),
        (
            "partial_payment",
            1,
            RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED,
        ),
        (
            "partial_payment",
            "false",
            RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED,
        ),
    ],
)
def test_existing_order_provider_binding_failure_never_posts(
    field: str,
    value: object,
    expected: RazorpayOrderFailureCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = (
        _response(partial_payment=value)
        if field == "partial_payment"
        else _response(offer_id=value)
    )
    boundary = _install_boundary(monkeypatch, (200, response))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        reference = _record_reference(ledger)
        _assert_order_error(expected, lambda: _call(ledger))
        assert ledger.list_provider_references(reference.execution_id, limit=1_000) == (reference,)
    assert boundary.get_count == 1
    assert boundary.post_count == 0


def test_existing_razorpay_reference_hidden_after_full_page_is_still_fetched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        plan = _record_filler_references(ledger)
        ledger.record_provider_reference(
            ProviderReferenceV1(
                provider_name="razorpay",
                reference_kind="order",
                reference_id=_ORDER_ID,
                execution_id=plan.execution_id,
                recorded_at=_TIME,
            )
        )
        result = _call(ledger)
    assert result.resolution is RazorpayOrderResolutionV1.EXISTING
    assert result.order.provider_order_id == _ORDER_ID
    assert boundary.get_count == 1
    assert boundary.post_count == 0


def test_hidden_duplicate_razorpay_references_fail_before_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        plan = _record_filler_references(ledger)
        for provider_order_id in (_ORDER_ID, "order_CLEARReview2"):
            ledger.record_provider_reference(
                ProviderReferenceV1(
                    provider_name="razorpay",
                    reference_kind="order",
                    reference_id=provider_order_id,
                    execution_id=plan.execution_id,
                    recorded_at=_TIME,
                )
            )
        _assert_order_error(
            RazorpayOrderFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
            lambda: _call(ledger),
        )
    assert boundary.get_count == 0
    assert boundary.post_count == 0


def test_created_reference_after_full_page_is_verified_and_retry_fetches_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_filler_references(ledger)
        created = _call(ledger)
        existing = _call(ledger)
    assert created.resolution is RazorpayOrderResolutionV1.CREATED
    assert created.order.provider_order_id == _ORDER_ID
    assert existing.resolution is RazorpayOrderResolutionV1.EXISTING
    assert existing.order.provider_order_id == _ORDER_ID
    assert boundary.post_count == 1
    assert boundary.get_count == 1


def test_duplicate_local_order_references_fail_before_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        first = _record_reference(ledger)
        ledger.record_provider_reference(
            ProviderReferenceV1(
                provider_name="razorpay",
                reference_kind="order",
                reference_id="order_CLEARReview2",
                execution_id=first.execution_id,
                recorded_at=_TIME,
            )
        )
        _assert_order_error(
            RazorpayOrderFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
            lambda: _call(ledger),
        )
    assert boundary.calls == []


def test_malformed_local_order_reference_fails_before_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_reference(ledger, "not/a/provider/order")
        _assert_order_error(
            RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH,
            lambda: _call(ledger),
        )
    assert boundary.calls == []


@pytest.mark.parametrize(
    ("same", "expected"),
    [
        (True, RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED),
        (False, RazorpayOrderFailureCode.LOCAL_IDEMPOTENCY_CONFLICT),
    ],
)
def test_preexisting_create_claim_never_blindly_posts(
    same: bool,
    expected: RazorpayOrderFailureCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        plan = _authorized_plan(ledger)
        ledger.claim_idempotency(
            IdempotencyRecordV1(
                namespace=_IDEMPOTENCY_NAMESPACE,
                idempotency_key=plan.execution_id,
                request_fingerprint_sha256=(
                    razorpay_order_create_fingerprint_v1(plan) if same else "0" * 64
                ),
                execution_id=plan.execution_id,
                recorded_at=_TIME,
            )
        )
        _assert_order_error(expected, lambda: _call(ledger))
    assert boundary.calls == []


def _uncertain_outcome(kind: str) -> tuple[int, bytes] | BaseException:
    if kind == "timeout":
        return TimeoutError()
    if kind == "tls":
        return ssl.SSLError()
    if kind == "oserror":
        return ConnectionResetError()
    if kind == "http_exception":
        return orders_module.http.client.HTTPException()
    if kind.startswith("status_"):
        return int(kind.removeprefix("status_")), b"provider prose must stay private"
    if kind == "oversized":
        return 200, b"x" * 262_145
    if kind == "invalid_utf8":
        return 200, b"\xff"
    if kind == "invalid_json":
        return 200, b"{"
    if kind == "nul":
        return 200, _response() + b"\x00"
    if kind == "root_array":
        return 200, b"[]"
    if kind == "missing_field":
        return 200, b"{}"
    if kind == "duplicate":
        return 200, _response()[:-1] + b',"extra":{"x":1,"x":2}}'
    changes: dict[str, object] = {
        "wrong_amount": {"amount": 2_701},
        "wrong_receipt": {"receipt": "e1000000-0000-4000-8000-000000000002"},
        "wrong_currency": {"currency": "USD"},
        "wrong_entity": {"entity": "payment"},
        "wrong_id": {"provider_order_id": "bad-order"},
        "wrong_status": {"status": "attempted"},
        "paid": {"amount_paid": 1},
        "due": {"amount_due": 2_699},
        "attempts": {"attempts": 1},
        "bool_amount": {"amount": True},
        "nan": {},
        "infinity": {},
        "negative_infinity": {},
    }[kind]
    if kind == "nan":
        return 200, _response()[:-1] + b',"extra":NaN}'
    if kind == "infinity":
        return 200, _response()[:-1] + b',"extra":Infinity}'
    if kind == "negative_infinity":
        return 200, _response()[:-1] + b',"extra":-Infinity}'
    return 200, _response(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "tls",
        "oserror",
        "http_exception",
        "status_301",
        "status_302",
        "status_307",
        "status_308",
        "status_400",
        "status_401",
        "status_429",
        "status_500",
        "oversized",
        "invalid_utf8",
        "invalid_json",
        "nul",
        "root_array",
        "missing_field",
        "duplicate",
        "wrong_amount",
        "wrong_receipt",
        "wrong_currency",
        "wrong_entity",
        "wrong_id",
        "wrong_status",
        "paid",
        "due",
        "attempts",
        "bool_amount",
        "nan",
        "infinity",
        "negative_infinity",
    ],
)
def test_uncertain_post_outcome_is_claimed_once_and_never_retried(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, _uncertain_outcome(kind))
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger),
        )
        assert boundary.post_count == 1
        assert (
            ledger.get_idempotency_record(
                namespace=_IDEMPOTENCY_NAMESPACE,
                idempotency_key="e1000000-0000-4000-8000-000000000001",
            )
            is not None
        )
        assert (
            ledger.list_provider_references(
                "e1000000-0000-4000-8000-000000000001",
                limit=1_000,
            )
            == ()
        )
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger),
        )
    assert boundary.post_count == 1


def test_provider_success_then_reference_persistence_failure_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    original = SQLiteFinancialLedgerV1.record_provider_reference

    def fail_record(
        _ledger: SQLiteFinancialLedgerV1,
        _reference: ProviderReferenceV1,
    ) -> Any:
        raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED)

    monkeypatch.setattr(SQLiteFinancialLedgerV1, "record_provider_reference", fail_record)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(PersistenceError) as caught:
            _call(ledger)
        assert caught.value.code is PersistenceErrorCode.DATABASE_OPERATION_FAILED
        assert boundary.post_count == 1
        monkeypatch.setattr(SQLiteFinancialLedgerV1, "record_provider_reference", original)
        _assert_order_error(
            RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED,
            lambda: _call(ledger),
        )
    assert boundary.post_count == 1


@pytest.mark.parametrize(
    "outcome",
    [
        TimeoutError(),
        (301, b"redirect"),
        (404, b"missing"),
        (500, b"failure"),
        (200, b"{"),
        (200, b"x" * 262_145),
        (200, b"\xff"),
        (200, _response()[:-1] + b',"extra":{"x":1,"x":2}}'),
    ],
)
def test_existing_get_transport_status_and_parse_failures_are_fetch_failures(
    outcome: tuple[int, bytes] | BaseException,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, outcome)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_reference(ledger)
        _assert_order_error(
            RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED,
            lambda: _call(ledger),
        )
        assert (
            len(
                ledger.list_provider_references("e1000000-0000-4000-8000-000000000001", limit=1_000)
            )
            == 1
        )
    assert boundary.get_count == 1
    assert boundary.post_count == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_order_id": "order_Different"},
        {"amount": 2_701, "amount_due": 2_701},
        {"currency": "USD"},
        {"receipt": "e1000000-0000-4000-8000-000000000002"},
        {"amount_paid": 1, "amount_due": 2_700},
        {"entity": "payment"},
        {"attempts": -1},
    ],
)
def test_existing_order_binding_mismatch_never_posts(
    changes: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response(**changes)))  # type: ignore[arg-type]
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_reference(ledger)
        _assert_order_error(
            RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH,
            lambda: _call(ledger),
        )
    assert boundary.get_count == 1
    assert boundary.post_count == 0


def test_https_boundary_uses_exact_host_tls_timeout_basic_auth_and_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _Response:
        status = 200

        def read(self, amount: int) -> bytes:
            observed["read"] = amount
            return _response()

    class _Connection:
        def __init__(self, host: str, port: int, **kwargs: object) -> None:
            observed.update(host=host, port=port, **kwargs)

        def request(self, method: str, path: str, **kwargs: object) -> None:
            observed.update(method=method, path=path, **kwargs)

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(orders_module.http.client, "HTTPSConnection", _Connection)
    status, _data = orders_module._https_request(
        method="POST",
        path="/v1/orders",
        credentials=_credentials(),
        body=b"{}",
    )
    headers = observed["headers"]
    assert isinstance(headers, dict)
    authorization = headers["Authorization"]
    assert authorization.startswith("Basic ")
    decoded = base64.b64decode(authorization.removeprefix("Basic ")).decode()
    if not hmac.compare_digest(decoded, f"{_KEY_ID}:{_KEY_SECRET}"):
        raise AssertionError("invalid Basic authentication material")
    assert observed["host"] == "api.razorpay.com"
    assert observed["port"] == 443
    assert observed["timeout"] == 10
    assert isinstance(observed["context"], ssl.SSLContext)
    assert observed["read"] == 262_145
    assert observed["closed"] is True
    assert status == 200


def test_concurrent_same_execution_performs_at_most_one_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)):
        pass

    def run() -> object:
        with open_sqlite_financial_ledger_v1(str(path)) as ledger:
            try:
                return _call(ledger)
            except RazorpayOrderError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _index: run(), range(2)))

    assert boundary.post_count == 1
    assert any(
        getattr(outcome, "resolution", None) is RazorpayOrderResolutionV1.CREATED
        for outcome in outcomes
    )
    assert all(
        getattr(outcome, "resolution", None)
        in {RazorpayOrderResolutionV1.CREATED, RazorpayOrderResolutionV1.EXISTING}
        or outcome is RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED
        for outcome in outcomes
    )
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        references = ledger.list_provider_references(
            "e1000000-0000-4000-8000-000000000001",
            limit=1_000,
        )
    assert len(references) == 1


def test_prior_certificate_and_execution_goldens_used_by_order_fixture_are_exact() -> None:
    certificate = _certificate()
    assert allocation_certificate_v2_digest(certificate) == (
        "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
    )
    assert _request_for(certificate).certificate_digest_sha256 == (
        "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
    )


def test_decision_time_before_window_still_fails_before_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, (200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(MoneyGovernorError):
            _call(ledger, decision_time=_VALID_FROM - timedelta(microseconds=1))
    assert boundary.calls == []
