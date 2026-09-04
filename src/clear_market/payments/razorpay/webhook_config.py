"""Trusted local verification configuration for Razorpay webhook ingress."""

import re
from typing import Final

_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"acc_[A-Za-z0-9]{1,14}",
    flags=re.ASCII,
)
_REDACTED_REPRESENTATION: Final[str] = "RazorpayWebhookVerificationConfigV1(<redacted>)"


def _account_id(value: object) -> str:
    if type(value) is not str or _ACCOUNT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("expected account ID is not canonical")
    return value


def _secret(value: object) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError("webhook secret is invalid")
    try:
        length = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise ValueError("webhook secret is invalid") from None
    if not 1 <= length <= 512:
        raise ValueError("webhook secret is invalid")
    return value


class RazorpayWebhookVerificationConfigV1:
    """Trusted application configuration for an intended Razorpay Test Mode endpoint.

    The caller must supply the webhook secrets configured for that endpoint. Webhook JSON does not
    establish whether a delivery came from a Test Mode or Live Mode endpoint.
    """

    __slots__ = ("_expected_account_id", "_secrets")

    _expected_account_id: str
    _secrets: tuple[str, ...]

    def __init__(
        self,
        *,
        expected_account_id: str,
        secrets: tuple[str, ...],
    ) -> None:
        if type(secrets) is not tuple or not 1 <= len(secrets) <= 8:
            raise ValueError("webhook secrets must be an exact tuple containing 1..8 values")
        validated = tuple(_secret(value) for value in secrets)
        if len(set(validated)) != len(validated):
            raise ValueError("webhook secrets must be unique")
        object.__setattr__(self, "_expected_account_id", _account_id(expected_account_id))
        object.__setattr__(self, "_secrets", validated)

    @property
    def expected_account_id(self) -> str:
        return self._expected_account_id

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("RazorpayWebhookVerificationConfigV1 is immutable")

    def __repr__(self) -> str:
        return _REDACTED_REPRESENTATION

    def __str__(self) -> str:
        return _REDACTED_REPRESENTATION


def _verification_material(
    value: object,
) -> tuple[str, tuple[str, ...]]:
    if type(value) is not RazorpayWebhookVerificationConfigV1:
        raise TypeError("verification_config must be exactly RazorpayWebhookVerificationConfigV1")
    try:
        account_id = object.__getattribute__(value, "_expected_account_id")
        secrets = object.__getattribute__(value, "_secrets")
    except AttributeError:
        raise ValueError("verification configuration is invalid") from None
    fresh = RazorpayWebhookVerificationConfigV1(
        expected_account_id=account_id,
        secrets=secrets,
    )
    return fresh._expected_account_id, fresh._secrets
