import json
from typing import Any, cast

import pytest

from clear_market.certificate.v2 import (
    MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES,
    AllocationCertificateV2ParseError,
    AllocationCertificateV2ParseFailureCode,
    MerchantOfferAdmissionDecisionV2,
    canonical_allocation_certificate_v2_bytes,
    parse_canonical_allocation_certificate_v2,
)
from tests.certificate.v2.test_serialization import _certificate, _validated_copy


class _BytesSubclass(bytes):
    pass


def _canonical_data() -> bytes:
    return canonical_allocation_certificate_v2_bytes(_certificate())


def _parsed_wire() -> dict[str, Any]:
    parsed = json.loads(_canonical_data())
    assert type(parsed) is dict
    return cast(dict[str, Any], parsed)


def _compact_json(value: object, *, ensure_ascii: bool = False) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _assert_parse_failure(
    data: bytes,
    expected: AllocationCertificateV2ParseFailureCode,
) -> None:
    with pytest.raises(AllocationCertificateV2ParseError) as caught:
        parse_canonical_allocation_certificate_v2(data)
    assert caught.value.code is expected
    assert str(caught.value) == expected.value


def test_parser_requires_exact_builtin_bytes() -> None:
    data = _canonical_data()
    for invalid in (_BytesSubclass(data), bytearray(data), memoryview(data), data.decode()):
        with pytest.raises(TypeError):
            parse_canonical_allocation_certificate_v2(cast(Any, invalid))


def test_frozen_19a_golden_parses_and_roundtrips_exactly() -> None:
    data = _canonical_data()
    assert len(data) == 14_454
    parsed = parse_canonical_allocation_certificate_v2(data)
    assert parsed == _certificate()
    assert canonical_allocation_certificate_v2_bytes(parsed) == data
    assert parse_canonical_allocation_certificate_v2(data) == parsed


@pytest.mark.parametrize("extra", [1, 4_096])
def test_oversized_input_is_rejected_before_content(extra: int) -> None:
    _assert_parse_failure(
        b"x" * (MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES + extra),
        AllocationCertificateV2ParseFailureCode.INPUT_TOO_LARGE,
    )


@pytest.mark.parametrize(
    "data",
    [
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"x":"\xff"}',
    ],
)
def test_invalid_utf8_and_bom_fail_closed(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.INVALID_UTF8)


@pytest.mark.parametrize("data", [b"{", b"[", b'{"x":', b"not-json"])
def test_malformed_json_is_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize(
    "data",
    [b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}'],
)
def test_nonstandard_json_constants_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.INVALID_JSON)


def test_json_recursion_failure_is_stable_and_bounded() -> None:
    data = b"[" * 10_000 + b"]" * 10_000
    assert len(data) < MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES
    with pytest.raises(RecursionError):
        json.loads(data.decode("ascii"))
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.INVALID_JSON)


def test_json_integer_conversion_value_error_is_stable_when_enabled() -> None:
    data = b'{"x":' + b"1" * 5_000 + b"}"
    assert len(data) < MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES
    try:
        json.loads(data)
    except ValueError:
        pass
    else:
        pytest.skip("runtime integer-string conversion protection is disabled")
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize(
    "data",
    [
        b'{"canonicalization_version":"clear-json-v1",'
        b'"canonicalization_version":"clear-json-v1",'
        b'"payload":{},"payload_type":"allocation_certificate_v2"}',
        b'{"canonicalization_version":"clear-json-v1",'
        b'"payload":{"nested":{"schema_version":"2","schema_version":"2"}},'
        b'"payload_type":"allocation_certificate_v2"}',
    ],
)
def test_duplicate_keys_at_any_depth_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.DUPLICATE_KEY)


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b"{}",
        b'{"canonicalization_version":"clear-json-v1","payload":{}}',
        b'{"payload":{},"payload_type":"allocation_certificate_v2"}',
        b'{"canonicalization_version":"clear-json-v1","payload_type":"allocation_certificate_v2"}',
        b'{"canonicalization_version":"clear-json-v1","extra":0,'
        b'"payload":{},"payload_type":"allocation_certificate_v2"}',
        b'{"canonicalization_version":"clear-json-v2","payload":{},'
        b'"payload_type":"allocation_certificate_v2"}',
        b'{"canonicalization_version":"clear-json-v1","payload":{},"payload_type":"other"}',
        b'{"canonicalization_version":"clear-json-v1","payload":[],'
        b'"payload_type":"allocation_certificate_v2"}',
        b'{"canonicalization_version":"clear-json-v1","payload":null,'
        b'"payload_type":"allocation_certificate_v2"}',
    ],
)
def test_invalid_root_and_envelope_shapes_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateV2ParseFailureCode.INVALID_ENVELOPE)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("payload", "schema_version"), "1"),
        (("payload", "buyer_policy", "max_total_payment", "amount_paise"), "5000"),
        (("payload", "allocation", "status"), "UNKNOWN"),
        (("payload", "certificate_id"), "not-a-uuid"),
        (("payload", "buyer_policy", "offer_deadline"), "2026-09-01T12:00:00"),
        (("payload", "buyer_policy", "market_spec", "hard_constraints"), [[]]),
    ],
)
def test_structurally_invalid_certificate_payloads_are_rejected(
    path: tuple[str, ...],
    invalid: object,
) -> None:
    parsed: Any = _parsed_wire()
    target = parsed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = invalid
    _assert_parse_failure(
        _compact_json(parsed),
        AllocationCertificateV2ParseFailureCode.INVALID_CERTIFICATE,
    )


def test_unrepresentable_unicode_is_invalid_certificate_not_a_raw_error() -> None:
    parsed: Any = _parsed_wire()
    parsed["payload"]["merchant_offer_evidence"][0]["catalog"]["products"][0]["display_name"] = (
        "\ud800"
    )
    data = _compact_json(parsed, ensure_ascii=True)
    assert b"\\ud800" in data
    _assert_parse_failure(
        data,
        AllocationCertificateV2ParseFailureCode.INVALID_CERTIFICATE,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data + b"\n",
        lambda data: b" " + data,
        lambda data: data.replace(
            b'{"canonicalization_version":"clear-json-v1","payload":',
            b'{"payload":',
            1,
        ).replace(
            b',"payload_type":"allocation_certificate_v2"}',
            b',"payload_type":"allocation_certificate_v2",'
            b'"canonicalization_version":"clear-json-v1"}',
            1,
        ),
        lambda _data: _compact_json(_parsed_wire(), ensure_ascii=True),
        lambda data: data.replace(
            b"2026-09-01T12:00:00.000000Z",
            b"2026-09-01T12:00:00.000000+00:00",
            1,
        ),
        lambda data: data.replace(
            b"2026-09-01T11:59:58.000000Z",
            b"2026-09-01T17:29:58.000000+05:30",
            1,
        ),
        lambda data: data.replace(
            b"2026-09-01T11:59:58.000000Z",
            b"2026-09-01T11:59:58Z",
            1,
        ),
    ],
)
def test_semantically_decodable_noncanonical_wire_forms_are_rejected(
    mutate: Any,
) -> None:
    data = _canonical_data()
    changed = mutate(data)
    assert changed != data
    _assert_parse_failure(changed, AllocationCertificateV2ParseFailureCode.NON_CANONICAL)


def test_semantic_transcript_order_is_preserved_by_structural_parser() -> None:
    certificate = _certificate()
    reversed_certificate = _validated_copy(
        certificate,
        merchant_offer_evidence=tuple(reversed(certificate.merchant_offer_evidence)),
    )
    parsed = parse_canonical_allocation_certificate_v2(
        canonical_allocation_certificate_v2_bytes(reversed_certificate)
    )
    assert parsed.merchant_offer_evidence == reversed_certificate.merchant_offer_evidence


def test_semantically_false_but_canonical_certificate_is_structurally_parseable() -> None:
    certificate = _certificate()
    first = _validated_copy(
        certificate.merchant_offer_evidence[0],
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    false_claim = _validated_copy(
        certificate,
        merchant_offer_evidence=(first, *certificate.merchant_offer_evidence[1:]),
    )
    data = canonical_allocation_certificate_v2_bytes(false_claim)
    assert parse_canonical_allocation_certificate_v2(data) == false_claim
