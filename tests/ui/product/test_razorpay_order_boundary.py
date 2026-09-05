from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier, Lock
from typing import Any

import pytest

import ui.product.service as service_module
from clear_market.execution import ExecutionPlanV1
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResultV1,
    RazorpayOrderStatusV1,
    RazorpayOrderV1,
    razorpay_order_create_fingerprint_v1,
)
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryError,
    RazorpayOrderRecoveryFailureCode,
    RazorpayOrderRecoveryResultV1,
)
from clear_market.persistence import ProviderReferenceV1, SQLiteFinancialLedgerV1
from ui.product.models import SubmitOfferRequest
from ui.product.service import ProductErrorCode, ProductService, ProductServiceError

from .test_authority_workspace import _closed_feasible, _market, _runtime

_ENVIRONMENT = {
    "RAZORPAY_TEST_KEY_ID": "rzp_test_product_boundary",
    "RAZORPAY_TEST_KEY_SECRET": "product-test-secret-never-print",
}
_ORDER_ID = "order_CLEARProductBoundary1"


def _authorized(
    tmp_path: Path,
) -> tuple[ProductService, str, Path, dict[str, object]]:
    service, _clock, _merchants, market_id, _product_path, ledger_path = _closed_feasible(tmp_path)
    authority = service.authorize_market_execution(market_id)
    plan = authority["governor"]["execution_plan"]  # type: ignore[index]
    assert isinstance(plan, dict)
    return service, market_id, ledger_path, plan


def _provider_payload(
    *,
    execution_id: str,
    amount_paise: int,
    provider_order_id: str = _ORDER_ID,
) -> bytes:
    return json.dumps(
        {
            "id": provider_order_id,
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": "INR",
            "receipt": execution_id,
            "status": "created",
            "attempts": 0,
            "partial_payment": False,
            "offer_id": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class _OrderBoundary:
    def __init__(self, *, execution_id: str, amount_paise: int) -> None:
        self.execution_id = execution_id
        self.amount_paise = amount_paise
        self.calls: list[dict[str, object]] = []
        self._lock = Lock()

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        with self._lock:
            self.calls.append(kwargs)
        assert kwargs["method"] in {"GET", "POST"}
        assert kwargs["path"] in {"/v1/orders", f"/v1/orders/{_ORDER_ID}"}
        return 200, _provider_payload(
            execution_id=self.execution_id,
            amount_paise=self.amount_paise,
        )

    @property
    def post_count(self) -> int:
        return sum(call["method"] == "POST" for call in self.calls)

    @property
    def get_count(self) -> int:
        return sum(call["method"] == "GET" for call in self.calls)


def _persisted_plan(service: ProductService, market_id: str) -> tuple[ExecutionPlanV1, datetime]:
    with service.store.connection() as connection:
        context = service._load_closed_authority_context(connection, market_id)
        record = service.store.get_execution_authority(connection, market_id)
        assert record is not None
        _request, decision_time, plan = service._validated_execution_record(context, record)
    assert plan is not None
    return plan, decision_time


def test_product_order_requires_closed_feasible_authorized_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls = 0

    def forbidden_provider(**_kwargs: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider boundary must not run")

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", forbidden_provider)
    open_path = tmp_path / "open"
    open_path.mkdir()
    service, clock, merchants, _product_path, _ledger_path = _runtime(open_path)
    open_market = _market(service, clock, list(merchants.values()))
    with pytest.raises(ProductServiceError) as open_error:
        service.create_market_razorpay_order(open_market, environment=_ENVIRONMENT)
    assert open_error.value.code is ProductErrorCode.MARKET_NOT_CLOSED

    unauthorized_path = tmp_path / "unauthorized"
    unauthorized_path.mkdir()
    closed, _clock, _merchants, market_id, _product, _ledger = _closed_feasible(unauthorized_path)
    with pytest.raises(ProductServiceError) as unauthorized_error:
        closed.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)
    assert unauthorized_error.value.code is ProductErrorCode.EXECUTION_NOT_AUTHORIZED

    infeasible_path = tmp_path / "infeasible"
    infeasible_path.mkdir()
    infeasible, infeasible_clock, infeasible_merchants, _product, _ledger = _runtime(
        infeasible_path
    )
    infeasible_market = _market(
        infeasible,
        infeasible_clock,
        list(infeasible_merchants.values()),
        requested_quantity=5,
        minimum_acceptable_quantity=5,
    )
    for merchant_id in infeasible_merchants.values():
        infeasible.submit_offer(
            infeasible_market,
            SubmitOfferRequest(
                merchant_id=merchant_id,
                proposed_quantity=3,
                proposed_unit_price_paise=10_000,
            ),
        )
    infeasible.close_market(infeasible_market)
    with pytest.raises(ProductServiceError) as infeasible_error:
        infeasible.create_market_razorpay_order(
            infeasible_market,
            environment=_ENVIRONMENT,
        )
    assert infeasible_error.value.code is ProductErrorCode.ALLOCATION_NOT_EXECUTABLE
    assert provider_calls == 0


@pytest.mark.parametrize(
    "environment",
    (
        {},
        {"RAZORPAY_TEST_KEY_ID": "rzp_test_only"},
        {
            "RAZORPAY_TEST_KEY_ID": "rzp_live_forbidden",
            "RAZORPAY_TEST_KEY_SECRET": "must-not-leak",
        },
    ),
)
def test_missing_or_invalid_credentials_are_safe_and_do_not_contact_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> None:
    service, market_id, _ledger, _plan = _authorized(tmp_path)
    authority_before = service.get_market_authority(market_id)

    def forbidden_provider(**_kwargs: object) -> object:
        raise AssertionError("credentials must be validated before the provider boundary")

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", forbidden_provider)
    result = service.create_market_razorpay_order(market_id, environment=environment)

    assert result["result"] == "UNAVAILABLE"
    assert result["code"] == "RAZORPAY_TEST_MODE_UNAVAILABLE"
    assert result["provider_contacted"] is False
    assert service.get_market_authority(market_id) == authority_before
    assert authority_before["razorpay_order"]["state"] == "NOT_DEMONSTRATED"  # type: ignore[index]
    serialized = json.dumps(result)
    for value in environment.values():
        assert value not in serialized


def test_corrupt_persisted_plan_fails_before_provider_contact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, _ledger, _plan = _authorized(tmp_path)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_execution_authorities SET canonical_plan = ? WHERE market_id = ?",
            (b"{}", market_id),
        )

    def forbidden_provider(**_kwargs: object) -> object:
        raise AssertionError("corrupt authority must fail before provider contact")

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", forbidden_provider)
    with pytest.raises(ProductServiceError) as raised:
        service.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_conflicting_persisted_order_intent_fails_before_provider_contact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, ledger_path, _plan = _authorized(tmp_path)
    persisted_plan, decision_time = _persisted_plan(service, market_id)
    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        ledger.claim_idempotency(
            service_module.IdempotencyRecordV1(
                namespace="razorpay.order.create.v1",
                idempotency_key=persisted_plan.execution_id,
                request_fingerprint_sha256="0" * 64,
                execution_id=persisted_plan.execution_id,
                recorded_at=decision_time,
            )
        )

    def forbidden_provider(**_kwargs: object) -> object:
        raise AssertionError("conflicting create intent must fail before provider contact")

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", forbidden_provider)
    with pytest.raises(ProductServiceError) as raised:
        service.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_current_runtime_order_uses_production_boundary_and_converges_through_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, _ledger_path, projected_plan = _authorized(tmp_path)
    execution_id = str(projected_plan["execution_id"])
    amount_paise = int(projected_plan["order_amount_paise"])
    boundary = _OrderBoundary(execution_id=execution_id, amount_paise=amount_paise)
    calls: list[dict[str, object]] = []
    production_create = service_module.create_razorpay_test_order_v1

    def captured_create(**kwargs: object) -> RazorpayOrderResultV1:
        calls.append(kwargs)
        return production_create(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", captured_create)
    first = service.create_market_razorpay_order(
        market_id,
        environment=_ENVIRONMENT,
        transport=boundary,
    )
    second = service.create_market_razorpay_order(
        market_id,
        environment=_ENVIRONMENT,
        transport=boundary,
    )

    assert first["resolution"] == "CREATED"
    assert second["resolution"] == "EXISTING"
    assert first["provider_order_id"] == second["provider_order_id"] == _ORDER_ID
    for result in (first, second):
        assert result["execution_id"] == execution_id
        assert result["order_amount_paise"] == amount_paise
        assert result["currency"] == "INR"
        assert result["receipt"] == execution_id
        assert result["observation"] == "CURRENT-RUN PROVIDER OBSERVATION"
        assert result["provider_contacted"] is True
    assert boundary.post_count == 1
    assert boundary.get_count == 1
    assert len(calls) == 2
    persisted_plan, decision_time = _persisted_plan(service, market_id)
    for call in calls:
        assert call["certificate"].allocation.total_payment == persisted_plan.order_amount  # type: ignore[attr-defined]
        assert call["execution_request"].execution_id == execution_id  # type: ignore[attr-defined]
        assert call["decision_time"] == decision_time
        assert type(call["ledger"]) is SQLiteFinancialLedgerV1
        assert "amount" not in call
        assert "currency" not in call
        assert "receipt" not in call
    posted_body = next(call["body"] for call in boundary.calls if call["method"] == "POST")
    assert json.loads(posted_body) == {
        "amount": amount_paise,
        "currency": "INR",
        "partial_payment": False,
        "receipt": execution_id,
    }


def test_recovery_required_invokes_existing_get_only_recovery_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, _ledger, projected_plan = _authorized(tmp_path)
    plan, _decision_time = _persisted_plan(service, market_id)
    create_calls = 0
    recovery_calls: list[dict[str, object]] = []

    def recovery_required(**_kwargs: object) -> object:
        nonlocal create_calls
        create_calls += 1
        raise RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)

    def recovered(**kwargs: object) -> RazorpayOrderRecoveryResultV1:
        recovery_calls.append(kwargs)
        order = RazorpayOrderV1(
            execution_id=plan.execution_id,
            provider_order_id=_ORDER_ID,
            amount=plan.order_amount,
            receipt=plan.execution_id,
            status=RazorpayOrderStatusV1.CREATED,
        )
        return RazorpayOrderRecoveryResultV1(
            disposition=RazorpayOrderRecoveryDispositionV1.RECOVERED,
            execution_id=plan.execution_id,
            order_create_fingerprint_sha256=razorpay_order_create_fingerprint_v1(plan),
            order=order,
        )

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", recovery_required)
    monkeypatch.setattr(service_module, "recover_razorpay_test_order_v1", recovered)
    result = service.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)

    assert result["resolution"] == "RECOVERED"
    assert result["provider_order_id"] == _ORDER_ID
    assert result["order_amount_paise"] == projected_plan["order_amount_paise"]
    assert result["provider_contacted"] is True
    assert create_calls == 1
    assert len(recovery_calls) == 1
    assert "transport" not in recovery_calls[0]


def test_recovery_not_found_fails_without_an_invented_second_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, _ledger, _projected_plan = _authorized(tmp_path)
    plan, _decision_time = _persisted_plan(service, market_id)
    create_calls = 0
    recovery_calls = 0

    def recovery_required(**_kwargs: object) -> object:
        nonlocal create_calls
        create_calls += 1
        raise RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)

    def not_found(**_kwargs: object) -> RazorpayOrderRecoveryResultV1:
        nonlocal recovery_calls
        recovery_calls += 1
        return RazorpayOrderRecoveryResultV1(
            disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
            execution_id=plan.execution_id,
            order_create_fingerprint_sha256=razorpay_order_create_fingerprint_v1(plan),
            order=None,
        )

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", recovery_required)
    monkeypatch.setattr(service_module, "recover_razorpay_test_order_v1", not_found)
    result = service.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)

    assert result["result"] == "FAILED"
    assert result["code"] == "ORDER_RECOVERY_NOT_FOUND"
    assert result["provider_contacted"] is None
    assert create_calls == 1
    assert recovery_calls == 1


@pytest.mark.parametrize(
    "failure_code",
    (
        RazorpayOrderFailureCode.INVALID_PROVIDER_RESPONSE,
        RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH,
        RazorpayOrderFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
    ),
)
def test_provider_or_local_reference_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_code: RazorpayOrderFailureCode,
) -> None:
    service, market_id, _ledger, _plan = _authorized(tmp_path)

    def mismatched(**_kwargs: object) -> object:
        raise RazorpayOrderError(failure_code)

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", mismatched)
    result = service.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)
    assert result["result"] == "FAILED"
    assert result["code"] == failure_code.value
    assert result["provider_contacted"] is None
    assert "secret" not in json.dumps(result).lower()


@pytest.mark.parametrize(
    "failure_code",
    (
        RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
        RazorpayOrderRecoveryFailureCode.CREATE_INTENT_MISSING,
        RazorpayOrderRecoveryFailureCode.CREATE_INTENT_CONFLICT,
    ),
)
def test_recovery_local_failure_does_not_fabricate_provider_contact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_code: RazorpayOrderRecoveryFailureCode,
) -> None:
    service, market_id, _ledger, _plan = _authorized(tmp_path)

    def recovery_required(**_kwargs: object) -> object:
        raise RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)

    def ambiguous_recovery(**_kwargs: object) -> object:
        raise RazorpayOrderRecoveryError(failure_code)

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", recovery_required)
    monkeypatch.setattr(service_module, "recover_razorpay_test_order_v1", ambiguous_recovery)
    result = service.create_market_razorpay_order(market_id, environment=_ENVIRONMENT)

    assert result["result"] == "FAILED"
    assert result["code"] == failure_code.value
    assert result["provider_contacted"] is None
    assert "secret" not in json.dumps(result).lower()


def test_cold_concurrent_actions_issue_at_most_one_post_then_converge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, _ledger, projected_plan = _authorized(tmp_path)
    execution_id = str(projected_plan["execution_id"])
    amount_paise = int(projected_plan["order_amount_paise"])
    boundary = _OrderBoundary(execution_id=execution_id, amount_paise=amount_paise)
    production_create = service_module.create_razorpay_test_order_v1
    rendezvous = Barrier(2)

    def simultaneous_create(**kwargs: object) -> RazorpayOrderResultV1:
        rendezvous.wait()
        return production_create(**kwargs)  # type: ignore[arg-type]

    def safe_racing_recovery(**_kwargs: object) -> object:
        raise RazorpayOrderRecoveryError(
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED
        )

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", simultaneous_create)
    monkeypatch.setattr(service_module, "recover_razorpay_test_order_v1", safe_racing_recovery)

    def invoke() -> dict[str, object]:
        return service.create_market_razorpay_order(
            market_id,
            environment=_ENVIRONMENT,
            transport=boundary,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(executor.map(lambda _value: invoke(), range(2)))

    assert boundary.post_count == 1
    assert any(result["result"] == "SUCCESS" for result in concurrent)
    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", production_create)
    later = invoke()
    assert later["resolution"] == "EXISTING"
    assert later["provider_order_id"] == _ORDER_ID
    assert boundary.post_count == 1
    assert boundary.get_count >= 1


def test_get_reconciliation_is_read_only_and_exposes_only_persisted_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, market_id, ledger_path, projected_plan = _authorized(tmp_path)
    boundary = _OrderBoundary(
        execution_id=str(projected_plan["execution_id"]),
        amount_paise=int(projected_plan["order_amount_paise"]),
    )
    created = service.create_market_razorpay_order(
        market_id,
        environment=_ENVIRONMENT,
        transport=boundary,
    )
    assert created["resolution"] == "CREATED"
    ledger_before = ledger_path.read_bytes()

    def forbidden_provider(**_kwargs: object) -> Any:
        raise AssertionError("GET reconciliation must not invoke a provider boundary")

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", forbidden_provider)
    monkeypatch.setattr(service_module, "recover_razorpay_test_order_v1", forbidden_provider)
    authority = service.get_market_authority(market_id)

    assert ledger_path.read_bytes() == ledger_before
    persisted = authority["razorpay_order"]
    assert persisted == {
        "state": "ORDER_REFERENCE_PERSISTED",
        "provider_order_id": _ORDER_ID,
        "execution_id": projected_plan["execution_id"],
        "order_amount_paise": projected_plan["order_amount_paise"],
        "currency": "INR",
        "receipt": projected_plan["execution_id"],
        "provider_status_refreshed": False,
        "scope": "Razorpay Test Mode order creation and existing-order resolution only.",
        "limitations": (
            "This does not demonstrate payment capture, customer payment, webhook handling, "
            "transfers, settlement, refunds, fulfillment, or real-money movement."
        ),
    }
    assert boundary.post_count == 1
    assert boundary.get_count == 0


@pytest.mark.parametrize("corruption", ("duplicate", "malformed"))
def test_get_reconciliation_rejects_conflicting_or_malformed_provider_references(
    tmp_path: Path,
    corruption: str,
) -> None:
    service, market_id, ledger_path, _projected_plan = _authorized(tmp_path)
    plan, decision_time = _persisted_plan(service, market_id)
    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        ledger.claim_idempotency(
            service_module.IdempotencyRecordV1(
                namespace="razorpay.order.create.v1",
                idempotency_key=plan.execution_id,
                request_fingerprint_sha256=razorpay_order_create_fingerprint_v1(plan),
                execution_id=plan.execution_id,
                recorded_at=decision_time,
            )
        )
        ledger.record_provider_reference(
            ProviderReferenceV1(
                provider_name="razorpay",
                reference_kind="order",
                reference_id=_ORDER_ID,
                execution_id=plan.execution_id,
                recorded_at=decision_time,
            )
        )
        if corruption == "duplicate":
            ledger.record_provider_reference(
                ProviderReferenceV1(
                    provider_name="razorpay",
                    reference_kind="order",
                    reference_id="order_CLEARProductBoundary2",
                    execution_id=plan.execution_id,
                    recorded_at=decision_time,
                )
            )
    if corruption == "malformed":
        with sqlite3.connect(ledger_path) as connection:
            connection.execute(
                "UPDATE clear_provider_references_v1 SET reference_id = ? WHERE execution_id = ?",
                ("not-an-order-id", plan.execution_id),
            )

    with pytest.raises(ProductServiceError) as raised:
        service.get_market_authority(market_id)
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_tamper_control_remains_provider_free_and_endpoint_has_no_transfer_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _clock, _merchants, market_id, _product, _ledger = _closed_feasible(tmp_path)

    def forbidden_provider(**_kwargs: object) -> object:
        raise AssertionError("tamper control must remain provider-free")

    monkeypatch.setattr(service_module, "create_razorpay_test_order_v1", forbidden_provider)
    monkeypatch.setattr(service_module, "recover_razorpay_test_order_v1", forbidden_provider)
    tamper = service.test_market_authority_tamper(market_id)
    assert tamper["provider_invoked"] is False

    root = Path(__file__).resolve().parents[3]
    product_service = (root / "ui" / "product" / "service.py").read_text(encoding="utf-8")
    server = (root / "ui" / "server.py").read_text(encoding="utf-8")
    endpoint_block = server.split("razorpay_order_match =", 1)[1].split(
        "authority_tamper_match =", 1
    )[0]
    for forbidden in (
        "create_or_reconcile_razorpay_test_transfers_v1",
        "authenticate_and_record_razorpay_webhook_v1",
        "PAYMENT_CAPTURED",
    ):
        assert forbidden not in endpoint_block
    assert "create_or_reconcile_razorpay_test_transfers_v1" not in product_service
    assert "capture" not in endpoint_block


def test_browser_razorpay_action_is_explicit_empty_body_and_stale_guarded() -> None:
    root = Path(__file__).resolve().parents[3]
    script = (root / "ui" / "product_app.js").read_text(encoding="utf-8")
    markup = (root / "ui" / "index.html").read_text(encoding="utf-8")
    action = script.split('runtimeRazorpayButton.addEventListener("click"', 1)[1].split(
        "if (runtimeRazorpayCheckoutButton instanceof HTMLButtonElement)", 1
    )[0]

    assert "/authority/razorpay-order`" in action
    assert '{ method: "POST", body: "{}" }' in action
    assert "amount:" not in action
    assert "currency:" not in action
    assert "receipt:" not in action
    assert "certificate:" not in action
    assert "winner" not in action.lower()
    assert "transfer" not in action.lower()
    assert "requestGeneration !== razorpayRequestGeneration" in action
    assert "currentClearingMarketId !== marketId" in action
    assert "currentRuntimeExecutionId !== executionId" in action
    assert (
        "++razorpayRequestGeneration"
        in script.split("const resetRuntimeRazorpay = () =>", 1)[1].split(
            "const clearRuntimeAuthorityPresentation", 1
        )[0]
    )
    assert "innerHTML" not in script
    assert "Create Razorpay Test Mode order" in markup
    assert "CURRENT-RUN PROVIDER OBSERVATION" not in markup
    assert "payment capture" in markup
    assert "real-money movement" in markup
