import json
from io import BytesIO
from types import MethodType

import pytest

import clear_market.payments.razorpay.orders as orders_module
import ui.server as server_module
from ui.server import _Handler


def _post(path: str, body: bytes = b"{}") -> tuple[int, dict[str, object]]:
    handler = object.__new__(_Handler)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body))}  # type: ignore[assignment]
    handler.rfile = BytesIO(body)
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


def test_ai_endpoints_are_unavailable_without_config_while_existing_routes_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLEAR_AI_BASE_URL",
        "CLEAR_AI_API_KEY",
        "CLEAR_AI_PROVIDER_NAME",
        "CLEAR_AI_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)

    merchant_status, merchant = _post("/api/ai-merchant-proposal-evidence")
    explanation_status, explanation = _post("/api/ai-certificate-explanation-evidence")
    demo_status, demo = _post("/api/authority-demo")

    assert merchant_status == 503
    assert merchant["code"] == "LIVE_AI_UNAVAILABLE"
    assert merchant["provider_invoked"] is False
    assert explanation_status == 503
    assert explanation["code"] == "LIVE_AI_UNAVAILABLE"
    assert explanation["provider_invoked"] is False
    assert demo_status == 200
    assert demo["presentation_version"] == "clear-authority-presentation-v1"


@pytest.mark.parametrize(
    ("path", "builder_name"),
    [
        ("/api/ai-merchant-proposal-evidence", "build_ai_merchant_proposal_evidence"),
        (
            "/api/ai-certificate-explanation-evidence",
            "build_ai_certificate_explanation_evidence",
        ),
    ],
)
def test_ai_endpoints_ignore_browser_supplied_authority_and_call_builder_without_arguments(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    builder_name: str,
) -> None:
    calls = 0

    def builder() -> dict[str, object]:
        nonlocal calls
        calls += 1
        unavailable = (
            server_module.merchant_unavailable_presentation
            if "merchant" in path
            else server_module.explanation_unavailable_presentation
        )
        return unavailable("LIVE_AI_UNAVAILABLE", "Server-owned inputs only.")

    monkeypatch.setattr(server_module, builder_name, builder)
    body = json.dumps(
        {
            "buyer_policy": {"forged": True},
            "certificate": {"forged": True},
            "governor": "AUTHORIZED",
        }
    ).encode()

    status, result = _post(path, body)

    assert status == 503
    assert result["code"] == "LIVE_AI_UNAVAILABLE"
    assert calls == 1


def test_one_shared_server_lock_refuses_both_ai_endpoints_concurrently() -> None:
    assert server_module._LIVE_AI_EVIDENCE_LOCK.acquire(blocking=False)
    try:
        merchant_status, merchant = _post("/api/ai-merchant-proposal-evidence")
        explanation_status, explanation = _post("/api/ai-certificate-explanation-evidence")
    finally:
        server_module._LIVE_AI_EVIDENCE_LOCK.release()

    assert merchant_status == 409
    assert merchant["code"] == "LIVE_AI_BUSY"
    assert merchant["provider_invoked"] is False
    assert explanation_status == 409
    assert explanation["code"] == "LIVE_AI_BUSY"
    assert explanation["provider_invoked"] is False
