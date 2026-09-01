import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Final, cast

from pydantic import ValidationError

from clear_market.certificate.models import AllocationCertificate
from clear_market.certificate.serialization import canonical_allocation_certificate_bytes

MAX_CANONICAL_CERTIFICATE_BYTES: Final[int] = 1_048_576

_UTF8_BOM = b"\xef\xbb\xbf"
_ENVELOPE_KEYS = frozenset(("canonicalization_version", "payload_type", "payload"))
_WIRE_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class AllocationCertificateParseFailureCode(StrEnum):
    INPUT_TOO_LARGE = "input_too_large"
    INVALID_UTF8 = "invalid_utf8"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_ENVELOPE = "invalid_envelope"
    INVALID_CERTIFICATE = "invalid_certificate"
    NON_CANONICAL = "non_canonical"


class AllocationCertificateParseError(ValueError):
    """Stable failure category for untrusted canonical certificate bytes."""

    __slots__ = ("_code",)

    def __init__(self, code: AllocationCertificateParseFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> AllocationCertificateParseFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _NonStandardConstantError(ValueError):
    pass


class _InvalidWireTimestampError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonstandard_constant(_value: str) -> object:
    raise _NonStandardConstantError


def _wire_datetime(value: object) -> object:
    if type(value) is not str:
        return value
    text = value
    if _WIRE_TIMESTAMP_PATTERN.fullmatch(text) is None:
        raise _InvalidWireTimestampError

    construction_text = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(construction_text)
    except ValueError:
        raise _InvalidWireTimestampError from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _InvalidWireTimestampError
    return parsed


def _as_exact_dict(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    return cast(dict[str, object], value)


def _convert_targeted_wire_timestamps(payload: dict[str, object]) -> None:
    buyer_policy = _as_exact_dict(payload.get("buyer_policy"))
    if buyer_policy is not None and "bid_deadline" in buyer_policy:
        buyer_policy["bid_deadline"] = _wire_datetime(buyer_policy["bid_deadline"])

    admission_decisions = payload.get("admission_decisions")
    if type(admission_decisions) is not list:
        return

    for decision_value in cast(list[object], admission_decisions):
        decision = _as_exact_dict(decision_value)
        if decision is None:
            continue

        signed_bid = _as_exact_dict(decision.get("signed_bid"))
        bid = _as_exact_dict(signed_bid.get("bid")) if signed_bid is not None else None
        if bid is not None and "submitted_at" in bid:
            bid["submitted_at"] = _wire_datetime(bid["submitted_at"])

        context = _as_exact_dict(decision.get("context"))
        if context is not None and "received_at" in context:
            context["received_at"] = _wire_datetime(context["received_at"])


def parse_canonical_allocation_certificate(data: bytes) -> AllocationCertificate:
    """Accept only a bounded, exact canonical encoding of the frozen certificate model."""
    if type(data) is not bytes:
        raise TypeError("data must be exactly bytes")
    if len(data) > MAX_CANONICAL_CERTIFICATE_BYTES:
        raise AllocationCertificateParseError(AllocationCertificateParseFailureCode.INPUT_TOO_LARGE)
    if data.startswith(_UTF8_BOM):
        raise AllocationCertificateParseError(AllocationCertificateParseFailureCode.INVALID_UTF8)

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_UTF8
        ) from None

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except _DuplicateKeyError:
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.DUPLICATE_KEY
        ) from None
    except (_NonStandardConstantError, json.JSONDecodeError, ValueError):
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_JSON
        ) from None

    root = _as_exact_dict(parsed)
    if root is None:
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_ENVELOPE
        )
    if set(root) != _ENVELOPE_KEYS:
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_ENVELOPE
        )
    if root["canonicalization_version"] != "clear-json-v1":
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_ENVELOPE
        )
    if root["payload_type"] != "allocation_certificate":
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_ENVELOPE
        )

    payload = _as_exact_dict(root["payload"])
    if payload is None:
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_ENVELOPE
        )

    try:
        _convert_targeted_wire_timestamps(payload)
        certificate = AllocationCertificate.model_validate(payload)
    except (_InvalidWireTimestampError, ValidationError):
        raise AllocationCertificateParseError(
            AllocationCertificateParseFailureCode.INVALID_CERTIFICATE
        ) from None

    if canonical_allocation_certificate_bytes(certificate) != data:
        raise AllocationCertificateParseError(AllocationCertificateParseFailureCode.NON_CANONICAL)
    return certificate
