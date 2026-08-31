from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from clear_market.domain.constants import MAX_MONEY_PAISE, MAX_QUANTITY


class Currency(StrEnum):
    INR = "INR"


class InvalidQuantityError(ValueError):
    """Quantity supplied to a primitive operation violates Week-2 bounds."""


class MoneyOverflowError(ArithmeticError):
    """Exact money arithmetic would exceed MAX_MONEY_PAISE."""


class Money(BaseModel):
    """A bounded INR amount; zero is valid because positivity is contextual."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_paise: Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_PAISE)]
    currency: Currency = Currency.INR

    def checked_multiply(self, quantity: int) -> "Money":
        """Multiply exactly while enforcing quantity and money domain ceilings."""
        # bool must be rejected explicitly because it subclasses int.
        if type(quantity) is not int or not 0 <= quantity <= MAX_QUANTITY:
            raise InvalidQuantityError

        total = self.amount_paise * quantity
        if total > MAX_MONEY_PAISE:
            raise MoneyOverflowError

        return Money(amount_paise=total, currency=self.currency)
