from io import BytesIO
from types import MethodType

import pytest

import clear_market.payments.razorpay.orders as orders_module
from ui.server import _Handler


def _post(path: str) -> tuple[int, dict[str, object]]:
    handler = object.__new__(_Handler)
    handler.path = path
    handler.headers = {"Content-Length": "2"}  # type: ignore[assignment]
    handler.rfile = BytesIO(b"{}")
    captured: list[tuple[int, dict[str, object]]] = []

    def capture(
        _self: _Handler,
        payload: object,
        status: int = 200,
    ) -> None:
        assert type(payload) is dict
        captured.append((status, payload))

    handler._send_json = MethodType(capture, handler)  # type: ignore[method-assign]
    handler.do_POST()
    assert len(captured) == 1
    return captured[0]


def test_live_endpoint_is_narrowly_unavailable_without_credentials_while_demo_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAZORPAY_TEST_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_TEST_KEY_SECRET", raising=False)

    def reject_network(**_kwargs: object) -> tuple[int, bytes]:
        raise AssertionError("the deterministic endpoint contacted live Razorpay")

    monkeypatch.setattr(orders_module, "_https_request", reject_network)
    live_status, live = _post("/api/razorpay-test-order-evidence")
    demo_status, demo = _post("/api/authority-demo")

    assert live_status == 503
    assert live == {
        "presentation_version": "clear-razorpay-test-order-evidence-v1",
        "result": "UNAVAILABLE",
        "code": "LIVE_TEST_MODE_UNAVAILABLE",
        "message": "Server-side Razorpay Test Mode credentials are unavailable or invalid.",
        "mode": "RAZORPAY TEST MODE",
        "current_run": True,
        "authority_verified": False,
        "governor_state": "NOT REACHED",
        "execution_reserved": False,
        "provider_contacted": False,
    }
    assert demo_status == 200
    assert demo["presentation_version"] == "clear-authority-presentation-v1"
    assert demo["current_run"] == {
        "evidence_class": "REAL LOCAL PRODUCTION LOGIC",
        "ai_invoked": False,
        "razorpay_contacted": False,
        "ai_statement": "AI is not invoked by this deterministic run.",
        "razorpay_statement": "Live Razorpay was not contacted by this deterministic run.",
        "fixture_context": "Displayed input context is fixture-backed.",
    }
