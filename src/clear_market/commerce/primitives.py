import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

PROVENANCE_VERSION: Final[str] = "provenance-v1"
ATTRIBUTE_VALUE_VERSION: Final[str] = "attribute-value-v1"


class ProvenanceLabel(StrEnum):
    """Semantic provenance categories without an implied trust ordering."""

    VERIFIED = "VERIFIED"
    ATTESTED = "ATTESTED"
    CLAIMED = "CLAIMED"
    DERIVED = "DERIVED"
    PREDICTED = "PREDICTED"


_ATTRIBUTE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}", flags=re.ASCII)


def _validate_attribute_key(value: object) -> str:
    """Require callers to supply an already-canonical attribute identifier."""
    if type(value) is not str or _ATTRIBUTE_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("attribute key is not canonical")
    return value


type AttributeKey = Annotated[str, BeforeValidator(_validate_attribute_key)]


class AttributeValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"


type _AttributeScalar = StrictStr | StrictInt | StrictBool


class AttributeValue(BaseModel):
    """An immutable tagged commercial scalar with no coercion or float representation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"] = "1"
    attribute_value_version: Literal["attribute-value-v1"] = "attribute-value-v1"
    value_type: AttributeValueType
    value: _AttributeScalar

    @model_validator(mode="after")
    def _validate_declared_type(self) -> Self:
        expected_type = {
            AttributeValueType.STRING: str,
            AttributeValueType.INTEGER: int,
            AttributeValueType.BOOLEAN: bool,
        }[self.value_type]
        if type(self.value) is not expected_type:
            raise ValueError("declared attribute value type does not match the scalar")
        return self
