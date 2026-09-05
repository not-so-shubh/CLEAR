import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest

import clear_market.ai.live_profile as live_profile
from clear_market.ai import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseV1,
    AIProviderTask,
)
from clear_market.ai.live_profile import (
    MAX_PROFILE_MODELS,
    PROFILE_DISCLAIMER,
    PROFILE_OPT_IN,
    PROFILE_VERSION,
    LiveProfileConfig,
    LiveProfileConfigurationError,
    load_profile_config,
    run_live_profile,
)

_FAKE_KEY = "fake-profile-key"
_PROVIDER_NAME = "gateway.test"


def _config(*models: str) -> LiveProfileConfig:
    return LiveProfileConfig(
        base_url="https://example.invalid/v1",
        api_key=_FAKE_KEY,
        provider_name=_PROVIDER_NAME,
        models=tuple(models or ("model-a",)),
    )


def _profile_environment(*models: str) -> dict[str, str]:
    return {
        "CLEAR_AI_PROFILE": PROFILE_OPT_IN,
        "CLEAR_AI_BASE_URL": "https://example.invalid/v1",
        "CLEAR_AI_API_KEY": _FAKE_KEY,
        "CLEAR_AI_PROVIDER_NAME": _PROVIDER_NAME,
        "CLEAR_AI_MODELS": ",".join(models or ("model-a",)),
    }


def _buyer_candidate(case_id: str, mode: str) -> dict[str, object]:
    if case_id == "A":
        payload: dict[str, object] = {
            "schema_version": "1",
            "buyer_intent_candidate_version": "buyer-intent-candidate-v1",
            "requested_quantity": 2,
            "minimum_acceptable_quantity": 2,
            "max_winners": 1,
            "max_total_payment_paise": 50_000,
            "hard_constraints": [],
            "soft_preferences": [],
        }
    else:
        payload = {
            "schema_version": "1",
            "buyer_intent_candidate_version": "buyer-intent-candidate-v1",
            "requested_quantity": 6,
            "minimum_acceptable_quantity": 4,
            "max_winners": 2,
            "max_total_payment_paise": 150_000,
            "hard_constraints": [],
            "soft_preferences": [],
        }
    if case_id == "A":
        if mode == "wrong_quantity":
            payload["requested_quantity"] = 3
            payload["minimum_acceptable_quantity"] = 3
        elif mode == "wrong_minimum":
            payload["minimum_acceptable_quantity"] = 1
        elif mode == "wrong_max_winners":
            payload["max_winners"] = 2
        elif mode == "wrong_budget":
            payload["max_total_payment_paise"] = 49_999
        elif mode == "invented_constraints":
            payload["hard_constraints"] = [
                {
                    "schema_version": "1",
                    "buyer_intent_rule_candidate_version": "buyer-intent-rule-candidate-v1",
                    "rule_id": "91000000-0000-4000-8000-000000000001",
                    "attribute_key": "brand",
                    "operator": "eq",
                    "value_type": "string",
                    "value": "synthetic",
                    "allowed_provenance": ["CLAIMED"],
                }
            ]
        elif mode == "invented_preferences":
            payload["soft_preferences"] = [
                {
                    "schema_version": "1",
                    "buyer_intent_rule_candidate_version": "buyer-intent-rule-candidate-v1",
                    "rule_id": "91000000-0000-4000-8000-000000000002",
                    "attribute_key": "color",
                    "operator": "eq",
                    "value_type": "string",
                    "value": "synthetic",
                    "allowed_provenance": ["CLAIMED"],
                }
            ]
    return payload


class _FakeProvider:
    def __init__(self, behavior: str, owner: "_FakeFactory") -> None:
        self.behavior = behavior
        self.owner = owner
        self.requests: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        behavior = self.owner.behavior_for(request.model)
        with self.owner.lock:
            self.requests.append(request)
            self.owner.all_requests.append(request)
        if behavior == "gateway_timeout":
            raise AIProviderError(AIProviderErrorCode.PROVIDER_TIMEOUT)
        if behavior == "fail_first_buyer" and request.task is AIProviderTask.BUYER_INTENT:
            if request.input_text.startswith("Buy exactly 2 units"):
                raise AIProviderError(AIProviderErrorCode.INVALID_RESPONSE)
        if behavior == "reject_request":
            raise AIProviderError(AIProviderErrorCode.PROVIDER_REQUEST_REJECTED)

        if request.task is AIProviderTask.BUYER_INTENT:
            case_id = "A" if request.input_text.startswith("Buy exactly 2 units") else "B"
            payload = _buyer_candidate(case_id, behavior)
        else:
            context = cast(dict[str, object], json.loads(request.input_text))
            sku = cast(list[dict[str, object]], context["offerable_skus"])[0]
            merchant_id = cast(str, context["merchant_id"])
            sku_id = cast(str, sku["sku_id"])
            minimum_price = cast(int, sku["minimum_unit_price_paise"])
            if behavior == "no_offer" or (
                behavior == "one_no_offer" and merchant_id.endswith("11")
            ):
                payload = {
                    "schema_version": "1",
                    "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
                    "decision": "NO_OFFER",
                    "lines": [],
                }
            else:
                if behavior == "invalid_sku":
                    sku_id = "92000000-0000-4000-8000-000000000999"
                if behavior == "below_floor":
                    minimum_price -= 1
                payload = {
                    "schema_version": "1",
                    "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
                    "decision": "OFFER",
                    "lines": [
                        {
                            "schema_version": "1",
                            "merchant_offer_proposal_line_version": (
                                "merchant-offer-proposal-line-v1"
                            ),
                            "sku_id": sku_id,
                            "proposed_quantity": 2,
                            "proposed_unit_price_paise": minimum_price,
                        }
                    ],
                }
        output_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return AIProviderResponseV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            finish_reason=AIProviderFinishReason.COMPLETED,
            output_text=output_text,
        )


class _FakeFactory:
    def __init__(self, behavior: str = "success") -> None:
        self.behavior = behavior
        self.instances: list[_FakeProvider] = []
        self.all_requests: list[AIProviderRequestV1] = []
        self.lock = threading.Lock()

    def behavior_for(self, _model: str) -> str:
        return self.behavior

    def __call__(self, **_kwargs: object) -> _FakeProvider:
        provider = _FakeProvider(self.behavior, self)
        with self.lock:
            self.instances.append(provider)
        return provider


class _ModelFactory(_FakeFactory):
    def __init__(self, behaviors: dict[str, str]) -> None:
        super().__init__()
        self.behaviors = behaviors

    def behavior_for(self, model: str) -> str:
        return self.behaviors.get(model, "success")


def _factory_for(behavior: str = "success") -> _FakeFactory:
    return _FakeFactory(behavior)


def _step_clock() -> Callable[[], int]:
    state = {"value": 0}
    lock = threading.Lock()

    def clock() -> int:
        with lock:
            state["value"] += 1_000_000
            return state["value"]

    return clock


def test_configuration_requires_opt_in_and_all_required_values() -> None:
    with pytest.raises(LiveProfileConfigurationError):
        load_profile_config({})
    with pytest.raises(LiveProfileConfigurationError):
        load_profile_config({"CLEAR_AI_PROFILE": PROFILE_OPT_IN})


def test_configuration_rejects_invalid_model_lists() -> None:
    base = _profile_environment()
    base.pop("CLEAR_AI_MODELS")
    for raw_models in ("", "model-a,", "model-a, model-b", "model-a,model-a"):
        with pytest.raises(LiveProfileConfigurationError):
            load_profile_config({**base, "CLEAR_AI_MODELS": raw_models})
    too_many = ",".join(f"model-{index}" for index in range(MAX_PROFILE_MODELS + 1))
    with pytest.raises(LiveProfileConfigurationError):
        load_profile_config({**base, "CLEAR_AI_MODELS": too_many})


def test_configuration_repr_does_not_include_credential() -> None:
    config = _config()
    assert _FAKE_KEY not in repr(config)
    assert _FAKE_KEY not in str(config)


def test_direct_config_over_four_models_is_rejected_before_provider_use() -> None:
    factory = _factory_for()
    config = LiveProfileConfig(
        base_url="https://example.invalid/v1",
        api_key=_FAKE_KEY,
        provider_name=_PROVIDER_NAME,
        models=tuple(f"model-{index}" for index in range(MAX_PROFILE_MODELS + 1)),
    )
    with pytest.raises(LiveProfileConfigurationError):
        run_live_profile(config, provider_factory=factory)
    assert factory.instances == []
    assert factory.all_requests == []


@pytest.mark.parametrize(
    "models",
    [
        (),
        ("",),
        ("model-a", "model-a"),
        ("model-a", " model-b"),
        ("model-a", "model-b "),
    ],
)
def test_direct_config_invalid_model_tuple_is_rejected_before_calls(
    models: tuple[str, ...],
) -> None:
    factory = _factory_for()
    config = LiveProfileConfig(
        base_url="https://example.invalid/v1",
        api_key=_FAKE_KEY,
        provider_name=_PROVIDER_NAME,
        models=models,
    )
    with pytest.raises(LiveProfileConfigurationError):
        run_live_profile(config, provider_factory=factory)
    assert factory.instances == []
    assert factory.all_requests == []


def test_default_provider_requires_paid_authorization_before_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_provider(**_kwargs: object) -> _FakeProvider:
        raise AssertionError("default provider must not be constructed")

    monkeypatch.setattr(live_profile, "OpenAICompatibleProvider", unexpected_provider)
    with pytest.raises(LiveProfileConfigurationError):
        run_live_profile(_config())


def test_authorized_default_path_accepts_four_models_and_rejects_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory_for()
    monkeypatch.setattr(live_profile, "OpenAICompatibleProvider", factory)
    four_models = tuple(f"model-{index}" for index in range(MAX_PROFILE_MODELS))
    report = run_live_profile(
        _config(*four_models),
        clock_ns=_step_clock(),
        authorize_paid_calls=True,
    )
    assert report["paid_call_count"] == MAX_PROFILE_MODELS * 4
    assert len(factory.all_requests) == MAX_PROFILE_MODELS * 4

    five_model_config = LiveProfileConfig(
        base_url="https://example.invalid/v1",
        api_key=_FAKE_KEY,
        provider_name=_PROVIDER_NAME,
        models=(*four_models, "model-4"),
    )
    with pytest.raises(LiveProfileConfigurationError):
        run_live_profile(five_model_config, authorize_paid_calls=True)
    assert len(factory.all_requests) == MAX_PROFILE_MODELS * 4


def test_fake_provider_path_requires_no_environment_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLEAR_AI_PROFILE", raising=False)
    factory = _factory_for()
    report = run_live_profile(
        _config(),
        provider_factory=factory,
        clock_ns=_step_clock(),
    )
    assert report["all_models_passed"] is True
    assert report["paid_call_count"] == 4


def test_failure_metadata_uses_only_closed_safe_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contaminated_type = type(f"Leaked_{_FAKE_KEY}", (RuntimeError,), {})
    contaminated_error = contaminated_type(f"raw output and {_FAKE_KEY}")
    contaminated_error.code = f"UNSAFE_{_FAKE_KEY}"

    def raise_contaminated_error(**_kwargs: object) -> object:
        raise contaminated_error

    monkeypatch.setattr(
        live_profile,
        "interpret_buyer_intent_v1",
        raise_contaminated_error,
    )
    report = run_live_profile(
        _config(),
        provider_factory=_factory_for(),
        clock_ns=_step_clock(),
    )
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    assert _FAKE_KEY not in encoded
    model = cast(list[dict[str, object]], report["models"])[0]
    for case in cast(list[dict[str, object]], model["buyer_cases"]):
        failure = cast(dict[str, object], case["failure"])
        assert failure["error_code"] == "UNEXPECTED_FAILURE"
        assert failure["failure_class"] == "UNEXPECTED"
        assert "exception_class" not in failure


def test_successful_model_uses_exactly_four_paid_calls_and_two_merchants() -> None:
    factory = _factory_for()
    report = run_live_profile(_config(), provider_factory=factory, clock_ns=_step_clock())

    assert report["paid_call_count"] == 4
    model = cast(list[dict[str, object]], report["models"])[0]
    assert model["passed"] is True
    assert len(cast(list[object], model["buyer_cases"])) == 2
    merchant_calls = cast(list[dict[str, object]], model["merchant_calls"])
    assert len(merchant_calls) == 2
    assert len(factory.instances) == 4
    assert len({id(instance) for instance in factory.instances[2:]}) == 2


def test_failed_first_buyer_skips_merchants_and_continues_models() -> None:
    first = _factory_for("fail_first_buyer")
    first_report = run_live_profile(_config(), provider_factory=first, clock_ns=_step_clock())
    first_model = cast(list[dict[str, object]], first_report["models"])[0]
    assert first_report["paid_call_count"] == 2
    assert first_model["passed"] is False
    assert first_model["merchant_calls"] == []
    assert len(first.instances) == 2

    factory = _ModelFactory({"failed-model": "fail_first_buyer", "good-model": "success"})
    report = run_live_profile(
        _config("failed-model", "good-model"),
        provider_factory=factory,
        clock_ns=_step_clock(),
    )
    assert report["paid_call_count"] == 6
    assert len(cast(list[object], report["models"])) == 2


def test_gateway_failure_aborts_remaining_models_without_retry() -> None:
    factory = _factory_for("gateway_timeout")
    report = run_live_profile(
        _config("model-a", "model-b"),
        provider_factory=factory,
        clock_ns=_step_clock(),
    )
    assert report["aborted"] is True
    assert report["paid_call_count"] == 1
    assert len(cast(list[object], report["models"])) == 1
    assert len(factory.instances) == 1
    failure = cast(dict[str, object], report["failure"])
    assert failure["error_code"] == "PROVIDER_TIMEOUT"
    assert failure["failure_class"] == "PROVIDER"


@pytest.mark.parametrize(
    "behavior",
    [
        "wrong_quantity",
        "wrong_minimum",
        "wrong_max_winners",
        "wrong_budget",
        "invented_constraints",
        "invented_preferences",
    ],
)
def test_buyer_semantic_mismatch_fails_model_without_merchants(behavior: str) -> None:
    factory = _factory_for(behavior)
    report = run_live_profile(_config(), provider_factory=factory, clock_ns=_step_clock())
    model = cast(list[dict[str, object]], report["models"])[0]
    assert model["passed"] is False
    assert model["merchant_calls"] == []
    assert len(factory.instances) == 2


def test_trusted_context_mutation_cannot_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    original = live_profile.interpret_buyer_intent_v1

    def mutate_context(**kwargs: object) -> object:
        policy = original(**kwargs)  # type: ignore[arg-type]
        assert type(policy).__name__ == "BuyerPolicyV2"
        return policy.model_copy(update={"offer_deadline": datetime(2036, 1, 1, tzinfo=UTC)})

    monkeypatch.setattr(live_profile, "interpret_buyer_intent_v1", mutate_context)
    report = run_live_profile(_config(), provider_factory=_factory_for(), clock_ns=_step_clock())
    model = cast(list[dict[str, object]], report["models"])[0]
    assert model["passed"] is False
    assert model["merchant_calls"] == []


@pytest.mark.parametrize("behavior", ["no_offer", "invalid_sku", "below_floor"])
def test_merchant_deterministic_validation_is_required(behavior: str) -> None:
    factory = _factory_for(behavior)
    report = run_live_profile(_config(), provider_factory=factory, clock_ns=_step_clock())
    model = cast(list[dict[str, object]], report["models"])[0]
    assert model["passed"] is False
    merchants = cast(list[dict[str, object]], model["merchant_calls"])
    assert len(merchants) == 2
    assert all(call["passed"] is False for call in merchants)
    if behavior == "below_floor":
        failures = [cast(dict[str, object], call["failure"]) for call in merchants]
        assert all(
            failure["error_code"] == "CANDIDATE_PRICE_BELOW_FLOOR"
            and failure["failure_class"] == "MERCHANT_BUILD"
            for failure in failures
        )


def test_complete_buyer_and_merchant_timings_survive_one_merchant_failure() -> None:
    report = run_live_profile(
        _config(),
        provider_factory=_factory_for("one_no_offer"),
        clock_ns=_step_clock(),
    )
    model = cast(list[dict[str, object]], report["models"])[0]
    assert model["passed"] is False
    buyer_cases = cast(list[dict[str, object]], model["buyer_cases"])
    expected_buyer_mean = round(sum(float(case["e2e_ms"]) for case in buyer_cases) / 2, 3)
    assert model["buyer_mean_ms"] == expected_buyer_mean

    merchant_calls = cast(list[dict[str, object]], model["merchant_calls"])
    assert [call["passed"] for call in merchant_calls].count(False) == 1
    wall = float(model["merchant_parallel_wall_ms"])
    assert wall > 0
    expected_speedup = round(
        sum(float(call["e2e_ms"]) for call in merchant_calls) / wall,
        3,
    )
    assert model["merchant_parallel_speedup_descriptive"] == expected_speedup


def test_merchants_are_reported_in_id_order_after_reversed_two_worker_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_executor = live_profile.ThreadPoolExecutor
    worker_counts: list[int] = []

    def recording_executor(*, max_workers: int) -> object:
        worker_counts.append(max_workers)
        return original_executor(max_workers=max_workers)

    original_worker = live_profile._merchant_worker
    second_worker_done = threading.Event()
    completion_order: list[str] = []

    def reversed_worker(**kwargs: object) -> object:
        fixture = cast(live_profile._MerchantFixture, kwargs["fixture"])
        merchant_id = fixture.merchant_id
        if merchant_id.endswith("11"):
            assert second_worker_done.wait(timeout=2)
        attempt = original_worker(**kwargs)  # type: ignore[arg-type]
        completion_order.append(merchant_id)
        if merchant_id.endswith("12"):
            second_worker_done.set()
        return attempt

    monkeypatch.setattr(live_profile, "ThreadPoolExecutor", recording_executor)
    monkeypatch.setattr(live_profile, "_merchant_worker", reversed_worker)
    factory = _factory_for()
    report = run_live_profile(_config(), provider_factory=factory, clock_ns=_step_clock())
    model = cast(list[dict[str, object]], report["models"])[0]
    merchants = cast(list[dict[str, object]], model["merchant_calls"])
    merchant_ids = [cast(str, merchant["merchant_id"]) for merchant in merchants]
    assert merchant_ids == sorted(merchant_ids)
    assert completion_order == list(reversed(merchant_ids))
    assert worker_counts == [2]
    merchant_requests = [
        request for request in factory.all_requests if request.task is AIProviderTask.MERCHANT_OFFER
    ]
    assert len(merchant_requests) == 2


def test_timing_and_descriptive_speedup_are_nonnegative_and_formula_based() -> None:
    factory = _factory_for()
    report = run_live_profile(_config(), provider_factory=factory, clock_ns=_step_clock())
    model = cast(list[dict[str, object]], report["models"])[0]
    buyer_cases = cast(list[dict[str, object]], model["buyer_cases"])
    merchant_calls = cast(list[dict[str, object]], model["merchant_calls"])
    wall = cast(float, model["merchant_parallel_wall_ms"])
    assert all(cast(float, case["e2e_ms"]) >= 0 for case in buyer_cases)
    assert all(cast(float, call["e2e_ms"]) >= 0 for call in merchant_calls)
    assert wall >= 0
    expected = (
        0.0 if wall == 0 else round(sum(float(c["e2e_ms"]) for c in merchant_calls) / wall, 3)
    )
    assert model["merchant_parallel_speedup_descriptive"] == expected


def test_recommendation_uses_only_passing_models_and_lexical_ties() -> None:
    factory = _ModelFactory({"z-model": "success", "a-model": "success"})
    report = run_live_profile(
        _config("z-model", "a-model"),
        provider_factory=factory,
        clock_ns=lambda: 0,
    )
    assert report["all_models_passed"] is True
    assert report["development_demo_latency_recommendation"] == "a-model"

    failed = _ModelFactory({"bad-model": "wrong_budget", "good-model": "success"})
    failed_report = run_live_profile(
        _config("bad-model", "good-model"),
        provider_factory=failed,
        clock_ns=lambda: 0,
    )
    assert failed_report["all_models_passed"] is False
    assert failed_report["development_demo_latency_recommendation"] == "good-model"


def test_report_is_safe_machine_readable_and_versioned() -> None:
    factory = _factory_for()
    report = run_live_profile(_config(), provider_factory=factory, clock_ns=_step_clock())
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    parsed = json.loads(encoded)
    assert parsed["schema_version"] == "1"
    assert parsed["profile_version"] == PROFILE_VERSION
    assert parsed["disclaimer"] == PROFILE_DISCLAIMER
    assert _FAKE_KEY not in encoded
    assert "Authorization" not in encoded
    assert "Buy exactly" not in encoded


def test_main_authorizes_runner_only_after_validated_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorizations: list[bool] = []

    def fake_runner(
        _config: LiveProfileConfig,
        *,
        authorize_paid_calls: bool = False,
    ) -> dict[str, object]:
        authorizations.append(authorize_paid_calls)
        return {"all_models_passed": True}

    monkeypatch.setattr(live_profile, "run_live_profile", fake_runner)
    monkeypatch.delenv("CLEAR_AI_PROFILE", raising=False)
    assert live_profile.main() == 2
    assert authorizations == []
    capsys.readouterr()

    for name, value in _profile_environment().items():
        monkeypatch.setenv(name, value)
    assert live_profile.main() == 0
    assert authorizations == [True]
    assert json.loads(capsys.readouterr().out)["all_models_passed"] is True


@pytest.mark.parametrize(
    ("behavior", "expected_status", "expected_all_passed"),
    [
        ("success", 0, True),
        ("wrong_budget", 1, False),
        ("gateway_timeout", 1, False),
    ],
)
def test_main_exit_status_reflects_complete_profile_result(
    behavior: str,
    expected_status: int,
    expected_all_passed: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory = _factory_for(behavior)
    monkeypatch.setattr(live_profile, "OpenAICompatibleProvider", factory)
    for name, value in _profile_environment().items():
        monkeypatch.setenv(name, value)

    assert live_profile.main() == expected_status
    report = json.loads(capsys.readouterr().out)
    assert report["all_models_passed"] is expected_all_passed


def test_no_opt_in_cli_prints_sanitized_report_without_provider_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CLEAR_AI_PROFILE", raising=False)

    class _UnexpectedProvider:
        def __init__(self, **_kwargs: object) -> None:
            raise AssertionError("provider must not be constructed")

    monkeypatch.setattr(live_profile, "OpenAICompatibleProvider", _UnexpectedProvider)
    assert live_profile.main() == 2
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["paid_call_count"] == 0
    assert report["profile_version"] == PROFILE_VERSION
    assert _FAKE_KEY not in output
