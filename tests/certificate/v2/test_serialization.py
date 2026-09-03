import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel

from clear_market.certificate.v2 import (
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimStatusV2,
    AllocationClaimV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
    allocation_certificate_v2_digest,
    canonical_allocation_certificate_v2_bytes,
)
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
    MerchantOfferLineV2,
    MerchantOfferV2,
    MerchantSigningIdentityV2,
    ProvenanceLabel,
    SignedMerchantOfferV2,
    SoftPreference,
    buyer_policy_v2_commitment,
    inventory_snapshot_v2_commitment,
    merchant_catalog_v2_commitment,
)
from clear_market.commerce.offer_serialization import canonical_merchant_offer_v2_bytes
from clear_market.domain import Money

_MARKET_ID = "b1000000-0000-4000-8000-000000000001"
_BUYER_ID = "b2000000-0000-4000-8000-000000000001"
_CERTIFICATE_ID = "ba000000-0000-4000-8000-000000000001"
_OTHER_CERTIFICATE_ID = "ba000000-0000-4000-8000-000000000002"
_HARD_ID = "bb000000-0000-4000-8000-000000000001"
_SOFT_ID = "bc000000-0000-4000-8000-000000000001"
_OFFER_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_CATALOG_TIME = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
_INVENTORY_TIME = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
_RECEIVED_BEFORE_DEADLINE = _OFFER_DEADLINE - timedelta(seconds=2)
_RECEIVED_AFTER_DEADLINE = _OFFER_DEADLINE + timedelta(microseconds=1)
_CANDIDATE_GOLDEN_BYTE_LENGTH = 14_454
_CANDIDATE_GOLDEN_SHA256 = "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def _merchant_id(index: int) -> str:
    return f"b3000000-{index:04x}-4000-8000-000000000001"


def _catalog_id(index: int) -> str:
    return f"b4000000-{index:04x}-4000-8000-000000000001"


def _product_id(index: int) -> str:
    return f"b5000000-{index:04x}-4000-8000-000000000001"


def _sku_id(index: int) -> str:
    return f"b6000000-{index:04x}-4000-8000-000000000001"


def _snapshot_id(index: int) -> str:
    return f"b7000000-{index:04x}-4000-8000-000000000001"


def _offer_id(index: int) -> str:
    return f"b8000000-{index:04x}-4000-8000-000000000001"


def _evidence_id(index: int, suffix: int) -> str:
    return f"b9000000-{index:04x}-4000-8000-{suffix:012x}"


def _validated_copy[ModelT: BaseModel](model: ModelT, **changes: object) -> ModelT:
    fields = {name: model.__dict__[name] for name in type(model).model_fields}
    fields.update(changes)
    return type(model).model_validate(fields)


def _hard_constraint(*, brand: str = "Café") -> HardConstraint:
    return HardConstraint(
        constraint_id=_HARD_ID,
        attribute_key="brand",
        operator=ComparisonOperator.EQ,
        operand=AttributeValue(value_type=AttributeValueType.STRING, value=brand),
        allowed_provenance=(ProvenanceLabel.ATTESTED, ProvenanceLabel.VERIFIED),
    )


def _soft_preference(*, ram_gb: int = 16) -> SoftPreference:
    return SoftPreference(
        preference_id=_SOFT_ID,
        attribute_key="ram_gb",
        operator=ComparisonOperator.GTE,
        operand=AttributeValue(value_type=AttributeValueType.INTEGER, value=ram_gb),
        allowed_provenance=(ProvenanceLabel.CLAIMED, ProvenanceLabel.VERIFIED),
    )


def _policy(
    *,
    requested_quantity: int = 5,
    minimum_acceptable_quantity: int = 3,
    max_winners: int = 2,
    budget: int = 5_000,
    hard_constraint: HardConstraint | None = None,
    soft_preference: SoftPreference | None = None,
) -> BuyerPolicyV2:
    return BuyerPolicyV2(
        market_spec=MarketSpecV2(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=requested_quantity,
            minimum_acceptable_quantity=minimum_acceptable_quantity,
            max_winners=max_winners,
            hard_constraints=(hard_constraint or _hard_constraint(),),
            soft_preferences=(soft_preference or _soft_preference(),),
        ),
        max_total_payment=Money(amount_paise=budget),
        eligible_merchant_ids=(_merchant_id(2), _merchant_id(1)),
        offer_deadline=_OFFER_DEADLINE,
        mechanism_version="heterogeneous-pay-as-bid-v2",
        objective_version="quantity-cost-soft-objective-v2",
    )


def _attribute(
    index: int,
    *,
    value: str = "Café",
    provenance: ProvenanceLabel = ProvenanceLabel.VERIFIED,
    evidence_suffix: int = 1,
) -> CatalogAttributeV2:
    return CatalogAttributeV2(
        attribute_key="brand",
        value=AttributeValue(value_type=AttributeValueType.STRING, value=value),
        provenance=provenance,
        evidence_reference_id=_evidence_id(index, evidence_suffix),
    )


def _catalog(
    index: int,
    *,
    product_name: str | None = None,
    attribute: CatalogAttributeV2 | None = None,
) -> MerchantCatalogV2:
    return MerchantCatalogV2(
        catalog_id=_catalog_id(index),
        merchant_id=_merchant_id(index),
        generated_at=_CATALOG_TIME,
        products=(
            CatalogProductV2(
                product_id=_product_id(index),
                display_name=product_name or f"Portable {index}",
                description=f"Reviewable merchant product {index}",
            ),
        ),
        skus=(
            CatalogSkuV2(
                sku_id=_sku_id(index),
                product_id=_product_id(index),
                merchant_sku=f"SKU-{index}",
                display_name=f"Portable SKU {index}",
                attributes=(attribute or _attribute(index),),
            ),
        ),
    )


def _inventory(
    index: int,
    *,
    quantity: int | None = None,
    provenance: ProvenanceLabel = ProvenanceLabel.ATTESTED,
    evidence_suffix: int = 2,
) -> InventorySnapshotV2:
    return InventorySnapshotV2(
        snapshot_id=_snapshot_id(index),
        catalog_id=_catalog_id(index),
        merchant_id=_merchant_id(index),
        captured_at=_INVENTORY_TIME,
        lines=(
            InventoryLineV2(
                sku_id=_sku_id(index),
                quantity_available=quantity if quantity is not None else (4 if index == 1 else 3),
                provenance=provenance,
                evidence_reference_id=_evidence_id(index, evidence_suffix),
            ),
        ),
    )


def _private_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([index]) * 32)


def _identity(index: int, *, public_key_hex: str | None = None) -> MerchantSigningIdentityV2:
    key_bytes = (
        _private_key(index)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return MerchantSigningIdentityV2(
        merchant_id=_merchant_id(index),
        ed25519_public_key_hex=public_key_hex or key_bytes.hex(),
    )


def _offer(
    index: int,
    *,
    policy: BuyerPolicyV2,
    catalog: MerchantCatalogV2,
    inventory: InventorySnapshotV2,
    offer_id: str | None = None,
    max_quantity: int | None = None,
    price: int | None = None,
) -> MerchantOfferV2:
    return MerchantOfferV2(
        offer_id=offer_id or _offer_id(index),
        market_id=_MARKET_ID,
        merchant_id=_merchant_id(index),
        catalog_id=catalog.catalog_id,
        inventory_snapshot_id=inventory.snapshot_id,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
        merchant_catalog_commitment_sha256=merchant_catalog_v2_commitment(catalog),
        inventory_snapshot_commitment_sha256=inventory_snapshot_v2_commitment(inventory),
        lines=(
            MerchantOfferLineV2(
                sku_id=_sku_id(index),
                max_offer_quantity=(
                    max_quantity if max_quantity is not None else (3 if index == 1 else 2)
                ),
                unit_price=Money(
                    amount_paise=price if price is not None else (500 if index == 1 else 600)
                ),
                attributes=catalog.skus[0].attributes,
                inventory_provenance=inventory.lines[0].provenance,
                inventory_evidence_reference_id=inventory.lines[0].evidence_reference_id,
            ),
        ),
    )


def _signed_offer(
    index: int,
    *,
    offer: MerchantOfferV2,
    signature_hex: str | None = None,
) -> SignedMerchantOfferV2:
    signature = _private_key(index).sign(canonical_merchant_offer_v2_bytes(offer)).hex()
    return SignedMerchantOfferV2(
        offer=offer,
        signature_hex=signature_hex or signature,
    )


def _evidence(
    index: int,
    *,
    policy: BuyerPolicyV2,
    identity: MerchantSigningIdentityV2 | None = None,
    catalog: MerchantCatalogV2 | None = None,
    inventory: InventorySnapshotV2 | None = None,
    offer: MerchantOfferV2 | None = None,
    signature_hex: str | None = None,
    received_at: datetime = _RECEIVED_BEFORE_DEADLINE,
    admission_decision: MerchantOfferAdmissionDecisionV2 = (
        MerchantOfferAdmissionDecisionV2.ADMITTED
    ),
) -> MerchantOfferEvidenceV2:
    source_catalog = catalog or _catalog(index)
    source_inventory = inventory or _inventory(index)
    source_offer = offer or _offer(
        index,
        policy=policy,
        catalog=source_catalog,
        inventory=source_inventory,
    )
    return MerchantOfferEvidenceV2(
        received_at=received_at,
        admission_decision=admission_decision,
        signing_identity=identity or _identity(index),
        catalog=source_catalog,
        inventory=source_inventory,
        signed_offer=_signed_offer(index, offer=source_offer, signature_hex=signature_hex),
    )


def _allocation() -> AllocationClaimV2:
    lines = (
        AllocationClaimLineV2(
            offer_id=_offer_id(2),
            merchant_id=_merchant_id(2),
            sku_id=_sku_id(2),
            allocated_quantity=2,
            unit_payment=Money(amount_paise=600),
            line_payment=Money(amount_paise=1_200),
        ),
        AllocationClaimLineV2(
            offer_id=_offer_id(1),
            merchant_id=_merchant_id(1),
            sku_id=_sku_id(1),
            allocated_quantity=3,
            unit_payment=Money(amount_paise=500),
            line_payment=Money(amount_paise=1_500),
        ),
    )
    return AllocationClaimV2(
        market_id=_MARKET_ID,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(_policy()),
        status=AllocationClaimStatusV2.FEASIBLE,
        fulfilled_quantity=5,
        total_payment=Money(amount_paise=2_700),
        soft_preference_unit_score=0,
        winner_count=2,
        lines=lines,
    )


def _certificate(
    *,
    certificate_id: str = _CERTIFICATE_ID,
    policy: BuyerPolicyV2 | None = None,
    evidence: tuple[MerchantOfferEvidenceV2, ...] | None = None,
    allocation: AllocationClaimV2 | None = None,
) -> AllocationCertificateV2:
    buyer_policy = policy or _policy()
    if evidence is None:
        catalog = _catalog(1)
        inventory = _inventory(1)
        rejected_offer = _offer(
            1,
            policy=buyer_policy,
            catalog=catalog,
            inventory=inventory,
            offer_id=_offer_id(3),
            max_quantity=3,
            price=1,
        )
        evidence_values = (
            _evidence(1, policy=buyer_policy),
            _evidence(
                2,
                policy=buyer_policy,
                received_at=_OFFER_DEADLINE,
            ),
            _evidence(
                1,
                policy=buyer_policy,
                catalog=catalog,
                inventory=inventory,
                offer=rejected_offer,
                received_at=_RECEIVED_AFTER_DEADLINE,
                admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
            ),
        )
    else:
        evidence_values = evidence
    return AllocationCertificateV2(
        certificate_id=certificate_id,
        buyer_policy=buyer_policy,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(buyer_policy),
        merchant_offer_evidence=evidence_values,
        allocation=allocation or _allocation(),
    )


class _CertificateSubclass(AllocationCertificateV2):
    pass


def _nested_float_exists(value: object) -> bool:
    if type(value) is float:
        return True
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        return any(_nested_float_exists(item) for item in mapping.values())
    if type(value) is list:
        return any(_nested_float_exists(item) for item in cast(list[object], value))
    return False


def test_serializer_and_digest_require_exact_certificate_type() -> None:
    certificate = _certificate()
    subclass = _CertificateSubclass.model_construct(**certificate.__dict__)
    with pytest.raises(TypeError):
        canonical_allocation_certificate_v2_bytes(subclass)
    with pytest.raises(TypeError):
        allocation_certificate_v2_digest(subclass)
    for invalid in ({}, None, certificate.model_dump(mode="python")):
        with pytest.raises(TypeError):
            canonical_allocation_certificate_v2_bytes(cast(Any, invalid))


def test_canonical_bytes_are_deterministic_and_transcript_order_is_semantic() -> None:
    certificate = _certificate()
    first = canonical_allocation_certificate_v2_bytes(certificate)
    assert canonical_allocation_certificate_v2_bytes(certificate) == first

    reversed_input = _certificate(evidence=tuple(reversed(certificate.merchant_offer_evidence)))
    reversed_bytes = canonical_allocation_certificate_v2_bytes(reversed_input)
    assert reversed_input != certificate
    assert reversed_bytes != first
    assert allocation_certificate_v2_digest(reversed_input) != allocation_certificate_v2_digest(
        certificate
    )


def test_canonical_envelope_utf8_timestamps_and_compact_form_are_exact() -> None:
    data = canonical_allocation_certificate_v2_bytes(_certificate())
    parsed = json.loads(data)
    assert type(parsed) is dict
    assert set(parsed) == {"canonicalization_version", "payload", "payload_type"}
    assert parsed["canonicalization_version"] == "clear-json-v1"
    assert parsed["payload_type"] == "allocation_certificate_v2"
    assert parsed["payload"]["certificate_version"] == "allocation-certificate-v2"
    assert parsed["payload"]["buyer_policy"]["offer_deadline"] == ("2026-09-01T12:00:00.000000Z")
    first_evidence = parsed["payload"]["merchant_offer_evidence"][0]
    assert first_evidence["received_at"] == "2026-09-01T11:59:58.000000Z"
    assert first_evidence["admission_decision"] == "ADMITTED"
    assert first_evidence["catalog"]["generated_at"] == "2026-09-01T10:00:00.000000Z"
    assert first_evidence["inventory"]["captured_at"] == "2026-09-01T11:00:00.000000Z"
    assert b"Caf\xc3\xa9" in data
    assert b"\\u00e9" not in data
    assert data.decode("utf-8").encode("utf-8") == data
    assert b"\n" not in data
    assert b": " not in data
    assert b", " not in data
    assert not _nested_float_exists(parsed)


def test_complete_public_evidence_and_allocation_fields_are_projected() -> None:
    parsed = json.loads(canonical_allocation_certificate_v2_bytes(_certificate()))["payload"]
    assert set(parsed["buyer_policy"]) == {
        "buyer_policy_version",
        "eligible_merchant_ids",
        "market_spec",
        "max_total_payment",
        "mechanism_version",
        "objective_version",
        "offer_deadline",
        "schema_version",
    }
    market = parsed["buyer_policy"]["market_spec"]
    assert market["hard_constraints"][0]["allowed_provenance"] == ["ATTESTED", "VERIFIED"]
    assert market["soft_preferences"][0]["allowed_provenance"] == ["CLAIMED", "VERIFIED"]

    evidence = parsed["merchant_offer_evidence"][0]
    assert set(evidence) == {
        "admission_decision",
        "catalog",
        "inventory",
        "merchant_offer_evidence_version",
        "received_at",
        "schema_version",
        "signed_offer",
        "signing_identity",
    }
    assert len(evidence["signing_identity"]["ed25519_public_key_hex"]) == 64
    assert evidence["catalog"]["products"][0]["description"] == "Reviewable merchant product 1"
    catalog_attribute = evidence["catalog"]["skus"][0]["attributes"][0]
    assert catalog_attribute["provenance"] == "VERIFIED"
    assert catalog_attribute["evidence_reference_id"] == _evidence_id(1, 1)
    inventory_line = evidence["inventory"]["lines"][0]
    assert inventory_line["provenance"] == "ATTESTED"
    assert inventory_line["evidence_reference_id"] == _evidence_id(1, 2)
    signed_offer = evidence["signed_offer"]
    assert len(signed_offer["signature_hex"]) == 128
    offer_line = signed_offer["offer"]["lines"][0]
    assert offer_line["attributes"] == [catalog_attribute]
    assert offer_line["inventory_evidence_reference_id"] == _evidence_id(1, 2)

    allocation = parsed["allocation"]
    assert allocation["status"] == "FEASIBLE"
    assert allocation["fulfilled_quantity"] == 5
    assert allocation["total_payment"] == {"amount_paise": 2700, "currency": "INR"}
    assert len(allocation["lines"]) == 2
    assert allocation["soft_preference_unit_score"] == 0
    assert allocation["lines"][0]["line_payment"] == {
        "amount_paise": 1500,
        "currency": "INR",
    }

    transcript = parsed["merchant_offer_evidence"]
    assert [record["admission_decision"] for record in transcript] == [
        "ADMITTED",
        "ADMITTED",
        "REJECTED",
    ]
    assert transcript[1]["received_at"] == "2026-09-01T12:00:00.000000Z"
    assert transcript[2]["received_at"] == "2026-09-01T12:00:00.000001Z"
    assert transcript[2]["signed_offer"]["offer"]["offer_id"] == _offer_id(3)
    assert transcript[2]["signed_offer"]["offer"]["lines"][0]["unit_price"] == {
        "amount_paise": 1,
        "currency": "INR",
    }
    assert _offer_id(3) not in {line["offer_id"] for line in allocation["lines"]}
    # Slice 19B replays records in tuple order and excludes independently rejected records.


def _mutate_policy(certificate: AllocationCertificateV2, kind: str) -> AllocationCertificateV2:
    policy = certificate.buyer_policy
    market = policy.market_spec
    if kind == "requested_quantity":
        market = _validated_copy(market, requested_quantity=6)
    elif kind == "minimum_quantity":
        market = _validated_copy(market, minimum_acceptable_quantity=4)
    elif kind == "max_winners":
        market = _validated_copy(market, max_winners=1)
    elif kind == "hard_constraint":
        market = _validated_copy(market, hard_constraints=(_hard_constraint(brand="Acme"),))
    elif kind == "soft_preference":
        market = _validated_copy(market, soft_preferences=(_soft_preference(ram_gb=17),))
    elif kind == "budget":
        return _validated_copy(
            certificate,
            buyer_policy=_validated_copy(policy, max_total_payment=Money(amount_paise=5_001)),
        )
    else:
        raise AssertionError(kind)
    return _validated_copy(certificate, buyer_policy=_validated_copy(policy, market_spec=market))


def _replace_first_evidence(
    certificate: AllocationCertificateV2,
    replacement: MerchantOfferEvidenceV2,
) -> AllocationCertificateV2:
    return _validated_copy(
        certificate,
        merchant_offer_evidence=(replacement, *certificate.merchant_offer_evidence[1:]),
    )


def _mutate_evidence(certificate: AllocationCertificateV2, kind: str) -> AllocationCertificateV2:
    evidence = certificate.merchant_offer_evidence[0]
    if kind == "received_at":
        return _replace_first_evidence(
            certificate,
            _validated_copy(
                evidence,
                received_at=evidence.received_at + timedelta(microseconds=1),
            ),
        )
    if kind == "admission_decision":
        return _replace_first_evidence(
            certificate,
            _validated_copy(
                evidence,
                admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
            ),
        )
    if kind == "public_key":
        return _replace_first_evidence(
            certificate,
            _validated_copy(
                evidence,
                signing_identity=_validated_copy(
                    evidence.signing_identity,
                    ed25519_public_key_hex="0" * 64,
                ),
            ),
        )

    catalog = evidence.catalog
    sku = catalog.skus[0]
    attribute = sku.attributes[0]
    inventory = evidence.inventory
    inventory_line = inventory.lines[0]
    signed = evidence.signed_offer
    offer = signed.offer
    offer_line = offer.lines[0]
    if kind == "product_text":
        catalog = _validated_copy(
            catalog,
            products=(
                _validated_copy(catalog.products[0], description="Different public description"),
            ),
        )
        evidence = _validated_copy(evidence, catalog=catalog)
    elif kind in {"attribute_value", "attribute_provenance", "attribute_reference"}:
        attribute_changes: dict[str, object] = {
            "attribute_value": {
                "value": AttributeValue(value_type=AttributeValueType.STRING, value="Acme")
            },
            "attribute_provenance": {"provenance": ProvenanceLabel.CLAIMED},
            "attribute_reference": {"evidence_reference_id": _evidence_id(1, 9)},
        }[kind]
        changed_attribute = _validated_copy(attribute, **attribute_changes)
        catalog = _validated_copy(
            catalog,
            skus=(_validated_copy(sku, attributes=(changed_attribute,)),),
        )
        evidence = _validated_copy(evidence, catalog=catalog)
    elif kind in {"inventory_quantity", "inventory_provenance", "inventory_reference"}:
        inventory_changes: dict[str, object] = {
            "inventory_quantity": {"quantity_available": inventory_line.quantity_available + 1},
            "inventory_provenance": {"provenance": ProvenanceLabel.DERIVED},
            "inventory_reference": {"evidence_reference_id": _evidence_id(1, 8)},
        }[kind]
        inventory = _validated_copy(
            inventory,
            lines=(_validated_copy(inventory_line, **inventory_changes),),
        )
        evidence = _validated_copy(evidence, inventory=inventory)
    elif kind in {"offer_price", "offer_quantity", "signature"}:
        if kind == "signature":
            signed = _validated_copy(signed, signature_hex="f" * 128)
        else:
            line_changes: dict[str, object] = (
                {"unit_price": Money(amount_paise=offer_line.unit_price.amount_paise + 1)}
                if kind == "offer_price"
                else {"max_offer_quantity": offer_line.max_offer_quantity + 1}
            )
            offer = _validated_copy(offer, lines=(_validated_copy(offer_line, **line_changes),))
            signed = _validated_copy(signed, offer=offer)
        evidence = _validated_copy(evidence, signed_offer=signed)
    else:
        raise AssertionError(kind)
    return _replace_first_evidence(certificate, evidence)


def _mutate_allocation(certificate: AllocationCertificateV2, kind: str) -> AllocationCertificateV2:
    allocation = certificate.allocation
    first, second = allocation.lines
    if kind == "allocated_quantity":
        first = _validated_copy(
            first,
            allocated_quantity=4,
            line_payment=Money(amount_paise=2_000),
        )
        allocation = _validated_copy(
            allocation,
            fulfilled_quantity=6,
            total_payment=Money(amount_paise=3_200),
            lines=(first, second),
        )
    elif kind == "payment":
        first = _validated_copy(
            first,
            unit_payment=Money(amount_paise=501),
            line_payment=Money(amount_paise=1_503),
        )
        allocation = _validated_copy(
            allocation,
            total_payment=Money(amount_paise=2_703),
            lines=(first, second),
        )
    elif kind == "soft_score":
        allocation = _validated_copy(allocation, soft_preference_unit_score=5)
    else:
        raise AssertionError(kind)
    return _validated_copy(certificate, allocation=allocation)


@pytest.mark.parametrize(
    "kind",
    [
        "requested_quantity",
        "minimum_quantity",
        "max_winners",
        "budget",
        "hard_constraint",
        "soft_preference",
    ],
)
def test_buyer_policy_mutations_change_canonical_bytes_and_digest(kind: str) -> None:
    certificate = _certificate()
    mutated = _mutate_policy(certificate, kind)
    assert canonical_allocation_certificate_v2_bytes(mutated) != (
        canonical_allocation_certificate_v2_bytes(certificate)
    )
    assert allocation_certificate_v2_digest(mutated) != allocation_certificate_v2_digest(
        certificate
    )


@pytest.mark.parametrize(
    "kind",
    [
        "received_at",
        "admission_decision",
        "public_key",
        "product_text",
        "attribute_value",
        "attribute_provenance",
        "attribute_reference",
        "inventory_quantity",
        "inventory_provenance",
        "inventory_reference",
        "offer_price",
        "offer_quantity",
        "signature",
    ],
)
def test_identity_source_and_offer_mutations_change_bytes_and_digest(kind: str) -> None:
    certificate = _certificate()
    mutated = _mutate_evidence(certificate, kind)
    assert canonical_allocation_certificate_v2_bytes(mutated) != (
        canonical_allocation_certificate_v2_bytes(certificate)
    )
    assert allocation_certificate_v2_digest(mutated) != allocation_certificate_v2_digest(
        certificate
    )


@pytest.mark.parametrize("kind", ["allocated_quantity", "payment", "soft_score"])
def test_allocation_mutations_change_canonical_bytes_and_digest(kind: str) -> None:
    certificate = _certificate()
    mutated = _mutate_allocation(certificate, kind)
    assert canonical_allocation_certificate_v2_bytes(mutated) != (
        canonical_allocation_certificate_v2_bytes(certificate)
    )
    assert allocation_certificate_v2_digest(mutated) != allocation_certificate_v2_digest(
        certificate
    )


def test_digest_is_stable_sensitive_and_lowercase_sha256() -> None:
    certificate = _certificate()
    digest = allocation_certificate_v2_digest(certificate)
    assert allocation_certificate_v2_digest(certificate) == digest
    assert _LOWER_SHA256.fullmatch(digest) is not None

    changed_id = _certificate(certificate_id=_OTHER_CERTIFICATE_ID)
    changed_signature = _mutate_evidence(certificate, "signature")
    changed_source = _mutate_evidence(certificate, "inventory_quantity")
    changed_allocation = _mutate_allocation(certificate, "soft_score")
    assert (
        len(
            {
                digest,
                allocation_certificate_v2_digest(changed_id),
                allocation_certificate_v2_digest(changed_signature),
                allocation_certificate_v2_digest(changed_source),
                allocation_certificate_v2_digest(changed_allocation),
            }
        )
        == 5
    )


def test_candidate_canonical_certificate_v2_golden() -> None:
    data = canonical_allocation_certificate_v2_bytes(_certificate())
    digest = hashlib.sha256(data).hexdigest()
    assert len(data) == _CANDIDATE_GOLDEN_BYTE_LENGTH
    assert digest == _CANDIDATE_GOLDEN_SHA256
    assert allocation_certificate_v2_digest(_certificate()) == _CANDIDATE_GOLDEN_SHA256
