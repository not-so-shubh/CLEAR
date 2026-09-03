from collections.abc import Callable
from itertools import permutations
from pathlib import Path

import pytest
from pydantic import ValidationError

import clear_market.mechanism.v2 as mechanism_v2
from clear_market.commerce.market import MAX_SOFT_PREFERENCES
from clear_market.commerce.merchant import MAX_OFFER_LINES
from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, MAX_SELLERS, Currency, Money
from clear_market.mechanism.v2 import (
    ALLOCATION_LINE_V2_VERSION,
    ALLOCATION_V2_VERSION,
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    AllocationLineV2,
    AllocationStatusV2,
    AllocationV2,
    MechanismV2Error,
    MechanismV2ErrorCode,
)

_MARKET_ID = "60000000-0000-4000-8000-000000000001"
_COMMITMENT = "a" * 64


def _merchant_id(index: int) -> str:
    return f"61000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"62000000-0000-4000-8000-{index:012x}"


def _offer_id(index: int) -> str:
    return f"63000000-0000-4000-8000-{index:012x}"


def _line(
    index: int = 1,
    *,
    merchant_index: int = 1,
    offer_index: int | None = None,
    sku_index: int | None = None,
    quantity: int = 2,
    unit_payment_paise: int = 100,
    **changes: object,
) -> AllocationLineV2:
    offer = index if offer_index is None else offer_index
    sku = index if sku_index is None else sku_index
    values: dict[str, object] = {
        "offer_id": _offer_id(offer),
        "merchant_id": _merchant_id(merchant_index),
        "sku_id": _sku_id(sku),
        "allocated_quantity": quantity,
        "unit_payment": Money(amount_paise=unit_payment_paise),
        "line_payment": Money(amount_paise=quantity * unit_payment_paise),
        **changes,
    }
    return AllocationLineV2(**values)


def _feasible_lines() -> tuple[AllocationLineV2, ...]:
    return (
        _line(3, merchant_index=2, quantity=2, unit_payment_paise=50),
        _line(2, merchant_index=1, offer_index=1, quantity=1, unit_payment_paise=0),
        _line(1, merchant_index=1, quantity=3, unit_payment_paise=100),
    )


def _allocation(**changes: object) -> AllocationV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": AllocationStatusV2.FEASIBLE,
        "fulfilled_quantity": 6,
        "total_payment": Money(amount_paise=400),
        "soft_preference_unit_score": 7,
        "winner_count": 2,
        "lines": _feasible_lines(),
        **changes,
    }
    return AllocationV2(**values)


def _infeasible(**changes: object) -> AllocationV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": AllocationStatusV2.INFEASIBLE,
        "fulfilled_quantity": 0,
        "total_payment": Money(amount_paise=0),
        "soft_preference_unit_score": 0,
        "winner_count": 0,
        "lines": (),
        **changes,
    }
    return AllocationV2(**values)


def test_version_constants_are_exact() -> None:
    assert HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION == "heterogeneous-pay-as-bid-v2"
    assert QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION == "quantity-cost-soft-objective-v2"
    assert ALLOCATION_LINE_V2_VERSION == "allocation-line-v2"
    assert ALLOCATION_V2_VERSION == "allocation-v2"


def test_public_api_is_exact() -> None:
    assert mechanism_v2.__all__ == (
        "HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION",
        "QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION",
        "ALLOCATION_LINE_V2_VERSION",
        "ALLOCATION_V2_VERSION",
        "AllocationStatusV2",
        "AllocationLineV2",
        "AllocationV2",
        "MechanismV2ErrorCode",
        "MechanismV2Error",
    )


def test_allocation_status_contract_is_exact() -> None:
    assert tuple(AllocationStatusV2) == (
        AllocationStatusV2.FEASIBLE,
        AllocationStatusV2.INFEASIBLE,
    )
    assert tuple(status.value for status in AllocationStatusV2) == (
        "FEASIBLE",
        "INFEASIBLE",
    )


def test_mechanism_error_code_contract_is_exact() -> None:
    assert tuple(MechanismV2ErrorCode) == (
        MechanismV2ErrorCode.INVALID_BUYER_POLICY,
        MechanismV2ErrorCode.INVALID_SIGNED_OFFER,
        MechanismV2ErrorCode.UNSUPPORTED_MECHANISM_VERSION,
        MechanismV2ErrorCode.UNSUPPORTED_OBJECTIVE_VERSION,
        MechanismV2ErrorCode.DUPLICATE_OFFER_ID,
        MechanismV2ErrorCode.DUPLICATE_MERCHANT_OFFER,
        MechanismV2ErrorCode.MERCHANT_NOT_ELIGIBLE,
        MechanismV2ErrorCode.MARKET_ID_MISMATCH,
        MechanismV2ErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH,
        MechanismV2ErrorCode.SOLVER_FAILURE,
    )
    assert tuple(code.value for code in MechanismV2ErrorCode) == tuple(
        code.name for code in MechanismV2ErrorCode
    )


def test_mechanism_error_has_exact_message_and_read_only_code() -> None:
    error = MechanismV2Error(MechanismV2ErrorCode.SOLVER_FAILURE)

    assert error.code is MechanismV2ErrorCode.SOLVER_FAILURE
    assert str(error) == "SOLVER_FAILURE"
    with pytest.raises(AttributeError):
        error.code = MechanismV2ErrorCode.INVALID_BUYER_POLICY  # type: ignore[misc]


def test_allocation_models_have_required_strict_revalidation_config() -> None:
    for model in (AllocationLineV2, AllocationV2):
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
        assert model.model_config["revalidate_instances"] == "always"


def test_allocation_line_has_exact_fields_versions_and_values() -> None:
    line = _line()

    assert tuple(AllocationLineV2.model_fields) == (
        "schema_version",
        "allocation_line_version",
        "offer_id",
        "merchant_id",
        "sku_id",
        "allocated_quantity",
        "unit_payment",
        "line_payment",
    )
    assert line.schema_version == "2"
    assert line.allocation_line_version == "allocation-line-v2"
    assert line.allocated_quantity == 2
    assert line.unit_payment == Money(amount_paise=100)
    assert line.line_payment == Money(amount_paise=200)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1"),
        ("allocation_line_version", "allocation-line-v3"),
    ],
)
def test_allocation_line_rejects_protocol_version_mismatch(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _line(**{field: value})


@pytest.mark.parametrize("field", ["offer_id", "merchant_id", "sku_id"])
@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "63000000-0000-1000-8000-000000000001",
        "63000000-0000-4000-8000-000000000001 ",
        1,
        None,
    ],
)
def test_allocation_line_requires_strict_canonical_uuid4(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _line(**{field: value})


@pytest.mark.parametrize("quantity", [0, MAX_QUANTITY + 1, True, False, 1.0, "1"])
def test_allocation_line_requires_strict_positive_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        _line(allocated_quantity=quantity)


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
@pytest.mark.parametrize(
    "value",
    [
        {"amount_paise": 100},
        100,
        True,
        None,
    ],
)
def test_allocation_line_requires_exact_money_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _line(**{field: value})


def test_allocation_line_allows_zero_unit_price() -> None:
    line = _line(unit_payment_paise=0)

    assert line.unit_payment == Money(amount_paise=0)
    assert line.line_payment == Money(amount_paise=0)


def test_allocation_line_rejects_payment_mismatch() -> None:
    with pytest.raises(ValidationError):
        _line(line_payment=Money(amount_paise=199))


def test_allocation_line_rejects_checked_multiplication_overflow() -> None:
    with pytest.raises(ValidationError):
        _line(
            quantity=2,
            unit_payment=Money(amount_paise=MAX_MONEY_PAISE),
            line_payment=Money(amount_paise=MAX_MONEY_PAISE),
        )


def test_allocation_line_revalidates_constructed_invalid_money() -> None:
    invalid_money = Money.model_construct(amount_paise=MAX_MONEY_PAISE + 1)

    with pytest.raises(ValidationError):
        _line(unit_payment=invalid_money)


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
def test_allocation_line_rejects_constructed_money_missing_amount_without_attribute_error(
    field: str,
) -> None:
    invalid_money = Money.model_construct(currency=Currency.INR)

    with pytest.raises(ValidationError):
        _line(**{field: invalid_money})


def test_allocation_line_strictly_revalidates_constructed_money_amount_type() -> None:
    invalid_money = Money.model_construct(amount_paise="100", currency=Currency.INR)

    with pytest.raises(ValidationError):
        _line(unit_payment=invalid_money)


def test_allocation_line_is_frozen_and_forbids_extra_fields() -> None:
    line = _line()
    with pytest.raises(ValidationError):
        line.allocated_quantity = 1
    with pytest.raises(ValidationError):
        _line(attributes=())


def test_allocation_v2_has_exact_fields_and_versions() -> None:
    allocation = _allocation()

    assert tuple(AllocationV2.model_fields) == (
        "schema_version",
        "allocation_version",
        "mechanism_version",
        "objective_version",
        "market_id",
        "buyer_policy_commitment_version",
        "buyer_policy_commitment_sha256",
        "status",
        "fulfilled_quantity",
        "total_payment",
        "soft_preference_unit_score",
        "winner_count",
        "lines",
    )
    assert allocation.schema_version == "2"
    assert allocation.allocation_version == "allocation-v2"
    assert allocation.mechanism_version == "heterogeneous-pay-as-bid-v2"
    assert allocation.objective_version == "quantity-cost-soft-objective-v2"
    assert allocation.buyer_policy_commitment_version == ("sha256-buyer-policy-v2-clear-json-v1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1"),
        ("allocation_version", "allocation-v3"),
        ("mechanism_version", "other-mechanism-v2"),
        ("objective_version", "other-objective-v2"),
        ("buyer_policy_commitment_version", "sha256-other-v2"),
    ],
)
def test_allocation_v2_rejects_protocol_version_mismatch(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(**{field: value})


@pytest.mark.parametrize(
    "digest",
    [
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "0x" + "a" * 64,
        "g" * 64,
        b"a" * 64,
        1,
        None,
    ],
)
def test_allocation_v2_requires_strict_lowercase_sha256(digest: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(buyer_policy_commitment_sha256=digest)


def test_valid_feasible_allocation_normalizes_lines_and_counts_distinct_merchants() -> None:
    allocation = _allocation()

    assert tuple((line.merchant_id, line.sku_id, line.offer_id) for line in allocation.lines) == (
        (_merchant_id(1), _sku_id(1), _offer_id(1)),
        (_merchant_id(1), _sku_id(2), _offer_id(1)),
        (_merchant_id(2), _sku_id(3), _offer_id(3)),
    )
    assert allocation.fulfilled_quantity == 6
    assert allocation.total_payment == Money(amount_paise=400)
    assert allocation.winner_count == 2
    assert len(allocation.lines) == 3


def test_valid_multiple_skus_for_same_merchant_and_offer_are_accepted() -> None:
    lines = (
        _line(2, merchant_index=1, offer_index=1, quantity=1, unit_payment_paise=0),
        _line(1, merchant_index=1, offer_index=1, quantity=3, unit_payment_paise=100),
    )

    allocation = _allocation(
        fulfilled_quantity=4,
        total_payment=Money(amount_paise=300),
        soft_preference_unit_score=0,
        winner_count=1,
        lines=lines,
    )

    assert tuple(line.offer_id for line in allocation.lines) == (_offer_id(1), _offer_id(1))
    assert tuple(line.sku_id for line in allocation.lines) == (_sku_id(1), _sku_id(2))


def test_equivalent_line_input_permutations_produce_equal_allocations() -> None:
    lines = _feasible_lines()
    expected = _allocation(lines=lines)

    assert all(
        _allocation(lines=ordered_lines) == expected for ordered_lines in permutations(lines)
    )


def test_allocation_v2_requires_exact_tuple_lines() -> None:
    with pytest.raises(ValidationError):
        _allocation(lines=list(_feasible_lines()))


def test_allocation_v2_rejects_duplicate_offer_and_sku_pair() -> None:
    first = _line(1, merchant_index=1, sku_index=1)
    duplicate = _line(
        1,
        merchant_index=2,
        sku_index=1,
        quantity=1,
        unit_payment_paise=0,
    )
    with pytest.raises(ValidationError):
        _allocation(
            fulfilled_quantity=3,
            total_payment=Money(amount_paise=200),
            soft_preference_unit_score=0,
            lines=(first, duplicate),
        )


def test_allocation_v2_rejects_duplicate_merchant_and_sku_pair() -> None:
    first = _line(1, merchant_index=1, sku_index=1)
    duplicate = _line(
        2,
        merchant_index=1,
        sku_index=1,
        quantity=1,
        unit_payment_paise=0,
    )
    with pytest.raises(ValidationError):
        _allocation(
            fulfilled_quantity=3,
            total_payment=Money(amount_paise=200),
            soft_preference_unit_score=0,
            winner_count=1,
            lines=(first, duplicate),
        )


def test_allocation_v2_rejects_one_merchant_mapped_to_multiple_offers() -> None:
    lines = (
        _line(1, merchant_index=1, offer_index=1, sku_index=1),
        _line(2, merchant_index=1, offer_index=2, sku_index=2),
    )

    with pytest.raises(ValidationError, match="one merchant must map to one offer"):
        _allocation(
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
            soft_preference_unit_score=0,
            winner_count=1,
            lines=lines,
        )


def test_allocation_v2_rejects_one_offer_mapped_to_multiple_merchants() -> None:
    lines = (
        _line(1, merchant_index=1, offer_index=1, sku_index=1),
        _line(2, merchant_index=2, offer_index=1, sku_index=2),
    )

    with pytest.raises(ValidationError, match="one offer must map to one merchant"):
        _allocation(
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
            soft_preference_unit_score=0,
            winner_count=2,
            lines=lines,
        )


def test_allocation_v2_rejects_wrong_quantity_sum() -> None:
    with pytest.raises(ValidationError):
        _allocation(fulfilled_quantity=5)


def test_allocation_v2_rejects_wrong_payment_sum() -> None:
    with pytest.raises(ValidationError):
        _allocation(total_payment=Money(amount_paise=399))


def test_allocation_v2_rejects_payment_sum_above_money_bound() -> None:
    lines = (
        _line(1, unit_payment_paise=MAX_MONEY_PAISE // 2 + 1, quantity=1),
        _line(
            2,
            merchant_index=2,
            unit_payment_paise=MAX_MONEY_PAISE // 2 + 1,
            quantity=1,
        ),
    )

    with pytest.raises(ValidationError):
        _allocation(
            fulfilled_quantity=2,
            total_payment=Money(amount_paise=MAX_MONEY_PAISE),
            soft_preference_unit_score=0,
            lines=lines,
        )


def test_allocation_v2_rejects_wrong_distinct_winner_count() -> None:
    with pytest.raises(ValidationError):
        _allocation(winner_count=3)


@pytest.mark.parametrize(
    "value",
    [True, False, 1.0, "1", -1, MAX_QUANTITY * MAX_SOFT_PREFERENCES + 1],
)
def test_allocation_v2_requires_bounded_strict_soft_score(value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(soft_preference_unit_score=value)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", -1, MAX_SELLERS + 1])
def test_allocation_v2_requires_bounded_strict_winner_count(value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(winner_count=value)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", -1, MAX_QUANTITY + 1])
def test_allocation_v2_requires_bounded_strict_fulfilled_quantity(value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(fulfilled_quantity=value)


def test_allocation_v2_requires_exact_total_money_and_revalidates_it() -> None:
    with pytest.raises(ValidationError):
        _allocation(total_payment={"amount_paise": 400})
    with pytest.raises(ValidationError):
        _allocation(total_payment=Money.model_construct(amount_paise=MAX_MONEY_PAISE + 1))


def test_allocation_v2_rejects_constructed_total_money_missing_amount() -> None:
    invalid_money = Money.model_construct(currency=Currency.INR)

    with pytest.raises(ValidationError):
        _allocation(total_payment=invalid_money)


def test_allocation_v2_revalidates_constructed_invalid_line() -> None:
    invalid_line = AllocationLineV2.model_construct(
        offer_id=_offer_id(1),
        merchant_id=_merchant_id(1),
        sku_id=_sku_id(1),
        allocated_quantity=2,
        unit_payment=Money.model_construct(amount_paise=MAX_MONEY_PAISE + 1),
        line_payment=Money(amount_paise=0),
    )

    with pytest.raises(ValidationError):
        _allocation(
            fulfilled_quantity=2,
            total_payment=Money(amount_paise=0),
            soft_preference_unit_score=0,
            winner_count=1,
            lines=(invalid_line,),
        )


def test_allocation_line_count_bound_is_exact() -> None:
    line_count = MAX_SELLERS * MAX_OFFER_LINES
    lines = tuple(
        _line(
            index,
            merchant_index=(index % MAX_SELLERS) + 1,
            offer_index=(index % MAX_SELLERS) + 1,
            sku_index=index,
            quantity=1,
            unit_payment_paise=0,
        )
        for index in range(1, line_count + 1)
    )

    allocation = _allocation(
        fulfilled_quantity=line_count,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=MAX_SELLERS,
        lines=lines,
    )
    assert len(allocation.lines) == line_count

    with pytest.raises(ValidationError):
        _allocation(
            fulfilled_quantity=line_count + 1,
            total_payment=Money(amount_paise=0),
            soft_preference_unit_score=0,
            winner_count=MAX_SELLERS,
            lines=(
                *lines,
                _line(
                    line_count + 1,
                    merchant_index=1,
                    offer_index=1,
                    sku_index=line_count + 1,
                    quantity=1,
                    unit_payment_paise=0,
                ),
            ),
        )


def test_valid_infeasible_allocation_has_exact_zero_shape() -> None:
    allocation = _infeasible()

    assert allocation.status is AllocationStatusV2.INFEASIBLE
    assert allocation.fulfilled_quantity == 0
    assert allocation.total_payment == Money(amount_paise=0)
    assert allocation.soft_preference_unit_score == 0
    assert allocation.winner_count == 0
    assert allocation.lines == ()


@pytest.mark.parametrize(
    "change",
    [
        {"fulfilled_quantity": 1},
        {"total_payment": Money(amount_paise=1)},
        {"soft_preference_unit_score": 1},
        {"winner_count": 1},
        {
            "fulfilled_quantity": 2,
            "total_payment": Money(amount_paise=200),
            "winner_count": 1,
            "lines": (_line(),),
        },
    ],
)
def test_infeasible_allocation_rejects_each_nonzero_result_component(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _infeasible(**change)


@pytest.mark.parametrize(
    "change",
    [
        {
            "fulfilled_quantity": 0,
            "total_payment": Money(amount_paise=0),
            "winner_count": 0,
            "lines": (),
        },
        {"fulfilled_quantity": 0},
        {"winner_count": 0},
        {"lines": ()},
    ],
)
def test_feasible_allocation_rejects_missing_positive_allocation_shape(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _allocation(**change)


def test_allocation_v2_is_frozen_and_forbids_extra_fields() -> None:
    allocation = _allocation()
    with pytest.raises(ValidationError):
        allocation.status = AllocationStatusV2.INFEASIBLE
    with pytest.raises(ValidationError):
        _allocation(reason="trusted prose")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AllocationLineV2(
            offer_id=_offer_id(1),
            merchant_id=_merchant_id(1),
            sku_id=_sku_id(1),
            allocated_quantity=1,
            unit_payment=Money(amount_paise=1),
            line_payment=Money(amount_paise=1),
            provenance="VERIFIED",
        ),
        lambda: _allocation(execution_plan_id=_offer_id(99)),
    ],
)
def test_result_models_reject_out_of_scope_fields(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_normative_contract_has_required_sections_and_claim_boundaries() -> None:
    contract = Path("docs/MECHANISM_V2_CONTRACT.md").read_text(encoding="utf-8")

    expected_sections = tuple(
        f"## {index}. {title}"
        for index, title in enumerate(
            (
                "Scope",
                "Trust boundary",
                "Input validation",
                "Hard constraints",
                "Soft preferences",
                "Feasible allocation",
                "Pay-as-bid payment",
                "Lexicographic objective",
                "Canonical tie resolution",
                "Infeasibility",
                "CP-SAT production strategy",
                "Independent oracle",
                "Security / incentive limitations",
            ),
            start=1,
        )
    )
    assert tuple(line for line in contract.splitlines() if line.startswith("## ")) == (
        expected_sections
    )
    assert (
        "Cost precedes soft preferences because the current buyer policy supplies no monetary "
        "utility weight for a soft preference."
    ) in contract
    assert (
        "CLEAR does not claim that heterogeneous-pay-as-bid-v2 is truthful, strategy-proof, "
        "incentive compatible, collusion resistant, or Sybil resistant."
    ) in contract
    assert "Fresh validation before canonical semantic ordering" in contract
    assert "(merchant_id, offer_id)" in contract
