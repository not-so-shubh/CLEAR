import ast
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

import clear_market.certificate.v2.construction as construction_module
from clear_market.certificate.v2 import (
    AllocationCertificateV2,
    AllocationClaimStatusV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
    allocation_certificate_v2_digest,
    allocation_claim_v2_from_allocation_v2,
    build_allocation_certificate_v2,
    canonical_allocation_certificate_v2_bytes,
)
from clear_market.commerce import (
    BuyerPolicyV2,
    CatalogProductV2,
    CatalogSkuV2,
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
    build_and_sign_merchant_offer_v2,
    buyer_policy_v2_commitment,
)
from clear_market.domain import Money
from clear_market.mechanism.v2 import (
    AllocationLineV2,
    AllocationStatusV2,
    AllocationV2,
    allocate_market_v2,
)
from clear_market.verification.v2 import verify_allocation_certificate_v2

_MARKET_ID = "ca000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "ca000000-0000-4000-8000-000000000002"
_BUYER_ID = "cb000000-0000-4000-8000-000000000001"
_CERTIFICATE_ID = "cc000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2031, 6, 1, 12, 0, tzinfo=UTC)
_CATALOG_TIME = datetime(2031, 6, 1, 10, 0, tzinfo=UTC)
_INVENTORY_TIME = datetime(2031, 6, 1, 11, 0, tzinfo=UTC)
_RECEIVED_TIME = datetime(2031, 6, 1, 11, 59, 50, tzinfo=UTC)


def _merchant_id(index: int) -> str:
    return f"cd000000-0000-4000-8000-{index:012x}"


def _catalog_id(index: int) -> str:
    return f"ce000000-0000-4000-8000-{index:012x}"


def _product_id(index: int) -> str:
    return f"cf000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"d0000000-0000-4000-8000-{index:012x}"


def _snapshot_id(index: int) -> str:
    return f"d1000000-0000-4000-8000-{index:012x}"


def _inventory_evidence_id(index: int) -> str:
    return f"d2000000-0000-4000-8000-{index:012x}"


def _economic_policy_id(index: int) -> str:
    return f"d3000000-0000-4000-8000-{index:012x}"


def _offer_id(index: int) -> str:
    return f"d4000000-0000-4000-8000-{index:012x}"


def _policy(*, market_id: str = _MARKET_ID) -> BuyerPolicyV2:
    return BuyerPolicyV2(
        market_spec=MarketSpecV2(
            market_id=market_id,
            buyer_id=_BUYER_ID,
            requested_quantity=5,
            minimum_acceptable_quantity=5,
            max_winners=2,
            hard_constraints=(),
            soft_preferences=(),
        ),
        max_total_payment=Money(amount_paise=5_000),
        eligible_merchant_ids=(_merchant_id(2), _merchant_id(1)),
        offer_deadline=_DEADLINE,
        mechanism_version="heterogeneous-pay-as-bid-v2",
        objective_version="quantity-cost-soft-objective-v2",
    )


def _private_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([index]) * 32)


def _identity(index: int) -> MerchantSigningIdentityV2:
    public_key = (
        _private_key(index)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return MerchantSigningIdentityV2(
        merchant_id=_merchant_id(index),
        ed25519_public_key_hex=public_key.hex(),
    )


def _catalog(index: int) -> MerchantCatalogV2:
    return MerchantCatalogV2(
        catalog_id=_catalog_id(index),
        merchant_id=_merchant_id(index),
        generated_at=_CATALOG_TIME,
        products=(
            CatalogProductV2(
                product_id=_product_id(index),
                display_name=f"Deterministic product {index}",
                description="Certificate construction test fixture",
            ),
        ),
        skus=(
            CatalogSkuV2(
                sku_id=_sku_id(index),
                product_id=_product_id(index),
                merchant_sku=f"CERT-{index}",
                display_name=f"Deterministic SKU {index}",
                attributes=(),
            ),
        ),
    )


def _inventory(index: int) -> InventorySnapshotV2:
    quantity = 3 if index == 1 else 2
    return InventorySnapshotV2(
        snapshot_id=_snapshot_id(index),
        catalog_id=_catalog_id(index),
        merchant_id=_merchant_id(index),
        captured_at=_INVENTORY_TIME,
        lines=(
            InventoryLineV2(
                sku_id=_sku_id(index),
                quantity_available=quantity,
                provenance=ProvenanceLabel.VERIFIED,
                evidence_reference_id=_inventory_evidence_id(index),
            ),
        ),
    )


def _economic_policy(index: int) -> MerchantEconomicPolicyV2:
    quantity = 3 if index == 1 else 2
    return MerchantEconomicPolicyV2(
        economic_policy_id=_economic_policy_id(index),
        merchant_id=_merchant_id(index),
        catalog_id=_catalog_id(index),
        sku_rules=(
            MerchantSkuEconomicRuleV2(
                sku_id=_sku_id(index),
                unit_cost_basis=Money(amount_paise=300 + (index * 100)),
                minimum_margin=Money(amount_paise=100),
                max_quantity_per_offer=quantity,
            ),
        ),
    )


def _signed_offer(
    index: int,
    *,
    policy: BuyerPolicyV2,
    catalog: MerchantCatalogV2,
    inventory: InventorySnapshotV2,
) -> SignedMerchantOfferV2:
    quantity = 3 if index == 1 else 2
    price = 500 if index == 1 else 600
    return build_and_sign_merchant_offer_v2(
        offer_id=_offer_id(index),
        buyer_policy=policy,
        catalog=catalog,
        inventory=inventory,
        economic_policy=_economic_policy(index),
        candidate=MerchantOfferCandidateV2(
            lines=(
                MerchantOfferCandidateLineV2(
                    sku_id=_sku_id(index),
                    proposed_quantity=quantity,
                    proposed_unit_price=Money(amount_paise=price),
                ),
            ),
        ),
        signing_identity=_identity(index),
        private_key=_private_key(index),
    )


@dataclass(frozen=True)
class _AllocatedFixture:
    policy: BuyerPolicyV2
    identities: tuple[MerchantSigningIdentityV2, ...]
    evidence: tuple[MerchantOfferEvidenceV2, ...]
    allocation: AllocationV2


def _allocated_fixture() -> _AllocatedFixture:
    policy = _policy()
    catalogs = (_catalog(1), _catalog(2))
    inventories = (_inventory(1), _inventory(2))
    identities = (_identity(1), _identity(2))
    signed_offers = tuple(
        _signed_offer(
            index,
            policy=policy,
            catalog=catalogs[index - 1],
            inventory=inventories[index - 1],
        )
        for index in (1, 2)
    )
    evidence = tuple(
        MerchantOfferEvidenceV2(
            received_at=_RECEIVED_TIME + timedelta(seconds=index),
            admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
            signing_identity=identities[index - 1],
            catalog=catalogs[index - 1],
            inventory=inventories[index - 1],
            signed_offer=signed_offers[index - 1],
        )
        for index in (1, 2)
    )
    allocation = allocate_market_v2(
        buyer_policy=policy,
        signed_offers=signed_offers,
    )
    return _AllocatedFixture(
        policy=policy,
        identities=identities,
        evidence=evidence,
        allocation=allocation,
    )


def _manual_feasible_allocation(policy: BuyerPolicyV2) -> AllocationV2:
    lines = (
        AllocationLineV2(
            offer_id=_offer_id(2),
            merchant_id=_merchant_id(2),
            sku_id=_sku_id(2),
            allocated_quantity=2,
            unit_payment=Money(amount_paise=600),
            line_payment=Money(amount_paise=1_200),
        ),
        AllocationLineV2(
            offer_id=_offer_id(1),
            merchant_id=_merchant_id(1),
            sku_id=_sku_id(1),
            allocated_quantity=3,
            unit_payment=Money(amount_paise=500),
            line_payment=Money(amount_paise=1_500),
        ),
    )
    return AllocationV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
        status=AllocationStatusV2.FEASIBLE,
        fulfilled_quantity=5,
        total_payment=Money(amount_paise=2_700),
        soft_preference_unit_score=0,
        winner_count=2,
        lines=lines,
    )


def _manual_infeasible_allocation(policy: BuyerPolicyV2) -> AllocationV2:
    return AllocationV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
        status=AllocationStatusV2.INFEASIBLE,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=0,
        lines=(),
    )


def _allocation_copy(allocation: AllocationV2, **changes: object) -> AllocationV2:
    fields = {name: allocation.__dict__[name] for name in AllocationV2.model_fields}
    fields.update(changes)
    return AllocationV2.model_validate(fields)


def _certificate(fixture: _AllocatedFixture) -> AllocationCertificateV2:
    return build_allocation_certificate_v2(
        certificate_id=_CERTIFICATE_ID,
        buyer_policy=fixture.policy,
        merchant_offer_evidence=fixture.evidence,
        allocation=fixture.allocation,
    )


def test_feasible_allocation_projects_every_semantic_field_exactly() -> None:
    allocation = _manual_feasible_allocation(_policy())

    claim = allocation_claim_v2_from_allocation_v2(allocation)

    assert claim.model_dump(mode="json") == allocation.model_dump(mode="json")
    assert claim.status is AllocationClaimStatusV2.FEASIBLE
    assert claim.winner_count == 2
    assert len(claim.lines) == 2
    assert claim.total_payment is not allocation.total_payment
    assert all(
        projected is not source
        for projected, source in zip(claim.lines, allocation.lines, strict=True)
    )


def test_infeasible_allocation_projects_the_exact_zero_shape() -> None:
    allocation = _manual_infeasible_allocation(_policy())

    claim = allocation_claim_v2_from_allocation_v2(allocation)

    assert claim.model_dump(mode="json") == allocation.model_dump(mode="json")
    assert claim.status is AllocationClaimStatusV2.INFEASIBLE
    assert claim.fulfilled_quantity == 0
    assert claim.total_payment == Money(amount_paise=0)
    assert claim.soft_preference_unit_score == 0
    assert claim.winner_count == 0
    assert claim.lines == ()


def test_real_production_allocation_is_projected_without_a_manual_substitute() -> None:
    fixture = _allocated_fixture()

    claim = allocation_claim_v2_from_allocation_v2(fixture.allocation)

    assert type(fixture.allocation) is AllocationV2
    assert fixture.allocation.status is AllocationStatusV2.FEASIBLE
    assert fixture.allocation.winner_count == 2
    assert claim.model_dump(mode="json") == fixture.allocation.model_dump(mode="json")


def test_full_certificate_contains_the_exact_production_allocation_claim() -> None:
    fixture = _allocated_fixture()

    certificate = _certificate(fixture)

    assert type(certificate) is AllocationCertificateV2
    assert certificate.buyer_policy == fixture.policy
    assert certificate.buyer_policy is not fixture.policy
    assert certificate.buyer_policy_commitment_sha256 == buyer_policy_v2_commitment(fixture.policy)
    assert certificate.merchant_offer_evidence == fixture.evidence
    assert certificate.allocation == allocation_claim_v2_from_allocation_v2(fixture.allocation)


def test_independent_verifier_accepts_a_certificate_built_from_production_allocation() -> None:
    fixture = _allocated_fixture()

    result = verify_allocation_certificate_v2(
        _certificate(fixture),
        trusted_signing_identities=fixture.identities,
    )

    assert result.verified is True
    assert result.failure_code is None
    assert result.failed_evidence_index is None


def test_builder_rejects_policy_commitment_mismatch() -> None:
    fixture = _allocated_fixture()
    mismatched = _allocation_copy(
        fixture.allocation,
        buyer_policy_commitment_sha256="f" * 64,
    )

    with pytest.raises(ValueError, match="allocation commitment does not match buyer policy"):
        build_allocation_certificate_v2(
            certificate_id=_CERTIFICATE_ID,
            buyer_policy=fixture.policy,
            merchant_offer_evidence=fixture.evidence,
            allocation=mismatched,
        )


def test_builder_rejects_market_id_mismatch() -> None:
    fixture = _allocated_fixture()
    mismatched = _allocation_copy(fixture.allocation, market_id=_OTHER_MARKET_ID)

    with pytest.raises(ValueError, match="allocation market does not match buyer policy market"):
        build_allocation_certificate_v2(
            certificate_id=_CERTIFICATE_ID,
            buyer_policy=fixture.policy,
            merchant_offer_evidence=fixture.evidence,
            allocation=mismatched,
        )


class _AllocationSubclass(AllocationV2):
    pass


class _BuyerPolicySubclass(BuyerPolicyV2):
    pass


class _EvidenceTupleSubclass(tuple[MerchantOfferEvidenceV2, ...]):
    pass


def test_projection_rejects_wrong_subclass_and_malformed_allocation_inputs() -> None:
    allocation = _manual_feasible_allocation(_policy())
    subclass = _AllocationSubclass.model_validate(
        {name: allocation.__dict__[name] for name in AllocationV2.model_fields}
    )
    malformed = AllocationV2.model_construct(
        market_id=_MARKET_ID,
        buyer_policy_commitment_sha256="f" * 64,
        status=AllocationStatusV2.FEASIBLE,
    )
    malformed_line = AllocationLineV2.model_construct(
        offer_id=_offer_id(1),
        merchant_id=_merchant_id(1),
        sku_id=_sku_id(1),
        allocated_quantity=3,
        unit_payment=Money(amount_paise=500),
        line_payment=Money(amount_paise=1),
    )
    malformed_nested = AllocationV2.model_construct(
        **{
            name: allocation.__dict__[name] for name in AllocationV2.model_fields if name != "lines"
        },
        lines=(malformed_line, allocation.lines[1]),
    )

    for invalid in ({}, allocation.model_dump(mode="python"), subclass):
        with pytest.raises(TypeError):
            allocation_claim_v2_from_allocation_v2(cast(Any, invalid))
    with pytest.raises(ValueError, match="allocation must be a valid exact AllocationV2"):
        allocation_claim_v2_from_allocation_v2(malformed)
    with pytest.raises(ValueError, match="allocation must be a valid exact AllocationV2"):
        allocation_claim_v2_from_allocation_v2(malformed_nested)


def test_builder_rejects_nonexact_or_malformed_policy_and_evidence_inputs() -> None:
    fixture = _allocated_fixture()
    policy_subclass = _BuyerPolicySubclass.model_validate(fixture.policy.model_dump(mode="python"))
    malformed_policy = BuyerPolicyV2.model_construct(
        market_spec=fixture.policy.market_spec,
        max_total_payment=fixture.policy.max_total_payment,
    )

    with pytest.raises(TypeError):
        build_allocation_certificate_v2(
            certificate_id=_CERTIFICATE_ID,
            buyer_policy=policy_subclass,
            merchant_offer_evidence=fixture.evidence,
            allocation=fixture.allocation,
        )
    with pytest.raises(ValueError, match="buyer_policy must be a valid exact BuyerPolicyV2"):
        build_allocation_certificate_v2(
            certificate_id=_CERTIFICATE_ID,
            buyer_policy=malformed_policy,
            merchant_offer_evidence=fixture.evidence,
            allocation=fixture.allocation,
        )
    with pytest.raises(ValidationError):
        build_allocation_certificate_v2(
            certificate_id=_CERTIFICATE_ID,
            buyer_policy=fixture.policy,
            merchant_offer_evidence=cast(
                Any,
                _EvidenceTupleSubclass(fixture.evidence),
            ),
            allocation=fixture.allocation,
        )


def test_construction_has_no_authority_or_side_effect_dependencies() -> None:
    source_path = Path(cast(str, construction_module.__file__))
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    allowed_modules = {
        "pydantic",
        "clear_market.certificate.v2.models",
        "clear_market.commerce.market",
        "clear_market.commerce.merchant",
        "clear_market.domain",
        "clear_market.mechanism.v2.contracts",
    }
    forbidden_symbols = {
        "allocate_market_v2",
        "compute_oracle_allocation_v2",
        "verify_allocation_certificate_v2",
        "authorize_execution_v1",
    }
    referenced_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert imported_modules == allowed_modules
    assert referenced_names.isdisjoint(forbidden_symbols)
    assert not any(
        module.startswith(
            (
                "clear_market.oracle",
                "clear_market.verification",
                "clear_market.execution",
                "clear_market.persistence",
                "clear_market.payments",
            )
        )
        for module in imported_modules
    )


def test_identical_inputs_produce_identical_canonical_bytes_and_digest() -> None:
    fixture = _allocated_fixture()

    first = _certificate(fixture)
    second = _certificate(fixture)

    assert canonical_allocation_certificate_v2_bytes(first) == (
        canonical_allocation_certificate_v2_bytes(second)
    )
    assert allocation_certificate_v2_digest(first) == allocation_certificate_v2_digest(second)
