from datetime import UTC, datetime
from importlib.metadata import version
from itertools import permutations
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

import clear_market.mechanism.v2.allocator as allocator_module
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    CatalogAttributeV2,
    ComparisonOperator,
    HardConstraint,
    MarketSpecV2,
    MerchantOfferLineV2,
    MerchantOfferV2,
    ProvenanceLabel,
    SignedMerchantOfferV2,
    SoftPreference,
    buyer_policy_v2_commitment,
)
from clear_market.domain import MAX_MONEY_PAISE, Money
from clear_market.mechanism.v2 import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    AllocationStatusV2,
    AllocationV2,
    MechanismV2Error,
    MechanismV2ErrorCode,
    allocate_market_v2,
)

_MARKET_ID = "70000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "70000000-0000-4000-8000-000000000002"
_BUYER_ID = "71000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2027, 7, 8, 12, 0, tzinfo=UTC)
_DIGEST = "a" * 64
_SIGNATURE = "0" * 128


def _merchant_id(index: int) -> str:
    return f"72000000-0000-4000-8000-{index:012x}"


def _offer_id(index: int) -> str:
    return f"73000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"74000000-0000-4000-8000-{index:012x}"


def _evidence_id(index: int) -> str:
    return f"75000000-0000-4000-8000-{index:012x}"


def _rule_id(index: int) -> str:
    return f"76000000-0000-4000-8000-{index:012x}"


def _value(value_type: AttributeValueType, value: str | int | bool) -> AttributeValue:
    return AttributeValue(value_type=value_type, value=value)


def _attribute(
    *,
    key: str = "metric",
    value_type: AttributeValueType = AttributeValueType.INTEGER,
    value: str | int | bool = 10,
    provenance: ProvenanceLabel = ProvenanceLabel.VERIFIED,
    index: int = 1,
) -> CatalogAttributeV2:
    return CatalogAttributeV2(
        attribute_key=key,
        value=_value(value_type, value),
        provenance=provenance,
        evidence_reference_id=_evidence_id(index),
    )


def _hard(
    *,
    operator: ComparisonOperator = ComparisonOperator.EQ,
    value_type: AttributeValueType = AttributeValueType.INTEGER,
    value: str | int | bool = 10,
    key: str = "metric",
    provenance: tuple[ProvenanceLabel, ...] = (ProvenanceLabel.VERIFIED,),
    index: int = 1,
) -> HardConstraint:
    return HardConstraint(
        constraint_id=_rule_id(index),
        attribute_key=key,
        operator=operator,
        operand=_value(value_type, value),
        allowed_provenance=provenance,
    )


def _soft(
    *,
    operator: ComparisonOperator = ComparisonOperator.EQ,
    value_type: AttributeValueType = AttributeValueType.INTEGER,
    value: str | int | bool = 10,
    key: str = "metric",
    provenance: tuple[ProvenanceLabel, ...] = (ProvenanceLabel.VERIFIED,),
    index: int = 101,
) -> SoftPreference:
    return SoftPreference(
        preference_id=_rule_id(index),
        attribute_key=key,
        operator=operator,
        operand=_value(value_type, value),
        allowed_provenance=provenance,
    )


def _market(
    *,
    requested: int = 5,
    minimum: int = 1,
    max_winners: int = 2,
    hard: tuple[HardConstraint, ...] = (),
    soft: tuple[SoftPreference, ...] = (),
    market_id: str = _MARKET_ID,
) -> MarketSpecV2:
    return MarketSpecV2(
        market_id=market_id,
        buyer_id=_BUYER_ID,
        requested_quantity=requested,
        minimum_acceptable_quantity=minimum,
        max_winners=max_winners,
        hard_constraints=hard,
        soft_preferences=soft,
    )


def _policy(
    *,
    market: MarketSpecV2 | None = None,
    budget: int = 100_000,
    eligible: tuple[str, ...] | None = None,
    mechanism: str = HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    objective: str = QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
) -> BuyerPolicyV2:
    return BuyerPolicyV2(
        market_spec=_market() if market is None else market,
        max_total_payment=Money(amount_paise=budget),
        eligible_merchant_ids=(
            (_merchant_id(1), _merchant_id(2), _merchant_id(3)) if eligible is None else eligible
        ),
        offer_deadline=_DEADLINE,
        mechanism_version=mechanism,
        objective_version=objective,
    )


def _line(
    sku_index: int,
    *,
    capacity: int = 5,
    price: int = 100,
    attributes: tuple[CatalogAttributeV2, ...] = (),
) -> MerchantOfferLineV2:
    return MerchantOfferLineV2(
        sku_id=_sku_id(sku_index),
        max_offer_quantity=capacity,
        unit_price=Money(amount_paise=price),
        attributes=attributes,
        inventory_provenance=ProvenanceLabel.VERIFIED,
        inventory_evidence_reference_id=_evidence_id(1_000 + sku_index),
    )


def _signed(
    policy: BuyerPolicyV2,
    merchant_index: int,
    *,
    lines: tuple[MerchantOfferLineV2, ...] | None = None,
    offer_index: int | None = None,
    market_id: str | None = None,
    commitment: str | None = None,
    signature: str = _SIGNATURE,
) -> SignedMerchantOfferV2:
    offer_number = merchant_index if offer_index is None else offer_index
    offer = MerchantOfferV2(
        offer_id=_offer_id(offer_number),
        market_id=policy.market_spec.market_id if market_id is None else market_id,
        merchant_id=_merchant_id(merchant_index),
        catalog_id=f"77000000-0000-4000-8000-{merchant_index:012x}",
        inventory_snapshot_id=f"78000000-0000-4000-8000-{merchant_index:012x}",
        buyer_policy_commitment_sha256=(
            buyer_policy_v2_commitment(policy) if commitment is None else commitment
        ),
        merchant_catalog_commitment_sha256=_DIGEST,
        inventory_snapshot_commitment_sha256=_DIGEST,
        lines=(_line(merchant_index),) if lines is None else lines,
    )
    return SignedMerchantOfferV2(offer=offer, signature_hex=signature)


def _allocate(
    policy: BuyerPolicyV2,
    *offers: SignedMerchantOfferV2,
) -> AllocationV2:
    return allocate_market_v2(buyer_policy=policy, signed_offers=offers)


def _assert_error(
    code: MechanismV2ErrorCode,
    *,
    policy: object,
    offers: object,
) -> None:
    with pytest.raises(MechanismV2Error) as caught:
        allocate_market_v2(  # type: ignore[arg-type]
            buyer_policy=policy,
            signed_offers=offers,
        )
    assert caught.value.code is code
    assert str(caught.value) == code.value


class _BuyerPolicySubclass(BuyerPolicyV2):
    pass


class _SignedOfferSubclass(SignedMerchantOfferV2):
    pass


@pytest.mark.parametrize("invalid", [None, {}, "policy"])
def test_invalid_buyer_policy_wrong_type_uses_stable_taxonomy(invalid: object) -> None:
    _assert_error(
        MechanismV2ErrorCode.INVALID_BUYER_POLICY,
        policy=invalid,
        offers=(),
    )


def test_invalid_buyer_policy_subclass_uses_stable_taxonomy() -> None:
    policy = _policy()
    subclass = _BuyerPolicySubclass.model_validate(policy.model_dump(mode="python"))

    _assert_error(MechanismV2ErrorCode.INVALID_BUYER_POLICY, policy=subclass, offers=())


def test_invalid_constructed_buyer_policy_does_not_leak_validation_error() -> None:
    malformed = BuyerPolicyV2.model_construct(
        mechanism_version="unsupported-v1",
        objective_version=QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    )

    _assert_error(MechanismV2ErrorCode.INVALID_BUYER_POLICY, policy=malformed, offers=())


def test_unsupported_mechanism_precedes_objective_and_offer_validation() -> None:
    policy = _policy(mechanism="unsupported-v1", objective="unsupported-v1")

    _assert_error(
        MechanismV2ErrorCode.UNSUPPORTED_MECHANISM_VERSION,
        policy=policy,
        offers=[],
    )


def test_unsupported_objective_precedes_offer_validation() -> None:
    policy = _policy(objective="unsupported-v1")

    _assert_error(
        MechanismV2ErrorCode.UNSUPPORTED_OBJECTIVE_VERSION,
        policy=policy,
        offers=[],
    )


def test_signed_offers_requires_exact_tuple() -> None:
    policy = _policy()

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=[_signed(policy, 1)],
    )


def test_signed_offers_rejects_wrong_element_before_validating_other_elements() -> None:
    policy = _policy()
    malformed = SignedMerchantOfferV2.model_construct(signature_hex=_SIGNATURE)

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(malformed, object()),
    )


def test_signed_offer_subclass_is_rejected() -> None:
    policy = _policy()
    signed = _signed(policy, 1)
    subclass = _SignedOfferSubclass.model_validate(signed.model_dump(mode="python"))

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(subclass,),
    )


def test_constructed_signed_offer_missing_offer_uses_stable_taxonomy() -> None:
    policy = _policy()
    malformed = SignedMerchantOfferV2.model_construct(signature_hex=_SIGNATURE)

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(malformed,),
    )


def test_invalid_signed_offer_precedes_duplicate_offer_id() -> None:
    policy = _policy()
    valid = _signed(policy, 1)
    malformed = valid.model_copy(update={"signature_hex": "invalid"})

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(malformed, malformed),
    )


def test_constructed_signed_offer_with_malformed_nested_offer_uses_stable_taxonomy() -> None:
    policy = _policy()
    malformed = SignedMerchantOfferV2.model_construct(
        offer=MerchantOfferV2.model_construct(merchant_id=_merchant_id(1)),
        signature_hex=_SIGNATURE,
    )

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(malformed,),
    )


def test_constructed_signed_offer_with_malformed_nested_money_uses_stable_taxonomy() -> None:
    policy = _policy()
    signed = _signed(policy, 1)
    malformed_line = signed.offer.lines[0].model_copy(
        update={"unit_price": Money.model_construct(amount_paise="100")}
    )
    malformed_offer = signed.offer.model_copy(update={"lines": (malformed_line,)})
    malformed = signed.model_copy(update={"offer": malformed_offer})

    _assert_error(
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(malformed,),
    )


def test_duplicate_offer_id_precedes_duplicate_merchant() -> None:
    policy = _policy()
    offer = _signed(policy, 1)

    _assert_error(
        MechanismV2ErrorCode.DUPLICATE_OFFER_ID,
        policy=policy,
        offers=(offer, offer),
    )


def test_duplicate_merchant_with_different_offer_ids_is_rejected() -> None:
    policy = _policy()

    _assert_error(
        MechanismV2ErrorCode.DUPLICATE_MERCHANT_OFFER,
        policy=policy,
        offers=(_signed(policy, 1, offer_index=1), _signed(policy, 1, offer_index=2)),
    )


def test_ineligible_merchant_precedes_market_and_commitment_mismatch() -> None:
    policy = _policy(eligible=(_merchant_id(1), _merchant_id(2)))
    invalid = _signed(
        policy,
        3,
        market_id=_OTHER_MARKET_ID,
        commitment="b" * 64,
    )

    _assert_error(
        MechanismV2ErrorCode.MERCHANT_NOT_ELIGIBLE,
        policy=policy,
        offers=(invalid,),
    )


def test_market_mismatch_precedes_commitment_mismatch() -> None:
    policy = _policy()
    invalid = _signed(
        policy,
        1,
        market_id=_OTHER_MARKET_ID,
        commitment="b" * 64,
    )

    _assert_error(
        MechanismV2ErrorCode.MARKET_ID_MISMATCH,
        policy=policy,
        offers=(invalid,),
    )


def test_policy_commitment_mismatch_is_rejected() -> None:
    policy = _policy()

    _assert_error(
        MechanismV2ErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH,
        policy=policy,
        offers=(_signed(policy, 1, commitment="b" * 64),),
    )


def test_duplicate_merchant_precedes_ineligible_category() -> None:
    policy = _policy(eligible=(_merchant_id(2), _merchant_id(3)))
    offers = (_signed(policy, 1, offer_index=1), _signed(policy, 1, offer_index=2))

    _assert_error(
        MechanismV2ErrorCode.DUPLICATE_MERCHANT_OFFER,
        policy=policy,
        offers=offers,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_offer_order_does_not_change_failure_category(reverse: bool) -> None:
    policy = _policy(eligible=(_merchant_id(1), _merchant_id(2)))
    offers = (
        _signed(policy, 1, market_id=_OTHER_MARKET_ID),
        _signed(policy, 3),
    )
    if reverse:
        offers = tuple(reversed(offers))

    _assert_error(
        MechanismV2ErrorCode.MERCHANT_NOT_ELIGIBLE,
        policy=policy,
        offers=offers,
    )


def test_zero_hard_constraints_qualifies_structural_offer() -> None:
    policy = _policy(market=_market(requested=2, minimum=2, max_winners=1))
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=2),)))

    assert allocation.status is AllocationStatusV2.FEASIBLE
    assert allocation.fulfilled_quantity == 2


@pytest.mark.parametrize(
    ("operator", "operand", "actual", "qualifies"),
    [
        (ComparisonOperator.EQ, 10, 10, True),
        (ComparisonOperator.EQ, 10, 11, False),
        (ComparisonOperator.NE, 10, 11, True),
        (ComparisonOperator.NE, 10, 10, False),
        (ComparisonOperator.LT, 10, 9, True),
        (ComparisonOperator.LT, 10, 10, False),
        (ComparisonOperator.LTE, 10, 10, True),
        (ComparisonOperator.LTE, 10, 11, False),
        (ComparisonOperator.GT, 10, 11, True),
        (ComparisonOperator.GT, 10, 10, False),
        (ComparisonOperator.GTE, 10, 10, True),
        (ComparisonOperator.GTE, 10, 9, False),
    ],
)
def test_hard_constraint_operator_semantics_are_exact(
    operator: ComparisonOperator,
    operand: int,
    actual: int,
    qualifies: bool,
) -> None:
    policy = _policy(
        market=_market(
            hard=(_hard(operator=operator, value=operand),),
            max_winners=1,
        )
    )
    offer = _signed(
        policy,
        1,
        lines=(_line(1, attributes=(_attribute(value=actual),)),),
    )

    allocation = _allocate(policy, offer)

    expected = AllocationStatusV2.FEASIBLE if qualifies else AllocationStatusV2.INFEASIBLE
    assert allocation.status is expected


@pytest.mark.parametrize(
    "attributes",
    [
        (),
        (_attribute(provenance=ProvenanceLabel.CLAIMED),),
        (_attribute(value_type=AttributeValueType.STRING, value="10"),),
    ],
)
def test_missing_disallowed_or_type_mismatched_hard_attribute_is_nonqualifying(
    attributes: tuple[CatalogAttributeV2, ...],
) -> None:
    policy = _policy(market=_market(hard=(_hard(operator=ComparisonOperator.NE, value=99),)))

    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, attributes=attributes),)))

    assert allocation.status is AllocationStatusV2.INFEASIBLE


def test_string_comparison_is_case_sensitive_and_has_no_normalization() -> None:
    policy = _policy(
        market=_market(
            hard=(
                _hard(
                    value_type=AttributeValueType.STRING,
                    value="Clear",
                    key="brand",
                ),
            )
        )
    )
    offer = _signed(
        policy,
        1,
        lines=(
            _line(
                1,
                attributes=(
                    _attribute(
                        key="brand",
                        value_type=AttributeValueType.STRING,
                        value="clear",
                    ),
                ),
            ),
        ),
    )

    assert _allocate(policy, offer).status is AllocationStatusV2.INFEASIBLE


def test_boolean_hard_equality_uses_exact_tagged_value() -> None:
    policy = _policy(
        market=_market(
            hard=(
                _hard(
                    value_type=AttributeValueType.BOOLEAN,
                    value=True,
                    key="available",
                ),
            )
        )
    )
    attribute = _attribute(
        key="available",
        value_type=AttributeValueType.BOOLEAN,
        value=True,
    )

    allocation = _allocate(
        policy,
        _signed(policy, 1, lines=(_line(1, attributes=(attribute,)),)),
    )

    assert allocation.status is AllocationStatusV2.FEASIBLE


def test_one_failed_hard_constraint_makes_line_nonqualifying() -> None:
    policy = _policy(
        market=_market(
            hard=(
                _hard(value=10, index=1),
                _hard(value=20, key="other", index=2),
            )
        )
    )
    attributes = (_attribute(value=10), _attribute(key="other", value=19, index=2))

    assert (
        _allocate(policy, _signed(policy, 1, lines=(_line(1, attributes=attributes),))).status
        is AllocationStatusV2.INFEASIBLE
    )


def test_soft_preference_never_creates_hard_feasibility() -> None:
    policy = _policy(
        market=_market(
            hard=(_hard(value=99),),
            soft=(_soft(value=10),),
        )
    )
    offer = _signed(policy, 1, lines=(_line(1, attributes=(_attribute(value=10),)),))

    assert _allocate(policy, offer).status is AllocationStatusV2.INFEASIBLE


def test_higher_soft_score_breaks_equal_quantity_and_payment_tie() -> None:
    policy = _policy(market=_market(requested=2, minimum=2, max_winners=1, soft=(_soft(value=10),)))
    without_match = _signed(
        policy,
        1,
        lines=(_line(1, capacity=2, attributes=(_attribute(value=9),)),),
    )
    with_match = _signed(
        policy,
        2,
        lines=(_line(2, capacity=2, attributes=(_attribute(value=10),)),),
    )

    allocation = _allocate(policy, without_match, with_match)

    assert allocation.lines[0].merchant_id == _merchant_id(2)
    assert allocation.soft_preference_unit_score == 2


def test_payment_precedes_soft_score() -> None:
    policy = _policy(market=_market(requested=2, minimum=2, max_winners=1, soft=(_soft(value=10),)))
    cheaper = _signed(
        policy,
        1,
        lines=(_line(1, capacity=2, price=99, attributes=(_attribute(value=9),)),),
    )
    preferred = _signed(
        policy,
        2,
        lines=(_line(2, capacity=2, price=100, attributes=(_attribute(value=10),)),),
    )

    allocation = _allocate(policy, cheaper, preferred)

    assert allocation.lines[0].merchant_id == _merchant_id(1)
    assert allocation.soft_preference_unit_score == 0


def test_soft_score_is_quantity_weighted() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, soft=(_soft(value=10),)))
    allocation = _allocate(
        policy,
        _signed(
            policy,
            1,
            lines=(_line(1, capacity=4, attributes=(_attribute(value=10),)),),
        ),
    )

    assert allocation.soft_preference_unit_score == 4


@pytest.mark.parametrize(
    "attributes",
    [
        (),
        (_attribute(provenance=ProvenanceLabel.CLAIMED),),
        (_attribute(value_type=AttributeValueType.STRING, value="10"),),
    ],
)
def test_missing_disallowed_or_type_mismatched_soft_attribute_scores_zero(
    attributes: tuple[CatalogAttributeV2, ...],
) -> None:
    policy = _policy(market=_market(soft=(_soft(value=10),)))
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, attributes=attributes),)))

    assert allocation.status is AllocationStatusV2.FEASIBLE
    assert allocation.soft_preference_unit_score == 0


def test_zero_preferences_produces_zero_score() -> None:
    policy = _policy()
    allocation = _allocate(policy, _signed(policy, 1))

    assert allocation.soft_preference_unit_score == 0


def test_requested_quantity_is_never_exceeded() -> None:
    policy = _policy(market=_market(requested=3, minimum=1))
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=100),)))

    assert allocation.fulfilled_quantity == 3


def test_maximum_feasible_quantity_wins_even_at_higher_payment() -> None:
    policy = _policy(market=_market(requested=3, minimum=1, max_winners=1))
    cheaper_smaller = _signed(policy, 1, lines=(_line(1, capacity=2, price=1),))
    expensive_full = _signed(policy, 2, lines=(_line(2, capacity=3, price=100),))

    allocation = _allocate(policy, cheaper_smaller, expensive_full)

    assert allocation.fulfilled_quantity == 3
    assert allocation.lines[0].merchant_id == _merchant_id(2)


def test_partial_fulfillment_at_minimum_is_feasible() -> None:
    policy = _policy(market=_market(requested=5, minimum=3))
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=3),)))

    assert allocation.status is AllocationStatusV2.FEASIBLE
    assert allocation.fulfilled_quantity == 3


def test_positive_capacity_below_minimum_is_infeasible() -> None:
    policy = _policy(market=_market(requested=5, minimum=4))
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=3),)))

    assert allocation.status is AllocationStatusV2.INFEASIBLE
    assert allocation.lines == ()


def test_empty_offer_tuple_is_economic_infeasibility() -> None:
    policy = _policy()
    allocation = allocate_market_v2(buyer_policy=policy, signed_offers=())

    assert allocation.status is AllocationStatusV2.INFEASIBLE


def test_pay_as_bid_is_exact_for_one_line() -> None:
    policy = _policy(market=_market(requested=3, minimum=3))
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=3, price=17),)))

    assert allocation.lines[0].unit_payment == Money(amount_paise=17)
    assert allocation.lines[0].line_payment == Money(amount_paise=51)
    assert allocation.total_payment == Money(amount_paise=51)


def test_pay_as_bid_sums_multiple_lines_without_second_price() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    offers = (
        _signed(policy, 1, lines=(_line(1, capacity=2, price=10),)),
        _signed(policy, 2, lines=(_line(2, capacity=2, price=20),)),
    )

    allocation = _allocate(policy, *offers)

    assert tuple(line.unit_payment.amount_paise for line in allocation.lines) == (10, 20)
    assert allocation.total_payment == Money(amount_paise=60)


def test_zero_price_line_is_supported() -> None:
    policy = _policy(market=_market(requested=3, minimum=3), budget=0)
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=3, price=0),)))

    assert allocation.status is AllocationStatusV2.FEASIBLE
    assert allocation.total_payment == Money(amount_paise=0)


def test_exact_budget_boundary_is_feasible() -> None:
    policy = _policy(market=_market(requested=3, minimum=3), budget=300)
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=3, price=100),)))

    assert allocation.status is AllocationStatusV2.FEASIBLE
    assert allocation.total_payment == Money(amount_paise=300)


def test_one_paise_over_budget_prevents_full_allocation() -> None:
    policy = _policy(market=_market(requested=3, minimum=3), budget=299)
    allocation = _allocate(policy, _signed(policy, 1, lines=(_line(1, capacity=3, price=100),)))

    assert allocation.status is AllocationStatusV2.INFEASIBLE


def test_payment_is_minimized_after_quantity() -> None:
    policy = _policy(market=_market(requested=3, minimum=3, max_winners=1))
    expensive = _signed(policy, 1, lines=(_line(1, capacity=3, price=101),))
    cheaper = _signed(policy, 2, lines=(_line(2, capacity=3, price=100),))

    allocation = _allocate(policy, expensive, cheaper)

    assert allocation.lines[0].merchant_id == _merchant_id(2)
    assert allocation.total_payment == Money(amount_paise=300)


def test_max_winners_one_limits_distinct_merchants() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=1))
    offers = (
        _signed(policy, 1, lines=(_line(1, capacity=4, price=100),)),
        _signed(policy, 2, lines=(_line(2, capacity=2, price=1),)),
    )

    allocation = _allocate(policy, *offers)

    assert allocation.winner_count == 1
    assert allocation.lines[0].merchant_id == _merchant_id(1)


def test_multiple_winners_can_split_fulfillment() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    allocation = _allocate(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2),)),
        _signed(policy, 2, lines=(_line(2, capacity=2),)),
    )

    assert allocation.winner_count == 2
    assert allocation.fulfilled_quantity == 4


def test_two_positive_skus_from_one_merchant_count_as_one_winner() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=1))
    offer = _signed(
        policy,
        1,
        lines=(_line(1, capacity=2), _line(2, capacity=2)),
    )

    allocation = _allocate(policy, offer)

    assert allocation.winner_count == 1
    assert len(allocation.lines) == 2


def test_winner_limit_can_make_required_quantity_infeasible() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=1))
    allocation = _allocate(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2),)),
        _signed(policy, 2, lines=(_line(2, capacity=2),)),
    )

    assert allocation.status is AllocationStatusV2.INFEASIBLE


def test_winner_restriction_can_force_a_different_feasible_allocation() -> None:
    one_winner_policy = _policy(market=_market(requested=4, minimum=3, max_winners=1))
    one_winner = _allocate(
        one_winner_policy,
        _signed(one_winner_policy, 1, lines=(_line(1, capacity=3),)),
        _signed(one_winner_policy, 2, lines=(_line(2, capacity=3),)),
    )
    two_winner_policy = _policy(market=_market(requested=4, minimum=3, max_winners=2))
    two_winner = _allocate(
        two_winner_policy,
        _signed(two_winner_policy, 1, lines=(_line(1, capacity=3),)),
        _signed(two_winner_policy, 2, lines=(_line(2, capacity=3),)),
    )

    assert one_winner.status is AllocationStatusV2.FEASIBLE
    assert one_winner.fulfilled_quantity == 3
    assert one_winner.winner_count == 1
    assert two_winner.status is AllocationStatusV2.FEASIBLE
    assert two_winner.fulfilled_quantity == 4
    assert two_winner.winner_count == 2


def test_canonical_merchant_tie_selects_earlier_line() -> None:
    policy = _policy(market=_market(requested=2, minimum=2, max_winners=1))
    allocation = _allocate(
        policy,
        _signed(policy, 2, lines=(_line(2, capacity=2),)),
        _signed(policy, 1, lines=(_line(1, capacity=2),)),
    )

    assert allocation.lines[0].merchant_id == _merchant_id(1)


def test_canonical_same_offer_sku_tie_maximizes_earlier_sku() -> None:
    policy = _policy(market=_market(requested=3, minimum=3, max_winners=1))
    offer = _signed(
        policy,
        1,
        lines=(_line(2, capacity=3), _line(1, capacity=3)),
    )

    allocation = _allocate(policy, offer)

    assert len(allocation.lines) == 1
    assert allocation.lines[0].sku_id == _sku_id(1)
    assert allocation.lines[0].allocated_quantity == 3


def test_canonical_earlier_line_saturates_before_next_line() -> None:
    policy = _policy(market=_market(requested=5, minimum=5, max_winners=1))
    offer = _signed(
        policy,
        1,
        lines=(_line(2, capacity=5), _line(1, capacity=2)),
    )

    allocation = _allocate(policy, offer)

    assert tuple((line.sku_id, line.allocated_quantity) for line in allocation.lines) == (
        (_sku_id(1), 2),
        (_sku_id(2), 3),
    )


def test_offer_and_source_line_permutations_produce_identical_allocation() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    first = _signed(policy, 1, lines=(_line(2, capacity=2), _line(1, capacity=2)))
    second = _signed(policy, 2, lines=(_line(4, capacity=2), _line(3, capacity=2)))
    expected = _allocate(policy, first, second)

    for ordered in permutations((first, second)):
        reversed_lines = tuple(reversed(ordered[0].offer.lines))
        reversed_offer = ordered[0].offer.model_copy(update={"lines": reversed_lines})
        reversed_signed = ordered[0].model_copy(update={"offer": reversed_offer})
        assert _allocate(policy, reversed_signed, ordered[1]) == expected


def test_allocator_is_deterministic_across_repeated_calls() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    offers = (
        _signed(policy, 1, lines=(_line(1, capacity=2, price=10),)),
        _signed(policy, 2, lines=(_line(2, capacity=2, price=20),)),
    )

    assert all(_allocate(policy, *offers) == _allocate(policy, *offers) for _ in range(5))


def test_syntactically_valid_bogus_signature_is_not_verified_by_allocator() -> None:
    policy = _policy(market=_market(requested=1, minimum=1, max_winners=1))
    bogus = _signed(policy, 1, signature="f" * 128)

    allocation = _allocate(policy, bogus)

    assert allocation.status is AllocationStatusV2.FEASIBLE
    # Allocation is not authentication and does not authorize money movement.
    assert allocation.total_payment == Money(amount_paise=100)


def test_returned_feasible_result_binds_policy_and_exact_aggregates() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    allocation = _allocate(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2, price=10),)),
        _signed(policy, 2, lines=(_line(2, capacity=2, price=20),)),
    )

    assert allocation.market_id == policy.market_spec.market_id
    assert allocation.buyer_policy_commitment_sha256 == buyer_policy_v2_commitment(policy)
    assert allocation.mechanism_version == HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION
    assert allocation.objective_version == QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION
    assert allocation.fulfilled_quantity == sum(
        line.allocated_quantity for line in allocation.lines
    )
    assert allocation.total_payment.amount_paise == sum(
        line.line_payment.amount_paise for line in allocation.lines
    )
    assert allocation.winner_count == len({line.merchant_id for line in allocation.lines})


def test_infeasible_result_has_exact_zero_shape_and_policy_binding() -> None:
    policy = _policy()
    allocation = allocate_market_v2(buyer_policy=policy, signed_offers=())

    assert allocation.market_id == policy.market_spec.market_id
    assert allocation.buyer_policy_commitment_sha256 == buyer_policy_v2_commitment(policy)
    assert allocation.status is AllocationStatusV2.INFEASIBLE
    assert allocation.fulfilled_quantity == 0
    assert allocation.total_payment == Money(amount_paise=0)
    assert allocation.soft_preference_unit_score == 0
    assert allocation.winner_count == 0
    assert allocation.lines == ()


@pytest.mark.parametrize(
    "status",
    [cp_model.FEASIBLE, cp_model.UNKNOWN, cp_model.MODEL_INVALID],
)
def test_phase_one_nonfinal_solver_status_is_failure(
    monkeypatch: pytest.MonkeyPatch,
    status: cp_model.CpSolverStatus,
) -> None:
    policy = _policy()
    monkeypatch.setattr(
        allocator_module,
        "_solve_model",
        lambda model: allocator_module._SolverResult(
            status=status,
            solver=cp_model.CpSolver(),
        ),
    )

    _assert_error(
        MechanismV2ErrorCode.SOLVER_FAILURE,
        policy=policy,
        offers=(_signed(policy, 1),),
    )


def test_phase_one_infeasible_maps_to_economic_infeasibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy()
    monkeypatch.setattr(
        allocator_module,
        "_solve_model",
        lambda model: allocator_module._SolverResult(
            status=cp_model.INFEASIBLE,
            solver=cp_model.CpSolver(),
        ),
    )

    allocation = _allocate(policy, _signed(policy, 1))

    assert allocation.status is AllocationStatusV2.INFEASIBLE


@pytest.mark.parametrize(
    "later_status",
    [cp_model.INFEASIBLE, cp_model.FEASIBLE, cp_model.UNKNOWN, cp_model.MODEL_INVALID],
)
def test_later_phase_nonoptimal_status_is_solver_failure(
    monkeypatch: pytest.MonkeyPatch,
    later_status: cp_model.CpSolverStatus,
) -> None:
    policy = _policy()
    original = allocator_module._solve_model
    call_count = 0

    def fail_second_solve(model: cp_model.CpModel) -> allocator_module._SolverResult:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return allocator_module._SolverResult(
                status=later_status,
                solver=cp_model.CpSolver(),
            )
        return original(model)

    monkeypatch.setattr(allocator_module, "_solve_model", fail_second_solve)

    _assert_error(
        MechanismV2ErrorCode.SOLVER_FAILURE,
        policy=policy,
        offers=(_signed(policy, 1),),
    )


def test_solver_configuration_is_exact_and_has_no_time_limit_source() -> None:
    solver = allocator_module._new_solver()
    source = Path("src/clear_market/mechanism/v2/allocator.py").read_text(encoding="utf-8")

    assert solver.parameters.num_search_workers == 1
    assert solver.parameters.random_seed == 0
    assert solver.parameters.randomize_search is False
    assert "max_time_in_seconds" not in source
    assert "max_deterministic_time" not in source


def test_ortools_runtime_version_is_exact() -> None:
    assert version("ortools") == "9.15.6755"


def test_effective_cap_handles_money_ceiling_without_overflow() -> None:
    policy = _policy(
        market=_market(requested=2, minimum=1, max_winners=1),
        budget=MAX_MONEY_PAISE,
    )
    allocation = _allocate(
        policy,
        _signed(
            policy,
            1,
            lines=(_line(1, capacity=2, price=MAX_MONEY_PAISE),),
        ),
    )

    assert allocation.fulfilled_quantity == 1
    assert allocation.total_payment == Money(amount_paise=MAX_MONEY_PAISE)


def test_allocator_does_not_mutate_policy_or_signed_offers() -> None:
    policy = _policy()
    offers = (_signed(policy, 1), _signed(policy, 2))
    snapshot = (
        policy.model_dump(mode="python"),
        tuple(o.model_dump(mode="python") for o in offers),
    )

    _allocate(policy, *offers)

    assert snapshot == (
        policy.model_dump(mode="python"),
        tuple(offer.model_dump(mode="python") for offer in offers),
    )
