from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from clear_market.commerce.primitives import (
    AttributeKey,
    AttributeValue,
    AttributeValueType,
    ProvenanceLabel,
)
from clear_market.domain import CanonicalUUID4

CONSTRAINT_PRIMITIVES_VERSION: Final[str] = "constraint-primitives-v1"


class ComparisonOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


_ORDERED_COMPARISON_OPERATORS = frozenset(
    {
        ComparisonOperator.LT,
        ComparisonOperator.LTE,
        ComparisonOperator.GT,
        ComparisonOperator.GTE,
    }
)


def _require_provenance_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("allowed provenance must be supplied as a tuple")
    return value


type _AllowedProvenance = Annotated[
    tuple[ProvenanceLabel, ...],
    BeforeValidator(_require_provenance_tuple),
    Field(min_length=1),
]


def _normalize_allowed_provenance(
    labels: tuple[ProvenanceLabel, ...],
) -> tuple[ProvenanceLabel, ...]:
    if len(set(labels)) != len(labels):
        raise ValueError("allowed provenance labels must be unique")
    return tuple(sorted(labels, key=lambda label: label.value))


def _validate_operator_operand(
    operator: ComparisonOperator,
    operand: AttributeValue,
) -> None:
    if (
        operator in _ORDERED_COMPARISON_OPERATORS
        and operand.value_type is not AttributeValueType.INTEGER
    ):
        raise ValueError("ordered comparisons require an integer operand")


class HardConstraint(BaseModel):
    """A declarative mandatory condition; evaluation is intentionally out of scope."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"] = "1"
    constraint_primitives_version: Literal["constraint-primitives-v1"] = "constraint-primitives-v1"
    constraint_id: CanonicalUUID4
    attribute_key: AttributeKey
    operator: ComparisonOperator
    operand: AttributeValue
    allowed_provenance: _AllowedProvenance

    @field_validator("allowed_provenance")
    @classmethod
    def _validate_allowed_provenance(
        cls,
        labels: tuple[ProvenanceLabel, ...],
    ) -> tuple[ProvenanceLabel, ...]:
        return _normalize_allowed_provenance(labels)

    @model_validator(mode="after")
    def _validate_operator_compatibility(self) -> Self:
        _validate_operator_operand(self.operator, self.operand)
        return self


class SoftPreference(BaseModel):
    """A declarative preferred condition with no weight, score, or evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"] = "1"
    constraint_primitives_version: Literal["constraint-primitives-v1"] = "constraint-primitives-v1"
    preference_id: CanonicalUUID4
    attribute_key: AttributeKey
    operator: ComparisonOperator
    operand: AttributeValue
    allowed_provenance: _AllowedProvenance

    @field_validator("allowed_provenance")
    @classmethod
    def _validate_allowed_provenance(
        cls,
        labels: tuple[ProvenanceLabel, ...],
    ) -> tuple[ProvenanceLabel, ...]:
        return _normalize_allowed_provenance(labels)

    @model_validator(mode="after")
    def _validate_operator_compatibility(self) -> Self:
        _validate_operator_operand(self.operator, self.operand)
        return self
