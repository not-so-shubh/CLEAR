import pytest
from pydantic import ValidationError

import clear_market.oracle as oracle
from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, Money
from clear_market.oracle import OracleAllocation, OracleAllocationStatus

_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_MERCHANT_ID = "30000000-0000-4000-8000-000000000001"
_BID_ID = "40000000-0000-4000-8000-000000000001"
_POLICY_COMMITMENT = "a" * 64


def _feasible_oracle_allocation(**overrides: object) -> OracleAllocation:
    fields: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment": _POLICY_COMMITMENT,
        "status": OracleAllocationStatus.FEASIBLE,
        "winner_merchant_id": _MERCHANT_ID,
        "winning_bid_id": _BID_ID,
        "allocated_quantity": 4,
        "winning_unit_price": Money(amount_paise=100),
        "payment_unit_price": Money(amount_paise=110),
        "total_payment": Money(amount_paise=440),
    }
    fields.update(overrides)
    return OracleAllocation(**fields)


def _infeasible_oracle_allocation(**overrides: object) -> OracleAllocation:
    fields: dict[str, object] = {
        "market_id": _MARKET_ID,
        "buyer_policy_commitment": _POLICY_COMMITMENT,
        "status": OracleAllocationStatus.INFEASIBLE,
    }
    fields.update(overrides)
    return OracleAllocation(**fields)


def test_oracle_public_api_is_exact() -> None:
    assert oracle.__all__ == (
        "OracleAllocation",
        "OracleAllocationStatus",
        "compute_oracle_allocation",
    )


def test_oracle_allocation_status_is_exact() -> None:
    assert tuple((status.name, status.value) for status in OracleAllocationStatus) == (
        ("FEASIBLE", "feasible"),
        ("INFEASIBLE", "infeasible"),
    )


def test_valid_feasible_oracle_allocation_is_accepted() -> None:
    allocation = _feasible_oracle_allocation()

    assert allocation.status is OracleAllocationStatus.FEASIBLE
    assert allocation.winner_merchant_id == _MERCHANT_ID
    assert allocation.winning_bid_id == _BID_ID
    assert allocation.allocated_quantity == 4
    assert allocation.winning_unit_price == Money(amount_paise=100)
    assert allocation.payment_unit_price == Money(amount_paise=110)
    assert allocation.total_payment == Money(amount_paise=440)


def test_valid_infeasible_oracle_allocation_is_accepted() -> None:
    allocation = _infeasible_oracle_allocation()

    assert allocation.status is OracleAllocationStatus.INFEASIBLE
    assert allocation.winner_merchant_id is None
    assert allocation.winning_bid_id is None
    assert allocation.allocated_quantity is None
    assert allocation.winning_unit_price is None
    assert allocation.payment_unit_price is None
    assert allocation.total_payment is None


def test_oracle_allocation_has_exact_fields_and_protocol_defaults() -> None:
    allocation = _feasible_oracle_allocation()

    assert tuple(OracleAllocation.model_fields) == (
        "schema_version",
        "market_id",
        "buyer_policy_commitment_version",
        "buyer_policy_commitment",
        "mechanism_version",
        "status",
        "winner_merchant_id",
        "winning_bid_id",
        "allocated_quantity",
        "winning_unit_price",
        "payment_unit_price",
        "total_payment",
    )
    assert allocation.schema_version == "1"
    assert allocation.buyer_policy_commitment_version == "sha256-clear-json-v1"
    assert allocation.mechanism_version == "reverse_second_price_v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("buyer_policy_commitment_version", "sha256-other-v1"),
        ("mechanism_version", "reverse_first_price_v1"),
    ],
)
def test_oracle_allocation_rejects_unsupported_protocol_values(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(**{field: value})


def test_oracle_allocation_is_frozen() -> None:
    allocation = _feasible_oracle_allocation()

    with pytest.raises(ValidationError):
        allocation.status = OracleAllocationStatus.INFEASIBLE


def test_oracle_allocation_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(unexpected=True)


def test_oracle_allocation_accepts_exact_lowercase_commitment() -> None:
    allocation = _feasible_oracle_allocation(buyer_policy_commitment=_POLICY_COMMITMENT)

    assert allocation.buyer_policy_commitment == _POLICY_COMMITMENT


@pytest.mark.parametrize(
    "commitment",
    [
        "a" * 63,
        "a" * 65,
        "A" * 64,
        f" {_POLICY_COMMITMENT}",
        f"{_POLICY_COMMITMENT} ",
        f"0x{_POLICY_COMMITMENT}",
        f"sha256:{_POLICY_COMMITMENT}",
        f"g{_POLICY_COMMITMENT[1:]}",
        _POLICY_COMMITMENT.encode(),
        1,
        None,
    ],
)
def test_oracle_allocation_rejects_invalid_commitment_representation(
    commitment: object,
) -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(buyer_policy_commitment=commitment)


@pytest.mark.parametrize(
    "missing_field",
    [
        "winner_merchant_id",
        "winning_bid_id",
        "allocated_quantity",
        "winning_unit_price",
        "payment_unit_price",
        "total_payment",
    ],
)
def test_feasible_oracle_allocation_rejects_missing_evidence(missing_field: str) -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(**{missing_field: None})


def test_infeasible_oracle_allocation_rejects_winner_evidence() -> None:
    with pytest.raises(ValidationError):
        _infeasible_oracle_allocation(winner_merchant_id=_MERCHANT_ID)


def test_infeasible_oracle_allocation_rejects_payment_evidence() -> None:
    with pytest.raises(ValidationError):
        _infeasible_oracle_allocation(total_payment=Money(amount_paise=0))


def test_oracle_allocation_rejects_payment_below_winning_bid() -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(
            winning_unit_price=Money(amount_paise=111),
            payment_unit_price=Money(amount_paise=110),
        )


def test_oracle_allocation_rejects_total_payment_mismatch() -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(total_payment=Money(amount_paise=439))


def test_oracle_allocation_converts_multiplication_overflow_to_validation_error() -> None:
    with pytest.raises(ValidationError):
        _feasible_oracle_allocation(
            allocated_quantity=MAX_QUANTITY,
            winning_unit_price=Money(amount_paise=1),
            payment_unit_price=Money(amount_paise=MAX_MONEY_PAISE),
            total_payment=Money(amount_paise=MAX_MONEY_PAISE),
        )
