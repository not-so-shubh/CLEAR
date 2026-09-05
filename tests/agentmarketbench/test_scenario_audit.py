from clear_market.agentmarketbench.admission import admit_agent_market_bench_market_input_v1
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.method_models import AgentMarketBenchAdmissionV1
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialClassificationV1,
    AgentMarketBenchAdversarialScenarioV1,
)
from clear_market.agentmarketbench.protocol import agent_market_bench_market_input_v1
from clear_market.agentmarketbench.scenario_audit import audit_agent_market_bench_scenarios_v1

_START = 100_000_000


def _scenario_case(scenario: AgentMarketBenchAdversarialScenarioV1):
    return next(
        generate_agent_market_bench_case_v1(seed)
        for seed in range(_START, _START + 42)
        if generate_agent_market_bench_case_v1(seed).adversarial_scenarios == (scenario,)
    )


def test_all_21_scenarios_have_exact_reviewed_classification() -> None:
    protocol = {
        AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER,
        AgentMarketBenchAdversarialScenarioV1.LATE_OFFER,
        AgentMarketBenchAdversarialScenarioV1.REPLAYED_OFFER,
        AgentMarketBenchAdversarialScenarioV1.FORGED_MERCHANT,
    }
    ai = {
        AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
        AgentMarketBenchAdversarialScenarioV1.MALICIOUS_CATALOG_TEXT,
        AgentMarketBenchAdversarialScenarioV1.SCHEMA_MANIPULATION,
    }
    economic = {
        AgentMarketBenchAdversarialScenarioV1.STRATEGIC_SHADING,
        AgentMarketBenchAdversarialScenarioV1.SELLER_DROPOUT,
        AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY,
        AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE,
        AgentMarketBenchAdversarialScenarioV1.SYBIL_SENSITIVITY,
        AgentMarketBenchAdversarialScenarioV1.COLLUSION_SENSITIVITY,
    }
    for scenario in AgentMarketBenchAdversarialScenarioV1:
        case = _scenario_case(scenario)
        admission = admit_agent_market_bench_market_input_v1(
            agent_market_bench_market_input_v1(case)
        )
        assessment = audit_agent_market_bench_scenarios_v1(case=case, admission=admission)[0]
        if scenario in protocol:
            assert (
                assessment.classification is AgentMarketBenchAdversarialClassificationV1.PREVENTED
            )
            assert assessment.evidence_basis.value == "SHARED_ADMISSION"
        elif scenario in ai:
            assert (
                assessment.classification
                is AgentMarketBenchAdversarialClassificationV1.OUT_OF_SCOPE
            )
            assert assessment.evidence_basis.value == "AI_NOT_EXERCISED"
        elif scenario in economic:
            assert assessment.classification is AgentMarketBenchAdversarialClassificationV1.MEASURED
            assert assessment.evidence_basis.value == "ECONOMIC_SENSITIVITY"
        else:
            assert (
                assessment.classification
                is AgentMarketBenchAdversarialClassificationV1.OUT_OF_SCOPE
            )
            assert assessment.evidence_basis.value == "FINANCIAL_RUNTIME_NOT_EXERCISED"


def test_protocol_without_expected_rejection_is_measured() -> None:
    case = _scenario_case(AgentMarketBenchAdversarialScenarioV1.LATE_OFFER)
    assessment = audit_agent_market_bench_scenarios_v1(
        case=case,
        admission=AgentMarketBenchAdmissionV1(admitted_submission_indices=(), rejections=()),
    )[0]
    assert assessment.classification is AgentMarketBenchAdversarialClassificationV1.MEASURED
