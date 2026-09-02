import json
import sys

import pytest

from clear_market.ai import (
    MerchantOfferProposalDecision,
    MerchantOfferProposalParseError,
    MerchantOfferProposalParseFailureCode,
    parse_merchant_offer_proposal_v1,
)
from clear_market.ai.merchant_offer import MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES
from clear_market.commerce.merchant import MAX_OFFER_LINES


def _sku_id(index: int) -> str:
    return f"49000000-0000-4000-8000-{index:012x}"


def _line_payload(index: int = 1, **changes: object) -> dict[str, object]:
    return {
        "schema_version": "1",
        "merchant_offer_proposal_line_version": "merchant-offer-proposal-line-v1",
        "sku_id": _sku_id(index),
        "proposed_quantity": 5,
        "proposed_unit_price_paise": 500,
        **changes,
    }


def _proposal_payload(**changes: object) -> dict[str, object]:
    return {
        "schema_version": "1",
        "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
        "decision": "OFFER",
        "lines": [_line_payload()],
        **changes,
    }


def _valid_json(**changes: object) -> str:
    return json.dumps(_proposal_payload(**changes), ensure_ascii=False)


def _assert_parse_failure(
    output_text: str,
    expected: MerchantOfferProposalParseFailureCode,
) -> MerchantOfferProposalParseError:
    with pytest.raises(MerchantOfferProposalParseError) as caught:
        parse_merchant_offer_proposal_v1(output_text)
    assert caught.value.code is expected
    assert str(caught.value) == expected.value
    return caught.value


class _StringSubclass(str):
    pass


def test_parse_failure_contract_is_exact_and_read_only() -> None:
    assert tuple(MerchantOfferProposalParseFailureCode) == (
        MerchantOfferProposalParseFailureCode.INPUT_TOO_LARGE,
        MerchantOfferProposalParseFailureCode.INVALID_TEXT,
        MerchantOfferProposalParseFailureCode.INVALID_JSON,
        MerchantOfferProposalParseFailureCode.DUPLICATE_KEY,
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    error = MerchantOfferProposalParseError(MerchantOfferProposalParseFailureCode.INVALID_JSON)
    assert str(error) == "invalid_json"
    with pytest.raises(AttributeError):
        error.code = MerchantOfferProposalParseFailureCode.INVALID_TEXT


@pytest.mark.parametrize("wrong", [b"{}", {}, None, 1, _StringSubclass("{}")])
def test_parser_requires_exact_builtin_string(wrong: object) -> None:
    with pytest.raises(TypeError):
        parse_merchant_offer_proposal_v1(wrong)  # type: ignore[arg-type]


def test_parser_rejects_nul_and_lone_surrogate_as_invalid_text() -> None:
    _assert_parse_failure(
        _valid_json() + "\x00",
        MerchantOfferProposalParseFailureCode.INVALID_TEXT,
    )
    _assert_parse_failure("\ud800", MerchantOfferProposalParseFailureCode.INVALID_TEXT)


def test_parser_byte_ceiling_is_inclusive_before_json_validation() -> None:
    exact = "x" * MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES
    one_over = exact + "x"
    assert len(exact.encode("utf-8")) == MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES
    _assert_parse_failure(exact, MerchantOfferProposalParseFailureCode.INVALID_JSON)
    _assert_parse_failure(one_over, MerchantOfferProposalParseFailureCode.INPUT_TOO_LARGE)


@pytest.mark.parametrize(
    "output_text",
    [
        "",
        "{",
        "[",
        '{"schema_version":',
        _valid_json() + " trailing prose",
        "```json\n" + _valid_json() + "\n```",
    ],
)
def test_parser_rejects_malformed_truncated_trailing_or_fenced_json(output_text: str) -> None:
    _assert_parse_failure(output_text, MerchantOfferProposalParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parser_rejects_nonstandard_json_constants(constant: str) -> None:
    _assert_parse_failure(
        '{"value":' + constant + "}",
        MerchantOfferProposalParseFailureCode.INVALID_JSON,
    )


def test_parser_maps_protected_integer_value_error_to_invalid_json() -> None:
    digit_limit = sys.get_int_max_str_digits()
    assert digit_limit > 0
    output_text = '{"value":' + ("9" * (digit_limit + 1)) + "}"
    assert len(output_text.encode("utf-8")) < MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES
    with pytest.raises(ValueError) as direct_error:
        json.loads(output_text)
    assert type(direct_error.value) is ValueError
    _assert_parse_failure(output_text, MerchantOfferProposalParseFailureCode.INVALID_JSON)


def test_parser_maps_decoder_recursion_to_invalid_json() -> None:
    output_text = "[" * 10_000 + "]" * 10_000
    assert len(output_text.encode("utf-8")) < MAX_MERCHANT_OFFER_PROPOSAL_JSON_BYTES
    _assert_parse_failure(output_text, MerchantOfferProposalParseFailureCode.INVALID_JSON)


def test_parser_rejects_duplicate_root_and_nested_line_keys() -> None:
    root_duplicate = (
        '{"schema_version":"1","schema_version":"1",'
        '"merchant_offer_proposal_version":"merchant-offer-proposal-v1",'
        '"decision":"NO_OFFER","lines":[]}'
    )
    nested_duplicate = (
        '{"schema_version":"1",'
        '"merchant_offer_proposal_version":"merchant-offer-proposal-v1",'
        '"decision":"OFFER","lines":[{'
        '"schema_version":"1",'
        '"merchant_offer_proposal_line_version":"merchant-offer-proposal-line-v1",'
        f'"sku_id":"{_sku_id(1)}","proposed_quantity":5,'
        '"proposed_quantity":5,"proposed_unit_price_paise":500}]}'
    )
    _assert_parse_failure(root_duplicate, MerchantOfferProposalParseFailureCode.DUPLICATE_KEY)
    _assert_parse_failure(nested_duplicate, MerchantOfferProposalParseFailureCode.DUPLICATE_KEY)


@pytest.mark.parametrize("output_text", ["[]", "null", '"text"', "1", "true"])
def test_parser_rejects_non_object_root(output_text: str) -> None:
    _assert_parse_failure(output_text, MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL)


@pytest.mark.parametrize("missing", ["decision", "lines"])
def test_parser_rejects_missing_required_field(missing: str) -> None:
    payload = _proposal_payload()
    del payload[missing]
    _assert_parse_failure(
        json.dumps(payload), MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL
    )


def test_parser_rejects_extra_root_and_line_fields() -> None:
    _assert_parse_failure(
        _valid_json(rationale="safe"),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    _assert_parse_failure(
        _valid_json(lines=[_line_payload(attributes=[])]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )


def test_parser_rejects_invalid_versions_decision_and_uuid() -> None:
    _assert_parse_failure(
        _valid_json(merchant_offer_proposal_version="merchant-offer-proposal-v2"),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    _assert_parse_failure(
        _valid_json(lines=[_line_payload(merchant_offer_proposal_line_version="bad")]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    _assert_parse_failure(
        _valid_json(decision="MAYBE"),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    _assert_parse_failure(
        _valid_json(lines=[_line_payload(sku_id="not-a-uuid")]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )


@pytest.mark.parametrize("field", ["proposed_quantity", "proposed_unit_price_paise"])
@pytest.mark.parametrize("value", [1.5, True, "5"])
def test_parser_does_not_coerce_quantity_or_price(field: str, value: object) -> None:
    _assert_parse_failure(
        _valid_json(lines=[_line_payload(**{field: value})]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )


def test_parser_rejects_duplicate_skus_and_line_bound() -> None:
    _assert_parse_failure(
        _valid_json(lines=[_line_payload(), _line_payload()]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    lines = [_line_payload(index) for index in range(1, MAX_OFFER_LINES + 2)]
    _assert_parse_failure(
        _valid_json(lines=lines),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )


def test_parser_enforces_offer_and_no_offer_line_semantics() -> None:
    _assert_parse_failure(
        _valid_json(lines=[]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )
    _assert_parse_failure(
        _valid_json(decision="NO_OFFER", lines=[_line_payload()]),
        MerchantOfferProposalParseFailureCode.INVALID_PROPOSAL,
    )


def test_parser_accepts_valid_offer_and_no_offer() -> None:
    offer = parse_merchant_offer_proposal_v1(
        _valid_json(lines=[_line_payload(2), _line_payload(1)])
    )
    assert offer.decision is MerchantOfferProposalDecision.OFFER
    assert tuple(line.sku_id for line in offer.lines) == (_sku_id(1), _sku_id(2))

    no_offer = parse_merchant_offer_proposal_v1(_valid_json(decision="NO_OFFER", lines=[]))
    assert no_offer.decision is MerchantOfferProposalDecision.NO_OFFER
    assert no_offer.lines == ()


def test_parser_accepts_noncanonical_whitespace_and_key_order() -> None:
    payload = _proposal_payload()
    reversed_payload = dict(reversed(tuple(payload.items())))
    proposal = parse_merchant_offer_proposal_v1(json.dumps(reversed_payload, indent=2))
    assert proposal.decision is MerchantOfferProposalDecision.OFFER
    assert proposal.lines[0].proposed_unit_price_paise == 500


def test_duplicate_key_precedes_invalid_proposal_schema() -> None:
    _assert_parse_failure(
        '{"unknown":1,"unknown":2}',
        MerchantOfferProposalParseFailureCode.DUPLICATE_KEY,
    )
