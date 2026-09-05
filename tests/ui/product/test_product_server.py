from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import MethodType

import pytest

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
