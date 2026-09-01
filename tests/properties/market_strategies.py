from dataclasses import dataclass

from hypothesis import strategies as st

from clear_market.domain import MAX_MONEY_PAISE, MAX_QUANTITY, MAX_SELLERS, MIN_SELLERS


@dataclass(frozen=True)
class PropertyMarketCase:
    case_tag: int
    seller_count: int
    requested_quantity: int
    reserve_unit_price_paise: int
    participates: tuple[bool, ...]
    quantity_available: tuple[int, ...]
    unit_price_paise: tuple[int, ...]


@st.composite
def property_market_cases(draw: st.DrawFn) -> PropertyMarketCase:
    case_tag = draw(st.integers(min_value=0, max_value=65_535))
    seller_count = draw(st.integers(min_value=MIN_SELLERS, max_value=MAX_SELLERS))
    requested_quantity = draw(st.integers(min_value=1, max_value=1_000))
    reserve_unit_price_paise = draw(st.integers(min_value=0, max_value=1_000_000))

    participates = tuple(draw(st.booleans()) for _ in range(seller_count))

    quantity_neighborhood = (
        0,
        max(0, requested_quantity - 1),
        requested_quantity,
        requested_quantity + 1,
        requested_quantity + 2,
    )
    quantity_strategy = st.one_of(
        st.sampled_from(quantity_neighborhood),
        st.integers(
            min_value=0,
            max_value=min(MAX_QUANTITY, requested_quantity + 100),
        ),
    )
    quantity_available = tuple(draw(quantity_strategy) for _ in range(seller_count))

    price_neighborhood = (
        0,
        max(0, reserve_unit_price_paise - 1),
        reserve_unit_price_paise,
        reserve_unit_price_paise + 1,
        reserve_unit_price_paise + 2,
    )
    price_strategy = st.one_of(
        st.sampled_from(price_neighborhood),
        st.integers(
            min_value=0,
            max_value=min(MAX_MONEY_PAISE, reserve_unit_price_paise + 100),
        ),
    )
    unit_price_paise = tuple(draw(price_strategy) for _ in range(seller_count))

    return PropertyMarketCase(
        case_tag=case_tag,
        seller_count=seller_count,
        requested_quantity=requested_quantity,
        reserve_unit_price_paise=reserve_unit_price_paise,
        participates=participates,
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
    )
