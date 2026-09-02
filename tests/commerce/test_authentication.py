import inspect
from datetime import UTC, datetime

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import ValidationError

import clear_market.commerce as commerce
from clear_market.commerce import (
    MERCHANT_OFFER_V2_SIGNATURE_VERSION,
    MERCHANT_SIGNING_IDENTITY_V2_VERSION,
    SIGNED_MERCHANT_OFFER_V2_VERSION,
    MerchantOfferBuildError,
    MerchantOfferBuildErrorCode,
    MerchantOfferSigningError,
    MerchantOfferSigningErrorCode,
    MerchantOfferVerificationError,
    MerchantOfferVerificationErrorCode,
    MerchantSigningIdentityV2,
    ProvenanceLabel,
    SignedMerchantOfferV2,
    build_and_sign_merchant_offer_v2,
    canonical_merchant_offer_v2_bytes,
    canonical_signed_merchant_offer_v2_bytes,
    inventory_snapshot_v2_commitment,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.domain import Money
from tests.commerce.test_merchant import (
    _MERCHANT_ID,
    _OFFER_ID,
    _OTHER_CATALOG_ID,
    _OTHER_ELIGIBLE_MERCHANT_ID,
    _OUTSIDER_MERCHANT_ID,
    _build,
    _buyer_policy,
    _buyer_policy_subclass,
    _candidate,
    _candidate_line,
    _candidate_subclass,
    _catalog,
    _catalog_subclass,
    _economic_policy,
    _economic_policy_subclass,
    _inventory,
    _inventory_subclass,
    _sku_id,
)

# TEST-ONLY deterministic signing material; never production keys.
_PRIVATE_KEY_BYTES = bytes.fromhex(
    "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
)
_OTHER_PRIVATE_KEY_BYTES = bytes.fromhex(
    "202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f"
)
_PUBLIC_KEY_HEX = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
_OTHER_MARKET_ID = "41000000-0000-4000-8000-000000000002"
_OTHER_SNAPSHOT_ID = "45000000-0000-4000-8000-000000000002"


def _private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_PRIVATE_KEY_BYTES)


def _other_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_OTHER_PRIVATE_KEY_BYTES)


def _identity(**changes: object) -> MerchantSigningIdentityV2:
    values: dict[str, object] = {
        "merchant_id": _MERCHANT_ID,
        "ed25519_public_key_hex": _PUBLIC_KEY_HEX,
        **changes,
    }
    return MerchantSigningIdentityV2(**values)


def _signed(**changes: object) -> SignedMerchantOfferV2:
    values: dict[str, object] = {
        "offer_id": _OFFER_ID,
        "buyer_policy": _buyer_policy(),
        "catalog": _catalog(),
        "inventory": _inventory(),
        "economic_policy": _economic_policy(),
        "candidate": _candidate(),
        "signing_identity": _identity(),
        "private_key": _private_key(),
        **changes,
    }
    return build_and_sign_merchant_offer_v2(**values)  # type: ignore[arg-type]


def _directly_signed(offer: object) -> SignedMerchantOfferV2:
    canonical = canonical_merchant_offer_v2_bytes(offer)  # type: ignore[arg-type]
    return SignedMerchantOfferV2(offer=offer, signature_hex=_private_key().sign(canonical).hex())


def _verification_data(signed: SignedMerchantOfferV2 | None = None) -> bytes:
    return canonical_signed_merchant_offer_v2_bytes(_signed() if signed is None else signed)


def _assert_verification_error(
    expected: MerchantOfferVerificationErrorCode,
    *,
    data: bytes | None = None,
    signing_identity: MerchantSigningIdentityV2 | None = None,
    buyer_policy: object | None = None,
    catalog: object | None = None,
    inventory: object | None = None,
) -> None:
    with pytest.raises(MerchantOfferVerificationError) as caught:
        verify_canonical_signed_merchant_offer_v2(
            data=_verification_data() if data is None else data,
            signing_identity=_identity() if signing_identity is None else signing_identity,
            buyer_policy=_buyer_policy() if buyer_policy is None else buyer_policy,  # type: ignore[arg-type]
            catalog=_catalog() if catalog is None else catalog,  # type: ignore[arg-type]
            inventory=_inventory() if inventory is None else inventory,  # type: ignore[arg-type]
        )
    assert caught.value.code is expected
    assert str(caught.value) == expected.value


def test_authentication_versions_are_exact() -> None:
    assert MERCHANT_SIGNING_IDENTITY_V2_VERSION == "merchant-signing-identity-v2"
    assert SIGNED_MERCHANT_OFFER_V2_VERSION == "signed-merchant-offer-v2"
    assert MERCHANT_OFFER_V2_SIGNATURE_VERSION == ("ed25519-raw-merchant-offer-v2-clear-json-v1")


def test_signing_identity_has_exact_fields_and_test_public_key() -> None:
    identity = _identity()

    assert tuple(MerchantSigningIdentityV2.model_fields) == (
        "schema_version",
        "merchant_signing_identity_version",
        "merchant_id",
        "ed25519_public_key_hex",
    )
    assert identity.schema_version == "2"
    assert identity.merchant_signing_identity_version == "merchant-signing-identity-v2"
    assert identity.ed25519_public_key_hex == _PUBLIC_KEY_HEX
    assert (
        _private_key()
        .public_key()
        .public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        .hex()
        == _PUBLIC_KEY_HEX
    )


@pytest.mark.parametrize(
    "value",
    [
        _PUBLIC_KEY_HEX.upper(),
        f" {_PUBLIC_KEY_HEX}",
        f"{_PUBLIC_KEY_HEX} ",
        f"0x{_PUBLIC_KEY_HEX}",
        _PUBLIC_KEY_HEX[:-1],
        f"{_PUBLIC_KEY_HEX}0",
        "g" * 64,
        1,
        None,
        b"0" * 64,
    ],
)
def test_signing_identity_rejects_noncanonical_public_key_hex(value: object) -> None:
    with pytest.raises(ValidationError):
        _identity(ed25519_public_key_hex=value)


def test_signing_identity_is_frozen_and_forbids_extra_fields() -> None:
    identity = _identity()
    with pytest.raises(ValidationError):
        identity.merchant_id = _OUTSIDER_MERCHANT_ID
    with pytest.raises(ValidationError):
        _identity(provider_account_id="secret")


def test_signed_offer_has_exact_fields_and_excludes_identity_and_private_policy() -> None:
    signed = _signed()

    assert tuple(SignedMerchantOfferV2.model_fields) == (
        "schema_version",
        "signed_merchant_offer_version",
        "signature_version",
        "offer",
        "signature_hex",
    )
    assert signed.schema_version == "2"
    assert signed.signed_merchant_offer_version == "signed-merchant-offer-v2"
    assert signed.signature_version == "ed25519-raw-merchant-offer-v2-clear-json-v1"
    assert "public_key" not in SignedMerchantOfferV2.model_fields
    assert "private_key" not in SignedMerchantOfferV2.model_fields
    assert "economic_policy" not in SignedMerchantOfferV2.model_fields
    assert "candidate" not in SignedMerchantOfferV2.model_fields


@pytest.mark.parametrize(
    "value",
    ["A" * 128, " " + "0" * 128, "0x" + "0" * 128, "0" * 127, "0" * 129, "g" * 128, 1, None],
)
def test_signed_offer_rejects_noncanonical_signature_hex(value: object) -> None:
    with pytest.raises(ValidationError):
        SignedMerchantOfferV2(offer=_build(), signature_hex=value)


def test_signed_offer_is_frozen_and_forbids_extra_fields() -> None:
    signed = _signed()
    with pytest.raises(ValidationError):
        signed.signature_hex = "0" * 128
    with pytest.raises(ValidationError):
        SignedMerchantOfferV2(offer=_build(), signature_hex="0" * 128, public_key="0" * 64)


def test_signing_and_verification_error_code_contracts_are_exact_and_read_only() -> None:
    assert tuple(MerchantOfferSigningErrorCode) == (
        MerchantOfferSigningErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH,
        MerchantOfferSigningErrorCode.PRIVATE_KEY_MISMATCH,
    )
    assert tuple(MerchantOfferVerificationErrorCode) == (
        MerchantOfferVerificationErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH,
        MerchantOfferVerificationErrorCode.INVALID_SIGNATURE,
        MerchantOfferVerificationErrorCode.MERCHANT_NOT_ELIGIBLE,
        MerchantOfferVerificationErrorCode.MARKET_ID_MISMATCH,
        MerchantOfferVerificationErrorCode.CATALOG_MERCHANT_MISMATCH,
        MerchantOfferVerificationErrorCode.CATALOG_ID_MISMATCH,
        MerchantOfferVerificationErrorCode.INVENTORY_MERCHANT_MISMATCH,
        MerchantOfferVerificationErrorCode.INVENTORY_CATALOG_MISMATCH,
        MerchantOfferVerificationErrorCode.INVENTORY_SNAPSHOT_ID_MISMATCH,
        MerchantOfferVerificationErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH,
        MerchantOfferVerificationErrorCode.MERCHANT_CATALOG_COMMITMENT_MISMATCH,
        MerchantOfferVerificationErrorCode.INVENTORY_SNAPSHOT_COMMITMENT_MISMATCH,
        MerchantOfferVerificationErrorCode.OFFER_UNKNOWN_CATALOG_SKU,
        MerchantOfferVerificationErrorCode.OFFER_MISSING_INVENTORY,
        MerchantOfferVerificationErrorCode.OFFER_ATTRIBUTES_MISMATCH,
        MerchantOfferVerificationErrorCode.OFFER_INVENTORY_EVIDENCE_MISMATCH,
        MerchantOfferVerificationErrorCode.OFFER_EXCEEDS_INVENTORY,
    )
    signing_error = MerchantOfferSigningError(MerchantOfferSigningErrorCode.PRIVATE_KEY_MISMATCH)
    verification_error = MerchantOfferVerificationError(
        MerchantOfferVerificationErrorCode.INVALID_SIGNATURE
    )
    assert str(signing_error) == "PRIVATE_KEY_MISMATCH"
    assert str(verification_error) == "INVALID_SIGNATURE"
    with pytest.raises(AttributeError):
        signing_error.code = MerchantOfferSigningErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH
    with pytest.raises(AttributeError):
        verification_error.code = MerchantOfferVerificationErrorCode.MERCHANT_NOT_ELIGIBLE


def test_build_and_sign_matches_builder_and_signs_exact_canonical_offer_bytes() -> None:
    signed = _signed()

    assert signed.offer == _build()
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(_PUBLIC_KEY_HEX)).verify(
        bytes.fromhex(signed.signature_hex),
        canonical_merchant_offer_v2_bytes(signed.offer),
    )


def test_signature_fails_after_offer_content_mutation() -> None:
    signed = _signed()
    mutated = signed.offer.model_copy(update={"market_id": _OTHER_MARKET_ID})

    with pytest.raises(InvalidSignature):
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_PUBLIC_KEY_HEX)).verify(
            bytes.fromhex(signed.signature_hex),
            canonical_merchant_offer_v2_bytes(mutated),
        )


def test_build_and_sign_is_deterministic() -> None:
    assert _signed() == _signed()
    assert canonical_signed_merchant_offer_v2_bytes(_signed()) == _verification_data()


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (
            _candidate(lines=(_candidate_line(1, price=499),)),
            MerchantOfferBuildErrorCode.CANDIDATE_PRICE_BELOW_FLOOR,
        ),
        (
            _candidate(lines=(_candidate_line(1, quantity=11),)),
            MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_INVENTORY,
        ),
    ],
)
def test_unsafe_candidate_fails_in_existing_builder_before_signing(
    candidate: object,
    expected: MerchantOfferBuildErrorCode,
) -> None:
    with pytest.raises(MerchantOfferBuildError) as caught:
        _signed(candidate=candidate)
    assert caught.value.code is expected


def test_signing_identity_merchant_mismatch_fails_after_build() -> None:
    with pytest.raises(MerchantOfferSigningError) as caught:
        _signed(signing_identity=_identity(merchant_id=_OUTSIDER_MERCHANT_ID))
    assert caught.value.code is MerchantOfferSigningErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH


def test_private_key_must_match_trusted_identity_without_key_material_in_error() -> None:
    with pytest.raises(MerchantOfferSigningError) as caught:
        _signed(private_key=_other_private_key())
    assert caught.value.code is MerchantOfferSigningErrorCode.PRIVATE_KEY_MISMATCH
    assert str(caught.value) == "PRIVATE_KEY_MISMATCH"
    assert _PUBLIC_KEY_HEX not in str(caught.value)


def test_wrong_private_key_object_is_type_error() -> None:
    with pytest.raises(TypeError):
        _signed(private_key=object())


class _IdentitySubclass(MerchantSigningIdentityV2):
    pass


def _identity_subclass() -> _IdentitySubclass:
    return _IdentitySubclass(merchant_id=_MERCHANT_ID, ed25519_public_key_hex=_PUBLIC_KEY_HEX)


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("buyer_policy", _buyer_policy_subclass()),
        ("catalog", _catalog_subclass()),
        ("inventory", _inventory_subclass()),
        ("economic_policy", _economic_policy_subclass()),
        ("candidate", _candidate_subclass()),
        ("signing_identity", _identity_subclass()),
        ("buyer_policy", None),
        ("catalog", {}),
    ],
)
def test_build_and_sign_requires_exact_protocol_model_types(
    field: str, wrong_value: object
) -> None:
    with pytest.raises(TypeError):
        _signed(**{field: wrong_value})


def test_public_signing_api_has_no_arbitrary_offer_input_or_export() -> None:
    assert "offer" not in inspect.signature(build_and_sign_merchant_offer_v2).parameters
    assert "sign_merchant_offer_v2" not in commerce.__all__
    assert not hasattr(commerce, "sign_merchant_offer_v2")
    with pytest.raises(TypeError):
        build_and_sign_merchant_offer_v2(offer=_build())  # type: ignore[call-arg]


def test_verifier_accepts_valid_canonical_raw_bytes() -> None:
    data = _verification_data()

    verified = verify_canonical_signed_merchant_offer_v2(
        data=data,
        signing_identity=_identity(),
        buyer_policy=_buyer_policy(),
        catalog=_catalog(),
        inventory=_inventory(),
    )

    assert verified == _signed()


def test_verifier_starts_with_raw_parser() -> None:
    with pytest.raises(TypeError):
        verify_canonical_signed_merchant_offer_v2(
            data=_signed(),  # type: ignore[arg-type]
            signing_identity=_identity(),
            buyer_policy=_buyer_policy(),
            catalog=_catalog(),
            inventory=_inventory(),
        )


def test_verifier_rejects_signing_identity_merchant_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH,
        signing_identity=_identity(merchant_id=_OUTSIDER_MERCHANT_ID),
    )


def test_verifier_rejects_invalid_signature_before_source_details() -> None:
    signed = _signed().model_copy(update={"signature_hex": "0" * 128})
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.INVALID_SIGNATURE,
        data=_verification_data(signed),
        catalog=_catalog(merchant_id=_OUTSIDER_MERCHANT_ID),
    )


def test_verifier_rejects_ineligible_merchant() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.MERCHANT_NOT_ELIGIBLE,
        buyer_policy=_buyer_policy(
            eligible_merchant_ids=(_OTHER_ELIGIBLE_MERCHANT_ID, _OUTSIDER_MERCHANT_ID)
        ),
    )


def test_verifier_rejects_market_id_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.MARKET_ID_MISMATCH,
        buyer_policy=_buyer_policy(
            market_spec=_buyer_policy().market_spec.model_copy(
                update={"market_id": _OTHER_MARKET_ID}
            )
        ),
    )


def test_verifier_rejects_catalog_merchant_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.CATALOG_MERCHANT_MISMATCH,
        catalog=_catalog(merchant_id=_OUTSIDER_MERCHANT_ID),
    )


def test_verifier_rejects_catalog_id_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.CATALOG_ID_MISMATCH,
        catalog=_catalog(catalog_id=_OTHER_CATALOG_ID),
    )


def test_verifier_rejects_inventory_merchant_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.INVENTORY_MERCHANT_MISMATCH,
        inventory=_inventory(merchant_id=_OUTSIDER_MERCHANT_ID),
    )


def test_verifier_rejects_inventory_catalog_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.INVENTORY_CATALOG_MISMATCH,
        inventory=_inventory(catalog_id=_OTHER_CATALOG_ID),
    )


def test_verifier_rejects_inventory_snapshot_id_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.INVENTORY_SNAPSHOT_ID_MISMATCH,
        inventory=_inventory(snapshot_id=_OTHER_SNAPSHOT_ID),
    )


def test_verifier_rejects_buyer_policy_commitment_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH,
        buyer_policy=_buyer_policy(
            max_total_payment=_buyer_policy().max_total_payment.model_copy(
                update={"amount_paise": 10_001}
            )
        ),
    )


def test_verifier_rejects_catalog_commitment_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.MERCHANT_CATALOG_COMMITMENT_MISMATCH,
        catalog=_catalog(generated_at=datetime(2027, 3, 4, 9, 0, 1, tzinfo=UTC)),
    )


def test_verifier_rejects_inventory_commitment_mismatch() -> None:
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.INVENTORY_SNAPSHOT_COMMITMENT_MISMATCH,
        inventory=_inventory(captured_at=datetime(2027, 3, 4, 9, 30, 1, tzinfo=UTC)),
    )


def test_verifier_rejects_offer_unknown_catalog_sku() -> None:
    offer = _build()
    line = offer.lines[0].model_copy(update={"sku_id": _sku_id(99)})
    malicious = _directly_signed(offer.model_copy(update={"lines": (offer.lines[1], line)}))
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.OFFER_UNKNOWN_CATALOG_SKU,
        data=_verification_data(malicious),
    )


def test_verifier_rejects_offer_missing_inventory() -> None:
    inventory = _inventory(lines=(_inventory().lines[1],))
    offer = _build().model_copy(
        update={"inventory_snapshot_commitment_sha256": inventory_snapshot_v2_commitment(inventory)}
    )
    malicious = _directly_signed(offer)
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.OFFER_MISSING_INVENTORY,
        data=_verification_data(malicious),
        inventory=inventory,
    )


def test_valid_signature_does_not_authorize_forged_catalog_attributes() -> None:
    offer = _build()
    line = offer.lines[0].model_copy(update={"attributes": ()})
    malicious = _directly_signed(offer.model_copy(update={"lines": (line, offer.lines[1])}))
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.OFFER_ATTRIBUTES_MISMATCH,
        data=_verification_data(malicious),
    )


def test_verifier_rejects_inventory_evidence_mismatch() -> None:
    offer = _build()
    line = offer.lines[0].model_copy(update={"inventory_provenance": ProvenanceLabel.DERIVED})
    malicious = _directly_signed(offer.model_copy(update={"lines": (line, offer.lines[1])}))
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.OFFER_INVENTORY_EVIDENCE_MISMATCH,
        data=_verification_data(malicious),
    )


def test_verifier_rejects_offer_quantity_above_inventory() -> None:
    offer = _build()
    line = offer.lines[0].model_copy(update={"max_offer_quantity": 11})
    malicious = _directly_signed(offer.model_copy(update={"lines": (line, offer.lines[1])}))
    _assert_verification_error(
        MerchantOfferVerificationErrorCode.OFFER_EXCEEDS_INVENTORY,
        data=_verification_data(malicious),
    )


def test_market_verifier_does_not_claim_private_economic_policy_compliance() -> None:
    offer = _build()
    line = offer.lines[0].model_copy(update={"unit_price": Money(amount_paise=1)})
    malicious = _directly_signed(offer.model_copy(update={"lines": (line, offer.lines[1])}))

    verified = verify_canonical_signed_merchant_offer_v2(
        data=_verification_data(malicious),
        signing_identity=_identity(),
        buyer_policy=_buyer_policy(),
        catalog=_catalog(),
        inventory=_inventory(),
    )

    assert verified == malicious


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("signing_identity", _identity_subclass()),
        ("buyer_policy", _buyer_policy_subclass()),
        ("catalog", _catalog_subclass()),
        ("inventory", _inventory_subclass()),
        ("signing_identity", None),
    ],
)
def test_verifier_requires_exact_trusted_source_types(field: str, wrong_value: object) -> None:
    values: dict[str, object] = {
        "data": _verification_data(),
        "signing_identity": _identity(),
        "buyer_policy": _buyer_policy(),
        "catalog": _catalog(),
        "inventory": _inventory(),
        field: wrong_value,
    }
    with pytest.raises(TypeError):
        verify_canonical_signed_merchant_offer_v2(**values)  # type: ignore[arg-type]
