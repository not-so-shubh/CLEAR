"""Contract and fresh-validation tests for AgentMarketBench models."""

import pytest
from pydantic import ValidationError

from clear_market.agentmarketbench import (
    AGENT_MARKET_BENCH_CASE_DIGEST_V1_VERSION,
    AGENT_MARKET_BENCH_CASE_V1_VERSION,
    AGENT_MARKET_BENCH_GENERATOR_V1_VERSION,
    AGENT_MARKET_BENCH_LATENT_ATTRIBUTE_V1_VERSION,
    AGENT_MARKET_BENCH_LATENT_LINE_V1_VERSION,
    AGENT_MARKET_BENCH_MARKET_INPUT_V1_VERSION,
    AGENT_MARKET_BENCH_OBSERVED_MERCHANT_V1_VERSION,
    AGENT_MARKET_BENCH_PROTOCOL_V1_VERSION,
    AGENT_MARKET_BENCH_REPORTED_OFFER_V1_VERSION,
    MAX_AGENT_MARKET_BENCH_SEED,
    AgentMarketBenchAdversarialClassificationV1,
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchCaseV1,
    AgentMarketBenchLatentAttributeV1,
    AgentMarketBenchLatentLineV1,
    AgentMarketBenchMarketInputV1,
    AgentMarketBenchMetricV1,
    AgentMarketBenchObservedMerchantV1,
    AgentMarketBenchReportedOfferV1,
)
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
)
from clear_market.commerce.authentication import MerchantSigningIdentityV2, SignedMerchantOfferV2
from clear_market.domain import Money

from .test_protocol import _fixture


def test_versions_and_enum_contracts_are_exact() -> None:
    assert {
        "protocol": AGENT_MARKET_BENCH_PROTOCOL_V1_VERSION,
        "generator": AGENT_MARKET_BENCH_GENERATOR_V1_VERSION,
        "case": AGENT_MARKET_BENCH_CASE_V1_VERSION,
        "market_input": AGENT_MARKET_BENCH_MARKET_INPUT_V1_VERSION,
        "latent_attribute": AGENT_MARKET_BENCH_LATENT_ATTRIBUTE_V1_VERSION,
        "latent_line": AGENT_MARKET_BENCH_LATENT_LINE_V1_VERSION,
        "observed_merchant": AGENT_MARKET_BENCH_OBSERVED_MERCHANT_V1_VERSION,
        "reported_offer": AGENT_MARKET_BENCH_REPORTED_OFFER_V1_VERSION,
        "case_digest": AGENT_MARKET_BENCH_CASE_DIGEST_V1_VERSION,
    } == {
        "protocol": "agent-market-bench-protocol-v1",
        "generator": "agent-market-bench-generator-v1",
        "case": "agent-market-bench-case-v1",
        "market_input": "agent-market-bench-market-input-v1",
        "latent_attribute": "agent-market-bench-latent-attribute-v1",
        "latent_line": "agent-market-bench-latent-line-v1",
        "observed_merchant": "agent-market-bench-observed-merchant-v1",
        "reported_offer": "agent-market-bench-reported-offer-v1",
        "case_digest": "sha256-agent-market-bench-case-v1-clear-json-v1",
    }
    assert MAX_AGENT_MARKET_BENCH_SEED == 2_147_483_647

    assert [(member.name, member.value) for member in AgentMarketBenchBaselineV1] == [
        ("RANDOM_QUALIFYING_SELLER", "RANDOM_QUALIFYING_SELLER"),
        ("CHEAPEST_QUALIFYING", "CHEAPEST_QUALIFYING"),
        ("STATIC_WEIGHTED_SCORE", "STATIC_WEIGHTED_SCORE"),
        ("BILATERAL_NEGOTIATION", "BILATERAL_NEGOTIATION"),
        ("SEQUENTIAL_NEGOTIATION", "SEQUENTIAL_NEGOTIATION"),
        ("FIRST_PRICE_REVERSE_AUCTION", "FIRST_PRICE_REVERSE_AUCTION"),
        ("REVERSE_VICKREY", "REVERSE_VICKREY"),
        ("CLEAR", "CLEAR"),
        ("FULL_INFORMATION_ORACLE", "FULL_INFORMATION_ORACLE"),
    ]
    assert [(member.name, member.value) for member in AgentMarketBenchMetricV1] == [
        ("ALLOCATIVE_EFFICIENCY", "ALLOCATIVE_EFFICIENCY"),
        ("REGRET", "REGRET"),
        ("BUYER_SURPLUS", "BUYER_SURPLUS"),
        ("MERCHANT_SURPLUS", "MERCHANT_SURPLUS"),
        ("WELFARE", "WELFARE"),
        ("COMPLETION", "COMPLETION"),
        ("HARD_CONSTRAINT_VIOLATIONS", "HARD_CONSTRAINT_VIOLATIONS"),
        ("MANIPULATION_SUCCESS", "MANIPULATION_SUCCESS"),
        ("PAYMENT_CORRECTNESS", "PAYMENT_CORRECTNESS"),
        ("DUPLICATE_FINANCIAL_SIDE_EFFECTS", "DUPLICATE_FINANCIAL_SIDE_EFFECTS"),
        ("LATENCY", "LATENCY"),
    ]
    assert [
        (member.name, member.value) for member in AgentMarketBenchAdversarialClassificationV1
    ] == [
        ("PREVENTED", "PREVENTED"),
        ("DETECTED", "DETECTED"),
        ("MITIGATED", "MITIGATED"),
        ("MEASURED", "MEASURED"),
        ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ]
    assert [(member.name, member.value) for member in AgentMarketBenchAdversarialScenarioV1] == [
        ("ALTERED_OFFER", "ALTERED_OFFER"),
        ("LATE_OFFER", "LATE_OFFER"),
        ("REPLAYED_OFFER", "REPLAYED_OFFER"),
        ("FORGED_MERCHANT", "FORGED_MERCHANT"),
        ("PROMPT_INJECTION", "PROMPT_INJECTION"),
        ("MALICIOUS_CATALOG_TEXT", "MALICIOUS_CATALOG_TEXT"),
        ("SCHEMA_MANIPULATION", "SCHEMA_MANIPULATION"),
        ("STRATEGIC_SHADING", "STRATEGIC_SHADING"),
        ("SELLER_DROPOUT", "SELLER_DROPOUT"),
        ("FAKE_INVENTORY", "FAKE_INVENTORY"),
        ("SLA_OVERPROMISE", "SLA_OVERPROMISE"),
        ("SYBIL_SENSITIVITY", "SYBIL_SENSITIVITY"),
        ("COLLUSION_SENSITIVITY", "COLLUSION_SENSITIVITY"),
        ("DUPLICATE_EVENT", "DUPLICATE_EVENT"),
        ("EVENT_REORDERING", "EVENT_REORDERING"),
        ("PROVIDER_TIMEOUT", "PROVIDER_TIMEOUT"),
        ("PAYMENT_FAILURE", "PAYMENT_FAILURE"),
        ("TRANSFER_FAILURE", "TRANSFER_FAILURE"),
        ("RETRY", "RETRY"),
        ("RECONCILIATION", "RECONCILIATION"),
        ("RECOVERY", "RECOVERY"),
    ]


def test_field_order_and_model_configuration_are_exact() -> None:
    expected_fields = {
        AgentMarketBenchLatentAttributeV1: (
            "schema_version",
            "agent_market_bench_latent_attribute_version",
            "attribute_key",
            "value",
        ),
        AgentMarketBenchLatentLineV1: (
            "schema_version",
            "agent_market_bench_latent_line_version",
            "economic_principal_id",
            "merchant_id",
            "sku_id",
            "true_available_quantity",
            "true_unit_cost",
            "true_unit_buyer_value",
            "true_attributes",
        ),
        AgentMarketBenchObservedMerchantV1: (
            "schema_version",
            "agent_market_bench_observed_merchant_version",
            "merchant_id",
            "catalog",
            "inventory_snapshot",
            "signing_identity",
        ),
        AgentMarketBenchReportedOfferV1: (
            "schema_version",
            "agent_market_bench_reported_offer_version",
            "submission_index",
            "received_at",
            "signed_offer",
        ),
        AgentMarketBenchCaseV1: (
            "schema_version",
            "agent_market_bench_case_version",
            "generator_version",
            "seed",
            "case_id",
            "buyer_text",
            "buyer_policy",
            "observed_merchants",
            "latent_lines",
            "reported_offers",
            "adversarial_scenarios",
        ),
        AgentMarketBenchMarketInputV1: (
            "schema_version",
            "agent_market_bench_market_input_version",
            "buyer_policy",
            "observed_merchants",
            "reported_offers",
        ),
    }
    for model_type, fields in expected_fields.items():
        assert tuple(model_type.model_fields) == fields
        assert model_type.model_config == {
            "frozen": True,
            "extra": "forbid",
            "strict": True,
            "revalidate_instances": "always",
        }


def test_public_all_and_authority_docstrings_are_exactly_limited() -> None:
    import clear_market.agentmarketbench as package

    assert package.__all__ == (
        "AGENT_MARKET_BENCH_PROTOCOL_V1_VERSION",
        "AGENT_MARKET_BENCH_GENERATOR_V1_VERSION",
        "AGENT_MARKET_BENCH_CASE_V1_VERSION",
        "AGENT_MARKET_BENCH_MARKET_INPUT_V1_VERSION",
        "AGENT_MARKET_BENCH_LATENT_ATTRIBUTE_V1_VERSION",
        "AGENT_MARKET_BENCH_LATENT_LINE_V1_VERSION",
        "AGENT_MARKET_BENCH_OBSERVED_MERCHANT_V1_VERSION",
        "AGENT_MARKET_BENCH_REPORTED_OFFER_V1_VERSION",
        "AGENT_MARKET_BENCH_CASE_DIGEST_V1_VERSION",
        "MAX_AGENT_MARKET_BENCH_SEED",
        "AgentMarketBenchBaselineV1",
        "AgentMarketBenchMetricV1",
        "AgentMarketBenchAdversarialClassificationV1",
        "AgentMarketBenchAdversarialScenarioV1",
        "AgentMarketBenchLatentAttributeV1",
        "AgentMarketBenchLatentLineV1",
        "AgentMarketBenchObservedMerchantV1",
        "AgentMarketBenchReportedOfferV1",
        "AgentMarketBenchCaseV1",
        "AgentMarketBenchMarketInputV1",
        "agent_market_bench_market_input_v1",
        "canonical_agent_market_bench_case_v1_bytes",
        "agent_market_bench_case_v1_digest",
    )
    assert "Hidden benchmark ground truth" in AgentMarketBenchLatentAttributeV1.__doc__
    assert "Evaluation evidence only" in AgentMarketBenchCaseV1.__doc__
    assert "Direct construction does not authenticate" in AgentMarketBenchCaseV1.__doc__
    assert "no certificate" in AgentMarketBenchMarketInputV1.__doc__
    assert "allocation" in AgentMarketBenchMarketInputV1.__doc__
    assert "financial" in AgentMarketBenchMarketInputV1.__doc__
    assert "payment" in AgentMarketBenchMarketInputV1.__doc__
    assert "routing" in AgentMarketBenchMarketInputV1.__doc__
    assert "settlement" in AgentMarketBenchMarketInputV1.__doc__
    assert "fulfillment" in AgentMarketBenchMarketInputV1.__doc__
    assert "benchmark-visible input only" in AgentMarketBenchMarketInputV1.__doc__


def _parent_with_field(parent: object, field_name: str, value: object) -> object:
    return parent.model_copy(update={field_name: value})  # type: ignore[attr-defined]


def _subclass_instance(model_type: type[object], value: object) -> object:
    class NestedSubclass(model_type):  # type: ignore[misc, valid-type]
        pass

    fields = {
        field_name: getattr(value, field_name)
        for field_name in type(value).model_fields  # type: ignore[attr-defined]
    }
    return NestedSubclass.model_construct(**fields)  # type: ignore[attr-defined]


def test_fresh_exact_nested_models_reject_invalid_forms() -> None:
    case, observed = _fixture()

    nested_cases = (
        (
            AttributeValue,
            case.latent_lines[0].true_attributes[0].value,
            case.latent_lines[0].true_attributes[0],
            "value",
        ),
        (
            Money,
            case.latent_lines[0].true_unit_cost,
            case.latent_lines[0],
            "true_unit_cost",
        ),
        (BuyerPolicyV2, case.buyer_policy, case, "buyer_policy"),
        (
            MerchantCatalogV2,
            observed[0].catalog,
            case.observed_merchants[0],
            "catalog",
        ),
        (
            InventorySnapshotV2,
            observed[0].inventory_snapshot,
            case.observed_merchants[0],
            "inventory_snapshot",
        ),
        (
            MerchantSigningIdentityV2,
            observed[0].signing_identity,
            case.observed_merchants[0],
            "signing_identity",
        ),
        (
            SignedMerchantOfferV2,
            case.reported_offers[0].signed_offer,
            case.reported_offers[0],
            "signed_offer",
        ),
        (
            AgentMarketBenchLatentAttributeV1,
            case.latent_lines[0].true_attributes[0],
            case.latent_lines[0],
            "true_attributes",
        ),
        (
            AgentMarketBenchObservedMerchantV1,
            case.observed_merchants[0],
            case,
            "observed_merchants",
        ),
        (
            AgentMarketBenchReportedOfferV1,
            case.reported_offers[0],
            case,
            "reported_offers",
        ),
    )
    for nested_type, nested_value, parent, field_name in nested_cases:
        if field_name == "true_attributes":
            dict_value = (nested_value.model_dump(mode="python"),)
            subclass_value = (_subclass_instance(nested_type, nested_value),)
            corrupt_value = (nested_type.model_construct(),)
        elif field_name == "observed_merchants":
            dict_value = (nested_value.model_dump(mode="python"), case.observed_merchants[1])
            subclass_value = (
                _subclass_instance(nested_type, nested_value),
                case.observed_merchants[1],
            )
            corrupt_value = (nested_type.model_construct(), case.observed_merchants[1])
        elif field_name == "reported_offers":
            dict_value = (nested_value.model_dump(mode="python"), case.reported_offers[1])
            subclass_value = (
                _subclass_instance(nested_type, nested_value),
                case.reported_offers[1],
            )
            corrupt_value = (nested_type.model_construct(), case.reported_offers[1])
        else:
            dict_value = nested_value.model_dump(mode="python")
            subclass_value = _subclass_instance(nested_type, nested_value)
            corrupt_value = nested_type.model_construct()
        with pytest.raises(ValidationError):
            type(parent).model_validate(_parent_with_field(parent, field_name, dict_value))
        with pytest.raises(ValidationError):
            type(parent).model_validate(_parent_with_field(parent, field_name, subclass_value))
        with pytest.raises(ValidationError):
            type(parent).model_validate(_parent_with_field(parent, field_name, corrupt_value))
    corrupt_attribute = AttributeValue.model_construct(
        value_type=AttributeValueType.INTEGER,
        value="not-an-integer",
    )
    with pytest.raises(ValidationError):
        AgentMarketBenchLatentAttributeV1(attribute_key="x", value=corrupt_attribute)
    corrupt_case = case.model_copy(update={"buyer_policy": BuyerPolicyV2.model_construct()})
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(corrupt_case)
    with pytest.raises(ValidationError):
        AgentMarketBenchLatentAttributeV1.model_validate(
            {"attribute_key": "x", "value": {"value_type": AttributeValueType.INTEGER}}
        )


def test_fresh_reconstruction_returns_new_nested_objects() -> None:
    case, observed = _fixture()
    validated = AgentMarketBenchCaseV1.model_validate(case)
    assert validated is not case
    assert validated.buyer_policy is not case.buyer_policy
    assert validated.observed_merchants[0] is not case.observed_merchants[0]
    assert validated.observed_merchants[0].catalog is not case.observed_merchants[0].catalog
    assert validated.observed_merchants[0].inventory_snapshot is not observed[0].inventory_snapshot
    assert validated.observed_merchants[0].signing_identity is not observed[0].signing_identity
    assert validated.latent_lines[0] is not case.latent_lines[0]
    assert validated.latent_lines[0].true_unit_cost is not case.latent_lines[0].true_unit_cost
    assert validated.reported_offers[0] is not case.reported_offers[0]
    assert validated.reported_offers[0].signed_offer is not case.reported_offers[0].signed_offer
