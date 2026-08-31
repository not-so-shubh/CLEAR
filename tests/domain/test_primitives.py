from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

import clear_market.domain as domain
from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    CanonicalUUID4,
    Currency,
    InvalidQuantityError,
    Money,
    MoneyOverflowError,
    PositiveQuantity,
    Quantity,
    UTCDateTime,
)

_VALID_UUID4 = "550e8400-e29b-41d4-a716-446655440000"


class _QuantityModel(BaseModel):
    value: Quantity


class _PositiveQuantityModel(BaseModel):
    value: PositiveQuantity


class _UUIDModel(BaseModel):
    value: CanonicalUUID4


class _DateTimeModel(BaseModel):
    value: UTCDateTime


class _NoOffsetTimezone(tzinfo):
    def utcoffset(self, _value: datetime | None) -> None:
        return None


def test_domain_public_api_is_exact() -> None:
    assert domain.__all__ == (
        "MAX_MONEY_PAISE",
        "MAX_QUANTITY",
        "MIN_SELLERS",
        "MAX_SELLERS",
        "CanonicalUUID4",
        "Currency",
        "InvalidQuantityError",
        "Money",
        "MoneyOverflowError",
        "PositiveQuantity",
        "Quantity",
        "UTCDateTime",
        "MarketSpec",
        "MerchantIdentity",
        "BuyerPolicy",
    )
    assert MAX_MONEY_PAISE == 1_000_000_000_000
    assert MAX_QUANTITY == 1_000_000
    assert Currency.INR.value == "INR"
    assert issubclass(InvalidQuantityError, ValueError)
    assert issubclass(MoneyOverflowError, ArithmeticError)
    assert Money(amount_paise=0).amount_paise == 0


@pytest.mark.parametrize("value", [0, MAX_QUANTITY])
def test_quantity_accepts_bounds(value: int) -> None:
    validated = _QuantityModel(value=value).value

    assert validated == value
    assert type(validated) is int


@pytest.mark.parametrize(
    "value",
    [-1, MAX_QUANTITY + 1, 1.0, True, "1", Decimal("1")],
)
def test_quantity_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValidationError):
        _QuantityModel(value=value)


@pytest.mark.parametrize("value", [1, MAX_QUANTITY])
def test_positive_quantity_accepts_bounds(value: int) -> None:
    validated = _PositiveQuantityModel(value=value).value

    assert validated == value
    assert type(validated) is int


@pytest.mark.parametrize(
    "value",
    [0, -1, MAX_QUANTITY + 1, 1.0, True, "1", Decimal("1")],
)
def test_positive_quantity_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValidationError):
        _PositiveQuantityModel(value=value)


def test_canonical_uuid4_accepts_canonical_literal_as_str() -> None:
    validated = _UUIDModel(value=_VALID_UUID4).value

    assert validated == _VALID_UUID4
    assert type(validated) is str


@pytest.mark.parametrize(
    "value",
    [
        _VALID_UUID4.upper(),
        f" {_VALID_UUID4}",
        f"{_VALID_UUID4} ",
        _VALID_UUID4.replace("-", ""),
        UUID(_VALID_UUID4),
        "not-a-uuid",
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "6fa459ea-ee8a-3ca4-894e-db77e160355e",
        1,
        _VALID_UUID4.encode(),
        None,
    ],
)
def test_canonical_uuid4_rejects_invalid_input(value: object) -> None:
    with pytest.raises(ValidationError):
        _UUIDModel(value=value)


def test_utc_datetime_accepts_utc_aware_value() -> None:
    value = datetime(2026, 8, 31, 6, 30, tzinfo=UTC)

    validated = _DateTimeModel(value=value).value

    assert validated == value
    assert validated.utcoffset() == timedelta(0)


def test_utc_datetime_normalizes_positive_offset() -> None:
    value = datetime(
        2026,
        8,
        31,
        12,
        0,
        0,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    validated = _DateTimeModel(value=value).value

    assert validated == datetime(2026, 8, 31, 6, 30, 0, 123_456, tzinfo=UTC)
    assert validated.microsecond == 123_456


def test_utc_datetime_normalizes_negative_offset() -> None:
    value = datetime(2026, 8, 31, 1, 15, tzinfo=timezone(-timedelta(hours=4)))

    validated = _DateTimeModel(value=value).value

    assert validated == datetime(2026, 8, 31, 5, 15, tzinfo=UTC)


def test_utc_datetime_rejects_tzinfo_without_offset() -> None:
    value = datetime(2026, 8, 31, 6, 30, tzinfo=_NoOffsetTimezone())

    assert value.tzinfo is not None
    assert value.utcoffset() is None
    with pytest.raises(ValidationError):
        _DateTimeModel(value=value)


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 31, 6, 30),
        "2026-08-31T06:30:00.000000Z",
        date(2026, 8, 31),
        None,
    ],
)
def test_utc_datetime_rejects_invalid_input(value: object) -> None:
    with pytest.raises(ValidationError):
        _DateTimeModel(value=value)


@st.composite
def _aware_datetimes(draw: st.DrawFn) -> datetime:
    naive = draw(
        st.datetimes(
            min_value=datetime(2000, 1, 2),
            max_value=datetime(2030, 12, 30, 23, 59, 59, 999_999),
        )
    )
    offset_minutes = draw(st.integers(min_value=-1_439, max_value=1_439))
    return naive.replace(tzinfo=timezone(timedelta(minutes=offset_minutes)))


@given(_aware_datetimes())
def test_utc_normalization_preserves_absolute_instant(value: datetime) -> None:
    normalized = _DateTimeModel(value=value).value

    assert normalized == value.astimezone(UTC)
    assert normalized.astimezone(UTC) == value.astimezone(UTC)
