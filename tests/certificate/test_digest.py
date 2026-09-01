import pytest

from clear_market.certificate import (
    ALLOCATION_CERTIFICATE_DIGEST_VERSION,
    allocation_certificate_digest,
    canonical_allocation_certificate_bytes,
)

from .test_serialization import _accepted_order_certificate, _golden_certificate

_GOLDEN_CERTIFICATE_SHA256 = "53a6342dd1d719bea7b15dd4c5ae66a392cf2a862febc49a16f233ca632d1796"
_OTHER_CERTIFICATE_ID = "50000000-0000-4000-8000-000000000002"
_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def test_allocation_certificate_digest_version_is_exact() -> None:
    assert ALLOCATION_CERTIFICATE_DIGEST_VERSION == "sha256-allocation-certificate-clear-json-v1"


def test_golden_allocation_certificate_digest_is_exact() -> None:
    assert allocation_certificate_digest(_golden_certificate()) == _GOLDEN_CERTIFICATE_SHA256


def test_allocation_certificate_digest_is_lowercase_64_character_hex() -> None:
    digest = allocation_certificate_digest(_golden_certificate())

    assert len(digest) == 64
    assert all(character in _LOWERCASE_HEX_DIGITS for character in digest)


def test_allocation_certificate_digest_is_deterministic() -> None:
    allocation_certificate = _golden_certificate()

    assert allocation_certificate_digest(allocation_certificate) == allocation_certificate_digest(
        allocation_certificate
    )


@pytest.mark.parametrize("value", [None, {}, "certificate", b"certificate", object()])
def test_allocation_certificate_digest_rejects_non_certificate(value: object) -> None:
    with pytest.raises(TypeError):
        allocation_certificate_digest(value)


def test_certificate_id_changes_canonical_bytes_and_digest() -> None:
    original = _golden_certificate()
    changed = _golden_certificate(_OTHER_CERTIFICATE_ID)

    assert canonical_allocation_certificate_bytes(
        original
    ) != canonical_allocation_certificate_bytes(changed)
    assert allocation_certificate_digest(original) != allocation_certificate_digest(changed)


def test_transcript_order_changes_allocation_certificate_digest() -> None:
    certificate_ab = _accepted_order_certificate((0, 1))
    certificate_ba = _accepted_order_certificate((1, 0))

    assert certificate_ab.allocation == certificate_ba.allocation
    assert allocation_certificate_digest(certificate_ab) != allocation_certificate_digest(
        certificate_ba
    )
