from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import MethodType

import pytest

import ui.server as server_module
from clear_market.canonical.serialization import canonical_utc_datetime
from ui.server import _Handler


def _request(
    method: str,
    path: str,
    body: bytes = b"",
) -> tuple[int, dict[str, object]]:
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
    if method == "POST":
        handler.do_POST()
    else:
        handler.do_GET()
    assert len(captured) == 1
    return captured[0]


def _post(path: str, value: object | None = None) -> tuple[int, dict[str, object]]:
    body = b"" if value is None else json.dumps(value).encode("utf-8")
    return _request("POST", path, body)


def _merchant(name: str) -> dict[str, object]:
    return {
        "display_name": name,
        "product_display_name": f"{name} EdgeBox",
        "merchant_sku": f"{name.upper()}-EDGE",
        "inventory_quantity": 3,
        "unit_cost_basis_paise": 100,
        "minimum_margin_paise": 0,
        "max_quantity_per_offer": 3,
    }


def test_product_http_routes_build_and_reload_safe_runtime_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))
    merchants: list[dict[str, object]] = []
    for name in ("Alpha", "Beta", "Gamma"):
        status, merchant = _post("/api/product-v1/merchants", _merchant(name))
        assert status == 201
        merchants.append(merchant)

    deadline = canonical_utc_datetime(datetime.now(UTC) + timedelta(hours=1))
    status, market = _post(
        "/api/product-v1/markets",
        {
            "requested_quantity": 5,
            "minimum_acceptable_quantity": 5,
            "max_winners": 2,
            "max_total_payment_paise": 10_000,
            "eligible_merchant_ids": [merchant["merchant_id"] for merchant in merchants],
            "offer_deadline": deadline,
        },
    )
    assert status == 201
    market_id = market["market_id"]
    assert type(market_id) is str

    for merchant, price in zip(merchants, (500, 600, 700), strict=True):
        status, offer = _post(
            f"/api/product-v1/markets/{market_id}/offers",
            {
                "merchant_id": merchant["merchant_id"],
                "proposed_quantity": 3,
                "proposed_unit_price_paise": price,
            },
        )
        assert status == 201
        assert offer["authenticated"] is True

    close_status, closed = _post(f"/api/product-v1/markets/{market_id}/close")
    get_status, reloaded = _request("GET", f"/api/product-v1/markets/{market_id}")

    assert close_status == 200
    assert get_status == 200
    assert reloaded == closed
    assert closed["certificate_verified"] is True
    assert closed["total_payment_paise"] == 2_700
    assert "allocated_quantity" not in json.dumps(closed)
    assert "private" not in json.dumps([*merchants, market, closed]).lower()


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b'{"display_name":"A","display_name":"B"}',
        json.dumps({**_merchant("Bad"), "inventory_quantity": True}).encode(),
        json.dumps({**_merchant("Bad"), "unit_cost_basis_paise": 1.5}).encode(),
        json.dumps({**_merchant("Bad"), "certificate_verified": True}).encode(),
    ],
)
def test_product_http_strictly_rejects_malformed_coerced_or_authority_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))

    status, payload = _request("POST", "/api/product-v1/merchants", body)

    assert status == 400
    assert payload == {
        "error": {"code": "INVALID_REQUEST", "message": "Product request failed closed."}
    }


def test_product_http_rejects_invalid_uuid_and_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))
    merchants = []
    for name in ("One", "Two"):
        _, merchant = _post("/api/product-v1/merchants", _merchant(name))
        merchants.append(merchant)

    timestamp_status, _ = _post(
        "/api/product-v1/markets",
        {
            "requested_quantity": 2,
            "minimum_acceptable_quantity": 2,
            "max_winners": 2,
            "max_total_payment_paise": 10_000,
            "eligible_merchant_ids": [merchant["merchant_id"] for merchant in merchants],
            "offer_deadline": "2030-01-01T00:00:00+00:00",
        },
    )
    uuid_status, _ = _request("GET", "/api/product-v1/markets/not-a-uuid")

    assert timestamp_status == 400
    assert uuid_status == 400


def test_product_request_size_bound_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))
    body = b"x" * (1024 * 1024 + 1)

    status, payload = _request("POST", "/api/product-v1/merchants", body)

    assert status == 413
    assert payload == {"error": "request too large"}


def test_merchant_discovery_and_buyer_draft_routes_are_safe_and_non_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))
    for name in ("One", "Two"):
        status, _ = _post("/api/product-v1/merchants", _merchant(name))
        assert status == 201

    list_status, merchant_list = _request("GET", "/api/product-v1/merchants")
    assert list_status == 200
    merchants = merchant_list["merchants"]
    assert type(merchants) is list and len(merchants) == 2
    assert "private" not in json.dumps(merchant_list).lower()
    deadline = canonical_utc_datetime(datetime.now(UTC) + timedelta(hours=1))
    draft_status, draft = _post(
        "/api/product-v1/buyer-drafts",
        {
            "buyer_text": "Buy two runtime products for no more than INR 100.",
            "eligible_merchant_ids": [merchant["merchant_id"] for merchant in merchants],
            "offer_deadline": deadline,
        },
    )
    assert draft_status == 201
    assert draft["state"] == "DRAFT"
    assert draft["authority"] == "ADVISORY_ONLY"
    market_id = draft["market_id"]
    assert type(market_id) is str
    get_status, _ = _request("GET", f"/api/product-v1/markets/{market_id}")
    assert get_status == 404


def test_buyer_interpret_route_is_truthfully_unavailable_and_shares_live_ai_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))
    for name in (
        "CLEAR_AI_BASE_URL",
        "CLEAR_AI_API_KEY",
        "CLEAR_AI_PROVIDER_NAME",
        "CLEAR_AI_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)
    merchants = []
    for name in ("One", "Two"):
        _, merchant = _post("/api/product-v1/merchants", _merchant(name))
        merchants.append(merchant)
    _, draft = _post(
        "/api/product-v1/buyer-drafts",
        {
            "buyer_text": "Buy two products within a 10,000 paise budget.",
            "eligible_merchant_ids": [merchant["merchant_id"] for merchant in merchants],
            "offer_deadline": canonical_utc_datetime(datetime.now(UTC) + timedelta(hours=1)),
        },
    )
    market_id = draft["market_id"]

    unavailable_status, unavailable = _post(
        f"/api/product-v1/buyer-drafts/{market_id}/interpret", {}
    )
    assert unavailable_status == 503
    assert unavailable["code"] == "LIVE_AI_UNAVAILABLE"
    assert unavailable["provider_invoked"] is False

    assert server_module._LIVE_AI_EVIDENCE_LOCK.acquire(blocking=False)
    try:
        busy_status, busy = _post(f"/api/product-v1/buyer-drafts/{market_id}/interpret", {})
    finally:
        server_module._LIVE_AI_EVIDENCE_LOCK.release()
    assert busy_status == 409
    assert busy["code"] == "LIVE_AI_BUSY"
    assert busy["provider_invoked"] is False


def test_buyer_routes_reject_client_supplied_authority_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLEAR_PRODUCT_DB_PATH", str(tmp_path / "product.sqlite3"))
    merchants = [_post("/api/product-v1/merchants", _merchant(name))[1] for name in ("One", "Two")]
    deadline = canonical_utc_datetime(datetime.now(UTC) + timedelta(hours=1))
    draft_input = {
        "buyer_text": "Buy two runtime products.",
        "eligible_merchant_ids": [merchant["merchant_id"] for merchant in merchants],
        "offer_deadline": deadline,
    }

    draft_status, _ = _post(
        "/api/product-v1/buyer-drafts",
        {**draft_input, "mechanism_version": "client-chosen"},
    )
    assert draft_status == 400
    _, draft = _post("/api/product-v1/buyer-drafts", draft_input)
    market_id = draft["market_id"]

    interpret_status, _ = _post(
        f"/api/product-v1/buyer-drafts/{market_id}/interpret",
        {"market_id": market_id, "authority": "AUTHORITATIVE"},
    )
    freeze_status, _ = _post(
        f"/api/product-v1/buyer-drafts/{market_id}/freeze",
        {"buyer_policy_frozen": True},
    )

    assert interpret_status == 400
    assert freeze_status == 400
    market_status, _ = _request("GET", f"/api/product-v1/markets/{market_id}")
    assert market_status == 404
