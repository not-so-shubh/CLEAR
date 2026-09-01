from collections.abc import Callable

import pytest

from clear_market.certificate import (
    MAX_CANONICAL_CERTIFICATE_BYTES,
    AllocationCertificateParseError,
    AllocationCertificateParseFailureCode,
    canonical_allocation_certificate_bytes,
    parse_canonical_allocation_certificate,
)
from tests.adversarial.parser_helpers import (
    replace_once,
    valid_adversarial_certificate_bytes,
)

_DEADLINE = b"2026-09-01T12:00:00.000000Z"
_FIRST_SUBMITTED_WITH_PRICE = b'"submitted_at":"2026-09-01T11:59:58.000000Z","unit_price_paise":400'
_FIRST_RECEIVED_WITH_BID_ID = (
    b'"context":{"received_at":"2026-09-01T11:59:59.000000Z"},'
    b'"rejection_code":null,"signed_bid":{"bid":{"bid_id":'
    b'"74000000-0001-4000-8000-000000000385"'
)


class BytesSubclass(bytes):
    pass


def _assert_parse_failure(
    data: bytes,
    expected_code: AllocationCertificateParseFailureCode,
) -> None:
    with pytest.raises(AllocationCertificateParseError) as caught:
        parse_canonical_allocation_certificate(data)

    assert caught.value.code is expected_code


def test_valid_canonical_certificate_control_roundtrips_exactly() -> None:
    original = valid_adversarial_certificate_bytes()

    parsed = parse_canonical_allocation_certificate(original)

    assert canonical_allocation_certificate_bytes(parsed) == original


def test_bytes_subclass_is_rejected_by_exact_type_boundary() -> None:
    data = BytesSubclass(valid_adversarial_certificate_bytes())

    with pytest.raises(TypeError):
        parse_canonical_allocation_certificate(data)


@pytest.mark.parametrize("excess", [1, 4_096], ids=["max-plus-one", "max-plus-4096"])
def test_oversized_input_is_rejected_before_later_parsing(excess: int) -> None:
    _assert_parse_failure(
        b"x" * (MAX_CANONICAL_CERTIFICATE_BYTES + excess),
        AllocationCertificateParseFailureCode.INPUT_TOO_LARGE,
    )


@pytest.mark.parametrize(
    "data_factory",
    [
        lambda: b"\xff",
        lambda: b"\xef\xbb\xbf" + valid_adversarial_certificate_bytes(),
        lambda: replace_once(
            valid_adversarial_certificate_bytes(),
            b'"payload_type":"allocation_certificate"',
            b'"payload_type":"allocation_\xffcertificate"',
        ),
    ],
    ids=["raw-invalid-byte", "utf8-bom", "invalid-byte-inside-certificate"],
)
def test_invalid_utf8_and_bom_are_rejected(data_factory: Callable[[], bytes]) -> None:
    _assert_parse_failure(
        data_factory(),
        AllocationCertificateParseFailureCode.INVALID_UTF8,
    )


@pytest.mark.parametrize(
    "data",
    [
        b"{",
        b"[",
        b'{"x":',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
    ],
    ids=["object", "array", "missing-value", "nan", "infinity", "negative-infinity"],
)
def test_malformed_json_and_nonstandard_constants_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize(
    "data",
    [
        (
            b'{"canonicalization_version":"clear-json-v1",'
            b'"canonicalization_version":"clear-json-v1","payload":{},'
            b'"payload_type":"allocation_certificate"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{'
            b'"schema_version":"1","schema_version":"1"},'
            b'"payload_type":"allocation_certificate"}'
        ),
    ],
    ids=["root", "nested-payload"],
)
def test_duplicate_keys_are_rejected_at_every_nesting_level(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateParseFailureCode.DUPLICATE_KEY)


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b"{}",
        b'{"canonicalization_version":"clear-json-v1","payload":{}}',
        b'{"payload":{},"payload_type":"allocation_certificate"}',
        (b'{"canonicalization_version":"clear-json-v1","payload_type":"allocation_certificate"}'),
        (
            b'{"canonicalization_version":"clear-json-v1","extra":null,"payload":{},'
            b'"payload_type":"allocation_certificate"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v2","payload":{},'
            b'"payload_type":"allocation_certificate"}'
        ),
        (b'{"canonicalization_version":"clear-json-v1","payload":{},"payload_type":"other"}'),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":[],'
            b'"payload_type":"allocation_certificate"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":null,'
            b'"payload_type":"allocation_certificate"}'
        ),
    ],
    ids=[
        "root-array",
        "empty-object",
        "missing-payload-type",
        "missing-canonicalization-version",
        "missing-payload",
        "extra-key",
        "wrong-canonicalization-version",
        "wrong-payload-type",
        "payload-array",
        "payload-null",
    ],
)
def test_invalid_root_and_envelope_shapes_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateParseFailureCode.INVALID_ENVELOPE)


@pytest.mark.parametrize(
    "data",
    [
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{},'
            b'"payload_type":"allocation_certificate"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1",'
            b'"payload":{"schema_version":"1"},'
            b'"payload_type":"allocation_certificate"}'
        ),
    ],
    ids=["empty-payload", "schema-only-payload"],
)
def test_valid_envelope_with_invalid_certificate_payload_is_rejected(data: bytes) -> None:
    _assert_parse_failure(data, AllocationCertificateParseFailureCode.INVALID_CERTIFICATE)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data + b"\n",
        lambda data: data + b" ",
        lambda data: b" " + data,
        lambda data: b"\n" + data,
    ],
    ids=["trailing-newline", "trailing-space", "leading-space", "leading-newline"],
)
def test_leading_and_trailing_json_whitespace_is_noncanonical(
    mutator: Callable[[bytes], bytes],
) -> None:
    _assert_parse_failure(
        mutator(valid_adversarial_certificate_bytes()),
        AllocationCertificateParseFailureCode.NON_CANONICAL,
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (_DEADLINE, b"2026-09-01T12:00:00.000000+00:00"),
        (
            _FIRST_SUBMITTED_WITH_PRICE,
            b'"submitted_at":"2026-09-01T11:59:58Z","unit_price_paise":400',
        ),
        (
            _FIRST_RECEIVED_WITH_BID_ID,
            b'"context":{"received_at":"2026-09-01T17:29:59.000000+05:30"},'
            b'"rejection_code":null,"signed_bid":{"bid":{"bid_id":'
            b'"74000000-0001-4000-8000-000000000385"',
        ),
    ],
    ids=["deadline-plus-zero-offset", "submitted-no-microseconds", "received-plus-0530"],
)
def test_semantically_parseable_timestamp_variants_are_noncanonical(
    old: bytes,
    new: bytes,
) -> None:
    mutated = replace_once(valid_adversarial_certificate_bytes(), old, new)

    _assert_parse_failure(mutated, AllocationCertificateParseFailureCode.NON_CANONICAL)


def test_malformed_timestamp_grammar_is_invalid_certificate() -> None:
    malformed = replace_once(
        valid_adversarial_certificate_bytes(),
        _FIRST_SUBMITTED_WITH_PRICE,
        b'"submitted_at":"2026-09-01 11:59:58","unit_price_paise":400',
    )

    _assert_parse_failure(
        malformed,
        AllocationCertificateParseFailureCode.INVALID_CERTIFICATE,
    )
