import json
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from pydantic import ValidationError

from clear_market.ai import (
    BUYER_INTENT_CANDIDATE_V1_VERSION,
    BUYER_INTENT_INSTRUCTION_V1_VERSION,
    BUYER_INTENT_RULE_CANDIDATE_V1_VERSION,
    BUYER_POLICY_FREEZE_CONTEXT_V1_VERSION,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderResponseV1,
    AIProviderTask,
    BuyerIntentCandidateV1,
    BuyerIntentFreezeError,
    BuyerIntentFreezeErrorCode,
    BuyerIntentParseError,
    BuyerIntentParseFailureCode,
    BuyerIntentRuleCandidateV1,
    BuyerPolicyFreezeContextV1,
    freeze_buyer_policy_v2,
    interpret_buyer_intent_v1,
)
from clear_market.ai.buyer_intent import (
    MAX_BUYER_INTENT_JSON_BYTES,
    MAX_BUYER_INTENT_RULES_PER_KIND,
    MAX_BUYER_INTENT_STRING_VALUE_BYTES,
)
from clear_market.commerce import (
    AttributeValueType,
    ComparisonOperator,
    HardConstraint,
    ProvenanceLabel,
    SoftPreference,
)
from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, MAX_SELLERS, MIN_SELLERS

_REQUEST_ID = "91000000-0000-4000-8000-000000000001"
_MARKET_ID = "92000000-0000-4000-8000-000000000001"
_BUYER_ID = "92000000-0000-4000-8000-000000000002"
_HARD_ID = "93000000-0000-4000-8000-000000000001"
_OTHER_HARD_ID = "93000000-0000-4000-8000-000000000002"
_SOFT_ID = "93000000-0000-4000-8000-000000000003"
_OTHER_SOFT_ID = "93000000-0000-4000-8000-000000000004"
_DEADLINE = datetime(2027, 3, 4, 12, 0, 0, 123_456, tzinfo=UTC)


def _merchant_id(index: int) -> str:
    return f"94000000-0000-4000-8000-{index:012x}"


def _rule(
    rule_id: str = _HARD_ID,
    *,
    attribute_key: object = "ram_gb",
    operator: object = ComparisonOperator.GTE,
    value_type: object = AttributeValueType.INTEGER,
    value: object = 16,
    allowed_provenance: object = (
        ProvenanceLabel.VERIFIED,
        ProvenanceLabel.ATTESTED,
    ),
    **extra: object,
) -> BuyerIntentRuleCandidateV1:
    values: dict[str, object] = {
        "rule_id": rule_id,
        "attribute_key": attribute_key,
        "operator": operator,
        "value_type": value_type,
        "value": value,
        "allowed_provenance": allowed_provenance,
        **extra,
    }
    return BuyerIntentRuleCandidateV1(**values)


def _soft_rule(
    rule_id: str = _SOFT_ID,
    *,
    allowed_provenance: object = (ProvenanceLabel.CLAIMED,),
) -> BuyerIntentRuleCandidateV1:
    return _rule(
        rule_id,
        attribute_key="brand",
        operator=ComparisonOperator.EQ,
        value_type=AttributeValueType.STRING,
        value="clear",
        allowed_provenance=allowed_provenance,
    )


def _candidate(**changes: object) -> BuyerIntentCandidateV1:
    values: dict[str, object] = {
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 6,
        "max_winners": 2,
        "max_total_payment_paise": 500_000,
        "hard_constraints": (_rule(),),
        "soft_preferences": (_soft_rule(),),
        **changes,
    }
    return BuyerIntentCandidateV1(**values)


def _context(**changes: object) -> BuyerPolicyFreezeContextV1:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_id": _BUYER_ID,
        "eligible_merchant_ids": (_merchant_id(3), _merchant_id(1), _merchant_id(2)),
        "offer_deadline": _DEADLINE,
        "mechanism_version": "heterogeneous-mechanism-test-v1",
        "objective_version": "heterogeneous-objective-test-v1",
        **changes,
    }
    return BuyerPolicyFreezeContextV1(**values)


def _construct_rule(**changes: object) -> BuyerIntentRuleCandidateV1:
    valid = _rule()
    values = {field: getattr(valid, field) for field in BuyerIntentRuleCandidateV1.model_fields}
    values.update(changes)
    return BuyerIntentRuleCandidateV1.model_construct(**values)


def _construct_candidate(**changes: object) -> BuyerIntentCandidateV1:
    valid = _candidate()
    values = {field: getattr(valid, field) for field in BuyerIntentCandidateV1.model_fields}
    values.update(changes)
    return BuyerIntentCandidateV1.model_construct(**values)


def _construct_context(**changes: object) -> BuyerPolicyFreezeContextV1:
    valid = _context()
    values = {field: getattr(valid, field) for field in BuyerPolicyFreezeContextV1.model_fields}
    values.update(changes)
    return BuyerPolicyFreezeContextV1.model_construct(**values)


def _candidate_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1",
        "buyer_intent_candidate_version": "buyer-intent-candidate-v1",
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 6,
        "max_winners": 2,
        "max_total_payment_paise": 500_000,
        "hard_constraints": [
            {
                "schema_version": "1",
                "buyer_intent_rule_candidate_version": "buyer-intent-rule-candidate-v1",
                "rule_id": _HARD_ID,
                "attribute_key": "ram_gb",
                "operator": "gte",
                "value_type": "integer",
                "value": 16,
                "allowed_provenance": ["VERIFIED", "ATTESTED"],
            }
        ],
        "soft_preferences": [
            {
                "schema_version": "1",
                "buyer_intent_rule_candidate_version": "buyer-intent-rule-candidate-v1",
                "rule_id": _SOFT_ID,
                "attribute_key": "brand",
                "operator": "eq",
                "value_type": "string",
                "value": "clear",
                "allowed_provenance": ["CLAIMED"],
            }
        ],
        **changes,
    }
    return payload


class _StaticProvider:
    def __init__(
        self,
        output_text: str,
        *,
        finish_reason: AIProviderFinishReason = AIProviderFinishReason.COMPLETED,
    ) -> None:
        self.output_text = output_text
        self.finish_reason = finish_reason
        self.requests: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        self.requests.append(request)
        return AIProviderResponseV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            finish_reason=self.finish_reason,
            output_text=self.output_text,
        )


class _ErrorProvider:
    def __init__(self, error: AIProviderError) -> None:
        self.error = error
        self.requests: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        self.requests.append(request)
        raise self.error


class _ContextSubclass(BuyerPolicyFreezeContextV1):
    pass


class _CandidateSubclass(BuyerIntentCandidateV1):
    pass


def _assert_freeze_error(
    code: BuyerIntentFreezeErrorCode,
    *,
    context: BuyerPolicyFreezeContextV1,
    candidate: BuyerIntentCandidateV1,
) -> BuyerIntentFreezeError:
    with pytest.raises(BuyerIntentFreezeError) as caught:
        freeze_buyer_policy_v2(context=context, candidate=candidate)
    assert caught.value.code is code
    assert str(caught.value) == code.value
    return caught.value


def test_buyer_intent_versions_are_exact() -> None:
    assert BUYER_INTENT_RULE_CANDIDATE_V1_VERSION == "buyer-intent-rule-candidate-v1"
    assert BUYER_INTENT_CANDIDATE_V1_VERSION == "buyer-intent-candidate-v1"
    assert BUYER_POLICY_FREEZE_CONTEXT_V1_VERSION == "buyer-policy-freeze-context-v1"
    assert BUYER_INTENT_INSTRUCTION_V1_VERSION == "buyer-intent-instruction-v1"


def test_freeze_error_contract_is_exact_and_read_only() -> None:
    assert tuple(BuyerIntentFreezeErrorCode) == (
        BuyerIntentFreezeErrorCode.INVALID_CONTEXT,
        BuyerIntentFreezeErrorCode.INVALID_CANDIDATE,
        BuyerIntentFreezeErrorCode.MAX_WINNERS_EXCEEDS_ELIGIBLE_MERCHANTS,
    )
    error = BuyerIntentFreezeError(BuyerIntentFreezeErrorCode.INVALID_CONTEXT)
    assert str(error) == "INVALID_CONTEXT"
    with pytest.raises(AttributeError):
        error.code = BuyerIntentFreezeErrorCode.INVALID_CANDIDATE


def test_rule_candidate_has_exact_fields_versions_and_config() -> None:
    rule = _rule()

    assert tuple(BuyerIntentRuleCandidateV1.model_fields) == (
        "schema_version",
        "buyer_intent_rule_candidate_version",
        "rule_id",
        "attribute_key",
        "operator",
        "value_type",
        "value",
        "allowed_provenance",
    )
    assert rule.schema_version == "1"
    assert rule.buyer_intent_rule_candidate_version == "buyer-intent-rule-candidate-v1"
    assert rule.rule_id == _HARD_ID
    assert BuyerIntentRuleCandidateV1.model_config["frozen"] is True
    assert BuyerIntentRuleCandidateV1.model_config["extra"] == "forbid"
    assert BuyerIntentRuleCandidateV1.model_config["strict"] is True
    assert BuyerIntentRuleCandidateV1.model_config["revalidate_instances"] == "always"


@pytest.mark.parametrize("operator", tuple(ComparisonOperator))
def test_rule_candidate_accepts_every_operator_with_compatible_value(
    operator: ComparisonOperator,
) -> None:
    rule = _rule(operator=operator)
    assert rule.operator is operator


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, ""),
        (AttributeValueType.STRING, "café"),
        (AttributeValueType.INTEGER, 0),
        (AttributeValueType.BOOLEAN, True),
        (AttributeValueType.BOOLEAN, False),
    ],
)
def test_rule_candidate_accepts_exact_scalar_types(
    value_type: AttributeValueType,
    value: str | int | bool,
) -> None:
    rule = _rule(
        operator=ComparisonOperator.EQ,
        value_type=value_type,
        value=value,
    )
    assert type(rule.value) is type(value)
    assert rule.value == value


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, 1),
        (AttributeValueType.STRING, True),
        (AttributeValueType.INTEGER, "1"),
        (AttributeValueType.INTEGER, True),
        (AttributeValueType.BOOLEAN, 1),
        (AttributeValueType.BOOLEAN, "true"),
        (AttributeValueType.INTEGER, 1.0),
        (AttributeValueType.STRING, b"value"),
        (AttributeValueType.STRING, None),
        (AttributeValueType.STRING, []),
    ],
)
def test_rule_candidate_rejects_wrong_or_coercive_scalar_type(
    value_type: AttributeValueType,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _rule(operator=ComparisonOperator.EQ, value_type=value_type, value=value)


@pytest.mark.parametrize(
    "operator",
    [
        ComparisonOperator.LT,
        ComparisonOperator.LTE,
        ComparisonOperator.GT,
        ComparisonOperator.GTE,
    ],
)
@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, "16"),
        (AttributeValueType.BOOLEAN, True),
    ],
)
def test_ordered_rule_candidate_requires_integer(
    operator: ComparisonOperator,
    value_type: AttributeValueType,
    value: str | bool,
) -> None:
    with pytest.raises(ValidationError):
        _rule(operator=operator, value_type=value_type, value=value)


def test_rule_string_utf8_bound_is_exact_and_preserves_input() -> None:
    exact = "é" * (MAX_BUYER_INTENT_STRING_VALUE_BYTES // 2)
    rule = _rule(
        operator=ComparisonOperator.EQ,
        value_type=AttributeValueType.STRING,
        value=exact,
    )
    assert rule.value == exact
    assert len(cast(str, rule.value).encode("utf-8")) == MAX_BUYER_INTENT_STRING_VALUE_BYTES

    with pytest.raises(ValidationError):
        _rule(
            operator=ComparisonOperator.EQ,
            value_type=AttributeValueType.STRING,
            value=exact + "a",
        )


@pytest.mark.parametrize("value", ["before\x00after", "\ud800"])
def test_rule_string_rejects_nul_or_lone_surrogate(value: str) -> None:
    with pytest.raises(ValidationError):
        _rule(
            operator=ComparisonOperator.EQ,
            value_type=AttributeValueType.STRING,
            value=value,
        )


def test_rule_requires_canonical_attribute_key_and_uuid4() -> None:
    with pytest.raises(ValidationError):
        _rule(attribute_key="RAM GB")
    with pytest.raises(ValidationError):
        _rule("not-a-uuid")


@pytest.mark.parametrize("allowed", [[], (), "VERIFIED", None])
def test_rule_allowed_provenance_requires_nonempty_exact_tuple(allowed: object) -> None:
    with pytest.raises(ValidationError):
        _rule(allowed_provenance=allowed)


def test_rule_rejects_duplicate_and_normalizes_unique_provenance() -> None:
    with pytest.raises(ValidationError):
        _rule(allowed_provenance=(ProvenanceLabel.VERIFIED, ProvenanceLabel.VERIFIED))

    rule = _rule(
        allowed_provenance=(
            ProvenanceLabel.VERIFIED,
            ProvenanceLabel.CLAIMED,
            ProvenanceLabel.ATTESTED,
        )
    )
    assert rule.allowed_provenance == (
        ProvenanceLabel.ATTESTED,
        ProvenanceLabel.CLAIMED,
        ProvenanceLabel.VERIFIED,
    )


def test_rule_candidate_is_frozen_and_forbids_extras_and_wrong_versions() -> None:
    rule = _rule()
    with pytest.raises(ValidationError):
        rule.value = 32
    with pytest.raises(ValidationError):
        _rule(weight=1)
    with pytest.raises(ValidationError):
        _rule(schema_version="2")
    with pytest.raises(ValidationError):
        _rule(buyer_intent_rule_candidate_version="buyer-intent-rule-candidate-v2")


def test_candidate_has_exact_fields_versions_and_config() -> None:
    candidate = _candidate()
    assert tuple(BuyerIntentCandidateV1.model_fields) == (
        "schema_version",
        "buyer_intent_candidate_version",
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "max_total_payment_paise",
        "hard_constraints",
        "soft_preferences",
    )
    assert candidate.schema_version == "1"
    assert candidate.buyer_intent_candidate_version == "buyer-intent-candidate-v1"
    assert BuyerIntentCandidateV1.model_config["frozen"] is True
    assert BuyerIntentCandidateV1.model_config["extra"] == "forbid"
    assert BuyerIntentCandidateV1.model_config["strict"] is True
    assert BuyerIntentCandidateV1.model_config["revalidate_instances"] == "always"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_quantity", True),
        ("requested_quantity", 1.0),
        ("requested_quantity", "1"),
        ("minimum_acceptable_quantity", False),
        ("minimum_acceptable_quantity", 1.0),
        ("minimum_acceptable_quantity", "1"),
        ("max_winners", True),
        ("max_winners", 1.0),
        ("max_winners", "1"),
        ("max_total_payment_paise", True),
        ("max_total_payment_paise", 1.0),
        ("max_total_payment_paise", "1"),
    ],
)
def test_candidate_numeric_fields_are_strict(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _candidate(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_quantity", 0),
        ("requested_quantity", MAX_QUANTITY + 1),
        ("minimum_acceptable_quantity", 0),
        ("max_winners", 0),
        ("max_winners", MAX_SELLERS + 1),
        ("max_total_payment_paise", -1),
        ("max_total_payment_paise", MAX_MONEY_PAISE + 1),
    ],
)
def test_candidate_numeric_fields_enforce_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        _candidate(**{field: value})


def test_candidate_accepts_numeric_boundaries() -> None:
    candidate = _candidate(
        requested_quantity=MAX_QUANTITY,
        minimum_acceptable_quantity=1,
        max_winners=MAX_SELLERS,
        max_total_payment_paise=MAX_MONEY_PAISE,
    )
    assert candidate.requested_quantity == MAX_QUANTITY
    assert candidate.max_total_payment_paise == MAX_MONEY_PAISE


@pytest.mark.parametrize("field", ["hard_constraints", "soft_preferences"])
def test_candidate_requires_exact_rule_tuples(field: str) -> None:
    rules = [_rule()] if field == "hard_constraints" else [_soft_rule()]
    with pytest.raises(ValidationError):
        _candidate(**{field: rules})


def test_candidate_allows_explicit_empty_rule_collections() -> None:
    candidate = _candidate(hard_constraints=(), soft_preferences=())
    assert candidate.hard_constraints == ()
    assert candidate.soft_preferences == ()


@pytest.mark.parametrize("field", ["hard_constraints", "soft_preferences"])
def test_candidate_rejects_more_than_64_rules_per_kind(field: str) -> None:
    rules = tuple(
        _rule(
            f"95000000-0000-4000-8000-{index:012x}",
            operator=ComparisonOperator.EQ,
        )
        for index in range(MAX_BUYER_INTENT_RULES_PER_KIND + 1)
    )
    with pytest.raises(ValidationError):
        _candidate(**{field: rules})


@pytest.mark.parametrize("field", ["hard_constraints", "soft_preferences"])
def test_candidate_rejects_duplicate_ids_within_each_collection(field: str) -> None:
    rule = _rule() if field == "hard_constraints" else _soft_rule()
    with pytest.raises(ValidationError):
        _candidate(**{field: (rule, rule)})


def test_candidate_rejects_hard_soft_rule_id_collision() -> None:
    with pytest.raises(ValidationError):
        _candidate(soft_preferences=(_soft_rule(_HARD_ID),))


def test_candidate_normalizes_each_rule_collection_by_id() -> None:
    candidate = _candidate(
        hard_constraints=(_rule(_OTHER_HARD_ID), _rule(_HARD_ID)),
        soft_preferences=(_soft_rule(_OTHER_SOFT_ID), _soft_rule(_SOFT_ID)),
    )
    assert tuple(rule.rule_id for rule in candidate.hard_constraints) == (
        _HARD_ID,
        _OTHER_HARD_ID,
    )
    assert tuple(rule.rule_id for rule in candidate.soft_preferences) == (
        _SOFT_ID,
        _OTHER_SOFT_ID,
    )


def test_candidate_rejects_invalid_quantity_relationships() -> None:
    with pytest.raises(ValidationError):
        _candidate(requested_quantity=10, minimum_acceptable_quantity=11)
    with pytest.raises(ValidationError):
        _candidate(requested_quantity=2, minimum_acceptable_quantity=1, max_winners=3)


def test_predicted_provenance_is_rejected_for_hard_and_allowed_for_soft() -> None:
    predicted = (ProvenanceLabel.PREDICTED,)
    with pytest.raises(ValidationError):
        _candidate(hard_constraints=(_rule(allowed_provenance=predicted),))

    candidate = _candidate(soft_preferences=(_soft_rule(allowed_provenance=predicted),))
    assert candidate.soft_preferences[0].allowed_provenance == predicted


def test_candidate_is_frozen_forbids_extras_and_requires_exact_versions() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError):
        candidate.max_winners = 1
    with pytest.raises(ValidationError):
        _candidate(market_id=_MARKET_ID)
    with pytest.raises(ValidationError):
        _candidate(schema_version="2")
    with pytest.raises(ValidationError):
        _candidate(buyer_intent_candidate_version="buyer-intent-candidate-v2")


def test_freeze_context_has_exact_fields_versions_and_config() -> None:
    context = _context()
    assert tuple(BuyerPolicyFreezeContextV1.model_fields) == (
        "schema_version",
        "buyer_policy_freeze_context_version",
        "market_id",
        "buyer_id",
        "eligible_merchant_ids",
        "offer_deadline",
        "mechanism_version",
        "objective_version",
    )
    assert context.schema_version == "1"
    assert context.buyer_policy_freeze_context_version == "buyer-policy-freeze-context-v1"
    assert BuyerPolicyFreezeContextV1.model_config["frozen"] is True
    assert BuyerPolicyFreezeContextV1.model_config["extra"] == "forbid"
    assert BuyerPolicyFreezeContextV1.model_config["strict"] is True
    assert BuyerPolicyFreezeContextV1.model_config["revalidate_instances"] == "always"


def test_freeze_context_contains_only_trusted_market_fields() -> None:
    assert set(BuyerPolicyFreezeContextV1.model_fields).isdisjoint(
        {
            "provider_name",
            "model",
            "input_text",
            "candidate",
            "winner",
            "payment",
            "merchant_fact_provenance",
        }
    )


@pytest.mark.parametrize("count", [MIN_SELLERS, MAX_SELLERS])
def test_freeze_context_accepts_merchant_population_bounds(count: int) -> None:
    context = _context(eligible_merchant_ids=tuple(_merchant_id(i) for i in range(count)))
    assert len(context.eligible_merchant_ids) == count


@pytest.mark.parametrize("count", [MIN_SELLERS - 1, MAX_SELLERS + 1])
def test_freeze_context_rejects_invalid_merchant_population(count: int) -> None:
    with pytest.raises(ValidationError):
        _context(eligible_merchant_ids=tuple(_merchant_id(i) for i in range(count)))


def test_freeze_context_requires_tuple_rejects_duplicates_and_sorts() -> None:
    with pytest.raises(ValidationError):
        _context(eligible_merchant_ids=[_merchant_id(1), _merchant_id(2)])
    with pytest.raises(ValidationError):
        _context(eligible_merchant_ids=(_merchant_id(1), _merchant_id(1)))
    assert _context().eligible_merchant_ids == (
        _merchant_id(1),
        _merchant_id(2),
        _merchant_id(3),
    )


def test_freeze_context_requires_canonical_ids_and_normalizes_aware_deadline_to_utc() -> None:
    with pytest.raises(ValidationError):
        _context(market_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _context(buyer_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _context(offer_deadline=datetime(2027, 3, 4, 12, 0))

    offset_deadline = datetime(
        2027,
        3,
        4,
        17,
        30,
        0,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    assert _context(offer_deadline=offset_deadline).offer_deadline == _DEADLINE


@pytest.mark.parametrize(
    "identifier",
    ["a", "mechanism-v1", "objective.v1", "market_v2", "a" + "0" * 127],
)
@pytest.mark.parametrize("field", ["mechanism_version", "objective_version"])
def test_freeze_context_accepts_canonical_versions(identifier: str, field: str) -> None:
    assert getattr(_context(**{field: identifier}), field) == identifier


@pytest.mark.parametrize(
    "identifier",
    ["", "Version", ".version", " version", "version ", "version/x", "vérsion", "a" + "0" * 128, 1],
)
@pytest.mark.parametrize("field", ["mechanism_version", "objective_version"])
def test_freeze_context_rejects_noncanonical_versions(identifier: object, field: str) -> None:
    with pytest.raises(ValidationError):
        _context(**{field: identifier})


def test_freeze_context_is_frozen_forbids_extras_and_versions_are_exact() -> None:
    context = _context()
    with pytest.raises(ValidationError):
        context.objective_version = "changed-v1"
    with pytest.raises(ValidationError):
        _context(provider_name="provider")
    with pytest.raises(ValidationError):
        _context(schema_version="2")
    with pytest.raises(ValidationError):
        _context(buyer_policy_freeze_context_version="buyer-policy-freeze-context-v2")


def test_freeze_maps_trusted_context_and_candidate_exactly() -> None:
    hard_a = _rule(_HARD_ID)
    hard_b = _rule(
        _OTHER_HARD_ID,
        attribute_key="refurbished",
        operator=ComparisonOperator.EQ,
        value_type=AttributeValueType.BOOLEAN,
        value=False,
        allowed_provenance=(ProvenanceLabel.ATTESTED,),
    )
    soft_a = _soft_rule(_SOFT_ID, allowed_provenance=(ProvenanceLabel.PREDICTED,))
    soft_b = _rule(
        _OTHER_SOFT_ID,
        attribute_key="delivery.days",
        operator=ComparisonOperator.LTE,
        value_type=AttributeValueType.INTEGER,
        value=3,
        allowed_provenance=(ProvenanceLabel.DERIVED,),
    )
    candidate = _candidate(
        hard_constraints=(hard_b, hard_a),
        soft_preferences=(soft_b, soft_a),
    )
    context = _context()

    policy = freeze_buyer_policy_v2(context=context, candidate=candidate)

    assert policy.market_spec.market_id == context.market_id
    assert policy.market_spec.buyer_id == context.buyer_id
    assert policy.eligible_merchant_ids == context.eligible_merchant_ids
    assert policy.offer_deadline == context.offer_deadline
    assert policy.mechanism_version == context.mechanism_version
    assert policy.objective_version == context.objective_version
    assert policy.market_spec.requested_quantity == candidate.requested_quantity
    assert policy.market_spec.minimum_acceptable_quantity == candidate.minimum_acceptable_quantity
    assert policy.market_spec.max_winners == candidate.max_winners
    assert policy.max_total_payment.amount_paise == candidate.max_total_payment_paise
    assert tuple(type(rule) for rule in policy.market_spec.hard_constraints) == (
        HardConstraint,
        HardConstraint,
    )
    assert tuple(type(rule) for rule in policy.market_spec.soft_preferences) == (
        SoftPreference,
        SoftPreference,
    )
    assert tuple(rule.constraint_id for rule in policy.market_spec.hard_constraints) == (
        _HARD_ID,
        _OTHER_HARD_ID,
    )
    assert tuple(rule.preference_id for rule in policy.market_spec.soft_preferences) == (
        _SOFT_ID,
        _OTHER_SOFT_ID,
    )
    assert policy.market_spec.hard_constraints[1].operand.value is False
    assert policy.market_spec.soft_preferences[1].operand.value == 3
    assert policy.market_spec.soft_preferences[0].allowed_provenance == (ProvenanceLabel.PREDICTED,)


def test_reordered_candidate_inputs_freeze_to_equal_policy() -> None:
    hard = (_rule(_HARD_ID), _rule(_OTHER_HARD_ID))
    soft = (_soft_rule(_SOFT_ID), _soft_rule(_OTHER_SOFT_ID))
    forward = _candidate(hard_constraints=hard, soft_preferences=soft)
    reverse = _candidate(
        hard_constraints=tuple(reversed(hard)),
        soft_preferences=tuple(reversed(soft)),
    )
    assert freeze_buyer_policy_v2(context=_context(), candidate=forward) == freeze_buyer_policy_v2(
        context=_context(), candidate=reverse
    )


@pytest.mark.parametrize(
    "invalid_context",
    [
        _construct_context(mechanism_version="Invalid"),
        _construct_context(eligible_merchant_ids=(_merchant_id(1), _merchant_id(1))),
    ],
)
def test_freeze_revalidates_model_construct_context(
    invalid_context: BuyerPolicyFreezeContextV1,
) -> None:
    _assert_freeze_error(
        BuyerIntentFreezeErrorCode.INVALID_CONTEXT,
        context=invalid_context,
        candidate=_candidate(),
    )


def test_freeze_revalidates_model_construct_candidate_relationship() -> None:
    candidate = _construct_candidate(minimum_acceptable_quantity=11)
    _assert_freeze_error(
        BuyerIntentFreezeErrorCode.INVALID_CANDIDATE,
        context=_context(),
        candidate=candidate,
    )


def test_freeze_revalidates_nested_model_construct_rule() -> None:
    predicted_rule = _construct_rule(allowed_provenance=(ProvenanceLabel.PREDICTED,))
    candidate = _construct_candidate(hard_constraints=(predicted_rule,))
    _assert_freeze_error(
        BuyerIntentFreezeErrorCode.INVALID_CANDIDATE,
        context=_context(),
        candidate=candidate,
    )


def test_freeze_revalidates_nested_scalar_type_relation() -> None:
    invalid_rule = _construct_rule(value=True)
    candidate = _construct_candidate(hard_constraints=(invalid_rule,))
    _assert_freeze_error(
        BuyerIntentFreezeErrorCode.INVALID_CANDIDATE,
        context=_context(),
        candidate=candidate,
    )


def test_freeze_rejects_more_winners_than_trusted_population_without_clamping() -> None:
    candidate = _candidate(requested_quantity=3, minimum_acceptable_quantity=1, max_winners=3)
    context = _context(eligible_merchant_ids=(_merchant_id(1), _merchant_id(2)))
    _assert_freeze_error(
        BuyerIntentFreezeErrorCode.MAX_WINNERS_EXCEEDS_ELIGIBLE_MERCHANTS,
        context=context,
        candidate=candidate,
    )


def test_freeze_requires_exact_context_and_candidate_types() -> None:
    context = _context()
    candidate = _candidate()
    context_subclass = _ContextSubclass(**context.model_dump())
    candidate_subclass = _CandidateSubclass(**candidate.model_dump())

    with pytest.raises(TypeError):
        freeze_buyer_policy_v2(context=context_subclass, candidate=candidate)
    with pytest.raises(TypeError):
        freeze_buyer_policy_v2(context=context, candidate=candidate_subclass)
    with pytest.raises(TypeError):
        freeze_buyer_policy_v2(context=cast(BuyerPolicyFreezeContextV1, {}), candidate=candidate)
    with pytest.raises(TypeError):
        freeze_buyer_policy_v2(context=context, candidate=cast(BuyerIntentCandidateV1, {}))


def test_interpretation_sends_exact_separated_provider_request_and_freezes_policy() -> None:
    buyer_text = "Need ten laptops, at least six, with 16 GB RAM."
    provider = _StaticProvider(json.dumps(_candidate_payload()))
    context = _context()

    policy = interpret_buyer_intent_v1(
        provider=provider,
        request_id=_REQUEST_ID,
        provider_name="test-provider",
        model="model.v1:test/path",
        buyer_text=buyer_text,
        freeze_context=context,
    )

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.request_id == _REQUEST_ID
    assert request.task is AIProviderTask.BUYER_INTENT
    assert request.provider_name == "test-provider"
    assert request.model == "model.v1:test/path"
    assert request.response_format is AIProviderResponseFormat.JSON_OBJECT
    assert request.input_text == buyer_text
    assert buyer_text not in request.instruction_text
    assert request.max_output_bytes == MAX_BUYER_INTENT_JSON_BYTES
    assert policy.market_spec.market_id == context.market_id
    assert policy.market_spec.buyer_id == context.buyer_id
    assert policy.max_total_payment.amount_paise == 500_000


def test_static_instruction_covers_schema_authority_and_no_guessing_policy() -> None:
    provider = _StaticProvider(json.dumps(_candidate_payload()))
    interpret_buyer_intent_v1(
        provider=provider,
        request_id=_REQUEST_ID,
        provider_name="test-provider",
        model="model-v1",
        buyer_text="buyer input",
        freeze_context=_context(),
    )
    instruction = provider.requests[0].instruction_text
    for required in (
        "exactly one JSON object",
        "no markdown",
        'schema_version "1"',
        "valid canonical UUIDv4",
        "integer INR paise",
        "hard_constraints",
        "soft_preferences",
        "eq, ne, lt, lte, gt, gte",
        "string, integer, boolean",
        "VERIFIED, ATTESTED, CLAIMED, DERIVED, PREDICTED",
        "Never include PREDICTED",
        "Never claim that a product or merchant fact is VERIFIED",
        "Do not output trusted context fields",
        "Do not invent a budget or requested quantity",
        "minimum_acceptable_quantity equal to",
        "max_winners to 1",
    ):
        assert required in instruction


@pytest.mark.parametrize(
    "code",
    [
        AIProviderErrorCode.PROVIDER_UNAVAILABLE,
        AIProviderErrorCode.PROVIDER_TIMEOUT,
        AIProviderErrorCode.PROVIDER_RATE_LIMITED,
    ],
)
def test_interpretation_propagates_provider_error_unchanged(code: AIProviderErrorCode) -> None:
    error = AIProviderError(code)
    provider = _ErrorProvider(error)
    with pytest.raises(AIProviderError) as caught:
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=_context(),
        )
    assert caught.value is error


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        (AIProviderFinishReason.MAX_OUTPUT, AIProviderErrorCode.OUTPUT_INCOMPLETE),
        (AIProviderFinishReason.REFUSED, AIProviderErrorCode.OUTPUT_REFUSED),
    ],
)
def test_interpretation_propagates_incomplete_or_refused_provider_result(
    finish_reason: AIProviderFinishReason,
    expected: AIProviderErrorCode,
) -> None:
    provider = _StaticProvider("not-json", finish_reason=finish_reason)
    with pytest.raises(AIProviderError) as caught:
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=_context(),
        )
    assert caught.value.code is expected


def test_interpretation_propagates_parse_failure() -> None:
    provider = _StaticProvider("{")
    with pytest.raises(BuyerIntentParseError) as caught:
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=_context(),
        )
    assert caught.value.code is BuyerIntentParseFailureCode.INVALID_JSON


def test_interpretation_propagates_schema_failure() -> None:
    provider = _StaticProvider("{}")
    with pytest.raises(BuyerIntentParseError) as caught:
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=_context(),
        )
    assert caught.value.code is BuyerIntentParseFailureCode.INVALID_CANDIDATE


def test_interpretation_propagates_freeze_population_failure() -> None:
    payload = _candidate_payload(
        requested_quantity=3,
        minimum_acceptable_quantity=1,
        max_winners=3,
    )
    provider = _StaticProvider(json.dumps(payload))
    context = _context(eligible_merchant_ids=(_merchant_id(1), _merchant_id(2)))
    with pytest.raises(BuyerIntentFreezeError) as caught:
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=context,
        )
    assert caught.value.code is BuyerIntentFreezeErrorCode.MAX_WINNERS_EXCEEDS_ELIGIBLE_MERCHANTS


def test_invalid_constructed_context_precedes_provider_and_provider_is_not_called() -> None:
    invalid = _construct_context(mechanism_version="Invalid")
    provider = _ErrorProvider(AIProviderError(AIProviderErrorCode.PROVIDER_TIMEOUT))

    with pytest.raises(BuyerIntentFreezeError) as caught:
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=invalid,
        )
    assert caught.value.code is BuyerIntentFreezeErrorCode.INVALID_CONTEXT
    assert provider.requests == []


def test_interpretation_requires_exact_context_type_before_provider_call() -> None:
    context = _context()
    subclass = _ContextSubclass(**context.model_dump())
    provider = _StaticProvider(json.dumps(_candidate_payload()))
    with pytest.raises(TypeError):
        interpret_buyer_intent_v1(
            provider=provider,
            request_id=_REQUEST_ID,
            provider_name="test-provider",
            model="model-v1",
            buyer_text="buyer input",
            freeze_context=subclass,
        )
    assert provider.requests == []
