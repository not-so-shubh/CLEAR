import json
from datetime import datetime
from typing import cast

import pytest

from clear_market.certificate import (
    MAX_CANONICAL_CERTIFICATE_BYTES,
    AllocationCertificate,
    AllocationCertificateParseError,
    AllocationCertificateParseFailureCode,
    canonical_allocation_certificate_bytes,
    parse_canonical_allocation_certificate,
)
from clear_market.mechanism import Allocation, AllocationStatus
from clear_market.verification import (
    CertificateVerificationFailureCode,
    verify_allocation_certificate,
)

from .test_serialization import (
    _accepted_order_certificate,
    _empty_certificate,
    _golden_certificate,
)


class _BytesSubclass(bytes):
    pass


def _json_bytes(
    value: object,
    *,
    sort_keys: bool = True,
    separators: tuple[str, str] = (",", ":"),
) -> bytes:
    return json.dumps(
        value,
        sort_keys=sort_keys,
        separators=separators,
        ensure_ascii=False,
    ).encode("utf-8")


def _golden_data() -> bytes:
    return canonical_allocation_certificate_bytes(_golden_certificate())


def _golden_envelope() -> dict[str, object]:
    parsed = json.loads(_golden_data())
    assert type(parsed) is dict
    return cast(dict[str, object], parsed)


def _payload(envelope: dict[str, object]) -> dict[str, object]:
    payload = envelope["payload"]
    assert type(payload) is dict
    return cast(dict[str, object], payload)


def _buyer_policy(payload: dict[str, object]) -> dict[str, object]:
    policy = payload["buyer_policy"]
    assert type(policy) is dict
    return cast(dict[str, object], policy)


def _first_decision(payload: dict[str, object]) -> dict[str, object]:
    decisions = payload["admission_decisions"]
    assert type(decisions) is list
    first = cast(list[object], decisions)[0]
    assert type(first) is dict
    return cast(dict[str, object], first)


def _first_bid(payload: dict[str, object]) -> dict[str, object]:
    signed_bid = _first_decision(payload)["signed_bid"]
    assert type(signed_bid) is dict
    bid = cast(dict[str, object], signed_bid)["bid"]
    assert type(bid) is dict
    return cast(dict[str, object], bid)


def _first_context(payload: dict[str, object]) -> dict[str, object]:
    context = _first_decision(payload)["context"]
    assert type(context) is dict
    return cast(dict[str, object], context)


def _assert_parse_failure(
    data: bytes,
    expected: AllocationCertificateParseFailureCode,
) -> None:
    with pytest.raises(AllocationCertificateParseError) as caught:
        parse_canonical_allocation_certificate(data)

    assert caught.value.code is expected


def _replace_timestamp(location: str, value: object) -> bytes:
    envelope = _golden_envelope()
    payload = _payload(envelope)
    if location == "bid_deadline":
        _buyer_policy(payload)["bid_deadline"] = value
    elif location == "submitted_at":
        _first_bid(payload)["submitted_at"] = value
    elif location == "received_at":
        _first_context(payload)["received_at"] = value
    else:
        raise AssertionError("unknown test timestamp location")
    return _json_bytes(envelope)


def test_parse_failure_enum_is_exact() -> None:
    assert tuple(AllocationCertificateParseFailureCode) == (
        AllocationCertificateParseFailureCode.INPUT_TOO_LARGE,
        AllocationCertificateParseFailureCode.INVALID_UTF8,
        AllocationCertificateParseFailureCode.INVALID_JSON,
        AllocationCertificateParseFailureCode.DUPLICATE_KEY,
        AllocationCertificateParseFailureCode.INVALID_ENVELOPE,
        AllocationCertificateParseFailureCode.INVALID_CERTIFICATE,
        AllocationCertificateParseFailureCode.NON_CANONICAL,
    )
    assert tuple(member.value for member in AllocationCertificateParseFailureCode) == (
        "input_too_large",
        "invalid_utf8",
        "invalid_json",
        "duplicate_key",
        "invalid_envelope",
        "invalid_certificate",
        "non_canonical",
    )


def test_maximum_input_size_is_exact() -> None:
    assert MAX_CANONICAL_CERTIFICATE_BYTES == 1_048_576


def test_parse_error_exposes_read_only_stable_code() -> None:
    error = AllocationCertificateParseError(AllocationCertificateParseFailureCode.INVALID_JSON)

    assert error.code is AllocationCertificateParseFailureCode.INVALID_JSON
    assert str(error) == "invalid_json"
    with pytest.raises(AttributeError):
        error.code = AllocationCertificateParseFailureCode.NON_CANONICAL


def test_golden_certificate_and_wire_timestamps_roundtrip_exactly() -> None:
    original = _golden_certificate()
    data = canonical_allocation_certificate_bytes(original)

    parsed = parse_canonical_allocation_certificate(data)

    assert len(data) == 3311
    assert parsed == original
    assert isinstance(parsed.buyer_policy.bid_deadline, datetime)
    for decision in parsed.admission_decisions:
        assert isinstance(decision.signed_bid.bid.submitted_at, datetime)
        assert isinstance(decision.context.received_at, datetime)
    assert canonical_allocation_certificate_bytes(parsed) == data


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        "json",
        bytearray(b"{}"),
        memoryview(b"{}"),
        _BytesSubclass(b"{}"),
    ],
)
def test_parser_rejects_every_non_exact_bytes_input(value: object) -> None:
    with pytest.raises(TypeError):
        parse_canonical_allocation_certificate(value)


def test_oversized_input_fails_before_json_handling() -> None:
    _assert_parse_failure(
        b"x" * (MAX_CANONICAL_CERTIFICATE_BYTES + 1),
        AllocationCertificateParseFailureCode.INPUT_TOO_LARGE,
    )


def test_exact_size_limit_proceeds_to_later_validation() -> None:
    _assert_parse_failure(
        b"x" * MAX_CANONICAL_CERTIFICATE_BYTES,
        AllocationCertificateParseFailureCode.INVALID_JSON,
    )


def test_malformed_utf8_is_rejected() -> None:
    _assert_parse_failure(
        b"\xff",
        AllocationCertificateParseFailureCode.INVALID_UTF8,
    )


def test_utf8_bom_is_rejected_with_stable_category() -> None:
    _assert_parse_failure(
        b"\xef\xbb\xbf" + _golden_data(),
        AllocationCertificateParseFailureCode.INVALID_UTF8,
    )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{",
        b'{"x":}',
        b"NaN",
        b"Infinity",
        b"-Infinity",
    ],
)
def test_invalid_json_and_nonstandard_constants_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize(
    "data",
    [
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{},'
            b'"payload_type":"allocation_certificate",'
            b'"payload_type":"allocation_certificate"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{'
            b'"certificate_id":"50000000-0000-4000-8000-000000000001",'
            b'"certificate_id":"50000000-0000-4000-8000-000000000002"},'
            b'"payload_type":"allocation_certificate"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{'
            b'"admission_decisions":[{"signed_bid":{"bid":{'
            b'"unit_price_paise":1,"unit_price_paise":2}}}]},'
            b'"payload_type":"allocation_certificate"}'
        ),
    ],
)
def test_duplicate_keys_at_every_nesting_depth_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateParseFailureCode.DUPLICATE_KEY)


@pytest.mark.parametrize("root", [[], None, "hello", 1, True])
def test_valid_json_with_wrong_root_type_is_invalid_envelope(root: object) -> None:
    _assert_parse_failure(
        _json_bytes(root),
        AllocationCertificateParseFailureCode.INVALID_ENVELOPE,
    )


@pytest.mark.parametrize(
    "envelope",
    [
        {"canonicalization_version": "clear-json-v1", "payload": {}},
        {
            "canonicalization_version": "clear-json-v1",
            "payload_type": "allocation_certificate",
            "payload": {},
            "extra": True,
        },
        {
            "canonicalization_version": "clear-json-v2",
            "payload_type": "allocation_certificate",
            "payload": {},
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload_type": "buyer_policy",
            "payload": {},
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload_type": "allocation_certificate",
            "payload": [],
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload_type": "allocation_certificate",
            "payload": None,
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload_type": "allocation_certificate",
            "payload": "certificate",
        },
    ],
)
def test_exact_envelope_contract_is_enforced(envelope: dict[str, object]) -> None:
    _assert_parse_failure(
        _json_bytes(envelope),
        AllocationCertificateParseFailureCode.INVALID_ENVELOPE,
    )


@pytest.mark.parametrize(
    "case",
    [
        "missing_certificate_id",
        "invalid_certificate_id",
        "wrong_certificate_version",
        "malformed_buyer_policy",
        "malformed_signature",
        "malformed_allocation",
    ],
)
def test_malformed_payload_maps_to_invalid_certificate(case: str) -> None:
    envelope = _golden_envelope()
    payload = _payload(envelope)

    if case == "missing_certificate_id":
        del payload["certificate_id"]
    elif case == "invalid_certificate_id":
        payload["certificate_id"] = "not-a-uuid"
    elif case == "wrong_certificate_version":
        payload["certificate_version"] = "allocation-certificate-v2"
    elif case == "malformed_buyer_policy":
        payload["buyer_policy"] = {}
    elif case == "malformed_signature":
        signed_bid = _first_decision(payload)["signed_bid"]
        assert type(signed_bid) is dict
        cast(dict[str, object], signed_bid)["signature_hex"] = "invalid"
    elif case == "malformed_allocation":
        payload["allocation"] = {}
    else:
        raise AssertionError("unknown malformed certificate case")

    _assert_parse_failure(
        _json_bytes(envelope),
        AllocationCertificateParseFailureCode.INVALID_CERTIFICATE,
    )


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("bid_deadline", "not-a-date"),
        ("bid_deadline", "2026-09-01T12:00:00.000000"),
        ("submitted_at", "2026-09-01T11:59:58.000000z"),
        ("received_at", "2026-09-01T11:59:59.0000000Z"),
        ("bid_deadline", "2026-13-01T12:00:00.000000Z"),
    ],
)
def test_malformed_wire_timestamps_are_invalid_certificate(
    location: str,
    value: str,
) -> None:
    _assert_parse_failure(
        _replace_timestamp(location, value),
        AllocationCertificateParseFailureCode.INVALID_CERTIFICATE,
    )


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("bid_deadline", None),
        ("submitted_at", 1),
        ("received_at", True),
    ],
)
def test_non_string_wire_timestamps_are_left_for_model_validation(
    location: str,
    value: object,
) -> None:
    _assert_parse_failure(
        _replace_timestamp(location, value),
        AllocationCertificateParseFailureCode.INVALID_CERTIFICATE,
    )


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("bid_deadline", "2026-09-01T12:00:00Z"),
        ("bid_deadline", "2026-09-01T12:00:00.000000+00:00"),
        ("submitted_at", "2026-09-01T11:59:58Z"),
    ],
)
def test_valid_but_noncanonical_wire_timestamps_are_rejected(
    location: str,
    value: str,
) -> None:
    _assert_parse_failure(
        _replace_timestamp(location, value),
        AllocationCertificateParseFailureCode.NON_CANONICAL,
    )


def test_semantically_equivalent_noncanonical_json_forms_are_rejected() -> None:
    data = _golden_data()
    envelope = _golden_envelope()
    payload = _payload(envelope)

    reordered_top_level = {
        "payload_type": envelope["payload_type"],
        "payload": envelope["payload"],
        "canonicalization_version": envelope["canonicalization_version"],
    }
    reordered_payload_envelope = {
        "canonicalization_version": envelope["canonicalization_version"],
        "payload": dict(reversed(tuple(payload.items()))),
        "payload_type": envelope["payload_type"],
    }
    variants = (
        data + b"\n",
        b" " + data + b" ",
        json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8"),
        _json_bytes(reordered_top_level, sort_keys=False),
        _json_bytes(reordered_payload_envelope, sort_keys=False),
        _json_bytes(envelope, separators=(", ", ": ")),
    )

    for variant in variants:
        _assert_parse_failure(
            variant,
            AllocationCertificateParseFailureCode.NON_CANONICAL,
        )


def test_each_canonical_transcript_order_parses_without_normalization() -> None:
    certificate_ab = _accepted_order_certificate((0, 1))
    certificate_ba = _accepted_order_certificate((1, 0))

    parsed_ab = parse_canonical_allocation_certificate(
        canonical_allocation_certificate_bytes(certificate_ab)
    )
    parsed_ba = parse_canonical_allocation_certificate(
        canonical_allocation_certificate_bytes(certificate_ba)
    )

    assert parsed_ab.admission_decisions == certificate_ab.admission_decisions
    assert parsed_ba.admission_decisions == certificate_ba.admission_decisions
    assert parsed_ab.admission_decisions != parsed_ba.admission_decisions


def test_infeasible_certificate_preserves_explicit_null_evidence() -> None:
    parsed = parse_canonical_allocation_certificate(
        canonical_allocation_certificate_bytes(_empty_certificate())
    )

    assert parsed.allocation.status is AllocationStatus.INFEASIBLE
    assert parsed.allocation.winner_merchant_id is None
    assert parsed.allocation.winning_bid_id is None
    assert parsed.allocation.allocated_quantity is None
    assert parsed.allocation.winning_unit_price is None
    assert parsed.allocation.payment_unit_price is None
    assert parsed.allocation.total_payment is None


def test_parsing_is_deterministic() -> None:
    data = _golden_data()

    first = parse_canonical_allocation_certificate(data)
    second = parse_canonical_allocation_certificate(data)

    assert first == second


def test_structurally_valid_false_allocation_parses_without_semantic_verification() -> None:
    original = _accepted_order_certificate((0, 1))
    wrong_allocation = Allocation(
        market_id=original.allocation.market_id,
        buyer_policy_commitment=original.buyer_policy_commitment,
        mechanism_version=original.buyer_policy.mechanism_version,
        status=AllocationStatus.FEASIBLE,
        winner_merchant_id=original.allocation.winner_merchant_id,
        winning_bid_id=original.allocation.winning_bid_id,
        allocated_quantity=4,
        winning_unit_price=original.allocation.winning_unit_price,
        payment_unit_price=original.buyer_policy.reserve_unit_price,
        total_payment=original.buyer_policy.max_total_payment,
    )
    false_certificate = AllocationCertificate(
        certificate_id=original.certificate_id,
        buyer_policy=original.buyer_policy,
        buyer_policy_commitment=original.buyer_policy_commitment,
        admission_decisions=original.admission_decisions,
        allocation=wrong_allocation,
    )
    data = canonical_allocation_certificate_bytes(false_certificate)

    parsed = parse_canonical_allocation_certificate(data)
    verification = verify_allocation_certificate(parsed)

    assert parsed == false_certificate
    assert verification.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
