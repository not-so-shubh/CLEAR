"""Immutable non-protocol credentials for Razorpay Test Mode only."""


def _validated_text(
    value: object,
    *,
    minimum_bytes: int,
    maximum_bytes: int,
    message: str,
) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError(message)
    try:
        byte_length = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise ValueError(message) from None
    if not minimum_bytes <= byte_length <= maximum_bytes:
        raise ValueError(message)
    return value


class RazorpayTestCredentialsV1:
    """Redacted, immutable credentials incapable of accepting a live key ID."""

    __slots__ = ("__key_id", "__key_secret")
    __key_id: str
    __key_secret: str

    def __init__(self, *, key_id: str, key_secret: str) -> None:
        validated_key_id = _validated_text(
            key_id,
            minimum_bytes=1,
            maximum_bytes=256,
            message="key_id must be 1..256 valid UTF-8 bytes without NUL",
        )
        if not validated_key_id.startswith("rzp_test_"):
            raise ValueError("key_id must identify Razorpay Test Mode")
        validated_secret = _validated_text(
            key_secret,
            minimum_bytes=1,
            maximum_bytes=512,
            message="key_secret must be 1..512 valid UTF-8 bytes without NUL",
        )
        object.__setattr__(self, "_RazorpayTestCredentialsV1__key_id", validated_key_id)
        object.__setattr__(self, "_RazorpayTestCredentialsV1__key_secret", validated_secret)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("RazorpayTestCredentialsV1 is immutable")

    def __repr__(self) -> str:
        return "RazorpayTestCredentialsV1(<redacted>)"

    __str__ = __repr__

    def _private_pair(self) -> tuple[str, str]:
        return self.__key_id, self.__key_secret


def _credential_pair(value: object) -> tuple[str, str]:
    if type(value) is not RazorpayTestCredentialsV1:
        raise TypeError("credentials must be exactly RazorpayTestCredentialsV1")
    key_id, key_secret = value._private_pair()
    validated_key_id = _validated_text(
        key_id,
        minimum_bytes=1,
        maximum_bytes=256,
        message="key_id must be 1..256 valid UTF-8 bytes without NUL",
    )
    if not validated_key_id.startswith("rzp_test_"):
        raise ValueError("key_id must identify Razorpay Test Mode")
    validated_secret = _validated_text(
        key_secret,
        minimum_bytes=1,
        maximum_bytes=512,
        message="key_secret must be 1..512 valid UTF-8 bytes without NUL",
    )
    return validated_key_id, validated_secret
