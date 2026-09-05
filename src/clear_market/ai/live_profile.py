"""Development-only live model profile with bounded, explicitly paid calls."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Final

from clear_market.ai.buyer_intent import (
    BuyerIntentFreezeError,
    BuyerIntentFreezeErrorCode,
    BuyerPolicyFreezeContextV1,
    interpret_buyer_intent_v1,
)
from clear_market.ai.buyer_intent_parsing import (
    BuyerIntentParseError,
    BuyerIntentParseFailureCode,
)
from clear_market.ai.merchant_offer import (
    MerchantAIContextError,
    MerchantAIContextErrorCode,
    MerchantOfferProposalFreezeError,
    MerchantOfferProposalFreezeErrorCode,
    propose_merchant_offer_candidate_v1,
)
from clear_market.ai.merchant_offer_parsing import (
    MerchantOfferProposalParseError,
    MerchantOfferProposalParseFailureCode,
)
from clear_market.ai.openai_compatible import OpenAICompatibleProvider
from clear_market.ai.provider import AIProvider, AIProviderError, AIProviderErrorCode
from clear_market.commerce import (
    BuyerPolicyV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
    MerchantEconomicPolicyV2,
    MerchantOfferBuildError,
    MerchantOfferBuildErrorCode,
    MerchantOfferCandidateV2,
    MerchantSkuEconomicRuleV2,
    ProvenanceLabel,
    build_merchant_offer_v2,
)
from clear_market.domain import Money
from clear_market.mechanism.v2 import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
)

PROFILE_VERSION: Final[str] = "clear-ai-live-profile-v1"
PROFILE_OPT_IN: Final[str] = "I_UNDERSTAND_THIS_MAKES_MULTIPLE_PAID_REQUESTS"
PROFILE_DISCLAIMER: Final[str] = (
    "development profile; timings are environment- and gateway-sensitive"
)
PROFILE_TIMEOUT_SECONDS: Final[int] = 60
MAX_PROFILE_MODELS: Final[int] = 4

_REQUIRED_ENVIRONMENT: Final[tuple[str, ...]] = (
    "CLEAR_AI_BASE_URL",
    "CLEAR_AI_API_KEY",
    "CLEAR_AI_PROVIDER_NAME",
    "CLEAR_AI_MODELS",
)
_GATEWAY_FAILURE_CODES: Final[frozenset[AIProviderErrorCode]] = frozenset(
    {
        AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
        AIProviderErrorCode.PROVIDER_RATE_LIMITED,
        AIProviderErrorCode.PROVIDER_UNAVAILABLE,
        AIProviderErrorCode.PROVIDER_TIMEOUT,
    }
)
_DEADLINE: Final[datetime] = datetime(2035, 1, 1, 12, 0, tzinfo=UTC)
_PROFILE_BUYER_A_ELIGIBLE_MERCHANTS: Final[tuple[str, str]] = (
    "82000000-0000-4000-8000-000000000011",
    "82000000-0000-4000-8000-000000000012",
)


class LiveProfileConfigurationError(ValueError):
    """Safe configuration failure for the development profile."""


class _ProfileSemanticFailureCode(StrEnum):
    BUYER_POLICY_TYPE_MISMATCH = "BUYER_POLICY_TYPE_MISMATCH"
    BUYER_SEMANTICS_MISMATCH = "BUYER_SEMANTICS_MISMATCH"
    TRUSTED_CONTEXT_MUTATION = "TRUSTED_CONTEXT_MUTATION"
    NO_OFFER = "NO_OFFER"
    INVALID_MERCHANT_CANDIDATE = "INVALID_MERCHANT_CANDIDATE"
    INVALID_SKU = "INVALID_SKU"


class _ProfileFailureClass(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    PROVIDER = "PROVIDER"
    BUYER_PARSE = "BUYER_PARSE"
    BUYER_FREEZE = "BUYER_FREEZE"
    PROFILE_SEMANTIC = "PROFILE_SEMANTIC"
    MERCHANT_CONTEXT = "MERCHANT_CONTEXT"
    MERCHANT_PARSE = "MERCHANT_PARSE"
    MERCHANT_FREEZE = "MERCHANT_FREEZE"
    MERCHANT_BUILD = "MERCHANT_BUILD"
    GATEWAY_TRANSPORT = "GATEWAY_TRANSPORT"
    UNEXPECTED = "UNEXPECTED"


class _ProfileGenericFailureCode(StrEnum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    UNEXPECTED_FAILURE = "UNEXPECTED_FAILURE"


class _ProfileSemanticError(ValueError):
    def __init__(self, code: _ProfileSemanticFailureCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True, repr=False)
class LiveProfileConfig:
    """Explicit profile configuration; the credential is intentionally omitted from repr."""

    base_url: str
    api_key: str = field(repr=False)
    provider_name: str
    models: tuple[str, ...]

    def __repr__(self) -> str:
        return f"LiveProfileConfig(provider_name={self.provider_name!r}, models={self.models!r})"


@dataclass(frozen=True, slots=True)
class _BuyerScenario:
    case_id: str
    buyer_text: str
    requested_quantity: int
    minimum_acceptable_quantity: int
    max_winners: int
    max_total_payment_paise: int
    market_id: str
    buyer_id: str
    eligible_merchant_ids: tuple[str, str]


_BUYER_SCENARIOS: Final[tuple[_BuyerScenario, ...]] = (
    _BuyerScenario(
        case_id="A",
        buyer_text=(
            "Buy exactly 2 units. Maximum total payment is INR 500. "
            "Partial fulfillment is not allowed. Use one winner. "
            "I have no additional product constraints."
        ),
        requested_quantity=2,
        minimum_acceptable_quantity=2,
        max_winners=1,
        max_total_payment_paise=50_000,
        market_id="82000000-0000-4000-8000-000000000001",
        buyer_id="82000000-0000-4000-8000-000000000002",
        eligible_merchant_ids=_PROFILE_BUYER_A_ELIGIBLE_MERCHANTS,
    ),
    _BuyerScenario(
        case_id="B",
        buyer_text=(
            "Buy 6 units. Maximum total payment is INR 1500. "
            "Partial fulfillment is allowed, but I need at least 4 units. "
            "Use at most 2 winners. I have no additional product constraints."
        ),
        requested_quantity=6,
        minimum_acceptable_quantity=4,
        max_winners=2,
        max_total_payment_paise=150_000,
        market_id="82000000-0000-4000-8000-000000000101",
        buyer_id="82000000-0000-4000-8000-000000000102",
        eligible_merchant_ids=(
            "82000000-0000-4000-8000-000000000111",
            "82000000-0000-4000-8000-000000000112",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class _MerchantFixture:
    merchant_id: str
    catalog: MerchantCatalogV2
    inventory: InventorySnapshotV2
    economic_policy: MerchantEconomicPolicyV2
    sku_id: str
    offer_id: str


@dataclass(frozen=True, slots=True)
class _MerchantAttempt:
    merchant_id: str
    elapsed_ns: int
    error: Exception | None = None


class _PaidCallCounter:
    def __init__(self) -> None:
        self._count = 0
        self._lock = Lock()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def increment(self) -> None:
        with self._lock:
            self._count += 1


type ProviderFactory = Callable[..., AIProvider]
type Clock = Callable[[], int]


def _validate_profile_config(config: LiveProfileConfig) -> LiveProfileConfig:
    if type(config) is not LiveProfileConfig:
        raise TypeError("config must be exactly a LiveProfileConfig")
    required_values = (config.base_url, config.api_key, config.provider_name)
    if any(type(value) is not str or value.strip() == "" for value in required_values):
        raise LiveProfileConfigurationError("required profile configuration is missing")

    models = config.models
    if type(models) is not tuple:
        raise LiveProfileConfigurationError("profile models must be supplied as an exact tuple")
    if not models:
        raise LiveProfileConfigurationError("profile model list is empty")
    if any(type(item) is not str or item == "" for item in models):
        raise LiveProfileConfigurationError("profile model list contains an invalid item")
    if any(item.strip() != item for item in models):
        raise LiveProfileConfigurationError("profile model list contains whitespace")
    if len(set(models)) != len(models):
        raise LiveProfileConfigurationError("profile model list contains duplicates")
    if len(models) > MAX_PROFILE_MODELS:
        raise LiveProfileConfigurationError("profile model list is too large")
    return config


def load_profile_config(
    env: Mapping[str, str] | None = None,
) -> LiveProfileConfig:
    """Load explicit opt-in configuration without reading the environment at import time."""
    source = os.environ if env is None else env
    if source.get("CLEAR_AI_PROFILE") != PROFILE_OPT_IN:
        raise LiveProfileConfigurationError("explicit profile opt-in is required")

    missing = tuple(
        name
        for name in _REQUIRED_ENVIRONMENT
        if not isinstance(source.get(name), str) or source.get(name, "").strip() == ""
    )
    if missing:
        raise LiveProfileConfigurationError("required profile configuration is missing")

    return _validate_profile_config(
        LiveProfileConfig(
            base_url=source["CLEAR_AI_BASE_URL"],
            api_key=source["CLEAR_AI_API_KEY"],
            provider_name=source["CLEAR_AI_PROVIDER_NAME"],
            models=tuple(source["CLEAR_AI_MODELS"].split(",")),
        )
    )


def _context_for_scenario(scenario: _BuyerScenario) -> BuyerPolicyFreezeContextV1:
    return BuyerPolicyFreezeContextV1(
        market_id=scenario.market_id,
        buyer_id=scenario.buyer_id,
        eligible_merchant_ids=scenario.eligible_merchant_ids,
        offer_deadline=_DEADLINE,
        mechanism_version=HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
        objective_version=QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    )


def _verify_buyer_policy(
    policy: object,
    scenario: _BuyerScenario,
    context: BuyerPolicyFreezeContextV1,
) -> BuyerPolicyV2:
    if type(policy) is not BuyerPolicyV2:
        raise _ProfileSemanticError(_ProfileSemanticFailureCode.BUYER_POLICY_TYPE_MISMATCH)
    market = policy.market_spec
    if (
        market.requested_quantity != scenario.requested_quantity
        or market.minimum_acceptable_quantity != scenario.minimum_acceptable_quantity
        or market.max_winners != scenario.max_winners
        or policy.max_total_payment.amount_paise != scenario.max_total_payment_paise
        or market.hard_constraints != ()
        or market.soft_preferences != ()
    ):
        raise _ProfileSemanticError(_ProfileSemanticFailureCode.BUYER_SEMANTICS_MISMATCH)
    if (
        market.market_id != context.market_id
        or market.buyer_id != context.buyer_id
        or policy.eligible_merchant_ids != context.eligible_merchant_ids
        or policy.offer_deadline != context.offer_deadline
        or policy.mechanism_version != context.mechanism_version
        or policy.objective_version != context.objective_version
    ):
        raise _ProfileSemanticError(_ProfileSemanticFailureCode.TRUSTED_CONTEXT_MUTATION)
    return policy


def _merchant_fixture(index: int, buyer_policy: BuyerPolicyV2) -> _MerchantFixture:
    merchant_id = buyer_policy.eligible_merchant_ids[index]
    catalog_id = f"83000000-0000-4000-8000-0000000000{index + 1:02d}"
    product_id = f"84000000-0000-4000-8000-0000000000{index + 1:02d}"
    sku_id = f"85000000-0000-4000-8000-0000000000{index + 1:02d}"
    snapshot_id = f"86000000-0000-4000-8000-0000000000{index + 1:02d}"
    economic_policy_id = f"87000000-0000-4000-8000-0000000000{index + 1:02d}"
    evidence_id = f"88000000-0000-4000-8000-0000000000{index + 1:02d}"
    offer_id = f"89000000-0000-4000-8000-0000000000{index + 1:02d}"
    catalog = MerchantCatalogV2(
        catalog_id=catalog_id,
        merchant_id=merchant_id,
        generated_at=datetime(2035, 1, 1, 10 + index, 0, tzinfo=UTC),
        products=(
            CatalogProductV2(
                product_id=product_id,
                display_name=f"Profile item {index + 1}",
                description="Fixed development profile fixture.",
            ),
        ),
        skus=(
            CatalogSkuV2(
                sku_id=sku_id,
                product_id=product_id,
                merchant_sku=f"PROFILE-{index + 1}",
                display_name=f"Profile SKU {index + 1}",
                attributes=(),
            ),
        ),
    )
    inventory = InventorySnapshotV2(
        snapshot_id=snapshot_id,
        catalog_id=catalog_id,
        merchant_id=merchant_id,
        captured_at=datetime(2035, 1, 1, 11 + index, 0, tzinfo=UTC),
        lines=(
            InventoryLineV2(
                sku_id=sku_id,
                quantity_available=2,
                provenance=ProvenanceLabel.VERIFIED,
                evidence_reference_id=evidence_id,
            ),
        ),
    )
    economic_policy = MerchantEconomicPolicyV2(
        economic_policy_id=economic_policy_id,
        merchant_id=merchant_id,
        catalog_id=catalog_id,
        sku_rules=(
            MerchantSkuEconomicRuleV2(
                sku_id=sku_id,
                unit_cost_basis=Money(amount_paise=1_000 + index * 500),
                minimum_margin=Money(amount_paise=200),
                max_quantity_per_offer=2,
            ),
        ),
    )
    return _MerchantFixture(
        merchant_id=merchant_id,
        catalog=catalog,
        inventory=inventory,
        economic_policy=economic_policy,
        sku_id=sku_id,
        offer_id=offer_id,
    )


def _elapsed_ns(start: int, end: int) -> int:
    return max(0, end - start)


def _milliseconds(elapsed_ns: int) -> float:
    return round(_elapsed_ns(0, elapsed_ns) / 1_000_000, 3)


def _safe_failure_metadata(error: Exception) -> tuple[str, str]:
    if type(error) is AIProviderError and type(error.code) is AIProviderErrorCode:
        return _ProfileFailureClass.PROVIDER.value, error.code.value
    if type(error) is BuyerIntentParseError and type(error.code) is BuyerIntentParseFailureCode:
        return _ProfileFailureClass.BUYER_PARSE.value, error.code.value
    if type(error) is BuyerIntentFreezeError and type(error.code) is BuyerIntentFreezeErrorCode:
        return _ProfileFailureClass.BUYER_FREEZE.value, error.code.value
    if type(error) is _ProfileSemanticError and type(error.code) is _ProfileSemanticFailureCode:
        return _ProfileFailureClass.PROFILE_SEMANTIC.value, error.code.value
    if type(error) is MerchantAIContextError and type(error.code) is MerchantAIContextErrorCode:
        return _ProfileFailureClass.MERCHANT_CONTEXT.value, error.code.value
    if (
        type(error) is MerchantOfferProposalParseError
        and type(error.code) is MerchantOfferProposalParseFailureCode
    ):
        return _ProfileFailureClass.MERCHANT_PARSE.value, error.code.value
    if (
        type(error) is MerchantOfferProposalFreezeError
        and type(error.code) is MerchantOfferProposalFreezeErrorCode
    ):
        return _ProfileFailureClass.MERCHANT_FREEZE.value, error.code.value
    if type(error) is MerchantOfferBuildError and type(error.code) is MerchantOfferBuildErrorCode:
        return _ProfileFailureClass.MERCHANT_BUILD.value, error.code.value
    if isinstance(error, TimeoutError):
        return (
            _ProfileFailureClass.GATEWAY_TRANSPORT.value,
            AIProviderErrorCode.PROVIDER_TIMEOUT.value,
        )
    if isinstance(error, OSError):
        return (
            _ProfileFailureClass.GATEWAY_TRANSPORT.value,
            AIProviderErrorCode.PROVIDER_UNAVAILABLE.value,
        )
    return (
        _ProfileFailureClass.UNEXPECTED.value,
        _ProfileGenericFailureCode.UNEXPECTED_FAILURE.value,
    )


def _failure(
    *,
    phase: str,
    model: str,
    error: Exception,
    case_id: str | None = None,
    merchant_id: str | None = None,
) -> dict[str, object]:
    failure_class, error_code = _safe_failure_metadata(error)
    result: dict[str, object] = {
        "error_code": error_code,
        "failure_class": failure_class,
        "model": model,
        "phase": phase,
    }
    if case_id is not None:
        result["case_id"] = case_id
    if merchant_id is not None:
        result["merchant_id"] = merchant_id
    return result


def _is_gateway_failure(error: Exception) -> bool:
    if isinstance(error, AIProviderError):
        return error.code in _GATEWAY_FAILURE_CODES
    return isinstance(error, (TimeoutError, OSError))


def _provider_for(config: LiveProfileConfig, factory: ProviderFactory) -> AIProvider:
    return factory(
        base_url=config.base_url,
        api_key=config.api_key,
        timeout_seconds=PROFILE_TIMEOUT_SECONDS,
    )


def _merchant_worker(
    *,
    config: LiveProfileConfig,
    factory: ProviderFactory,
    model: str,
    buyer_policy: BuyerPolicyV2,
    fixture: _MerchantFixture,
    counter: _PaidCallCounter,
    clock: Clock,
) -> _MerchantAttempt:
    try:
        provider = _provider_for(config, factory)
    except Exception as error:
        return _MerchantAttempt(fixture.merchant_id, 0, error)

    start = clock()
    counter.increment()
    try:
        candidate = propose_merchant_offer_candidate_v1(
            provider=provider,
            request_id=fixture.offer_id,
            provider_name=config.provider_name,
            model=model,
            buyer_policy=buyer_policy,
            catalog=fixture.catalog,
            inventory=fixture.inventory,
            economic_policy=fixture.economic_policy,
        )
        if candidate is None:
            raise _ProfileSemanticError(_ProfileSemanticFailureCode.NO_OFFER)
        if type(candidate) is not MerchantOfferCandidateV2 or len(candidate.lines) != 1:
            raise _ProfileSemanticError(_ProfileSemanticFailureCode.INVALID_MERCHANT_CANDIDATE)
        if any(line.sku_id != fixture.sku_id for line in candidate.lines):
            raise _ProfileSemanticError(_ProfileSemanticFailureCode.INVALID_SKU)
        build_merchant_offer_v2(
            offer_id=fixture.offer_id,
            buyer_policy=buyer_policy,
            catalog=fixture.catalog,
            inventory=fixture.inventory,
            economic_policy=fixture.economic_policy,
            candidate=candidate,
        )
    except Exception as error:
        return _MerchantAttempt(fixture.merchant_id, _elapsed_ns(start, clock()), error)
    return _MerchantAttempt(fixture.merchant_id, _elapsed_ns(start, clock()))


def _base_report(
    *,
    config: LiveProfileConfig,
    counter: _PaidCallCounter,
    model_reports: list[dict[str, object]],
    aborted: bool,
    abort_failure: dict[str, object] | None,
) -> dict[str, object]:
    fully_passing = [
        report
        for report in model_reports
        if report.get("passed") is True
        and isinstance(report.get("buyer_mean_ms"), (int, float))
        and isinstance(report.get("merchant_parallel_wall_ms"), (int, float))
    ]
    recommendation: str | None = None
    if fully_passing:

        def score(report: dict[str, object]) -> float:
            buyer_mean = report.get("buyer_mean_ms")
            parallel_wall = report.get("merchant_parallel_wall_ms")
            if not isinstance(buyer_mean, (int, float)) or not isinstance(
                parallel_wall, (int, float)
            ):
                return float("inf")
            return float(buyer_mean) + float(parallel_wall)

        recommended_report = min(
            fully_passing,
            key=lambda report: (score(report), str(report["model"])),
        )
        recommended_model = recommended_report.get("model")
        if isinstance(recommended_model, str):
            recommendation = recommended_model

    result: dict[str, object] = {
        "all_models_passed": (
            not aborted
            and len(model_reports) == len(config.models)
            and bool(model_reports)
            and all(report.get("passed") is True for report in model_reports)
        ),
        "candidate_model_count": len(config.models),
        "development_demo_latency_recommendation": recommendation,
        "disclaimer": PROFILE_DISCLAIMER,
        "models": model_reports,
        "paid_call_count": counter.count,
        "profile_version": PROFILE_VERSION,
        "schema_version": "1",
    }
    if aborted and abort_failure is not None:
        result["aborted"] = True
        result["failure"] = abort_failure
    return result


def run_live_profile(
    config: LiveProfileConfig,
    *,
    provider_factory: ProviderFactory | None = None,
    clock_ns: Clock | None = None,
    authorize_paid_calls: bool = False,
) -> dict[str, object]:
    """Run the fixed development profile using an injected provider factory in tests."""
    config = _validate_profile_config(config)
    factory: ProviderFactory
    if provider_factory is None:
        if authorize_paid_calls is not True:
            raise LiveProfileConfigurationError("explicit paid-call authorization is required")
        factory = OpenAICompatibleProvider
    else:
        factory = provider_factory
    clock = time.perf_counter_ns if clock_ns is None else clock_ns
    counter = _PaidCallCounter()
    model_reports: list[dict[str, object]] = []
    aborted = False
    abort_failure: dict[str, object] | None = None

    for model in config.models:
        model_report: dict[str, object] = {
            "buyer_cases": [],
            "merchant_calls": [],
            "model": model,
            "passed": False,
        }
        buyer_cases = model_report["buyer_cases"]
        if not isinstance(buyer_cases, list):
            raise AssertionError("internal report shape")
        buyer_policies: dict[str, BuyerPolicyV2] = {}
        gateway_error: tuple[str, Exception] | None = None
        for scenario in _BUYER_SCENARIOS:
            context = _context_for_scenario(scenario)
            case_report: dict[str, object] = {"case_id": scenario.case_id, "passed": False}
            start: int | None = None
            try:
                provider = _provider_for(config, factory)
                start = clock()
                counter.increment()
                policy = interpret_buyer_intent_v1(
                    provider=provider,
                    request_id=scenario.buyer_id,
                    provider_name=config.provider_name,
                    model=model,
                    buyer_text=scenario.buyer_text,
                    freeze_context=context,
                )
                buyer_policies[scenario.case_id] = _verify_buyer_policy(
                    policy,
                    scenario,
                    context,
                )
                elapsed_ns = _elapsed_ns(start, clock())
                case_report["passed"] = True
            except Exception as error:
                elapsed_ns = _elapsed_ns(start, clock()) if start is not None else 0
                case_report["failure"] = _failure(
                    phase="buyer",
                    model=model,
                    case_id=scenario.case_id,
                    error=error,
                )
                if _is_gateway_failure(error):
                    gateway_error = (scenario.case_id, error)
            case_report["e2e_ms"] = _milliseconds(elapsed_ns)
            buyer_cases.append(case_report)
            if gateway_error is not None:
                break

        if gateway_error is not None:
            case_id, gateway_case_error = gateway_error
            abort_failure = _failure(
                phase="buyer",
                model=model,
                case_id=case_id,
                error=gateway_case_error,
            )
            model_report["failure"] = abort_failure
            model_reports.append(model_report)
            aborted = True
            break

        if len(buyer_policies) != len(_BUYER_SCENARIOS):
            model_reports.append(model_report)
            continue

        buyer_case_values = [
            float(case["e2e_ms"]) for case in buyer_cases if case.get("passed") is True
        ]
        if len(buyer_case_values) != len(_BUYER_SCENARIOS):
            raise AssertionError("internal buyer timing shape")
        model_report["buyer_mean_ms"] = round(
            sum(buyer_case_values) / len(_BUYER_SCENARIOS),
            3,
        )

        buyer_policy = buyer_policies["A"]
        fixtures = tuple(
            _merchant_fixture(index, buyer_policy)
            for index in range(len(_PROFILE_BUYER_A_ELIGIBLE_MERCHANTS))
        )
        parallel_start = clock()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                fixture.merchant_id: executor.submit(
                    _merchant_worker,
                    config=config,
                    factory=factory,
                    model=model,
                    buyer_policy=buyer_policy,
                    fixture=fixture,
                    counter=counter,
                    clock=clock,
                )
                for fixture in fixtures
            }
            attempts = {
                merchant_id: futures[merchant_id].result() for merchant_id in sorted(futures)
            }
        parallel_wall_ms = _milliseconds(_elapsed_ns(parallel_start, clock()))
        merchant_calls = model_report["merchant_calls"]
        if not isinstance(merchant_calls, list):
            raise AssertionError("internal report shape")
        merchant_gateway_error: tuple[str, Exception] | None = None
        for merchant_id in sorted(attempts):
            attempt = attempts[merchant_id]
            merchant_report: dict[str, object] = {
                "e2e_ms": _milliseconds(attempt.elapsed_ns),
                "merchant_id": merchant_id,
                "passed": attempt.error is None,
            }
            if attempt.error is not None:
                merchant_report["failure"] = _failure(
                    phase="merchant",
                    model=model,
                    merchant_id=merchant_id,
                    error=attempt.error,
                )
                if _is_gateway_failure(attempt.error):
                    merchant_gateway_error = (merchant_id, attempt.error)
            merchant_calls.append(merchant_report)
        model_report["merchant_parallel_wall_ms"] = parallel_wall_ms
        merchant_values = [float(call["e2e_ms"]) for call in merchant_calls]
        if parallel_wall_ms > 0:
            model_report["merchant_parallel_speedup_descriptive"] = round(
                sum(merchant_values) / parallel_wall_ms,
                3,
            )
        if merchant_gateway_error is not None:
            merchant_id, gateway_merchant_error = merchant_gateway_error
            abort_failure = _failure(
                phase="merchant",
                model=model,
                merchant_id=merchant_id,
                error=gateway_merchant_error,
            )
            model_report["failure"] = abort_failure
            model_reports.append(model_report)
            aborted = True
            break
        if any(call.get("passed") is not True for call in merchant_calls):
            model_reports.append(model_report)
            continue

        model_report["passed"] = True
        model_reports.append(model_report)

    return _base_report(
        config=config,
        counter=counter,
        model_reports=model_reports,
        aborted=aborted,
        abort_failure=abort_failure,
    )


run_profile = run_live_profile


def _configuration_report() -> dict[str, object]:
    return {
        "all_models_passed": False,
        "candidate_model_count": 0,
        "development_demo_latency_recommendation": None,
        "disclaimer": PROFILE_DISCLAIMER,
        "failure": {
            "error_code": _ProfileGenericFailureCode.CONFIGURATION_ERROR.value,
            "failure_class": _ProfileFailureClass.CONFIGURATION.value,
            "phase": "configuration",
        },
        "models": [],
        "paid_call_count": 0,
        "profile_version": PROFILE_VERSION,
        "schema_version": "1",
    }


def _print_report(report: dict[str, object]) -> None:
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main() -> int:
    try:
        config = load_profile_config()
    except LiveProfileConfigurationError:
        _print_report(_configuration_report())
        return 2
    report = run_live_profile(config, authorize_paid_calls=True)
    _print_report(report)
    return 0 if report.get("all_models_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "MAX_PROFILE_MODELS",
    "PROFILE_DISCLAIMER",
    "PROFILE_OPT_IN",
    "PROFILE_TIMEOUT_SECONDS",
    "PROFILE_VERSION",
    "LiveProfileConfig",
    "LiveProfileConfigurationError",
    "load_profile_config",
    "main",
    "run_live_profile",
    "run_profile",
)
