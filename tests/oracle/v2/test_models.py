from collections.abc import Callable

import pytest
from pydantic import ValidationError

import clear_market.oracle.v2 as oracle_v2
from clear_market.commerce.market import MAX_SOFT_PREFERENCES
from clear_market.commerce.merchant import MAX_OFFER_LINES
from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, MAX_SELLERS, Currency, Money
from clear_market.oracle.v2 import (
    HETEROGENEOUS_ORACLE_V2_VERSION,
    ORACLE_ALLOCATION_LINE_V2_VERSION,
    ORACLE_ALLOCATION_V2_VERSION,
    OracleAllocationLineV2,
    OracleAllocationStatusV2,
    OracleAllocationV2,
    OracleV2Error,
    OracleV2ErrorCode,
)

_MARKET_ID = "80000000-0000-4000-8000-000000000001"
_COMMITMENT = "a" * 64


def _merchant_id(index: int) -> str:
    return f"81000000-0000-4000-8000-{index:012x}"


def _offer_id(index: int) -> str:
    return f"82000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"83000000-0000-4000-8000-{index:012x}"


def _line(
    index: int = 1,
    *,
    merchant_index: int = 1,
    offer_index: int | None = None,
    sku_index: int | None = None,
    quantity: int = 2,
    price: int = 100,
    **changes: object,
) -> OracleAllocationLineV2:
    offer = merchant_index if offer_index is None else offer_index
    sku = index if sku_index is None else sku_index
    values: dict[str, object] = {
        "offer_id": _offer_id(offer),
        "merchant_id": _merchant_id(merchant_index),
        "sku_id": _sku_id(sku),
        "allocated_quantity": quantity,
        "unit_payment": Money(amount_paise=price),
        "line_payment": Money(amount_paise=quantity * price),
        **changes,
    }
    return OracleAllocationLineV2(**values)


def _lines() -> tuple[OracleAllocationLineV2, ...]:
    return (
        _line(3, merchant_index=2, quantity=2, price=50),
        _line(2, merchant_index=1, quantity=1, price=0),
        _line(1, merchant_index=1, quantity=3, price=100),
    )


def _allocation(**changes: object) -> OracleAllocationV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": OracleAllocationStatusV2.FEASIBLE,
        "fulfilled_quantity": 6,
        "total_payment": Money(amount_paise=400),
        "soft_preference_unit_score": 7,
        "winner_count": 2,
        "lines": _lines(),
        **changes,
    }
    return OracleAllocationV2(**values)


def _infeasible(**changes: object) -> OracleAllocationV2:
    values: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": OracleAllocationStatusV2.INFEASIBLE,
        "fulfilled_quantity": 0,
        "total_payment": Money(amount_paise=0),
        "soft_preference_unit_score": 0,
        "winner_count": 0,
        "lines": (),
        **changes,
    }
    return OracleAllocationV2(**values)


def test_version_constants_and_public_api_are_exact() -> None:
    assert HETEROGENEOUS_ORACLE_V2_VERSION == "independent-heterogeneous-oracle-v2"
    assert ORACLE_ALLOCATION_LINE_V2_VERSION == "oracle-allocation-line-v2"
    assert ORACLE_ALLOCATION_V2_VERSION == "oracle-allocation-v2"
    assert oracle_v2.__all__ == (
        "HETEROGENEOUS_ORACLE_V2_VERSION",
        "ORACLE_ALLOCATION_LINE_V2_VERSION",
        "ORACLE_ALLOCATION_V2_VERSION",
        "OracleAllocationStatusV2",
        "OracleAllocationLineV2",
        "OracleAllocationV2",
        "OracleV2ErrorCode",
        "OracleV2Error",
        "compute_oracle_allocation_v2",
    )


def test_status_and_error_code_contracts_are_exact() -> None:
    assert tuple(status.value for status in OracleAllocationStatusV2) == (
        "FEASIBLE",
        "INFEASIBLE",
    )
    assert tuple(code.value for code in OracleV2ErrorCode) == (
        "INVALID_BUYER_POLICY",
        "INVALID_SIGNED_OFFER",
        "UNSUPPORTED_MECHANISM_VERSION",
        "UNSUPPORTED_OBJECTIVE_VERSION",
        "DUPLICATE_OFFER_ID",
        "DUPLICATE_MERCHANT_OFFER",
        "MERCHANT_NOT_ELIGIBLE",
        "MARKET_ID_MISMATCH",
        "BUYER_POLICY_COMMITMENT_MISMATCH",
    )


def test_oracle_error_has_exact_message_and_read_only_code() -> None:
    error = OracleV2Error(OracleV2ErrorCode.INVALID_SIGNED_OFFER)
    assert str(error) == "INVALID_SIGNED_OFFER"
    assert error.code is OracleV2ErrorCode.INVALID_SIGNED_OFFER
    with pytest.raises(AttributeError):
        error.code = OracleV2ErrorCode.INVALID_BUYER_POLICY  # type: ignore[misc]


def test_models_have_exact_strict_immutable_config() -> None:
    for model in (OracleAllocationLineV2, OracleAllocationV2):
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
        assert model.model_config["revalidate_instances"] == "always"


def test_oracle_line_has_exact_fields_versions_and_payment() -> None:
    line = _line()
    assert tuple(OracleAllocationLineV2.model_fields) == (
        "schema_version",
        "oracle_allocation_line_version",
        "offer_id",
        "merchant_id",
        "sku_id",
        "allocated_quantity",
        "unit_payment",
        "line_payment",
    )
    assert line.schema_version == "2"
    assert line.oracle_allocation_line_version == "oracle-allocation-line-v2"
    assert line.line_payment == line.unit_payment.checked_multiply(line.allocated_quantity)


@pytest.mark.parametrize("field", ["offer_id", "merchant_id", "sku_id"])
@pytest.mark.parametrize("value", ["not-a-uuid", 1, None])
def test_oracle_line_requires_strict_canonical_uuid4(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _line(**{field: value})


@pytest.mark.parametrize("quantity", [0, MAX_QUANTITY + 1, True, 1.0, "1"])
def test_oracle_line_requires_strict_positive_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        _line(allocated_quantity=quantity)


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
@pytest.mark.parametrize("value", [{"amount_paise": 100}, 100, None])
def test_oracle_line_requires_exact_money(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _line(**{field: value})


@pytest.mark.parametrize("field", ["unit_payment", "line_payment"])
def test_constructed_money_missing_amount_does_not_leak_attribute_error(field: str) -> None:
    bad = Money.model_construct(currency=Currency.INR)
    with pytest.raises(ValidationError):
        _line(**{field: bad})


def test_constructed_money_wrong_amount_type_is_revalidated() -> None:
    bad = Money.model_construct(amount_paise="100", currency=Currency.INR)
    with pytest.raises(ValidationError):
        _line(unit_payment=bad)


def test_oracle_line_rejects_payment_mismatch_and_overflow() -> None:
    with pytest.raises(ValidationError):
        _line(line_payment=Money(amount_paise=199))
    with pytest.raises(ValidationError):
        _line(
            quantity=2,
            unit_payment=Money(amount_paise=MAX_MONEY_PAISE),
            line_payment=Money(amount_paise=MAX_MONEY_PAISE),
        )


def test_oracle_line_is_frozen_and_forbids_extra() -> None:
    line = _line()
    with pytest.raises(ValidationError):
        line.allocated_quantity = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _line(extra_field=True)


def test_oracle_allocation_has_exact_fields_and_fixed_versions() -> None:
    allocation = _allocation()
    assert tuple(OracleAllocationV2.model_fields) == (
        "schema_version",
        "oracle_allocation_version",
        "oracle_version",
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
    assert allocation.oracle_allocation_version == "oracle-allocation-v2"
    assert allocation.oracle_version == "independent-heterogeneous-oracle-v2"
    assert allocation.mechanism_version == "heterogeneous-pay-as-bid-v2"
    assert allocation.objective_version == "quantity-cost-soft-objective-v2"
    assert allocation.buyer_policy_commitment_version == "sha256-buyer-policy-v2-clear-json-v1"


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64, 1, None])
def test_oracle_allocation_requires_strict_digest(digest: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(buyer_policy_commitment_sha256=digest)


def test_oracle_allocation_requires_tuple_and_normalizes_lines() -> None:
    allocation = _allocation()
    assert allocation.lines == tuple(
        sorted(_lines(), key=lambda line: (line.merchant_id, line.sku_id, line.offer_id))
    )
    assert _allocation(lines=tuple(reversed(_lines()))) == allocation
    with pytest.raises(ValidationError):
        _allocation(lines=list(_lines()))


def test_oracle_allocation_revalidates_exact_nested_lines() -> None:
    malformed = OracleAllocationLineV2.model_construct(
        offer_id=_offer_id(1),
        merchant_id=_merchant_id(1),
        sku_id=_sku_id(1),
    )
    with pytest.raises(ValidationError):
        _allocation(lines=(malformed,))
    with pytest.raises(ValidationError):
        _allocation(lines=(_line(), object()))


def test_oracle_allocation_rejects_duplicate_line_keys() -> None:
    first = _line(1, merchant_index=1)
    with pytest.raises(ValidationError):
        _allocation(
            lines=(first, first), fulfilled_quantity=4, total_payment=Money(amount_paise=400)
        )
    with pytest.raises(ValidationError):
        _allocation(
            lines=(first, _line(2, merchant_index=1, sku_index=1)),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
        )


def test_oracle_allocation_enforces_offer_merchant_bijection() -> None:
    with pytest.raises(ValidationError, match="one oracle merchant must map to one offer"):
        _allocation(
            lines=(
                _line(1, merchant_index=1, offer_index=1),
                _line(2, merchant_index=1, offer_index=2),
            ),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
            winner_count=1,
        )
    with pytest.raises(ValidationError, match="one oracle offer must map to one merchant"):
        _allocation(
            lines=(
                _line(1, merchant_index=1, offer_index=1),
                _line(2, merchant_index=2, offer_index=1),
            ),
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=400),
        )


def test_multiple_skus_same_merchant_and_offer_are_valid() -> None:
    lines = (
        _line(1, merchant_index=1, offer_index=1),
        _line(2, merchant_index=1, offer_index=1),
    )
    allocation = _allocation(
        lines=lines,
        fulfilled_quantity=4,
        total_payment=Money(amount_paise=400),
        winner_count=1,
    )
    assert allocation.lines == lines


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulfilled_quantity", 5),
        ("total_payment", Money(amount_paise=399)),
        ("winner_count", 1),
    ],
)
def test_oracle_allocation_requires_exact_aggregates(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("soft_preference_unit_score", -1),
        ("soft_preference_unit_score", MAX_QUANTITY * MAX_SOFT_PREFERENCES + 1),
        ("soft_preference_unit_score", True),
        ("winner_count", -1),
        ("winner_count", MAX_SELLERS + 1),
        ("winner_count", True),
    ],
)
def test_oracle_allocation_requires_strict_bounded_counts(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(**{field: value})


def test_allocation_line_count_is_bounded() -> None:
    line = _line()
    with pytest.raises(ValidationError):
        _allocation(lines=(line,) * (MAX_SELLERS * MAX_OFFER_LINES + 1))


def test_infeasible_allocation_has_exact_zero_shape() -> None:
    assert _infeasible().model_dump(mode="python") == {
        "schema_version": "2",
        "oracle_allocation_version": "oracle-allocation-v2",
        "oracle_version": "independent-heterogeneous-oracle-v2",
        "mechanism_version": "heterogeneous-pay-as-bid-v2",
        "objective_version": "quantity-cost-soft-objective-v2",
        "market_id": _MARKET_ID,
        "buyer_policy_commitment_version": "sha256-buyer-policy-v2-clear-json-v1",
        "buyer_policy_commitment_sha256": _COMMITMENT,
        "status": OracleAllocationStatusV2.INFEASIBLE,
        "fulfilled_quantity": 0,
        "total_payment": {"amount_paise": 0, "currency": Currency.INR},
        "soft_preference_unit_score": 0,
        "winner_count": 0,
        "lines": (),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulfilled_quantity", 1),
        ("total_payment", Money(amount_paise=1)),
        ("soft_preference_unit_score", 1),
        ("winner_count", 1),
        ("lines", (_line(),)),
    ],
)
def test_infeasible_rejects_each_nonzero_component(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _infeasible(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulfilled_quantity", 0),
        ("winner_count", 0),
        ("lines", ()),
    ],
)
def test_feasible_requires_positive_shape(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _allocation(**{field: value})


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _allocation(total_payment=Money.model_construct(currency=Currency.INR)),
        lambda: _allocation(extra_field=True),
    ],
)
def test_oracle_allocation_rejects_malformed_money_and_extra_fields(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_oracle_allocation_is_frozen() -> None:
    allocation = _allocation()
    with pytest.raises(ValidationError):
        allocation.winner_count = 3  # type: ignore[misc]
