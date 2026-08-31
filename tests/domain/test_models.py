from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    MAX_SELLERS,
    MIN_SELLERS,
    BuyerPolicy,
    MarketSpec,
    MerchantIdentity,
    Money,
)

_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_IDS = (
    "30000000-0000-4000-8000-000000000001",
    "30000000-0000-4000-8000-000000000002",
    "30000000-0000-4000-8000-000000000003",
    "30000000-0000-4000-8000-000000000004",
    "30000000-0000-4000-8000-000000000005",
    "30000000-0000-4000-8000-000000000006",
    "30000000-0000-4000-8000-000000000007",
    "30000000-0000-4000-8000-000000000008",
    "30000000-0000-4000-8000-000000000009",
    "30000000-0000-4000-8000-00000000000a",
    "30000000-0000-4000-8000-00000000000b",
    "30000000-0000-4000-8000-00000000000c",
    "30000000-0000-4000-8000-00000000000d",
    "30000000-0000-4000-8000-00000000000e",
    "30000000-0000-4000-8000-00000000000f",
    "30000000-0000-4000-8000-000000000010",
    "30000000-0000-4000-8000-000000000011",
    "30000000-0000-4000-8000-000000000012",
    "30000000-0000-4000-8000-000000000013",
    "30000000-0000-4000-8000-000000000014",
    "30000000-0000-4000-8000-000000000015",
)
_PUBLIC_KEY_A = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_PUBLIC_KEY_B = "1111111111111111111111111111111111111111111111111111111111111111"
_DEADLINE = datetime(2026, 9, 1, 12, 0, 0, 123_456, tzinfo=UTC)


def _market_spec(requested_quantity: object = 4) -> MarketSpec:
    return MarketSpec(
        market_id=_MARKET_ID,
        buyer_id=_BUYER_ID,
        requested_quantity=requested_quantity,
    )


def _merchant(index: int, public_key: object = _PUBLIC_KEY_A) -> MerchantIdentity:
    return MerchantIdentity(
        merchant_id=_MERCHANT_IDS[index],
        ed25519_public_key_hex=public_key,
    )


def _merchants(count: int) -> tuple[MerchantIdentity, ...]:
    return tuple(_merchant(index) for index in range(count))


def _policy(
    *,
    eligible_merchants: object | None = None,
    requested_quantity: object = 4,
    reserve_unit_price_paise: object = 125,
    max_total_payment_paise: object = 500,
    bid_deadline: object = _DEADLINE,
    mechanism_version: object = "reverse_second_price_v1",
    tie_break_rule: object = "merchant_id_lexicographic_ascending",
) -> BuyerPolicy:
    merchants = _merchants(MIN_SELLERS) if eligible_merchants is None else eligible_merchants
    return BuyerPolicy(
        market_spec=_market_spec(requested_quantity),
        max_total_payment=Money(amount_paise=max_total_payment_paise),
        reserve_unit_price=Money(amount_paise=reserve_unit_price_paise),
        eligible_merchants=merchants,
        bid_deadline=bid_deadline,
        mechanism_version=mechanism_version,
        tie_break_rule=tie_break_rule,
    )


def test_market_spec_accepts_valid_input() -> None:
    market = _market_spec()

    assert market.market_id == _MARKET_ID
    assert market.buyer_id == _BUYER_ID
    assert market.requested_quantity == 4


def test_market_spec_defaults_schema_version() -> None:
    assert _market_spec().schema_version == "1"


def test_market_spec_accepts_explicit_schema_version() -> None:
    market = MarketSpec(
        schema_version="1",
        market_id=_MARKET_ID,
        buyer_id=_BUYER_ID,
        requested_quantity=1,
    )

    assert market.schema_version == "1"


@pytest.mark.parametrize("schema_version", [1, "2", None])
def test_market_spec_rejects_unsupported_schema_version(schema_version: object) -> None:
    with pytest.raises(ValidationError):
        MarketSpec(
            schema_version=schema_version,
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=1,
        )


def test_market_spec_ids_remain_strings() -> None:
    market = _market_spec()

    assert type(market.market_id) is str
    assert type(market.buyer_id) is str


def test_market_spec_rejects_invalid_market_id() -> None:
    with pytest.raises(ValidationError):
        MarketSpec(
            market_id="not-a-uuid",
            buyer_id=_BUYER_ID,
            requested_quantity=1,
        )


def test_market_spec_rejects_invalid_buyer_id() -> None:
    with pytest.raises(ValidationError):
        MarketSpec(
            market_id=_MARKET_ID,
            buyer_id="not-a-uuid",
            requested_quantity=1,
        )


@pytest.mark.parametrize("requested_quantity", [1, MAX_QUANTITY])
def test_market_spec_accepts_quantity_bounds(requested_quantity: int) -> None:
    assert _market_spec(requested_quantity).requested_quantity == requested_quantity


@pytest.mark.parametrize("requested_quantity", [0, MAX_QUANTITY + 1, 1.0, True, "1"])
def test_market_spec_rejects_invalid_quantity(requested_quantity: object) -> None:
    with pytest.raises(ValidationError):
        _market_spec(requested_quantity)


def test_market_spec_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=1,
            product_description="not permitted",
        )


def test_market_spec_is_frozen() -> None:
    market = _market_spec()

    with pytest.raises(ValidationError):
        market.requested_quantity = 2


def test_merchant_identity_accepts_valid_input() -> None:
    merchant = _merchant(0)

    assert merchant.schema_version == "1"
    assert merchant.merchant_id == _MERCHANT_IDS[0]
    assert type(merchant.merchant_id) is str
    assert merchant.ed25519_public_key_hex == _PUBLIC_KEY_A


@pytest.mark.parametrize("schema_version", [1, "2", None])
def test_merchant_identity_rejects_unsupported_schema_version(schema_version: object) -> None:
    with pytest.raises(ValidationError):
        MerchantIdentity(
            schema_version=schema_version,
            merchant_id=_MERCHANT_IDS[0],
            ed25519_public_key_hex=_PUBLIC_KEY_A,
        )


@pytest.mark.parametrize(
    "public_key",
    [
        _PUBLIC_KEY_A[:-1],
        f"{_PUBLIC_KEY_A}0",
        _PUBLIC_KEY_A.upper(),
        f"g{_PUBLIC_KEY_A[1:]}",
        f" {_PUBLIC_KEY_A}",
        f"{_PUBLIC_KEY_A} ",
        f"0x{_PUBLIC_KEY_A}",
        _PUBLIC_KEY_A.encode(),
        1,
        None,
    ],
)
def test_merchant_identity_rejects_invalid_public_key(public_key: object) -> None:
    with pytest.raises(ValidationError):
        _merchant(0, public_key)


@pytest.mark.parametrize("merchant_id", ["not-a-uuid", UUID(_MERCHANT_IDS[0])])
def test_merchant_identity_rejects_invalid_merchant_id(merchant_id: object) -> None:
    with pytest.raises(ValidationError):
        MerchantIdentity(
            merchant_id=merchant_id,
            ed25519_public_key_hex=_PUBLIC_KEY_A,
        )


def test_merchant_identity_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        MerchantIdentity(
            merchant_id=_MERCHANT_IDS[0],
            ed25519_public_key_hex=_PUBLIC_KEY_A,
            display_name="not permitted",
        )


def test_merchant_identity_is_frozen() -> None:
    merchant = _merchant(0)

    with pytest.raises(ValidationError):
        merchant.ed25519_public_key_hex = _PUBLIC_KEY_B


@pytest.mark.parametrize("seller_count", [MIN_SELLERS, MAX_SELLERS])
def test_buyer_policy_accepts_seller_count_bounds(seller_count: int) -> None:
    policy = _policy(eligible_merchants=_merchants(seller_count))

    assert len(policy.eligible_merchants) == seller_count


def test_buyer_policy_stores_merchants_as_tuple() -> None:
    policy = _policy(eligible_merchants=list(_merchants(MIN_SELLERS)))

    assert type(policy.eligible_merchants) is tuple


def test_buyer_policy_sorts_merchants_by_merchant_id() -> None:
    policy = _policy(eligible_merchants=(_merchant(2), _merchant(0), _merchant(1)))

    assert tuple(merchant.merchant_id for merchant in policy.eligible_merchants) == tuple(
        sorted((_MERCHANT_IDS[2], _MERCHANT_IDS[0], _MERCHANT_IDS[1]))
    )


def test_buyer_policy_merchant_sort_is_deterministic() -> None:
    first = _policy(eligible_merchants=(_merchant(2), _merchant(0), _merchant(1)))
    second = _policy(eligible_merchants=(_merchant(1), _merchant(2), _merchant(0)))

    assert first.eligible_merchants == second.eligible_merchants


def test_buyer_policy_preserves_market_spec_structurally() -> None:
    market = _market_spec()
    policy = BuyerPolicy(
        market_spec=market,
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
        eligible_merchants=_merchants(MIN_SELLERS),
        bid_deadline=_DEADLINE,
    )

    assert policy.market_spec == market


def test_buyer_policy_defaults_versions_and_rules() -> None:
    policy = _policy()

    assert policy.schema_version == "1"
    assert policy.mechanism_version == "reverse_second_price_v1"
    assert policy.tie_break_rule == "merchant_id_lexicographic_ascending"


def test_buyer_policy_accepts_explicit_supported_versions_and_rules() -> None:
    policy = BuyerPolicy(
        schema_version="1",
        market_spec=_market_spec(),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
        eligible_merchants=_merchants(MIN_SELLERS),
        bid_deadline=_DEADLINE,
        mechanism_version="reverse_second_price_v1",
        tie_break_rule="merchant_id_lexicographic_ascending",
    )

    assert policy.schema_version == "1"


def test_buyer_policy_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        BuyerPolicy(
            market_spec=_market_spec(),
            max_total_payment=Money(amount_paise=500),
            reserve_unit_price=Money(amount_paise=125),
            eligible_merchants=_merchants(MIN_SELLERS),
            bid_deadline=_DEADLINE,
            status="not permitted",
        )


@pytest.mark.parametrize("seller_count", [0, 1, MAX_SELLERS + 1])
def test_buyer_policy_rejects_invalid_seller_count(seller_count: int) -> None:
    with pytest.raises(ValidationError):
        _policy(eligible_merchants=_merchants(seller_count))


def test_buyer_policy_rejects_duplicate_merchant_id_with_same_key() -> None:
    with pytest.raises(ValidationError):
        _policy(eligible_merchants=(_merchant(0), _merchant(0)))


def test_buyer_policy_rejects_duplicate_merchant_id_with_different_key() -> None:
    with pytest.raises(ValidationError):
        _policy(eligible_merchants=(_merchant(0), _merchant(0, _PUBLIC_KEY_B)))


def test_buyer_policy_accepts_distinct_merchants_with_different_ids() -> None:
    policy = _policy(eligible_merchants=(_merchant(0), _merchant(1, _PUBLIC_KEY_B)))

    assert len(policy.eligible_merchants) == 2


def test_buyer_policy_accepts_reserve_total_equal_to_budget() -> None:
    policy = _policy(
        requested_quantity=4,
        reserve_unit_price_paise=125,
        max_total_payment_paise=500,
    )

    assert policy.max_total_payment.amount_paise == 500


def test_buyer_policy_rejects_reserve_total_above_budget() -> None:
    with pytest.raises(ValidationError):
        _policy(
            requested_quantity=4,
            reserve_unit_price_paise=125,
            max_total_payment_paise=499,
        )


def test_buyer_policy_accepts_reserve_total_at_global_maximum() -> None:
    policy = _policy(
        requested_quantity=MAX_QUANTITY,
        reserve_unit_price_paise=MAX_MONEY_PAISE // MAX_QUANTITY,
        max_total_payment_paise=MAX_MONEY_PAISE,
    )

    assert policy.max_total_payment.amount_paise == MAX_MONEY_PAISE


def test_buyer_policy_converts_reserve_overflow_to_validation_error() -> None:
    with pytest.raises(ValidationError):
        _policy(
            requested_quantity=MAX_QUANTITY,
            reserve_unit_price_paise=MAX_MONEY_PAISE // MAX_QUANTITY + 1,
            max_total_payment_paise=MAX_MONEY_PAISE,
        )


def test_buyer_policy_accepts_zero_reserve_and_zero_budget() -> None:
    policy = _policy(reserve_unit_price_paise=0, max_total_payment_paise=0)

    assert policy.reserve_unit_price.amount_paise == 0
    assert policy.max_total_payment.amount_paise == 0


def test_buyer_policy_accepts_utc_deadline() -> None:
    assert _policy(bid_deadline=_DEADLINE).bid_deadline == _DEADLINE


def test_buyer_policy_normalizes_deadline_to_utc() -> None:
    deadline = datetime(
        2026,
        9,
        1,
        17,
        30,
        0,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert _policy(bid_deadline=deadline).bid_deadline == _DEADLINE


@pytest.mark.parametrize("deadline", [datetime(2026, 9, 1, 12, 0), "2026-09-01T12:00:00Z"])
def test_buyer_policy_rejects_invalid_deadline(deadline: object) -> None:
    with pytest.raises(ValidationError):
        _policy(bid_deadline=deadline)


@pytest.mark.parametrize("schema_version", [1, "2", None])
def test_buyer_policy_rejects_unsupported_schema_version(schema_version: object) -> None:
    with pytest.raises(ValidationError):
        BuyerPolicy(
            schema_version=schema_version,
            market_spec=_market_spec(),
            max_total_payment=Money(amount_paise=500),
            reserve_unit_price=Money(amount_paise=125),
            eligible_merchants=_merchants(MIN_SELLERS),
            bid_deadline=_DEADLINE,
        )


@pytest.mark.parametrize("mechanism_version", ["reverse_first_price_v1", 1, None])
def test_buyer_policy_rejects_invalid_mechanism_version(mechanism_version: object) -> None:
    with pytest.raises(ValidationError):
        _policy(mechanism_version=mechanism_version)


@pytest.mark.parametrize("tie_break_rule", ["submission_time", 1, None])
def test_buyer_policy_rejects_invalid_tie_break_rule(tie_break_rule: object) -> None:
    with pytest.raises(ValidationError):
        _policy(tie_break_rule=tie_break_rule)


def test_buyer_policy_is_frozen() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        policy.bid_deadline = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def test_buyer_policy_nested_market_spec_is_frozen() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        policy.market_spec.requested_quantity = 2


def test_buyer_policy_nested_merchant_identity_is_frozen() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        policy.eligible_merchants[0].merchant_id = _MERCHANT_IDS[2]
