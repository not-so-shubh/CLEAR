"""Tests for the deterministic AgentMarketBench V1 generator."""

import json
from datetime import timedelta
from hashlib import sha256

import pytest

from clear_market.agentmarketbench import (
    AGENT_MARKET_BENCH_GENERATOR_V1_VERSION,
    AgentMarketBenchAdversarialScenarioV1,
    agent_market_bench_case_v1_digest,
    agent_market_bench_market_input_v1,
    canonical_agent_market_bench_case_v1_bytes,
)
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.models import AgentMarketBenchCaseV1
from clear_market.commerce import (
    AttributeValueType,
    MerchantOfferVerificationError,
    MerchantOfferVerificationErrorCode,
    buyer_policy_v2_commitment,
    canonical_signed_merchant_offer_v2_bytes,
    inventory_snapshot_v2_commitment,
    merchant_catalog_v2_commitment,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.mechanism.v2.contracts import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
)

from .test_protocol import _fixture

_DEVELOPMENT_START = 100_000_000
_FIRST_CYCLE = tuple(range(_DEVELOPMENT_START, _DEVELOPMENT_START + 42))
_RUNTIME_ONLY = {
    AgentMarketBenchAdversarialScenarioV1.DUPLICATE_EVENT,
    AgentMarketBenchAdversarialScenarioV1.EVENT_REORDERING,
    AgentMarketBenchAdversarialScenarioV1.PROVIDER_TIMEOUT,
    AgentMarketBenchAdversarialScenarioV1.PAYMENT_FAILURE,
    AgentMarketBenchAdversarialScenarioV1.TRANSFER_FAILURE,
    AgentMarketBenchAdversarialScenarioV1.RETRY,
    AgentMarketBenchAdversarialScenarioV1.RECONCILIATION,
    AgentMarketBenchAdversarialScenarioV1.RECOVERY,
}


def _scenario_seed(scenario: AgentMarketBenchAdversarialScenarioV1) -> int:
    for seed in _FIRST_CYCLE:
        case = generate_agent_market_bench_case_v1(seed)
        if case.adversarial_scenarios == (scenario,):
            return seed
    raise AssertionError(f"no development seed for {scenario}")


def _observed_by_merchant(case: AgentMarketBenchCaseV1):
    return {merchant.merchant_id: merchant for merchant in case.observed_merchants}


def _verify_present_offers(case: AgentMarketBenchCaseV1) -> None:
    observed = _observed_by_merchant(case)
    for report in case.reported_offers:
        merchant = observed[report.signed_offer.offer.merchant_id]
        verified = verify_canonical_signed_merchant_offer_v2(
            data=canonical_signed_merchant_offer_v2_bytes(report.signed_offer),
            signing_identity=merchant.signing_identity,
            buyer_policy=case.buyer_policy,
            catalog=merchant.catalog,
            inventory=merchant.inventory_snapshot,
        )
        assert verified == report.signed_offer


def test_generator_rejects_invalid_seed_types_and_ranges() -> None:
    with pytest.raises(TypeError):
        generate_agent_market_bench_case_v1(True)
    with pytest.raises(TypeError):
        generate_agent_market_bench_case_v1("100000000")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        generate_agent_market_bench_case_v1(-1)
    with pytest.raises(ValueError):
        generate_agent_market_bench_case_v1(2_147_483_648)


def test_same_seed_is_exactly_reproducible() -> None:
    first = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    second = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    assert first == second
    assert canonical_agent_market_bench_case_v1_bytes(
        first
    ) == canonical_agent_market_bench_case_v1_bytes(second)
    assert agent_market_bench_case_v1_digest(first) == agent_market_bench_case_v1_digest(second)


def test_different_development_seeds_change_identity() -> None:
    first = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    second = generate_agent_market_bench_case_v1(_DEVELOPMENT_START + 1)
    assert first.case_id != second.case_id
    assert agent_market_bench_case_v1_digest(first) != agent_market_bench_case_v1_digest(second)


def test_generated_versions_and_production_mechanism_contract_are_exact() -> None:
    case = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    assert case.generator_version == AGENT_MARKET_BENCH_GENERATOR_V1_VERSION
    assert case.buyer_policy.mechanism_version == HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION
    assert case.buyer_policy.objective_version == QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION


def test_generated_market_shape_and_latent_key_space() -> None:
    for seed in _FIRST_CYCLE[:12]:
        case = generate_agent_market_bench_case_v1(seed)
        assert 3 <= len(case.observed_merchants) <= 7
        assert all(1 <= len(merchant.catalog.skus) <= 3 for merchant in case.observed_merchants)
        observed_keys = {
            (merchant.merchant_id, sku.sku_id)
            for merchant in case.observed_merchants
            for sku in merchant.catalog.skus
        }
        latent_keys = {(line.merchant_id, line.sku_id) for line in case.latent_lines}
        assert latent_keys == observed_keys
        assert 4 <= case.buyer_policy.market_spec.requested_quantity <= 12
        assert (
            1
            <= case.buyer_policy.market_spec.max_winners
            <= min(
                4, len(case.observed_merchants), case.buyer_policy.market_spec.requested_quantity
            )
        )


def test_generated_cases_pass_market_input_firewall_and_hide_private_state() -> None:
    case = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    market_input = agent_market_bench_market_input_v1(case)
    market_json = json.dumps(
        market_input.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    case_json = json.dumps(case.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    assert json.loads(market_json) == market_input.model_dump(mode="json")
    assert json.loads(case_json) == case.model_dump(mode="json")
    for forbidden in (
        "seed",
        "case_id",
        "buyer_text",
        "latent_lines",
        "adversarial_scenarios",
        "economic_principal_id",
        "true_unit_cost",
        "true_unit_buyer_value",
        "true_available_quantity",
        "economic_policy",
        "private_key",
    ):
        assert forbidden not in market_json
    assert "economic_policy" not in case_json
    assert "private_key" not in case_json
    for merchant_index in range(len(case.observed_merchants)):
        private_seed = sha256(
            f"{AGENT_MARKET_BENCH_GENERATOR_V1_VERSION}|merchant-key|seed={case.seed}|"
            f"merchant_index={merchant_index}".encode("ascii")
        ).digest()
        assert private_seed not in case_json.encode("utf-8")
        assert private_seed.hex() not in case_json
        assert private_seed not in market_json.encode("utf-8")
        assert private_seed.hex() not in market_json


def test_normal_offers_authenticate_and_commit_to_exact_sources() -> None:
    case = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    _verify_present_offers(case)
    observed = _observed_by_merchant(case)
    for report in case.reported_offers:
        merchant = observed[report.signed_offer.offer.merchant_id]
        offer = report.signed_offer.offer
        assert offer.buyer_policy_commitment_sha256 == buyer_policy_v2_commitment(case.buyer_policy)
        assert offer.merchant_catalog_commitment_sha256 == merchant_catalog_v2_commitment(
            merchant.catalog
        )
        assert offer.inventory_snapshot_commitment_sha256 == inventory_snapshot_v2_commitment(
            merchant.inventory_snapshot
        )


def test_normal_receipts_are_before_deadline_and_indexes_are_contiguous() -> None:
    case = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    assert tuple(report.submission_index for report in case.reported_offers) == tuple(
        range(len(case.reported_offers))
    )
    assert all(
        report.received_at < case.buyer_policy.offer_deadline for report in case.reported_offers
    )


def test_24a_standard_candidate_golden_is_unchanged() -> None:
    candidate, _ = _fixture()
    assert len(canonical_agent_market_bench_case_v1_bytes(candidate)) == 12004
    assert agent_market_bench_case_v1_digest(candidate) == (
        "9b37bb9e79aad00515e3c2b1c53253c10faecef355d9a5872ba987b535bbc128"
    )


@pytest.mark.parametrize(
    ("seed", "expected_length", "expected_digest"),
    (
        (
            100_000_000,
            75_487,
            "adddf847fb36bd38734eabea30483ce4b7bc1cd88838a50953967f43638e382e",
        ),
        (
            100_000_001,
            24_405,
            "5cb0431d86b366c796196a480ce025259a576654bcd0c345ef918e0cfc6706c4",
        ),
        (
            100_000_002,
            43_895,
            "42671dfa08cdd0a97afddf1a39a0ca3f0d2a9c70115019cfaf59f798ac63e281",
        ),
    ),
)
def test_development_generator_golden_vectors(
    seed: int, expected_length: int, expected_digest: str
) -> None:
    case = generate_agent_market_bench_case_v1(seed)
    assert len(canonical_agent_market_bench_case_v1_bytes(case)) == expected_length
    assert agent_market_bench_case_v1_digest(case) == expected_digest


def test_first_development_cycle_has_exact_scenario_balance() -> None:
    cases = [generate_agent_market_bench_case_v1(seed) for seed in _FIRST_CYCLE]
    standard = [case for case in cases if case.adversarial_scenarios == ()]
    labelled = [case.adversarial_scenarios[0] for case in cases if case.adversarial_scenarios]
    assert len(standard) == 21
    assert len(labelled) == 21
    assert set(labelled) == set(AgentMarketBenchAdversarialScenarioV1)
    assert all(labelled.count(scenario) == 1 for scenario in AgentMarketBenchAdversarialScenarioV1)


def test_scenario_assignment_is_exact_for_first_cycle() -> None:
    scenarios = tuple(AgentMarketBenchAdversarialScenarioV1)
    for offset in range(21):
        seed = _DEVELOPMENT_START + 1 + (2 * offset)
        expected = scenarios[((seed // 2) % len(scenarios))]
        assert generate_agent_market_bench_case_v1(seed).adversarial_scenarios == (expected,)


@pytest.mark.parametrize("scenario", tuple(AgentMarketBenchAdversarialScenarioV1))
def test_each_scenario_has_frozen_case_level_semantics(
    scenario: AgentMarketBenchAdversarialScenarioV1,
) -> None:
    case = generate_agent_market_bench_case_v1(_scenario_seed(scenario))
    assert case.adversarial_scenarios == (scenario,)
    observed = _observed_by_merchant(case)
    reports_by_merchant = {
        report.signed_offer.offer.merchant_id: report for report in case.reported_offers
    }

    if scenario in {
        AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER,
        AgentMarketBenchAdversarialScenarioV1.FORGED_MERCHANT,
    }:
        failures = []
        for report in case.reported_offers:
            merchant = observed[report.signed_offer.offer.merchant_id]
            try:
                verify_canonical_signed_merchant_offer_v2(
                    data=canonical_signed_merchant_offer_v2_bytes(report.signed_offer),
                    signing_identity=merchant.signing_identity,
                    buyer_policy=case.buyer_policy,
                    catalog=merchant.catalog,
                    inventory=merchant.inventory_snapshot,
                )
            except MerchantOfferVerificationError as error:
                failures.append((report, error.code))
        assert len(failures) == 1
        assert failures[0][1] is MerchantOfferVerificationErrorCode.INVALID_SIGNATURE
        return

    _verify_present_offers(case)
    if scenario is AgentMarketBenchAdversarialScenarioV1.LATE_OFFER:
        late_reports = [
            report
            for report in case.reported_offers
            if report.received_at > case.buyer_policy.offer_deadline
        ]
        assert len(late_reports) == 1
        assert late_reports[0].received_at == case.buyer_policy.offer_deadline + timedelta(
            seconds=1
        )
        assert all(
            report.received_at < case.buyer_policy.offer_deadline
            for report in case.reported_offers
            if report is not late_reports[0]
        )
    elif scenario is AgentMarketBenchAdversarialScenarioV1.REPLAYED_OFFER:
        assert len(case.reported_offers) == len(case.observed_merchants) + 1
        signed_bytes = [
            canonical_signed_merchant_offer_v2_bytes(report.signed_offer)
            for report in case.reported_offers
        ]
        assert len(set(signed_bytes)) < len(signed_bytes)
    elif scenario is AgentMarketBenchAdversarialScenarioV1.SELLER_DROPOUT:
        assert len(case.reported_offers) == len(case.observed_merchants) - 1
    elif scenario is AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY:
        latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
        divergences = []
        for merchant in case.observed_merchants:
            for inventory_line in merchant.inventory_snapshot.lines:
                true_quantity = latent[
                    (merchant.merchant_id, inventory_line.sku_id)
                ].true_available_quantity
                if inventory_line.quantity_available > true_quantity:
                    report = reports_by_merchant[merchant.merchant_id]
                    offered = next(
                        line
                        for line in report.signed_offer.offer.lines
                        if line.sku_id == inventory_line.sku_id
                    )
                    divergences.append(
                        (
                            inventory_line.quantity_available,
                            true_quantity,
                            offered.max_offer_quantity,
                        )
                    )
        assert divergences and all(
            reported == true + 3 == offered for reported, true, offered in divergences
        )
    elif scenario is AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE:
        latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
        assert any(
            next(
                attribute.value.value
                for attribute in sku.attributes
                if attribute.attribute_key == "sla_days"
            )
            == 1
            and next(
                attribute.value.value
                for attribute in latent[(merchant.merchant_id, sku.sku_id)].true_attributes
                if attribute.attribute_key == "sla_days"
            )
            == 7
            for merchant in case.observed_merchants
            for sku in merchant.catalog.skus
        )
    elif scenario is AgentMarketBenchAdversarialScenarioV1.SYBIL_SENSITIVITY:
        assert len({line.economic_principal_id for line in case.latent_lines}) < len(
            case.observed_merchants
        )
        assert len({merchant.merchant_id for merchant in case.observed_merchants}) == len(
            case.observed_merchants
        )
        assert len(
            {
                merchant.signing_identity.ed25519_public_key_hex
                for merchant in case.observed_merchants
            }
        ) == len(case.observed_merchants)
    elif scenario is AgentMarketBenchAdversarialScenarioV1.COLLUSION_SENSITIVITY:
        assert len({line.economic_principal_id for line in case.latent_lines}) == len(
            case.observed_merchants
        )
        assert (
            sum(
                line.unit_price.amount_paise == 3_500
                for report in case.reported_offers
                for line in report.signed_offer.offer.lines
            )
            >= 2
        )
    elif scenario in _RUNTIME_ONLY:
        method_json = json.dumps(
            agent_market_bench_market_input_v1(case).model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert scenario.value not in method_json
        assert all(
            field not in method_json for field in ("webhook", "transfer_event", "provider_event")
        )
    elif scenario in {
        AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
        AgentMarketBenchAdversarialScenarioV1.MALICIOUS_CATALOG_TEXT,
        AgentMarketBenchAdversarialScenarioV1.SCHEMA_MANIPULATION,
    }:
        descriptions = [
            product.description
            for merchant in case.observed_merchants
            for product in merchant.catalog.products
        ]
        assert any(
            description != "Synthetic catalog product description." for description in descriptions
        )
        assert all(scenario.value not in description for description in descriptions)
    elif scenario is AgentMarketBenchAdversarialScenarioV1.STRATEGIC_SHADING:
        latent_costs = {
            (line.merchant_id, line.sku_id): line.true_unit_cost.amount_paise
            for line in case.latent_lines
        }
        assert any(
            line.unit_price.amount_paise
            - latent_costs[(report.signed_offer.offer.merchant_id, line.sku_id)]
            == 1_500
            for report in case.reported_offers
            for line in report.signed_offer.offer.lines
        )


def test_runtime_labels_do_not_add_case_or_provider_fields() -> None:
    case_fields = set(AgentMarketBenchCaseV1.model_fields)
    for scenario in _RUNTIME_ONLY:
        case = generate_agent_market_bench_case_v1(_scenario_seed(scenario))
        assert set(case.model_dump(mode="python")) == case_fields
        method_input = agent_market_bench_market_input_v1(case)
        assert set(method_input.model_dump(mode="python")) == {
            "schema_version",
            "agent_market_bench_market_input_version",
            "buyer_policy",
            "observed_merchants",
            "reported_offers",
        }


def test_buyer_text_contains_policy_evidence_without_hidden_metadata() -> None:
    case = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    assert str(case.seed) not in case.buyer_text
    assert case.case_id not in case.buyer_text
    assert all(
        scenario.value not in case.buyer_text for scenario in AgentMarketBenchAdversarialScenarioV1
    )
    assert all(line.economic_principal_id not in case.buyer_text for line in case.latent_lines)
    assert "payment ceiling" in case.buyer_text


def test_development_digest_sample_is_unique() -> None:
    digests = {
        agent_market_bench_case_v1_digest(generate_agent_market_bench_case_v1(seed))
        for seed in _FIRST_CYCLE[:24]
    }
    assert len(digests) == 24


def test_attribute_contract_has_three_typed_keys() -> None:
    case = generate_agent_market_bench_case_v1(_DEVELOPMENT_START)
    for merchant in case.observed_merchants:
        for sku in merchant.catalog.skus:
            assert {attribute.attribute_key for attribute in sku.attributes} == {
                "quality_score",
                "sla_days",
                "eco_certified",
            }
            values = {
                attribute.attribute_key: attribute.value.value_type for attribute in sku.attributes
            }
            assert values == {
                "quality_score": AttributeValueType.INTEGER,
                "sla_days": AttributeValueType.INTEGER,
                "eco_certified": AttributeValueType.BOOLEAN,
            }
