import pytest

from clear_market.payments.razorpay import RazorpayTestCredentialsV1
from clear_market.payments.razorpay.credentials import _credential_pair

_SECRET = "test-secret-value"


def test_valid_credentials_are_immutable_slotted_and_redacted() -> None:
    credentials = RazorpayTestCredentialsV1(
        key_id="rzp_test_reviewable",
        key_secret=_SECRET,
    )
    assert repr(credentials) == "RazorpayTestCredentialsV1(<redacted>)"
    assert str(credentials) == "RazorpayTestCredentialsV1(<redacted>)"
    assert _SECRET not in repr(credentials)
    assert not hasattr(credentials, "__dict__")
    assert not hasattr(credentials, "model_dump")
    with pytest.raises(AttributeError):
        credentials.key_id = "rzp_test_other"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("key_id", "key_secret"),
    [
        ("", _SECRET),
        ("rzp_live_reviewable", _SECRET),
        ("test_reviewable", _SECRET),
        (" rzp_test_reviewable", _SECRET),
        ("rzp_test_\x00bad", _SECRET),
        ("rzp_test_\ud800", _SECRET),
        ("rzp_test_reviewable", ""),
        ("rzp_test_reviewable", "\x00"),
        ("rzp_test_reviewable", "\ud800"),
        ("rzp_test_" + "a" * 248, _SECRET),
        ("rzp_test_reviewable", "s" * 513),
    ],
)
def test_invalid_credentials_are_rejected_without_normalization(
    key_id: str,
    key_secret: str,
) -> None:
    with pytest.raises(ValueError):
        RazorpayTestCredentialsV1(key_id=key_id, key_secret=key_secret)


@pytest.mark.parametrize(
    ("key_id", "key_secret"),
    [
        (b"rzp_test_key", _SECRET),
        (1, _SECRET),
        ("rzp_test_key", b"secret"),
        ("rzp_test_key", None),
    ],
)
def test_credentials_require_exact_strings(key_id: object, key_secret: object) -> None:
    with pytest.raises(ValueError):
        RazorpayTestCredentialsV1(key_id=key_id, key_secret=key_secret)  # type: ignore[arg-type]


def test_credential_utf8_byte_bounds_are_inclusive() -> None:
    RazorpayTestCredentialsV1(key_id="rzp_test_" + "a" * 247, key_secret="s" * 512)


def test_credentials_are_not_trimmed_or_normalized() -> None:
    credentials = RazorpayTestCredentialsV1(
        key_id="rzp_test_reviewable ",
        key_secret=" secret ",
    )
    assert _credential_pair(credentials) == ("rzp_test_reviewable ", " secret ")
