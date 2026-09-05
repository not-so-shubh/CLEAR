"""Reviewed Slice 24D scenario classifications."""

from clear_market.agentmarketbench.measurement_models import (
    AgentMarketBenchScenarioAssessmentV1,
    AgentMarketBenchScenarioEvidenceBasisV1,
)
from clear_market.agentmarketbench.method_models import AgentMarketBenchAdmissionV1
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialClassificationV1,
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchCaseV1,
)

_PROTOCOL_EXPECTED = {
    AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER: "AUTHENTICATION_FAILED",
    AgentMarketBenchAdversarialScenarioV1.LATE_OFFER: "LATE_OFFER",
    AgentMarketBenchAdversarialScenarioV1.REPLAYED_OFFER: "DUPLICATE_OFFER_ID",
    AgentMarketBenchAdversarialScenarioV1.FORGED_MERCHANT: "AUTHENTICATION_FAILED",
}
_AI_SCENARIOS = {
    AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
    AgentMarketBenchAdversarialScenarioV1.MALICIOUS_CATALOG_TEXT,
    AgentMarketBenchAdversarialScenarioV1.SCHEMA_MANIPULATION,
}
_ECONOMIC_SCENARIOS = {
    AgentMarketBenchAdversarialScenarioV1.STRATEGIC_SHADING,
    AgentMarketBenchAdversarialScenarioV1.SELLER_DROPOUT,
    AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY,
    AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE,
    AgentMarketBenchAdversarialScenarioV1.SYBIL_SENSITIVITY,
    AgentMarketBenchAdversarialScenarioV1.COLLUSION_SENSITIVITY,
}
_RUNTIME_SCENARIOS = {
    AgentMarketBenchAdversarialScenarioV1.DUPLICATE_EVENT,
    AgentMarketBenchAdversarialScenarioV1.EVENT_REORDERING,
    AgentMarketBenchAdversarialScenarioV1.PROVIDER_TIMEOUT,
    AgentMarketBenchAdversarialScenarioV1.PAYMENT_FAILURE,
    AgentMarketBenchAdversarialScenarioV1.TRANSFER_FAILURE,
    AgentMarketBenchAdversarialScenarioV1.RETRY,
    AgentMarketBenchAdversarialScenarioV1.RECONCILIATION,
    AgentMarketBenchAdversarialScenarioV1.RECOVERY,
}


def audit_agent_market_bench_scenarios_v1(
    *, case: AgentMarketBenchCaseV1, admission: AgentMarketBenchAdmissionV1
) -> tuple[AgentMarketBenchScenarioAssessmentV1, ...]:
    """Classify exactly the scenarios declared by one case using shared evidence."""

    if type(case) is not AgentMarketBenchCaseV1:
        raise TypeError("case must be exactly an AgentMarketBenchCaseV1")
    if type(admission) is not AgentMarketBenchAdmissionV1:
        raise TypeError("admission must be exactly an AgentMarketBenchAdmissionV1")
    reasons = {rejection.reason.value for rejection in admission.rejections}
    assessments = []
    for scenario in sorted(case.adversarial_scenarios, key=lambda item: item.value):
        if scenario in _PROTOCOL_EXPECTED:
            classification = (
                AgentMarketBenchAdversarialClassificationV1.PREVENTED
                if _PROTOCOL_EXPECTED[scenario] in reasons
                else AgentMarketBenchAdversarialClassificationV1.MEASURED
            )
            basis = AgentMarketBenchScenarioEvidenceBasisV1.SHARED_ADMISSION
        elif scenario in _AI_SCENARIOS:
            classification = AgentMarketBenchAdversarialClassificationV1.OUT_OF_SCOPE
            basis = AgentMarketBenchScenarioEvidenceBasisV1.AI_NOT_EXERCISED
        elif scenario in _ECONOMIC_SCENARIOS:
            classification = AgentMarketBenchAdversarialClassificationV1.MEASURED
            basis = AgentMarketBenchScenarioEvidenceBasisV1.ECONOMIC_SENSITIVITY
        elif scenario in _RUNTIME_SCENARIOS:
            classification = AgentMarketBenchAdversarialClassificationV1.OUT_OF_SCOPE
            basis = AgentMarketBenchScenarioEvidenceBasisV1.FINANCIAL_RUNTIME_NOT_EXERCISED
        else:
            raise ValueError(f"unsupported scenario {scenario!r}")
        assessments.append(
            AgentMarketBenchScenarioAssessmentV1(
                scenario=scenario,
                classification=classification,
                evidence_basis=basis,
            )
        )
    return tuple(assessments)


assess_agent_market_bench_scenarios_v1 = audit_agent_market_bench_scenarios_v1
classify_agent_market_bench_scenarios_v1 = audit_agent_market_bench_scenarios_v1


__all__ = (
    "assess_agent_market_bench_scenarios_v1",
    "audit_agent_market_bench_scenarios_v1",
    "classify_agent_market_bench_scenarios_v1",
)
