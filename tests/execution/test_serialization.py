import hashlib
import json
import re
from datetime import timedelta
from typing import Any, cast

import pytest

from clear_market.domain import Money
from clear_market.execution import (
    ExecutionAuthorizationRequestV1,
    MarketExecutionStateV1,
    canonical_execution_authorization_request_v1_bytes,
    execution_request_fingerprint_v1,
)
from tests.execution.test_models import (
    _DIGEST,
    _EXECUTION_ID,
    _MARKET_ID,
    _buyer_authorization,
    _market_authorization,
    _recipient_authorization,
    _request,
    _uuid,
    _validated_copy,
)

_CANDIDATE_EXECUTION_REQUEST_BYTE_LENGTH = 2_899
_CANDIDATE_EXECUTION_REQUEST_SHA256 = (
    "571a471725f18190f19dff2acc198b93682671e935843f3f5ef4f8ace6dbbe68"
)
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def _nested_float_exists(value: object) -> bool:
    if type(value) is float:
        return True
    if type(value) is dict:
        return any(
            _nested_float_exists(item) for item in cast(dict[object, object], value).values()
        )
    if type(value) is list:
        return any(_nested_float_exists(item) for item in cast(list[object], value))
    return False


def test_exact_envelope_and_complete_explicit_projection() -> None:
    data = canonical_execution_authorization_request_v1_bytes(_request())
    parsed = json.loads(data)
    assert set(parsed) == {"canonicalization_version", "payload", "payload_type"}
    assert parsed["canonicalization_version"] == "clear-json-v1"
    assert parsed["payload_type"] == "execution_authorization_request_v1"
    payload = parsed["payload"]
    assert set(payload) == {
        "buyer_financial_authorization",
        "certificate_digest_sha256",
        "certificate_digest_version",
        "execution_authorization_request_version",
        "execution_id",
        "market_execution_authorization",
        "market_id",
        "merchant_recipient_authorizations",
        "schema_version",
    }
    assert payload["schema_version"] == "1"
    assert payload["execution_authorization_request_version"] == (
        "execution-authorization-request-v1"
    )
    assert payload["execution_id"] == _EXECUTION_ID
    assert payload["market_id"] == _MARKET_ID
    assert payload["certificate_digest_sha256"] == _DIGEST

    market = payload["market_execution_authorization"]
    assert set(market) == {
        "authorization_id",
        "certificate_digest_sha256",
        "certificate_digest_version",
        "market_execution_authorization_version",
        "market_id",
        "schema_version",
        "state",
        "valid_from",
        "valid_until",
    }
    assert market["state"] == "EXECUTABLE"
    assert market["valid_from"] == "2026-09-01T11:00:00.000000Z"
    assert market["valid_until"] == "2026-09-01T13:00:00.000000Z"

    buyer = payload["buyer_financial_authorization"]
    assert set(buyer) == {
        "authorization_id",
        "buyer_financial_authorization_version",
        "buyer_id",
        "certificate_digest_sha256",
        "certificate_digest_version",
        "market_id",
        "maximum_total_payment",
        "schema_version",
        "valid_from",
        "valid_until",
    }
    assert buyer["maximum_total_payment"] == {"amount_paise": 2_700, "currency": "INR"}

    recipients = payload["merchant_recipient_authorizations"]
    assert [value["merchant_id"] for value in recipients] == sorted(
        value["merchant_id"] for value in recipients
    )
    assert set(recipients[0]) == {
        "authorization_id",
        "certificate_digest_sha256",
        "certificate_digest_version",
        "market_id",
        "maximum_transfer",
        "merchant_id",
        "merchant_recipient_authorization_version",
        "recipient_id",
        "schema_version",
        "valid_from",
        "valid_until",
    }
    assert recipients[0]["maximum_transfer"] == {"amount_paise": 1_500, "currency": "INR"}


def test_canonical_bytes_are_compact_utf8_float_free_and_deterministic() -> None:
    data = canonical_execution_authorization_request_v1_bytes(_request())
    assert canonical_execution_authorization_request_v1_bytes(_request()) == data
    assert data.decode("utf-8").encode("utf-8") == data
    assert b"\n" not in data
    assert b": " not in data
    assert b", " not in data
    assert not _nested_float_exists(json.loads(data))


def test_recipient_input_order_is_semantically_irrelevant() -> None:
    first = _recipient_authorization(1)
    second = _recipient_authorization(2)
    forward = _request(merchant_recipient_authorizations=(first, second))
    reverse = _request(merchant_recipient_authorizations=(second, first))
    assert forward == reverse
    assert canonical_execution_authorization_request_v1_bytes(forward) == (
        canonical_execution_authorization_request_v1_bytes(reverse)
    )
    assert execution_request_fingerprint_v1(forward) == execution_request_fingerprint_v1(reverse)


def _with_digest(digest: str) -> ExecutionAuthorizationRequestV1:
    return _request(
        certificate_digest_sha256=digest,
        market_execution_authorization=_market_authorization(certificate_digest_sha256=digest),
        buyer_financial_authorization=_buyer_authorization(certificate_digest_sha256=digest),
        merchant_recipient_authorizations=(
            _recipient_authorization(1, certificate_digest_sha256=digest),
            _recipient_authorization(2, certificate_digest_sha256=digest),
        ),
    )


def _mutation(kind: str) -> ExecutionAuthorizationRequestV1:
    request = _request()
    market = request.market_execution_authorization
    buyer = request.buyer_financial_authorization
    first, second = request.merchant_recipient_authorizations
    if kind == "execution_id":
        return _request(execution_id=_uuid(1, 2))
    if kind == "certificate_digest":
        return _with_digest("f" * 64)
    if kind == "market_auth_id":
        return _request(
            market_execution_authorization=_validated_copy(market, authorization_id=_uuid(2, 2))
        )
    if kind == "market_state":
        return _request(
            market_execution_authorization=_validated_copy(
                market, state=MarketExecutionStateV1.PAUSED
            )
        )
    if kind == "market_window":
        return _request(
            market_execution_authorization=_validated_copy(
                market, valid_from=market.valid_from + timedelta(microseconds=1)
            )
        )
    if kind == "buyer_auth_id":
        return _request(
            buyer_financial_authorization=_validated_copy(buyer, authorization_id=_uuid(3, 2))
        )
    if kind == "buyer_id":
        return _request(buyer_financial_authorization=_validated_copy(buyer, buyer_id=_uuid(8, 2)))
    if kind == "buyer_ceiling":
        return _request(
            buyer_financial_authorization=_validated_copy(
                buyer, maximum_total_payment=Money(amount_paise=2_701)
            )
        )
    if kind == "buyer_window":
        return _request(
            buyer_financial_authorization=_validated_copy(
                buyer, valid_until=buyer.valid_until + timedelta(microseconds=1)
            )
        )
    if kind == "recipient_auth_id":
        first = _validated_copy(first, authorization_id=_uuid(4, 9))
    elif kind == "recipient_id":
        first = _validated_copy(first, recipient_id="clear.recipient.changed")
    elif kind == "recipient_ceiling":
        first = _validated_copy(first, maximum_transfer=Money(amount_paise=1_501))
    elif kind == "recipient_window":
        first = _validated_copy(first, valid_until=first.valid_until + timedelta(microseconds=1))
    else:
        raise AssertionError(kind)
    return _request(merchant_recipient_authorizations=(first, second))


@pytest.mark.parametrize(
    "kind",
    [
        "execution_id",
        "certificate_digest",
        "market_auth_id",
        "market_state",
        "market_window",
        "buyer_auth_id",
        "buyer_id",
        "buyer_ceiling",
        "buyer_window",
        "recipient_auth_id",
        "recipient_id",
        "recipient_ceiling",
        "recipient_window",
    ],
)
def test_every_material_authorization_change_alters_bytes_and_fingerprint(kind: str) -> None:
    base = _request()
    changed = _mutation(kind)
    assert canonical_execution_authorization_request_v1_bytes(changed) != (
        canonical_execution_authorization_request_v1_bytes(base)
    )
    assert execution_request_fingerprint_v1(changed) != execution_request_fingerprint_v1(base)


def test_fingerprint_is_lowercase_sha256_and_has_no_decision_time_input() -> None:
    request = _request()
    digest = execution_request_fingerprint_v1(request)
    assert _LOWER_SHA256.fullmatch(digest) is not None
    assert (
        digest
        == hashlib.sha256(canonical_execution_authorization_request_v1_bytes(request)).hexdigest()
    )
    assert "decision_time" not in type(request).model_fields
    assert b"decision_time" not in canonical_execution_authorization_request_v1_bytes(request)


class _RequestSubclass(ExecutionAuthorizationRequestV1):
    pass


def test_serializer_requires_a_fresh_exact_request() -> None:
    request = _request()
    for invalid in (
        request.model_dump(),
        _RequestSubclass(**request.__dict__),
        ExecutionAuthorizationRequestV1.model_construct(execution_id=request.execution_id),
    ):
        with pytest.raises((TypeError, ValueError)):
            canonical_execution_authorization_request_v1_bytes(cast(Any, invalid))


def test_candidate_execution_request_golden() -> None:
    data = canonical_execution_authorization_request_v1_bytes(_request())
    assert len(data) == _CANDIDATE_EXECUTION_REQUEST_BYTE_LENGTH
    assert hashlib.sha256(data).hexdigest() == _CANDIDATE_EXECUTION_REQUEST_SHA256
    assert execution_request_fingerprint_v1(_request()) == _CANDIDATE_EXECUTION_REQUEST_SHA256
