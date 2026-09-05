import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import clear_market.agentmarketbench.methods as methods_module
from clear_market.agentmarketbench.admission import admit_agent_market_bench_market_input_v1
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionRejectionReasonV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.methods import run_agent_market_bench_method_v1
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMarketInputV1,
    AgentMarketBenchObservedMerchantV1,
    AgentMarketBenchReportedOfferV1,
)
from clear_market.agentmarketbench.protocol import agent_market_bench_market_input_v1
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    ComparisonOperator,
    HardConstraint,
    InventoryLineV2,
    InventorySnapshotV2,
    MarketSpecV2,
    MerchantCatalogV2,
    MerchantEconomicPolicyV2,
    MerchantOfferCandidateLineV2,
    MerchantOfferCandidateV2,
    MerchantSigningIdentityV2,
    MerchantSkuEconomicRuleV2,
    ProvenanceLabel,
    SignedMerchantOfferV2,
    SoftPreference,
    build_and_sign_merchant_offer_v2,
    canonical_merchant_offer_v2_bytes,
)
from clear_market.domain import Money
from clear_market.mechanism.v2 import allocate_market_v2

_START = 100_000_000


@dataclass(frozen=True)
class _SkuSpec:
    name: str
    ask: int
    quantity: int
    attributes: tuple[tuple[str, AttributeValueType, object, ProvenanceLabel], ...]


@dataclass(frozen=True)
class _MerchantSpec:
    name: str
    skus: tuple[_SkuSpec, ...]


def _fixture_uuid(label: str) -> str:
    digest = bytearray(sha256(label.encode("ascii")).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(digest)))


def _fixture_key(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(sha256(label.encode("ascii")).digest())


def _attribute(
    key: str,
    value: object,
    *,
    value_type: AttributeValueType | None = None,
    provenance: ProvenanceLabel = ProvenanceLabel.CLAIMED,
) -> tuple[str, AttributeValueType, object, ProvenanceLabel]:
    if value_type is None:
        value_type = (
            AttributeValueType.BOOLEAN
            if type(value) is bool
            else (AttributeValueType.INTEGER if type(value) is int else AttributeValueType.STRING)
        )
    return key, value_type, value, provenance


def _hard_rule(
    key: str,
    value: object,
    operator: ComparisonOperator,
    *,
    value_type: AttributeValueType | None = None,
    allowed_provenance: tuple[ProvenanceLabel, ...] = (ProvenanceLabel.CLAIMED,),
) -> HardConstraint:
    _, value_type, value, _ = _attribute(key, value, value_type=value_type)
    return HardConstraint(
        constraint_id=_fixture_uuid(f"constraint|{key}|{operator.value}|{value}"),
        attribute_key=key,
        operator=operator,
        operand=AttributeValue(value_type=value_type, value=value),
        allowed_provenance=allowed_provenance,
    )


def _soft_rule(
    key: str,
    value: object,
    operator: ComparisonOperator,
    *,
    value_type: AttributeValueType | None = None,
    allowed_provenance: tuple[ProvenanceLabel, ...] = (ProvenanceLabel.CLAIMED,),
) -> SoftPreference:
    _, value_type, value, _ = _attribute(key, value, value_type=value_type)
    return SoftPreference(
        preference_id=_fixture_uuid(f"preference|{key}|{operator.value}|{value}"),
        attribute_key=key,
        operator=operator,
        operand=AttributeValue(value_type=value_type, value=value),
        allowed_provenance=allowed_provenance,
    )


def _market_input_fixture(
    label: str,
    merchants: tuple[_MerchantSpec, ...],
    *,
    requested_quantity: int,
    minimum_acceptable_quantity: int,
    max_winners: int,
    budget: int,
    hard_constraints: tuple[HardConstraint, ...] = (),
    soft_preferences: tuple[SoftPreference, ...] = (),
    receipt_order: tuple[int, ...] | None = None,
) -> tuple[BuyerPolicyV2, AgentMarketBenchMarketInputV1]:
    merchant_ids = tuple(
        _fixture_uuid(f"{label}|merchant|{merchant.name}") for merchant in merchants
    )
    policy = BuyerPolicyV2(
        market_spec=MarketSpecV2(
            market_id=_fixture_uuid(f"{label}|market"),
            buyer_id=_fixture_uuid(f"{label}|buyer"),
            requested_quantity=requested_quantity,
            minimum_acceptable_quantity=minimum_acceptable_quantity,
            max_winners=max_winners,
            hard_constraints=hard_constraints,
            soft_preferences=soft_preferences,
        ),
        max_total_payment=Money(amount_paise=budget),
        eligible_merchant_ids=merchant_ids,
        offer_deadline=datetime(2030, 1, 1, 12, tzinfo=UTC),
        mechanism_version="heterogeneous-pay-as-bid-v2",
        objective_version="quantity-cost-soft-objective-v2",
    )
    observed: list[AgentMarketBenchObservedMerchantV1] = []
    signed_offers: list[SignedMerchantOfferV2] = []
    for merchant_index, (merchant, merchant_id) in enumerate(
        zip(merchants, merchant_ids, strict=True)
    ):
        catalog_id = _fixture_uuid(f"{label}|catalog|{merchant.name}")
        product_ids = tuple(
            _fixture_uuid(f"{label}|product|{merchant.name}|{sku.name}") for sku in merchant.skus
        )
        sku_ids = tuple(
            _fixture_uuid(f"{label}|sku|{merchant.name}|{sku.name}") for sku in merchant.skus
        )
        products = tuple(
            CatalogProductV2(
                product_id=product_id,
                display_name=f"Product {merchant.name} {sku.name}",
                description="Deterministic fixture",
            )
            for product_id, sku in zip(product_ids, merchant.skus, strict=True)
        )
        catalog_skus = tuple(
            CatalogSkuV2(
                sku_id=sku_id,
                product_id=product_id,
                merchant_sku=f"SKU-{merchant_index}-{sku_index}",
                display_name=f"SKU {merchant.name} {sku.name}",
                attributes=tuple(
                    CatalogAttributeV2(
                        attribute_key=key,
                        value=AttributeValue(value_type=value_type, value=value),
                        provenance=provenance,
                        evidence_reference_id=_fixture_uuid(
                            f"{label}|evidence|{merchant.name}|{sku.name}|{key}"
                        ),
                    )
                    for key, value_type, value, provenance in sku.attributes
                ),
            )
            for sku_index, (sku_id, product_id, sku) in enumerate(
                zip(sku_ids, product_ids, merchant.skus, strict=True)
            )
        )
        catalog = MerchantCatalogV2(
            catalog_id=catalog_id,
            merchant_id=merchant_id,
            generated_at=datetime(2030, 1, 1, 9, tzinfo=UTC),
            products=products,
            skus=catalog_skus,
        )
        inventory = InventorySnapshotV2(
            snapshot_id=_fixture_uuid(f"{label}|snapshot|{merchant.name}"),
            catalog_id=catalog_id,
            merchant_id=merchant_id,
            captured_at=datetime(2030, 1, 1, 10, tzinfo=UTC),
            lines=tuple(
                InventoryLineV2(
                    sku_id=sku_id,
                    quantity_available=sku.quantity,
                    provenance=ProvenanceLabel.CLAIMED,
                    evidence_reference_id=_fixture_uuid(
                        f"{label}|inventory-evidence|{merchant.name}|{sku.name}"
                    ),
                )
                for sku_id, sku in zip(sku_ids, merchant.skus, strict=True)
            ),
        )
        private_key = _fixture_key(f"{label}|key|{merchant.name}")
        identity = MerchantSigningIdentityV2(
            merchant_id=merchant_id,
            ed25519_public_key_hex=private_key.public_key().public_bytes_raw().hex(),
        )
        economic_policy = MerchantEconomicPolicyV2(
            economic_policy_id=_fixture_uuid(f"{label}|economic|{merchant.name}"),
            merchant_id=merchant_id,
            catalog_id=catalog_id,
            sku_rules=tuple(
                MerchantSkuEconomicRuleV2(
                    sku_id=sku_id,
                    unit_cost_basis=Money(amount_paise=sku.ask),
                    minimum_margin=Money(amount_paise=0),
                    max_quantity_per_offer=sku.quantity,
                )
                for sku_id, sku in zip(sku_ids, merchant.skus, strict=True)
            ),
        )
        signed_offers.append(
            build_and_sign_merchant_offer_v2(
                offer_id=_fixture_uuid(f"{label}|offer|{merchant.name}"),
                buyer_policy=policy,
                catalog=catalog,
                inventory=inventory,
                economic_policy=economic_policy,
                candidate=MerchantOfferCandidateV2(
                    lines=tuple(
                        MerchantOfferCandidateLineV2(
                            sku_id=sku_id,
                            proposed_quantity=sku.quantity,
                            proposed_unit_price=Money(amount_paise=sku.ask),
                        )
                        for sku_id, sku in zip(sku_ids, merchant.skus, strict=True)
                    )
                ),
                signing_identity=identity,
                private_key=private_key,
            )
        )
        observed.append(
            AgentMarketBenchObservedMerchantV1(
                merchant_id=merchant_id,
                catalog=catalog,
                inventory_snapshot=inventory,
                signing_identity=identity,
            )
        )
    order = receipt_order if receipt_order is not None else tuple(range(len(merchants)))
    reports = tuple(
        AgentMarketBenchReportedOfferV1(
            submission_index=report_index,
            received_at=datetime(2030, 1, 1, 11, tzinfo=UTC) + timedelta(seconds=report_index),
            signed_offer=signed_offers[merchant_index],
        )
        for report_index, merchant_index in enumerate(order)
    )
    return policy, AgentMarketBenchMarketInputV1(
        buyer_policy=policy,
        observed_merchants=tuple(observed),
        reported_offers=reports,
    )


def _resign_offer(
    signed_offer: SignedMerchantOfferV2,
    *,
    offer_id: str,
    private_key: Ed25519PrivateKey,
) -> SignedMerchantOfferV2:
    offer = signed_offer.offer.model_copy(update={"offer_id": offer_id})
    return SignedMerchantOfferV2(
        offer=offer,
        signature_hex=private_key.sign(canonical_merchant_offer_v2_bytes(offer)).hex(),
    )


def test_public_input_firewall_and_no_forbidden_method_dependencies() -> None:
    module_source = inspect.getsource(
        __import__("clear_market.agentmarketbench.methods", fromlist=["x"])
    )
    for forbidden in (
        "AgentMarketBenchCaseV1",
        "latent_lines",
        "agentmarketbench.generator",
        "agentmarketbench.seeds",
        "AdversarialScenario",
        "clear_market.benchmark",
        "clear_market.oracle.v2",
        "payments",
        "Razorpay",
        "clear_market.ai",
        "persistence",
        "execution",
    ):
        assert forbidden not in module_source


def test_admission_scenarios_have_expected_public_outcomes() -> None:
    expected = {
        AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER: "AUTHENTICATION_FAILED",
        AgentMarketBenchAdversarialScenarioV1.FORGED_MERCHANT: "AUTHENTICATION_FAILED",
        AgentMarketBenchAdversarialScenarioV1.LATE_OFFER: "LATE_OFFER",
        AgentMarketBenchAdversarialScenarioV1.REPLAYED_OFFER: "DUPLICATE_OFFER_ID",
    }
    for scenario, reason in expected.items():
        case = next(
            generate_agent_market_bench_case_v1(seed)
            for seed in range(_START, _START + 42)
            if generate_agent_market_bench_case_v1(seed).adversarial_scenarios == (scenario,)
        )
        admission = admit_agent_market_bench_market_input_v1(
            agent_market_bench_market_input_v1(case)
        )
        assert len(admission.rejections) == 1
        assert admission.rejections[0].reason.value == reason


@pytest.mark.parametrize(
    "scenario",
    (
        AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY,
        AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE,
        AgentMarketBenchAdversarialScenarioV1.SELLER_DROPOUT,
        AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
        AgentMarketBenchAdversarialScenarioV1.MALICIOUS_CATALOG_TEXT,
    ),
)
def test_non_cryptographic_scenarios_do_not_gain_fake_admission_rejections(
    scenario: AgentMarketBenchAdversarialScenarioV1,
) -> None:
    case = next(
        generate_agent_market_bench_case_v1(seed)
        for seed in range(_START, _START + 42)
        if generate_agent_market_bench_case_v1(seed).adversarial_scenarios == (scenario,)
    )
    admission = admit_agent_market_bench_market_input_v1(agent_market_bench_market_input_v1(case))
    assert len(admission.rejections) == 0


def test_admission_accepts_exact_deadline_and_rejects_noncontiguous_indexes() -> None:
    market_input = agent_market_bench_market_input_v1(generate_agent_market_bench_case_v1(_START))
    reports = list(market_input.reported_offers)
    reports[0] = reports[0].model_copy(
        update={"received_at": market_input.buyer_policy.offer_deadline}
    )
    deadline_input = market_input.model_copy(update={"reported_offers": tuple(reports)})
    assert len(admit_agent_market_bench_market_input_v1(deadline_input).rejections) == 0

    reports[0] = reports[0].model_copy(update={"submission_index": 1})
    malformed = market_input.model_copy(update={"reported_offers": tuple(reports)})
    with pytest.raises(ValueError, match="submission indexes"):
        admit_agent_market_bench_market_input_v1(malformed)


def test_all_ordinary_methods_are_total_and_deterministic_for_first_42_development_cases() -> None:
    methods = tuple(
        method for method in AgentMarketBenchBaselineV1 if method.name != "FULL_INFORMATION_ORACLE"
    )
    for seed in range(_START, _START + 42):
        market_input = agent_market_bench_market_input_v1(generate_agent_market_bench_case_v1(seed))
        for method in methods:
            first = run_agent_market_bench_method_v1(method=method, market_input=market_input)
            second = run_agent_market_bench_method_v1(method=method, market_input=market_input)
            assert first == second
            assert first.method is method
            assert first.status in tuple(AgentMarketBenchMethodStatusV1)
            assert (
                first.fulfilled_quantity <= market_input.buyer_policy.market_spec.requested_quantity
            )
            assert first.winner_count <= market_input.buyer_policy.market_spec.max_winners


def test_clear_matches_production_allocator_after_shared_admission() -> None:
    market_input = agent_market_bench_market_input_v1(generate_agent_market_bench_case_v1(_START))
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.CLEAR,
        market_input=market_input,
    )
    from clear_market.agentmarketbench.admission import _admit_with_reports

    reports, _ = _admit_with_reports(market_input)
    expected = allocate_market_v2(
        buyer_policy=market_input.buyer_policy,
        signed_offers=tuple(report.signed_offer for report in reports),
    )
    assert result.status.value == expected.status.value
    assert result.fulfilled_quantity == expected.fulfilled_quantity
    assert result.total_payment == expected.total_payment
    assert result.winner_count == expected.winner_count
    assert tuple(
        (line.merchant_id, line.sku_id, line.allocated_quantity) for line in result.lines
    ) == tuple((line.merchant_id, line.sku_id, line.allocated_quantity) for line in expected.lines)


def test_full_information_method_requires_case_aware_api() -> None:
    market_input = agent_market_bench_market_input_v1(generate_agent_market_bench_case_v1(_START))
    with pytest.raises(ValueError, match="case-aware"):
        run_agent_market_bench_method_v1(
            method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
            market_input=market_input,
        )


def _single_unit_market_input() -> tuple[object, object]:
    market_id = "51000000-0000-4000-8000-000000000101"
    merchant_ids = (
        "43000000-0000-4000-8000-000000000101",
        "43000000-0000-4000-8000-000000000102",
    )
    sku_ids = (
        "46000000-0000-4000-8000-000000000101",
        "46000000-0000-4000-8000-000000000102",
    )
    policy = BuyerPolicyV2(
        market_spec=MarketSpecV2(
            market_id=market_id,
            buyer_id="42000000-0000-4000-8000-000000000101",
            requested_quantity=1,
            minimum_acceptable_quantity=1,
            max_winners=1,
            hard_constraints=(),
            soft_preferences=(),
        ),
        max_total_payment=Money(amount_paise=100),
        eligible_merchant_ids=merchant_ids,
        offer_deadline=datetime(2030, 1, 1, 12, tzinfo=UTC),
        mechanism_version="heterogeneous-pay-as-bid-v2",
        objective_version="quantity-cost-soft-objective-v2",
    )
    observed = []
    reports = []
    for index, (merchant_id, sku_id, ask) in enumerate(
        zip(merchant_ids, sku_ids, (30, 40), strict=True)
    ):
        private_key = _fixture_key(f"single-unit|merchant|{index}")
        public_key = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )
        catalog_id = f"44000000-0000-4000-8000-00000000010{index + 1}"
        product_id = f"45000000-0000-4000-8000-00000000010{index + 1}"
        snapshot_id = f"48000000-0000-4000-8000-00000000010{index + 1}"
        evidence_id = f"47000000-0000-4000-8000-00000000010{index + 1}"
        catalog = MerchantCatalogV2(
            catalog_id=catalog_id,
            merchant_id=merchant_id,
            generated_at=datetime(2030, 1, 1, 9, tzinfo=UTC),
            products=(CatalogProductV2(product_id=product_id, display_name="P", description="D"),),
            skus=(
                CatalogSkuV2(
                    sku_id=sku_id,
                    product_id=product_id,
                    merchant_sku=f"SKU{index}",
                    display_name="S",
                    attributes=(),
                ),
            ),
        )
        inventory = InventorySnapshotV2(
            snapshot_id=snapshot_id,
            catalog_id=catalog_id,
            merchant_id=merchant_id,
            captured_at=datetime(2030, 1, 1, 10, tzinfo=UTC),
            lines=(
                InventoryLineV2(
                    sku_id=sku_id,
                    quantity_available=1,
                    provenance=ProvenanceLabel.CLAIMED,
                    evidence_reference_id=evidence_id,
                ),
            ),
        )
        identity = MerchantSigningIdentityV2(
            merchant_id=merchant_id,
            ed25519_public_key_hex=public_key,
        )
        economic = MerchantEconomicPolicyV2(
            economic_policy_id=f"52000000-0000-4000-8000-00000000010{index + 1}",
            merchant_id=merchant_id,
            catalog_id=catalog_id,
            sku_rules=(
                MerchantSkuEconomicRuleV2(
                    sku_id=sku_id,
                    unit_cost_basis=Money(amount_paise=ask),
                    minimum_margin=Money(amount_paise=0),
                    max_quantity_per_offer=1,
                ),
            ),
        )
        signed = build_and_sign_merchant_offer_v2(
            offer_id=f"49000000-0000-4000-8000-00000000010{index + 1}",
            buyer_policy=policy,
            catalog=catalog,
            inventory=inventory,
            economic_policy=economic,
            candidate=MerchantOfferCandidateV2(
                lines=(
                    MerchantOfferCandidateLineV2(
                        sku_id=sku_id,
                        proposed_quantity=1,
                        proposed_unit_price=Money(amount_paise=ask),
                    ),
                ),
            ),
            signing_identity=identity,
            private_key=private_key,
        )
        observed.append(
            AgentMarketBenchObservedMerchantV1(
                merchant_id=merchant_id,
                catalog=catalog,
                inventory_snapshot=inventory,
                signing_identity=identity,
            )
        )
        reports.append(
            AgentMarketBenchReportedOfferV1(
                submission_index=index,
                received_at=datetime(2030, 1, 1, 11, tzinfo=UTC),
                signed_offer=signed,
            )
        )
    return policy, AgentMarketBenchMarketInputV1(
        buyer_policy=policy,
        observed_merchants=tuple(observed),
        reported_offers=tuple(reports),
    )


def test_reverse_vickrey_narrow_fixture_pays_second_ask() -> None:
    _, market_input = _single_unit_market_input()
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.REVERSE_VICKREY,
        market_input=market_input,
    )
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert result.fulfilled_quantity == 1
    assert result.total_payment.amount_paise == 40
    assert result.lines[0].unit_payment.amount_paise == 40


def _basic_sku(
    name: str,
    ask: int,
    quantity: int,
    *attributes: tuple[str, AttributeValueType, object, ProvenanceLabel],
) -> _SkuSpec:
    return _SkuSpec(name=name, ask=ask, quantity=quantity, attributes=attributes)


def test_random_qualifying_seller_uses_the_frozen_digest_rank() -> None:
    merchants = (
        _MerchantSpec("random-a", (_basic_sku("sku", 11, 2),)),
        _MerchantSpec("random-b", (_basic_sku("sku", 13, 2),)),
    )
    policy, market_input = _market_input_fixture(
        "random-rank",
        merchants,
        requested_quantity=2,
        minimum_acceptable_quantity=1,
        max_winners=2,
        budget=100,
    )
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
        market_input=market_input,
    )
    merchant_ids = {
        report.signed_offer.offer.merchant_id for report in market_input.reported_offers
    }
    market_id = policy.market_spec.market_id
    ranks = {
        merchant_id: sha256(
            (
                "agent-market-bench-methods-v1|RANDOM_QUALIFYING_SELLER|"
                f"market_id={market_id}|merchant_id={merchant_id}"
            ).encode("ascii")
        ).hexdigest()
        for merchant_id in merchant_ids
    }
    expected_merchant = min(merchant_ids, key=lambda merchant_id: (ranks[merchant_id], merchant_id))
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert {line.merchant_id for line in result.lines} == {expected_merchant}
    assert result.winner_count == 1
    assert result == run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
        market_input=market_input,
    )


def test_cheapest_qualifying_uses_exact_average_then_frozen_ties() -> None:
    merchants = (
        _MerchantSpec("cheap-total", (_basic_sku("sku", 5, 2),)),
        _MerchantSpec("cheap-average", (_basic_sku("sku", 4, 3),)),
    )
    _, market_input = _market_input_fixture(
        "cheapest-average",
        merchants,
        requested_quantity=3,
        minimum_acceptable_quantity=2,
        max_winners=2,
        budget=100,
    )
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
        market_input=market_input,
    )
    average_winner = market_input.reported_offers[1].signed_offer.offer.merchant_id
    assert {line.merchant_id for line in result.lines} == {average_winner}
    assert result.fulfilled_quantity == 3
    assert result.total_payment.amount_paise == 12

    tie_merchants = (
        _MerchantSpec("tie-a", (_basic_sku("sku", 5, 2),)),
        _MerchantSpec("tie-b", (_basic_sku("sku", 5, 3),)),
        _MerchantSpec("tie-c", (_basic_sku("sku", 5, 3),)),
    )
    _, tie_input = _market_input_fixture(
        "cheapest-ties",
        tie_merchants,
        requested_quantity=3,
        minimum_acceptable_quantity=1,
        max_winners=3,
        budget=100,
    )
    tie_result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
        market_input=tie_input,
    )
    tie_ids = {
        report.signed_offer.offer.merchant_id
        for report in tie_input.reported_offers
        if report.signed_offer.offer.merchant_id
        != tie_input.reported_offers[0].signed_offer.offer.merchant_id
    }
    assert {line.merchant_id for line in tie_result.lines} == {min(tie_ids)}
    assert tie_result.fulfilled_quantity == 3


def test_static_weighted_score_freezes_integer_components_and_constraints() -> None:
    poor = _basic_sku(
        "poor",
        20,
        2,
        _attribute("quality_score", 1),
        _attribute("sla_days", 7),
        _attribute("eco_certified", False),
    )
    rich = _basic_sku(
        "rich",
        50,
        1,
        _attribute("quality_score", 10),
        _attribute("sla_days", 1),
        _attribute("eco_certified", True),
    )
    _, market_input = _market_input_fixture(
        "static-score",
        (_MerchantSpec("poor", (poor,)), _MerchantSpec("rich", (rich,))),
        requested_quantity=2,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=200,
    )
    qualified = methods_module._qualified_lines(
        market_input.buyer_policy, market_input.reported_offers
    )
    expected_scores = {"poor": (800, 100, 142, 0), "rich": (500, 1000, 1000, 1000)}
    for line in qualified:
        merchant_name = "poor" if line.unit_price_paise == 20 else "rich"
        price_score, quality_score, sla_score, eco_score = expected_scores[merchant_name]
        expected = 40 * price_score + 30 * quality_score + 20 * sla_score + 10 * eco_score
        assert methods_module._static_score(market_input.buyer_policy, line) == expected
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.STATIC_WEIGHTED_SCORE,
        market_input=market_input,
    )
    rich_id = market_input.reported_offers[1].signed_offer.offer.merchant_id
    assert {line.merchant_id for line in result.lines} == {rich_id}
    assert result.fulfilled_quantity == 1
    assert (
        result.total_payment.amount_paise
        <= market_input.buyer_policy.max_total_payment.amount_paise
    )
    assert result.fulfilled_quantity <= market_input.buyer_policy.market_spec.requested_quantity
    assert result.lines[0].allocated_quantity <= 1
    assert result.winner_count <= market_input.buyer_policy.market_spec.max_winners


def test_bilateral_negotiation_does_not_switch_after_first_merchant_fails_minimum() -> None:
    _, market_input = _market_input_fixture(
        "bilateral-minimum",
        (
            _MerchantSpec("first", (_basic_sku("sku", 10, 1),)),
            _MerchantSpec("later", (_basic_sku("sku", 11, 3),)),
        ),
        requested_quantity=3,
        minimum_acceptable_quantity=2,
        max_winners=1,
        budget=100,
    )
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.BILATERAL_NEGOTIATION,
        market_input=market_input,
    )
    assert result.status is AgentMarketBenchMethodStatusV1.INFEASIBLE
    assert result.fulfilled_quantity == 0
    assert result.total_payment.amount_paise == 0
    assert result.winner_count == 0
    assert result.lines == ()


def test_sequential_negotiation_combines_merchants_in_receipt_order() -> None:
    merchants = (
        _MerchantSpec("first", (_basic_sku("sku", 10, 2),)),
        _MerchantSpec("second", (_basic_sku("sku", 20, 2),)),
    )
    _, first_input = _market_input_fixture(
        "sequential-forward",
        merchants,
        requested_quantity=3,
        minimum_acceptable_quantity=3,
        max_winners=2,
        budget=100,
        receipt_order=(0, 1),
    )
    _, reverse_input = _market_input_fixture(
        "sequential-reverse",
        merchants,
        requested_quantity=3,
        minimum_acceptable_quantity=3,
        max_winners=2,
        budget=100,
        receipt_order=(1, 0),
    )
    forward = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.SEQUENTIAL_NEGOTIATION,
        market_input=first_input,
    )
    reverse = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.SEQUENTIAL_NEGOTIATION,
        market_input=reverse_input,
    )
    first_id = first_input.reported_offers[0].signed_offer.offer.merchant_id
    second_id = first_input.reported_offers[1].signed_offer.offer.merchant_id
    assert forward.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert forward.winner_count == 2
    assert {(line.merchant_id, line.allocated_quantity) for line in forward.lines} == {
        (first_id, 2),
        (second_id, 1),
    }
    reverse_first_id = reverse_input.reported_offers[0].signed_offer.offer.merchant_id
    reverse_second_id = reverse_input.reported_offers[1].signed_offer.offer.merchant_id
    assert {(line.merchant_id, line.allocated_quantity) for line in reverse.lines} == {
        (reverse_first_id, 2),
        (reverse_second_id, 1),
    }
    assert forward.winner_count <= first_input.buyer_policy.market_spec.max_winners


def test_first_price_reverse_auction_enumerates_winner_subsets() -> None:
    _, market_input = _market_input_fixture(
        "first-price-trap",
        (
            _MerchantSpec("cheapest-small", (_basic_sku("sku", 1, 1),)),
            _MerchantSpec("second-small", (_basic_sku("sku", 2, 1),)),
            _MerchantSpec("large", (_basic_sku("sku", 100, 4),)),
        ),
        requested_quantity=4,
        minimum_acceptable_quantity=4,
        max_winners=2,
        budget=1_000,
    )
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.FIRST_PRICE_REVERSE_AUCTION,
        market_input=market_input,
    )
    cheapest_id = market_input.reported_offers[0].signed_offer.offer.merchant_id
    second_id = market_input.reported_offers[1].signed_offer.offer.merchant_id
    large_id = market_input.reported_offers[2].signed_offer.offer.merchant_id
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert result.fulfilled_quantity == 4
    assert result.total_payment.amount_paise == 301
    assert {line.merchant_id for line in result.lines} == {cheapest_id, large_id}
    assert {(line.merchant_id, line.allocated_quantity) for line in result.lines} == {
        (cheapest_id, 1),
        (large_id, 3),
    }
    naive_quantity = 1 + 1
    assert result.fulfilled_quantity > naive_quantity
    assert second_id not in {line.merchant_id for line in result.lines}


def test_hard_constraints_exclude_attractive_invalid_lines_for_every_baseline() -> None:
    hard = (_hard_rule("quality_score", 8, ComparisonOperator.GTE),)
    _, market_input = _market_input_fixture(
        "hard-safety",
        (
            _MerchantSpec("invalid", (_basic_sku("sku", 1, 1, _attribute("quality_score", 1)),)),
            _MerchantSpec("valid", (_basic_sku("sku", 20, 1, _attribute("quality_score", 8)),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=hard,
    )
    invalid_sku = market_input.reported_offers[0].signed_offer.offer.lines[0].sku_id
    for method in AgentMarketBenchBaselineV1:
        if method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE:
            continue
        result = run_agent_market_bench_method_v1(method=method, market_input=market_input)
        assert all(line.sku_id != invalid_sku for line in result.lines)


def test_below_minimum_collapses_to_the_exact_zero_result_for_all_baselines() -> None:
    _, market_input = _market_input_fixture(
        "below-minimum",
        (
            _MerchantSpec("only", (_basic_sku("sku", 10, 1),)),
            _MerchantSpec("empty", (_basic_sku("sku", 12, 1),)),
        ),
        requested_quantity=3,
        minimum_acceptable_quantity=3,
        max_winners=2,
        budget=100,
    )
    for method in AgentMarketBenchBaselineV1:
        if method in (
            AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
            AgentMarketBenchBaselineV1.REVERSE_VICKREY,
        ):
            continue
        result = run_agent_market_bench_method_v1(method=method, market_input=market_input)
        assert result.status is AgentMarketBenchMethodStatusV1.INFEASIBLE
        assert result.fulfilled_quantity == 0
        assert result.total_payment.amount_paise == 0
        assert result.winner_count == 0
        assert result.lines == ()


def test_reverse_vickrey_requires_identical_typed_relevant_attributes() -> None:
    hard = (_hard_rule("quality_score", 8, ComparisonOperator.GTE),)
    soft = (_soft_rule("eco_certified", True, ComparisonOperator.EQ),)
    _, applicable_input = _market_input_fixture(
        "vickrey-applicable",
        (
            _MerchantSpec(
                "a",
                (
                    _basic_sku(
                        "sku",
                        30,
                        1,
                        _attribute("quality_score", 8),
                        _attribute("eco_certified", True),
                    ),
                ),
            ),
            _MerchantSpec(
                "b",
                (
                    _basic_sku(
                        "sku",
                        40,
                        1,
                        _attribute("quality_score", 8),
                        _attribute("eco_certified", True),
                    ),
                ),
            ),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=hard,
        soft_preferences=soft,
    )
    applicable = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.REVERSE_VICKREY,
        market_input=applicable_input,
    )
    assert applicable.status is AgentMarketBenchMethodStatusV1.FEASIBLE

    _, different_input = _market_input_fixture(
        "vickrey-different",
        (
            _MerchantSpec(
                "a",
                (
                    _basic_sku(
                        "sku",
                        30,
                        1,
                        _attribute("quality_score", 8),
                        _attribute("eco_certified", True),
                    ),
                ),
            ),
            _MerchantSpec(
                "b",
                (
                    _basic_sku(
                        "sku",
                        40,
                        1,
                        _attribute("quality_score", 9),
                        _attribute("eco_certified", True),
                    ),
                ),
            ),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=hard,
        soft_preferences=soft,
    )
    assert (
        run_agent_market_bench_method_v1(
            method=AgentMarketBenchBaselineV1.REVERSE_VICKREY,
            market_input=different_input,
        ).status
        is AgentMarketBenchMethodStatusV1.NOT_APPLICABLE
    )

    _, missing_input = _market_input_fixture(
        "vickrey-missing",
        (
            _MerchantSpec("a", (_basic_sku("sku", 30, 1, _attribute("quality_score", 8)),)),
            _MerchantSpec("b", (_basic_sku("sku", 40, 1, _attribute("quality_score", 8)),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=hard,
        soft_preferences=soft,
    )
    assert (
        run_agent_market_bench_method_v1(
            method=AgentMarketBenchBaselineV1.REVERSE_VICKREY,
            market_input=missing_input,
        ).status
        is AgentMarketBenchMethodStatusV1.NOT_APPLICABLE
    )


def test_generated_multi_unit_case_is_not_reverse_vickrey_applicable() -> None:
    market_input = agent_market_bench_market_input_v1(generate_agent_market_bench_case_v1(_START))
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.REVERSE_VICKREY,
        market_input=market_input,
    )
    assert result.status is AgentMarketBenchMethodStatusV1.NOT_APPLICABLE


def test_admission_classifies_unknown_source_before_authentication() -> None:
    policy, market_input = _market_input_fixture(
        "admission-unknown",
        (
            _MerchantSpec("known", (_basic_sku("sku", 10, 1),)),
            _MerchantSpec("unknown", (_basic_sku("sku", 11, 1),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
    )
    unknown_report = market_input.reported_offers[1].model_copy(update={"submission_index": 0})
    reduced_input = AgentMarketBenchMarketInputV1(
        buyer_policy=policy,
        observed_merchants=(market_input.observed_merchants[0],),
        reported_offers=(unknown_report,),
    )
    admission = admit_agent_market_bench_market_input_v1(reduced_input)
    assert (
        admission.rejections[0].reason
        is AgentMarketBenchAdmissionRejectionReasonV1.UNKNOWN_MERCHANT
    )


def test_admission_classifies_valid_signature_with_mismatched_source_as_authentication_failed() -> (
    None
):
    policy, market_input = _market_input_fixture(
        "admission-source-mismatch",
        (
            _MerchantSpec("one", (_basic_sku("sku", 10, 1),)),
            _MerchantSpec("two", (_basic_sku("sku", 11, 1),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
    )
    original = market_input.observed_merchants[0]
    changed_product = original.catalog.products[0].model_copy(update={"description": "changed"})
    changed_catalog = MerchantCatalogV2(
        catalog_id=original.catalog.catalog_id,
        merchant_id=original.catalog.merchant_id,
        generated_at=original.catalog.generated_at,
        products=(changed_product,),
        skus=original.catalog.skus,
    )
    changed_observed = AgentMarketBenchObservedMerchantV1(
        merchant_id=original.merchant_id,
        catalog=changed_catalog,
        inventory_snapshot=original.inventory_snapshot,
        signing_identity=original.signing_identity,
    )
    malformed_input = AgentMarketBenchMarketInputV1(
        buyer_policy=policy,
        observed_merchants=(changed_observed, market_input.observed_merchants[1]),
        reported_offers=(market_input.reported_offers[0],),
    )
    admission = admit_agent_market_bench_market_input_v1(malformed_input)
    assert (
        admission.rejections[0].reason
        is AgentMarketBenchAdmissionRejectionReasonV1.AUTHENTICATION_FAILED
    )


def test_admission_rejects_second_authenticated_offer_from_same_merchant() -> None:
    policy, market_input = _market_input_fixture(
        "admission-duplicate-merchant",
        (
            _MerchantSpec("one", (_basic_sku("sku", 10, 1),)),
            _MerchantSpec("two", (_basic_sku("sku", 11, 1),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
    )
    key = _fixture_key("admission-duplicate-merchant|key|one")
    second_offer = _resign_offer(
        market_input.reported_offers[0].signed_offer,
        offer_id=_fixture_uuid("admission-duplicate-merchant|second-offer"),
        private_key=key,
    )
    duplicate_input = AgentMarketBenchMarketInputV1(
        buyer_policy=policy,
        observed_merchants=market_input.observed_merchants,
        reported_offers=(
            market_input.reported_offers[0],
            AgentMarketBenchReportedOfferV1(
                submission_index=1,
                received_at=datetime(2030, 1, 1, 11, 0, 1, tzinfo=UTC),
                signed_offer=second_offer,
            ),
        ),
    )
    admission = admit_agent_market_bench_market_input_v1(duplicate_input)
    assert admission.admitted_submission_indices == (0,)
    assert (
        admission.rejections[0].reason
        is AgentMarketBenchAdmissionRejectionReasonV1.DUPLICATE_MERCHANT
    )


def test_admission_duplicate_offer_id_precedes_duplicate_merchant_and_is_deterministic() -> None:
    policy, market_input = _market_input_fixture(
        "admission-replay",
        (
            _MerchantSpec("one", (_basic_sku("sku", 10, 1),)),
            _MerchantSpec("two", (_basic_sku("sku", 11, 1),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
    )
    replay_input = AgentMarketBenchMarketInputV1(
        buyer_policy=policy,
        observed_merchants=market_input.observed_merchants,
        reported_offers=(
            market_input.reported_offers[0],
            market_input.reported_offers[0].model_copy(update={"submission_index": 1}),
        ),
    )
    first = admit_agent_market_bench_market_input_v1(replay_input)
    second = admit_agent_market_bench_market_input_v1(replay_input)
    assert first == second
    assert (
        first.rejections[0].reason is AgentMarketBenchAdmissionRejectionReasonV1.DUPLICATE_OFFER_ID
    )
