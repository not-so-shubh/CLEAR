"""AgentMarketBench projections and canonical case identity."""

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import cast

from clear_market.agentmarketbench.models import (
    AgentMarketBenchCaseV1,
    AgentMarketBenchMarketInputV1,
    _fresh_exact,
)
from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    canonical_utc_datetime,
)


def agent_market_bench_market_input_v1(
    case: AgentMarketBenchCaseV1,
) -> AgentMarketBenchMarketInputV1:
    """Project a validated case into the complete latent-free method-visible input."""
    if type(case) is not AgentMarketBenchCaseV1:
        raise TypeError("case must be exactly an AgentMarketBenchCaseV1")
    fresh_case = _fresh_exact(AgentMarketBenchCaseV1, case)
    return AgentMarketBenchMarketInputV1(
        buyer_policy=fresh_case.buyer_policy,
        observed_merchants=fresh_case.observed_merchants,
        reported_offers=fresh_case.reported_offers,
    )


def _canonical_projection(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return canonical_utc_datetime(value)
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        return {key: _canonical_projection(item) for key, item in mapping.items()}
    if type(value) is tuple:
        return [_canonical_projection(item) for item in value]
    if type(value) is list:
        return [_canonical_projection(item) for item in value]
    return value


def canonical_agent_market_bench_case_v1_bytes(value: AgentMarketBenchCaseV1) -> bytes:
    """Serialize the complete validated case, including latent truth, deterministically."""
    if type(value) is not AgentMarketBenchCaseV1:
        raise TypeError("value must be exactly an AgentMarketBenchCaseV1")
    fresh_case = _fresh_exact(AgentMarketBenchCaseV1, value)
    payload = _canonical_projection(fresh_case.model_dump(mode="python"))
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "agent_market_bench_case_v1",
            "payload": payload,
        }
    )


def agent_market_bench_case_v1_digest(value: AgentMarketBenchCaseV1) -> str:
    """Return the benchmark-record SHA-256 identity, not financial authorization."""
    return sha256(canonical_agent_market_bench_case_v1_bytes(value)).hexdigest()
