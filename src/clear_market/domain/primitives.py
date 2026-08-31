from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator, Field

from clear_market.domain.constants import MAX_QUANTITY

type Quantity = Annotated[int, Field(strict=True, ge=0, le=MAX_QUANTITY)]
type PositiveQuantity = Annotated[int, Field(strict=True, ge=1, le=MAX_QUANTITY)]


def _validate_canonical_uuid4(value: object) -> str:
    """Accept UUID text only when the caller already supplied its canonical representation."""
    if type(value) is not str:
        raise ValueError("UUID input must be a string")

    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("UUID input is malformed") from error

    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("UUID input must be a canonical UUIDv4 string")

    return value


type CanonicalUUID4 = Annotated[str, BeforeValidator(_validate_canonical_uuid4)]


def _normalize_utc_datetime(value: object) -> datetime:
    """Normalize aware timestamps where they enter the pure-domain boundary."""
    if not isinstance(value, datetime):
        raise ValueError("timestamp input must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp input must be timezone-aware")

    return value.astimezone(UTC)


type UTCDateTime = Annotated[datetime, BeforeValidator(_normalize_utc_datetime)]
