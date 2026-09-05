from __future__ import annotations

import hashlib
import hmac
import json
from io import BytesIO
from pathlib import Path
from types import MethodType

import pytest

import ui.server as server_module
from clear_market.payments.razorpay import RazorpayWebhookFailureCode
from clear_market.persistence import SQLiteFinancialLedgerV1
from ui.product.service import ProductService

from .test_authority_workspace import _closed_feasible
from .test_razorpay_order_boundary import _ENVIRONMENT, _ORDER_ID, _OrderBoundary

_WEBHOOK_SECRET = "product-lifecycle-webhook-secret"
_ACCOUNT_ID = "acc_CLEARPRIMARY01"
_PAYMENT_ID = "pay_CLEARLifecycle1"
_EVENT_ID = "product-lifecycle-event-1"
_EVENT_CREATED_AT = 1_788_262_200
_PAYMENT_CREATED_AT = 1_788_262_190


def _webhook_body(
    *,
    event_type: str = "payment.captured",
    amount: int = 2_700,
    account_id: str = _ACCOUNT_ID,
    payment_id: str = _PAYMENT_ID,
    order_id: str = _ORDER_ID,
) -> bytes:
    status, captured = {
        "payment.authorized": ("authorized", False),
        "payment.captured": ("captured", True),
        "payment.failed": ("failed", False),
    }[event_type]
    payload = {
        "account_id": account_id,
        "contains": ["payment"],
        "created_at": _EVENT_CREATED_AT,
        "entity": "event",
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "amount": amount,
                    "captured": captured,
                    "created_at": _PAYMENT_CREATED_AT,
                    "currency": "INR",
                    "entity": "payment",
                    "id": payment_id,
                    "order_id": order_id,
                    "status": status,
                }
            }
        },
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _signature(raw_body: bytes) -> str:
    return hmac.new(_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()


def _authorized_order(
    tmp_path: Path,
) -> tuple[ProductService, str, dict[str, object], Path]:
    service, _clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)
    authority = service.authorize_market_execution(market_id)
    plan = authority["governor"]["execution_plan"]  # type: ignore[index]
    assert isinstance(plan, dict)
    boundary = _OrderBoundary(
        execution_id=str(plan["execution_id"]),
        amount_paise=int(plan["order_amount_paise"]),
    )
    order = service.create_market_razorpay_order(
        market_id,
        environment=_ENVIRONMENT,
        transport=boundary,
    )
    assert order["result"] == "SUCCESS"
    assert product_path.exists()
    return service, market_id, plan, ledger_path


def _request(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    handler = object.__new__(server_module._Handler)
    handler.path = path
    handler.headers = {
        "Content-Length": str(len(body)),
        **(headers or {}),
    }  # type: ignore[assignment]
    handler.rfile = BytesIO(body)
    captured: list[tuple[int, dict[str, object]]] = []

    def capture(
        _self: server_module._Handler,
        payload: object,
        status: int = 200,
    ) -> None:
        assert type(payload) is dict
        captured.append((status, payload))

    handler._send_json = MethodType(capture, handler)  # type: ignore[method-assign]
    if method == "POST":
        handler.do_POST()
    else:
        handler.do_GET()
    assert len(captured) == 1
    return captured[0]


def _webhook_environment() -> dict[str, str]:
    return {
        **_ENVIRONMENT,
        "RAZORPAY_TEST_WEBHOOK_SECRET": _WEBHOOK_SECRET,
        "RAZORPAY_TEST_ACCOUNT_ID": _ACCOUNT_ID,
    }


def test_order_success_exposes_only_safe_checkout_metadata(tmp_path: Path) -> None:
    service, market_id, plan, _ledger_path = _authorized_order(tmp_path)
    boundary = _OrderBoundary(
        execution_id=str(plan["execution_id"]),
        amount_paise=int(plan["order_amount_paise"]),
    )
    result = service.create_market_razorpay_order(
        market_id,
        environment=_ENVIRONMENT,
        transport=boundary,
    )

    checkout = result["checkout"]
    assert checkout == {
        "key_id": _ENVIRONMENT["RAZORPAY_TEST_KEY_ID"],
        "provider_order_id": _ORDER_ID,
        "amount_paise": plan["order_amount_paise"],
        "currency": "INR",
        "execution_id": plan["execution_id"],
    }
    assert result["order_amount_paise"] == plan["order_amount_paise"]
    assert _ENVIRONMENT["RAZORPAY_TEST_KEY_SECRET"] not in json.dumps(result)


def test_payment_state_replay_covers_authorized_captured_failed_and_duplicate(
    tmp_path: Path,
) -> None:
    service, market_id, plan, ledger_path = _authorized_order(tmp_path)
    environment = _webhook_environment()
    amount = int(plan["order_amount_paise"])

    authorized = service.record_razorpay_webhook(
        _webhook_body(event_type="payment.authorized", amount=amount),
        signature_header=_signature(_webhook_body(event_type="payment.authorized", amount=amount)),
        event_id_header="product-lifecycle-authorized",
        environment=environment,
    )
    assert authorized["result"] == "SUCCESS"
    assert authorized["payment_state"] == "PAYMENT_AUTHORIZED"
    assert authorized["market_id"] == market_id

    captured_body = _webhook_body(amount=amount)
    captured = service.record_razorpay_webhook(
        captured_body,
        signature_header=_signature(captured_body),
        event_id_header=_EVENT_ID,
        environment=environment,
    )
    duplicate = service.record_razorpay_webhook(
        captured_body,
        signature_header=_signature(captured_body),
        event_id_header=_EVENT_ID,
        environment=environment,
    )
    assert captured["payment_state"] == "PAYMENT_CAPTURED"
    assert captured["webhook_disposition"] == "RECORDED"
    assert duplicate["payment_state"] == "PAYMENT_CAPTURED"
    assert duplicate["webhook_disposition"] == "DUPLICATE"

    with service.store.connection():
        assert ledger_path.is_file()
    from clear_market.persistence import SQLiteFinancialLedgerV1

    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        assert len(ledger.list_events(str(plan["execution_id"]))) == 2

    failed_path = tmp_path / "failed"
    failed_path.mkdir()
    failed_service, failed_market_id, failed_plan, _failed_ledger = _authorized_order(failed_path)
    failed_body = _webhook_body(
        event_type="payment.failed",
        amount=int(failed_plan["order_amount_paise"]),
        payment_id="pay_CLEARLifecycle2",
    )
    failed = failed_service.record_razorpay_webhook(
        failed_body,
        signature_header=_signature(failed_body),
        event_id_header="product-lifecycle-failed",
        environment=environment,
    )
    assert failed["market_id"] == failed_market_id
    assert failed["payment_state"] == "PAYMENT_FAILED_OBSERVED"


def test_authenticated_mismatch_and_account_mismatch_never_report_capture(
    tmp_path: Path,
) -> None:
    service, market_id, plan, _ledger_path = _authorized_order(tmp_path)
    environment = _webhook_environment()
    wrong_amount_body = _webhook_body(amount=int(plan["order_amount_paise"]) + 1)
    wrong_amount = service.record_razorpay_webhook(
        wrong_amount_body,
        signature_header=_signature(wrong_amount_body),
        event_id_header="product-lifecycle-wrong-amount",
        environment=environment,
    )
    assert wrong_amount["result"] == "FAILED"
    assert wrong_amount["code"] == "PAYMENT_ECONOMIC_MISMATCH"
    assert wrong_amount.get("payment_state") != "PAYMENT_CAPTURED"

    account_body = _webhook_body(
        amount=int(plan["order_amount_paise"]),
        account_id="acc_CLEAROTHER01",
        payment_id="pay_CLEARLifecycle3",
    )
    account = service.record_razorpay_webhook(
        account_body,
        signature_header=_signature(account_body),
        event_id_header="product-lifecycle-account-mismatch",
        environment=environment,
    )
    assert account["result"] == "FAILED"
    assert account["code"] == RazorpayWebhookFailureCode.ACCOUNT_MISMATCH.value

    state = service.get_market_razorpay_payment_state(
        market_id,
        environment=environment,
    )
    assert state["result"] == "FAILED"
    assert state.get("payment_state") != "PAYMENT_CAPTURED"


def test_unknown_provider_order_fails_without_persisting_webhook_facts(
    tmp_path: Path,
) -> None:
    service, market_id, plan, ledger_path = _authorized_order(tmp_path)
    execution_id = str(plan["execution_id"])
    authority_before = service.get_market_authority(market_id)
    unknown_order_id = "order_CLEARUnknownOrder1"
    body = _webhook_body(
        amount=int(plan["order_amount_paise"]),
        order_id=unknown_order_id,
        payment_id="pay_CLEARUnknownOrder1",
    )

    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        references_before = ledger.list_provider_references(execution_id)
        events_before = ledger.list_events(execution_id)

    result = service.record_razorpay_webhook(
        body,
        signature_header=_signature(body),
        event_id_header="product-lifecycle-unknown-order",
        environment=_webhook_environment(),
    )

    assert result["result"] == "FAILED"
    assert result["code"] == RazorpayWebhookFailureCode.UNKNOWN_ORDER_REFERENCE.value
    assert result.get("payment_state") != "PAYMENT_CAPTURED"

    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        references_after = ledger.list_provider_references(execution_id)
        events_after = ledger.list_events(execution_id)

    assert references_after == references_before
    assert events_after == events_before
    assert all(reference.reference_id != unknown_order_id for reference in references_after)
    assert service.get_market_authority(market_id) == authority_before


def test_payment_state_get_endpoint_and_webhook_route_preserve_server_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_path = tmp_path / "product.sqlite3"
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(product_path))
    service, market_id, plan, _ledger_path = _authorized_order(tmp_path)
    environment = _webhook_environment()
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    body = _webhook_body(amount=int(plan["order_amount_paise"]))
    status, payload = _request(
        "POST",
        "/api/product-v1/razorpay/webhook",
        body,
        headers={
            "X-Razorpay-Signature": _signature(body),
            "x-razorpay-event-id": "product-lifecycle-route-event",
        },
    )
    assert status == 200
    assert payload["payment_state"] == "PAYMENT_CAPTURED"
    assert payload["market_id"] == market_id

    get_status, state = _request(
        "GET",
        f"/api/product-v1/markets/{market_id}/authority/razorpay-payment-state",
    )
    assert get_status == 200
    assert state["payment_state"] == "PAYMENT_CAPTURED"
    assert state["execution_id"] == plan["execution_id"]

    injected_body = json.dumps(
        {
            "execution_id": "client",
            "amount": 1,
            "captured": True,
            "payment_id": "pay_client",
        },
        separators=(",", ":"),
    ).encode()
    injected_status, injected_payload = _request(
        "POST",
        "/api/product-v1/razorpay/webhook",
        injected_body,
        headers={
            "X-Razorpay-Signature": _signature(injected_body),
            "x-razorpay-event-id": "product-lifecycle-injected",
        },
    )
    assert injected_status != 200
    assert injected_payload["result"] != "SUCCESS"
    assert (
        service.get_market_razorpay_payment_state(
            market_id,
            environment=environment,
        )["payment_state"]
        == "PAYMENT_CAPTURED"
    )


def test_webhook_configuration_and_hmac_fail_closed(tmp_path: Path) -> None:
    service, _market_id, plan, _ledger_path = _authorized_order(tmp_path)
    body = _webhook_body(amount=int(plan["order_amount_paise"]))
    missing = service.record_razorpay_webhook(
        body,
        signature_header=_signature(body),
        event_id_header="missing-config",
        environment={"RAZORPAY_TEST_KEY_ID": "test"},
    )
    assert missing["result"] == "UNAVAILABLE"
    assert missing["payment_state"] == "NOT AVAILABLE"

    bad_hmac = service.record_razorpay_webhook(
        body,
        signature_header="0" * 64,
        event_id_header="bad-hmac",
        environment=_webhook_environment(),
    )
    assert bad_hmac["result"] == "FAILED"
    assert bad_hmac["code"] == RazorpayWebhookFailureCode.INVALID_SIGNATURE.value
