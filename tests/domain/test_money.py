from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    Currency,
    InvalidQuantityError,
    Money,
    MoneyOverflowError,
)


@pytest.mark.parametrize("amount_paise", [0, 1, MAX_MONEY_PAISE])
def test_money_accepts_bounded_integer_amounts(amount_paise: int) -> None:
    money = Money(amount_paise=amount_paise)

    assert money.amount_paise == amount_paise


@pytest.mark.parametrize(
    "amount_paise",
    [-1, MAX_MONEY_PAISE + 1, 1.0, True, False, "100", Decimal("100")],
)
def test_money_rejects_invalid_amounts(amount_paise: object) -> None:
    with pytest.raises(ValidationError):
        Money(amount_paise=amount_paise)


def test_money_defaults_to_inr() -> None:
    assert Money(amount_paise=0).currency is Currency.INR


def test_money_accepts_explicit_inr_string() -> None:
    assert Money(amount_paise=0, currency="INR").currency is Currency.INR


def test_money_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError):
        Money(amount_paise=0, currency="USD")


def test_money_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Money(amount_paise=0, unexpected=True)


def test_money_is_frozen() -> None:
    money = Money(amount_paise=1)

    with pytest.raises(ValidationError):
        money.amount_paise = 2


def test_checked_multiply_is_exact() -> None:
    result = Money(amount_paise=125).checked_multiply(4)

    assert result == Money(amount_paise=500, currency=Currency.INR)


def test_checked_multiply_zero_amount() -> None:
    assert Money(amount_paise=0).checked_multiply(4).amount_paise == 0


def test_checked_multiply_zero_quantity() -> None:
    assert Money(amount_paise=100).checked_multiply(0).amount_paise == 0


def test_checked_multiply_maximum_by_one() -> None:
    result = Money(amount_paise=MAX_MONEY_PAISE).checked_multiply(1)

    assert result.amount_paise == MAX_MONEY_PAISE


def test_checked_multiply_result_exactly_at_maximum() -> None:
    result = Money(amount_paise=MAX_MONEY_PAISE // 4).checked_multiply(4)

    assert result.amount_paise == MAX_MONEY_PAISE


def test_checked_multiply_result_one_above_maximum_raises() -> None:
    with pytest.raises(MoneyOverflowError):
        Money(amount_paise=99_990_001).checked_multiply(10_001)


@pytest.mark.parametrize("quantity", [-1, MAX_QUANTITY + 1, 1.0, True, "1"])
def test_checked_multiply_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises(InvalidQuantityError):
        Money(amount_paise=1).checked_multiply(quantity)


def test_checked_multiply_returns_new_money_without_mutating_original() -> None:
    original = Money(amount_paise=125)

    result = original.checked_multiply(4)

    assert result is not original
    assert original.amount_paise == 125
    assert result.currency is original.currency is Currency.INR


@st.composite
def _non_overflowing_pairs(draw: st.DrawFn) -> tuple[int, int]:
    quantity = draw(st.integers(min_value=0, max_value=MAX_QUANTITY))
    maximum_amount = MAX_MONEY_PAISE if quantity == 0 else MAX_MONEY_PAISE // quantity
    amount = draw(st.integers(min_value=0, max_value=maximum_amount))
    return amount, quantity


@given(_non_overflowing_pairs())
def test_checked_multiply_matches_integer_arithmetic(pair: tuple[int, int]) -> None:
    amount, quantity = pair

    result = Money(amount_paise=amount).checked_multiply(quantity)

    assert result.amount_paise == amount * quantity


@st.composite
def _overflowing_pairs(draw: st.DrawFn) -> tuple[int, int]:
    quantity = draw(st.integers(min_value=2, max_value=MAX_QUANTITY))
    minimum_overflowing_amount = MAX_MONEY_PAISE // quantity + 1
    amount = draw(st.integers(min_value=minimum_overflowing_amount, max_value=MAX_MONEY_PAISE))
    return amount, quantity


@given(_overflowing_pairs())
def test_checked_multiply_rejects_every_generated_overflow(pair: tuple[int, int]) -> None:
    amount, quantity = pair

    with pytest.raises(MoneyOverflowError):
        Money(amount_paise=amount).checked_multiply(quantity)
