"""Protocol tests for the latent/observable firewall and case identity."""

import json
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from clear_market.agentmarketbench import (
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchCaseV1,
    AgentMarketBenchLatentAttributeV1,
    AgentMarketBenchLatentLineV1,
    AgentMarketBenchMarketInputV1,
    AgentMarketBenchObservedMerchantV1,
    AgentMarketBenchReportedOfferV1,
    agent_market_bench_case_v1_digest,
    agent_market_bench_market_input_v1,
    canonical_agent_market_bench_case_v1_bytes,
)
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MarketSpecV2,
    MerchantCatalogV2,
    MerchantEconomicPolicyV2,
    MerchantOfferCandidateLineV2,
    MerchantOfferCandidateV2,
    MerchantOfferLineV2,
    MerchantOfferV2,
    MerchantSkuEconomicRuleV2,
    ProvenanceLabel,
    build_and_sign_merchant_offer_v2,
    canonical_signed_merchant_offer_v2_bytes,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.commerce.authentication import MerchantSigningIdentityV2, SignedMerchantOfferV2
from clear_market.domain import Money


def _uid(prefix: str, number: int) -> str:
    return f"{prefix}-0000-4000-8000-{number:012x}"


def _standard_signing_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range((index - 1) * 32, index * 32)))


def _fixture() -> tuple[AgentMarketBenchCaseV1, tuple[AgentMarketBenchObservedMerchantV1, ...]]:
    merchant_ids = (_uid("43000000", 1), _uid("43000000", 2))
    policy = BuyerPolicyV2(
        market_spec=MarketSpecV2(
            market_id=_uid("41000000", 1),
            buyer_id=_uid("42000000", 1),
            requested_quantity=2,
            minimum_acceptable_quantity=1,
            max_winners=2,
            hard_constraints=(),
            soft_preferences=(),
        ),
        max_total_payment=Money(amount_paise=1_000),
        eligible_merchant_ids=merchant_ids,
        offer_deadline=datetime(2027, 1, 1, 12, tzinfo=UTC),
        mechanism_version="agentmarketbench-test-mechanism-v1",
        objective_version="agentmarketbench-test-objective-v1",
    )

    observed: list[AgentMarketBenchObservedMerchantV1] = []
    offers: list[AgentMarketBenchReportedOfferV1] = []
    latent: list[AgentMarketBenchLatentLineV1] = []
    for index, merchant_id in enumerate(merchant_ids, start=1):
        signing_key = _standard_signing_key(index)
        public_key = (
            signing_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )
        catalog_id = _uid("44000000", index)
        product_id = _uid("45000000", index)
        sku_id = _uid("46000000", index)
        evidence_id = _uid("47000000", index)
        snapshot_id = _uid("48000000", index)
        offer_id = _uid("49000000", index)
        catalog_attribute = CatalogAttributeV2(
            attribute_key="sla_days",
            value=AttributeValue(value_type=AttributeValueType.INTEGER, value=2),
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=evidence_id,
        )
        quality_attribute = CatalogAttributeV2(
            attribute_key="quality_score",
            value=AttributeValue(value_type=AttributeValueType.INTEGER, value=9),
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_uid("47000000", index + 10),
        )
        catalog_attributes = (catalog_attribute, quality_attribute)
        catalog = MerchantCatalogV2(
            catalog_id=catalog_id,
            merchant_id=merchant_id,
            generated_at=datetime(2027, 1, 1, 9, tzinfo=UTC),
            products=(
                CatalogProductV2(
                    product_id=product_id,
                    display_name="Product",
                    description="Catalog text",
                ),
            ),
            skus=(
                CatalogSkuV2(
                    sku_id=sku_id,
                    product_id=product_id,
                    merchant_sku=f"SKU-{index}",
                    display_name="SKU",
                    attributes=tuple(reversed(catalog_attributes)),
                ),
            ),
        )
        inventory = InventorySnapshotV2(
            snapshot_id=snapshot_id,
            catalog_id=catalog_id,
            merchant_id=merchant_id,
            captured_at=datetime(2027, 1, 1, 10, tzinfo=UTC),
            lines=(
                InventoryLineV2(
                    sku_id=sku_id,
                    quantity_available=2,
                    provenance=ProvenanceLabel.CLAIMED,
                    evidence_reference_id=evidence_id,
                ),
            ),
        )
        signing_identity = MerchantSigningIdentityV2(
            merchant_id=merchant_id,
            ed25519_public_key_hex=public_key,
        )
        observed.append(
            AgentMarketBenchObservedMerchantV1(
                merchant_id=merchant_id,
                catalog=catalog,
                inventory_snapshot=inventory,
                signing_identity=signing_identity,
            )
        )
        economic_policy = MerchantEconomicPolicyV2(
            economic_policy_id=_uid("52000000", index),
            merchant_id=merchant_id,
            catalog_id=catalog_id,
            sku_rules=(
                MerchantSkuEconomicRuleV2(
                    sku_id=sku_id,
                    unit_cost_basis=Money(amount_paise=51 + index),
                    minimum_margin=Money(amount_paise=10),
                    max_quantity_per_offer=2,
                ),
            ),
        )
        candidate = MerchantOfferCandidateV2(
            lines=(
                MerchantOfferCandidateLineV2(
                    sku_id=sku_id,
                    proposed_quantity=1,
                    proposed_unit_price=Money(amount_paise=100),
                ),
            ),
        )
        signed_offer = build_and_sign_merchant_offer_v2(
            offer_id=offer_id,
            buyer_policy=policy,
            catalog=catalog,
            inventory=inventory,
            economic_policy=economic_policy,
            candidate=candidate,
            signing_identity=signing_identity,
            private_key=signing_key,
        )
        offers.append(
            AgentMarketBenchReportedOfferV1(
                submission_index=index - 1,
                received_at=datetime(2027, 1, 1, 13 - index, tzinfo=UTC),
                signed_offer=signed_offer,
            )
        )
        latent.append(
            AgentMarketBenchLatentLineV1(
                economic_principal_id=_uid("50000000", index),
                merchant_id=merchant_id,
                sku_id=sku_id,
                true_available_quantity=3,
                true_unit_cost=Money(amount_paise=50 + index),
                true_unit_buyer_value=Money(amount_paise=200 + index),
                true_attributes=(
                    AgentMarketBenchLatentAttributeV1(
                        attribute_key="sla_days",
                        value=AttributeValue(
                            value_type=AttributeValueType.INTEGER,
                            value=4,
                        ),
                    ),
                    AgentMarketBenchLatentAttributeV1(
                        attribute_key="quality_score",
                        value=AttributeValue(
                            value_type=AttributeValueType.INTEGER,
                            value=10,
                        ),
                    ),
                ),
            )
        )

    case = AgentMarketBenchCaseV1(
        seed=24,
        case_id=_uid("51000000", 1),
        buyer_text="buy two substitute offers",
        buyer_policy=policy,
        observed_merchants=tuple(reversed(observed)),
        latent_lines=tuple(reversed(latent)),
        reported_offers=tuple(offers),
        adversarial_scenarios=(),
    )
    return case, tuple(observed)


def _validated_case(case: AgentMarketBenchCaseV1, **changes: object) -> AgentMarketBenchCaseV1:
    values = {
        field_name: getattr(case, field_name) for field_name in AgentMarketBenchCaseV1.model_fields
    }
    values.update(changes)
    return AgentMarketBenchCaseV1.model_validate(values)


def _validated_offer(
    offer: AgentMarketBenchReportedOfferV1,
    **changes: object,
) -> AgentMarketBenchReportedOfferV1:
    values = {
        field_name: getattr(offer, field_name)
        for field_name in AgentMarketBenchReportedOfferV1.model_fields
    }
    values.update(changes)
    return AgentMarketBenchReportedOfferV1.model_validate(values)


def _validated_line(
    line: AgentMarketBenchLatentLineV1,
    **changes: object,
) -> AgentMarketBenchLatentLineV1:
    values = {
        field_name: getattr(line, field_name)
        for field_name in AgentMarketBenchLatentLineV1.model_fields
    }
    values.update(changes)
    return AgentMarketBenchLatentLineV1.model_validate(values)


def _validated_observed(
    merchant: AgentMarketBenchObservedMerchantV1,
    **changes: object,
) -> AgentMarketBenchObservedMerchantV1:
    values = {
        field_name: getattr(merchant, field_name)
        for field_name in AgentMarketBenchObservedMerchantV1.model_fields
    }
    values.update(changes)
    return AgentMarketBenchObservedMerchantV1.model_validate(values)


def _validated_existing(model: object, model_type: type[object], **changes: object) -> object:
    values = {field_name: getattr(model, field_name) for field_name in model_type.model_fields}
    values.update(changes)
    return model_type.model_validate(values)


def test_case_normalizes_irrelevant_order_and_preserves_submission_order() -> None:
    case, observed = _fixture()
    assert tuple(merchant.merchant_id for merchant in case.observed_merchants) == tuple(
        sorted(merchant.merchant_id for merchant in observed)
    )
    assert tuple(line.merchant_id for line in case.latent_lines) == tuple(
        sorted(line.merchant_id for line in case.latent_lines)
    )
    assert tuple(offer.submission_index for offer in case.reported_offers) == (0, 1)
    assert case.reported_offers[0].received_at > case.reported_offers[1].received_at


def test_case_represents_replay_and_invalid_signature_without_authenticating() -> None:
    case, _ = _fixture()
    invalid_signed_offer = case.reported_offers[0].signed_offer.model_copy(
        update={"signature_hex": "0" * 128}
    )
    invalid_offer = case.reported_offers[0].model_copy(
        update={"signed_offer": invalid_signed_offer, "submission_index": 0}
    )
    replay = invalid_offer.model_copy(update={"submission_index": 1})
    replay_case = AgentMarketBenchCaseV1.model_validate(
        case.model_copy(update={"reported_offers": (invalid_offer, replay)})
    )
    assert (
        replay_case.reported_offers[0].signed_offer == replay_case.reported_offers[1].signed_offer
    )
    assert replay_case.reported_offers[0].signed_offer.signature_hex == "0" * 128


def test_case_digest_binds_reported_order_and_metadata() -> None:
    case, _ = _fixture()
    swapped = tuple(
        offer.model_copy(update={"submission_index": index})
        for index, offer in enumerate(reversed(case.reported_offers))
    )
    swapped_case = case.model_copy(update={"reported_offers": swapped})
    assert agent_market_bench_case_v1_digest(case) != agent_market_bench_case_v1_digest(
        swapped_case
    )
    assert agent_market_bench_case_v1_digest(case) != agent_market_bench_case_v1_digest(
        case.model_copy(update={"seed": case.seed + 1})
    )


def test_canonical_case_envelope_is_complete_and_stable() -> None:
    case, _ = _fixture()
    encoded = canonical_agent_market_bench_case_v1_bytes(case)
    envelope = json.loads(encoded)
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == "agent_market_bench_case_v1"
    assert set(envelope["payload"]) == {
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
    }
    assert encoded == canonical_agent_market_bench_case_v1_bytes(case)
    assert len(agent_market_bench_case_v1_digest(case)) == 64


@pytest.mark.parametrize(
    "field, value",
    [
        ("seed", -1),
        ("seed", 2_147_483_648),
        ("case_id", "not-a-uuid"),
        ("buyer_text", "bad\x00text"),
        ("buyer_text", "\ud800"),
        ("adversarial_scenarios", (AgentMarketBenchAdversarialScenarioV1.RETRY,) * 2),
    ],
)
def test_case_rejects_structural_invalidity(field: str, value: object) -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        case.model_copy(update={field: value})
        AgentMarketBenchCaseV1.model_validate(case.model_copy(update={field: value}))


def test_case_rejects_noncontiguous_report_indexes_and_identity_mismatch() -> None:
    case, observed = _fixture()
    bad_offer = case.reported_offers[1].model_copy(update={"submission_index": 4})
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(
            case.model_copy(update={"reported_offers": (case.reported_offers[0], bad_offer)})
        )

    mismatched_catalog = observed[0].catalog.model_copy(
        update={"merchant_id": observed[1].merchant_id}
    )
    bad_observed = observed[0].model_copy(update={"catalog": mismatched_catalog})
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(
            case.model_copy(update={"observed_merchants": (bad_observed, observed[1])})
        )


def test_fresh_nested_models_are_not_reused() -> None:
    case, observed = _fixture()
    assert case.observed_merchants[0] is not observed[0]
    assert case.observed_merchants[0].catalog is not observed[0].catalog
    assert case.latent_lines[0].true_unit_cost is not case.latent_lines[1].true_unit_cost
    method_input = agent_market_bench_market_input_v1(case)
    assert method_input.buyer_policy is not case.buyer_policy
    assert method_input.observed_merchants[0] is not case.observed_merchants[0]


def test_method_input_model_has_no_reference_metadata_fields() -> None:
    assert set(AgentMarketBenchMarketInputV1.model_fields) == {
        "schema_version",
        "agent_market_bench_market_input_version",
        "buyer_policy",
        "observed_merchants",
        "reported_offers",
    }


def test_attack_representability_replay_duplicate_offer_is_preserved() -> None:
    case, _ = _fixture()
    first = _validated_offer(case.reported_offers[0], submission_index=0)
    second = _validated_offer(case.reported_offers[0], submission_index=1)
    replay_case = _validated_case(case, reported_offers=(first, second))
    assert (
        replay_case.reported_offers[0].signed_offer == replay_case.reported_offers[1].signed_offer
    )
    assert tuple(offer.submission_index for offer in replay_case.reported_offers) == (0, 1)


def test_attack_representability_late_offer_is_preserved() -> None:
    case, _ = _fixture()
    late = _validated_offer(
        case.reported_offers[0],
        received_at=case.buyer_policy.offer_deadline.replace(hour=13),
        submission_index=0,
    )
    accepted = _validated_case(case, reported_offers=(late, case.reported_offers[1]))
    assert accepted.reported_offers[0].received_at > accepted.buyer_policy.offer_deadline


def test_attack_representability_non_monotonic_receipts_preserve_tuple_order() -> None:
    case, _ = _fixture()
    first = _validated_offer(
        case.reported_offers[0],
        received_at=case.buyer_policy.offer_deadline.replace(hour=11),
        submission_index=0,
    )
    second = _validated_offer(
        case.reported_offers[1],
        received_at=case.buyer_policy.offer_deadline.replace(hour=10),
        submission_index=1,
    )
    accepted = _validated_case(case, reported_offers=(first, second))
    assert accepted.reported_offers[0].received_at > accepted.reported_offers[1].received_at
    assert accepted.reported_offers[0].signed_offer == case.reported_offers[0].signed_offer


def test_attack_representability_invalid_signature_is_structurally_accepted() -> None:
    case, _ = _fixture()
    invalid_signed_offer = SignedMerchantOfferV2(
        offer=case.reported_offers[0].signed_offer.offer,
        signature_hex="0" * 128,
    )
    invalid_offer = _validated_offer(
        case.reported_offers[0],
        signed_offer=invalid_signed_offer,
        submission_index=0,
    )
    accepted = _validated_case(case, reported_offers=(invalid_offer, case.reported_offers[1]))
    assert accepted.reported_offers[0].signed_offer.signature_hex == "0" * 128


def test_attack_representability_inventory_truth_difference_is_accepted() -> None:
    case, _ = _fixture()
    assert case.observed_merchants[0].inventory_snapshot.lines[0].quantity_available != (
        case.latent_lines[0].true_available_quantity
    )
    assert _validated_case(case) == case


def test_attack_representability_attribute_truth_difference_is_accepted() -> None:
    case, _ = _fixture()
    observed_value = case.observed_merchants[0].catalog.skus[0].attributes[0].value.value
    latent_value = case.latent_lines[0].true_attributes[0].value.value
    assert observed_value != latent_value
    assert _validated_case(case) == case


def test_attack_representability_shared_economic_principal_is_accepted() -> None:
    case, _ = _fixture()
    shared_principal = _uid("50000000", 1)
    shared_principal_lines = tuple(
        _validated_line(line, economic_principal_id=shared_principal) for line in case.latent_lines
    )
    sybil_case = _validated_case(
        case,
        latent_lines=shared_principal_lines,
        adversarial_scenarios=(AgentMarketBenchAdversarialScenarioV1.SYBIL_SENSITIVITY,),
    )
    assert len({line.economic_principal_id for line in sybil_case.latent_lines}) == 1
    assert len({line.merchant_id for line in sybil_case.latent_lines}) == 2
    assert sybil_case.adversarial_scenarios == (
        AgentMarketBenchAdversarialScenarioV1.SYBIL_SENSITIVITY,
    )


def test_structural_rejection_duplicate_observed_merchant_ids() -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(
            case,
            observed_merchants=(case.observed_merchants[0], case.observed_merchants[0]),
        )


def test_structural_rejection_observed_set_must_equal_policy_set() -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(case, observed_merchants=(case.observed_merchants[0],))


def test_structural_rejection_catalog_merchant_mismatch() -> None:
    case, _ = _fixture()
    bad_catalog = case.observed_merchants[0].catalog.model_copy(
        update={"merchant_id": case.observed_merchants[1].merchant_id}
    )
    bad_observed = case.observed_merchants[0].model_copy(update={"catalog": bad_catalog})
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(
            case.model_copy(
                update={"observed_merchants": (bad_observed, case.observed_merchants[1])}
            )
        )


def test_structural_rejection_inventory_merchant_mismatch() -> None:
    case, _ = _fixture()
    bad_inventory = case.observed_merchants[0].inventory_snapshot.model_copy(
        update={"merchant_id": case.observed_merchants[1].merchant_id}
    )
    bad_observed = case.observed_merchants[0].model_copy(
        update={"inventory_snapshot": bad_inventory}
    )
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(
            case.model_copy(
                update={"observed_merchants": (bad_observed, case.observed_merchants[1])}
            )
        )


def test_structural_rejection_inventory_catalog_identity_mismatch() -> None:
    case, _ = _fixture()
    bad_inventory = case.observed_merchants[0].inventory_snapshot.model_copy(
        update={"catalog_id": case.observed_merchants[1].catalog.catalog_id}
    )
    bad_observed = case.observed_merchants[0].model_copy(
        update={"inventory_snapshot": bad_inventory}
    )
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(
            case.model_copy(
                update={"observed_merchants": (bad_observed, case.observed_merchants[1])}
            )
        )


def test_structural_rejection_signing_identity_merchant_mismatch() -> None:
    case, _ = _fixture()
    bad_identity = case.observed_merchants[0].signing_identity.model_copy(
        update={"merchant_id": case.observed_merchants[1].merchant_id}
    )
    bad_observed = case.observed_merchants[0].model_copy(update={"signing_identity": bad_identity})
    with pytest.raises(ValidationError):
        AgentMarketBenchCaseV1.model_validate(
            case.model_copy(
                update={"observed_merchants": (bad_observed, case.observed_merchants[1])}
            )
        )


def test_structural_rejection_duplicate_latent_key() -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(case, latent_lines=(case.latent_lines[0], case.latent_lines[0]))


def test_structural_rejection_latent_sku_absent_from_catalog() -> None:
    case, _ = _fixture()
    bad_line = _validated_line(
        case.latent_lines[0],
        sku_id=_uid("46000000", 99),
    )
    with pytest.raises(ValidationError):
        _validated_case(case, latent_lines=(bad_line, case.latent_lines[1]))


def test_structural_rejection_catalog_sku_lacking_latent_truth() -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(case, latent_lines=(case.latent_lines[0],))


def test_structural_rejection_latent_attribute_key_mismatch() -> None:
    case, _ = _fixture()
    bad_attribute = AgentMarketBenchLatentAttributeV1(
        attribute_key="different_key",
        value=case.latent_lines[0].true_attributes[0].value,
    )
    bad_line = _validated_line(
        case.latent_lines[0],
        true_attributes=(bad_attribute, case.latent_lines[0].true_attributes[1]),
    )
    with pytest.raises(ValidationError):
        _validated_case(case, latent_lines=(bad_line, case.latent_lines[1]))


def test_structural_rejection_same_merchant_multiple_principals() -> None:
    case, _ = _fixture()
    observed = case.observed_merchants[0]
    source_sku = observed.catalog.skus[0]
    extra_sku_id = _uid("46000000", 99)
    extra_sku = CatalogSkuV2(
        sku_id=extra_sku_id,
        product_id=source_sku.product_id,
        merchant_sku="SKU-EXTRA",
        display_name="Extra SKU",
        attributes=source_sku.attributes,
    )
    catalog = MerchantCatalogV2(
        catalog_id=observed.catalog.catalog_id,
        merchant_id=observed.merchant_id,
        generated_at=observed.catalog.generated_at,
        products=observed.catalog.products,
        skus=(*observed.catalog.skus, extra_sku),
    )
    inventory = InventorySnapshotV2(
        snapshot_id=observed.inventory_snapshot.snapshot_id,
        catalog_id=observed.inventory_snapshot.catalog_id,
        merchant_id=observed.inventory_snapshot.merchant_id,
        captured_at=observed.inventory_snapshot.captured_at,
        lines=(
            *observed.inventory_snapshot.lines,
            InventoryLineV2(
                sku_id=extra_sku_id,
                quantity_available=1,
                provenance=ProvenanceLabel.CLAIMED,
                evidence_reference_id=_uid("47000000", 99),
            ),
        ),
    )
    expanded = AgentMarketBenchObservedMerchantV1(
        merchant_id=observed.merchant_id,
        catalog=catalog,
        inventory_snapshot=inventory,
        signing_identity=observed.signing_identity,
    )
    extra_line = AgentMarketBenchLatentLineV1(
        economic_principal_id=_uid("50000000", 2),
        merchant_id=observed.merchant_id,
        sku_id=extra_sku_id,
        true_available_quantity=1,
        true_unit_cost=Money(amount_paise=77),
        true_unit_buyer_value=Money(amount_paise=177),
        true_attributes=case.latent_lines[0].true_attributes,
    )
    with pytest.raises(ValidationError):
        _validated_case(
            case,
            observed_merchants=(expanded, case.observed_merchants[1]),
            latent_lines=(case.latent_lines[0], case.latent_lines[1], extra_line),
        )


def test_structural_rejection_report_indexes_noncontiguous() -> None:
    case, _ = _fixture()
    bad = _validated_offer(case.reported_offers[1], submission_index=2)
    with pytest.raises(ValidationError):
        _validated_case(case, reported_offers=(case.reported_offers[0], bad))


def test_structural_rejection_report_indexes_disagree_with_tuple_order() -> None:
    case, _ = _fixture()
    first = _validated_offer(case.reported_offers[0], submission_index=1)
    second = _validated_offer(case.reported_offers[1], submission_index=0)
    with pytest.raises(ValidationError):
        _validated_case(case, reported_offers=(first, second))


def test_structural_rejection_duplicate_adversarial_labels() -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(
            case,
            adversarial_scenarios=(
                AgentMarketBenchAdversarialScenarioV1.RETRY,
                AgentMarketBenchAdversarialScenarioV1.RETRY,
            ),
        )


@pytest.mark.parametrize("seed", [-1, 2_147_483_648])
def test_structural_rejection_seed_bounds(seed: int) -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(case, seed=seed)


def test_structural_rejection_invalid_case_uuid() -> None:
    case, _ = _fixture()
    with pytest.raises(ValidationError):
        _validated_case(case, case_id="invalid")


def test_structural_rejection_buyer_text_nul_surrogate_and_byte_limit() -> None:
    case, _ = _fixture()
    for text in ("contains\x00nul", "\ud800", "é" * 131_073):
        with pytest.raises(ValidationError):
            _validated_case(case, buyer_text=text)


def _assert_latent_only_change_keeps_method_input(
    base: AgentMarketBenchCaseV1,
    changed: AgentMarketBenchCaseV1,
) -> None:
    assert agent_market_bench_case_v1_digest(base) != agent_market_bench_case_v1_digest(changed)
    assert agent_market_bench_market_input_v1(base) == agent_market_bench_market_input_v1(changed)


def test_firewall_isolated_true_unit_cost_change() -> None:
    base, _ = _fixture()
    changed_line = _validated_line(base.latent_lines[0], true_unit_cost=Money(amount_paise=901))
    changed = _validated_case(
        base,
        latent_lines=(changed_line, base.latent_lines[1]),
    )
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_true_unit_buyer_value_change() -> None:
    base, _ = _fixture()
    changed_line = _validated_line(
        base.latent_lines[0],
        true_unit_buyer_value=Money(amount_paise=902),
    )
    changed = _validated_case(base, latent_lines=(changed_line, base.latent_lines[1]))
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_true_available_quantity_change() -> None:
    base, _ = _fixture()
    changed_line = _validated_line(base.latent_lines[0], true_available_quantity=1)
    changed = _validated_case(base, latent_lines=(changed_line, base.latent_lines[1]))
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_latent_attribute_value_change() -> None:
    base, _ = _fixture()
    original = base.latent_lines[0].true_attributes[0]
    changed_attribute = AgentMarketBenchLatentAttributeV1(
        attribute_key=original.attribute_key,
        value=AttributeValue(value_type=AttributeValueType.INTEGER, value=901),
    )
    changed_line = _validated_line(
        base.latent_lines[0],
        true_attributes=(changed_attribute, base.latent_lines[0].true_attributes[1]),
    )
    changed = _validated_case(base, latent_lines=(changed_line, base.latent_lines[1]))
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_economic_principal_change() -> None:
    base, _ = _fixture()
    changed_line = _validated_line(
        base.latent_lines[0],
        economic_principal_id=_uid("50000000", 2),
    )
    changed = _validated_case(base, latent_lines=(changed_line, base.latent_lines[1]))
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_seed_change() -> None:
    base, _ = _fixture()
    changed = _validated_case(base, seed=25)
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_buyer_text_change() -> None:
    base, _ = _fixture()
    changed = _validated_case(base, buyer_text="different buyer wording")
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_firewall_isolated_adversarial_label_change() -> None:
    base, _ = _fixture()
    changed = _validated_case(
        base,
        adversarial_scenarios=(AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,),
    )
    _assert_latent_only_change_keeps_method_input(base, changed)


def test_observable_signed_offer_economic_content_changes_digest_and_input() -> None:
    base, _ = _fixture()
    original_offer = base.reported_offers[0].signed_offer.offer
    original_line = original_offer.lines[0]
    changed_line = MerchantOfferLineV2(
        sku_id=original_line.sku_id,
        max_offer_quantity=original_line.max_offer_quantity,
        unit_price=Money(amount_paise=101),
        attributes=original_line.attributes,
        inventory_provenance=original_line.inventory_provenance,
        inventory_evidence_reference_id=original_line.inventory_evidence_reference_id,
    )
    changed_offer = MerchantOfferV2(
        offer_id=original_offer.offer_id,
        market_id=original_offer.market_id,
        merchant_id=original_offer.merchant_id,
        catalog_id=original_offer.catalog_id,
        inventory_snapshot_id=original_offer.inventory_snapshot_id,
        buyer_policy_commitment_sha256=original_offer.buyer_policy_commitment_sha256,
        merchant_catalog_commitment_sha256=original_offer.merchant_catalog_commitment_sha256,
        inventory_snapshot_commitment_sha256=original_offer.inventory_snapshot_commitment_sha256,
        lines=(changed_line,),
    )
    changed_signed = SignedMerchantOfferV2(
        offer=changed_offer,
        signature_hex=base.reported_offers[0].signed_offer.signature_hex,
    )
    changed_report = _validated_offer(
        base.reported_offers[0],
        signed_offer=changed_signed,
        submission_index=0,
    )
    changed = _validated_case(base, reported_offers=(changed_report, base.reported_offers[1]))
    assert agent_market_bench_case_v1_digest(base) != agent_market_bench_case_v1_digest(changed)
    assert agent_market_bench_market_input_v1(base) != agent_market_bench_market_input_v1(changed)


def test_observable_inventory_change_changes_digest_and_input() -> None:
    base, _ = _fixture()
    observed = base.observed_merchants[0]
    old_line = observed.inventory_snapshot.lines[0]
    new_inventory = InventorySnapshotV2(
        snapshot_id=observed.inventory_snapshot.snapshot_id,
        catalog_id=observed.inventory_snapshot.catalog_id,
        merchant_id=observed.inventory_snapshot.merchant_id,
        captured_at=observed.inventory_snapshot.captured_at,
        lines=(
            InventoryLineV2(
                sku_id=old_line.sku_id,
                quantity_available=1,
                provenance=old_line.provenance,
                evidence_reference_id=old_line.evidence_reference_id,
            ),
        ),
    )
    new_observed = _validated_observed(observed, inventory_snapshot=new_inventory)
    changed = _validated_case(
        base,
        observed_merchants=(new_observed, base.observed_merchants[1]),
    )
    assert agent_market_bench_case_v1_digest(base) != agent_market_bench_case_v1_digest(changed)
    assert agent_market_bench_market_input_v1(base) != agent_market_bench_market_input_v1(changed)


def test_observable_catalog_text_change_changes_digest_and_input() -> None:
    base, _ = _fixture()
    observed = base.observed_merchants[0]
    old_product = observed.catalog.products[0]
    new_product = CatalogProductV2(
        product_id=old_product.product_id,
        display_name="Different catalog prose",
        description=old_product.description,
    )
    new_catalog = MerchantCatalogV2(
        catalog_id=observed.catalog.catalog_id,
        merchant_id=observed.catalog.merchant_id,
        generated_at=observed.catalog.generated_at,
        products=(new_product,),
        skus=observed.catalog.skus,
    )
    new_observed = _validated_observed(observed, catalog=new_catalog)
    changed = _validated_case(
        base,
        observed_merchants=(new_observed, base.observed_merchants[1]),
    )
    assert agent_market_bench_case_v1_digest(base) != agent_market_bench_case_v1_digest(changed)
    assert agent_market_bench_market_input_v1(base) != agent_market_bench_market_input_v1(changed)


def test_observable_buyer_policy_change_changes_digest_and_input() -> None:
    base, _ = _fixture()
    changed_policy = _validated_existing(
        base.buyer_policy,
        BuyerPolicyV2,
        max_total_payment=Money(amount_paise=999),
    )
    changed = _validated_case(base, buyer_policy=changed_policy)
    assert agent_market_bench_case_v1_digest(base) != agent_market_bench_case_v1_digest(changed)
    assert agent_market_bench_market_input_v1(base) != agent_market_bench_market_input_v1(changed)


def test_canonical_bytes_ignore_only_semantically_irrelevant_caller_order() -> None:
    base, _ = _fixture()
    reversed_lines = tuple(
        _validated_line(
            line,
            true_attributes=tuple(reversed(line.true_attributes)),
        )
        for line in reversed(base.latent_lines)
    )
    reversed_case = AgentMarketBenchCaseV1(
        seed=base.seed,
        case_id=base.case_id,
        buyer_text=base.buyer_text,
        buyer_policy=base.buyer_policy,
        observed_merchants=tuple(reversed(base.observed_merchants)),
        latent_lines=reversed_lines,
        reported_offers=base.reported_offers,
        adversarial_scenarios=(
            AgentMarketBenchAdversarialScenarioV1.RETRY,
            AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
        ),
    )
    canonical_order_case = AgentMarketBenchCaseV1(
        seed=base.seed,
        case_id=base.case_id,
        buyer_text=base.buyer_text,
        buyer_policy=base.buyer_policy,
        observed_merchants=base.observed_merchants,
        latent_lines=base.latent_lines,
        reported_offers=base.reported_offers,
        adversarial_scenarios=(
            AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
            AgentMarketBenchAdversarialScenarioV1.RETRY,
        ),
    )
    assert canonical_agent_market_bench_case_v1_bytes(reversed_case) == (
        canonical_agent_market_bench_case_v1_bytes(canonical_order_case)
    )
    assert agent_market_bench_case_v1_digest(reversed_case) == agent_market_bench_case_v1_digest(
        canonical_order_case
    )


def test_reported_order_is_semantic_after_reindexing() -> None:
    base, _ = _fixture()
    reordered = tuple(
        _validated_offer(offer, submission_index=index)
        for index, offer in enumerate(reversed(base.reported_offers))
    )
    changed = _validated_case(base, reported_offers=reordered)
    assert agent_market_bench_case_v1_digest(base) != agent_market_bench_case_v1_digest(changed)


def test_standard_candidate_has_valid_signatures_empty_labels_and_complete_projections() -> None:
    candidate, _ = _fixture()
    assert len(candidate.observed_merchants) == 2
    assert len(candidate.latent_lines) == 2
    assert candidate.adversarial_scenarios == ()
    assert len({line.economic_principal_id for line in candidate.latent_lines}) == 2
    assert (
        len(
            {
                merchant.signing_identity.ed25519_public_key_hex
                for merchant in candidate.observed_merchants
            }
        )
        == 2
    )
    canonical_bytes = canonical_agent_market_bench_case_v1_bytes(candidate)
    market_input = agent_market_bench_market_input_v1(candidate)
    assert len(canonical_bytes) > 0
    assert set(market_input.model_dump(mode="python")) == {
        "schema_version",
        "agent_market_bench_market_input_version",
        "buyer_policy",
        "observed_merchants",
        "reported_offers",
    }
    assert "latent_lines" not in market_input.model_dump(mode="python")
    assert "adversarial_scenarios" not in market_input.model_dump(mode="python")

    case_json = json.dumps(
        candidate.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    market_input_json = json.dumps(
        market_input.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert json.loads(case_json) == candidate.model_dump(mode="json")
    assert json.loads(market_input_json) == market_input.model_dump(mode="json")
    for serialized in (case_json, market_input_json):
        assert "private_key" not in serialized
        serialized_bytes = serialized.encode("utf-8")
        assert bytes(range(32)) not in serialized_bytes
        assert bytes(range(32, 64)) not in serialized_bytes
        assert bytes(range(32)).hex() not in serialized
        assert bytes(range(32, 64)).hex() not in serialized


def test_standard_candidate_offers_pass_production_authenticated_verifier() -> None:
    candidate, _ = _fixture()
    for observed, reported in zip(
        candidate.observed_merchants,
        candidate.reported_offers,
        strict=True,
    ):
        verified = verify_canonical_signed_merchant_offer_v2(
            data=canonical_signed_merchant_offer_v2_bytes(reported.signed_offer),
            signing_identity=observed.signing_identity,
            buyer_policy=candidate.buyer_policy,
            catalog=observed.catalog,
            inventory=observed.inventory_snapshot,
        )
        assert verified == reported.signed_offer
