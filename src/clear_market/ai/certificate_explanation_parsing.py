"""Strict JSON boundary for untrusted certificate-explanation model output."""

import json
from enum import StrEnum
from typing import NoReturn

from pydantic import ValidationError

from clear_market.ai.certificate_explanation import (
    MAX_CERTIFICATE_EXPLANATION_JSON_BYTES,
    CertificateExplanationCandidateV1,
    CertificateExplanationClaimV1,
)


class CertificateExplanationParseFailureCode(StrEnum):
    INPUT_TOO_LARGE = "input_too_large"
    INVALID_TEXT = "invalid_text"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_CANDIDATE = "invalid_candidate"


class CertificateExplanationParseError(ValueError):
    """Stable explanation parse failure without model output or validation details."""

    __slots__ = ("_code",)

    def __init__(self, code: CertificateExplanationParseFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> CertificateExplanationParseFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


_CANDIDATE_KEYS = {
    "schema_version",
    "certificate_explanation_candidate_version",
    "claims",
}
_CLAIM_KEYS = {
    "schema_version",
    "certificate_explanation_claim_version",
    "text",
    "citation_ids",
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_json_constant(_: str) -> NoReturn:
    raise _InvalidJsonConstantError


def _convert_claim(value: object) -> object:
    if type(value) is not dict or set(value) != _CLAIM_KEYS:
        return value
    converted = dict(value)
    citation_ids = converted.get("citation_ids")
    if type(citation_ids) is list:
        converted["citation_ids"] = tuple(citation_ids)
    try:
        return CertificateExplanationClaimV1.model_validate(converted)
    except ValidationError:
        return value


def _convert_candidate_root(value: dict[str, object]) -> dict[str, object]:
    converted = dict(value)
    claims = converted.get("claims")
    if type(claims) is list:
        converted["claims"] = tuple(_convert_claim(claim) for claim in claims)
    return converted


def parse_certificate_explanation_candidate_v1(
    output_text: str,
) -> CertificateExplanationCandidateV1:
    """Parse bounded provider JSON without repair, grounding, or canonical-byte requirements."""
    if type(output_text) is not str:
        raise TypeError("output_text must be exactly a string")
    if "\x00" in output_text:
        raise CertificateExplanationParseError(CertificateExplanationParseFailureCode.INVALID_TEXT)
    try:
        encoded = output_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise CertificateExplanationParseError(
            CertificateExplanationParseFailureCode.INVALID_TEXT
        ) from None
    if len(encoded) > MAX_CERTIFICATE_EXPLANATION_JSON_BYTES:
        raise CertificateExplanationParseError(
            CertificateExplanationParseFailureCode.INPUT_TOO_LARGE
        )

    try:
        parsed = json.loads(
            output_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKeyError:
        raise CertificateExplanationParseError(
            CertificateExplanationParseFailureCode.DUPLICATE_KEY
        ) from None
    except (ValueError, RecursionError):
        raise CertificateExplanationParseError(
            CertificateExplanationParseFailureCode.INVALID_JSON
        ) from None

    if type(parsed) is not dict or set(parsed) != _CANDIDATE_KEYS:
        raise CertificateExplanationParseError(
            CertificateExplanationParseFailureCode.INVALID_CANDIDATE
        )

    try:
        return CertificateExplanationCandidateV1.model_validate(_convert_candidate_root(parsed))
    except (ValidationError, RecursionError):
        raise CertificateExplanationParseError(
            CertificateExplanationParseFailureCode.INVALID_CANDIDATE
        ) from None
