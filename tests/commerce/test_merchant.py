from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from clear_market.commerce import (
    BUYER_POLICY_V2_COMMITMENT_VERSION,
    INVENTORY_SNAPSHOT_V2_COMMITMENT_VERSION,
    MERCHANT_CATALOG_V2_COMMITMENT_VERSION,
    MERCHANT_ECONOMIC_POLICY_V2_VERSION,
    MERCHANT_OFFER_CANDIDATE_LINE_V2_VERSION,
    MERCHANT_OFFER_CANDIDATE_V2_VERSION,
    MERCHANT_OFFER_LINE_V2_VERSION,
    MERCHANT_OFFER_V2_VERSION,
    MERCHANT_SKU_ECONOMIC_RULE_V2_VERSION,
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
    MerchantOfferBuildError,
    MerchantOfferBuildErrorCode,
    MerchantOfferCandidateLineV2,
    MerchantOfferCandidateV2,
    MerchantOfferLineV2,
    MerchantOfferV2,
    MerchantSkuEconomicRuleV2,
    ProvenanceLabel,
    build_merchant_offer_v2,
    buyer_policy_v2_commitment,
    canonical_buyer_policy_v2_bytes,
    canonical_inventory_snapshot_v2_bytes,
    canonical_merchant_catalog_v2_bytes,
    canonical_merchant_offer_v2_bytes,
    inventory_snapshot_v2_commitment,
    merchant_catalog_v2_commitment,
)
from clear_market.commerce.merchant import MAX_MERCHANT_ECONOMIC_RULES, MAX_OFFER_LINES
from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, Money

_MARKET_ID = "41000000-0000-4000-8000-000000000001"
_BUYER_ID = "42000000-0000-4000-8000-000000000001"
_MERCHANT_ID = "43000000-0000-4000-8000-000000000001"
_OTHER_ELIGIBLE_MERCHANT_ID = "43000000-0000-4000-8000-000000000002"
_OUTSIDER_MERCHANT_ID = "43000000-0000-4000-8000-000000000003"
_CATALOG_ID = "44000000-0000-4000-8000-000000000001"
_OTHER_CATALOG_ID = "44000000-0000-4000-8000-000000000002"
_SNAPSHOT_ID = "45000000-0000-4000-8000-000000000001"
_ECONOMIC_POLICY_ID = "46000000-0000-4000-8000-000000000001"
_OFFER_ID = "47000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2027, 3, 4, 12, 0, tzinfo=UTC)
_GENERATED_AT = datetime(2027, 3, 4, 9, 0, 0, 123_456, tzinfo=UTC)
_CAPTURED_AT = datetime(2027, 3, 4, 9, 30, 0, 654_321, tzinfo=UTC)
_DIGEST = "a" * 64


def _product_id(index: int) -> str:
    return f"48000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"49000000-0000-4000-8000-{index:012x}"


def _evidence_id(index: int) -> str:
    return f"50000000-0000-4000-8000-{index:012x}"


def _rule_id(index: int) -> str:
    return f"51000000-0000-4000-8000-{index:012x}"


def _attribute(
    key: str,
    value_type: AttributeValueType,
    value: str | int | bool,
    provenance: ProvenanceLabel,
    evidence_index: int,
) -> CatalogAttributeV2:
    return CatalogAttributeV2(
        attribute_key=key,
        value=AttributeValue(value_type=value_type, value=value),
        provenance=provenance,
        evidence_reference_id=_evidence_id(evidence_index),
    )


def _market(**changes: object) -> MarketSpecV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_id": _BUYER_ID,
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 5,
        "max_winners": 2,
        "hard_constraints": (),
        "soft_preferences": (),
        **changes,
    }
    return MarketSpecV2(**values)


def _buyer_policy(**changes: object) -> BuyerPolicyV2:
    values: dict[str, object] = {
        "market_spec": _market(),
        "max_total_payment": Money(amount_paise=10_000),
        "eligible_merchant_ids": (_OTHER_ELIGIBLE_MERCHANT_ID, _MERCHANT_ID),
        "offer_deadline": _DEADLINE,
        "mechanism_version": "heterogeneous-mechanism-test-v1",
        "objective_version": "heterogeneous-objective-test-v1",
        **changes,
    }
    return BuyerPolicyV2(**values)


def _products() -> tuple[CatalogProductV2, ...]:
    return (
        CatalogProductV2(
            product_id=_product_id(2),
            display_name="Dock display prose",
            description="Untrusted dock prose",
        ),
        CatalogProductV2(
            product_id=_product_id(1),
            display_name="Laptop display prose",
            description="Untrusted laptop prose",
        ),
    )


def _skus() -> tuple[CatalogSkuV2, ...]:
    return (
        CatalogSkuV2(
            sku_id=_sku_id(2),
            product_id=_product_id(2),
            merchant_sku="DOCK-1",
            display_name="Dock SKU prose",
            attributes=(
                _attribute(
                    "ports",
                    AttributeValueType.INTEGER,
                    4,
                    ProvenanceLabel.CLAIMED,
                    3,
                ),
            ),
        ),
        CatalogSkuV2(
            sku_id=_sku_id(1),
            product_id=_product_id(1),
            merchant_sku="LPT-16",
            display_name="Laptop SKU prose",
            attributes=(
                _attribute(
                    "ram_gb",
                    AttributeValueType.INTEGER,
                    16,
                    ProvenanceLabel.VERIFIED,
                    2,
                ),
                _attribute(
                    "brand",
                    AttributeValueType.STRING,
                    "Clear",
                    ProvenanceLabel.CLAIMED,
                    1,
                ),
            ),
        ),
    )


def _catalog(**changes: object) -> MerchantCatalogV2:
    values: dict[str, object] = {
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "generated_at": _GENERATED_AT,
        "products": _products(),
        "skus": _skus(),
        **changes,
    }
    return MerchantCatalogV2(**values)


def _inventory_lines() -> tuple[InventoryLineV2, ...]:
    return (
        InventoryLineV2(
            sku_id=_sku_id(2),
            quantity_available=6,
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(102),
        ),
        InventoryLineV2(
            sku_id=_sku_id(1),
            quantity_available=10,
            provenance=ProvenanceLabel.VERIFIED,
            evidence_reference_id=_evidence_id(101),
        ),
    )


def _inventory(**changes: object) -> InventorySnapshotV2:
    values: dict[str, object] = {
        "snapshot_id": _SNAPSHOT_ID,
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "captured_at": _CAPTURED_AT,
        "lines": _inventory_lines(),
        **changes,
    }
    return InventorySnapshotV2(**values)


def _economic_rule(
    index: int = 1,
    *,
    cost: int = 400,
    margin: int = 100,
    max_quantity: int = 8,
) -> MerchantSkuEconomicRuleV2:
    return MerchantSkuEconomicRuleV2(
        sku_id=_sku_id(index),
        unit_cost_basis=Money(amount_paise=cost),
        minimum_margin=Money(amount_paise=margin),
        max_quantity_per_offer=max_quantity,
    )


def _economic_policy(**changes: object) -> MerchantEconomicPolicyV2:
    values: dict[str, object] = {
        "economic_policy_id": _ECONOMIC_POLICY_ID,
        "merchant_id": _MERCHANT_ID,
        "catalog_id": _CATALOG_ID,
        "sku_rules": (
            _economic_rule(2, cost=500, margin=50, max_quantity=4),
            _economic_rule(1),
        ),
        **changes,
    }
    return MerchantEconomicPolicyV2(**values)


def _candidate_line(
    index: int = 1,
    *,
    quantity: int = 5,
    price: int = 500,
) -> MerchantOfferCandidateLineV2:
    return MerchantOfferCandidateLineV2(
        sku_id=_sku_id(index),
        proposed_quantity=quantity,
        proposed_unit_price=Money(amount_paise=price),
    )


def _candidate(**changes: object) -> MerchantOfferCandidateV2:
    values: dict[str, object] = {
        "lines": (
            _candidate_line(2, quantity=3, price=600),
            _candidate_line(1),
        ),
        **changes,
    }
    return MerchantOfferCandidateV2(**values)


def _build(**changes: object) -> MerchantOfferV2:
    values: dict[str, object] = {
        "offer_id": _OFFER_ID,
        "buyer_policy": _buyer_policy(),
        "catalog": _catalog(),
        "inventory": _inventory(),
        "economic_policy": _economic_policy(),
        "candidate": _candidate(),
        **changes,
    }
    return build_merchant_offer_v2(**values)  # type: ignore[arg-type]


def _offer_line(index: int = 1, **changes: object) -> MerchantOfferLineV2:
    sku = next(sku for sku in _catalog().skus if sku.sku_id == _sku_id(index))
    inventory_line = next(line for line in _inventory().lines if line.sku_id == _sku_id(index))
    values: dict[str, object] = {
        "sku_id": _sku_id(index),
        "max_offer_quantity": 5 if index == 1 else 3,
        "unit_price": Money(amount_paise=500 if index == 1 else 600),
        "attributes": sku.attributes,
        "inventory_provenance": inventory_line.provenance,
        "inventory_evidence_reference_id": inventory_line.evidence_reference_id,
        **changes,
    }
    return MerchantOfferLineV2(**values)


def _offer(**changes: object) -> MerchantOfferV2:
    values: dict[str, object] = {
        "offer_id": _OFFER_ID,
        "market_id": _MARKET_ID,
        "merchant_id": _MERCHANT_ID,
        "catalog_id": _CATALOG_ID,
        "inventory_snapshot_id": _SNAPSHOT_ID,
        "buyer_policy_commitment_sha256": "a" * 64,
        "merchant_catalog_commitment_sha256": "b" * 64,
        "inventory_snapshot_commitment_sha256": "c" * 64,
        "lines": (_offer_line(2), _offer_line(1)),
        **changes,
    }
    return MerchantOfferV2(**values)


def _assert_build_error(
    expected: MerchantOfferBuildErrorCode,
    **changes: object,
) -> None:
    with pytest.raises(MerchantOfferBuildError) as caught:
        _build(**changes)
    assert caught.value.code is expected


def test_merchant_versions_and_commitment_versions_are_exact() -> None:
    assert MERCHANT_SKU_ECONOMIC_RULE_V2_VERSION == "merchant-sku-economic-rule-v2"
    assert MERCHANT_ECONOMIC_POLICY_V2_VERSION == "merchant-economic-policy-v2"
    assert MERCHANT_OFFER_CANDIDATE_LINE_V2_VERSION == "merchant-offer-candidate-line-v2"
    assert MERCHANT_OFFER_CANDIDATE_V2_VERSION == "merchant-offer-candidate-v2"
    assert MERCHANT_OFFER_LINE_V2_VERSION == "merchant-offer-line-v2"
    assert MERCHANT_OFFER_V2_VERSION == "merchant-offer-v2"
    assert BUYER_POLICY_V2_COMMITMENT_VERSION == "sha256-buyer-policy-v2-clear-json-v1"
    assert MERCHANT_CATALOG_V2_COMMITMENT_VERSION == "sha256-merchant-catalog-v2-clear-json-v1"
    assert INVENTORY_SNAPSHOT_V2_COMMITMENT_VERSION == (
        "sha256-inventory-snapshot-v2-clear-json-v1"
    )


def test_economic_rule_has_exact_fields_and_versions() -> None:
    rule = _economic_rule()

    assert rule.schema_version == "2"
    assert rule.merchant_sku_economic_rule_version == "merchant-sku-economic-rule-v2"
    assert tuple(MerchantSkuEconomicRuleV2.model_fields) == (
        "schema_version",
        "merchant_sku_economic_rule_version",
        "sku_id",
        "unit_cost_basis",
        "minimum_margin",
        "max_quantity_per_offer",
    )


@pytest.mark.parametrize(("cost", "margin"), [(0, 0), (0, 100), (100, 0)])
def test_economic_rule_accepts_zero_cost_or_margin(cost: int, margin: int) -> None:
    rule = _economic_rule(cost=cost, margin=margin)

    assert rule.unit_cost_basis.amount_paise == cost
    assert rule.minimum_margin.amount_paise == margin


def test_economic_rule_accepts_exact_money_ceiling_and_rejects_overflow() -> None:
    assert _economic_rule(cost=MAX_MONEY_PAISE, margin=0).unit_cost_basis.amount_paise == (
        MAX_MONEY_PAISE
    )
    with pytest.raises(ValidationError):
        _economic_rule(cost=MAX_MONEY_PAISE, margin=1)


@pytest.mark.parametrize("quantity", [0, MAX_QUANTITY + 1, True, False, 1.0, "1"])
def test_economic_rule_requires_strict_positive_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        MerchantSkuEconomicRuleV2(
            sku_id=_sku_id(1),
            unit_cost_basis=Money(amount_paise=0),
            minimum_margin=Money(amount_paise=0),
            max_quantity_per_offer=quantity,
        )


def test_economic_policy_has_exact_fields_and_allowlist_order() -> None:
    policy = _economic_policy()

    assert tuple(MerchantEconomicPolicyV2.model_fields) == (
        "schema_version",
        "merchant_economic_policy_version",
        "economic_policy_id",
        "merchant_id",
        "catalog_id",
        "sku_rules",
    )
    assert tuple(rule.sku_id for rule in policy.sku_rules) == (_sku_id(1), _sku_id(2))


def test_economic_policy_requires_nonempty_tuple_rules() -> None:
    with pytest.raises(ValidationError):
        MerchantEconomicPolicyV2(
            economic_policy_id=_ECONOMIC_POLICY_ID,
            merchant_id=_MERCHANT_ID,
            catalog_id=_CATALOG_ID,
        )
    with pytest.raises(ValidationError):
        _economic_policy(sku_rules=())
    with pytest.raises(ValidationError):
        _economic_policy(sku_rules=[_economic_rule()])


def test_economic_policy_rejects_duplicate_sku_rules() -> None:
    with pytest.raises(ValidationError):
        _economic_policy(sku_rules=(_economic_rule(), _economic_rule()))


def test_economic_policy_rule_bound_is_exact() -> None:
    rules = tuple(_economic_rule(index + 1) for index in range(MAX_MERCHANT_ECONOMIC_RULES))

    assert len(_economic_policy(sku_rules=rules).sku_rules) == MAX_MERCHANT_ECONOMIC_RULES
    with pytest.raises(ValidationError):
        _economic_policy(sku_rules=(*rules, _economic_rule(MAX_MERCHANT_ECONOMIC_RULES + 1)))


def test_candidate_line_has_exact_fields_and_strict_values() -> None:
    line = _candidate_line()

    assert tuple(MerchantOfferCandidateLineV2.model_fields) == (
        "schema_version",
        "merchant_offer_candidate_line_version",
        "sku_id",
        "proposed_quantity",
        "proposed_unit_price",
    )
    assert line.proposed_quantity == 5
    assert line.proposed_unit_price == Money(amount_paise=500)


@pytest.mark.parametrize("quantity", [0, True, False, 1.0, "1"])
def test_candidate_line_rejects_nonpositive_or_non_strict_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        MerchantOfferCandidateLineV2(
            sku_id=_sku_id(1),
            proposed_quantity=quantity,
            proposed_unit_price=Money(amount_paise=500),
        )


def test_candidate_has_exact_identity_free_fields_and_normalized_lines() -> None:
    candidate = _candidate()

    assert tuple(MerchantOfferCandidateV2.model_fields) == (
        "schema_version",
        "merchant_offer_candidate_version",
        "lines",
    )
    assert tuple(line.sku_id for line in candidate.lines) == (_sku_id(1), _sku_id(2))


@pytest.mark.parametrize(
    "injected",
    [
        {"market_id": _MARKET_ID},
        {"merchant_id": _MERCHANT_ID},
        {"catalog_id": _CATALOG_ID},
        {"inventory_snapshot_id": _SNAPSHOT_ID},
        {"attributes": ()},
        {"inventory_provenance": ProvenanceLabel.VERIFIED},
        {"inventory_evidence_reference_id": _evidence_id(999)},
    ],
)
def test_candidate_line_rejects_source_authority_injection(injected: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MerchantOfferCandidateLineV2(
            sku_id=_sku_id(1),
            proposed_quantity=1,
            proposed_unit_price=Money(amount_paise=500),
            **injected,
        )


def test_candidate_requires_nonempty_tuple_lines() -> None:
    with pytest.raises(ValidationError):
        MerchantOfferCandidateV2()
    with pytest.raises(ValidationError):
        _candidate(lines=())
    with pytest.raises(ValidationError):
        _candidate(lines=[_candidate_line()])


def test_candidate_rejects_duplicate_sku_lines() -> None:
    with pytest.raises(ValidationError):
        _candidate(lines=(_candidate_line(), _candidate_line(price=501)))


def test_candidate_line_bound_is_exact() -> None:
    lines = tuple(_candidate_line(index + 1) for index in range(MAX_OFFER_LINES))

    assert len(_candidate(lines=lines).lines) == MAX_OFFER_LINES
    with pytest.raises(ValidationError):
        _candidate(lines=(*lines, _candidate_line(MAX_OFFER_LINES + 1)))


def test_offer_line_has_exact_fields_and_normalizes_attributes() -> None:
    attributes = tuple(reversed(_offer_line().attributes))
    line = _offer_line(attributes=attributes)

    assert tuple(MerchantOfferLineV2.model_fields) == (
        "schema_version",
        "merchant_offer_line_version",
        "sku_id",
        "max_offer_quantity",
        "unit_price",
        "attributes",
        "inventory_provenance",
        "inventory_evidence_reference_id",
    )
    assert tuple(attribute.attribute_key for attribute in line.attributes) == ("brand", "ram_gb")


def test_offer_line_rejects_list_and_duplicate_attributes() -> None:
    line = _offer_line()
    with pytest.raises(ValidationError):
        _offer_line(attributes=list(line.attributes))
    with pytest.raises(ValidationError):
        _offer_line(attributes=(line.attributes[0], line.attributes[0]))


@pytest.mark.parametrize("quantity", [0, True, False, 1.0, "1"])
def test_offer_line_requires_strict_positive_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        _offer_line(max_offer_quantity=quantity)


def test_offer_has_exact_fields_versions_and_normalized_lines() -> None:
    offer = _offer()

    assert tuple(MerchantOfferV2.model_fields) == (
        "schema_version",
        "merchant_offer_version",
        "offer_id",
        "market_id",
        "merchant_id",
        "catalog_id",
        "inventory_snapshot_id",
        "buyer_policy_commitment_version",
        "buyer_policy_commitment_sha256",
        "merchant_catalog_commitment_version",
        "merchant_catalog_commitment_sha256",
        "inventory_snapshot_commitment_version",
        "inventory_snapshot_commitment_sha256",
        "lines",
    )
    assert offer.buyer_policy_commitment_version == BUYER_POLICY_V2_COMMITMENT_VERSION
    assert offer.merchant_catalog_commitment_version == MERCHANT_CATALOG_V2_COMMITMENT_VERSION
    assert offer.inventory_snapshot_commitment_version == INVENTORY_SNAPSHOT_V2_COMMITMENT_VERSION
    assert tuple(line.sku_id for line in offer.lines) == (_sku_id(1), _sku_id(2))


@pytest.mark.parametrize(
    "digest",
    ["A" * 64, " a" * 32, "0x" + "a" * 62, "a" * 63, "a" * 65, "é" * 64, 1, None],
)
def test_offer_rejects_noncanonical_commitment_digest(digest: object) -> None:
    with pytest.raises(ValidationError):
        _offer(buyer_policy_commitment_sha256=digest)


def test_offer_requires_tuple_unique_lines() -> None:
    with pytest.raises(ValidationError):
        _offer(lines=[_offer_line()])
    with pytest.raises(ValidationError):
        _offer(lines=(_offer_line(), _offer_line(unit_price=Money(amount_paise=501))))


def test_offer_line_bound_is_exact() -> None:
    lines = tuple(
        _offer_line(
            1,
            sku_id=_sku_id(index + 1),
            inventory_evidence_reference_id=_evidence_id(500 + index),
        )
        for index in range(MAX_OFFER_LINES)
    )

    assert len(_offer(lines=lines).lines) == MAX_OFFER_LINES
    with pytest.raises(ValidationError):
        _offer(
            lines=(
                *lines,
                _offer_line(
                    1,
                    sku_id=_sku_id(MAX_OFFER_LINES + 1),
                    inventory_evidence_reference_id=_evidence_id(999),
                ),
            )
        )


@pytest.mark.parametrize(
    "model",
    [
        _economic_rule(),
        _economic_policy(),
        _candidate_line(),
        _candidate(),
        _offer_line(),
        _offer(),
    ],
)
def test_merchant_models_are_frozen(model: object) -> None:
    with pytest.raises(ValidationError):
        model.schema_version = "changed"  # type: ignore[attr-defined]


def test_merchant_models_forbid_extra_fields() -> None:
    factories: tuple[Callable[[], object], ...] = (
        lambda: MerchantSkuEconomicRuleV2(
            sku_id=_sku_id(1),
            unit_cost_basis=Money(amount_paise=1),
            minimum_margin=Money(amount_paise=1),
            max_quantity_per_offer=1,
            extra=True,
        ),
        lambda: _economic_policy(extra=True),
        lambda: MerchantOfferCandidateLineV2(
            sku_id=_sku_id(1),
            proposed_quantity=1,
            proposed_unit_price=Money(amount_paise=1),
            market_id=_MARKET_ID,
        ),
        lambda: _candidate(merchant_id=_MERCHANT_ID),
        lambda: _offer_line(extra=True),
        lambda: _offer(extra=True),
    )
    for factory in factories:
        with pytest.raises(ValidationError):
            factory()


def test_merchant_models_reject_version_mismatch() -> None:
    factories: tuple[Callable[[], object], ...] = (
        lambda: MerchantSkuEconomicRuleV2(
            merchant_sku_economic_rule_version="merchant-sku-economic-rule-v3",
            sku_id=_sku_id(1),
            unit_cost_basis=Money(amount_paise=1),
            minimum_margin=Money(amount_paise=1),
            max_quantity_per_offer=1,
        ),
        lambda: _economic_policy(merchant_economic_policy_version="merchant-economic-policy-v3"),
        lambda: MerchantOfferCandidateLineV2(
            merchant_offer_candidate_line_version="merchant-offer-candidate-line-v3",
            sku_id=_sku_id(1),
            proposed_quantity=1,
            proposed_unit_price=Money(amount_paise=1),
        ),
        lambda: _candidate(merchant_offer_candidate_version="merchant-offer-candidate-v3"),
        lambda: _offer_line(merchant_offer_line_version="merchant-offer-line-v3"),
        lambda: _offer(merchant_offer_version="merchant-offer-v3"),
    )
    for factory in factories:
        with pytest.raises(ValidationError):
            factory()


def test_commitments_are_exact_hashes_of_canonical_source_bytes() -> None:
    buyer_policy = _buyer_policy()
    catalog = _catalog()
    inventory = _inventory()

    assert (
        buyer_policy_v2_commitment(buyer_policy)
        == sha256(canonical_buyer_policy_v2_bytes(buyer_policy)).hexdigest()
    )
    assert (
        merchant_catalog_v2_commitment(catalog)
        == sha256(canonical_merchant_catalog_v2_bytes(catalog)).hexdigest()
    )
    assert (
        inventory_snapshot_v2_commitment(inventory)
        == sha256(canonical_inventory_snapshot_v2_bytes(inventory)).hexdigest()
    )


def test_commitments_change_with_protected_source_content() -> None:
    assert buyer_policy_v2_commitment(_buyer_policy()) != buyer_policy_v2_commitment(
        _buyer_policy(max_total_payment=Money(amount_paise=10_001))
    )
    assert merchant_catalog_v2_commitment(_catalog()) != merchant_catalog_v2_commitment(
        _catalog(generated_at=datetime(2027, 3, 4, 9, 0, 1, tzinfo=UTC))
    )
    assert inventory_snapshot_v2_commitment(_inventory()) != inventory_snapshot_v2_commitment(
        _inventory(captured_at=datetime(2027, 3, 4, 9, 30, 1, tzinfo=UTC))
    )


def test_commitments_ignore_semantically_irrelevant_collection_order() -> None:
    assert merchant_catalog_v2_commitment(_catalog()) == merchant_catalog_v2_commitment(
        _catalog(products=tuple(reversed(_products())), skus=tuple(reversed(_skus())))
    )
    assert inventory_snapshot_v2_commitment(_inventory()) == inventory_snapshot_v2_commitment(
        _inventory(lines=tuple(reversed(_inventory_lines())))
    )


class _BuyerPolicySubclass(BuyerPolicyV2):
    pass


class _CatalogSubclass(MerchantCatalogV2):
    pass


class _InventorySubclass(InventorySnapshotV2):
    pass


class _EconomicPolicySubclass(MerchantEconomicPolicyV2):
    pass


class _CandidateSubclass(MerchantOfferCandidateV2):
    pass


def _buyer_policy_subclass() -> _BuyerPolicySubclass:
    return _BuyerPolicySubclass(
        market_spec=_market(),
        max_total_payment=Money(amount_paise=10_000),
        eligible_merchant_ids=(_MERCHANT_ID, _OTHER_ELIGIBLE_MERCHANT_ID),
        offer_deadline=_DEADLINE,
        mechanism_version="heterogeneous-mechanism-test-v1",
        objective_version="heterogeneous-objective-test-v1",
    )


def _catalog_subclass() -> _CatalogSubclass:
    return _CatalogSubclass(
        catalog_id=_CATALOG_ID,
        merchant_id=_MERCHANT_ID,
        generated_at=_GENERATED_AT,
        products=_products(),
        skus=_skus(),
    )


def _inventory_subclass() -> _InventorySubclass:
    return _InventorySubclass(
        snapshot_id=_SNAPSHOT_ID,
        catalog_id=_CATALOG_ID,
        merchant_id=_MERCHANT_ID,
        captured_at=_CAPTURED_AT,
        lines=_inventory_lines(),
    )


def _economic_policy_subclass() -> _EconomicPolicySubclass:
    policy = _economic_policy()
    return _EconomicPolicySubclass(
        economic_policy_id=policy.economic_policy_id,
        merchant_id=policy.merchant_id,
        catalog_id=policy.catalog_id,
        sku_rules=policy.sku_rules,
    )


def _candidate_subclass() -> _CandidateSubclass:
    return _CandidateSubclass(lines=_candidate().lines)


@pytest.mark.parametrize(
    ("commitment", "wrong_value"),
    [
        (buyer_policy_v2_commitment, None),
        (buyer_policy_v2_commitment, _buyer_policy_subclass()),
        (merchant_catalog_v2_commitment, _inventory()),
        (merchant_catalog_v2_commitment, _catalog_subclass()),
        (inventory_snapshot_v2_commitment, {}),
        (inventory_snapshot_v2_commitment, _inventory_subclass()),
    ],
)
def test_commitments_require_exact_source_types(
    commitment: Callable[..., str],
    wrong_value: object,
) -> None:
    with pytest.raises(TypeError):
        commitment(wrong_value)


def test_builder_success_copies_only_authoritative_and_candidate_fields() -> None:
    buyer_policy = _buyer_policy()
    catalog = _catalog()
    inventory = _inventory()
    candidate = _candidate()
    offer = _build(
        buyer_policy=buyer_policy,
        catalog=catalog,
        inventory=inventory,
        candidate=candidate,
    )

    assert offer.market_id == buyer_policy.market_spec.market_id
    assert offer.merchant_id == catalog.merchant_id
    assert offer.catalog_id == catalog.catalog_id
    assert offer.inventory_snapshot_id == inventory.snapshot_id
    assert offer.buyer_policy_commitment_sha256 == buyer_policy_v2_commitment(buyer_policy)
    assert offer.merchant_catalog_commitment_sha256 == merchant_catalog_v2_commitment(catalog)
    assert offer.inventory_snapshot_commitment_sha256 == inventory_snapshot_v2_commitment(inventory)
    assert tuple(line.sku_id for line in offer.lines) == (_sku_id(1), _sku_id(2))

    by_sku = {line.sku_id: line for line in offer.lines}
    source_skus = {sku.sku_id: sku for sku in catalog.skus}
    source_inventory = {line.sku_id: line for line in inventory.lines}
    candidate_lines = {line.sku_id: line for line in candidate.lines}
    for sku_id, line in by_sku.items():
        assert line.max_offer_quantity == candidate_lines[sku_id].proposed_quantity
        assert line.unit_price == candidate_lines[sku_id].proposed_unit_price
        assert line.attributes == source_skus[sku_id].attributes
        assert line.inventory_provenance is source_inventory[sku_id].provenance
        assert (
            line.inventory_evidence_reference_id == source_inventory[sku_id].evidence_reference_id
        )


def test_builder_preserves_floor_and_above_floor_prices_without_clamping() -> None:
    at_floor = _build(candidate=_candidate(lines=(_candidate_line(price=500),)))
    above_floor = _build(candidate=_candidate(lines=(_candidate_line(price=777),)))

    assert at_floor.lines[0].unit_price.amount_paise == 500
    assert above_floor.lines[0].unit_price.amount_paise == 777


def test_builder_does_not_evaluate_buyer_constraint_or_budget() -> None:
    impossible_constraint = HardConstraint(
        constraint_id=_rule_id(1),
        attribute_key="ram_gb",
        operator=ComparisonOperator.GTE,
        operand=AttributeValue(value_type=AttributeValueType.INTEGER, value=999),
        allowed_provenance=(ProvenanceLabel.VERIFIED,),
    )
    policy = _buyer_policy(
        market_spec=_market(hard_constraints=(impossible_constraint,)),
        max_total_payment=Money(amount_paise=0),
    )

    assert _build(buyer_policy=policy).lines


def test_builder_is_deterministic_and_does_not_mutate_sources() -> None:
    catalog = _catalog()
    inventory = _inventory()
    economic_policy = _economic_policy()
    candidate = _candidate()
    snapshots = (
        catalog.products,
        catalog.skus,
        inventory.lines,
        economic_policy.sku_rules,
        candidate.lines,
    )

    first = _build(
        catalog=catalog,
        inventory=inventory,
        economic_policy=economic_policy,
        candidate=candidate,
    )
    second = _build(
        catalog=catalog,
        inventory=inventory,
        economic_policy=economic_policy,
        candidate=candidate,
    )

    assert first == second
    assert snapshots == (
        catalog.products,
        catalog.skus,
        inventory.lines,
        economic_policy.sku_rules,
        candidate.lines,
    )


def test_semantically_reversed_inputs_build_equal_offers() -> None:
    forward = _build()
    reverse = _build(
        catalog=_catalog(products=tuple(reversed(_products())), skus=tuple(reversed(_skus()))),
        inventory=_inventory(lines=tuple(reversed(_inventory_lines()))),
        economic_policy=_economic_policy(sku_rules=tuple(reversed(_economic_policy().sku_rules))),
        candidate=_candidate(lines=tuple(reversed(_candidate().lines))),
    )

    assert forward == reverse
    assert canonical_merchant_offer_v2_bytes(forward) == canonical_merchant_offer_v2_bytes(reverse)


def test_build_error_code_contract_is_exact() -> None:
    assert tuple(MerchantOfferBuildErrorCode) == (
        MerchantOfferBuildErrorCode.MERCHANT_NOT_ELIGIBLE,
        MerchantOfferBuildErrorCode.INVENTORY_MERCHANT_MISMATCH,
        MerchantOfferBuildErrorCode.INVENTORY_CATALOG_MISMATCH,
        MerchantOfferBuildErrorCode.ECONOMIC_POLICY_MERCHANT_MISMATCH,
        MerchantOfferBuildErrorCode.ECONOMIC_POLICY_CATALOG_MISMATCH,
        MerchantOfferBuildErrorCode.ECONOMIC_POLICY_UNKNOWN_SKU,
        MerchantOfferBuildErrorCode.CANDIDATE_UNKNOWN_CATALOG_SKU,
        MerchantOfferBuildErrorCode.CANDIDATE_MISSING_INVENTORY,
        MerchantOfferBuildErrorCode.CANDIDATE_NOT_ALLOWED_BY_POLICY,
        MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_INVENTORY,
        MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_POLICY_QUANTITY,
        MerchantOfferBuildErrorCode.CANDIDATE_PRICE_BELOW_FLOOR,
    )
    assert tuple(code.value for code in MerchantOfferBuildErrorCode) == tuple(
        code.name for code in MerchantOfferBuildErrorCode
    )


def test_builder_rejects_ineligible_merchant() -> None:
    policy = _buyer_policy(
        eligible_merchant_ids=(_OTHER_ELIGIBLE_MERCHANT_ID, _OUTSIDER_MERCHANT_ID)
    )
    _assert_build_error(MerchantOfferBuildErrorCode.MERCHANT_NOT_ELIGIBLE, buyer_policy=policy)


def test_builder_rejects_inventory_merchant_mismatch() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.INVENTORY_MERCHANT_MISMATCH,
        inventory=_inventory(merchant_id=_OUTSIDER_MERCHANT_ID),
    )


def test_builder_rejects_inventory_catalog_mismatch() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.INVENTORY_CATALOG_MISMATCH,
        inventory=_inventory(catalog_id=_OTHER_CATALOG_ID),
    )


def test_builder_rejects_economic_policy_merchant_mismatch() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.ECONOMIC_POLICY_MERCHANT_MISMATCH,
        economic_policy=_economic_policy(merchant_id=_OUTSIDER_MERCHANT_ID),
    )


def test_builder_rejects_economic_policy_catalog_mismatch() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.ECONOMIC_POLICY_CATALOG_MISMATCH,
        economic_policy=_economic_policy(catalog_id=_OTHER_CATALOG_ID),
    )


def test_builder_rejects_economic_policy_unknown_sku() -> None:
    policy = _economic_policy(
        sku_rules=(*_economic_policy().sku_rules, _economic_rule(3)),
    )
    _assert_build_error(
        MerchantOfferBuildErrorCode.ECONOMIC_POLICY_UNKNOWN_SKU,
        economic_policy=policy,
    )


def test_builder_rejects_candidate_unknown_catalog_sku() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.CANDIDATE_UNKNOWN_CATALOG_SKU,
        candidate=_candidate(lines=(_candidate_line(3),)),
    )


def test_builder_rejects_candidate_missing_inventory() -> None:
    second_line = next(line for line in _inventory().lines if line.sku_id == _sku_id(2))
    _assert_build_error(
        MerchantOfferBuildErrorCode.CANDIDATE_MISSING_INVENTORY,
        inventory=_inventory(lines=(second_line,)),
        candidate=_candidate(lines=(_candidate_line(1),)),
    )


def test_builder_rejects_candidate_not_allowed_by_policy() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.CANDIDATE_NOT_ALLOWED_BY_POLICY,
        economic_policy=_economic_policy(sku_rules=(_economic_rule(2),)),
        candidate=_candidate(lines=(_candidate_line(1),)),
    )


def test_builder_rejects_candidate_above_inventory() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_INVENTORY,
        candidate=_candidate(lines=(_candidate_line(1, quantity=11),)),
    )


def test_builder_rejects_candidate_above_policy_quantity() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_POLICY_QUANTITY,
        candidate=_candidate(lines=(_candidate_line(1, quantity=9),)),
    )


def test_builder_rejects_candidate_price_below_floor() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.CANDIDATE_PRICE_BELOW_FLOOR,
        candidate=_candidate(lines=(_candidate_line(1, price=499),)),
    )


def test_builder_cross_object_failure_precedence_is_exact() -> None:
    _assert_build_error(
        MerchantOfferBuildErrorCode.MERCHANT_NOT_ELIGIBLE,
        buyer_policy=_buyer_policy(
            eligible_merchant_ids=(_OTHER_ELIGIBLE_MERCHANT_ID, _OUTSIDER_MERCHANT_ID)
        ),
        inventory=_inventory(
            merchant_id=_OUTSIDER_MERCHANT_ID,
            catalog_id=_OTHER_CATALOG_ID,
        ),
        economic_policy=_economic_policy(
            merchant_id=_OUTSIDER_MERCHANT_ID,
            catalog_id=_OTHER_CATALOG_ID,
            sku_rules=(*_economic_policy().sku_rules, _economic_rule(3)),
        ),
        candidate=_candidate(lines=(_candidate_line(3),)),
    )


def test_builder_line_failure_precedence_is_stable_after_input_reversal() -> None:
    lines = (
        _candidate_line(2, quantity=7, price=600),
        _candidate_line(1, quantity=5, price=499),
    )
    for ordered_lines in (lines, tuple(reversed(lines))):
        _assert_build_error(
            MerchantOfferBuildErrorCode.CANDIDATE_PRICE_BELOW_FLOOR,
            candidate=_candidate(lines=ordered_lines),
        )


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("buyer_policy", None),
        ("buyer_policy", _buyer_policy_subclass()),
        ("catalog", {}),
        ("catalog", _catalog_subclass()),
        ("inventory", _catalog()),
        ("inventory", _inventory_subclass()),
        ("economic_policy", _candidate()),
        ("economic_policy", _economic_policy_subclass()),
        ("candidate", _economic_policy()),
        ("candidate", _candidate_subclass()),
    ],
)
def test_builder_requires_exact_object_input_types(field: str, wrong_value: object) -> None:
    with pytest.raises(TypeError):
        _build(**{field: wrong_value})


def test_builder_validates_caller_supplied_offer_id() -> None:
    with pytest.raises(ValidationError):
        _build(offer_id="not-a-uuid")


def test_build_error_code_is_read_only() -> None:
    error = MerchantOfferBuildError(MerchantOfferBuildErrorCode.CANDIDATE_PRICE_BELOW_FLOOR)

    with pytest.raises(AttributeError):
        error.code = MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_INVENTORY  # type: ignore[misc]
