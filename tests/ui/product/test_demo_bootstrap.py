from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clear_market.persistence import SQLiteFinancialLedgerV1
from ui.demo_bootstrap import (
    DemoBootstrapError,
    bootstrap_demo,
    financial_ledger_path_for_product_db,
)
from ui.product.service import ProductService

_BOOTSTRAP_TIME = datetime(2038, 6, 7, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _BOOTSTRAP_TIME


def _bootstrap(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    product_path = tmp_path / "product.sqlite3"
    ledger_path = financial_ledger_path_for_product_db(product_path)
    result = bootstrap_demo(product_path, clock=_clock)
    return product_path, ledger_path, result


def test_bootstrap_creates_only_the_open_authenticated_rehearsal_fixture(
    tmp_path: Path,
) -> None:
    product_path, ledger_path, output = _bootstrap(tmp_path)
    service = ProductService(product_path, clock=_clock)

    merchants = service.list_merchants()["merchants"]
    markets = service.list_markets()["markets"]
    assert isinstance(merchants, list)
    assert isinstance(markets, list)
    assert len(merchants) == 3
    assert len(markets) == 1
    assert {merchant["display_name"] for merchant in merchants} == {
        "Alpha Systems",
        "Beta Systems",
        "Gamma Systems",
    }
    assert all(merchant["product_display_name"] == "EdgeBox 32" for merchant in merchants)
    merchants_by_name = {merchant["display_name"]: merchant for merchant in merchants}
    assert {
        name: (
            merchant["merchant_sku"],
            merchant["inventory_quantity"],
        )
        for name, merchant in merchants_by_name.items()
    } == {
        "Alpha Systems": ("ALPHA-EDGE-32", 5),
        "Beta Systems": ("BETA-EDGE-32", 5),
        "Gamma Systems": ("GAMMA-EDGE-32", 5),
    }
    assert {
        (
            attribute["attribute_key"],
            attribute["value_type"],
            attribute["value"],
            attribute["provenance"],
        )
        for merchant in merchants
        for attribute in merchant["attributes"]
    } == {
        ("ram_gb", "integer", 32, "ATTESTED"),
        ("storage_gb", "integer", 1024, "ATTESTED"),
    }

    market_id = str(output["market_id"])
    snapshot = service.get_clearing_snapshot(market_id)
    assert markets[0] == {
        "market_id": market_id,
        "state": "OPEN",
        "requested_quantity": 5,
        "minimum_acceptable_quantity": 1,
        "max_winners": 2,
        "max_total_payment_paise": 500_000,
        "offer_deadline": "2038-06-08T12:00:00.000000Z",
        "submitted_offer_count": 2,
        "created_at": "2038-06-07T12:00:00.000000Z",
        "closed_at": None,
    }
    assert snapshot["result"] is None
    offers = snapshot["submitted_offers"]
    assert isinstance(offers, list)
    assert len(offers) == 2
    assert all(offer["signed"] is True and offer["authenticated"] is True for offer in offers)
    assert {
        (offer["display_name"], offer["submitted_quantity"], offer["unit_price_paise"])
        for offer in offers
    } == {
        ("Alpha Systems", 5, 45_000),
        ("Beta Systems", 5, 50_000),
    }

    with sqlite3.connect(product_path) as connection:
        economic_profiles = connection.execute(
            """
            SELECT display_name, unit_cost_basis_paise, minimum_margin_paise,
                   max_quantity_per_offer
            FROM product_merchants
            ORDER BY display_name
            """
        ).fetchall()
        result_count = connection.execute("SELECT COUNT(*) FROM product_market_results").fetchone()
        authority_count = connection.execute(
            "SELECT COUNT(*) FROM product_execution_authorities"
        ).fetchone()
    assert economic_profiles == [
        ("Alpha Systems", 40_000, 5_000, 5),
        ("Beta Systems", 45_000, 5_000, 5),
        ("Gamma Systems", 50_000, 5_000, 5),
    ]
    assert result_count == (0,)
    assert authority_count == (0,)
    assert not ledger_path.exists()
    assert output["provider_action"] == "NOT DEMONSTRATED"
    assert "winner" not in json.dumps(output).lower()


def test_real_close_and_authorization_produce_the_expected_authority(
    tmp_path: Path,
) -> None:
    product_path, ledger_path, output = _bootstrap(tmp_path)
    service = ProductService(product_path, clock=_clock)
    market_id = str(output["market_id"])

    service.close_market(market_id)
    snapshot = service.get_clearing_snapshot(market_id)
    result = snapshot["result"]
    assert isinstance(result, dict)
    assert result == {
        "allocation_status": "FEASIBLE",
        "requested_quantity": 5,
        "fulfilled_quantity": 5,
        "winner_count": 1,
        "total_payment_paise": 225_000,
        "winners": [
            {
                "merchant_id": output["merchants"][0]["merchant_id"],
                "display_name": "Alpha Systems",
            }
        ],
    }

    authority = service.get_market_authority(market_id)
    assert authority["certificate"]["allocation"]["status"] == "FEASIBLE"
    assert authority["verifier"] == {
        "verified": True,
        "failure_code": None,
        "failed_evidence_index": None,
        "truth_class": "REAL LOCAL PRODUCTION LOGIC",
    }
    assert authority["governor"] == {"state": "NOT_AUTHORIZED"}
    assert not ledger_path.exists()

    authorized = service.authorize_market_execution(market_id)
    governor = authorized["governor"]
    assert governor["state"] == "AUTHORIZED"
    plan = governor["execution_plan"]
    assert plan["execution_plan_version"] == "execution-plan-v1"
    assert plan["order_amount_paise"] == 225_000
    assert plan["provider_action"] == "NOT DEMONSTRATED"
    assert authorized["razorpay_order"]["state"] == "NOT_DEMONSTRATED"
    assert ledger_path.is_file()
    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        assert ledger.list_provider_references(str(plan["execution_id"])) == ()


def test_existing_product_db_is_refused_without_modification(tmp_path: Path) -> None:
    product_path = tmp_path / "existing.sqlite3"
    original = b"existing-product-bytes"
    product_path.write_bytes(original)
    ledger_path = financial_ledger_path_for_product_db(product_path)

    with pytest.raises(DemoBootstrapError, match="DEMO_TARGET_EXISTS") as raised:
        bootstrap_demo(product_path, clock=_clock)

    assert raised.value.code == "DEMO_TARGET_EXISTS"
    assert product_path.read_bytes() == original
    assert not ledger_path.exists()


def test_existing_financial_ledger_is_refused_without_touching_either_file(
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.sqlite3"
    ledger_path = financial_ledger_path_for_product_db(product_path)
    assert ledger_path == tmp_path / "product-financial-ledger.sqlite3"
    original = b"existing-ledger-bytes"
    ledger_path.write_bytes(original)

    with pytest.raises(DemoBootstrapError, match="DEMO_LEDGER_EXISTS") as raised:
        bootstrap_demo(product_path, clock=_clock)

    assert raised.value.code == "DEMO_LEDGER_EXISTS"
    assert not product_path.exists()
    assert ledger_path.read_bytes() == original


def test_cli_prints_one_safe_compact_json_object(tmp_path: Path) -> None:
    product_path = tmp_path / "cli-product.sqlite3"
    completed = subprocess.run(
        [sys.executable, "-m", "ui.demo_bootstrap", "--db", str(product_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.count("\n") == 1
    payload = json.loads(completed.stdout)
    assert payload == {
        "ai_action": "NOT INVOKED BY BOOTSTRAP",
        "input_evidence": "DETERMINISTIC FIXTURE",
        "market_id": payload["market_id"],
        "market_state": "OPEN",
        "merchants": payload["merchants"],
        "next_action": "CLOSE_MARKET_IN_UI",
        "product_db_path": str(product_path),
        "profile": "CLEAR_JUDGE_DEMO_V1",
        "provider_action": "NOT DEMONSTRATED",
        "runtime_logic": "REAL LOCAL PRODUCTION LOGIC",
        "submitted_offer_count": 2,
    }
    assert [merchant["display_name"] for merchant in payload["merchants"]] == [
        "Alpha Systems",
        "Beta Systems",
        "Gamma Systems",
    ]
    serialized = completed.stdout.lower()
    for forbidden in (
        "private_key",
        "key_secret",
        "api_key",
        "credential",
        "current-run provider observation",
        "winner",
        "payment capture",
        "settlement",
        "real-money movement",
    ):
        assert forbidden not in serialized


def test_cli_existing_target_failure_is_stable_and_secret_free(tmp_path: Path) -> None:
    product_path = tmp_path / "existing.sqlite3"
    original = b"leave-this-unchanged"
    product_path.write_bytes(original)

    completed = subprocess.run(
        [sys.executable, "-m", "ui.demo_bootstrap", "--db", str(product_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == '{"error":"DEMO_TARGET_EXISTS"}\n'
    assert product_path.read_bytes() == original


def test_bootstrap_source_has_no_ai_or_razorpay_invocation() -> None:
    source = Path("ui/demo_bootstrap.py").read_text(encoding="utf-8")

    for forbidden in (
        "interpret_buyer_intent_v1",
        "propose_merchant_offer_candidate_v1",
        "create_market_razorpay_order",
        "create_razorpay_test_order_v1",
        "recover_razorpay_test_order_v1",
        "create_or_reconcile_razorpay_test_transfers_v1",
    ):
        assert forbidden not in source
