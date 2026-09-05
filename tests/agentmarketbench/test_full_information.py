import inspect

import pytest

from clear_market.agentmarketbench.full_information import (
    run_agent_market_bench_full_information_oracle_v1,
)
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.method_models import AgentMarketBenchMethodStatusV1
from clear_market.agentmarketbench.methods import run_agent_market_bench_method_v1
from clear_market.agentmarketbench.models import (
    AgentMarketBenchBaselineV1,
    AgentMarketBenchCaseV1,
    AgentMarketBenchLatentAttributeV1,
    AgentMarketBenchLatentLineV1,
)
from clear_market.agentmarketbench.protocol import agent_market_bench_market_input_v1
from clear_market.commerce import AttributeValue, ComparisonOperator, ProvenanceLabel
from clear_market.domain import Money

from .test_methods import (
    _attribute,
    _fixture_uuid,
    _hard_rule,
    _market_input_fixture,
    _MerchantSpec,
    _SkuSpec,
    _soft_rule,
)

_START = 100_000_000


def _oracle_case_fixture(
    label: str,
    merchants: tuple[_MerchantSpec, ...],
    *,
    requested_quantity: int,
    minimum_acceptable_quantity: int,
    max_winners: int,
    budget: int,
    hard_constraints: tuple = (),
    soft_preferences: tuple = (),
    true_quantities: dict[tuple[int, int], int] | None = None,
    true_costs: dict[tuple[int, int], int] | None = None,
    true_values: dict[tuple[int, int], int] | None = None,
    latent_attribute_values: dict[tuple[int, int, str], object] | None = None,
) -> AgentMarketBenchCaseV1:
    policy, market_input = _market_input_fixture(
        label,
        merchants,
        requested_quantity=requested_quantity,
        minimum_acceptable_quantity=minimum_acceptable_quantity,
        max_winners=max_winners,
        budget=budget,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
    )
    true_quantities = true_quantities or {}
    true_costs = true_costs or {}
    true_values = true_values or {}
    latent_attribute_values = latent_attribute_values or {}
    latent_lines = []
    for merchant_index, (merchant, observed) in enumerate(
        zip(merchants, market_input.observed_merchants, strict=True)
    ):
        for sku_index, (sku_spec, catalog_sku) in enumerate(
            zip(merchant.skus, observed.catalog.skus, strict=True)
        ):
            true_attributes = tuple(
                AgentMarketBenchLatentAttributeV1(
                    attribute_key=attribute.attribute_key,
                    value=AttributeValue(
                        value_type=attribute.value.value_type,
                        value=latent_attribute_values.get(
                            (merchant_index, sku_index, attribute.attribute_key),
                            attribute.value.value,
                        ),
                    ),
                )
                for attribute in catalog_sku.attributes
            )
            true_cost = true_costs.get((merchant_index, sku_index), sku_spec.ask)
            true_value = true_values.get((merchant_index, sku_index), true_cost + 10)
            latent_lines.append(
                AgentMarketBenchLatentLineV1(
                    economic_principal_id=_fixture_uuid(f"{label}|principal|{merchant_index}"),
                    merchant_id=observed.merchant_id,
                    sku_id=catalog_sku.sku_id,
                    true_available_quantity=true_quantities.get(
                        (merchant_index, sku_index), sku_spec.quantity
                    ),
                    true_unit_cost=Money(amount_paise=true_cost),
                    true_unit_buyer_value=Money(amount_paise=true_value),
                    true_attributes=true_attributes,
                )
            )
    return AgentMarketBenchCaseV1(
        seed=1,
        case_id=_fixture_uuid(f"{label}|case"),
        buyer_text=f"deterministic oracle fixture {label}",
        buyer_policy=policy,
        observed_merchants=market_input.observed_merchants,
        latent_lines=tuple(latent_lines),
        reported_offers=market_input.reported_offers,
        adversarial_scenarios=(),
    )


def test_oracle_requires_exact_case_and_methods_cannot_run_it() -> None:
    case = generate_agent_market_bench_case_v1(_START)
    with pytest.raises(TypeError):
        run_agent_market_bench_full_information_oracle_v1(case.model_dump())
    with pytest.raises(ValueError, match="case-aware"):
        run_agent_market_bench_method_v1(
            method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
            market_input=agent_market_bench_market_input_v1(case),
        )


def test_oracle_is_deterministic_and_uses_only_latent_source_offer_free_lines() -> None:
    for seed in range(_START, _START + 42):
        case = generate_agent_market_bench_case_v1(seed)
        first = run_agent_market_bench_full_information_oracle_v1(case)
        second = run_agent_market_bench_full_information_oracle_v1(case)
        assert first == second
        assert first.method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE
        assert first.status in tuple(AgentMarketBenchMethodStatusV1)
        assert all(line.source_offer_id is None for line in first.lines)
        assert first.fulfilled_quantity <= case.buyer_policy.market_spec.requested_quantity
        assert first.winner_count <= case.buyer_policy.market_spec.max_winners
        latent_by_key = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
        for line in first.lines:
            assert (
                line.allocated_quantity
                <= latent_by_key[(line.merchant_id, line.sku_id)].true_available_quantity
            )


def test_oracle_reuses_public_admission_summary() -> None:
    case = generate_agent_market_bench_case_v1(_START + 27)  # altered offer
    oracle = run_agent_market_bench_full_information_oracle_v1(case)
    public = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.CLEAR,
        market_input=agent_market_bench_market_input_v1(case),
    )
    assert oracle.admission == public.admission
    assert len(oracle.admission.rejections) == 1


def test_oracle_module_has_no_production_allocator_or_oracle_dependency() -> None:
    source = inspect.getsource(
        __import__("clear_market.agentmarketbench.full_information", fromlist=["x"])
    )
    for forbidden in (
        "ortools",
        "allocate_market_v2",
        "clear_market.oracle.v2",
        "agentmarketbench.generator",
        "agentmarketbench.seeds",
        "clear_market.benchmark",
        "payments",
        "Razorpay",
        "clear_market.ai",
        "persistence",
        "execution",
    ):
        assert forbidden not in source


def test_oracle_excludes_the_missing_seller_in_dropout_case() -> None:
    case = generate_agent_market_bench_case_v1(
        next(
            seed
            for seed in range(_START, _START + 42)
            if generate_agent_market_bench_case_v1(seed).adversarial_scenarios
            and generate_agent_market_bench_case_v1(seed).adversarial_scenarios[0].name
            == "SELLER_DROPOUT"
        )
    )
    reported_merchants = {report.signed_offer.offer.merchant_id for report in case.reported_offers}
    missing_merchants = {
        merchant.merchant_id
        for merchant in case.observed_merchants
        if merchant.merchant_id not in reported_merchants
    }
    oracle = run_agent_market_bench_full_information_oracle_v1(case)
    assert len(missing_merchants) == 1
    assert all(line.merchant_id not in missing_merchants for line in oracle.lines)


def test_oracle_caps_fake_inventory_at_latent_quantity() -> None:
    case = generate_agent_market_bench_case_v1(
        next(
            seed
            for seed in range(_START, _START + 42)
            if generate_agent_market_bench_case_v1(seed).adversarial_scenarios
            and generate_agent_market_bench_case_v1(seed).adversarial_scenarios[0].name
            == "FAKE_INVENTORY"
        )
    )
    latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
    oracle = run_agent_market_bench_full_information_oracle_v1(case)
    inflated = []
    for merchant in case.observed_merchants:
        for inventory_line in merchant.inventory_snapshot.lines:
            latent_line = latent[(merchant.merchant_id, inventory_line.sku_id)]
            if inventory_line.quantity_available == latent_line.true_available_quantity + 3:
                inflated.append((merchant.merchant_id, inventory_line.sku_id, latent_line))
    assert len(inflated) == 1
    for merchant_id, sku_id, latent_line in inflated:
        allocations = [
            line.allocated_quantity
            for line in oracle.lines
            if line.merchant_id == merchant_id and line.sku_id == sku_id
        ]
        assert sum(allocations) <= latent_line.true_available_quantity


def test_oracle_uses_exact_latent_cost_as_reference_payment_and_respects_bounds() -> None:
    case = _oracle_case_fixture(
        "oracle-cost-payment",
        (
            _MerchantSpec("a", (_SkuSpec("sku", 20, 2, ()),)),
            _MerchantSpec("b", (_SkuSpec("sku", 25, 2, ()),)),
        ),
        requested_quantity=3,
        minimum_acceptable_quantity=2,
        max_winners=2,
        budget=100,
        true_quantities={(0, 0): 2, (1, 0): 2},
        true_costs={(0, 0): 7, (1, 0): 9},
        true_values={(0, 0): 20, (1, 0): 21},
    )
    result = run_agent_market_bench_full_information_oracle_v1(case)
    latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert case.buyer_policy.market_spec.minimum_acceptable_quantity <= result.fulfilled_quantity
    assert result.fulfilled_quantity <= case.buyer_policy.market_spec.requested_quantity
    assert result.winner_count <= case.buyer_policy.market_spec.max_winners
    assert result.total_payment.amount_paise <= case.buyer_policy.max_total_payment.amount_paise
    for line in result.lines:
        source = latent[(line.merchant_id, line.sku_id)]
        assert line.unit_payment.amount_paise == source.true_unit_cost.amount_paise
        assert (
            line.line_payment.amount_paise
            == source.true_unit_cost.amount_paise * line.allocated_quantity
        )
    assert result.total_payment.amount_paise == sum(
        line.line_payment.amount_paise for line in result.lines
    )


def test_oracle_uses_latent_hard_constraint_value() -> None:
    hard = (_hard_rule("quality_score", 8, ComparisonOperator.GTE),)
    case = _oracle_case_fixture(
        "oracle-latent-hard",
        (
            _MerchantSpec("target", (_SkuSpec("sku", 10, 1, (_attribute("quality_score", 10),)),)),
            _MerchantSpec("other", (_SkuSpec("sku", 30, 1, (_attribute("quality_score", 10),)),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=hard,
        latent_attribute_values={(0, 0, "quality_score"): 1},
    )
    target_sku = next(
        line.sku_id
        for line in case.latent_lines
        if next(attribute.value.value for attribute in line.true_attributes) == 1
    )
    result = run_agent_market_bench_full_information_oracle_v1(case)
    assert all(line.sku_id != target_sku for line in result.lines)


def test_oracle_ignores_reported_provenance_allowlist_for_latent_matching() -> None:
    hard = (
        _hard_rule(
            "quality_score",
            8,
            ComparisonOperator.GTE,
            allowed_provenance=(ProvenanceLabel.VERIFIED,),
        ),
    )
    case = _oracle_case_fixture(
        "oracle-provenance-ignore",
        (
            _MerchantSpec("target", (_SkuSpec("sku", 20, 1, (_attribute("quality_score", 9),)),)),
            _MerchantSpec("other", (_SkuSpec("sku", 30, 1, (_attribute("quality_score", 1),)),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=hard,
    )
    target_sku = next(
        line.sku_id
        for line in case.latent_lines
        if next(attribute.value.value for attribute in line.true_attributes) == 9
    )
    result = run_agent_market_bench_full_information_oracle_v1(case)
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert result.lines[0].sku_id == target_sku


def test_oracle_welfare_precedes_cheapest_reported_ask() -> None:
    case = _oracle_case_fixture(
        "oracle-welfare-first",
        (
            _MerchantSpec("cheap", (_SkuSpec("sku", 1, 1, ()),)),
            _MerchantSpec("valuable", (_SkuSpec("sku", 10, 1, ()),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 1, (1, 0): 10},
        true_values={(0, 0): 2, (1, 0): 100},
    )
    result = run_agent_market_bench_full_information_oracle_v1(case)
    valuable_sku = case.observed_merchants[1].catalog.skus[0].sku_id
    assert result.lines[0].sku_id == valuable_sku
    assert result.total_payment.amount_paise == 10


def test_oracle_tie_breakers_are_isolated_in_frozen_order() -> None:
    welfare_case = _oracle_case_fixture(
        "oracle-tie-welfare",
        (
            _MerchantSpec("one", (_SkuSpec("sku", 1, 1, ()),)),
            _MerchantSpec("two", (_SkuSpec("sku", 2, 2, ()),)),
        ),
        requested_quantity=2,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 1, (1, 0): 2},
        true_values={(0, 0): 11, (1, 0): 6},
    )
    welfare_result = run_agent_market_bench_full_information_oracle_v1(welfare_case)
    assert welfare_result.fulfilled_quantity == 1
    assert welfare_result.lines[0].merchant_id == welfare_case.observed_merchants[0].merchant_id

    quantity_case = _oracle_case_fixture(
        "oracle-tie-quantity",
        (
            _MerchantSpec("one", (_SkuSpec("sku", 1, 1, ()),)),
            _MerchantSpec("two", (_SkuSpec("sku", 2, 2, ()),)),
        ),
        requested_quantity=2,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 1, (1, 0): 2},
        true_values={(0, 0): 5, (1, 0): 4},
    )
    quantity_result = run_agent_market_bench_full_information_oracle_v1(quantity_case)
    assert quantity_result.fulfilled_quantity == 2
    assert quantity_result.lines[0].merchant_id == quantity_case.observed_merchants[1].merchant_id

    soft = (_soft_rule("quality_score", 8, ComparisonOperator.GTE),)
    soft_case = _oracle_case_fixture(
        "oracle-tie-soft",
        (
            _MerchantSpec("one", (_SkuSpec("sku", 5, 1, (_attribute("quality_score", 9),)),)),
            _MerchantSpec("two", (_SkuSpec("sku", 5, 1, (_attribute("quality_score", 1),)),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        soft_preferences=soft,
        true_costs={(0, 0): 5, (1, 0): 5},
        true_values={(0, 0): 10, (1, 0): 10},
    )
    soft_result = run_agent_market_bench_full_information_oracle_v1(soft_case)
    soft_target = next(
        line.merchant_id
        for line in soft_case.latent_lines
        if next(attribute.value.value for attribute in line.true_attributes) == 9
    )
    assert soft_result.lines[0].merchant_id == soft_target

    cost_case = _oracle_case_fixture(
        "oracle-tie-cost",
        (
            _MerchantSpec("one", (_SkuSpec("sku", 5, 1, ()),)),
            _MerchantSpec("two", (_SkuSpec("sku", 5, 1, ()),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 3, (1, 0): 4},
        true_values={(0, 0): 13, (1, 0): 14},
    )
    cost_result = run_agent_market_bench_full_information_oracle_v1(cost_case)
    cost_target = next(
        line.merchant_id for line in cost_case.latent_lines if line.true_unit_cost.amount_paise == 3
    )
    assert cost_result.lines[0].merchant_id == cost_target

    vector_case = _oracle_case_fixture(
        "oracle-tie-vector",
        (
            _MerchantSpec("one", (_SkuSpec("sku", 5, 1, ()),)),
            _MerchantSpec("two", (_SkuSpec("sku", 5, 1, ()),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 5, (1, 0): 5},
        true_values={(0, 0): 15, (1, 0): 15},
    )
    vector_result = run_agent_market_bench_full_information_oracle_v1(vector_case)
    expected_id = min(merchant.merchant_id for merchant in vector_case.observed_merchants)
    assert vector_result.lines[0].merchant_id == expected_id
