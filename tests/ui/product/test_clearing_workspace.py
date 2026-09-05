from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import ui.product.service as service_module
from clear_market.ai import (
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseV1,
)
from clear_market.canonical.serialization import canonical_utc_datetime
from ui.product.models import (
    CreateBuyerDraftRequest,
    CreateMarketRequest,
    CreateMerchantAttributeRequest,
    CreateMerchantRequest,
    SubmitOfferRequest,
)
from ui.product.service import ProductErrorCode, ProductService, ProductServiceError

_AI_ENVIRONMENT = {
    "CLEAR_AI_BASE_URL": "https://gateway.example/v1",
    "CLEAR_AI_API_KEY": "controlled-test-secret",
    "CLEAR_AI_PROVIDER_NAME": "controlled-provider",
    "CLEAR_AI_MODELS": "controlled-model",
}


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2034, 1, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _Provider:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.calls: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        self.calls.append(request)
        return AIProviderResponseV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            finish_reason=AIProviderFinishReason.COMPLETED,
            output_text=json.dumps(self.output),
        )


def _merchant_request(
    name: str,
    *,
    inventory: int = 3,
    attributes: list[CreateMerchantAttributeRequest] | None = None,
) -> CreateMerchantRequest:
    return CreateMerchantRequest(
        display_name=f"{name} Compute",
        product_display_name=f"{name} EdgeBox",
        merchant_sku=f"{name.upper()}-EDGE",
        inventory_quantity=inventory,
        unit_cost_basis_paise=100,
        minimum_margin_paise=0,
        max_quantity_per_offer=inventory,
        attributes=[] if attributes is None else attributes,
    )


def _merchants(service: ProductService) -> dict[str, str]:
    return {
        name: str(service.create_merchant(_merchant_request(name))["merchant_id"])
        for name in ("Alpha", "Beta", "Gamma")
    }


def _market(
    service: ProductService,
    clock: _Clock,
    merchant_ids: list[str],
    *,
    requested: int = 5,
    minimum: int = 5,
    max_winners: int = 2,
) -> str:
    created = service.create_market(
        CreateMarketRequest(
            requested_quantity=requested,
            minimum_acceptable_quantity=minimum,
            max_winners=max_winners,
            max_total_payment_paise=10_000,
            eligible_merchant_ids=merchant_ids,
            offer_deadline=canonical_utc_datetime(clock.now + timedelta(hours=1)),
        )
    )
    return str(created["market_id"])


def _offer(
    service: ProductService,
    market_id: str,
    merchant_id: str,
    *,
    quantity: int = 3,
    price: int,
) -> dict[str, object]:
    return service.submit_offer(
        market_id,
        SubmitOfferRequest(
            merchant_id=merchant_id,
            proposed_quantity=quantity,
            proposed_unit_price_paise=price,
        ),
    )


def _open_market_with_offers(tmp_path: Path) -> tuple[ProductService, _Clock, dict[str, str], str]:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = _market(service, clock, list(merchants.values()))
    for name, price in (("Alpha", 500), ("Beta", 600), ("Gamma", 700)):
        _offer(service, market_id, merchants[name], price=price)
    return service, clock, merchants, market_id


def test_market_discovery_is_persisted_ordered_and_keeps_closed_markets(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    path = tmp_path / "product.sqlite3"
    service = ProductService(path, clock=clock)
    merchants = _merchants(service)
    first = _market(service, clock, list(merchants.values()))
    clock.now += timedelta(minutes=1)
    second = _market(service, clock, list(merchants.values()))
    _offer(service, first, merchants["Alpha"], price=500)
    service.close_market(first)

    discovered = ProductService(path, clock=clock).list_markets()

    assert [value["market_id"] for value in discovered["markets"]] == [first, second]
    assert [value["state"] for value in discovered["markets"]] == ["CLOSED", "OPEN"]
    assert discovered["markets"][0]["submitted_offer_count"] == 1
    assert discovered["markets"][0]["closed_at"] is not None
    assert discovered["markets"][1]["closed_at"] is None
    assert set(discovered["markets"][0]) == {
        "market_id",
        "state",
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "max_total_payment_paise",
        "offer_deadline",
        "submitted_offer_count",
        "created_at",
        "closed_at",
    }


def test_open_snapshot_exposes_exact_policy_and_only_persisted_submitted_offers(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = _market(service, clock, list(merchants.values()))
    submitted = _offer(service, market_id, merchants["Alpha"], price=525)
    with service.store.connection() as connection:
        alpha = service.store.get_merchant(connection, merchants["Alpha"])
    assert alpha is not None

    snapshot = service.get_clearing_snapshot(market_id)

    assert snapshot["market"] == {
        "market_id": market_id,
        "state": "OPEN",
        "requested_quantity": 5,
        "minimum_acceptable_quantity": 5,
        "max_winners": 2,
        "max_total_payment_paise": 10_000,
        "offer_deadline": canonical_utc_datetime(clock.now + timedelta(hours=1)),
        "hard_constraints": [],
        "soft_preferences": [],
    }
    assert snapshot["result"] is None
    assert snapshot["submitted_offers"] == [
        {
            "offer_id": submitted["offer_id"],
            "merchant_id": merchants["Alpha"],
            "display_name": "Alpha Compute",
            "sku_id": alpha.sku_id,
            "merchant_sku": "ALPHA-EDGE",
            "product_display_name": "Alpha EdgeBox",
            "submitted_quantity": 3,
            "unit_price_paise": 525,
            "received_at": submitted["received_at"],
            "signed": True,
            "authenticated": True,
            "submitted": True,
        }
    ]


def test_snapshot_reauthenticates_canonical_offer_and_rejects_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _clock, _merchants_by_name, market_id = _open_market_with_offers(tmp_path)
    calls = 0
    original = service_module.verify_canonical_signed_merchant_offer_v2

    def counted(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "verify_canonical_signed_merchant_offer_v2", counted)
    service.get_clearing_snapshot(market_id)
    assert calls == 3

    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_offers SET canonical_signed_offer = ? WHERE market_id = ?",
            (b"{}", market_id),
        )
    with pytest.raises(ProductServiceError) as raised:
        service.get_clearing_snapshot(market_id)
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_snapshot_rejects_signed_offer_scalar_mismatch(tmp_path: Path) -> None:
    service, _clock, merchants, market_id = _open_market_with_offers(tmp_path)
    with service.store.connection(write=True) as connection:
        connection.execute(
            """
            UPDATE product_offers SET proposed_unit_price_paise = proposed_unit_price_paise + 1
            WHERE market_id = ? AND merchant_id = ?
            """,
            (market_id, merchants["Alpha"]),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_clearing_snapshot(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_proposed_and_no_offer_candidates_do_not_enter_clearing_snapshot(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = _market(service, clock, list(merchants.values()))
    alpha_sku = next(
        value["merchant_sku"]
        for value in service.list_merchants()["merchants"]
        if value["merchant_id"] == merchants["Alpha"]
    )
    assert alpha_sku == "ALPHA-EDGE"
    with service.store.connection() as connection:
        alpha = service.store.get_merchant(connection, merchants["Alpha"])
    assert alpha is not None
    proposed = _Provider(
        {
            "schema_version": "1",
            "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
            "decision": "OFFER",
            "lines": [
                {
                    "schema_version": "1",
                    "merchant_offer_proposal_line_version": "merchant-offer-proposal-line-v1",
                    "sku_id": alpha.sku_id,
                    "proposed_quantity": 2,
                    "proposed_unit_price_paise": 500,
                }
            ],
        }
    )
    no_offer = _Provider(
        {
            "schema_version": "1",
            "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
            "decision": "NO_OFFER",
            "lines": [],
        }
    )
    service.propose_merchant_offer(
        merchants["Alpha"], market_id, environment=_AI_ENVIRONMENT, provider=proposed
    )
    service.propose_merchant_offer(
        merchants["Beta"], market_id, environment=_AI_ENVIRONMENT, provider=no_offer
    )
    submitted = _offer(service, market_id, merchants["Gamma"], price=700)

    snapshot = service.get_clearing_snapshot(market_id)

    assert [value["offer_id"] for value in snapshot["submitted_offers"]] == [submitted["offer_id"]]
    assert [value["merchant_id"] for value in snapshot["submitted_offers"]] == [merchants["Gamma"]]


def test_discovery_snapshot_and_close_never_touch_ai_or_ai_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _clock, _merchants_by_name, market_id = _open_market_with_offers(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("clearing touched AI")

    for name in (
        "interpret_buyer_intent_v1",
        "propose_merchant_offer_candidate_v1",
        "configured_product_ai",
        "configured_external_product_ai",
        "OneCallProvider",
    ):
        monkeypatch.setattr(service_module, name, forbidden)
    for name in _AI_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    assert len(service.list_markets()["markets"]) == 1
    assert service.get_clearing_snapshot(market_id)["market"]["state"] == "OPEN"
    assert service.close_market(market_id)["market_state"] == "CLOSED"
    assert service.get_clearing_snapshot(market_id)["market"]["state"] == "CLOSED"


def test_closed_feasible_snapshot_projects_server_resolved_winners_and_survives_reopen(
    tmp_path: Path,
) -> None:
    service, clock, merchants, market_id = _open_market_with_offers(tmp_path)
    service.close_market(market_id)

    snapshot = ProductService(service.store.path, clock=clock).get_clearing_snapshot(market_id)

    assert snapshot["market"]["state"] == "CLOSED"
    assert snapshot["result"]["allocation_status"] == "FEASIBLE"
    assert snapshot["result"]["requested_quantity"] == 5
    assert snapshot["result"]["fulfilled_quantity"] == 5
    assert snapshot["result"]["winner_count"] == 2
    assert snapshot["result"]["total_payment_paise"] == 2_700
    assert {
        (value["merchant_id"], value["display_name"]) for value in snapshot["result"]["winners"]
    } == {
        (merchants["Alpha"], "Alpha Compute"),
        (merchants["Beta"], "Beta Compute"),
    }
    serialized = json.dumps(snapshot)
    for forbidden in (
        "certificate_id",
        "certificate_digest",
        "canonical_certificate",
        "signature_hex",
        "signing_private_key_hex",
        "unit_cost_basis_paise",
        "minimum_margin_paise",
    ):
        assert forbidden not in serialized


def test_closed_infeasible_snapshot_is_exact_zero_outcome(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = _market(service, clock, list(merchants.values()))
    _offer(service, market_id, merchants["Alpha"], quantity=3, price=500)
    service.close_market(market_id)

    snapshot = service.get_clearing_snapshot(market_id)

    assert snapshot["result"] == {
        "allocation_status": "INFEASIBLE",
        "requested_quantity": 5,
        "fulfilled_quantity": 0,
        "winner_count": 0,
        "total_payment_paise": 0,
        "winners": [],
    }


def test_runtime_price_change_changes_production_winners_and_total(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    outcomes = []
    for beta_price in (600, 1_000):
        market_id = _market(service, clock, list(merchants.values()))
        for name, price in (("Alpha", 500), ("Beta", beta_price), ("Gamma", 700)):
            _offer(service, market_id, merchants[name], price=price)
        service.close_market(market_id)
        outcomes.append(service.get_clearing_snapshot(market_id)["result"])

    assert {value["merchant_id"] for value in outcomes[0]["winners"]} == {
        merchants["Alpha"],
        merchants["Beta"],
    }
    assert outcomes[0]["total_payment_paise"] == 2_700
    assert {value["merchant_id"] for value in outcomes[1]["winners"]} == {
        merchants["Alpha"],
        merchants["Gamma"],
    }
    assert outcomes[1]["total_payment_paise"] == 2_900


def test_hard_attribute_constraint_excludes_cheaper_nonqualifying_offer(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    cheap = service.create_merchant(
        _merchant_request(
            "Cheap",
            attributes=[
                CreateMerchantAttributeRequest(
                    attribute_key="ram_gb",
                    value_type="integer",
                    value=8,
                    provenance="ATTESTED",
                )
            ],
        )
    )
    qualifying = service.create_merchant(
        _merchant_request(
            "Qualifying",
            attributes=[
                CreateMerchantAttributeRequest(
                    attribute_key="ram_gb",
                    value_type="integer",
                    value=16,
                    provenance="ATTESTED",
                )
            ],
        )
    )
    merchant_ids = [str(cheap["merchant_id"]), str(qualifying["merchant_id"])]
    deadline = canonical_utc_datetime(clock.now + timedelta(hours=1))
    draft = service.create_buyer_draft(
        CreateBuyerDraftRequest(
            buyer_text="Buy three systems with at least 16 GB RAM from one supplier.",
            eligible_merchant_ids=merchant_ids,
            offer_deadline=deadline,
        )
    )
    provider = _Provider(
        {
            "schema_version": "1",
            "buyer_intent_candidate_version": "buyer-intent-candidate-v1",
            "requested_quantity": 3,
            "minimum_acceptable_quantity": 3,
            "max_winners": 1,
            "max_total_payment_paise": 10_000,
            "hard_constraints": [
                {
                    "schema_version": "1",
                    "buyer_intent_rule_candidate_version": "buyer-intent-rule-candidate-v1",
                    "rule_id": "a1000000-0000-4000-8000-000000000010",
                    "attribute_key": "ram_gb",
                    "operator": "gte",
                    "value_type": "integer",
                    "value": 16,
                    "allowed_provenance": ["ATTESTED"],
                }
            ],
            "soft_preferences": [],
        }
    )
    market_id = str(draft["market_id"])
    interpreted = service.interpret_buyer_draft(
        market_id,
        environment=_AI_ENVIRONMENT,
        provider=provider,
    )
    assert interpreted["result"] == "SUCCESS"
    service.freeze_buyer_draft(market_id)
    _offer(service, market_id, merchant_ids[0], price=200)
    _offer(service, market_id, merchant_ids[1], price=500)
    service.close_market(market_id)

    snapshot = service.get_clearing_snapshot(market_id)

    assert snapshot["market"]["hard_constraints"][0]["attribute_key"] == "ram_gb"
    assert snapshot["result"]["winners"] == [
        {"merchant_id": merchant_ids[1], "display_name": "Qualifying Compute"}
    ]
    assert snapshot["result"]["total_payment_paise"] == 1_500


def test_closed_snapshot_rejects_malformed_or_mismatched_persisted_result(
    tmp_path: Path,
) -> None:
    service, _clock, _merchants_by_name, market_id = _open_market_with_offers(tmp_path)
    service.close_market(market_id)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_market_results SET total_payment_paise = 1 WHERE market_id = ?",
            (market_id,),
        )
    with pytest.raises(ProductServiceError) as mismatch:
        service.get_clearing_snapshot(market_id)
    assert mismatch.value.code is ProductErrorCode.PERSISTED_DATA_INVALID

    with service.store.connection(write=True) as connection:
        connection.execute(
            """
            UPDATE product_market_results
            SET canonical_certificate = ?, total_payment_paise = 2700
            WHERE market_id = ?
            """,
            (b"{}", market_id),
        )
    with pytest.raises(ProductServiceError) as malformed:
        service.get_clearing_snapshot(market_id)
    assert malformed.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


@pytest.mark.parametrize(
    "persisted_winner_ids",
    ("{", "{}", '["merchant-id",1]'),
    ids=("malformed", "object", "non-string-member"),
)
def test_closed_snapshot_maps_invalid_persisted_winner_ids_to_stable_error(
    tmp_path: Path,
    persisted_winner_ids: str,
) -> None:
    service, _clock, _merchants_by_name, market_id = _open_market_with_offers(tmp_path)
    service.close_market(market_id)
    with service.store.connection(write=True) as connection:
        connection.execute(
            """
            UPDATE product_market_results SET winner_merchant_ids_json = ?
            WHERE market_id = ?
            """,
            (persisted_winner_ids, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_clearing_snapshot(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


@pytest.mark.parametrize(
    "persisted_eligible_ids",
    ("{", "{}", '["merchant-id",1]'),
    ids=("malformed", "object", "non-string-member"),
)
def test_clearing_reads_map_invalid_persisted_eligible_ids_to_stable_error(
    tmp_path: Path,
    persisted_eligible_ids: str,
) -> None:
    service, _clock, _merchants_by_name, market_id = _open_market_with_offers(tmp_path)
    with service.store.connection(write=True) as connection:
        connection.execute(
            """
            UPDATE product_markets SET eligible_merchant_ids_json = ?
            WHERE market_id = ?
            """,
            (persisted_eligible_ids, market_id),
        )

    for read in (service.list_markets, lambda: service.get_clearing_snapshot(market_id)):
        with pytest.raises(ProductServiceError) as raised:
            read()
        assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_closed_market_server_reads_reconcile_buyer_and_merchant_workspaces(
    tmp_path: Path,
) -> None:
    service, _clock, merchants, market_id = _open_market_with_offers(tmp_path)
    open_inbox = service.list_merchant_markets(merchants["Alpha"])
    open_market = next(
        market for market in open_inbox["markets"] if market["market_id"] == market_id
    )
    assert open_market["market_state"] == "OPEN"
    assert open_market["proposal"]["state"] == "SUBMITTED"

    service.close_market(market_id)

    assert service.list_merchant_markets(merchants["Alpha"])["markets"] == []
    assert service.get_market(market_id)["market_state"] == "CLOSED"


def test_concurrent_close_has_one_result_and_reconciles_through_snapshot(
    tmp_path: Path,
) -> None:
    service, _clock, _merchants_by_name, market_id = _open_market_with_offers(tmp_path)
    outcomes: list[dict[str, object]] = []
    failures: list[ProductErrorCode] = []

    def close() -> None:
        try:
            outcomes.append(service.close_market(market_id))
        except ProductServiceError as error:
            failures.append(error.code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _value: close(), range(2)))

    with service.store.connection() as connection:
        assert service.store.count_results(connection, market_id) == 1
    assert len(outcomes) == 1
    assert failures == [ProductErrorCode.MARKET_NOT_OPEN]
    assert service.get_clearing_snapshot(market_id)["market"]["state"] == "CLOSED"


def test_clearing_client_is_get_restored_and_close_body_has_no_authority() -> None:
    markup = Path("ui/index.html").read_text(encoding="utf-8")
    client = Path("ui/product_app.js").read_text(encoding="utf-8")
    clearing_markup = markup.split('<main class="clearing-shell"', 1)[1].split('<main id="top"', 1)[
        0
    ]
    close_block = client.split('closeClearingMarket.addEventListener("click"', 1)[1].split(
        "if (refreshClearingMarkets", 1
    )[0]
    reconcile_block = client.split("const reconcileClearingClose = async", 1)[1].split(
        "if (closeClearingMarket", 1
    )[0]

    assert 'data-view-target="buyer"' in markup
    assert 'data-view-target="merchant"' in markup
    assert 'data-view-target="clearing"' in markup
    assert 'data-view-target="evidence"' in markup
    assert '["#clearing", "#market-clearing"]' in client
    assert 'window.addEventListener("hashchange", routeFromHash)' in client
    assert 'window.addEventListener("popstate", routeFromHash)' in client
    assert "CLEAR · MARKET CLEARING" in clearing_markup
    assert "NO WINNER EXISTS YET." in clearing_markup
    assert "AI DID NOT CHOOSE THE WINNERS." in clearing_markup
    assert "NO FEASIBLE ALLOCATION" in client

    assert "/api/product-v1/markets/${encodeURIComponent(marketId)}/close" in close_block
    assert 'method: "POST"' in close_block
    assert 'body: "{}"' in close_block
    for forbidden in ("offers", "prices", "quantities", "winner", "allocation instructions"):
        assert forbidden not in close_block.lower()
    assert client.count("/close`") == 1
    assert "/api/product-v1/markets/${encodeURIComponent(marketId)}/clearing" in reconcile_block
    assert 'method: "POST"' not in reconcile_block
    assert "CLOSE OUTCOME NOT CONFIRMED" in client
    assert "CLOSE NOT OBSERVED COMPLETE" in client
    assert 'response.payload.market.state === "CLOSED"' in reconcile_block
    assert 'response.payload.market.state === "OPEN"' in reconcile_block

    assert 'localStorage.getItem(\n            "clear-product-clearing-market-id"' in client
    assert 'localStorage.removeItem("clear-product-clearing-market-id")' in client
    assert "innerHTML" not in client
    assert ".sort(" not in client
    assert "submittedOffers" not in client
    assert (
        re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            client,
            re.IGNORECASE,
        )
        is None
    )
    for forbidden in ("certificate", "governor", "razorpay"):
        assert forbidden not in clearing_markup.lower()


def test_clearing_snapshot_404_releases_running_state() -> None:
    client = Path("ui/product_app.js").read_text(encoding="utf-8")
    load_block = client.split("const loadClearingSnapshot = async", 1)[1].split(
        "const selectClearingMarket =", 1
    )[0]
    not_found_branch = load_block.split("if (response.status === 404) {", 1)[1].split(
        "if (!response.ok)", 1
    )[0]
    running_block = client.split("const setClearingRunning =", 1)[1].split(
        "const forgetClearingSelection =", 1
    )[0]

    assert not_found_branch.index("forgetClearingSelection();") < not_found_branch.index(
        "setClearingRunning(false);"
    )
    assert not_found_branch.index("setClearingRunning(false);") < not_found_branch.index("return;")
    assert "refreshClearingMarkets.disabled = value;" in running_block
    assert "button.disabled = value;" in running_block
    assert 'method: "POST"' not in load_block
    assert "winner" not in not_found_branch.lower()
    assert "outcome" not in not_found_branch.lower()


def test_client_reconciles_closed_market_on_workspace_activation() -> None:
    client = Path("ui/product_app.js").read_text(encoding="utf-8")
    activation_block = client.split("reconcileActiveWorkspace = (view) => {", 1)[1].split(
        'setStage("draft");', 1
    )[0]
    view_button_block = client.split('button.addEventListener("click", () => {', 1)[1].split(
        "const initialView", 1
    )[0]
    route_block = client.split("const routeFromHash = () => {", 1)[1].split(
        'window.addEventListener("hashchange"', 1
    )[0]
    clear_selection_block = client.split("const clearMerchantSelection = () => {", 1)[1].split(
        "const renderMerchantProposalLines =", 1
    )[0]
    inbox_block = client.split("const loadMerchantInbox = async", 1)[1].split(
        "const renderMerchantActionFailure =", 1
    )[0]
    frozen_block = client.split("const renderFrozen = (payload) => {", 1)[1].split(
        "const restoreFrozenMarket =", 1
    )[0]
    restore_block = client.split("const restoreFrozenMarket = async", 1)[1].split(
        "if (freezeButton instanceof HTMLButtonElement)", 1
    )[0]

    assert "reconcileActiveWorkspace(selected);" in view_button_block
    assert "reconcileActiveWorkspace(selected);" in route_block
    assert "loadMerchantInbox(currentMerchantId);" in activation_block
    assert "restoreFrozenMarket();" in activation_block
    assert 'method: "POST"' not in activation_block
    assert inbox_block.index("clearMerchantSelection();") < inbox_block.index(
        "/api/product-v1/merchants/${encodeURIComponent(merchantId)}/markets"
    )
    assert "merchantMarketReview.hidden = true;" in clear_selection_block
    assert 'method: "POST"' not in inbox_block
    assert "/api/product-v1/markets/${encodeURIComponent(marketId)}" in restore_block
    assert 'method: "POST"' not in restore_block
    assert 'payload.market_state === "OPEN"' in frozen_block
    assert 'payload.market_state === "CLOSED"' in frozen_block
    assert "The persisted runtime market is closed." in frozen_block
    assert "is now open" not in frozen_block
