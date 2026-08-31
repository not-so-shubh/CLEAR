import hashlib
from typing import Final

from clear_market.canonical import canonical_buyer_policy_bytes
from clear_market.domain import BuyerPolicy

BUYER_POLICY_COMMITMENT_VERSION: Final[str] = "sha256-clear-json-v1"


def buyer_policy_commitment(policy: BuyerPolicy) -> str:
    """Bind a BuyerPolicy to the SHA-256 digest of its canonical bytes."""
    return hashlib.sha256(canonical_buyer_policy_bytes(policy)).hexdigest()
