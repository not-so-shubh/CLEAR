import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Never

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, BeforeValidator, ConfigDict

from clear_market.commerce.catalog import InventorySnapshotV2, MerchantCatalogV2
from clear_market.commerce.market import BuyerPolicyV2
from clear_market.commerce.merchant import (
    MerchantEconomicPolicyV2,
    MerchantOfferCandidateV2,
    MerchantOfferV2,
    build_merchant_offer_v2,
    buyer_policy_v2_commitment,
    inventory_snapshot_v2_commitment,
    merchant_catalog_v2_commitment,
)
from clear_market.commerce.offer_serialization import canonical_merchant_offer_v2_bytes
from clear_market.domain import CanonicalUUID4

MERCHANT_SIGNING_IDENTITY_V2_VERSION: Final[str] = "merchant-signing-identity-v2"
SIGNED_MERCHANT_OFFER_V2_VERSION: Final[str] = "signed-merchant-offer-v2"
MERCHANT_OFFER_V2_SIGNATURE_VERSION: Final[str] = "ed25519-raw-merchant-offer-v2-clear-json-v1"

_PUBLIC_KEY_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_SIGNATURE_HEX_PATTERN = re.compile(r"[0-9a-f]{128}", flags=re.ASCII)


def _validate_public_key_hex(value: object) -> str:
    if type(value) is not str or _PUBLIC_KEY_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("public key must be 64 lowercase hexadecimal characters")
    return value


def _validate_signature_hex(value: object) -> str:
    if type(value) is not str or _SIGNATURE_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("signature must be 128 lowercase hexadecimal characters")
    return value


type _Ed25519PublicKeyHex = Annotated[str, BeforeValidator(_validate_public_key_hex)]
type _Ed25519SignatureHex = Annotated[str, BeforeValidator(_validate_signature_hex)]


class MerchantSigningIdentityV2(BaseModel):
    """Trusted external binding between a merchant ID and one Ed25519 public key."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_signing_identity_version: Literal["merchant-signing-identity-v2"] = (
        "merchant-signing-identity-v2"
    )
    merchant_id: CanonicalUUID4
    ed25519_public_key_hex: _Ed25519PublicKeyHex


class SignedMerchantOfferV2(BaseModel):
    """Merchant authorization of exact canonical offer bytes, without private policy data."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    signed_merchant_offer_version: Literal["signed-merchant-offer-v2"] = "signed-merchant-offer-v2"
    signature_version: Literal["ed25519-raw-merchant-offer-v2-clear-json-v1"] = (
        "ed25519-raw-merchant-offer-v2-clear-json-v1"
    )
    offer: MerchantOfferV2
    signature_hex: _Ed25519SignatureHex


class MerchantOfferSigningErrorCode(StrEnum):
    SIGNING_IDENTITY_MERCHANT_MISMATCH = "SIGNING_IDENTITY_MERCHANT_MISMATCH"
    PRIVATE_KEY_MISMATCH = "PRIVATE_KEY_MISMATCH"


class MerchantOfferSigningError(ValueError):
    """Stable build-and-sign failure without exposing signing material."""

    __slots__ = ("_code",)

    def __init__(self, code: MerchantOfferSigningErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> MerchantOfferSigningErrorCode:
        return self._code


class MerchantOfferVerificationErrorCode(StrEnum):
    SIGNING_IDENTITY_MERCHANT_MISMATCH = "SIGNING_IDENTITY_MERCHANT_MISMATCH"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    MERCHANT_NOT_ELIGIBLE = "MERCHANT_NOT_ELIGIBLE"
    MARKET_ID_MISMATCH = "MARKET_ID_MISMATCH"
    CATALOG_MERCHANT_MISMATCH = "CATALOG_MERCHANT_MISMATCH"
    CATALOG_ID_MISMATCH = "CATALOG_ID_MISMATCH"
    INVENTORY_MERCHANT_MISMATCH = "INVENTORY_MERCHANT_MISMATCH"
    INVENTORY_CATALOG_MISMATCH = "INVENTORY_CATALOG_MISMATCH"
    INVENTORY_SNAPSHOT_ID_MISMATCH = "INVENTORY_SNAPSHOT_ID_MISMATCH"
    BUYER_POLICY_COMMITMENT_MISMATCH = "BUYER_POLICY_COMMITMENT_MISMATCH"
    MERCHANT_CATALOG_COMMITMENT_MISMATCH = "MERCHANT_CATALOG_COMMITMENT_MISMATCH"
    INVENTORY_SNAPSHOT_COMMITMENT_MISMATCH = "INVENTORY_SNAPSHOT_COMMITMENT_MISMATCH"
    OFFER_UNKNOWN_CATALOG_SKU = "OFFER_UNKNOWN_CATALOG_SKU"
    OFFER_MISSING_INVENTORY = "OFFER_MISSING_INVENTORY"
    OFFER_ATTRIBUTES_MISMATCH = "OFFER_ATTRIBUTES_MISMATCH"
    OFFER_INVENTORY_EVIDENCE_MISMATCH = "OFFER_INVENTORY_EVIDENCE_MISMATCH"
    OFFER_EXCEEDS_INVENTORY = "OFFER_EXCEEDS_INVENTORY"


class MerchantOfferVerificationError(ValueError):
    """Stable authenticated-offer verification failure."""

    __slots__ = ("_code",)

    def __init__(self, code: MerchantOfferVerificationErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> MerchantOfferVerificationErrorCode:
        return self._code


def _raw_public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _raise_signing_error(code: MerchantOfferSigningErrorCode) -> Never:
    raise MerchantOfferSigningError(code)


def _raise_verification_error(code: MerchantOfferVerificationErrorCode) -> Never:
    raise MerchantOfferVerificationError(code)


def build_and_sign_merchant_offer_v2(
    *,
    offer_id: CanonicalUUID4,
    buyer_policy: BuyerPolicyV2,
    catalog: MerchantCatalogV2,
    inventory: InventorySnapshotV2,
    economic_policy: MerchantEconomicPolicyV2,
    candidate: MerchantOfferCandidateV2,
    signing_identity: MerchantSigningIdentityV2,
    private_key: Ed25519PrivateKey,
) -> SignedMerchantOfferV2:
    """Build through merchant safety policy, then authorize the exact canonical offer bytes."""
    if type(buyer_policy) is not BuyerPolicyV2:
        raise TypeError("buyer_policy must be exactly a BuyerPolicyV2")
    if type(catalog) is not MerchantCatalogV2:
        raise TypeError("catalog must be exactly a MerchantCatalogV2")
    if type(inventory) is not InventorySnapshotV2:
        raise TypeError("inventory must be exactly an InventorySnapshotV2")
    if type(economic_policy) is not MerchantEconomicPolicyV2:
        raise TypeError("economic_policy must be exactly a MerchantEconomicPolicyV2")
    if type(candidate) is not MerchantOfferCandidateV2:
        raise TypeError("candidate must be exactly a MerchantOfferCandidateV2")
    if type(signing_identity) is not MerchantSigningIdentityV2:
        raise TypeError("signing_identity must be exactly a MerchantSigningIdentityV2")
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private_key must be an Ed25519PrivateKey")

    offer = build_merchant_offer_v2(
        offer_id=offer_id,
        buyer_policy=buyer_policy,
        catalog=catalog,
        inventory=inventory,
        economic_policy=economic_policy,
        candidate=candidate,
    )
    if signing_identity.merchant_id != offer.merchant_id:
        _raise_signing_error(MerchantOfferSigningErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH)
    if _raw_public_key_bytes(private_key).hex() != signing_identity.ed25519_public_key_hex:
        _raise_signing_error(MerchantOfferSigningErrorCode.PRIVATE_KEY_MISMATCH)

    signature = private_key.sign(canonical_merchant_offer_v2_bytes(offer))
    return SignedMerchantOfferV2(offer=offer, signature_hex=signature.hex())


def verify_canonical_signed_merchant_offer_v2(
    *,
    data: bytes,
    signing_identity: MerchantSigningIdentityV2,
    buyer_policy: BuyerPolicyV2,
    catalog: MerchantCatalogV2,
    inventory: InventorySnapshotV2,
) -> SignedMerchantOfferV2:
    """Authenticate raw canonical bytes and validate public source-state consistency.

    This does not independently establish compliance with merchant-private cost or margin policy.
    """
    from clear_market.commerce.auth_parsing import parse_canonical_signed_merchant_offer_v2

    signed_offer = parse_canonical_signed_merchant_offer_v2(data)

    if type(signing_identity) is not MerchantSigningIdentityV2:
        raise TypeError("signing_identity must be exactly a MerchantSigningIdentityV2")
    if type(buyer_policy) is not BuyerPolicyV2:
        raise TypeError("buyer_policy must be exactly a BuyerPolicyV2")
    if type(catalog) is not MerchantCatalogV2:
        raise TypeError("catalog must be exactly a MerchantCatalogV2")
    if type(inventory) is not InventorySnapshotV2:
        raise TypeError("inventory must be exactly an InventorySnapshotV2")

    offer = signed_offer.offer
    if signing_identity.merchant_id != offer.merchant_id:
        _raise_verification_error(
            MerchantOfferVerificationErrorCode.SIGNING_IDENTITY_MERCHANT_MISMATCH
        )

    public_key = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(signing_identity.ed25519_public_key_hex)
    )
    try:
        public_key.verify(
            bytes.fromhex(signed_offer.signature_hex),
            canonical_merchant_offer_v2_bytes(offer),
        )
    except InvalidSignature:
        _raise_verification_error(MerchantOfferVerificationErrorCode.INVALID_SIGNATURE)

    if offer.merchant_id not in buyer_policy.eligible_merchant_ids:
        _raise_verification_error(MerchantOfferVerificationErrorCode.MERCHANT_NOT_ELIGIBLE)
    if offer.market_id != buyer_policy.market_spec.market_id:
        _raise_verification_error(MerchantOfferVerificationErrorCode.MARKET_ID_MISMATCH)
    if catalog.merchant_id != offer.merchant_id:
        _raise_verification_error(MerchantOfferVerificationErrorCode.CATALOG_MERCHANT_MISMATCH)
    if catalog.catalog_id != offer.catalog_id:
        _raise_verification_error(MerchantOfferVerificationErrorCode.CATALOG_ID_MISMATCH)
    if inventory.merchant_id != offer.merchant_id:
        _raise_verification_error(MerchantOfferVerificationErrorCode.INVENTORY_MERCHANT_MISMATCH)
    if inventory.catalog_id != offer.catalog_id:
        _raise_verification_error(MerchantOfferVerificationErrorCode.INVENTORY_CATALOG_MISMATCH)
    if inventory.snapshot_id != offer.inventory_snapshot_id:
        _raise_verification_error(MerchantOfferVerificationErrorCode.INVENTORY_SNAPSHOT_ID_MISMATCH)
    if offer.buyer_policy_commitment_sha256 != buyer_policy_v2_commitment(buyer_policy):
        _raise_verification_error(
            MerchantOfferVerificationErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH
        )
    if offer.merchant_catalog_commitment_sha256 != merchant_catalog_v2_commitment(catalog):
        _raise_verification_error(
            MerchantOfferVerificationErrorCode.MERCHANT_CATALOG_COMMITMENT_MISMATCH
        )
    if offer.inventory_snapshot_commitment_sha256 != inventory_snapshot_v2_commitment(inventory):
        _raise_verification_error(
            MerchantOfferVerificationErrorCode.INVENTORY_SNAPSHOT_COMMITMENT_MISMATCH
        )

    catalog_skus = {sku.sku_id: sku for sku in catalog.skus}
    inventory_lines = {line.sku_id: line for line in inventory.lines}
    for offer_line in offer.lines:
        catalog_sku = catalog_skus.get(offer_line.sku_id)
        if catalog_sku is None:
            _raise_verification_error(MerchantOfferVerificationErrorCode.OFFER_UNKNOWN_CATALOG_SKU)
        inventory_line = inventory_lines.get(offer_line.sku_id)
        if inventory_line is None:
            _raise_verification_error(MerchantOfferVerificationErrorCode.OFFER_MISSING_INVENTORY)
        if offer_line.attributes != catalog_sku.attributes:
            _raise_verification_error(MerchantOfferVerificationErrorCode.OFFER_ATTRIBUTES_MISMATCH)
        if (
            offer_line.inventory_provenance is not inventory_line.provenance
            or offer_line.inventory_evidence_reference_id != inventory_line.evidence_reference_id
        ):
            _raise_verification_error(
                MerchantOfferVerificationErrorCode.OFFER_INVENTORY_EVIDENCE_MISMATCH
            )
        if offer_line.max_offer_quantity > inventory_line.quantity_available:
            _raise_verification_error(MerchantOfferVerificationErrorCode.OFFER_EXCEEDS_INVENTORY)

    return signed_offer
