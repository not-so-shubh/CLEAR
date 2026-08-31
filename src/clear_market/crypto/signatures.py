from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from clear_market.canonical import canonical_merchant_bid_bytes
from clear_market.domain import MerchantBid, MerchantIdentity, SignedMerchantBid

MERCHANT_BID_SIGNATURE_VERSION: Final[str] = "ed25519-raw-clear-json-v1"


def sign_merchant_bid(
    bid: MerchantBid,
    private_key: Ed25519PrivateKey,
) -> SignedMerchantBid:
    """Sign the exact canonical MerchantBid bytes with an Ed25519 private key."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private_key must be an Ed25519PrivateKey")

    signature = private_key.sign(canonical_merchant_bid_bytes(bid))
    return SignedMerchantBid(bid=bid, signature_hex=signature.hex())


def verify_merchant_bid_signature(
    signed_bid: SignedMerchantBid,
    merchant_identity: MerchantIdentity,
) -> bool:
    """Verify merchant identity agreement and the signature over exact canonical bid bytes."""
    if signed_bid.bid.merchant_id != merchant_identity.merchant_id:
        return False

    public_key = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(merchant_identity.ed25519_public_key_hex)
    )
    try:
        public_key.verify(
            bytes.fromhex(signed_bid.signature_hex),
            canonical_merchant_bid_bytes(signed_bid.bid),
        )
    except InvalidSignature:
        return False
    return True
