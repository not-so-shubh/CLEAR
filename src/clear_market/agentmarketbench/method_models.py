"""Strict evidence models for AgentMarketBench economic methods.

These objects describe benchmark decisions and admission evidence only.  They never
authorize allocation, settlement, payment, routing, or fulfillment.
"""

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from clear_market.agentmarketbench.models import AgentMarketBenchBaselineV1
from clear_market.domain import MAX_SELLERS, CanonicalUUID4, Money, MoneyOverflowError, Quantity

AGENT_MARKET_BENCH_METHODS_V1_VERSION: Final[str] = "agent-market-bench-methods-v1"
AGENT_MARKET_BENCH_ADMISSION_V1_VERSION: Final[str] = "agent-market-bench-admission-v1"
AGENT_MARKET_BENCH_ADMISSION_REJECTION_V1_VERSION: Final[str] = (
    "agent-market-bench-admission-rejection-v1"
)
AGENT_MARKET_BENCH_DECISION_LINE_V1_VERSION: Final[str] = "agent-market-bench-decision-line-v1"
AGENT_MARKET_BENCH_METHOD_RESULT_V1_VERSION: Final[str] = "agent-market-bench-method-result-v1"


class AgentMarketBenchMethodStatusV1(StrEnum):
    """A deterministic method outcome, not a payment or execution state."""

    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AgentMarketBenchAdmissionRejectionReasonV1(StrEnum):
    """A public benchmark admission classification, not a financial decision."""

    LATE_OFFER = "LATE_OFFER"
    UNKNOWN_MERCHANT = "UNKNOWN_MERCHANT"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    DUPLICATE_OFFER_ID = "DUPLICATE_OFFER_ID"
    DUPLICATE_MERCHANT = "DUPLICATE_MERCHANT"


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as a tuple")
    return value


def _require_exact_enum(enum_type: type[StrEnum], value: object) -> StrEnum:
    if type(value) is not enum_type:
        raise ValueError(f"value must be exactly {enum_type.__name__}")
    return value


def _fresh_exact[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT:
    if type(value) is not model_type:
        raise ValueError(f"value must be exactly {model_type.__name__}")
    try:
        fresh = model_type.model_validate(
            {field_name: getattr(value, field_name) for field_name in model_type.model_fields}
        )
    except Exception as error:
        raise ValueError(f"{model_type.__name__} failed fresh validation") from error
    if type(fresh) is not model_type:
        raise ValueError(f"value must revalidate to exactly {model_type.__name__}")
    return fresh


def _fresh_money(value: object) -> Money:
    return _fresh_exact(Money, value)


_FreshMoney = Annotated[Money, BeforeValidator(_fresh_money)]
_FreshAdmissionRejection = Annotated[
    "AgentMarketBenchAdmissionRejectionV1",
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchAdmissionRejectionV1, value)),
]
_FreshDecisionLine = Annotated[
    "AgentMarketBenchDecisionLineV1",
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchDecisionLineV1, value)),
]
_ExactMethod = Annotated[
    AgentMarketBenchBaselineV1,
    BeforeValidator(lambda value: _require_exact_enum(AgentMarketBenchBaselineV1, value)),
]
_ExactStatus = Annotated[
    AgentMarketBenchMethodStatusV1,
    BeforeValidator(lambda value: _require_exact_enum(AgentMarketBenchMethodStatusV1, value)),
]


class AgentMarketBenchAdmissionRejectionV1(BaseModel):
    """Evidence that one reported offer was excluded before economic comparison."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_admission_rejection_version: Literal[
        "agent-market-bench-admission-rejection-v1"
    ] = "agent-market-bench-admission-rejection-v1"
    submission_index: Annotated[int, Field(strict=True, ge=0)]
    reason: Annotated[
        AgentMarketBenchAdmissionRejectionReasonV1,
        BeforeValidator(
            lambda value: _require_exact_enum(AgentMarketBenchAdmissionRejectionReasonV1, value)
        ),
    ]


class AgentMarketBenchAdmissionV1(BaseModel):
    """Deterministic public admission evidence with no authorization semantics."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_admission_version: Literal["agent-market-bench-admission-v1"] = (
        "agent-market-bench-admission-v1"
    )
    admitted_submission_indices: Annotated[
        tuple[Annotated[int, Field(strict=True, ge=0)], ...],
        BeforeValidator(_require_tuple),
    ]
    rejections: Annotated[
        tuple[_FreshAdmissionRejection, ...],
        BeforeValidator(_require_tuple),
    ]

    @model_validator(mode="after")
    def _validate_indices(self) -> "AgentMarketBenchAdmissionV1":
        admitted = self.admitted_submission_indices
        rejected = tuple(item.submission_index for item in self.rejections)
        if admitted != tuple(sorted(set(admitted))):
            raise ValueError("admitted submission indices must be strictly increasing")
        if rejected != tuple(sorted(set(rejected))):
            raise ValueError("rejection submission indices must be strictly increasing")
        if set(admitted) & set(rejected):
            raise ValueError("admitted and rejected submission indices must be disjoint")
        return self


_FreshAdmission = Annotated[
    AgentMarketBenchAdmissionV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchAdmissionV1, value)),
]


class AgentMarketBenchDecisionLineV1(BaseModel):
    """Benchmark allocation evidence; it does not create an economic obligation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_decision_line_version: Literal["agent-market-bench-decision-line-v1"] = (
        "agent-market-bench-decision-line-v1"
    )
    source_offer_id: CanonicalUUID4 | None
    merchant_id: CanonicalUUID4
    sku_id: CanonicalUUID4
    allocated_quantity: Quantity
    unit_payment: _FreshMoney
    line_payment: _FreshMoney

    @model_validator(mode="after")
    def _validate_line_payment(self) -> "AgentMarketBenchDecisionLineV1":
        try:
            expected = self.unit_payment.checked_multiply(self.allocated_quantity)
        except MoneyOverflowError as error:
            raise ValueError("line payment exceeds the money bound") from error
        if self.line_payment != expected:
            raise ValueError("line payment does not match exact checked multiplication")
        return self


class AgentMarketBenchMethodResultV1(BaseModel):
    """A deterministic method result retained as benchmark evidence only."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_method_result_version: Literal["agent-market-bench-method-result-v1"] = (
        "agent-market-bench-method-result-v1"
    )
    method: _ExactMethod
    market_id: CanonicalUUID4
    status: _ExactStatus
    admission: _FreshAdmission
    fulfilled_quantity: Quantity
    total_payment: _FreshMoney
    winner_count: Annotated[int, Field(strict=True, ge=0, le=MAX_SELLERS)]
    lines: Annotated[tuple[_FreshDecisionLine, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> "AgentMarketBenchMethodResultV1":
        normalized = tuple(
            sorted(
                self.lines,
                key=lambda line: (
                    line.merchant_id,
                    line.sku_id,
                    line.source_offer_id or "",
                ),
            )
        )
        keys = tuple((line.merchant_id, line.sku_id, line.source_offer_id) for line in normalized)
        if len(set(keys)) != len(keys):
            raise ValueError("decision line keys must be unique")
        if normalized != self.lines:
            object.__setattr__(self, "lines", normalized)

        if any(line.allocated_quantity <= 0 for line in self.lines):
            raise ValueError("decision lines must have positive allocations")
        quantity = sum(line.allocated_quantity for line in self.lines)
        payment_paise = sum(line.line_payment.amount_paise for line in self.lines)
        if self.fulfilled_quantity != quantity:
            raise ValueError("fulfilled quantity does not match decision lines")
        if self.total_payment.amount_paise != payment_paise:
            raise ValueError("total payment does not match decision lines")
        winners = len({line.merchant_id for line in self.lines})
        if self.winner_count != winners:
            raise ValueError("winner count does not match decision lines")

        if self.status is AgentMarketBenchMethodStatusV1.FEASIBLE:
            if not self.lines or quantity <= 0 or winners <= 0:
                raise ValueError("feasible result requires positive decision evidence")
        elif quantity != 0 or payment_paise != 0 or winners != 0 or self.lines != ():
            raise ValueError("non-feasible result must have the exact zero result shape")

        if self.method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE:
            if any(line.source_offer_id is not None for line in self.lines):
                raise ValueError("full-information oracle lines cannot name source offers")
        elif any(line.source_offer_id is None for line in self.lines):
            raise ValueError("ordinary method lines must name source offers")
        return self


__all__ = (  # noqa: RUF022
    "AGENT_MARKET_BENCH_METHODS_V1_VERSION",
    "AGENT_MARKET_BENCH_ADMISSION_V1_VERSION",
    "AGENT_MARKET_BENCH_ADMISSION_REJECTION_V1_VERSION",
    "AGENT_MARKET_BENCH_DECISION_LINE_V1_VERSION",
    "AGENT_MARKET_BENCH_METHOD_RESULT_V1_VERSION",
    "AgentMarketBenchMethodStatusV1",
    "AgentMarketBenchAdmissionRejectionReasonV1",
    "AgentMarketBenchAdmissionRejectionV1",
    "AgentMarketBenchAdmissionV1",
    "AgentMarketBenchDecisionLineV1",
    "AgentMarketBenchMethodResultV1",
)
