from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    canonical_utc_datetime,
)
from clear_market.certificate.models import AllocationCertificate
from clear_market.domain import BuyerPolicy, Money, SignedMerchantBid
from clear_market.lifecycle import AdmissionDecision
from clear_market.mechanism import Allocation


def _money_payload(money: Money | None) -> dict[str, object] | None:
    if money is None:
        return None
    return {
        "amount_paise": money.amount_paise,
        "currency": money.currency.value,
    }


def _buyer_policy_payload(policy: BuyerPolicy) -> dict[str, object]:
    return {
        "schema_version": policy.schema_version,
        "market_spec": {
            "schema_version": policy.market_spec.schema_version,
            "market_id": policy.market_spec.market_id,
            "buyer_id": policy.market_spec.buyer_id,
            "requested_quantity": policy.market_spec.requested_quantity,
        },
        "max_total_payment": {
            "amount_paise": policy.max_total_payment.amount_paise,
            "currency": policy.max_total_payment.currency.value,
        },
        "reserve_unit_price": {
            "amount_paise": policy.reserve_unit_price.amount_paise,
            "currency": policy.reserve_unit_price.currency.value,
        },
        "eligible_merchants": [
            {
                "schema_version": merchant.schema_version,
                "merchant_id": merchant.merchant_id,
                "ed25519_public_key_hex": merchant.ed25519_public_key_hex,
            }
            for merchant in policy.eligible_merchants
        ],
        "bid_deadline": canonical_utc_datetime(policy.bid_deadline),
        "mechanism_version": policy.mechanism_version,
        "tie_break_rule": policy.tie_break_rule,
    }


def _signed_bid_payload(signed_bid: SignedMerchantBid) -> dict[str, object]:
    bid = signed_bid.bid
    return {
        "bid": {
            "schema_version": bid.schema_version,
            "bid_id": bid.bid_id,
            "market_id": bid.market_id,
            "merchant_id": bid.merchant_id,
            "buyer_policy_commitment_version": bid.buyer_policy_commitment_version,
            "buyer_policy_commitment": bid.buyer_policy_commitment,
            "quantity_available": bid.quantity_available,
            "unit_price_paise": bid.unit_price_paise,
            "currency": bid.currency.value,
            "submitted_at": canonical_utc_datetime(bid.submitted_at),
        },
        "signature_hex": signed_bid.signature_hex,
    }


def _admission_decision_payload(decision: AdmissionDecision) -> dict[str, object]:
    return {
        "signed_bid": _signed_bid_payload(decision.signed_bid),
        "context": {
            "received_at": canonical_utc_datetime(decision.context.received_at),
        },
        "rejection_code": (
            decision.rejection_code.value if decision.rejection_code is not None else None
        ),
    }


def _allocation_payload(allocation: Allocation) -> dict[str, object]:
    return {
        "schema_version": allocation.schema_version,
        "market_id": allocation.market_id,
        "buyer_policy_commitment_version": allocation.buyer_policy_commitment_version,
        "buyer_policy_commitment": allocation.buyer_policy_commitment,
        "mechanism_version": allocation.mechanism_version,
        "status": allocation.status.value,
        "winner_merchant_id": allocation.winner_merchant_id,
        "winning_bid_id": allocation.winning_bid_id,
        "allocated_quantity": allocation.allocated_quantity,
        "winning_unit_price": _money_payload(allocation.winning_unit_price),
        "payment_unit_price": _money_payload(allocation.payment_unit_price),
        "total_payment": _money_payload(allocation.total_payment),
    }


def canonical_allocation_certificate_bytes(certificate: AllocationCertificate) -> bytes:
    """Project every certificate evidence field into the frozen canonical byte envelope."""
    if not isinstance(certificate, AllocationCertificate):
        raise TypeError("certificate must be an AllocationCertificate")

    payload = {
        "schema_version": certificate.schema_version,
        "certificate_version": certificate.certificate_version,
        "certificate_id": certificate.certificate_id,
        "canonicalization_version": certificate.canonicalization_version,
        "buyer_policy_commitment_version": certificate.buyer_policy_commitment_version,
        "merchant_bid_signature_version": certificate.merchant_bid_signature_version,
        "buyer_policy": _buyer_policy_payload(certificate.buyer_policy),
        "buyer_policy_commitment": certificate.buyer_policy_commitment,
        "admission_decisions": [
            _admission_decision_payload(decision) for decision in certificate.admission_decisions
        ],
        "allocation": _allocation_payload(certificate.allocation),
    }
    envelope = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload_type": "allocation_certificate",
        "payload": payload,
    }
    return canonical_json_bytes(envelope)
