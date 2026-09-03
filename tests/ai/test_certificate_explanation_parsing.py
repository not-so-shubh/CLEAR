import json
from typing import Any, cast

import pytest

from clear_market.ai import (
    CertificateExplanationParseError,
    CertificateExplanationParseFailureCode,
    parse_certificate_explanation_candidate_v1,
)
from clear_market.ai.certificate_explanation import MAX_CERTIFICATE_EXPLANATION_JSON_BYTES

_DEFAULT = object()


class _StringSubclass(str):
    pass


def _claim_payload(**changes: object) -> dict[str, object]:
    return {
        "schema_version": "1",
        "certificate_explanation_claim_version": "certificate-explanation-claim-v1",
        "text": "The verified allocation fulfills five units.",
        "citation_ids": ["allocation"],
        **changes,
    }


def _candidate_payload(**changes: object) -> dict[str, object]:
    return {
        "schema_version": "1",
        "certificate_explanation_candidate_version": ("certificate-explanation-candidate-v1"),
        "claims": [_claim_payload()],
        **changes,
    }


def _json(payload: object = _DEFAULT, *, indent: int | None = None) -> str:
    return json.dumps(
        _candidate_payload() if payload is _DEFAULT else payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=None if indent is not None else (",", ":"),
        indent=indent,
    )


def _assert_failure(
    output_text: str,
    code: CertificateExplanationParseFailureCode,
) -> CertificateExplanationParseError:
    with pytest.raises(CertificateExplanationParseError) as caught:
        parse_certificate_explanation_candidate_v1(output_text)
    assert caught.value.code is code
    assert str(caught.value) == code.value
    return caught.value


def test_parse_failure_contract_is_exact_and_read_only() -> None:
    assert tuple(CertificateExplanationParseFailureCode) == (
        CertificateExplanationParseFailureCode.INPUT_TOO_LARGE,
        CertificateExplanationParseFailureCode.INVALID_TEXT,
        CertificateExplanationParseFailureCode.INVALID_JSON,
        CertificateExplanationParseFailureCode.DUPLICATE_KEY,
        CertificateExplanationParseFailureCode.INVALID_CANDIDATE,
    )
    assert tuple(code.value for code in CertificateExplanationParseFailureCode) == (
        "input_too_large",
        "invalid_text",
        "invalid_json",
        "duplicate_key",
        "invalid_candidate",
    )
    error = CertificateExplanationParseError(CertificateExplanationParseFailureCode.INVALID_JSON)
    assert str(error) == "invalid_json"
    with pytest.raises(AttributeError):
        error.code = CertificateExplanationParseFailureCode.INVALID_TEXT


@pytest.mark.parametrize("value", [b"{}", None, {}, 1, _StringSubclass("{}")])
def test_parser_requires_exact_string(value: object) -> None:
    with pytest.raises(TypeError):
        parse_certificate_explanation_candidate_v1(cast(Any, value))


@pytest.mark.parametrize("value", ["bad\x00text", "\ud800"])
def test_invalid_text_is_rejected(value: str) -> None:
    _assert_failure(value, CertificateExplanationParseFailureCode.INVALID_TEXT)


def test_input_byte_limit_is_exact_and_not_a_character_limit() -> None:
    _assert_failure(
        " " * MAX_CERTIFICATE_EXPLANATION_JSON_BYTES,
        CertificateExplanationParseFailureCode.INVALID_JSON,
    )
    _assert_failure(
        " " * (MAX_CERTIFICATE_EXPLANATION_JSON_BYTES + 1),
        CertificateExplanationParseFailureCode.INPUT_TOO_LARGE,
    )
    _assert_failure(
        "é" * ((MAX_CERTIFICATE_EXPLANATION_JSON_BYTES // 2) + 1),
        CertificateExplanationParseFailureCode.INPUT_TOO_LARGE,
    )


@pytest.mark.parametrize("value", ["{", "[", '{"claims":', "not json", "```json\n{}\n```"])
def test_malformed_or_wrapped_json_is_invalid_json(value: str) -> None:
    _assert_failure(value, CertificateExplanationParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_constants_are_rejected(constant: str) -> None:
    _assert_failure(
        '{"schema_version":"1","claims":[' + constant + "]}",
        CertificateExplanationParseFailureCode.INVALID_JSON,
    )


def test_plain_value_error_from_large_json_integer_is_invalid_json() -> None:
    value = "1" * 4_301
    text = '{"n":' + value + "}"
    assert len(text.encode("utf-8")) < MAX_CERTIFICATE_EXPLANATION_JSON_BYTES
    with pytest.raises(ValueError):
        json.loads(text)
    _assert_failure(text, CertificateExplanationParseFailureCode.INVALID_JSON)


def test_deep_json_recursion_is_invalid_json() -> None:
    text = "[" * 10_000 + "0" + "]" * 10_000
    assert len(text.encode("utf-8")) < MAX_CERTIFICATE_EXPLANATION_JSON_BYTES
    with pytest.raises(RecursionError):
        json.loads(text)
    _assert_failure(text, CertificateExplanationParseFailureCode.INVALID_JSON)


def test_duplicate_root_key_is_rejected() -> None:
    _assert_failure(
        '{"schema_version":"1","schema_version":"1",'
        '"certificate_explanation_candidate_version":"certificate-explanation-candidate-v1",'
        '"claims":[]}',
        CertificateExplanationParseFailureCode.DUPLICATE_KEY,
    )


def test_duplicate_nested_claim_key_is_rejected_recursively() -> None:
    _assert_failure(
        '{"schema_version":"1",'
        '"certificate_explanation_candidate_version":"certificate-explanation-candidate-v1",'
        '"claims":[{"schema_version":"1",'
        '"certificate_explanation_claim_version":"certificate-explanation-claim-v1",'
        '"text":"first","text":"second","citation_ids":["allocation"]}]}',
        CertificateExplanationParseFailureCode.DUPLICATE_KEY,
    )


@pytest.mark.parametrize("root", [[], "text", None, 1, True])
def test_non_object_root_is_invalid_candidate(root: object) -> None:
    _assert_failure(_json(root), CertificateExplanationParseFailureCode.INVALID_CANDIDATE)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "2"},
        {"certificate_explanation_candidate_version": "other"},
        {"claims": "not-an-array"},
        {"claims": {}},
        {"claims": ["not-an-object"]},
        {"claims": []},
        {"extra": "forbidden"},
    ],
)
def test_invalid_candidate_root_schema_is_rejected(changes: dict[str, object]) -> None:
    _assert_failure(
        _json(_candidate_payload(**changes)),
        CertificateExplanationParseFailureCode.INVALID_CANDIDATE,
    )


@pytest.mark.parametrize(
    "missing", ["schema_version", "certificate_explanation_candidate_version", "claims"]
)
def test_missing_candidate_field_is_rejected(missing: str) -> None:
    payload = _candidate_payload()
    del payload[missing]
    _assert_failure(_json(payload), CertificateExplanationParseFailureCode.INVALID_CANDIDATE)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "2"},
        {"certificate_explanation_claim_version": "other"},
        {"text": ""},
        {"text": 1},
        {"citation_ids": "allocation"},
        {"citation_ids": {}},
        {"citation_ids": []},
        {"citation_ids": [1]},
        {"citation_ids": ["Allocation"]},
        {"citation_ids": ["allocation", "allocation"]},
        {"extra": "forbidden"},
    ],
)
def test_invalid_nested_claim_schema_is_rejected(changes: dict[str, object]) -> None:
    payload = _candidate_payload(claims=[_claim_payload(**changes)])
    _assert_failure(_json(payload), CertificateExplanationParseFailureCode.INVALID_CANDIDATE)


@pytest.mark.parametrize(
    "missing",
    ["schema_version", "certificate_explanation_claim_version", "text", "citation_ids"],
)
def test_missing_claim_field_is_rejected(missing: str) -> None:
    claim = _claim_payload()
    del claim[missing]
    _assert_failure(
        _json(_candidate_payload(claims=[claim])),
        CertificateExplanationParseFailureCode.INVALID_CANDIDATE,
    )


def test_claim_and_citation_bounds_are_enforced() -> None:
    _assert_failure(
        _json(_candidate_payload(claims=[_claim_payload(text="é" * 2_049)])),
        CertificateExplanationParseFailureCode.INVALID_CANDIDATE,
    )
    _assert_failure(
        _json(
            _candidate_payload(
                claims=[
                    _claim_payload(citation_ids=[f"allocation.line.{index}" for index in range(9)])
                ]
            )
        ),
        CertificateExplanationParseFailureCode.INVALID_CANDIDATE,
    )
    _assert_failure(
        _json(_candidate_payload(claims=[_claim_payload()] * 13)),
        CertificateExplanationParseFailureCode.INVALID_CANDIDATE,
    )


def test_valid_json_arrays_are_intentionally_converted_to_tuples() -> None:
    candidate = parse_certificate_explanation_candidate_v1(
        _json(
            _candidate_payload(
                claims=[
                    _claim_payload(
                        text="First.",
                        citation_ids=["transcript.2", "allocation"],
                    ),
                    _claim_payload(text="Second.", citation_ids=["policy"]),
                ]
            )
        )
    )
    assert type(candidate.claims) is tuple
    assert [claim.text for claim in candidate.claims] == ["First.", "Second."]
    assert type(candidate.claims[0].citation_ids) is tuple
    assert candidate.claims[0].citation_ids == ("allocation", "transcript.2")


def test_unknown_but_syntactically_valid_citation_parses_successfully() -> None:
    candidate = parse_certificate_explanation_candidate_v1(
        _json(_candidate_payload(claims=[_claim_payload(citation_ids=["not.a.real.citation"])]))
    )
    assert candidate.claims[0].citation_ids == ("not.a.real.citation",)


def test_noncanonical_but_valid_json_has_no_canonical_byte_requirement() -> None:
    candidate = parse_certificate_explanation_candidate_v1(_json(indent=2) + "\n")
    assert candidate.claims[0].citation_ids == ("allocation",)
