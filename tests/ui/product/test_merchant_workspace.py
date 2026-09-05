from __future__ import annotations

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest

from clear_market.ai import (
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseV1,
)
from clear_market.canonical import canonical_json_bytes, canonical_utc_datetime
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    ComparisonOperator,
    HardConstraint,
    MarketSpecV2,
    ProvenanceLabel,
    canonical_buyer_policy_v2_bytes,
)
from ui.product.models import (
    CreateMarketRequest,
    CreateMerchantAttributeRequest,
    CreateMerchantRequest,
    ProductRequestError,
    SubmitOfferRequest,
    parse_product_json,
)
from ui.product.service import ProductErrorCode, ProductService, ProductServiceError

_ENVIRONMENT = {
    "CLEAR_AI_BASE_URL": "https://gateway.example/v1",
    "CLEAR_AI_API_KEY": "merchant-ai-secret",
    "CLEAR_AI_PROVIDER_NAME": "external-gateway",
    "CLEAR_AI_MODELS": "merchant-model-v1",
}


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2033, 1, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _MerchantProvider:
    def __init__(
        self,
        *,
        decision: str = "OFFER",
        quantity: int = 2,
        price: int = 500,
        output: str | None = None,
        entered: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self.decision = decision
        self.quantity = quantity
        self.price = price
        self.output = output
        self.entered = entered
        self.release = release
        self.requests: list[AIProviderRequestV1] = []
        self._lock = Lock()

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        with self._lock:
            self.requests.append(request)
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=10)
        if self.output is None:
            context = json.loads(request.input_text)
            sku_id = context["offerable_skus"][0]["sku_id"]
            lines = (
                []
                if self.decision == "NO_OFFER"
                else [
                    {
                        "schema_version": "1",
                        "merchant_offer_proposal_line_version": ("merchant-offer-proposal-line-v1"),
                        "sku_id": sku_id,
                        "proposed_quantity": self.quantity,
                        "proposed_unit_price_paise": self.price,
                    }
                ]
            )
            output = json.dumps(
                {
                    "schema_version": "1",
                    "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
                    "decision": self.decision,
                    "lines": lines,
                }
            )
        else:
            output = self.output
        return AIProviderResponseV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            finish_reason=AIProviderFinishReason.COMPLETED,
            output_text=output,
        )


def _attribute(
    key: str,
    value_type: str,
    value: str | int | bool,
    provenance: str = "CLAIMED",
) -> CreateMerchantAttributeRequest:
    return CreateMerchantAttributeRequest(
        attribute_key=key,
        value_type=value_type,
        value=value,
        provenance=provenance,
    )


def _merchant_request(
    name: str,
    *,
    attributes: list[CreateMerchantAttributeRequest] | None = None,
    inventory: int = 4,
    cost: int = 400,
    margin: int = 100,
    cap: int = 4,
) -> CreateMerchantRequest:
    return CreateMerchantRequest(
        display_name=f"{name} Compute",
        product_display_name=f"{name} EdgeBox",
        merchant_sku=f"{name.upper()}-EDGE",
        inventory_quantity=inventory,
        unit_cost_basis_paise=cost,
        minimum_margin_paise=margin,
        max_quantity_per_offer=cap,
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
    eligible: list[str],
) -> dict[str, object]:
    return service.create_market(
        CreateMarketRequest(
            requested_quantity=3,
            minimum_acceptable_quantity=2,
            max_winners=2,
            max_total_payment_paise=10_000,
            eligible_merchant_ids=eligible,
            offer_deadline=canonical_utc_datetime(clock.now + timedelta(hours=1)),
        )
    )


def _propose(
    service: ProductService,
    merchant_id: str,
    market_id: str,
    provider: _MerchantProvider,
) -> dict[str, object]:
    return service.propose_merchant_offer(
        merchant_id,
        market_id,
        environment=_ENVIRONMENT,
        provider=provider,
    )


def test_attributes_round_trip_and_reconstruct_exact_production_catalog(tmp_path: Path) -> None:
    path = tmp_path / "product.sqlite3"
    service = ProductService(path, clock=_Clock())
    created = service.create_merchant(
        _merchant_request(
            "Typed",
            attributes=[
                _attribute("ram_gb", "integer", 32, "ATTESTED"),
                _attribute("brand", "string", "CLEAR"),
                _attribute("fanless", "boolean", True, "ATTESTED"),
            ],
        )
    )

    reopened = ProductService(path, clock=_Clock())
    listed = reopened.list_merchants()["merchants"]
    assert type(listed) is list
    merchant = next(item for item in listed if item["merchant_id"] == created["merchant_id"])
    assert merchant["attributes"] == [
        {
            "attribute_key": "brand",
            "value_type": "string",
            "value": "CLEAR",
            "provenance": "CLAIMED",
        },
        {
            "attribute_key": "fanless",
            "value_type": "boolean",
            "value": True,
            "provenance": "ATTESTED",
        },
        {
            "attribute_key": "ram_gb",
            "value_type": "integer",
            "value": 32,
            "provenance": "ATTESTED",
        },
    ]
    assert "minimum_allowed_unit_price_paise" not in merchant
    assert "max_quantity_per_offer" not in merchant
    with reopened.store.connection() as connection:
        record = reopened.store.get_merchant(connection, str(created["merchant_id"]))
    assert record is not None and record.canonical_catalog_attributes is not None
    authority = reopened._merchant_authority(record)
    attributes = authority.catalog.skus[0].attributes
    assert tuple(attribute.attribute_key for attribute in attributes) == (
        "brand",
        "fanless",
        "ram_gb",
    )
    assert tuple(attribute.value.value for attribute in attributes) == ("CLEAR", True, 32)


def test_legacy_null_attribute_state_reconstructs_without_invention(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product.sqlite3", clock=_Clock())
    created = service.create_merchant(_merchant_request("Legacy"))
    with service.store.connection(write=True) as connection:
        connection.execute(
            """
            UPDATE product_merchants SET canonical_catalog_attributes = NULL
            WHERE merchant_id = ?
            """,
            (created["merchant_id"],),
        )
    with service.store.connection() as connection:
        record = service.store.get_merchant(connection, str(created["merchant_id"]))
    assert record is not None and record.canonical_catalog_attributes is None
    assert service._merchant_authority(record).catalog.skus[0].attributes == ()


def test_pre_28a3_merchant_table_migrates_additively_with_empty_attributes(
    tmp_path: Path,
) -> None:
    source = ProductService(tmp_path / "source.sqlite3", clock=_Clock())
    created = source.create_merchant(_merchant_request("Legacy"))
    with source.store.connection() as connection:
        record = source.store.get_merchant(connection, str(created["merchant_id"]))
    assert record is not None

    legacy_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(legacy_path)
    connection.execute(
        """
        CREATE TABLE product_merchants (
            merchant_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            product_id TEXT NOT NULL UNIQUE,
            catalog_id TEXT NOT NULL UNIQUE,
            sku_id TEXT NOT NULL UNIQUE,
            snapshot_id TEXT NOT NULL UNIQUE,
            inventory_evidence_reference_id TEXT NOT NULL UNIQUE,
            economic_policy_id TEXT NOT NULL UNIQUE,
            product_display_name TEXT NOT NULL,
            merchant_sku TEXT NOT NULL,
            inventory_quantity INTEGER NOT NULL,
            unit_cost_basis_paise INTEGER NOT NULL,
            minimum_margin_paise INTEGER NOT NULL,
            max_quantity_per_offer INTEGER NOT NULL,
            signing_public_key_hex TEXT NOT NULL,
            signing_private_key_hex TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO product_merchants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.merchant_id,
            record.display_name,
            record.product_id,
            record.catalog_id,
            record.sku_id,
            record.snapshot_id,
            record.inventory_evidence_reference_id,
            record.economic_policy_id,
            record.product_display_name,
            record.merchant_sku,
            record.inventory_quantity,
            record.unit_cost_basis_paise,
            record.minimum_margin_paise,
            record.max_quantity_per_offer,
            record.signing_public_key_hex,
            record.signing_private_key_hex,
            record.created_at,
        ),
    )
    connection.commit()
    connection.close()

    migrated = ProductService(legacy_path, clock=_Clock())
    with migrated.store.connection() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(product_merchants)")
        }
        migrated_record = migrated.store.get_merchant(connection, record.merchant_id)

    assert "canonical_catalog_attributes" in columns
    assert migrated_record is not None
    assert migrated_record.canonical_catalog_attributes is None
    assert migrated._merchant_authority(migrated_record).catalog.skus[0].attributes == ()


@pytest.mark.parametrize(
    "attributes",
    [
        [
            {
                "attribute_key": "Ram GB",
                "value_type": "integer",
                "value": 16,
                "provenance": "CLAIMED",
            }
        ],
        [
            {
                "attribute_key": "ram_gb",
                "value_type": "integer",
                "value": 16,
                "provenance": "CLAIMED",
            },
            {
                "attribute_key": "ram_gb",
                "value_type": "integer",
                "value": 32,
                "provenance": "ATTESTED",
            },
        ],
        [
            {
                "attribute_key": "ram_gb",
                "value_type": "integer",
                "value": "16",
                "provenance": "CLAIMED",
            }
        ],
        [
            {
                "attribute_key": "fanless",
                "value_type": "boolean",
                "value": 1,
                "provenance": "CLAIMED",
            }
        ],
        [
            {
                "attribute_key": "brand",
                "value_type": "string",
                "value": "CLEAR",
                "provenance": "VERIFIED",
            }
        ],
        [
            {
                "attribute_key": "weight",
                "value_type": "number",
                "value": 1.5,
                "provenance": "CLAIMED",
            }
        ],
    ],
)
def test_attribute_request_boundary_rejects_invalid_or_invented_facts(
    attributes: list[dict[str, object]],
) -> None:
    body = {
        "display_name": "Strict",
        "product_display_name": "Strict EdgeBox",
        "merchant_sku": "STRICT-EDGE",
        "inventory_quantity": 4,
        "unit_cost_basis_paise": 400,
        "minimum_margin_paise": 100,
        "max_quantity_per_offer": 4,
        "attributes": attributes,
    }
    with pytest.raises(ProductRequestError):
        parse_product_json(json.dumps(body).encode(), CreateMerchantRequest)


@pytest.mark.parametrize("provenance", ["VERIFIED", "PREDICTED", "DERIVED"])
def test_persisted_forbidden_attribute_provenance_fails_closed(
    tmp_path: Path,
    provenance: str,
) -> None:
    service = ProductService(tmp_path / "product.sqlite3", clock=_Clock())
    created = service.create_merchant(
        _merchant_request(
            "Persisted",
            attributes=[_attribute("brand", "string", "CLEAR")],
        )
    )
    with service.store.connection() as connection:
        record = service.store.get_merchant(connection, str(created["merchant_id"]))
    assert record is not None and record.canonical_catalog_attributes is not None
    attributes = json.loads(record.canonical_catalog_attributes)
    attributes[0]["provenance"] = provenance
    canonical = canonical_json_bytes(attributes)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_merchants SET canonical_catalog_attributes = ? WHERE merchant_id = ?",
            (canonical, record.merchant_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.list_merchants()
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_inbox_is_authoritatively_filtered_and_get_never_invokes_provider(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    eligible = _market(service, clock, [merchants["Alpha"], merchants["Beta"]])
    _market(service, clock, [merchants["Beta"], merchants["Gamma"]])
    provider = _MerchantProvider()

    alpha = service.list_merchant_markets(merchants["Alpha"])

    assert provider.requests == []
    assert [market["market_id"] for market in alpha["markets"]] == [eligible["market_id"]]
    assert alpha["merchant"]["minimum_allowed_unit_price_paise"] == 500
    assert alpha["merchant"]["max_quantity_per_offer"] == 4
    serialized = json.dumps(alpha)
    assert "private" not in serialized.lower()
    assert _ENVIRONMENT["CLEAR_AI_API_KEY"] not in serialized
    for forbidden in (
        "winner_merchant_ids",
        "allocated_quantity",
        "certificate_id",
        "payment_status",
    ):
        assert forbidden not in serialized


def test_production_merchant_ai_context_uses_persisted_referenced_attributes(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    alpha = service.create_merchant(
        _merchant_request(
            "Alpha",
            attributes=[
                _attribute("ram_gb", "integer", 32, "ATTESTED"),
                _attribute("brand", "string", "CLEAR"),
            ],
        )
    )
    beta = service.create_merchant(_merchant_request("Beta"))
    market = _market(service, clock, [str(alpha["merchant_id"]), str(beta["merchant_id"])])
    market_id = str(market["market_id"])
    with service.store.connection(write=True) as connection:
        record = service.store.get_market(connection, market_id)
        assert record is not None
        policy = service._load_policy(record)
        spec = policy.market_spec
        constrained_policy = BuyerPolicyV2(
            market_spec=MarketSpecV2(
                market_id=spec.market_id,
                buyer_id=spec.buyer_id,
                requested_quantity=spec.requested_quantity,
                minimum_acceptable_quantity=spec.minimum_acceptable_quantity,
                max_winners=spec.max_winners,
                hard_constraints=(
                    HardConstraint(
                        constraint_id="a7000000-0000-4000-8000-000000000001",
                        attribute_key="ram_gb",
                        operator=ComparisonOperator.GTE,
                        operand=AttributeValue(
                            value_type=AttributeValueType.INTEGER,
                            value=16,
                        ),
                        allowed_provenance=(ProvenanceLabel.ATTESTED,),
                    ),
                ),
                soft_preferences=(),
            ),
            max_total_payment=policy.max_total_payment,
            eligible_merchant_ids=policy.eligible_merchant_ids,
            offer_deadline=policy.offer_deadline,
            mechanism_version=policy.mechanism_version,
            objective_version=policy.objective_version,
        )
        connection.execute(
            "UPDATE product_markets SET canonical_buyer_policy = ? WHERE market_id = ?",
            (canonical_buyer_policy_v2_bytes(constrained_policy), market_id),
        )
    provider = _MerchantProvider()

    result = _propose(service, str(alpha["merchant_id"]), market_id, provider)

    assert result["state"] == "PROPOSED"
    assert len(provider.requests) == 1
    context = json.loads(provider.requests[0].input_text)
    assert context["offerable_skus"][0]["attributes"] == [
        {
            "attribute_key": "ram_gb",
            "provenance": "ATTESTED",
            "value": 32,
            "value_type": "integer",
        }
    ]


def test_noneligible_closed_and_expired_markets_never_invoke_merchant_ai(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market = _market(service, clock, [merchants["Alpha"], merchants["Beta"]])
    market_id = str(market["market_id"])
    provider = _MerchantProvider()

    with pytest.raises(ProductServiceError) as ineligible:
        _propose(service, merchants["Gamma"], market_id, provider)
    assert ineligible.value.code is ProductErrorCode.MERCHANT_NOT_ELIGIBLE
    with service.store.connection(write=True) as connection:
        service.store.transition_market_to_closed(
            connection,
            market_id=market_id,
            closed_at=canonical_utc_datetime(clock.now),
        )
    with pytest.raises(ProductServiceError) as closed:
        _propose(service, merchants["Alpha"], market_id, provider)
    assert closed.value.code is ProductErrorCode.MARKET_NOT_OPEN

    expiring = _market(service, clock, [merchants["Alpha"], merchants["Beta"]])
    clock.now += timedelta(hours=2)
    with pytest.raises(ProductServiceError) as expired:
        _propose(service, merchants["Alpha"], str(expiring["market_id"]), provider)
    assert expired.value.code is ProductErrorCode.OFFER_DEADLINE_PASSED
    assert provider.requests == []


def test_offer_proposal_is_advisory_persisted_once_and_restored(tmp_path: Path) -> None:
    path = tmp_path / "product.sqlite3"
    clock = _Clock()
    service = ProductService(path, clock=clock)
    merchants = _merchants(service)
    market = _market(service, clock, [merchants["Alpha"], merchants["Beta"]])
    market_id = str(market["market_id"])
    provider = _MerchantProvider(quantity=2, price=550)

    proposed = _propose(service, merchants["Alpha"], market_id, provider)

    assert proposed["result"] == "SUCCESS"
    assert proposed["state"] == "PROPOSED"
    assert proposed["authority"] == "ADVISORY_ONLY"
    assert proposed["signed"] is False
    assert proposed["submitted"] is False
    assert proposed["candidate"]["lines"][0]["proposed_quantity"] == 2
    assert proposed["candidate"]["lines"][0]["proposed_unit_price_paise"] == 550
    assert len(provider.requests) == 1
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 0
    restored = ProductService(path, clock=clock).list_merchant_markets(merchants["Alpha"])
    assert restored["markets"][0]["proposal"] == {
        key: value for key, value in proposed.items() if key != "result"
    }
    with pytest.raises(ProductServiceError) as repeated:
        _propose(service, merchants["Alpha"], market_id, provider)
    assert repeated.value.code is ProductErrorCode.PROPOSAL_NOT_AVAILABLE
    assert len(provider.requests) == 1


def test_valid_no_offer_is_terminal_without_signing_or_offer(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    provider = _MerchantProvider(decision="NO_OFFER")

    result = _propose(service, merchants["Alpha"], market_id, provider)

    assert result["result"] == "SUCCESS"
    assert result["state"] == "NO_OFFER"
    assert result["decision"] == "NO_OFFER"
    assert result["valid"] is True
    assert result["signed"] is False
    assert result["submitted"] is False
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 0
    with pytest.raises(ProductServiceError) as repeated:
        _propose(service, merchants["Alpha"], market_id, provider)
    assert repeated.value.code is ProductErrorCode.PROPOSAL_NOT_AVAILABLE
    assert len(provider.requests) == 1


def test_malformed_authority_like_output_fails_closed_without_raw_content(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    canary = "do-not-return-provider-content"
    provider = _MerchantProvider(
        output=json.dumps(
            {
                "schema_version": "1",
                "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
                "decision": "OFFER",
                "lines": [],
                "winner": canary,
            }
        )
    )

    result = _propose(service, merchants["Alpha"], market_id, provider)

    assert result["code"] == "STRICT_MERCHANT_OFFER_PARSE_FAILURE"
    assert result["diagnostic_code"] == "invalid_proposal"
    assert result["provider_invoked"] is True
    serialized = json.dumps(result)
    assert canary not in serialized
    assert provider.output not in serialized
    assert _ENVIRONMENT["CLEAR_AI_API_KEY"] not in serialized
    assert _ENVIRONMENT["CLEAR_AI_BASE_URL"] not in serialized
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 0
        assert (
            service.store.get_merchant_proposal(
                connection,
                market_id=market_id,
                merchant_id=merchants["Alpha"],
            )
            is None
        )


def test_concurrent_propose_invokes_provider_at_most_once(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    entered = Event()
    release = Event()
    provider = _MerchantProvider(entered=entered, release=release)

    def propose() -> dict[str, object] | ProductErrorCode:
        try:
            return _propose(service, merchants["Alpha"], market_id, provider)
        except ProductServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(propose)
        assert entered.wait(timeout=10)
        second_result = executor.submit(propose).result(timeout=10)
        release.set()
        first_result = first.result(timeout=10)

    assert type(first_result) is dict and first_result["state"] == "PROPOSED"
    assert second_result is ProductErrorCode.PROPOSAL_NOT_AVAILABLE
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    ("quantity", "price"),
    [(2, 499), (5, 500)],
)
def test_submit_revalidates_persisted_candidate_floor_and_inventory(
    tmp_path: Path,
    quantity: int,
    price: int,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    provider = _MerchantProvider(quantity=quantity, price=price)
    _propose(service, merchants["Alpha"], market_id, provider)

    with pytest.raises(ProductServiceError) as rejected:
        service.submit_merchant_proposal(merchants["Alpha"], market_id)

    assert rejected.value.code is ProductErrorCode.MERCHANT_OFFER_REJECTED
    assert len(provider.requests) == 1
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 0
        proposal = service.store.get_merchant_proposal(
            connection,
            market_id=market_id,
            merchant_id=merchants["Alpha"],
        )
    assert proposal is not None and proposal.state == "PROPOSED"


def test_explicit_submit_signs_authenticates_once_and_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "product.sqlite3"
    clock = _Clock()
    service = ProductService(path, clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    provider = _MerchantProvider(quantity=2, price=550)
    _propose(service, merchants["Alpha"], market_id, provider)

    submitted = service.submit_merchant_proposal(merchants["Alpha"], market_id)

    assert len(provider.requests) == 1
    assert submitted["state"] == "SUBMITTED"
    assert submitted["signed"] is True
    assert submitted["authenticated"] is True
    assert submitted["submitted"] is True
    assert submitted["market_cleared"] is False
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 1
    restored = ProductService(path, clock=clock).list_merchant_markets(merchants["Alpha"])
    proposal = restored["markets"][0]["proposal"]
    assert proposal["state"] == "SUBMITTED"
    assert proposal["signed"] is True
    assert proposal["authenticated"] is True
    assert proposal["market_cleared"] is False


def test_concurrent_submit_persists_at_most_one_offer(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    _propose(service, merchants["Alpha"], market_id, _MerchantProvider())
    start = Barrier(3)

    def submit() -> dict[str, object] | ProductErrorCode:
        start.wait()
        try:
            return service.submit_merchant_proposal(merchants["Alpha"], market_id)
        except ProductServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        start.wait()
        outcomes = [future.result(timeout=10) for future in futures]

    assert len([value for value in outcomes if type(value) is dict]) == 1
    assert [value for value in outcomes if type(value) is ProductErrorCode] == [
        ProductErrorCode.PROPOSAL_NOT_SUBMITTABLE
    ]
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 1


def test_manual_offer_remains_compatible_without_a_proposal(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])

    result = service.submit_offer(
        market_id,
        SubmitOfferRequest(
            merchant_id=merchants["Alpha"],
            proposed_quantity=2,
            proposed_unit_price_paise=500,
        ),
    )

    assert result["authenticated"] is True
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 1


@pytest.mark.parametrize("proposal_state", ["PROPOSING", "PROPOSED", "NO_OFFER"])
def test_manual_offer_rejects_existing_merchant_proposal_without_mutation(
    tmp_path: Path,
    proposal_state: str,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    market_id = str(_market(service, clock, [merchants["Alpha"], merchants["Beta"]])["market_id"])
    provider = _MerchantProvider(decision="NO_OFFER" if proposal_state == "NO_OFFER" else "OFFER")
    if proposal_state == "PROPOSING":
        with service.store.connection(write=True) as connection:
            service.store.claim_merchant_proposal(
                connection,
                market_id=market_id,
                merchant_id=merchants["Alpha"],
                provider_name="external-gateway",
                model="merchant-model-v1",
                now=canonical_utc_datetime(clock.now),
            )
    else:
        _propose(service, merchants["Alpha"], market_id, provider)

    with pytest.raises(ProductServiceError) as rejected:
        service.submit_offer(
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants["Alpha"],
                proposed_quantity=2,
                proposed_unit_price_paise=500,
            ),
        )

    assert rejected.value.code is ProductErrorCode.PROPOSAL_NOT_SUBMITTABLE
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 0
        proposal = service.store.get_merchant_proposal(
            connection,
            market_id=market_id,
            merchant_id=merchants["Alpha"],
        )
    assert proposal is not None and proposal.state == proposal_state


def test_merchant_workspace_client_restores_from_get_and_mutates_only_on_explicit_actions() -> None:
    markup = Path("ui/index.html").read_text(encoding="utf-8")
    client = Path("ui/product_app.js").read_text(encoding="utf-8")
    inbox_block = client.split("const loadMerchantInbox = async", 1)[1].split(
        "const renderMerchantActionFailure =", 1
    )[0]
    propose_block = client.split("requestMerchantProposal.addEventListener", 1)[1].split(
        "if (submitMerchantProposal instanceof HTMLButtonElement)", 1
    )[0]
    submit_block = client.split("submitMerchantProposal.addEventListener", 1)[1].split(
        "const renderInterpretationFailure", 1
    )[0]

    assert 'data-view-target="merchant"' in markup
    assert 'id="merchant-workspace"' in markup
    assert 'id="request-merchant-proposal"' in markup
    assert 'id="submit-merchant-proposal"' in markup
    assert 'data-app-view="evidence"' in markup
    assert '["#merchant", "#merchant-workspace"]' in client
    assert '["#buyer", "#buyer-workspace"]' in client
    assert '["#evidence", "#top", "#demo", "#supporting", "#architecture"]' in client
    assert 'window.addEventListener("hashchange", routeFromHash)' in client
    assert 'window.addEventListener("popstate", routeFromHash)' in client

    assert "/api/product-v1/merchants/${encodeURIComponent(merchantId)}/markets" in inbox_block
    assert 'method: "POST"' not in inbox_block
    assert "response.payload.merchant" in inbox_block
    assert "response.payload.markets" in inbox_block
    assert 'localStorage.getItem("clear-product-merchant-market-id")' in inbox_block
    assert "/propose`" in propose_block
    assert "/submit-proposal`" in submit_block
    assert '{ method: "POST", body: "{}" }' in propose_block
    assert '{ method: "POST", body: "{}" }' in submit_block
    assert "await loadMerchantInbox(merchantId, marketId);" in propose_block
    assert "await loadMerchantInbox(merchantId, marketId);" in submit_block
    assert "/api/product-v1/markets/${encodeURIComponent(marketId)}/offers" not in client

    assert "AI PROPOSAL · ADVISORY ONLY. AI DID NOT SUBMIT AN OFFER." in client
    assert "VALID NO_OFFER" in client
    assert "SIGNED · AUTHENTICATED · SUBMITTED" in client
    assert "AUTHENTICATED OFFER SUBMITTED. MARKET NOT CLEARED." in client
    assert "innerHTML" not in client
    assert "safeProposal.provider_invoked === true" in client
    assert "provider.hidden = !providerInvoked" in client
    assert "winner_merchant_ids" not in client
    assert "allocated_quantity" not in client
    assert "certificate_id" not in client
    assert "payment_status" not in client
    assert "unit_cost_basis_paise" not in client
    assert "minimum_margin_paise" not in client
    assert (
        re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            client,
            re.IGNORECASE,
        )
        is None
    )
