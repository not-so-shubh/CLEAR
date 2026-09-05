import pytest
from pydantic import ValidationError

from clear_market.agentmarketbench.method_models import (
    AGENT_MARKET_BENCH_ADMISSION_REJECTION_V1_VERSION,
    AGENT_MARKET_BENCH_ADMISSION_V1_VERSION,
    AGENT_MARKET_BENCH_DECISION_LINE_V1_VERSION,
    AGENT_MARKET_BENCH_METHOD_RESULT_V1_VERSION,
    AGENT_MARKET_BENCH_METHODS_V1_VERSION,
    AgentMarketBenchAdmissionRejectionReasonV1,
    AgentMarketBenchAdmissionRejectionV1,
    AgentMarketBenchAdmissionV1,
    AgentMarketBenchDecisionLineV1,
    AgentMarketBenchMethodResultV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.models import AgentMarketBenchBaselineV1
from clear_market.domain import Money

_MARKET_ID = "51000000-0000-4000-8000-000000000001"
_MERCHANT_ID = "43000000-0000-4000-8000-000000000001"
_SKU_ID = "46000000-0000-4000-8000-000000000001"
_OFFER_ID = "49000000-0000-4000-8000-000000000001"


def _admission() -> AgentMarketBenchAdmissionV1:
    return AgentMarketBenchAdmissionV1(
        admitted_submission_indices=(0,),
        rejections=(
            AgentMarketBenchAdmissionRejectionV1(
                submission_index=1,
                reason=AgentMarketBenchAdmissionRejectionReasonV1.LATE_OFFER,
            ),
        ),
    )


def _line(
    *, source_offer_id: str | None = _OFFER_ID, quantity: int = 2
) -> AgentMarketBenchDecisionLineV1:
    unit = Money(amount_paise=11)
    return AgentMarketBenchDecisionLineV1(
        source_offer_id=source_offer_id,
        merchant_id=_MERCHANT_ID,
        sku_id=_SKU_ID,
        allocated_quantity=quantity,
        unit_payment=unit,
        line_payment=unit.checked_multiply(quantity),
    )


def test_exact_constants_and_enums() -> None:
    assert AGENT_MARKET_BENCH_METHODS_V1_VERSION == "agent-market-bench-methods-v1"
    assert AGENT_MARKET_BENCH_ADMISSION_V1_VERSION == "agent-market-bench-admission-v1"
    assert AGENT_MARKET_BENCH_ADMISSION_REJECTION_V1_VERSION == (
        "agent-market-bench-admission-rejection-v1"
    )
    assert AGENT_MARKET_BENCH_DECISION_LINE_V1_VERSION == "agent-market-bench-decision-line-v1"
    assert AGENT_MARKET_BENCH_METHOD_RESULT_V1_VERSION == "agent-market-bench-method-result-v1"
    assert tuple(AgentMarketBenchMethodStatusV1) == (
        AgentMarketBenchMethodStatusV1.FEASIBLE,
        AgentMarketBenchMethodStatusV1.INFEASIBLE,
        AgentMarketBenchMethodStatusV1.NOT_APPLICABLE,
    )
    assert tuple(AgentMarketBenchAdmissionRejectionReasonV1) == (
        AgentMarketBenchAdmissionRejectionReasonV1.LATE_OFFER,
        AgentMarketBenchAdmissionRejectionReasonV1.UNKNOWN_MERCHANT,
        AgentMarketBenchAdmissionRejectionReasonV1.AUTHENTICATION_FAILED,
        AgentMarketBenchAdmissionRejectionReasonV1.DUPLICATE_OFFER_ID,
        AgentMarketBenchAdmissionRejectionReasonV1.DUPLICATE_MERCHANT,
    )


@pytest.mark.parametrize(
    "model_type",
    (
        AgentMarketBenchAdmissionRejectionV1,
        AgentMarketBenchAdmissionV1,
        AgentMarketBenchDecisionLineV1,
        AgentMarketBenchMethodResultV1,
    ),
)
def test_models_are_frozen_strict_forbid_and_revalidating(model_type: type[object]) -> None:
    config = model_type.model_config
    assert config["frozen"] is True
    assert config["strict"] is True
    assert config["extra"] == "forbid"
    assert config["revalidate_instances"] == "always"


def test_field_order_is_frozen() -> None:
    assert tuple(AgentMarketBenchAdmissionRejectionV1.model_fields) == (
        "schema_version",
        "agent_market_bench_admission_rejection_version",
        "submission_index",
        "reason",
    )
    assert tuple(AgentMarketBenchAdmissionV1.model_fields) == (
        "schema_version",
        "agent_market_bench_admission_version",
        "admitted_submission_indices",
        "rejections",
    )
    assert tuple(AgentMarketBenchDecisionLineV1.model_fields) == (
        "schema_version",
        "agent_market_bench_decision_line_version",
        "source_offer_id",
        "merchant_id",
        "sku_id",
        "allocated_quantity",
        "unit_payment",
        "line_payment",
    )
    assert tuple(AgentMarketBenchMethodResultV1.model_fields) == (
        "schema_version",
        "agent_market_bench_method_result_version",
        "method",
        "market_id",
        "status",
        "admission",
        "fulfilled_quantity",
        "total_payment",
        "winner_count",
        "lines",
    )


def test_admission_indices_are_unique_increasing_and_disjoint() -> None:
    with pytest.raises(ValidationError):
        AgentMarketBenchAdmissionV1(admitted_submission_indices=(1, 0), rejections=())
    with pytest.raises(ValidationError):
        AgentMarketBenchAdmissionV1(admitted_submission_indices=(0, 0), rejections=())
    with pytest.raises(ValidationError):
        AgentMarketBenchAdmissionV1(
            admitted_submission_indices=(0,),
            rejections=(
                AgentMarketBenchAdmissionRejectionV1(
                    submission_index=0,
                    reason=AgentMarketBenchAdmissionRejectionReasonV1.LATE_OFFER,
                ),
            ),
        )
    with pytest.raises(ValidationError):
        AgentMarketBenchAdmissionV1(admitted_submission_indices=([0],), rejections=())


def test_decision_line_payment_and_fresh_nested_validation() -> None:
    line = _line()
    assert line.line_payment == Money(amount_paise=22)
    with pytest.raises(ValidationError):
        AgentMarketBenchDecisionLineV1(
            source_offer_id=_OFFER_ID,
            merchant_id=_MERCHANT_ID,
            sku_id=_SKU_ID,
            allocated_quantity=2,
            unit_payment=Money(amount_paise=11),
            line_payment=Money(amount_paise=23),
        )
    with pytest.raises(ValidationError):
        AgentMarketBenchDecisionLineV1(
            source_offer_id=_OFFER_ID,
            merchant_id=_MERCHANT_ID,
            sku_id=_SKU_ID,
            allocated_quantity=2,
            unit_payment={"amount_paise": 11},
            line_payment=Money(amount_paise=22),
        )
    corrupt = AgentMarketBenchDecisionLineV1.model_construct(
        source_offer_id=_OFFER_ID,
        merchant_id=_MERCHANT_ID,
        sku_id=_SKU_ID,
        allocated_quantity=2,
        unit_payment=Money(amount_paise=11),
        line_payment=Money(amount_paise=23),
    )
    with pytest.raises(ValidationError):
        AgentMarketBenchMethodResultV1(
            method=AgentMarketBenchBaselineV1.CLEAR,
            market_id=_MARKET_ID,
            status=AgentMarketBenchMethodStatusV1.FEASIBLE,
            admission=_admission(),
            fulfilled_quantity=2,
            total_payment=Money(amount_paise=23),
            winner_count=1,
            lines=(corrupt,),
        )


def test_result_normalizes_lines_and_enforces_status_and_source_rules() -> None:
    first = _line(source_offer_id=_OFFER_ID)
    second = AgentMarketBenchDecisionLineV1(
        source_offer_id="49000000-0000-4000-8000-000000000002",
        merchant_id="43000000-0000-4000-8000-000000000002",
        sku_id="46000000-0000-4000-8000-000000000002",
        allocated_quantity=1,
        unit_payment=Money(amount_paise=7),
        line_payment=Money(amount_paise=7),
    )
    result = AgentMarketBenchMethodResultV1(
        method=AgentMarketBenchBaselineV1.CLEAR,
        market_id=_MARKET_ID,
        status=AgentMarketBenchMethodStatusV1.FEASIBLE,
        admission=_admission(),
        fulfilled_quantity=3,
        total_payment=Money(amount_paise=29),
        winner_count=2,
        lines=(second, first),
    )
    assert result.lines == (first, second)
    with pytest.raises(ValidationError):
        AgentMarketBenchMethodResultV1(
            method=AgentMarketBenchBaselineV1.CLEAR,
            market_id=_MARKET_ID,
            status=AgentMarketBenchMethodStatusV1.INFEASIBLE,
            admission=_admission(),
            fulfilled_quantity=0,
            total_payment=Money(amount_paise=0),
            winner_count=0,
            lines=(first,),
        )
    with pytest.raises(ValidationError):
        AgentMarketBenchMethodResultV1(
            method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
            market_id=_MARKET_ID,
            status=AgentMarketBenchMethodStatusV1.FEASIBLE,
            admission=_admission(),
            fulfilled_quantity=2,
            total_payment=Money(amount_paise=22),
            winner_count=1,
            lines=(_line(source_offer_id=_OFFER_ID),),
        )
    oracle = AgentMarketBenchMethodResultV1(
        method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
        market_id=_MARKET_ID,
        status=AgentMarketBenchMethodStatusV1.FEASIBLE,
        admission=_admission(),
        fulfilled_quantity=2,
        total_payment=Money(amount_paise=22),
        winner_count=1,
        lines=(_line(source_offer_id=None),),
    )
    assert oracle.lines[0].source_offer_id is None
