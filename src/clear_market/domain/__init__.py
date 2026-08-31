"""Public pure-domain primitives for CLEAR."""

from clear_market.domain.bids import MerchantBid, SignedMerchantBid
from clear_market.domain.constants import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    MAX_SELLERS,
    MIN_SELLERS,
)
from clear_market.domain.models import BuyerPolicy, MarketSpec, MerchantIdentity
from clear_market.domain.money import (
    Currency,
    InvalidQuantityError,
    Money,
    MoneyOverflowError,
)
from clear_market.domain.primitives import (
    CanonicalUUID4,
    PositiveQuantity,
    Quantity,
    UTCDateTime,
)

# This reviewed compatibility order intentionally differs from alphabetical presentation.
__all__ = (  # noqa: RUF022
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
    "MerchantBid",
    "SignedMerchantBid",
)
