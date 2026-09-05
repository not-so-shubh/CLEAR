from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

import clear_market.certificate.v2 as certificate_v2
from clear_market.certificate.v2 import (
    ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    ALLOCATION_CERTIFICATE_V2_VERSION,
    MERCHANT_OFFER_EVIDENCE_V2_VERSION,
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimStatusV2,
    AllocationClaimV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
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
    MerchantOfferLineV2,
    MerchantOfferV2,
    MerchantSigningIdentityV2,
    ProvenanceLabel,
    SignedMerchantOfferV2,
    buyer_policy_v2_commitment,
    merchant_catalog_v2_commitment,
)
from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, MAX_SELLERS, Currency, Money
from clear_market.mechanism.v2 import AllocationLineV2, AllocationStatusV2, AllocationV2

_CERTIFICATE_ID = "a0000000-0000-4000-8000-000000000001"
_MARKET_ID = "a1000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "a1000000-0000-4000-8000-000000000002"
_BUYER_ID = "a2000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2028, 2, 3, 12, 0, tzinfo=UTC)
_GENERATED_AT = datetime(2028, 2, 3, 9, 0, tzinfo=UTC)
_CAPTURED_AT = datetime(2028, 2, 3, 10, 0, tzinfo=UTC)
_RECEIVED_AT = datetime(2028, 2, 3, 11, 59, 59, tzinfo=UTC)
_COMMITMENT = "a" * 64


def _merchant_id(index: int) -> str:
    return f"a3000000-0000-4000-8000-{index:012x}"


def _offer_id(index: int) -> str:
    return f"a4000000-0000-4000-8000-{index:012x}"


def _catalog_id(index: int) -> str:
    return f"a5000000-0000-4000-8000-{index:012x}"


def _snapshot_id(index: int) -> str:
    return f"a6000000-0000-4000-8000-{index:012x}"


def _product_id(index: int) -> str:
    return f"a7000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"a8000000-0000-4000-8000-{index:012x}"


def _evidence_id(index: int) -> str:
    return f"a9000000-0000-4000-8000-{index:012x}"


def _policy(**changes: object) -> BuyerPolicyV2:
    market = MarketSpecV2(
        market_id=_MARKET_ID,
        buyer_id=_BUYER_ID,
        requested_quantity=5,
        minimum_acceptable_quantity=2,
        max_winners=2,
        hard_constraints=(),
        soft_preferences=(),
    )
    values: dict[str, object] = {
        "market_spec": market,
        "max_total_payment": Money(amount_paise=10_000),
        "eligible_merchant_ids": (_merchant_id(2), _merchant_id(1)),
        "offer_deadline": _DEADLINE,
        "mechanism_version": "heterogeneous-pay-as-bid-v2",
        "objective_version": "quantity-cost-soft-objective-v2",
        **changes,
    }
    return BuyerPolicyV2(**values)


def _attribute(index: int) -> CatalogAttributeV2:
    return CatalogAttributeV2(
        attribute_key="ram_gb",
        value=AttributeValue(value_type=AttributeValueType.INTEGER, value=16 + index),
        provenance=ProvenanceLabel.VERIFIED,
        evidence_reference_id=_evidence_id(index),
    )


def _catalog(index: int = 1, **changes: object) -> MerchantCatalogV2:
    values: dict[str, object] = {
        "catalog_id": _catalog_id(index),
        "merchant_id": _merchant_id(index),
        "generated_at": _GENERATED_AT,
        "products": (
            CatalogProductV2(
                product_id=_product_id(index),
                display_name=f"Product {index}",
                description="Public catalog text",
            ),
        ),
        "skus": (
            CatalogSkuV2(
                sku_id=_sku_id(index),
                product_id=_product_id(index),
                merchant_sku=f"SKU-{index}",
                display_name=f"SKU {index}",
                attributes=(_attribute(index),),
            ),
        ),
        **changes,
    }
    return MerchantCatalogV2(**values)


def _inventory(index: int = 1, **changes: object) -> InventorySnapshotV2:
    values: dict[str, object] = {
        "snapshot_id": _snapshot_id(index),
        "catalog_id": _catalog_id(index),
        "merchant_id": _merchant_id(index),
        "captured_at": _CAPTURED_AT,
        "lines": (
            InventoryLineV2(
                sku_id=_sku_id(index),
                quantity_available=5,
                provenance=ProvenanceLabel.VERIFIED,
                evidence_reference_id=_evidence_id(100 + index),
            ),
        ),
        **changes,
    }
    return InventorySnapshotV2(**values)


def _offer(index: int = 1, **changes: object) -> MerchantOfferV2:
    catalog = _catalog(index)
    inventory = _inventory(index)
    values: dict[str, object] = {
        "offer_id": _offer_id(index),
        "market_id": _MARKET_ID,
        "merchant_id": _merchant_id(index),
        "catalog_id": catalog.catalog_id,
        "inventory_snapshot_id": inventory.snapshot_id,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "merchant_catalog_commitment_sha256": "b" * 64,
        "inventory_snapshot_commitment_sha256": "c" * 64,
        "lines": (
            MerchantOfferLineV2(
                sku_id=_sku_id(index),
                max_offer_quantity=3,
                unit_price=Money(amount_paise=100 * index),
                attributes=catalog.skus[0].attributes,
                inventory_provenance=inventory.lines[0].provenance,
                inventory_evidence_reference_id=inventory.lines[0].evidence_reference_id,
            ),
        ),
        **changes,
    }
    return MerchantOfferV2(**values)


def _identity(index: int = 1, **changes: object) -> MerchantSigningIdentityV2:
    values: dict[str, object] = {
        "merchant_id": _merchant_id(index),
        "ed25519_public_key_hex": f"{index:064x}",
        **changes,
    }
    return MerchantSigningIdentityV2(**values)


def _signed(index: int = 1, **changes: object) -> SignedMerchantOfferV2:
    values: dict[str, object] = {
        "offer": _offer(index),
        "signature_hex": f"{index:0128x}",
        **changes,
    }
    return SignedMerchantOfferV2(**values)


def _evidence(index: int = 1, **changes: object) -> MerchantOfferEvidenceV2:
    values: dict[str, object] = {
        "received_at": _RECEIVED_AT,
        "admission_decision": MerchantOfferAdmissionDecisionV2.ADMITTED,
        "signing_identity": _identity(index),
        "catalog": _catalog(index),
        "inventory": _inventory(index),
        "signed_offer": _signed(index),
        **changes,
    }
    return MerchantOfferEvidenceV2(**values)


def _claim_line(
    index: int = 1,
    *,
    quantity: int = 2,
    price: int = 100,
    offer_index: int | None = None,
    merchant_index: int | None = None,
    sku_index: int | None = None,
    **changes: object,
) -> AllocationClaimLineV2:
    offer = index if offer_index is None else offer_index
    merchant = index if merchant_index is None else merchant_index
    sku = index if sku_index is None else sku_index
    values: dict[str, object] = {
        "offer_id": _offer_id(offer),
        "merchant_id": _merchant_id(merchant),
        "sku_id": _sku_id(sku),
        "allocated_quantity": quantity,
        "unit_payment": Money(amount_paise=price),
        "line_payment": Money(amount_paise=quantity * price),
        **changes,
    }
    return AllocationClaimLineV2(**values)


def _claim(**changes: object) -> AllocationClaimV2:
    lines = (
        _claim_line(2, quantity=1, price=200),
        _claim_line(1, quantity=2, price=100),
    )
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": AllocationClaimStatusV2.FEASIBLE,
        "fulfilled_quantity": 3,
        "total_payment": Money(amount_paise=400),
        "soft_preference_unit_score": 2,
        "winner_count": 2,
        "lines": lines,
        **changes,
    }
    return AllocationClaimV2(**values)


def _infeasible_claim(**changes: object) -> AllocationClaimV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": AllocationClaimStatusV2.INFEASIBLE,
        "fulfilled_quantity": 0,
        "total_payment": Money(amount_paise=0),
        "soft_preference_unit_score": 0,
        "winner_count": 0,
        "lines": (),
        **changes,
    }
    return AllocationClaimV2(**values)


def _certificate(**changes: object) -> AllocationCertificateV2:
    values: dict[str, object] = {
        "certificate_id": _CERTIFICATE_ID,
        "buyer_policy": _policy(),
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "merchant_offer_evidence": (_evidence(2), _evidence(1)),
        "allocation": _claim(),
        **changes,
    }
    return AllocationCertificateV2(**values)


class _MoneySubclass(Money):
    pass


class _PolicySubclass(BuyerPolicyV2):
    pass


class _IdentitySubclass(MerchantSigningIdentityV2):
    pass


class _CatalogSubclass(MerchantCatalogV2):
    pass


class _InventorySubclass(InventorySnapshotV2):
    pass


class _SignedOfferSubclass(SignedMerchantOfferV2):
    pass


class _EvidenceSubclass(MerchantOfferEvidenceV2):
    pass


class _ClaimSubclass(AllocationClaimV2):
    pass


def test_versions_and_public_api_are_exact() -> None:
    assert MERCHANT_OFFER_EVIDENCE_V2_VERSION == "merchant-offer-evidence-v2"
    assert ALLOCATION_CERTIFICATE_V2_VERSION == "allocation-certificate-v2"
    assert ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION == (
        "sha256-allocation-certificate-v2-clear-json-v1"
    )
    assert certificate_v2.__all__ == (
        "MERCHANT_OFFER_EVIDENCE_V2_VERSION",
        "ALLOCATION_CERTIFICATE_V2_VERSION",
        "ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION",
        "AllocationClaimStatusV2",
        "MerchantOfferAdmissionDecisionV2",
        "AllocationClaimLineV2",
        "AllocationClaimV2",
        "MerchantOfferEvidenceV2",
        "AllocationCertificateV2",
        "allocation_claim_v2_from_allocation_v2",
        "build_allocation_certificate_v2",
        "canonical_allocation_certificate_v2_bytes",
        "allocation_certificate_v2_digest",
        "MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES",
        "AllocationCertificateV2ParseFailureCode",
        "AllocationCertificateV2ParseError",
        "parse_canonical_allocation_certificate_v2",
    )


def test_allocation_claim_status_values_are_exact() -> None:
    assert tuple(status.value for status in AllocationClaimStatusV2) == (
        "FEASIBLE",
        "INFEASIBLE",
    )


def test_merchant_offer_admission_decision_values_are_exact() -> None:
    assert tuple(decision.value for decision in MerchantOfferAdmissionDecisionV2) == (
        "ADMITTED",
        "REJECTED",
    )


def test_all_models_have_exact_strict_immutable_config() -> None:
    for model in (
        AllocationClaimLineV2,
        AllocationClaimV2,
        MerchantOfferEvidenceV2,
        AllocationCertificateV2,
    ):
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
        assert model.model_config["revalidate_instances"] == "always"


def test_claim_line_has_exact_fields_and_versions() -> None:
    line = _claim_line()
    assert tuple(AllocationClaimLineV2.model_fields) == (
        "schema_version",
        "allocation_line_version",
        "offer_id",
        "merchant_id",
        "sku_id",
        "allocated_quantity",
        "unit_payment",
        "line_payment",
    )
    assert line.schema_version == "2"
    assert line.allocation_line_version == "allocation-line-v2"


@pytest.mark.parametrize("field", ["offer_id", "merchant_id", "sku_id"])
@pytest.mark.parametrize("value", ["not-a-uuid", 1, None])
def test_claim_line_requires_canonical_uuid4(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _claim_line(**{field: value})


@pytest.mark.parametrize("quantity", [0, MAX_QUANTITY + 1, True, 1.0, "1"])
def test_claim_line_requires_strict_positive_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        _claim_line(allocated_quantity=quantity)


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
@pytest.mark.parametrize("value", [{"amount_paise": 100}, 100, None])
def test_claim_line_requires_exact_money(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _claim_line(**{field: value})


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
def test_claim_line_rejects_money_subclasses(field: str) -> None:
    with pytest.raises(ValidationError):
        _claim_line(**{field: _MoneySubclass(amount_paise=100)})


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
def test_claim_line_constructed_money_missing_amount_fails_closed(field: str) -> None:
    malformed = Money.model_construct(currency=Currency.INR)
    with pytest.raises(ValidationError):
        _claim_line(**{field: malformed})


def test_claim_line_constructed_money_wrong_amount_type_fails_closed() -> None:
    malformed = Money.model_construct(amount_paise="100", currency=Currency.INR)
    with pytest.raises(ValidationError):
        _claim_line(unit_payment=malformed)


def test_claim_line_requires_exact_payment_and_rejects_overflow() -> None:
    with pytest.raises(ValidationError):
        _claim_line(line_payment=Money(amount_paise=199))
    with pytest.raises(ValidationError):
        _claim_line(
            quantity=2,
            unit_payment=Money(amount_paise=MAX_MONEY_PAISE),
            line_payment=Money(amount_paise=MAX_MONEY_PAISE),
        )


def test_claim_line_is_frozen_and_forbids_extra() -> None:
    line = _claim_line()
    with pytest.raises(ValidationError):
        line.allocated_quantity = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _claim_line(extra_field=True)


def test_claim_has_exact_fields_versions_and_normalized_lines() -> None:
    claim = _claim()
    assert tuple(AllocationClaimV2.model_fields) == (
        "schema_version",
        "allocation_version",
        "mechanism_version",
        "objective_version",
        "market_id",
        "buyer_policy_commitment_version",
        "buyer_policy_commitment_sha256",
        "status",
        "fulfilled_quantity",
        "total_payment",
        "soft_preference_unit_score",
        "winner_count",
        "lines",
    )
    assert claim.schema_version == "2"
    assert claim.allocation_version == "allocation-v2"
    assert claim.mechanism_version == "heterogeneous-pay-as-bid-v2"
    assert claim.objective_version == "quantity-cost-soft-objective-v2"
    assert claim.buyer_policy_commitment_version == "sha256-buyer-policy-v2-clear-json-v1"
    assert claim.lines == tuple(
        sorted(
            claim.lines,
            key=lambda line: (line.merchant_id, line.sku_id, line.offer_id),
        )
    )
    assert _claim(lines=tuple(reversed(claim.lines))) == claim


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64, 1, None])
def test_claim_requires_strict_lowercase_sha256(digest: object) -> None:
    with pytest.raises(ValidationError):
        _claim(buyer_policy_commitment_sha256=digest)


def test_claim_lines_require_exact_tuple_and_fresh_exact_values() -> None:
    line = _claim_line()
    with pytest.raises(ValidationError):
        _claim(lines=[line])
    with pytest.raises(ValidationError):
        _claim(lines=(object(),))
    malformed = AllocationClaimLineV2.model_construct(offer_id=_offer_id(1))
    with pytest.raises(ValidationError):
        _claim(lines=(malformed,))


def test_claim_rejects_duplicate_line_keys() -> None:
    first = _claim_line(1)
    with pytest.raises(ValidationError):
        _claim(
            lines=(first, first),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
            winner_count=1,
        )
    with pytest.raises(ValidationError):
        _claim(
            lines=(first, _claim_line(2, merchant_index=1, sku_index=1, offer_index=1)),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
            winner_count=1,
        )


def test_claim_enforces_offer_merchant_bijection() -> None:
    with pytest.raises(ValidationError, match="one claim merchant must map to one offer"):
        _claim(
            lines=(
                _claim_line(1, merchant_index=1, offer_index=1),
                _claim_line(2, merchant_index=1, offer_index=2),
            ),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
            winner_count=1,
        )
    with pytest.raises(ValidationError, match="one claim offer must map to one merchant"):
        _claim(
            lines=(
                _claim_line(1, merchant_index=1, offer_index=1),
                _claim_line(2, merchant_index=2, offer_index=1),
            ),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
        )


def test_claim_allows_multiple_skus_for_same_merchant_offer() -> None:
    lines = (
        _claim_line(1, merchant_index=1, offer_index=1),
        _claim_line(2, merchant_index=1, offer_index=1),
    )
    claim = _claim(
        lines=lines,
        fulfilled_quantity=4,
        total_payment=Money(amount_paise=400),
        winner_count=1,
    )
    assert claim.lines == lines


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulfilled_quantity", 2),
        ("total_payment", Money(amount_paise=399)),
        ("winner_count", 1),
    ],
)
def test_claim_requires_exact_aggregates(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _claim(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("soft_preference_unit_score", -1),
        ("soft_preference_unit_score", MAX_QUANTITY * 64 + 1),
        ("soft_preference_unit_score", True),
        ("winner_count", -1),
        ("winner_count", MAX_SELLERS + 1),
        ("winner_count", True),
    ],
)
def test_claim_requires_strict_bounded_scores_and_winners(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _claim(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulfilled_quantity", 0),
        ("winner_count", 0),
        ("lines", ()),
    ],
)
def test_feasible_claim_requires_positive_shape(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _claim(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulfilled_quantity", 1),
        ("total_payment", Money(amount_paise=1)),
        ("soft_preference_unit_score", 1),
        ("winner_count", 1),
        ("lines", (_claim_line(),)),
    ],
)
def test_infeasible_claim_requires_exact_zero_shape(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _infeasible_claim(**{field: value})


def test_claim_is_frozen_and_forbids_extra() -> None:
    claim = _claim()
    with pytest.raises(ValidationError):
        claim.winner_count = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _claim(extra_field=True)


def test_production_allocation_wire_schema_parity() -> None:
    assert tuple(AllocationClaimLineV2.model_fields) == tuple(AllocationLineV2.model_fields)
    assert tuple(AllocationClaimV2.model_fields) == tuple(AllocationV2.model_fields)
    assert tuple(status.value for status in AllocationClaimStatusV2) == tuple(
        status.value for status in AllocationStatusV2
    )

    claim = _claim()
    production_lines = tuple(AllocationLineV2.model_validate(line.__dict__) for line in claim.lines)
    production = AllocationV2(
        market_id=claim.market_id,
        buyer_policy_commitment_sha256=claim.buyer_policy_commitment_sha256,
        status=AllocationStatusV2.FEASIBLE,
        fulfilled_quantity=claim.fulfilled_quantity,
        total_payment=claim.total_payment,
        soft_preference_unit_score=claim.soft_preference_unit_score,
        winner_count=claim.winner_count,
        lines=production_lines,
    )
    assert production.model_dump(mode="json") == claim.model_dump(mode="json")

    infeasible_claim = _infeasible_claim()
    production_infeasible = AllocationV2(
        market_id=infeasible_claim.market_id,
        buyer_policy_commitment_sha256=infeasible_claim.buyer_policy_commitment_sha256,
        status=AllocationStatusV2.INFEASIBLE,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=0,
        lines=(),
    )
    assert production_infeasible.model_dump(mode="json") == infeasible_claim.model_dump(mode="json")


def test_evidence_has_exact_fields_version_and_no_private_economics() -> None:
    evidence = _evidence()
    assert tuple(MerchantOfferEvidenceV2.model_fields) == (
        "schema_version",
        "merchant_offer_evidence_version",
        "received_at",
        "admission_decision",
        "signing_identity",
        "catalog",
        "inventory",
        "signed_offer",
    )
    assert evidence.schema_version == "2"
    assert evidence.merchant_offer_evidence_version == "merchant-offer-evidence-v2"
    assert evidence.received_at == _RECEIVED_AT
    assert evidence.admission_decision is MerchantOfferAdmissionDecisionV2.ADMITTED
    assert "economic_policy" not in MerchantOfferEvidenceV2.model_fields
    assert "candidate" not in MerchantOfferEvidenceV2.model_fields
    assert "reasoning" not in MerchantOfferEvidenceV2.model_fields


def test_evidence_requires_datetime_and_strict_admission_enum() -> None:
    for invalid_timestamp in ("2028-02-03T11:59:59Z", datetime(2028, 2, 3, 11, 59, 59)):
        with pytest.raises(ValidationError):
            _evidence(received_at=invalid_timestamp)
    with pytest.raises(ValidationError):
        _evidence(admission_decision="ADMITTED")

    offset_timestamp = datetime(
        2028,
        2,
        3,
        17,
        29,
        59,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    assert _evidence(received_at=offset_timestamp).received_at == _RECEIVED_AT


@pytest.mark.parametrize(
    ("field", "factory"),
    [
        (
            "signing_identity",
            lambda: _IdentitySubclass.model_validate(_identity().model_dump(mode="python")),
        ),
        ("catalog", lambda: _CatalogSubclass.model_validate(_catalog().model_dump(mode="python"))),
        (
            "inventory",
            lambda: _InventorySubclass.model_validate(_inventory().model_dump(mode="python")),
        ),
        (
            "signed_offer",
            lambda: _SignedOfferSubclass.model_validate(_signed().model_dump(mode="python")),
        ),
    ],
)
def test_evidence_rejects_nested_subclasses(
    field: str,
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: factory()})


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        (
            "signing_identity",
            MerchantSigningIdentityV2.model_construct(merchant_id=_merchant_id(1)),
        ),
        ("catalog", MerchantCatalogV2.model_construct(catalog_id=_catalog_id(1))),
        ("inventory", InventorySnapshotV2.model_construct(snapshot_id=_snapshot_id(1))),
        ("signed_offer", SignedMerchantOfferV2.model_construct(signature_hex="0" * 128)),
    ],
)
def test_evidence_malformed_constructed_nested_values_fail_closed(
    field: str,
    malformed: object,
) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: malformed})


def test_evidence_is_frozen_and_forbids_extra() -> None:
    evidence = _evidence()
    with pytest.raises(ValidationError):
        evidence.catalog = _catalog(2)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _evidence(economic_policy="private")


def test_certificate_has_exact_fields_and_versions() -> None:
    certificate = _certificate()
    assert tuple(AllocationCertificateV2.model_fields) == (
        "schema_version",
        "certificate_version",
        "certificate_id",
        "canonicalization_version",
        "buyer_policy_commitment_version",
        "merchant_offer_signature_version",
        "buyer_policy",
        "buyer_policy_commitment_sha256",
        "merchant_offer_evidence",
        "allocation",
    )
    assert certificate.schema_version == "2"
    assert certificate.certificate_version == "allocation-certificate-v2"
    assert certificate.canonicalization_version == "clear-json-v1"
    assert certificate.buyer_policy_commitment_version == ("sha256-buyer-policy-v2-clear-json-v1")
    assert certificate.merchant_offer_signature_version == (
        "ed25519-raw-merchant-offer-v2-clear-json-v1"
    )


@pytest.mark.parametrize("certificate_id", ["not-a-uuid", 1, None])
def test_certificate_requires_canonical_uuid4(certificate_id: object) -> None:
    with pytest.raises(ValidationError):
        _certificate(certificate_id=certificate_id)


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64, 1, None])
def test_certificate_requires_strict_commitment_digest(digest: object) -> None:
    with pytest.raises(ValidationError):
        _certificate(buyer_policy_commitment_sha256=digest)


def test_certificate_requires_exact_nested_types_and_tuple() -> None:
    policy_subclass = _PolicySubclass.model_validate(_policy().model_dump(mode="python"))
    evidence_subclass = _EvidenceSubclass.model_construct(**_evidence().__dict__)
    claim_subclass = _ClaimSubclass.model_construct(**_claim().__dict__)
    with pytest.raises(ValidationError):
        _certificate(buyer_policy=policy_subclass)
    with pytest.raises(ValidationError):
        _certificate(merchant_offer_evidence=[_evidence()])
    with pytest.raises(ValidationError):
        _certificate(merchant_offer_evidence=(evidence_subclass,))
    with pytest.raises(ValidationError):
        _certificate(allocation=claim_subclass)


def test_certificate_malformed_constructed_nested_values_fail_closed() -> None:
    with pytest.raises(ValidationError):
        _certificate(buyer_policy=BuyerPolicyV2.model_construct(schema_version="2"))
    with pytest.raises(ValidationError):
        _certificate(
            merchant_offer_evidence=(MerchantOfferEvidenceV2.model_construct(schema_version="2"),)
        )
    with pytest.raises(ValidationError):
        _certificate(allocation=AllocationClaimV2.model_construct(schema_version="2"))


def test_certificate_preserves_semantic_transcript_order_and_allows_replays() -> None:
    first = _evidence(1)
    second = _evidence(2)
    certificate = _certificate(merchant_offer_evidence=(second, first))
    assert certificate.merchant_offer_evidence == (second, first)

    another_offer = _evidence(
        1,
        signed_offer=_signed(1, offer=_offer(1, offer_id=_offer_id(3))),
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    same_merchant = _certificate(merchant_offer_evidence=(first, another_offer))
    assert same_merchant.merchant_offer_evidence == (first, another_offer)

    replayed_offer_id = _evidence(
        1,
        received_at=_RECEIVED_AT + timedelta(microseconds=1),
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    replay = _certificate(merchant_offer_evidence=(first, replayed_offer_id))
    assert replay.merchant_offer_evidence == (first, replayed_offer_id)


def test_stored_admission_decisions_and_deadlines_are_not_model_authority() -> None:
    declared_rejected = _evidence(admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED)
    bogus_signature_admitted = _evidence(
        signed_offer=_signed(1, signature_hex="f" * 128),
        admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
    )
    late_admitted = _evidence(
        received_at=_DEADLINE + timedelta(microseconds=1),
        admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
    )
    certificate = _certificate(
        merchant_offer_evidence=(declared_rejected, bogus_signature_admitted, late_admitted)
    )
    assert certificate.merchant_offer_evidence == (
        declared_rejected,
        bogus_signature_admitted,
        late_admitted,
    )
    # Certificate structure does not authorize the stored admission decision; Slice 19B replays it.
    # Replay is in tuple order, and only independently admitted records reach the oracle.


def test_certificate_transcript_is_tuple_ordered_and_not_bounded_by_seller_count() -> None:
    assert _certificate(merchant_offer_evidence=()).merchant_offer_evidence == ()
    with pytest.raises(ValidationError):
        _certificate(merchant_offer_evidence=[_evidence()])

    records = tuple(
        _evidence(
            1,
            received_at=_RECEIVED_AT + timedelta(microseconds=index),
            admission_decision=(
                MerchantOfferAdmissionDecisionV2.ADMITTED
                if index == 0
                else MerchantOfferAdmissionDecisionV2.REJECTED
            ),
        )
        for index in range(MAX_SELLERS + 1)
    )
    certificate = _certificate(merchant_offer_evidence=records)
    assert certificate.merchant_offer_evidence == records
    # Transcript size is bounded at the untrusted canonical-byte parser boundary, not by merchant
    # population.


def test_certificate_is_frozen_and_forbids_extra() -> None:
    certificate = _certificate()
    with pytest.raises(ValidationError):
        certificate.certificate_id = _OTHER_MARKET_ID  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _certificate(digest="not-embedded")


def test_semantically_false_claims_remain_structurally_representable() -> None:
    wrong_commitment = _certificate(buyer_policy_commitment_sha256="f" * 64)
    assert wrong_commitment.buyer_policy_commitment_sha256 != buyer_policy_v2_commitment(
        wrong_commitment.buyer_policy
    )

    wrong_market_claim = _claim(market_id=_OTHER_MARKET_ID)
    wrong_market = _certificate(allocation=wrong_market_claim)
    assert wrong_market.allocation.market_id != wrong_market.buyer_policy.market_spec.market_id

    identity_mismatch = _evidence(1, signing_identity=_identity(2))
    mismatched_identity = _certificate(merchant_offer_evidence=(identity_mismatch,))
    assert (
        mismatched_identity.merchant_offer_evidence[0].signing_identity.merchant_id
        != mismatched_identity.merchant_offer_evidence[0].signed_offer.offer.merchant_id
    )

    bogus_signature = _evidence(1, signed_offer=_signed(1, signature_hex="f" * 128))
    assert (
        _certificate(merchant_offer_evidence=(bogus_signature,))
        .merchant_offer_evidence[0]
        .signed_offer.signature_hex
        == "f" * 128
    )

    inconsistent_source = _evidence(1)
    assert inconsistent_source.signed_offer.offer.merchant_catalog_commitment_sha256 != (
        merchant_catalog_v2_commitment(inconsistent_source.catalog)
    )
    assert _certificate(merchant_offer_evidence=(inconsistent_source,))
    # Certificate structure is not evidence verification. Slice 19B rejects these claims.
