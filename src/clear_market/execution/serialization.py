"""Canonical execution-authorization request bytes and deterministic fingerprint."""

import hashlib

from clear_market.canonical import CANONICALIZATION_VERSION, canonical_json_bytes
from clear_market.canonical.serialization import canonical_utc_datetime
from clear_market.domain import Money
from clear_market.execution.models import (
    ExecutionAuthorizationRequestV1,
    MerchantRecipientAuthorizationV1,
    _fresh_execution_authorization_request,
)


def _money_projection(value: Money) -> dict[str, object]:
    return {
        "amount_paise": value.amount_paise,
        "currency": value.currency.value,
    }


def _recipient_projection(value: MerchantRecipientAuthorizationV1) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_recipient_authorization_version": (
            value.merchant_recipient_authorization_version
        ),
        "authorization_id": value.authorization_id,
        "merchant_id": value.merchant_id,
        "recipient_id": value.recipient_id,
        "market_id": value.market_id,
        "certificate_digest_version": value.certificate_digest_version,
        "certificate_digest_sha256": value.certificate_digest_sha256,
        "maximum_transfer": _money_projection(value.maximum_transfer),
        "valid_from": canonical_utc_datetime(value.valid_from),
        "valid_until": canonical_utc_datetime(value.valid_until),
    }


def canonical_execution_authorization_request_v1_bytes(
    request: ExecutionAuthorizationRequestV1,
) -> bytes:
    """Bind every material authorization input, excluding decision and reservation time."""
    if type(request) is not ExecutionAuthorizationRequestV1:
        raise TypeError("request must be exactly an ExecutionAuthorizationRequestV1")
    value = _fresh_execution_authorization_request(request)
    market = value.market_execution_authorization
    buyer = value.buyer_financial_authorization
    payload = {
        "schema_version": value.schema_version,
        "execution_authorization_request_version": value.execution_authorization_request_version,
        "execution_id": value.execution_id,
        "certificate_digest_version": value.certificate_digest_version,
        "certificate_digest_sha256": value.certificate_digest_sha256,
        "market_id": value.market_id,
        "market_execution_authorization": {
            "schema_version": market.schema_version,
            "market_execution_authorization_version": (
                market.market_execution_authorization_version
            ),
            "authorization_id": market.authorization_id,
            "market_id": market.market_id,
            "certificate_digest_version": market.certificate_digest_version,
            "certificate_digest_sha256": market.certificate_digest_sha256,
            "state": market.state.value,
            "valid_from": canonical_utc_datetime(market.valid_from),
            "valid_until": canonical_utc_datetime(market.valid_until),
        },
        "buyer_financial_authorization": {
            "schema_version": buyer.schema_version,
            "buyer_financial_authorization_version": (buyer.buyer_financial_authorization_version),
            "authorization_id": buyer.authorization_id,
            "buyer_id": buyer.buyer_id,
            "market_id": buyer.market_id,
            "certificate_digest_version": buyer.certificate_digest_version,
            "certificate_digest_sha256": buyer.certificate_digest_sha256,
            "maximum_total_payment": _money_projection(buyer.maximum_total_payment),
            "valid_from": canonical_utc_datetime(buyer.valid_from),
            "valid_until": canonical_utc_datetime(buyer.valid_until),
        },
        "merchant_recipient_authorizations": [
            _recipient_projection(authorization)
            for authorization in value.merchant_recipient_authorizations
        ],
    }
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "execution_authorization_request_v1",
            "payload": payload,
        }
    )


def execution_request_fingerprint_v1(request: ExecutionAuthorizationRequestV1) -> str:
    """Return lowercase SHA-256 over exact canonical authorization-request bytes."""
    return hashlib.sha256(canonical_execution_authorization_request_v1_bytes(request)).hexdigest()
