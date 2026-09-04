import base64
import inspect
import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import pytest

import clear_market.payments.razorpay.orders as create_orders_module
import clear_market.payments.recovery.razorpay_orders as recovery_module
from clear_market.execution import (
    MoneyGovernorError,
    MoneyGovernorFailureCode,
    authorize_execution_v1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    create_razorpay_test_order_v1,
    razorpay_order_create_fingerprint_v1,
)
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryError,
    RazorpayOrderRecoveryFailureCode,
    recover_razorpay_test_order_v1,
)
from clear_market.persistence import (
    IdempotencyRecordV1,
    PersistenceError,
    PersistenceErrorCode,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)
from tests.certificate.v2.test_serialization import _certificate, _identity, _validated_copy
from tests.execution.test_governor import _request_for
from tests.execution.test_models import _TIME
from tests.payments.razorpay.test_orders import _credentials, _response
from tests.verification.v2.test_verifier import _tampered_allocation, _trusted

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_OTHER_EXECUTION_ID = "e1000000-0000-4000-8000-000000000002"
_ORDER_ID = "order_CLEARReview1"
_OTHER_ORDER_ID = "order_CLEARReview2"
_CREATE_NAMESPACE = "razorpay.order.create.v1"
_SECRET = "review-secret-never-print"


def _candidate(
    *,
    provider_order_id: object = _ORDER_ID,
    entity: object = "order",
    amount: object = 2_700,
    currency: object = "INR",
    receipt: object = _EXECUTION_ID,
    extra: object | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": provider_order_id,
        "entity": entity,
        "amount": amount,
        "currency": currency,
        "receipt": receipt,
    }
    if extra is not None:
        value["extra"] = extra
    return value


def _collection(
    items: list[object],
    *,
    entity: object = "collection",
    count: object | None = None,
    extra: object | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "entity": entity,
        "count": len(items) if count is None else count,
        "items": items,
    }
    if extra is not None:
        payload["extra"] = extra
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class _GetBoundary:
    def __init__(self, outcomes: dict[str, tuple[int, bytes] | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []
        self._lock = Lock()

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        with self._lock:
            self.calls.append(kwargs)
        path = kwargs["path"]
        assert isinstance(path, str)
        outcome = self.outcomes[path]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _query_path(execution_id: str = _EXECUTION_ID) -> str:
    return f"/v1/orders?receipt={execution_id}&count=100&skip=0"


def _install_boundary(
    monkeypatch: pytest.MonkeyPatch,
    *,
    query: tuple[int, bytes] | BaseException | None = None,
    fetch: tuple[int, bytes] | BaseException | None = None,
    provider_order_id: str = _ORDER_ID,
) -> _GetBoundary:
    outcomes: dict[str, tuple[int, bytes] | BaseException] = {}
    if query is not None:
        outcomes[_query_path()] = query
    if fetch is not None:
        outcomes[f"/v1/orders/{provider_order_id}"] = fetch
    boundary = _GetBoundary(outcomes)
    monkeypatch.setattr(recovery_module, "_https_get", boundary)
    return boundary


def _authorize(ledger: SQLiteFinancialLedgerV1):
    certificate = _certificate()
    request = _request_for(certificate)
    plan = authorize_execution_v1(
        certificate=certificate,
        trusted_signing_identities=_trusted(),
        request=request,
        decision_time=_TIME,
        ledger=ledger,
    )
    return certificate, request, plan


def _claim_create_intent(
    ledger: SQLiteFinancialLedgerV1,
    *,
    fingerprint: str | None = None,
    execution_id: str | None = _EXECUTION_ID,
):
    _certificate_value, _request, plan = _authorize(ledger)
    return ledger.claim_idempotency(
        IdempotencyRecordV1(
            namespace=_CREATE_NAMESPACE,
            idempotency_key=plan.execution_id,
            request_fingerprint_sha256=(
                razorpay_order_create_fingerprint_v1(plan) if fingerprint is None else fingerprint
            ),
            execution_id=execution_id,
            recorded_at=_TIME - timedelta(minutes=1),
        )
    ).stored_record


def _record_order_reference(
    ledger: SQLiteFinancialLedgerV1,
    *,
    provider_order_id: str = _ORDER_ID,
) -> ProviderReferenceV1:
    _certificate_value, _request, plan = _authorize(ledger)
    reference = ProviderReferenceV1(
        provider_name="razorpay",
        reference_kind="order",
        reference_id=provider_order_id,
        execution_id=plan.execution_id,
        recorded_at=_TIME - timedelta(minutes=1),
    )
    ledger.record_provider_reference(reference)
    return reference


def _call(
    ledger: SQLiteFinancialLedgerV1,
    *,
    certificate: Any | None = None,
    trusted: Any | None = None,
    request: Any | None = None,
    decision_time: Any = _TIME,
    credentials: Any | None = None,
):
    selected_certificate = certificate or _certificate()
    return recover_razorpay_test_order_v1(
        certificate=selected_certificate,
        trusted_signing_identities=_trusted() if trusted is None else trusted,
        execution_request=request or _request_for(selected_certificate),
        decision_time=decision_time,
        ledger=ledger,
        credentials=_credentials() if credentials is None else credentials,
    )


def _assert_error(
    code: RazorpayOrderRecoveryFailureCode,
    action: Any,
) -> RazorpayOrderRecoveryError:
    with pytest.raises(RazorpayOrderRecoveryError) as caught:
        action()
    assert caught.value.code is code
    assert str(caught.value) == code.value
    for private in (
        _SECRET,
        _EXECUTION_ID,
        _ORDER_ID,
        "2700",
        "Authorization",
    ):
        assert private not in str(caught.value)
    return caught.value


def _paths(boundary: _GetBoundary) -> tuple[str, ...]:
    return tuple(str(call["path"]) for call in boundary.calls)


def test_public_api_has_governor_inputs_and_no_naked_plan() -> None:
    signature = inspect.signature(recover_razorpay_test_order_v1)
    assert tuple(signature.parameters) == (
        "certificate",
        "trusted_signing_identities",
        "execution_request",
        "decision_time",
        "ledger",
        "credentials",
    )
    assert "plan" not in signature.parameters


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("empty_trust", MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ("altered_key", MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ("allocation", MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ("expired", MoneyGovernorFailureCode.BUYER_AUTHORIZATION_NOT_ACTIVE),
    ),
)
def test_governor_failure_precedes_provider_and_recovery_writes(
    kind: str,
    expected: MoneyGovernorFailureCode,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = _certificate()
    trusted = _trusted()
    request = _request_for(certificate)
    decision_time = _TIME
    if kind == "empty_trust":
        trusted = ()
    elif kind == "altered_key":
        trusted = (
            _identity(1, public_key_hex=_identity(2).ed25519_public_key_hex),
            _identity(2),
        )
    elif kind == "allocation":
        certificate = _validated_copy(
            certificate,
            allocation=_tampered_allocation("soft_score"),
        )
        request = _request_for(certificate)
    else:
        request = _request_for(
            certificate,
            buyer_valid_until=_TIME - timedelta(microseconds=1),
        )
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(MoneyGovernorError) as caught:
            _call(
                ledger,
                certificate=certificate,
                trusted=trusted,
                request=request,
                decision_time=decision_time,
            )
        assert caught.value.code is expected
        assert boundary.calls == []


def test_existing_reference_is_exact_get_validated_without_receipt_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, fetch=(200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        reference = _record_order_reference(ledger)
        before = ledger.list_provider_references(_EXECUTION_ID, limit=1_000)
        result = _call(ledger)
        after = ledger.list_provider_references(_EXECUTION_ID, limit=1_000)
    assert result.disposition is RazorpayOrderRecoveryDispositionV1.EXISTING
    assert result.order is not None
    assert result.order.provider_order_id == _ORDER_ID
    assert before == after == (reference,)
    assert _paths(boundary) == (f"/v1/orders/{_ORDER_ID}",)


def test_duplicate_local_order_references_fail_before_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        first = _record_order_reference(ledger)
        ledger.record_provider_reference(first.model_copy(update={"reference_id": _OTHER_ORDER_ID}))
        _assert_error(
            RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
            lambda: _call(ledger),
        )
    assert boundary.calls == []


def test_existing_reference_after_full_page_is_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, fetch=(200, _response()))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _certificate_value, _request, plan = _authorize(ledger)
        for index in range(1_000):
            ledger.record_provider_reference(
                ProviderReferenceV1(
                    provider_name="a-filler",
                    reference_kind="reference",
                    reference_id=f"filler-{index:04d}",
                    execution_id=plan.execution_id,
                    recorded_at=_TIME,
                )
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
        assert _call(ledger).disposition is RazorpayOrderRecoveryDispositionV1.EXISTING
    assert _paths(boundary) == (f"/v1/orders/{_ORDER_ID}",)


def test_malformed_existing_reference_fails_without_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _record_order_reference(ledger, provider_order_id="not/an/order")
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH,
            lambda: _call(ledger),
        )
    assert boundary.calls == []


def test_create_intent_is_required_before_provider_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _authorize(ledger)
        reservation = ledger.get_execution_reservation(_EXECUTION_ID)
        before = ledger.list_provider_references(_EXECUTION_ID, limit=1_000)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.CREATE_INTENT_MISSING,
            lambda: _call(ledger),
        )
        assert ledger.get_execution_reservation(_EXECUTION_ID) == reservation
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == before
    assert boundary.calls == []


def test_pristine_valid_governor_call_may_reserve_before_missing_create_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert ledger.get_execution_reservation(_EXECUTION_ID) is None
        _assert_error(
            RazorpayOrderRecoveryFailureCode.CREATE_INTENT_MISSING,
            lambda: _call(ledger),
        )
        assert ledger.get_execution_reservation(_EXECUTION_ID) is not None
        assert (
            ledger.get_idempotency_record(
                namespace=_CREATE_NAMESPACE,
                idempotency_key=_EXECUTION_ID,
            )
            is None
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
        assert ledger.list_events(_EXECUTION_ID, limit=1_000) == ()
    assert boundary.calls == []


@pytest.mark.parametrize("conflict", ("fingerprint", "execution"))
def test_conflicting_create_intent_blocks_provider_discovery(
    conflict: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(
            ledger,
            fingerprint="0" * 64 if conflict == "fingerprint" else None,
            execution_id=None if conflict == "execution" else _EXECUTION_ID,
        )
        _assert_error(
            RazorpayOrderRecoveryFailureCode.CREATE_INTENT_CONFLICT,
            lambda: _call(ledger),
        )
    assert boundary.calls == []


def test_not_found_is_successful_repeatable_get_only_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, query=(200, _collection([])))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        create_intent = _claim_create_intent(ledger)
        reservation = ledger.get_execution_reservation(_EXECUTION_ID)
        first = _call(ledger)
        second = _call(ledger)
        assert (
            ledger.get_idempotency_record(
                namespace=_CREATE_NAMESPACE,
                idempotency_key=_EXECUTION_ID,
            )
            == create_intent
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
        assert ledger.list_events(_EXECUTION_ID, limit=1_000) == ()
        assert ledger.get_execution_reservation(_EXECUTION_ID) == reservation
    assert first == second
    assert first.disposition is RazorpayOrderRecoveryDispositionV1.NOT_FOUND
    assert first.order is None
    assert _paths(boundary) == (_query_path(), _query_path())


def test_exact_discovery_fetch_and_reference_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate(extra={"future": True})], extra=True)),
        fetch=(200, _response(extra={"future": True})),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        create_intent = _claim_create_intent(ledger)
        result = _call(ledger)
        references = ledger.list_provider_references(_EXECUTION_ID, limit=1_000)
        assert (
            ledger.get_idempotency_record(
                namespace=_CREATE_NAMESPACE,
                idempotency_key=_EXECUTION_ID,
            )
            == create_intent
        )
        assert ledger.list_events(_EXECUTION_ID, limit=1_000) == ()
    assert result.disposition is RazorpayOrderRecoveryDispositionV1.RECOVERED
    assert result.order is not None
    assert result.order.provider_order_id == _ORDER_ID
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")
    assert references == (
        ProviderReferenceV1(
            provider_name="razorpay",
            reference_kind="order",
            reference_id=_ORDER_ID,
            execution_id=_EXECUTION_ID,
            recorded_at=_TIME,
        ),
    )


def test_uncertain_21a_attempt_recovers_then_21a_uses_get_without_second_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_calls: list[dict[str, object]] = []

    def uncertain_create(**kwargs: object) -> tuple[int, bytes]:
        create_calls.append(kwargs)
        raise TimeoutError

    monkeypatch.setattr(create_orders_module, "_https_request", uncertain_create)
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        with pytest.raises(RazorpayOrderError) as caught:
            create_razorpay_test_order_v1(
                certificate=_certificate(),
                trusted_signing_identities=_trusted(),
                execution_request=_request_for(_certificate()),
                decision_time=_TIME,
                ledger=ledger,
                credentials=_credentials(),
            )
        assert caught.value.code is RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED
        create_intent = ledger.get_idempotency_record(
            namespace=_CREATE_NAMESPACE,
            idempotency_key=_EXECUTION_ID,
        )
        assert create_intent is not None

        recovery_boundary = _install_boundary(
            monkeypatch,
            query=(200, _collection([_candidate()])),
            fetch=(200, _response()),
        )
        recovered = _call(ledger)

        later_calls: list[dict[str, object]] = []

        def later_get(**kwargs: object) -> tuple[int, bytes]:
            later_calls.append(kwargs)
            assert kwargs["method"] == "GET"
            return 200, _response()

        monkeypatch.setattr(create_orders_module, "_https_request", later_get)
        existing = create_razorpay_test_order_v1(
            certificate=_certificate(),
            trusted_signing_identities=_trusted(),
            execution_request=_request_for(_certificate()),
            decision_time=_TIME,
            ledger=ledger,
            credentials=_credentials(),
        )

    assert len(create_calls) == 1
    assert create_calls[0]["method"] == "POST"
    assert recovered.disposition is RazorpayOrderRecoveryDispositionV1.RECOVERED
    assert _paths(recovery_boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")
    assert existing.resolution is RazorpayOrderResolutionV1.EXISTING
    assert len(later_calls) == 1
    assert later_calls[0]["method"] == "GET"


def test_multiple_discovered_orders_fail_ambiguous_without_exact_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate(), _candidate(provider_order_id=_OTHER_ORDER_ID)])),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_AMBIGUOUS,
            lambda: _call(ledger),
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
    assert _paths(boundary) == (_query_path(),)


@pytest.mark.parametrize(
    ("count", "items"),
    (
        (1, []),
        (0, [_candidate()]),
        (2, [_candidate()]),
        (1, [_candidate(), _candidate(provider_order_id=_OTHER_ORDER_ID)]),
        (101, [_candidate() for _ in range(101)]),
    ),
)
def test_inconsistent_collection_metadata_fails_before_candidate_selection(
    count: int,
    items: list[object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection(items, count=count)),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        create_intent = _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED,
            lambda: _call(ledger),
        )
        assert (
            ledger.get_idempotency_record(
                namespace=_CREATE_NAMESPACE,
                idempotency_key=_EXECUTION_ID,
            )
            == create_intent
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
        assert ledger.list_events(_EXECUTION_ID, limit=1_000) == ()
    assert _paths(boundary) == (_query_path(),)


@pytest.mark.parametrize(
    "changes",
    (
        {"receipt": _OTHER_EXECUTION_ID},
        {"amount": 2_701},
        {"currency": "USD"},
        {"entity": "payment"},
        {"provider_order_id": "bad-order"},
    ),
)
def test_discovered_order_contradiction_is_mismatch_without_reference_write(
    changes: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate(**changes)])),  # type: ignore[arg-type]
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH,
            lambda: _call(ledger),
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
    assert _paths(boundary) == (_query_path(),)


def _query_failure(kind: str) -> tuple[int, bytes] | BaseException:
    if kind == "timeout":
        return TimeoutError()
    if kind == "tls":
        return ssl.SSLError()
    if kind == "reset":
        return ConnectionResetError()
    if kind == "http_exception":
        return recovery_module.http.client.HTTPException()
    if kind.startswith("status_"):
        return int(kind.removeprefix("status_")), b"private provider prose"
    if kind == "oversized":
        return 200, b"x" * 262_145
    if kind == "utf8":
        return 200, b"\xff"
    if kind == "json":
        return 200, b"{"
    if kind == "duplicate":
        return 200, b'{"entity":"collection","count":0,"items":[],"items":[]}'
    if kind == "nested_duplicate":
        return 200, (
            b'{"entity":"collection","count":1,"items":'
            b'[{"id":"order_CLEARReview1","id":"order_CLEARReview1"}]}'
        )
    if kind == "nan":
        return 200, b'{"entity":"collection","count":0,"items":[],"x":NaN}'
    if kind == "infinity":
        return 200, b'{"entity":"collection","count":0,"items":[],"x":Infinity}'
    if kind == "negative_infinity":
        return 200, b'{"entity":"collection","count":0,"items":[],"x":-Infinity}'
    if kind == "nul":
        return 200, _collection([]) + b"\x00"
    if kind == "root":
        return 200, b"[]"
    if kind == "bool_count":
        return 200, _collection([], count=True)
    if kind == "negative_count":
        return 200, _collection([], count=-1)
    if kind == "items_type":
        return 200, b'{"count":0,"entity":"collection","items":{}}'
    if kind == "item_type":
        return 200, _collection([[]])
    if kind == "item_missing":
        return 200, _collection([{}])
    if kind == "item_bool_amount":
        return 200, _collection([_candidate(amount=True)])
    if kind == "entity":
        return 200, _collection([], entity="orders")
    if kind == "missing":
        return 200, b"{}"
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    (
        "timeout",
        "tls",
        "reset",
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
        "utf8",
        "json",
        "duplicate",
        "nested_duplicate",
        "nan",
        "infinity",
        "negative_infinity",
        "nul",
        "root",
        "bool_count",
        "negative_count",
        "items_type",
        "item_type",
        "item_missing",
        "item_bool_amount",
        "entity",
        "missing",
    ),
)
def test_receipt_query_failures_are_sanitized_and_nonmutating(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, query=_query_failure(kind))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        intent = _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED,
            lambda: _call(ledger),
        )
        assert (
            ledger.get_idempotency_record(
                namespace=_CREATE_NAMESPACE,
                idempotency_key=_EXECUTION_ID,
            )
            == intent
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
    assert _paths(boundary) == (_query_path(),)


def _fetch_response(kind: str) -> bytes:
    semantic: dict[str, object] = {
        "wrong_id": {"provider_order_id": _OTHER_ORDER_ID},
        "bad_id": {"provider_order_id": "bad-order"},
        "wrong_amount": {"amount": 2_701, "amount_due": 2_701},
        "wrong_receipt": {"receipt": _OTHER_EXECUTION_ID},
        "wrong_currency": {"currency": "USD"},
        "wrong_entity": {"entity": "payment"},
        "partial_true": {"partial_payment": True},
        "offer": {"offer_id": "offer_unexpected"},
        "offers": {"extra": None},
        "sum": {"amount_paid": 1, "amount_due": 2_700},
        "status": {"status": "refunded"},
        "attempts": {"attempts": -1},
        "paid_negative": {"amount_paid": -1, "amount_due": 2_701},
        "due_negative": {"amount_paid": 2_701, "amount_due": -1},
    }[kind]
    if kind == "offers":
        payload = json.loads(_response())
        payload["offers"] = ["offer_unexpected"]
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _response(**semantic)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kind",
    (
        "wrong_id",
        "bad_id",
        "wrong_amount",
        "wrong_receipt",
        "wrong_currency",
        "wrong_entity",
        "partial_true",
        "offer",
        "offers",
        "sum",
        "status",
        "attempts",
        "paid_negative",
        "due_negative",
    ),
)
def test_exact_fetch_semantic_mismatch_never_persists(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, _fetch_response(kind)),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH,
            lambda: _call(ledger),
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")


@pytest.mark.parametrize(
    "response",
    (
        b"{}",
        b"[]",
        b"{",
        b"\xff",
        b"x" * 262_145,
        b'{"id":"x","id":"y"}',
        _response(partial_payment=1),
        _response(partial_payment="false"),
    ),
)
def test_exact_fetch_malformed_payload_is_fetch_failure(
    response: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, response),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED,
            lambda: _call(ledger),
        )
        assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")


def test_malformed_offers_collection_is_fetch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(_response())
    payload["offers"] = {}
    response = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, response),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED,
            lambda: _call(ledger),
        )
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")


@pytest.mark.parametrize(
    "outcome",
    (
        TimeoutError(),
        ssl.SSLError(),
        ConnectionResetError(),
        recovery_module.http.client.HTTPException(),
        (301, b"redirect"),
        (302, b"redirect"),
        (307, b"redirect"),
        (308, b"redirect"),
        (400, b"bad"),
        (401, b"bad"),
        (429, b"bad"),
        (500, b"bad"),
    ),
)
def test_exact_fetch_transport_or_status_failure_is_fetch_failure(
    outcome: tuple[int, bytes] | BaseException,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=outcome,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED,
            lambda: _call(ledger),
        )
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")


@pytest.mark.parametrize(
    "changes",
    (
        {},
        {"partial_payment": False, "offer_id": None},
    ),
)
@pytest.mark.parametrize(
    ("status", "amount_paid", "amount_due", "attempts"),
    (
        ("created", 0, 2_700, 0),
        ("attempted", 500, 2_200, 1),
        ("paid", 2_700, 0, 2),
    ),
)
def test_exact_fetch_accepts_optional_absence_or_compatible_values_and_provider_statuses(
    changes: dict[str, object],
    status: str,
    amount_paid: int,
    amount_due: int,
    attempts: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(
        _response(
            status=status,
            amount_paid=amount_paid,
            amount_due=amount_due,
            attempts=attempts,
        )
    )
    payload.pop("partial_payment")
    payload.pop("offer_id")
    payload.update(changes)
    payload["offers"] = []
    response = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, response),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        result = _call(ledger)
    assert result.disposition is RazorpayOrderRecoveryDispositionV1.RECOVERED
    assert result.order is not None
    assert result.order.status.value == status
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")


def test_post_write_exhaustive_scan_finds_reference_after_1000_fillers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, _response()),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        for index in range(1_000):
            ledger.record_provider_reference(
                ProviderReferenceV1(
                    provider_name="a-filler",
                    reference_kind="reference",
                    reference_id=f"filler-{index:04d}",
                    execution_id=_EXECUTION_ID,
                    recorded_at=_TIME,
                )
            )
        result = _call(ledger)
        references = ledger.list_provider_references(_EXECUTION_ID, limit=1_000, offset=1_000)
    assert result.disposition is RazorpayOrderRecoveryDispositionV1.RECOVERED
    assert references[-1].reference_id == _ORDER_ID
    assert _paths(boundary) == (_query_path(), f"/v1/orders/{_ORDER_ID}")


def test_concurrent_recovery_records_one_reference_without_provider_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, _response()),
    )
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        _claim_create_intent(ledger)

    def run() -> object:
        with open_sqlite_financial_ledger_v1(str(path)) as ledger:
            return _call(ledger)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: run(), range(2)))
    assert all(
        result.disposition
        in {
            RazorpayOrderRecoveryDispositionV1.RECOVERED,
            RazorpayOrderRecoveryDispositionV1.EXISTING,
        }
        for result in results
    )
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        references = ledger.list_provider_references(_EXECUTION_ID, limit=1_000)
    assert len(references) == 1
    assert references[0].reference_id == _ORDER_ID
    assert all("method" not in call or call["method"] == "GET" for call in boundary.calls)


def test_persistence_error_propagates_unchanged_before_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _authorize(ledger)

        def fail_list(*_args: object, **_kwargs: object) -> tuple[ProviderReferenceV1, ...]:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED)

        monkeypatch.setattr(ledger, "list_provider_references", fail_list)
        with pytest.raises(PersistenceError) as caught:
            _call(ledger)
        assert caught.value.code is PersistenceErrorCode.DATABASE_OPERATION_FAILED
    assert boundary.calls == []


def test_https_boundary_is_exact_tls_basic_auth_and_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _Response:
        status = 200

        def read(self, amount: int) -> bytes:
            observed["read"] = amount
            return _collection([])

    class _Connection:
        def __init__(self, host: str, port: int, **kwargs: object) -> None:
            observed.update(host=host, port=port, **kwargs)

        def request(self, method: str, path: str, **kwargs: object) -> None:
            observed.update(method=method, path=path, **kwargs)

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(recovery_module.http.client, "HTTPSConnection", _Connection)
    status, _data = recovery_module._https_get(
        path=_query_path(),
        credentials=_credentials(),
    )
    headers = observed["headers"]
    assert isinstance(headers, dict)
    encoded = str(headers["Authorization"]).removeprefix("Basic ")
    assert base64.b64decode(encoded).decode() == ("rzp_test_review_key:review-secret-never-print")
    assert observed["host"] == "api.razorpay.com"
    assert observed["port"] == 443
    assert observed["timeout"] == 10
    assert isinstance(observed["context"], ssl.SSLContext)
    assert observed["method"] == "GET"
    assert observed["path"] == _query_path()
    assert observed["read"] == 262_145
    assert observed["closed"] is True
    assert status == 200


def test_result_and_error_never_expose_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(monkeypatch, query=(500, b"Authorization private body"))
    credentials = _credentials()
    assert _SECRET not in repr(credentials)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        error = _assert_error(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED,
            lambda: _call(ledger, credentials=credentials),
        )
    assert _SECRET not in repr(error)
    assert "Authorization" not in repr(error)
    assert boundary.calls


def test_exact_recovery_result_dumps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_boundary(
        monkeypatch,
        query=(200, _collection([_candidate()])),
        fetch=(200, _response()),
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        recovered = _call(ledger)
        existing = _call(ledger)
    expected_order = {
        "schema_version": "1",
        "razorpay_order_version": "razorpay-order-v1",
        "execution_id": _EXECUTION_ID,
        "provider_order_id": _ORDER_ID,
        "amount": {"amount_paise": 2_700, "currency": "INR"},
        "currency": "INR",
        "receipt": _EXECUTION_ID,
        "status": "created",
    }
    base = {
        "schema_version": "1",
        "razorpay_order_recovery_result_version": "razorpay-order-recovery-result-v1",
        "recovery_version": "razorpay-order-recovery-v1",
        "execution_id": _EXECUTION_ID,
        "order_create_fingerprint_version": (
            "sha256-razorpay-order-create-intent-v1-clear-json-v1"
        ),
        "order_create_fingerprint_sha256": (
            "9a5897d3c79273ee2e5a331f3a36bb65093f41f7ed9b1c6e5d898af555ebd45c"
        ),
    }
    assert recovered.model_dump(mode="json") == {
        **base,
        "disposition": "RECOVERED",
        "order": expected_order,
    }
    assert existing.model_dump(mode="json") == {
        **base,
        "disposition": "EXISTING",
        "order": expected_order,
    }
    assert _paths(boundary) == (
        _query_path(),
        f"/v1/orders/{_ORDER_ID}",
        f"/v1/orders/{_ORDER_ID}",
    )


def test_exact_not_found_result_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_boundary(monkeypatch, query=(200, _collection([])))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _claim_create_intent(ledger)
        result = _call(ledger)
    assert result.model_dump(mode="json") == {
        "schema_version": "1",
        "razorpay_order_recovery_result_version": "razorpay-order-recovery-result-v1",
        "recovery_version": "razorpay-order-recovery-v1",
        "disposition": "NOT_FOUND",
        "execution_id": _EXECUTION_ID,
        "order_create_fingerprint_version": (
            "sha256-razorpay-order-create-intent-v1-clear-json-v1"
        ),
        "order_create_fingerprint_sha256": (
            "9a5897d3c79273ee2e5a331f3a36bb65093f41f7ed9b1c6e5d898af555ebd45c"
        ),
        "order": None,
    }
