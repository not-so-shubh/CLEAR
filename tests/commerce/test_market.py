from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from clear_market.commerce import (
    BUYER_POLICY_V2_VERSION,
    MARKET_SPEC_V2_VERSION,
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    ComparisonOperator,
    HardConstraint,
    MarketSpecV2,
    ProvenanceLabel,
    SoftPreference,
)
from clear_market.commerce.market import MAX_HARD_CONSTRAINTS, MAX_SOFT_PREFERENCES
from clear_market.domain import MAX_QUANTITY, MAX_SELLERS, MIN_SELLERS, Money

_MARKET_ID = "25000000-0000-4000-8000-000000000001"
_BUYER_ID = "26000000-0000-4000-8000-000000000001"
_HARD_ID = "27000000-0000-4000-8000-000000000001"
_OTHER_HARD_ID = "27000000-0000-4000-8000-000000000002"
_SOFT_ID = "27000000-0000-4000-8000-000000000003"
_OTHER_SOFT_ID = "27000000-0000-4000-8000-000000000004"
_DEADLINE = datetime(2027, 1, 2, 12, 0, 0, 123_456, tzinfo=UTC)


def _merchant_id(index: int) -> str:
    return f"28000000-0000-4000-8000-{index:012x}"


def _hard_constraint(
    constraint_id: str = _HARD_ID,
    *,
    attribute_key: str = "ram_gb",
) -> HardConstraint:
    return HardConstraint(
        constraint_id=constraint_id,
        attribute_key=attribute_key,
        operator=ComparisonOperator.GTE,
        operand=AttributeValue(value_type=AttributeValueType.INTEGER, value=16),
        allowed_provenance=(ProvenanceLabel.VERIFIED, ProvenanceLabel.ATTESTED),
    )


def _soft_preference(
    preference_id: str = _SOFT_ID,
    *,
    attribute_key: str = "brand",
) -> SoftPreference:
    return SoftPreference(
        preference_id=preference_id,
        attribute_key=attribute_key,
        operator=ComparisonOperator.EQ,
        operand=AttributeValue(value_type=AttributeValueType.STRING, value="clear"),
        allowed_provenance=(ProvenanceLabel.CLAIMED,),
    )


def _market(**changes: object) -> MarketSpecV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_id": _BUYER_ID,
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 6,
        "max_winners": 2,
        "hard_constraints": (_hard_constraint(),),
        "soft_preferences": (_soft_preference(),),
        **changes,
    }
    return MarketSpecV2(**values)


def _policy(**changes: object) -> BuyerPolicyV2:
    values: dict[str, object] = {
        "market_spec": _market(),
        "max_total_payment": Money(amount_paise=500_000),
        "eligible_merchant_ids": (_merchant_id(2), _merchant_id(1), _merchant_id(3)),
        "offer_deadline": _DEADLINE,
        "mechanism_version": "heterogeneous-mechanism-test-v1",
        "objective_version": "heterogeneous-objective-test-v1",
        **changes,
    }
    return BuyerPolicyV2(**values)


def test_market_versions_are_exact() -> None:
    assert MARKET_SPEC_V2_VERSION == "market-spec-v2"
    assert BUYER_POLICY_V2_VERSION == "buyer-policy-v2"


def test_market_spec_v2_has_exact_fields_and_versions() -> None:
    market = _market()

    assert market.schema_version == "2"
    assert market.market_spec_version == "market-spec-v2"
    assert tuple(MarketSpecV2.model_fields) == (
        "schema_version",
        "market_spec_version",
        "market_id",
        "buyer_id",
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "hard_constraints",
        "soft_preferences",
    )


def test_market_spec_v2_is_separate_from_v1() -> None:
    from clear_market.domain import MarketSpec

    assert MarketSpecV2 is not MarketSpec
    assert not issubclass(MarketSpecV2, MarketSpec)


def test_market_spec_accepts_valid_heterogeneous_contract() -> None:
    market = _market()

    assert market.market_id == _MARKET_ID
    assert market.buyer_id == _BUYER_ID
    assert market.requested_quantity == 10
    assert market.minimum_acceptable_quantity == 6
    assert market.max_winners == 2
    assert market.hard_constraints == (_hard_constraint(),)
    assert market.soft_preferences == (_soft_preference(),)


def test_market_spec_requires_explicit_empty_rule_collections() -> None:
    market = _market(hard_constraints=(), soft_preferences=())

    assert market.hard_constraints == ()
    assert market.soft_preferences == ()


@pytest.mark.parametrize("missing_field", ["hard_constraints", "soft_preferences"])
def test_market_spec_rejects_missing_rule_collection(missing_field: str) -> None:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_id": _BUYER_ID,
        "requested_quantity": 10,
        "minimum_acceptable_quantity": 6,
        "max_winners": 2,
        "hard_constraints": (),
        "soft_preferences": (),
    }
    del values[missing_field]

    with pytest.raises(ValidationError):
        MarketSpecV2(**values)


@pytest.mark.parametrize("requested_quantity", [1, MAX_QUANTITY])
def test_market_spec_accepts_requested_quantity_bounds(requested_quantity: int) -> None:
    market = _market(
        requested_quantity=requested_quantity,
        minimum_acceptable_quantity=1,
        max_winners=1,
    )

    assert market.requested_quantity == requested_quantity


@pytest.mark.parametrize(
    ("minimum_quantity", "requested_quantity"),
    [(1, 10), (MAX_QUANTITY, MAX_QUANTITY)],
)
def test_market_spec_accepts_minimum_quantity_bounds(
    minimum_quantity: int,
    requested_quantity: int,
) -> None:
    market = _market(
        requested_quantity=requested_quantity,
        minimum_acceptable_quantity=minimum_quantity,
    )

    assert market.minimum_acceptable_quantity == minimum_quantity


def test_market_spec_rejects_minimum_quantity_above_requested() -> None:
    with pytest.raises(ValidationError):
        _market(requested_quantity=10, minimum_acceptable_quantity=11)


def test_market_spec_full_fulfillment_is_expressed_by_equal_quantity_bounds() -> None:
    market = _market(requested_quantity=10, minimum_acceptable_quantity=10)

    assert market.minimum_acceptable_quantity == market.requested_quantity


def test_market_spec_partial_fulfillment_is_expressed_by_lower_minimum() -> None:
    market = _market(requested_quantity=10, minimum_acceptable_quantity=6)

    assert market.minimum_acceptable_quantity < market.requested_quantity


@pytest.mark.parametrize(
    ("max_winners", "requested_quantity"),
    [(1, 1), (MAX_SELLERS, MAX_SELLERS)],
)
def test_market_spec_accepts_winner_bounds(max_winners: int, requested_quantity: int) -> None:
    market = _market(
        requested_quantity=requested_quantity,
        minimum_acceptable_quantity=1,
        max_winners=max_winners,
    )

    assert market.max_winners == max_winners


@pytest.mark.parametrize("max_winners", [0, MAX_SELLERS + 1])
def test_market_spec_rejects_invalid_winner_bound(max_winners: int) -> None:
    with pytest.raises(ValidationError):
        _market(requested_quantity=MAX_SELLERS + 1, max_winners=max_winners)


def test_market_spec_rejects_more_winners_than_requested_units() -> None:
    with pytest.raises(ValidationError):
        _market(requested_quantity=2, minimum_acceptable_quantity=1, max_winners=3)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_quantity", True),
        ("requested_quantity", False),
        ("requested_quantity", 1.0),
        ("requested_quantity", "1"),
        ("minimum_acceptable_quantity", True),
        ("minimum_acceptable_quantity", False),
        ("minimum_acceptable_quantity", 1.0),
        ("minimum_acceptable_quantity", "1"),
        ("max_winners", True),
        ("max_winners", False),
        ("max_winners", 1.0),
        ("max_winners", "1"),
    ],
)
def test_market_spec_rejects_non_strict_integer_inputs(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _market(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hard_constraints", [_hard_constraint()]),
        ("soft_preferences", [_soft_preference()]),
    ],
)
def test_market_spec_requires_tuple_rule_collections(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _market(**{field: value})


def test_market_spec_rejects_too_many_hard_constraints() -> None:
    constraints = tuple(
        _hard_constraint(f"27000000-0000-4000-8000-{index:012x}")
        for index in range(MAX_HARD_CONSTRAINTS + 1)
    )

    with pytest.raises(ValidationError):
        _market(hard_constraints=constraints)


def test_market_spec_rejects_too_many_soft_preferences() -> None:
    preferences = tuple(
        _soft_preference(f"29000000-0000-4000-8000-{index:012x}")
        for index in range(MAX_SOFT_PREFERENCES + 1)
    )

    with pytest.raises(ValidationError):
        _market(soft_preferences=preferences)


def test_market_spec_rejects_duplicate_hard_constraint_ids() -> None:
    with pytest.raises(ValidationError):
        _market(hard_constraints=(_hard_constraint(), _hard_constraint()))


def test_market_spec_rejects_duplicate_soft_preference_ids() -> None:
    with pytest.raises(ValidationError):
        _market(soft_preferences=(_soft_preference(), _soft_preference()))


def test_market_spec_rejects_hard_soft_rule_id_collision() -> None:
    with pytest.raises(ValidationError):
        _market(
            hard_constraints=(_hard_constraint(_HARD_ID),),
            soft_preferences=(_soft_preference(_HARD_ID),),
        )


def test_market_spec_allows_multiple_rules_on_same_attribute() -> None:
    market = _market(
        hard_constraints=(
            _hard_constraint(_HARD_ID, attribute_key="ram_gb"),
            _hard_constraint(_OTHER_HARD_ID, attribute_key="ram_gb"),
        ),
        soft_preferences=(
            _soft_preference(_SOFT_ID, attribute_key="ram_gb"),
            _soft_preference(_OTHER_SOFT_ID, attribute_key="ram_gb"),
        ),
    )

    assert len(market.hard_constraints) == 2
    assert len(market.soft_preferences) == 2


def test_market_spec_sorts_rules_by_rule_id() -> None:
    market = _market(
        hard_constraints=(_hard_constraint(_OTHER_HARD_ID), _hard_constraint(_HARD_ID)),
        soft_preferences=(_soft_preference(_OTHER_SOFT_ID), _soft_preference(_SOFT_ID)),
    )

    assert tuple(rule.constraint_id for rule in market.hard_constraints) == (
        _HARD_ID,
        _OTHER_HARD_ID,
    )
    assert tuple(rule.preference_id for rule in market.soft_preferences) == (
        _SOFT_ID,
        _OTHER_SOFT_ID,
    )


def test_market_spec_is_frozen() -> None:
    market = _market()

    with pytest.raises(ValidationError):
        market.max_winners = 1


def test_market_spec_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _market(allow_split=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "1"), ("market_spec_version", "market-spec-v3")],
)
def test_market_spec_rejects_version_mismatch(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _market(**{field: value})


def test_buyer_policy_v2_has_exact_fields_and_versions() -> None:
    policy = _policy()

    assert policy.schema_version == "2"
    assert policy.buyer_policy_version == "buyer-policy-v2"
    assert tuple(BuyerPolicyV2.model_fields) == (
        "schema_version",
        "buyer_policy_version",
        "market_spec",
        "max_total_payment",
        "eligible_merchant_ids",
        "offer_deadline",
        "mechanism_version",
        "objective_version",
    )


def test_buyer_policy_v2_is_separate_from_v1() -> None:
    from clear_market.domain import BuyerPolicy

    assert BuyerPolicyV2 is not BuyerPolicy
    assert not issubclass(BuyerPolicyV2, BuyerPolicy)


@pytest.mark.parametrize("amount_paise", [0, 500_000])
def test_buyer_policy_accepts_money_ceiling(amount_paise: int) -> None:
    policy = _policy(max_total_payment=Money(amount_paise=amount_paise))

    assert policy.max_total_payment.amount_paise == amount_paise


@pytest.mark.parametrize("merchant_count", [MIN_SELLERS, MAX_SELLERS])
def test_buyer_policy_accepts_merchant_count_bounds(merchant_count: int) -> None:
    merchant_ids = tuple(_merchant_id(index) for index in range(merchant_count))
    market = _market(max_winners=min(merchant_count, 2))

    assert len(
        _policy(market_spec=market, eligible_merchant_ids=merchant_ids).eligible_merchant_ids
    ) == (merchant_count)


@pytest.mark.parametrize("merchant_count", [MIN_SELLERS - 1, MAX_SELLERS + 1])
def test_buyer_policy_rejects_invalid_merchant_count(merchant_count: int) -> None:
    with pytest.raises(ValidationError):
        _policy(eligible_merchant_ids=tuple(_merchant_id(index) for index in range(merchant_count)))


def test_buyer_policy_requires_merchant_tuple() -> None:
    with pytest.raises(ValidationError):
        _policy(eligible_merchant_ids=[_merchant_id(1), _merchant_id(2)])


def test_buyer_policy_rejects_duplicate_merchant_ids() -> None:
    with pytest.raises(ValidationError):
        _policy(eligible_merchant_ids=(_merchant_id(1), _merchant_id(1)))


def test_buyer_policy_normalizes_merchant_order() -> None:
    policy = _policy(eligible_merchant_ids=(_merchant_id(3), _merchant_id(1), _merchant_id(2)))

    assert policy.eligible_merchant_ids == (_merchant_id(1), _merchant_id(2), _merchant_id(3))


def test_buyer_policy_rejects_more_winners_than_eligible_merchants() -> None:
    market = _market(requested_quantity=3, minimum_acceptable_quantity=1, max_winners=3)

    with pytest.raises(ValidationError):
        _policy(market_spec=market, eligible_merchant_ids=(_merchant_id(1), _merchant_id(2)))


def test_buyer_policy_normalizes_aware_deadline_to_utc() -> None:
    deadline = datetime(
        2027,
        1,
        2,
        17,
        30,
        0,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert _policy(offer_deadline=deadline).offer_deadline == _DEADLINE


def test_buyer_policy_rejects_naive_deadline() -> None:
    with pytest.raises(ValidationError):
        _policy(offer_deadline=datetime(2027, 1, 2, 12, 0))


@pytest.mark.parametrize(
    "identifier",
    [
        "heterogeneous-procurement-v1",
        "lowest-cost-feasible-v1",
        "objective.v1",
        "market_v2_test",
        "a",
        "a" + "0" * 127,
    ],
)
@pytest.mark.parametrize("field", ["mechanism_version", "objective_version"])
def test_buyer_policy_accepts_canonical_version_identifier(
    identifier: str,
    field: str,
) -> None:
    assert getattr(_policy(**{field: identifier}), field) == identifier


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        " Mechanism",
        "Mechanism",
        "mechanism ",
        ".mechanism",
        "mechanism/value",
        "mécanisme",
        "a" + "0" * 128,
        1,
        b"mechanism",
        None,
    ],
)
@pytest.mark.parametrize("field", ["mechanism_version", "objective_version"])
def test_buyer_policy_rejects_noncanonical_version_identifier(
    identifier: object,
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        _policy(**{field: identifier})


@pytest.mark.parametrize("missing_field", ["mechanism_version", "objective_version"])
def test_buyer_policy_requires_economic_version_identifiers(missing_field: str) -> None:
    values: dict[str, object] = {
        "market_spec": _market(),
        "max_total_payment": Money(amount_paise=500_000),
        "eligible_merchant_ids": (_merchant_id(1), _merchant_id(2)),
        "offer_deadline": _DEADLINE,
        "mechanism_version": "heterogeneous-mechanism-test-v1",
        "objective_version": "heterogeneous-objective-test-v1",
    }
    del values[missing_field]

    with pytest.raises(ValidationError):
        BuyerPolicyV2(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "1"), ("buyer_policy_version", "buyer-policy-v3")],
)
def test_buyer_policy_rejects_version_mismatch(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _policy(**{field: value})


def test_buyer_policy_is_frozen() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        policy.objective_version = "changed-v1"


def test_buyer_policy_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _policy(reserve_unit_price=Money(amount_paise=100))
