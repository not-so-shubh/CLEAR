import pytest
from pydantic import ValidationError

from clear_market.commerce import (
    CONSTRAINT_PRIMITIVES_VERSION,
    AttributeValue,
    AttributeValueType,
    ComparisonOperator,
    HardConstraint,
    ProvenanceLabel,
    SoftPreference,
)

_CONSTRAINT_ID = "15000000-0000-4000-8000-000000000001"
_PREFERENCE_ID = "16000000-0000-4000-8000-000000000001"


def _attribute(value_type: AttributeValueType, value: str | int | bool) -> AttributeValue:
    return AttributeValue(value_type=value_type, value=value)


def _hard_constraint(
    *,
    attribute_key: object = "ram_gb",
    operator: ComparisonOperator = ComparisonOperator.GTE,
    operand: AttributeValue | None = None,
    allowed_provenance: object = (ProvenanceLabel.VERIFIED,),
    **extra: object,
) -> HardConstraint:
    values: dict[str, object] = {
        "constraint_id": _CONSTRAINT_ID,
        "attribute_key": attribute_key,
        "operator": operator,
        "operand": _attribute(AttributeValueType.INTEGER, 16) if operand is None else operand,
        "allowed_provenance": allowed_provenance,
        **extra,
    }
    return HardConstraint(**values)


def _soft_preference(
    *,
    attribute_key: object = "brand",
    operator: ComparisonOperator = ComparisonOperator.EQ,
    operand: AttributeValue | None = None,
    allowed_provenance: object = (ProvenanceLabel.CLAIMED,),
    **extra: object,
) -> SoftPreference:
    values: dict[str, object] = {
        "preference_id": _PREFERENCE_ID,
        "attribute_key": attribute_key,
        "operator": operator,
        "operand": _attribute(AttributeValueType.STRING, "clear") if operand is None else operand,
        "allowed_provenance": allowed_provenance,
        **extra,
    }
    return SoftPreference(**values)


def test_comparison_operator_contract_is_exact() -> None:
    assert CONSTRAINT_PRIMITIVES_VERSION == "constraint-primitives-v1"
    assert tuple(ComparisonOperator) == (
        ComparisonOperator.EQ,
        ComparisonOperator.NE,
        ComparisonOperator.LT,
        ComparisonOperator.LTE,
        ComparisonOperator.GT,
        ComparisonOperator.GTE,
    )
    assert tuple(operator.value for operator in ComparisonOperator) == (
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
    )


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, "clear"),
        (AttributeValueType.INTEGER, 16),
        (AttributeValueType.BOOLEAN, True),
    ],
)
@pytest.mark.parametrize("operator", [ComparisonOperator.EQ, ComparisonOperator.NE])
@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_equality_operators_accept_every_scalar_type(
    value_type: AttributeValueType,
    value: str | int | bool,
    operator: ComparisonOperator,
    model_kind: str,
) -> None:
    operand = _attribute(value_type, value)

    model = (
        _hard_constraint(operator=operator, operand=operand)
        if model_kind == "hard"
        else _soft_preference(operator=operator, operand=operand)
    )

    assert model.operator is operator
    assert model.operand == operand


@pytest.mark.parametrize(
    "operator",
    [
        ComparisonOperator.LT,
        ComparisonOperator.LTE,
        ComparisonOperator.GT,
        ComparisonOperator.GTE,
    ],
)
@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_ordered_operators_accept_integer_operand(
    operator: ComparisonOperator,
    model_kind: str,
) -> None:
    operand = _attribute(AttributeValueType.INTEGER, 16)

    model = (
        _hard_constraint(operator=operator, operand=operand)
        if model_kind == "hard"
        else _soft_preference(operator=operator, operand=operand)
    )

    assert model.operator is operator


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, "clear"),
        (AttributeValueType.BOOLEAN, True),
    ],
)
@pytest.mark.parametrize(
    "operator",
    [
        ComparisonOperator.LT,
        ComparisonOperator.LTE,
        ComparisonOperator.GT,
        ComparisonOperator.GTE,
    ],
)
@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_ordered_operators_reject_non_integer_operand(
    value_type: AttributeValueType,
    value: str | bool,
    operator: ComparisonOperator,
    model_kind: str,
) -> None:
    operand = _attribute(value_type, value)

    with pytest.raises(ValidationError):
        if model_kind == "hard":
            _hard_constraint(operator=operator, operand=operand)
        else:
            _soft_preference(operator=operator, operand=operand)


def test_hard_constraint_has_exact_fields_and_versions() -> None:
    constraint = _hard_constraint()

    assert constraint.schema_version == "1"
    assert constraint.constraint_primitives_version == "constraint-primitives-v1"
    assert constraint.constraint_id == _CONSTRAINT_ID
    assert constraint.attribute_key == "ram_gb"
    assert constraint.operator is ComparisonOperator.GTE
    assert constraint.operand == _attribute(AttributeValueType.INTEGER, 16)
    assert constraint.allowed_provenance == (ProvenanceLabel.VERIFIED,)
    assert tuple(constraint.__class__.model_fields) == (
        "schema_version",
        "constraint_primitives_version",
        "constraint_id",
        "attribute_key",
        "operator",
        "operand",
        "allowed_provenance",
    )


def test_soft_preference_has_exact_fields_and_versions() -> None:
    preference = _soft_preference()

    assert preference.schema_version == "1"
    assert preference.constraint_primitives_version == "constraint-primitives-v1"
    assert preference.preference_id == _PREFERENCE_ID
    assert preference.attribute_key == "brand"
    assert preference.operator is ComparisonOperator.EQ
    assert preference.operand == _attribute(AttributeValueType.STRING, "clear")
    assert preference.allowed_provenance == (ProvenanceLabel.CLAIMED,)
    assert tuple(preference.__class__.model_fields) == (
        "schema_version",
        "constraint_primitives_version",
        "preference_id",
        "attribute_key",
        "operator",
        "operand",
        "allowed_provenance",
    )


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraints_require_explicit_allowed_provenance(model_kind: str) -> None:
    values: dict[str, object] = {
        "attribute_key": "ram_gb",
        "operator": ComparisonOperator.EQ,
        "operand": _attribute(AttributeValueType.INTEGER, 16),
    }
    if model_kind == "hard":
        values["constraint_id"] = _CONSTRAINT_ID
    else:
        values["preference_id"] = _PREFERENCE_ID

    with pytest.raises(ValidationError):
        if model_kind == "hard":
            HardConstraint(**values)
        else:
            SoftPreference(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("constraint_primitives_version", "constraint-primitives-v2"),
    ],
)
@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraints_reject_invalid_versions(
    field: str,
    value: object,
    model_kind: str,
) -> None:
    with pytest.raises(ValidationError):
        if model_kind == "hard":
            _hard_constraint(**{field: value})
        else:
            _soft_preference(**{field: value})


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraints_normalize_provenance_to_deterministic_label_order(model_kind: str) -> None:
    labels = (
        ProvenanceLabel.VERIFIED,
        ProvenanceLabel.PREDICTED,
        ProvenanceLabel.ATTESTED,
    )

    model = (
        _hard_constraint(allowed_provenance=labels)
        if model_kind == "hard"
        else _soft_preference(allowed_provenance=labels)
    )

    assert model.allowed_provenance == (
        ProvenanceLabel.ATTESTED,
        ProvenanceLabel.PREDICTED,
        ProvenanceLabel.VERIFIED,
    )


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_predicted_is_absent_unless_explicitly_allowed(model_kind: str) -> None:
    without_predicted = _hard_constraint() if model_kind == "hard" else _soft_preference()
    with_predicted = (
        _hard_constraint(allowed_provenance=(ProvenanceLabel.PREDICTED,))
        if model_kind == "hard"
        else _soft_preference(allowed_provenance=(ProvenanceLabel.PREDICTED,))
    )

    assert ProvenanceLabel.PREDICTED not in without_predicted.allowed_provenance
    assert with_predicted.allowed_provenance == (ProvenanceLabel.PREDICTED,)


@pytest.mark.parametrize("labels", [(), []])
@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraints_reject_missing_or_non_tuple_provenance(
    labels: object,
    model_kind: str,
) -> None:
    with pytest.raises(ValidationError):
        if model_kind == "hard":
            _hard_constraint(allowed_provenance=labels)
        else:
            _soft_preference(allowed_provenance=labels)


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraints_reject_duplicate_provenance(model_kind: str) -> None:
    labels = (ProvenanceLabel.VERIFIED, ProvenanceLabel.VERIFIED)

    with pytest.raises(ValidationError):
        if model_kind == "hard":
            _hard_constraint(allowed_provenance=labels)
        else:
            _soft_preference(allowed_provenance=labels)


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraints_reject_invalid_attribute_key(model_kind: str) -> None:
    with pytest.raises(ValidationError):
        if model_kind == "hard":
            _hard_constraint(attribute_key="RAM GB")
        else:
            _soft_preference(attribute_key="RAM GB")


def test_hard_and_soft_models_are_structurally_distinct() -> None:
    assert HardConstraint is not SoftPreference
    assert "constraint_id" in HardConstraint.model_fields
    assert "preference_id" not in HardConstraint.model_fields
    assert "preference_id" in SoftPreference.model_fields
    assert "constraint_id" not in SoftPreference.model_fields


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraint_models_are_frozen(model_kind: str) -> None:
    model = _hard_constraint() if model_kind == "hard" else _soft_preference()

    with pytest.raises(ValidationError):
        model.attribute_key = "changed"


@pytest.mark.parametrize("model_kind", ["hard", "soft"])
def test_constraint_models_forbid_extra_fields(model_kind: str) -> None:
    with pytest.raises(ValidationError):
        if model_kind == "hard":
            _hard_constraint(weight=1)
        else:
            _soft_preference(weight=1)
