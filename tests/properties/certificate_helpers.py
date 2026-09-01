import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.certificate import AllocationCertificate, build_allocation_certificate
from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
    MAX_SELLERS,
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)
from clear_market.lifecycle import (
    AdmissionContext,
    AdmissionDecision,
    AdmissionState,
    admit_signed_bid,
)
from tests.properties.market_strategies import PropertyMarketCase

_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)

# TEST-ONLY deterministic signing material for reproducible certificate-property evidence;
# never production keys.
_PRIVATE_KEYS = tuple(
    Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(
            f"clear-certificate-property-suite-v1|merchant|{index}".encode("ascii")
        ).digest()
    )
    for index in range(MAX_SELLERS)
)
_PUBLIC_KEY_HEXES = tuple(
    private_key.public_key()
    .public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    .hex()
    for private_key in _PRIVATE_KEYS
)


@dataclass(frozen=True)
class PropertyCertificateAttempt:
    signed_bid: SignedMerchantBid
    context: AdmissionContext


@dataclass(frozen=True)
class PropertyCertificateFixture:
    policy: BuyerPolicy
    attempts: tuple[PropertyCertificateAttempt, ...]
    decisions: tuple[AdmissionDecision, ...]
    certificate: AllocationCertificate


def _market_id(case_tag: int) -> str:
    return f"71000000-0000-4000-8000-{case_tag:012x}"


def _buyer_id(case_tag: int) -> str:
    return f"72000000-0000-4000-8000-{case_tag:012x}"


def _merchant_id(case_tag: int, seller_index: int) -> str:
    return f"73000000-{seller_index + 1:04x}-4000-8000-{case_tag:012x}"


def _bid_id(case_tag: int, seller_index: int) -> str:
    return f"74000000-{seller_index + 1:04x}-4000-8000-{case_tag:012x}"


def _certificate_id(case_tag: int, certificate_variant: int) -> str:
    if type(certificate_variant) is not int:
        raise TypeError("certificate_variant must be exactly int")
    if certificate_variant not in (1, 2):
        raise ValueError("certificate_variant must be 1 or 2")
    return f"75000000-{certificate_variant:04x}-4000-8000-{case_tag:012x}"


def build_authenticated_transcript(
    case: PropertyMarketCase,
) -> tuple[
    BuyerPolicy,
    tuple[PropertyCertificateAttempt, ...],
    AdmissionState,
    tuple[AdmissionDecision, ...],
]:
    identities = tuple(
        MerchantIdentity(
            merchant_id=_merchant_id(case.case_tag, seller_index),
            ed25519_public_key_hex=_PUBLIC_KEY_HEXES[seller_index],
        )
        for seller_index in range(case.seller_count)
    )
    policy = BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_market_id(case.case_tag),
            buyer_id=_buyer_id(case.case_tag),
            requested_quantity=case.requested_quantity,
        ),
        max_total_payment=Money(
            amount_paise=case.reserve_unit_price_paise * case.requested_quantity
        ),
        reserve_unit_price=Money(amount_paise=case.reserve_unit_price_paise),
        eligible_merchants=identities,
        bid_deadline=_DEADLINE,
    )
    commitment = buyer_policy_commitment(policy)
    attempts = tuple(
        PropertyCertificateAttempt(
            signed_bid=sign_merchant_bid(
                MerchantBid(
                    bid_id=_bid_id(case.case_tag, seller_index),
                    market_id=policy.market_spec.market_id,
                    merchant_id=_merchant_id(case.case_tag, seller_index),
                    buyer_policy_commitment=commitment,
                    quantity_available=case.quantity_available[seller_index],
                    unit_price_paise=case.unit_price_paise[seller_index],
                    submitted_at=_SUBMITTED_AT,
                ),
                _PRIVATE_KEYS[seller_index],
            ),
            context=AdmissionContext(received_at=_RECEIVED_AT),
        )
        for seller_index, participates in enumerate(case.participates)
        if participates
    )

    state = AdmissionState(policy)
    decisions = tuple(
        admit_signed_bid(state, attempt.signed_bid, attempt.context) for attempt in attempts
    )
    assert all(decision.rejection_code is None for decision in decisions)
    return policy, attempts, state, decisions


def build_certificate_from_decisions(
    *,
    case_tag: int,
    certificate_variant: int,
    policy: BuyerPolicy,
    decisions: tuple[AdmissionDecision, ...],
) -> AllocationCertificate:
    return build_allocation_certificate(
        _certificate_id(case_tag, certificate_variant),
        policy,
        decisions,
    )


def build_property_certificate_fixture(
    case: PropertyMarketCase,
    *,
    certificate_variant: int = 1,
) -> PropertyCertificateFixture:
    _certificate_id(case.case_tag, certificate_variant)
    policy, attempts, _state, decisions = build_authenticated_transcript(case)
    certificate = build_certificate_from_decisions(
        case_tag=case.case_tag,
        certificate_variant=certificate_variant,
        policy=policy,
        decisions=decisions,
    )
    return PropertyCertificateFixture(
        policy=policy,
        attempts=attempts,
        decisions=decisions,
        certificate=certificate,
    )
