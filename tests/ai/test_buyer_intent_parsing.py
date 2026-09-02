import json
import sys

import pytest

from clear_market.ai import (
    BuyerIntentParseError,
    BuyerIntentParseFailureCode,
    parse_buyer_intent_candidate_v1,
)
from clear_market.ai.buyer_intent import MAX_BUYER_INTENT_JSON_BYTES
from clear_market.commerce import AttributeValueType, ComparisonOperator, ProvenanceLabel

_HARD_ID = "93000000-0000-4000-8000-000000000001"
_SOFT_ID = "93000000-0000-4000-8000-000000000002"


def _rule_payload(
    rule_id: str = _HARD_ID,
    **changes: object,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "buyer_intent_rule_candidate_version": "buyer-intent-rule-candidate-v1",
        "rule_id": rule_id,
        "attribute_key": "ram_gb",
        "operator": "gte",
        "value_type": "integer",
        "value": 16,
        "allowed_provenance": ["VERIFIED", "ATTESTED"],
        **changes,
    }


def _candidate_payload(**changes: object) -> dict[str, object]:
    return {
        "schema_version": "1",
        "buyer_intent_candidate_version": "buyer-intent-candidate-v1",
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 6,
        "max_winners": 2,
        "max_total_payment_paise": 500_000,
        "hard_constraints": [_rule_payload()],
        "soft_preferences": [
            _rule_payload(
                _SOFT_ID,
                attribute_key="brand",
                operator="eq",
                value_type="string",
                value="clear",
                allowed_provenance=["CLAIMED"],
            )
        ],
        **changes,
    }


def _valid_json(**changes: object) -> str:
    return json.dumps(_candidate_payload(**changes), ensure_ascii=False)


def _assert_parse_failure(
    output_text: str,
    expected: BuyerIntentParseFailureCode,
) -> BuyerIntentParseError:
    with pytest.raises(BuyerIntentParseError) as caught:
        parse_buyer_intent_candidate_v1(output_text)
    assert caught.value.code is expected
    assert str(caught.value) == expected.value
    return caught.value


class _StringSubclass(str):
    pass


def test_parse_failure_contract_is_exact_and_read_only() -> None:
    assert tuple(BuyerIntentParseFailureCode) == (
        BuyerIntentParseFailureCode.INPUT_TOO_LARGE,
        BuyerIntentParseFailureCode.INVALID_TEXT,
        BuyerIntentParseFailureCode.INVALID_JSON,
        BuyerIntentParseFailureCode.DUPLICATE_KEY,
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )
    error = BuyerIntentParseError(BuyerIntentParseFailureCode.INVALID_JSON)
    assert str(error) == "invalid_json"
    with pytest.raises(AttributeError):
        error.code = BuyerIntentParseFailureCode.INVALID_TEXT


@pytest.mark.parametrize("wrong", [b"{}", {}, None, 1, _StringSubclass("{}")])
def test_parser_requires_exact_builtin_string(wrong: object) -> None:
    with pytest.raises(TypeError):
        parse_buyer_intent_candidate_v1(wrong)  # type: ignore[arg-type]


def test_parser_rejects_nul_before_json_processing() -> None:
    _assert_parse_failure(
        _valid_json() + "\x00",
        BuyerIntentParseFailureCode.INVALID_TEXT,
    )


def test_parser_rejects_lone_surrogate_as_invalid_text() -> None:
    _assert_parse_failure("\ud800", BuyerIntentParseFailureCode.INVALID_TEXT)


def test_parser_byte_ceiling_is_inclusive_before_json_validation() -> None:
    exact = "x" * MAX_BUYER_INTENT_JSON_BYTES
    one_over = exact + "x"
    assert len(exact.encode("utf-8")) == MAX_BUYER_INTENT_JSON_BYTES
    _assert_parse_failure(exact, BuyerIntentParseFailureCode.INVALID_JSON)
    _assert_parse_failure(one_over, BuyerIntentParseFailureCode.INPUT_TOO_LARGE)


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
    _assert_parse_failure(output_text, BuyerIntentParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parser_rejects_nonstandard_json_constants(constant: str) -> None:
    _assert_parse_failure(
        '{"value":' + constant + "}",
        BuyerIntentParseFailureCode.INVALID_JSON,
    )


def test_parser_maps_protected_integer_conversion_value_error_to_invalid_json() -> None:
    digit_limit = sys.get_int_max_str_digits()
    assert digit_limit > 0
    output_text = '{"value":' + ("9" * (digit_limit + 1)) + "}"
    assert len(output_text.encode("utf-8")) < MAX_BUYER_INTENT_JSON_BYTES

    with pytest.raises(ValueError) as direct_error:
        json.loads(output_text)
    assert type(direct_error.value) is ValueError

    _assert_parse_failure(output_text, BuyerIntentParseFailureCode.INVALID_JSON)


def test_parser_maps_decoder_recursion_to_invalid_json() -> None:
    output_text = "[" * 10_000 + "]" * 10_000
    assert len(output_text.encode("utf-8")) < MAX_BUYER_INTENT_JSON_BYTES
    _assert_parse_failure(output_text, BuyerIntentParseFailureCode.INVALID_JSON)


def test_parser_rejects_duplicate_root_key_before_schema_validation() -> None:
    output_text = (
        '{"schema_version":"1","schema_version":"1",'
        '"buyer_intent_candidate_version":"buyer-intent-candidate-v1"}'
    )
    _assert_parse_failure(output_text, BuyerIntentParseFailureCode.DUPLICATE_KEY)


def test_parser_rejects_duplicate_nested_rule_key() -> None:
    output_text = (
        '{"schema_version":"1",'
        '"buyer_intent_candidate_version":"buyer-intent-candidate-v1",'
        '"requested_quantity":10,"minimum_acceptable_quantity":6,"max_winners":2,'
        '"max_total_payment_paise":500000,"hard_constraints":[{'
        '"schema_version":"1",'
        '"buyer_intent_rule_candidate_version":"buyer-intent-rule-candidate-v1",'
        f'"rule_id":"{_HARD_ID}","attribute_key":"ram_gb",'
        '"attribute_key":"ram_gb","operator":"gte","value_type":"integer",'
        '"value":16,"allowed_provenance":["VERIFIED"]}],"soft_preferences":[]}'
    )
    _assert_parse_failure(output_text, BuyerIntentParseFailureCode.DUPLICATE_KEY)


@pytest.mark.parametrize("output_text", ["[]", "null", '"text"', "1", "true"])
def test_parser_rejects_non_object_root_as_invalid_candidate(output_text: str) -> None:
    _assert_parse_failure(output_text, BuyerIntentParseFailureCode.INVALID_CANDIDATE)


@pytest.mark.parametrize(
    "missing_field",
    [
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "max_total_payment_paise",
        "hard_constraints",
        "soft_preferences",
    ],
)
def test_parser_rejects_missing_candidate_field(missing_field: str) -> None:
    payload = _candidate_payload()
    del payload[missing_field]
    _assert_parse_failure(json.dumps(payload), BuyerIntentParseFailureCode.INVALID_CANDIDATE)


def test_parser_rejects_extra_candidate_field() -> None:
    _assert_parse_failure(
        _valid_json(winner="merchant"),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


def test_parser_rejects_extra_rule_field() -> None:
    _assert_parse_failure(
        _valid_json(hard_constraints=[_rule_payload(weight=1)]),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


def test_parser_rejects_wrong_candidate_or_rule_version() -> None:
    _assert_parse_failure(
        _valid_json(buyer_intent_candidate_version="buyer-intent-candidate-v2"),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )
    _assert_parse_failure(
        _valid_json(
            hard_constraints=[
                _rule_payload(buyer_intent_rule_candidate_version="buyer-intent-rule-candidate-v2")
            ]
        ),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


def test_parser_rejects_invalid_rule_uuid() -> None:
    _assert_parse_failure(
        _valid_json(hard_constraints=[_rule_payload("not-a-uuid")]),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


@pytest.mark.parametrize("field", ["requested_quantity", "minimum_acceptable_quantity"])
@pytest.mark.parametrize("value", [1.5, True, "10"])
def test_parser_does_not_coerce_quantity(field: str, value: object) -> None:
    _assert_parse_failure(
        _valid_json(**{field: value}),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


@pytest.mark.parametrize("value", [1.5, True, "500000"])
def test_parser_does_not_coerce_money(value: object) -> None:
    _assert_parse_failure(
        _valid_json(max_total_payment_paise=value),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operator", "contains"),
        ("value_type", "number"),
        ("allowed_provenance", ["TRUSTED"]),
    ],
)
def test_parser_rejects_unknown_rule_enums(field: str, value: object) -> None:
    _assert_parse_failure(
        _valid_json(hard_constraints=[_rule_payload(**{field: value})]),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("integer", True),
        ("integer", "16"),
        ("boolean", 1),
        ("string", 16),
        ("string", ["clear"]),
    ],
)
def test_parser_does_not_coerce_or_recursively_transform_rule_values(
    value_type: str,
    value: object,
) -> None:
    _assert_parse_failure(
        _valid_json(
            hard_constraints=[_rule_payload(operator="eq", value_type=value_type, value=value)]
        ),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


@pytest.mark.parametrize("value_type", ["string", "boolean"])
def test_parser_rejects_ordered_noninteger_rule(value_type: str) -> None:
    value: object = "16" if value_type == "string" else True
    _assert_parse_failure(
        _valid_json(
            hard_constraints=[_rule_payload(operator="gte", value_type=value_type, value=value)]
        ),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


def test_parser_rejects_predicted_hard_rule_but_accepts_predicted_soft_rule() -> None:
    _assert_parse_failure(
        _valid_json(hard_constraints=[_rule_payload(allowed_provenance=["PREDICTED"])]),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )

    candidate = parse_buyer_intent_candidate_v1(
        _valid_json(
            soft_preferences=[
                _rule_payload(
                    _SOFT_ID,
                    attribute_key="brand",
                    operator="eq",
                    value_type="string",
                    value="clear",
                    allowed_provenance=["PREDICTED"],
                )
            ]
        )
    )
    assert candidate.soft_preferences[0].allowed_provenance == (ProvenanceLabel.PREDICTED,)


def test_parser_rejects_duplicate_rule_id_and_cross_collection_collision() -> None:
    _assert_parse_failure(
        _valid_json(hard_constraints=[_rule_payload(), _rule_payload()]),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )
    _assert_parse_failure(
        _valid_json(soft_preferences=[_rule_payload(_HARD_ID)]),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


def test_parser_converts_only_expected_lists_and_enums() -> None:
    candidate = parse_buyer_intent_candidate_v1(_valid_json())
    assert type(candidate.hard_constraints) is tuple
    assert type(candidate.soft_preferences) is tuple
    assert type(candidate.hard_constraints[0].allowed_provenance) is tuple
    assert candidate.hard_constraints[0].operator is ComparisonOperator.GTE
    assert candidate.hard_constraints[0].value_type is AttributeValueType.INTEGER
    assert candidate.hard_constraints[0].allowed_provenance == (
        ProvenanceLabel.ATTESTED,
        ProvenanceLabel.VERIFIED,
    )


def test_parser_accepts_valid_noncanonical_whitespace_and_key_order() -> None:
    payload = _candidate_payload()
    reversed_payload = dict(reversed(tuple(payload.items())))
    output_text = json.dumps(reversed_payload, indent=2)
    candidate = parse_buyer_intent_candidate_v1(output_text)
    assert candidate.requested_quantity == 10
    assert candidate.max_total_payment_paise == 500_000


def test_parser_returns_exact_valid_candidate() -> None:
    candidate = parse_buyer_intent_candidate_v1(_valid_json())
    assert candidate.schema_version == "1"
    assert candidate.buyer_intent_candidate_version == "buyer-intent-candidate-v1"
    assert candidate.requested_quantity == 10
    assert candidate.minimum_acceptable_quantity == 6
    assert candidate.max_winners == 2
    assert candidate.max_total_payment_paise == 500_000
    assert candidate.hard_constraints[0].rule_id == _HARD_ID
    assert candidate.soft_preferences[0].rule_id == _SOFT_ID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("market_id", "92000000-0000-4000-8000-000000000001"),
        ("buyer_id", "92000000-0000-4000-8000-000000000002"),
        ("eligible_merchant_ids", ["94000000-0000-4000-8000-000000000001"]),
        ("offer_deadline", "2027-03-04T12:00:00.000000Z"),
        ("mechanism_version", "attacker-mechanism-v1"),
        ("objective_version", "attacker-objective-v1"),
    ],
)
def test_parser_rejects_every_trusted_context_injection(field: str, value: object) -> None:
    _assert_parse_failure(
        _valid_json(**{field: value}),
        BuyerIntentParseFailureCode.INVALID_CANDIDATE,
    )


def test_duplicate_key_precedes_invalid_candidate_schema() -> None:
    _assert_parse_failure(
        '{"unknown":1,"unknown":2}',
        BuyerIntentParseFailureCode.DUPLICATE_KEY,
    )


def test_valid_json_wrong_schema_maps_to_invalid_candidate() -> None:
    _assert_parse_failure("{}", BuyerIntentParseFailureCode.INVALID_CANDIDATE)
