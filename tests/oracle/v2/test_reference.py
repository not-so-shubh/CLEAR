import random
import subprocess
import sys
from datetime import UTC, datetime
from itertools import product

import pytest

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
from clear_market.domain import Currency, Money
from clear_market.mechanism.v2 import AllocationV2, allocate_market_v2
from clear_market.oracle.v2 import (
    OracleAllocationStatusV2,
    OracleAllocationV2,
    OracleV2Error,
    OracleV2ErrorCode,
    compute_oracle_allocation_v2,
)

_MARKET_ID = "90000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "90000000-0000-4000-8000-000000000002"
_BUYER_ID = "91000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2028, 1, 2, 12, 0, tzinfo=UTC)
_DIGEST = "a" * 64
_SIGNATURE = "0" * 128


def _merchant_id(index: int) -> str:
    return f"92000000-0000-4000-8000-{index:012x}"


def _offer_id(index: int) -> str:
    return f"93000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"94000000-0000-4000-8000-{index:012x}"


def _evidence_id(index: int) -> str:
    return f"95000000-0000-4000-8000-{index:012x}"


def _rule_id(index: int) -> str:
    return f"96000000-0000-4000-8000-{index:012x}"


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
    max_winners: int | None = None,
    hard: tuple[HardConstraint, ...] = (),
    soft: tuple[SoftPreference, ...] = (),
    market_id: str = _MARKET_ID,
) -> MarketSpecV2:
    return MarketSpecV2(
        market_id=market_id,
        buyer_id=_BUYER_ID,
        requested_quantity=requested,
        minimum_acceptable_quantity=minimum,
        max_winners=min(2, requested) if max_winners is None else max_winners,
        hard_constraints=hard,
        soft_preferences=soft,
    )


def _policy(
    *,
    market: MarketSpecV2 | None = None,
    budget: int = 100_000,
    eligible: tuple[str, ...] | None = None,
    mechanism: str = "heterogeneous-pay-as-bid-v2",
    objective: str = "quantity-cost-soft-objective-v2",
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
    return SignedMerchantOfferV2(
        offer=MerchantOfferV2(
            offer_id=_offer_id(offer_number),
            market_id=policy.market_spec.market_id if market_id is None else market_id,
            merchant_id=_merchant_id(merchant_index),
            catalog_id=f"97000000-0000-4000-8000-{merchant_index:012x}",
            inventory_snapshot_id=f"98000000-0000-4000-8000-{merchant_index:012x}",
            buyer_policy_commitment_sha256=(
                buyer_policy_v2_commitment(policy) if commitment is None else commitment
            ),
            merchant_catalog_commitment_sha256=_DIGEST,
            inventory_snapshot_commitment_sha256=_DIGEST,
            lines=(_line(merchant_index),) if lines is None else lines,
        ),
        signature_hex=signature,
    )


def _oracle(policy: BuyerPolicyV2, *offers: SignedMerchantOfferV2) -> OracleAllocationV2:
    return compute_oracle_allocation_v2(buyer_policy=policy, signed_offers=offers)


def _assert_error(code: OracleV2ErrorCode, *, policy: object, offers: object) -> None:
    with pytest.raises(OracleV2Error) as caught:
        compute_oracle_allocation_v2(  # type: ignore[arg-type]
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
def test_invalid_buyer_policy_wrong_type(invalid: object) -> None:
    _assert_error(OracleV2ErrorCode.INVALID_BUYER_POLICY, policy=invalid, offers=())


def test_invalid_buyer_policy_subclass_and_constructed_state() -> None:
    policy = _policy()
    subclass = _BuyerPolicySubclass.model_validate(policy.model_dump(mode="python"))
    _assert_error(OracleV2ErrorCode.INVALID_BUYER_POLICY, policy=subclass, offers=())
    malformed = BuyerPolicyV2.model_construct(max_total_payment=Money(amount_paise=1))
    _assert_error(OracleV2ErrorCode.INVALID_BUYER_POLICY, policy=malformed, offers=())


def test_unsupported_versions_precede_offer_validation() -> None:
    _assert_error(
        OracleV2ErrorCode.UNSUPPORTED_MECHANISM_VERSION,
        policy=_policy(mechanism="other", objective="other"),
        offers=[],
    )
    _assert_error(
        OracleV2ErrorCode.UNSUPPORTED_OBJECTIVE_VERSION,
        policy=_policy(objective="other"),
        offers=[],
    )


def test_signed_offers_requires_exact_tuple_and_elements() -> None:
    policy = _policy()
    _assert_error(OracleV2ErrorCode.INVALID_SIGNED_OFFER, policy=policy, offers=[])
    _assert_error(OracleV2ErrorCode.INVALID_SIGNED_OFFER, policy=policy, offers=(object(),))
    subclass = _SignedOfferSubclass.model_validate(_signed(policy, 1).model_dump(mode="python"))
    _assert_error(OracleV2ErrorCode.INVALID_SIGNED_OFFER, policy=policy, offers=(subclass,))


def test_malformed_constructed_signed_offer_states_fail_closed() -> None:
    policy = _policy()
    missing_offer = SignedMerchantOfferV2.model_construct(signature_hex=_SIGNATURE)
    _assert_error(
        OracleV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(missing_offer,),
    )

    valid = _signed(policy, 1)
    malformed_offer = MerchantOfferV2.model_construct(
        **{**valid.offer.model_dump(mode="python"), "lines": ()}
    )
    nested_offer = SignedMerchantOfferV2.model_construct(
        offer=malformed_offer,
        signature_hex=_SIGNATURE,
    )
    _assert_error(
        OracleV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(nested_offer,),
    )

    bad_money = Money.model_construct(amount_paise="100", currency=Currency.INR)
    malformed_line = MerchantOfferLineV2.model_construct(
        **{**valid.offer.lines[0].model_dump(mode="python"), "unit_price": bad_money}
    )
    bad_nested_offer = MerchantOfferV2.model_construct(
        **{**valid.offer.model_dump(mode="python"), "lines": (malformed_line,)}
    )
    nested_money = SignedMerchantOfferV2.model_construct(
        offer=bad_nested_offer,
        signature_hex=_SIGNATURE,
    )
    _assert_error(
        OracleV2ErrorCode.INVALID_SIGNED_OFFER,
        policy=policy,
        offers=(nested_money,),
    )


def test_input_error_precedence_and_category_passes() -> None:
    policy = _policy()
    duplicate_offer = (
        _signed(policy, 1, offer_index=9),
        _signed(policy, 2, offer_index=9),
    )
    _assert_error(OracleV2ErrorCode.DUPLICATE_OFFER_ID, policy=policy, offers=duplicate_offer)

    duplicate_merchant = (
        _signed(policy, 1, offer_index=1),
        _signed(policy, 1, offer_index=2),
    )
    _assert_error(
        OracleV2ErrorCode.DUPLICATE_MERCHANT_OFFER,
        policy=policy,
        offers=duplicate_merchant,
    )

    restricted = _policy(eligible=(_merchant_id(1), _merchant_id(2)))
    ineligible = _signed(
        restricted,
        3,
        market_id=_OTHER_MARKET_ID,
        commitment="b" * 64,
    )
    _assert_error(OracleV2ErrorCode.MERCHANT_NOT_ELIGIBLE, policy=restricted, offers=(ineligible,))

    market_bad = _signed(policy, 1, market_id=_OTHER_MARKET_ID, commitment="b" * 64)
    _assert_error(OracleV2ErrorCode.MARKET_ID_MISMATCH, policy=policy, offers=(market_bad,))
    commitment_bad = _signed(policy, 1, commitment="b" * 64)
    _assert_error(
        OracleV2ErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH,
        policy=policy,
        offers=(commitment_bad,),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_input_order_cannot_change_failure_category(reverse: bool) -> None:
    policy = _policy(eligible=(_merchant_id(1), _merchant_id(2)))
    offers = (
        _signed(policy, 1, market_id=_OTHER_MARKET_ID),
        _signed(policy, 3),
    )
    if reverse:
        offers = tuple(reversed(offers))
    _assert_error(OracleV2ErrorCode.MERCHANT_NOT_ELIGIBLE, policy=policy, offers=offers)


@pytest.mark.parametrize(
    ("operator", "actual", "expected", "qualifies"),
    [
        (ComparisonOperator.EQ, 10, 10, True),
        (ComparisonOperator.EQ, 10, 11, False),
        (ComparisonOperator.NE, 10, 11, True),
        (ComparisonOperator.NE, 10, 10, False),
        (ComparisonOperator.LT, 9, 10, True),
        (ComparisonOperator.LTE, 10, 10, True),
        (ComparisonOperator.GT, 11, 10, True),
        (ComparisonOperator.GTE, 10, 10, True),
    ],
)
def test_hard_constraint_operators_are_independently_exact(
    operator: ComparisonOperator,
    actual: int,
    expected: int,
    qualifies: bool,
) -> None:
    policy = _policy(
        market=_market(
            requested=1,
            minimum=1,
            hard=(_hard(operator=operator, value=expected),),
        )
    )
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=1, attributes=(_attribute(value=actual),)),)),
    )
    assert (result.status is OracleAllocationStatusV2.FEASIBLE) is qualifies


@pytest.mark.parametrize(
    "attributes",
    [
        (),
        (_attribute(provenance=ProvenanceLabel.CLAIMED),),
        (_attribute(value_type=AttributeValueType.STRING, value="10"),),
    ],
)
def test_missing_disallowed_and_type_mismatched_hard_attributes_fail(
    attributes: tuple[CatalogAttributeV2, ...],
) -> None:
    policy = _policy(market=_market(requested=1, hard=(_hard(),)))
    assert _oracle(policy, _signed(policy, 1, lines=(_line(1, attributes=attributes),))).status is (
        OracleAllocationStatusV2.INFEASIBLE
    )


def test_ne_type_mismatch_string_case_boolean_and_multiple_hard_rules() -> None:
    ne_policy = _policy(
        market=_market(
            requested=1,
            hard=(
                _hard(
                    operator=ComparisonOperator.NE,
                    value_type=AttributeValueType.STRING,
                    value="10",
                ),
            ),
        )
    )
    assert (
        _oracle(
            ne_policy,
            _signed(ne_policy, 1, lines=(_line(1, attributes=(_attribute(value=10),)),)),
        ).status
        is OracleAllocationStatusV2.INFEASIBLE
    )

    exact_policy = _policy(
        market=_market(
            requested=1,
            hard=(
                _hard(value_type=AttributeValueType.STRING, value="Case", index=1),
                _hard(
                    key="enabled",
                    value_type=AttributeValueType.BOOLEAN,
                    value=True,
                    index=2,
                ),
            ),
        )
    )
    attributes = (
        _attribute(value_type=AttributeValueType.STRING, value="case", index=1),
        _attribute(
            key="enabled",
            value_type=AttributeValueType.BOOLEAN,
            value=True,
            index=2,
        ),
    )
    assert (
        _oracle(
            exact_policy,
            _signed(exact_policy, 1, lines=(_line(1, attributes=attributes),)),
        ).status
        is OracleAllocationStatusV2.INFEASIBLE
    )


def test_zero_constraints_qualifies_and_soft_never_creates_qualification() -> None:
    zero = _policy(market=_market(requested=1))
    zero_result = _oracle(zero, _signed(zero, 1, lines=(_line(1, capacity=1),)))
    assert zero_result.status is OracleAllocationStatusV2.FEASIBLE
    assert zero_result.soft_preference_unit_score == 0
    constrained = _policy(
        market=_market(
            requested=1,
            hard=(_hard(value=99),),
            soft=(_soft(value=10),),
        )
    )
    result = _oracle(
        constrained,
        _signed(
            constrained,
            1,
            lines=(_line(1, attributes=(_attribute(value=10),)),),
        ),
    )
    assert result.status is OracleAllocationStatusV2.INFEASIBLE


def test_boolean_hard_equality_is_exact() -> None:
    policy = _policy(
        market=_market(
            requested=1,
            hard=(
                _hard(
                    key="enabled",
                    value_type=AttributeValueType.BOOLEAN,
                    value=True,
                ),
            ),
        )
    )
    attributes = (
        _attribute(
            key="enabled",
            value_type=AttributeValueType.BOOLEAN,
            value=True,
        ),
    )
    assert (
        _oracle(
            policy,
            _signed(policy, 1, lines=(_line(1, capacity=1, attributes=attributes),)),
        ).status
        is OracleAllocationStatusV2.FEASIBLE
    )


def test_soft_score_breaks_equal_cost_tie_and_is_quantity_weighted() -> None:
    policy = _policy(market=_market(requested=3, max_winners=2, soft=(_soft(),)))
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=3, attributes=()),)),
        _signed(
            policy,
            2,
            lines=(_line(2, capacity=3, attributes=(_attribute(value=10),)),),
        ),
    )
    assert result.lines[0].merchant_id == _merchant_id(2)
    assert result.soft_preference_unit_score == 3


def test_cheaper_line_beats_preferred_expensive_line() -> None:
    policy = _policy(market=_market(requested=2, soft=(_soft(),)))
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2, price=10),)),
        _signed(
            policy,
            2,
            lines=(_line(2, capacity=2, price=11, attributes=(_attribute(),)),),
        ),
    )
    assert result.total_payment.amount_paise == 20
    assert result.soft_preference_unit_score == 0


@pytest.mark.parametrize(
    "attributes",
    [
        (),
        (_attribute(provenance=ProvenanceLabel.CLAIMED),),
        (_attribute(value_type=AttributeValueType.STRING, value="10"),),
    ],
)
def test_missing_disallowed_or_type_mismatched_soft_scores_zero(
    attributes: tuple[CatalogAttributeV2, ...],
) -> None:
    policy = _policy(market=_market(requested=1, soft=(_soft(),)))
    result = _oracle(policy, _signed(policy, 1, lines=(_line(1, attributes=attributes),)))
    assert result.soft_preference_unit_score == 0


def test_quantity_payment_budget_and_partial_fulfillment_boundaries() -> None:
    full = _policy(market=_market(requested=3, minimum=2), budget=15)
    result = _oracle(full, _signed(full, 1, lines=(_line(1, capacity=5, price=5),)))
    assert result.fulfilled_quantity == 3
    assert result.total_payment == Money(amount_paise=15)
    assert result.lines[0].allocated_quantity == 3

    partial = _policy(market=_market(requested=3, minimum=2), budget=14)
    partial_result = _oracle(
        partial,
        _signed(partial, 1, lines=(_line(1, capacity=5, price=5),)),
    )
    assert partial_result.status is OracleAllocationStatusV2.FEASIBLE
    assert partial_result.fulfilled_quantity == 2

    insufficient = _policy(market=_market(requested=3, minimum=3), budget=14)
    assert (
        _oracle(
            insufficient,
            _signed(insufficient, 1, lines=(_line(1, capacity=5, price=5),)),
        ).status
        is OracleAllocationStatusV2.INFEASIBLE
    )


def test_zero_price_and_pay_as_bid_multiple_lines() -> None:
    policy = _policy(market=_market(requested=4), budget=10)
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2, price=0),)),
        _signed(policy, 2, lines=(_line(2, capacity=2, price=5),)),
    )
    assert result.fulfilled_quantity == 4
    assert result.total_payment.amount_paise == 10
    assert tuple(line.unit_payment.amount_paise for line in result.lines) == (0, 5)
    assert tuple(line.line_payment.amount_paise for line in result.lines) == (0, 10)


def test_payment_minimization_occurs_after_quantity() -> None:
    policy = _policy(market=_market(requested=2, max_winners=1))
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2, price=10),)),
        _signed(policy, 2, lines=(_line(2, capacity=3, price=9),)),
    )
    assert result.lines[0].merchant_id == _merchant_id(2)
    assert result.total_payment.amount_paise == 18


def test_winner_limits_split_and_multiple_skus_per_merchant() -> None:
    one = _policy(market=_market(requested=4, minimum=4, max_winners=1))
    assert (
        _oracle(
            one,
            _signed(one, 1, lines=(_line(1, capacity=2),)),
            _signed(one, 2, lines=(_line(2, capacity=2),)),
        ).status
        is OracleAllocationStatusV2.INFEASIBLE
    )

    split = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    split_result = _oracle(
        split,
        _signed(split, 1, lines=(_line(1, capacity=2),)),
        _signed(split, 2, lines=(_line(2, capacity=2),)),
    )
    assert split_result.winner_count == 2

    one_merchant = _policy(market=_market(requested=4, max_winners=1))
    multi_sku_result = _oracle(
        one_merchant,
        _signed(
            one_merchant,
            1,
            lines=(_line(1, capacity=2), _line(2, capacity=2)),
        ),
    )
    assert multi_sku_result.winner_count == 1
    assert len(multi_sku_result.lines) == 2


def test_winner_restriction_changes_feasible_allocation() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=1))
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2, price=1),)),
        _signed(policy, 2, lines=(_line(2, capacity=4, price=3),)),
    )
    assert result.lines[0].merchant_id == _merchant_id(2)
    assert result.total_payment.amount_paise == 12


def test_canonical_ties_and_capacity_saturation_are_exact() -> None:
    merchant_tie = _policy(market=_market(requested=1, max_winners=1))
    merchant_result = _oracle(
        merchant_tie,
        _signed(merchant_tie, 2, lines=(_line(2, capacity=1),)),
        _signed(merchant_tie, 1, lines=(_line(1, capacity=1),)),
    )
    assert merchant_result.lines[0].merchant_id == _merchant_id(1)

    sku_tie = _policy(market=_market(requested=3, max_winners=1))
    sku_result = _oracle(
        sku_tie,
        _signed(
            sku_tie,
            1,
            lines=(_line(2, capacity=3), _line(1, capacity=2)),
        ),
    )
    assert tuple((line.sku_id, line.allocated_quantity) for line in sku_result.lines) == (
        (_sku_id(1), 2),
        (_sku_id(2), 1),
    )


def test_offer_and_source_line_permutations_are_identical() -> None:
    policy = _policy(market=_market(requested=4))
    first = _signed(policy, 1, lines=(_line(2, capacity=2), _line(1, capacity=2)))
    second = _signed(policy, 2, lines=(_line(4, capacity=2), _line(3, capacity=2)))
    expected = _oracle(policy, first, second)
    assert _oracle(policy, second, first) == expected
    rebuilt_first = _signed(policy, 1, lines=tuple(reversed(first.offer.lines)))
    assert _oracle(policy, rebuilt_first, second) == expected


def test_exact_size_subset_enumeration_covers_fewer_actual_winners() -> None:
    policy = _policy(market=_market(requested=2, max_winners=2))
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2, price=1),)),
        _signed(policy, 2, lines=(_line(2, capacity=1, price=2),)),
        _signed(policy, 3, lines=(_line(3, capacity=1, price=3),)),
    )
    assert result.winner_count == 1
    assert result.lines[0].merchant_id == _merchant_id(1)


def test_exact_size_subset_can_require_two_merchants_and_all_merchant_subset() -> None:
    policy = _policy(market=_market(requested=4, minimum=4, max_winners=2))
    result = _oracle(
        policy,
        _signed(policy, 1, lines=(_line(1, capacity=2),)),
        _signed(policy, 2, lines=(_line(2, capacity=2),)),
        _signed(policy, 3, lines=(_line(3, capacity=1),)),
    )
    assert result.winner_count == 2
    all_policy = _policy(market=_market(requested=5, max_winners=3))
    assert (
        _oracle(
            all_policy,
            _signed(all_policy, 1, lines=(_line(1, capacity=2),)),
            _signed(all_policy, 2, lines=(_line(2, capacity=2),)),
            _signed(all_policy, 3, lines=(_line(3, capacity=2),)),
        ).fulfilled_quantity
        == 5
    )


@pytest.mark.parametrize("max_winners", [1, 20])
def test_twenty_merchant_population_has_no_artificial_oracle_cap(max_winners: int) -> None:
    eligible = tuple(_merchant_id(index) for index in range(1, 21))
    policy = _policy(
        market=_market(requested=20, minimum=1, max_winners=max_winners),
        eligible=eligible,
    )
    offers = tuple(
        _signed(policy, index, lines=(_line(index, capacity=20, price=index),))
        for index in range(1, 21)
    )
    result = compute_oracle_allocation_v2(buyer_policy=policy, signed_offers=offers)
    assert result.status is OracleAllocationStatusV2.FEASIBLE
    assert result.fulfilled_quantity == 20


def test_bogus_signature_has_no_authenticity_or_money_authority() -> None:
    policy = _policy(market=_market(requested=1))
    offer = _signed(policy, 1, signature="f" * 128)
    oracle = _oracle(policy, offer)
    production = allocate_market_v2(buyer_policy=policy, signed_offers=(offer,))
    assert oracle.status.value == production.status.value == "FEASIBLE"
    # Neither economic result proves signature validity or authorizes money movement.


def test_fresh_process_import_does_not_load_production_allocator_or_ortools() -> None:
    script = """
import sys
import clear_market.oracle.v2
assert all(name != 'ortools' and not name.startswith('ortools.') for name in sys.modules)
assert 'clear_market.mechanism.v2.allocator' not in sys.modules
print('ORACLE_RUNTIME_INDEPENDENCE_PASS')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == "ORACLE_RUNTIME_INDEPENDENCE_PASS\n"


def _test_rule_matches(
    attributes: tuple[CatalogAttributeV2, ...],
    rule: HardConstraint | SoftPreference,
) -> bool:
    attribute = next(
        (candidate for candidate in attributes if candidate.attribute_key == rule.attribute_key),
        None,
    )
    if attribute is None or attribute.provenance not in rule.allowed_provenance:
        return False
    if attribute.value.value_type is not rule.operand.value_type:
        return False
    actual = attribute.value.value
    expected = rule.operand.value
    if rule.operator is ComparisonOperator.EQ:
        return actual == expected
    if rule.operator is ComparisonOperator.NE:
        return actual != expected
    if type(actual) is not int or type(expected) is not int:
        return False
    return {
        ComparisonOperator.LT: actual < expected,
        ComparisonOperator.LTE: actual <= expected,
        ComparisonOperator.GT: actual > expected,
        ComparisonOperator.GTE: actual >= expected,
    }[rule.operator]


def _brute_projection(
    policy: BuyerPolicyV2,
    offers: tuple[SignedMerchantOfferV2, ...],
) -> tuple[str, int, int, int, int, tuple[tuple[str, str, str, int, int, int], ...]]:
    records: list[tuple[str, str, str, int, int, int]] = []
    for signed in offers:
        for line in signed.offer.lines:
            if all(
                _test_rule_matches(line.attributes, constraint)
                for constraint in policy.market_spec.hard_constraints
            ):
                records.append(
                    (
                        signed.offer.merchant_id,
                        line.sku_id,
                        signed.offer.offer_id,
                        line.max_offer_quantity,
                        line.unit_price.amount_paise,
                        sum(
                            _test_rule_matches(line.attributes, preference)
                            for preference in policy.market_spec.soft_preferences
                        ),
                    )
                )
    records.sort(key=lambda record: record[:3])
    best: tuple[int, int, int, tuple[int, ...]] | None = None
    for quantities in product(*(range(record[3] + 1) for record in records)):
        quantity = sum(quantities)
        payment = sum(
            allocated * record[4] for allocated, record in zip(quantities, records, strict=True)
        )
        winners = {
            record[0]
            for allocated, record in zip(quantities, records, strict=True)
            if allocated > 0
        }
        if (
            not policy.market_spec.minimum_acceptable_quantity
            <= quantity
            <= (policy.market_spec.requested_quantity)
        ):
            continue
        if payment > policy.max_total_payment.amount_paise:
            continue
        if len(winners) > policy.market_spec.max_winners:
            continue
        soft = sum(
            allocated * record[5] for allocated, record in zip(quantities, records, strict=True)
        )
        objective = (quantity, -payment, soft, quantities)
        if best is None or objective > best:
            best = objective
    if best is None:
        return ("INFEASIBLE", 0, 0, 0, 0, ())
    quantity, negative_payment, soft, quantities = best
    positive_lines = tuple(
        (record[2], record[0], record[1], allocated, record[4], allocated * record[4])
        for allocated, record in zip(quantities, records, strict=True)
        if allocated > 0
    )
    return (
        "FEASIBLE",
        quantity,
        -negative_payment,
        soft,
        len({line[1] for line in positive_lines}),
        positive_lines,
    )


def _result_projection(
    result: OracleAllocationV2 | AllocationV2,
) -> tuple[str, int, int, int, int, tuple[tuple[str, str, str, int, int, int], ...]]:
    return (
        result.status.value,
        result.fulfilled_quantity,
        result.total_payment.amount_paise,
        result.soft_preference_unit_score,
        result.winner_count,
        tuple(
            (
                line.offer_id,
                line.merchant_id,
                line.sku_id,
                line.allocated_quantity,
                line.unit_payment.amount_paise,
                line.line_payment.amount_paise,
            )
            for line in result.lines
        ),
    )


def _micro_market(
    rng: random.Random,
    case_index: int,
) -> tuple[BuyerPolicyV2, tuple[SignedMerchantOfferV2, ...]]:
    merchant_count = rng.randint(2, 4)
    eligible = tuple(_merchant_id(index) for index in range(1, merchant_count + 1))
    requested = rng.randint(1, 6)
    minimum = rng.randint(1, requested)
    max_winners = rng.randint(1, min(merchant_count, requested))
    use_soft = rng.choice((False, True))
    policy = _policy(
        market=_market(
            requested=requested,
            minimum=minimum,
            max_winners=max_winners,
            soft=(
                _soft(
                    key="preferred",
                    value_type=AttributeValueType.BOOLEAN,
                    value=True,
                ),
            )
            if use_soft
            else (),
            market_id=f"99000000-0000-4000-8000-{case_index + 1:012x}",
        ),
        budget=rng.randint(0, 30),
        eligible=eligible,
    )
    offers: list[SignedMerchantOfferV2] = []
    sku_counter = case_index * 10 + 1
    for merchant_index in range(1, merchant_count + 1):
        lines: list[MerchantOfferLineV2] = []
        for _ in range(rng.randint(1, 2)):
            preferred = rng.choice((False, True))
            attributes = (
                _attribute(
                    key="preferred",
                    value_type=AttributeValueType.BOOLEAN,
                    value=preferred,
                    index=10_000 + sku_counter,
                ),
            )
            lines.append(
                _line(
                    sku_counter,
                    capacity=rng.randint(1, 3),
                    price=rng.randint(0, 5),
                    attributes=attributes,
                )
            )
            sku_counter += 1
        offers.append(_signed(policy, merchant_index, lines=tuple(lines)))
    rng.shuffle(offers)
    return policy, tuple(offers)


def test_240_deterministic_micro_markets_match_brute_oracle_and_production() -> None:
    rng = random.Random(18_003)
    for case_index in range(240):
        policy, offers = _micro_market(rng, case_index)
        brute = _brute_projection(policy, offers)
        oracle = _result_projection(
            compute_oracle_allocation_v2(buyer_policy=policy, signed_offers=offers)
        )
        production = _result_projection(
            allocate_market_v2(buyer_policy=policy, signed_offers=offers)
        )
        assert oracle == brute, case_index
        assert production == brute, case_index
