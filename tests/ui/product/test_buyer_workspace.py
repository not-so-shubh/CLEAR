from __future__ import annotations

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock

import pytest

import ui.product.service as service_module
from clear_market.ai import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderResponseV1,
    AIProviderTask,
)
from clear_market.canonical import canonical_utc_datetime
from clear_market.commerce import canonical_buyer_policy_v2_bytes
from ui.product.ai import BuyerIntentPromptGuardProvider
from ui.product.models import (
    CreateBuyerDraftRequest,
    CreateMerchantRequest,
    SubmitOfferRequest,
)
from ui.product.policy import parse_canonical_buyer_policy_v2
from ui.product.service import ProductErrorCode, ProductService, ProductServiceError

_ENVIRONMENT = {
    "CLEAR_AI_BASE_URL": "https://gateway.example/v1",
    "CLEAR_AI_API_KEY": "server-side-product-secret",
    "CLEAR_AI_PROVIDER_NAME": "external-gateway",
    "CLEAR_AI_MODELS": "buyer-model-v1",
}
_HARD_RULE_ID = "a1000000-0000-4000-8000-000000000001"
_SOFT_RULE_ID = "a1000000-0000-4000-8000-000000000002"


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2032, 1, 1, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _Provider:
    def __init__(
        self,
        output: str,
        *,
        error: AIProviderError | None = None,
        entered: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.entered = entered
        self.release = release
        self.calls: list[AIProviderRequestV1] = []
        self.responses: list[AIProviderResponseV1] = []
        self._lock = Lock()

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        with self._lock:
            self.calls.append(request)
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=10)
        if self.error is not None:
            raise self.error
        response = AIProviderResponseV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            finish_reason=AIProviderFinishReason.COMPLETED,
            output_text=self.output,
        )
        self.responses.append(response)
        return response


def _merchant_request(name: str) -> CreateMerchantRequest:
    return CreateMerchantRequest(
        display_name=f"{name} Compute",
        product_display_name=f"{name} EdgeBox",
        merchant_sku=f"{name.upper()}-EDGE",
        inventory_quantity=5,
        unit_cost_basis_paise=100,
        minimum_margin_paise=0,
        max_quantity_per_offer=5,
    )


def _merchants(service: ProductService) -> list[str]:
    return [
        str(service.create_merchant(_merchant_request(name))["merchant_id"])
        for name in ("Alpha", "Beta", "Gamma")
    ]


def _draft(
    service: ProductService,
    clock: _Clock,
    merchants: list[str],
) -> dict[str, object]:
    return service.create_buyer_draft(
        CreateBuyerDraftRequest(
            buyer_text=(
                "Buy five edge systems for at most INR 100. Require at least 16 GB RAM "
                "and prefer the CLEAR brand. Use at most two suppliers."
            ),
            eligible_merchant_ids=merchants,
            offer_deadline=canonical_utc_datetime(clock.now + timedelta(hours=2)),
        )
    )


def _output(*, rules: bool = True, **changes: object) -> str:
    payload: dict[str, object] = {
        "schema_version": "1",
        "buyer_intent_candidate_version": "buyer-intent-candidate-v1",
        "requested_quantity": 5,
        "minimum_acceptable_quantity": 5,
        "max_winners": 2,
        "max_total_payment_paise": 10_000,
        "hard_constraints": (
            [
                {
                    "schema_version": "1",
                    "buyer_intent_rule_candidate_version": ("buyer-intent-rule-candidate-v1"),
                    "rule_id": _HARD_RULE_ID,
                    "attribute_key": "ram_gb",
                    "operator": "gte",
                    "value_type": "integer",
                    "value": 16,
                    "allowed_provenance": ["VERIFIED", "ATTESTED"],
                }
            ]
            if rules
            else []
        ),
        "soft_preferences": (
            [
                {
                    "schema_version": "1",
                    "buyer_intent_rule_candidate_version": ("buyer-intent-rule-candidate-v1"),
                    "rule_id": _SOFT_RULE_ID,
                    "attribute_key": "brand",
                    "operator": "eq",
                    "value_type": "string",
                    "value": "CLEAR",
                    "allowed_provenance": ["CLAIMED", "ATTESTED"],
                }
            ]
            if rules
            else []
        ),
        **changes,
    }
    return json.dumps(payload)


def _interpreted_service(
    tmp_path: Path,
    *,
    rules: bool = True,
) -> tuple[ProductService, _Clock, list[str], dict[str, object], _Provider]:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)
    draft = _draft(service, clock, merchants)
    provider = _Provider(_output(rules=rules))
    result = service.interpret_buyer_draft(
        str(draft["market_id"]),
        environment=_ENVIRONMENT,
        provider=provider,
    )
    assert result["result"] == "SUCCESS"
    return service, clock, merchants, draft, provider


def test_runtime_merchant_discovery_is_safe_and_persisted(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product.sqlite3")
    ids = _merchants(service)

    result = service.list_merchants()

    assert [merchant["merchant_id"] for merchant in result["merchants"]] == ids
    text = json.dumps(result)
    assert "signing_private" not in text
    assert "unit_cost_basis" not in text
    assert "minimum_margin" not in text
    assert "minimum_allowed_unit_price_paise" not in text
    assert "max_quantity_per_offer" not in text


def test_buyer_draft_generates_ids_and_no_authoritative_market(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)

    draft = _draft(service, clock, merchants)

    assert draft["state"] == "DRAFT"
    assert draft["authority"] == "ADVISORY_ONLY"
    assert draft["market_id"] not in merchants
    assert type(draft["buyer_id"]) is str
    draft_text = json.dumps(draft)
    assert "minimum_allowed_unit_price_paise" not in draft_text
    assert "max_quantity_per_offer" not in draft_text
    with service.store.connection() as connection:
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            **_ENVIRONMENT,
            "CLEAR_AI_API_KEY": "",
        },
        {
            **_ENVIRONMENT,
            "CLEAR_AI_MODELS": "buyer-model-v1,buyer-model-v2",
        },
    ],
)
def test_invalid_ai_configuration_is_unavailable_without_provider_or_market(
    tmp_path: Path,
    environment: dict[str, str],
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    provider = _Provider(_output())

    result = service.interpret_buyer_draft(
        str(draft["market_id"]),
        environment=environment,
        provider=provider,
    )

    assert result["code"] == "LIVE_AI_UNAVAILABLE"
    assert "diagnostic_code" not in result
    assert "candidate_diagnostic" not in result
    assert result["provider_invoked"] is False
    assert provider.calls == []
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0
    assert persisted is not None and persisted.state == "DRAFT"


def test_buyer_draft_rejects_unknown_runtime_merchant(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    known = _merchants(service)[0]

    with pytest.raises(ProductServiceError) as raised:
        _draft(
            service,
            clock,
            [known, "a9000000-0000-4000-8000-000000000001"],
        )

    assert raised.value.code is ProductErrorCode.NOT_FOUND
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM product_buyer_drafts").fetchone()[0] == 0


def test_prompt_guard_preserves_request_and_returns_provider_output_unmodified() -> None:
    provider = _Provider(_output(item_description="provider-added field"))
    guard = BuyerIntentPromptGuardProvider(provider)
    request = AIProviderRequestV1(
        request_id="a0000000-0000-4000-8000-000000000001",
        task=AIProviderTask.BUYER_INTENT,
        provider_name="external-gateway",
        model="buyer-model-v1",
        response_format=AIProviderResponseFormat.JSON_OBJECT,
        instruction_text="Original production instruction.\n",
        input_text="Exact buyer input: 16 GB, INR 100.",
        max_output_bytes=65_536,
    )

    response = guard.complete(request)

    assert len(provider.calls) == 1
    assert response is provider.responses[0]
    assert response.output_text == provider.output
    outgoing = provider.calls[0]
    preserved_fields = (
        "request_id",
        "task",
        "provider_name",
        "model",
        "response_format",
        "input_text",
        "max_output_bytes",
    )
    for field_name in preserved_fields:
        assert getattr(outgoing, field_name) == getattr(request, field_name)
    changed_fields = {
        field_name
        for field_name in AIProviderRequestV1.model_fields
        if getattr(outgoing, field_name) != getattr(request, field_name)
    }
    assert changed_fields == {"instruction_text"}
    assert outgoing.input_text == request.input_text
    assert outgoing.input_text.encode("utf-8") == request.input_text.encode("utf-8")
    assert outgoing.instruction_text.startswith(request.instruction_text)
    suffix = outgoing.instruction_text[len(request.instruction_text) :]
    for field_name in (
        "schema_version",
        "buyer_intent_candidate_version",
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "max_total_payment_paise",
        "hard_constraints",
        "soft_preferences",
        "buyer_intent_rule_candidate_version",
        "rule_id",
        "attribute_key",
        "operator",
        "value_type",
        "value",
        "allowed_provenance",
    ):
        assert field_name in suffix
    assert "exactly these top-level keys and no others" in suffix
    assert "No other rule keys are permitted" in suffix
    assert "description, item_description, item description" in suffix
    assert "or any other top-level key" in suffix
    assert "hard_constraints must be []" in suffix
    assert "soft_preferences must be []" in suffix


def test_valid_provider_uses_production_interpreter_once_and_persists_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    provider = _Provider(_output())
    production_calls = 0
    guard_requests: list[AIProviderRequestV1] = []
    original = service_module.interpret_buyer_intent_v1
    original_guard_complete = BuyerIntentPromptGuardProvider.complete

    def wrapped(**kwargs: object) -> object:
        nonlocal production_calls
        production_calls += 1
        return original(**kwargs)  # type: ignore[arg-type]

    def capture_guard_request(
        guard: BuyerIntentPromptGuardProvider, request: AIProviderRequestV1
    ) -> AIProviderResponseV1:
        guard_requests.append(request)
        return original_guard_complete(guard, request)

    monkeypatch.setattr(service_module, "interpret_buyer_intent_v1", wrapped)
    monkeypatch.setattr(BuyerIntentPromptGuardProvider, "complete", capture_guard_request)
    result = service.interpret_buyer_draft(
        str(draft["market_id"]),
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert production_calls == 1
    assert len(guard_requests) == 1
    assert len(provider.calls) == 1
    production_request = guard_requests[0]
    outgoing_request = provider.calls[0]
    assert production_request.task is AIProviderTask.BUYER_INTENT
    assert outgoing_request.instruction_text.startswith(production_request.instruction_text)
    assert outgoing_request.input_text == production_request.input_text
    assert result["state"] == "INTERPRETED"
    assert result["authority"] == "ADVISORY_ONLY"
    assert result["policy_state"] == "NOT_FROZEN"
    interpretation = result["interpretation"]
    assert type(interpretation) is dict
    assert interpretation["requested_quantity"] == 5
    assert interpretation["max_total_payment_paise"] == 10_000
    assert len(interpretation["hard_constraints"]) == 1
    assert len(interpretation["soft_preferences"]) == 1
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0
    assert persisted is not None and persisted.state == "INTERPRETED"
    assert persisted.canonical_interpreted_policy is not None
    parsed = parse_canonical_buyer_policy_v2(persisted.canonical_interpreted_policy)
    assert len(parsed.market_spec.hard_constraints) == 1
    assert len(parsed.market_spec.soft_preferences) == 1


@pytest.mark.parametrize(
    ("output", "diagnostic_code"),
    [
        ("{", "invalid_json"),
        (_output(winner="merchant-a"), "invalid_candidate"),
        (_output(allocation={"forged": True}), "invalid_candidate"),
        (_output(eligible_merchant_ids=[]), "invalid_candidate"),
        (_output(market_id="a2000000-0000-4000-8000-000000000001"), "invalid_candidate"),
        (_output(payment={"amount": 1}), "invalid_candidate"),
    ],
)
def test_malformed_or_authority_like_ai_output_fails_strict_parse(
    tmp_path: Path,
    output: str,
    diagnostic_code: str,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    provider = _Provider(output)

    result = service.interpret_buyer_draft(
        str(draft["market_id"]), environment=_ENVIRONMENT, provider=provider
    )

    assert result["code"] == "STRICT_BUYER_INTENT_PARSE_FAILURE"
    assert result["diagnostic_code"] == diagnostic_code
    if diagnostic_code == "invalid_candidate":
        assert "candidate_diagnostic" in result
    else:
        assert "candidate_diagnostic" not in result
    assert result["provider_invoked"] is True
    assert "raw" not in json.dumps(result).lower()
    assert "validationerror" not in json.dumps(result).lower()
    assert "json.decoder" not in json.dumps(result).lower()
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0
    assert persisted is not None and persisted.state == "DRAFT"


@pytest.mark.parametrize(
    ("output", "diagnostic_code"),
    [
        (_output(), "duplicate_key"),
        (_output(requested_quantity=0), "invalid_candidate"),
    ],
)
def test_parse_diagnostic_codes_preserve_failure_boundary(
    tmp_path: Path,
    output: str,
    diagnostic_code: str,
) -> None:
    if diagnostic_code == "duplicate_key":
        output = output[:-1] + ',"requested_quantity":5}'
    clock = _Clock()
    service = ProductService(tmp_path / f"{diagnostic_code}.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))

    result = service.interpret_buyer_draft(
        str(draft["market_id"]), environment=_ENVIRONMENT, provider=_Provider(output)
    )

    assert result["code"] == "STRICT_BUYER_INTENT_PARSE_FAILURE"
    assert result["diagnostic_code"] == diagnostic_code
    if diagnostic_code == "invalid_candidate":
        assert "candidate_diagnostic" in result
    else:
        assert "candidate_diagnostic" not in result
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0
    assert persisted is not None and persisted.state == "DRAFT"
    assert persisted.canonical_interpreted_policy is None
    with pytest.raises(ProductServiceError) as raised:
        service.freeze_buyer_draft(str(draft["market_id"]))
    assert raised.value.code is ProductErrorCode.DRAFT_NOT_FREEZABLE


def test_invalid_candidate_diagnostic_is_structural_and_secret_free(tmp_path: Path) -> None:
    canary = "DO-NOT-EXPOSE-RAW-MODEL-CONTENT"
    canary_key = "do_not_expose_raw_model_content"
    nested_canary_key = "do_not_expose_nested_model_content"
    payload = json.loads(_output())
    payload.pop("hard_constraints")
    payload[canary_key] = canary
    payload["requested_quantity"] = canary
    payload["max_winners"] = True
    payload["max_total_payment_paise"] = 12.5
    payload["schema_version"] = canary
    payload["buyer_intent_candidate_version"] = canary
    payload["soft_preferences"] = [
        {
            "schema_version": canary,
            "buyer_intent_rule_candidate_version": canary,
            "rule_id": "not-a-uuid",
            "operator": "not-an-operator",
            "value_type": "not-a-value-type",
            "value": canary,
            "allowed_provenance": canary,
            nested_canary_key: canary,
        }
    ]
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    provider = _Provider(json.dumps(payload))

    result = service.interpret_buyer_draft(
        str(draft["market_id"]), environment=_ENVIRONMENT, provider=provider
    )

    assert result["code"] == "STRICT_BUYER_INTENT_PARSE_FAILURE"
    assert result["diagnostic_code"] == "invalid_candidate"
    diagnostic = result["candidate_diagnostic"]
    assert diagnostic["missing_fields"] == ["hard_constraints"]
    assert diagnostic["extra_field_count"] == 1
    assert diagnostic["field_types"]["requested_quantity"] == "string"
    assert diagnostic["field_types"]["max_winners"] == "boolean"
    assert diagnostic["field_types"]["max_total_payment_paise"] == "number_other"
    assert "hard_constraints" not in diagnostic["field_types"]
    assert diagnostic["schema_version_valid"] is False
    assert diagnostic["candidate_version_valid"] is False
    assert diagnostic["requested_quantity_positive_integer"] is False
    assert diagnostic["soft_preferences"]["invalid_rule_schema_version_count"] == 1
    assert diagnostic["soft_preferences"]["invalid_rule_candidate_version_count"] == 1
    assert diagnostic["soft_preferences"]["invalid_rule_id_format_count"] == 1
    assert diagnostic["soft_preferences"]["invalid_operator_count"] == 1
    assert diagnostic["soft_preferences"]["invalid_value_type_count"] == 1
    assert diagnostic["soft_preferences"]["invalid_allowed_provenance_shape_count"] == 1
    assert diagnostic["soft_preferences"]["extra_rule_field_count"] == 1
    serialized = json.dumps(result)
    assert canary not in serialized
    assert canary_key not in serialized
    assert nested_canary_key not in serialized
    assert "extra_fields" not in serialized
    assert "extra_rule_fields" not in serialized
    assert len(provider.calls) == 1
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0
    assert persisted is not None and persisted.state == "DRAFT"
    assert persisted.canonical_interpreted_policy is None
    with pytest.raises(ProductServiceError) as raised:
        service.freeze_buyer_draft(str(draft["market_id"]))
    assert raised.value.code is ProductErrorCode.DRAFT_NOT_FREEZABLE


def test_item_description_remains_rejected_without_exposing_model_key(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    output = _output(item_description="edge systems")
    provider = _Provider(output)

    result = service.interpret_buyer_draft(
        str(draft["market_id"]), environment=_ENVIRONMENT, provider=provider
    )

    assert len(provider.calls) == 1
    assert provider.responses[0].output_text == output
    assert result["code"] == "STRICT_BUYER_INTENT_PARSE_FAILURE"
    assert result["diagnostic_code"] == "invalid_candidate"
    assert result["candidate_diagnostic"]["extra_field_count"] == 1
    assert "item_description" not in json.dumps(result)
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
        assert service.store.count_markets(connection, str(draft["market_id"])) == 0
    assert persisted is not None and persisted.state == "DRAFT"
    assert persisted.canonical_interpreted_policy is None
    with pytest.raises(ProductServiceError) as raised:
        service.freeze_buyer_draft(str(draft["market_id"]))
    assert raised.value.code is ProductErrorCode.DRAFT_NOT_FREEZABLE


def test_diagnostic_failure_preserves_original_parse_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))

    def fail_diagnostic(_output_text: str) -> dict[str, object]:
        raise RuntimeError("diagnostic failed")

    monkeypatch.setattr(service_module, "fingerprint_invalid_candidate", fail_diagnostic)
    result = service.interpret_buyer_draft(
        str(draft["market_id"]),
        environment=_ENVIRONMENT,
        provider=_Provider(_output(item_description="rejected")),
    )

    assert result["code"] == "STRICT_BUYER_INTENT_PARSE_FAILURE"
    assert result["diagnostic_code"] == "invalid_candidate"
    assert "candidate_diagnostic" not in result


def test_strict_freeze_rejection_remains_retryable(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _merchants(service)[:2]
    draft = _draft(service, clock, merchants)
    provider = _Provider(_output(max_winners=3))

    result = service.interpret_buyer_draft(
        str(draft["market_id"]), environment=_ENVIRONMENT, provider=provider
    )

    assert result["code"] == "STRICT_BUYER_INTENT_REJECTION"
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, str(draft["market_id"]))
    assert persisted is not None and persisted.state == "DRAFT"


@pytest.mark.parametrize(
    ("provider_code", "product_code"),
    [
        (AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED, "PROVIDER_AUTHENTICATION_FAILURE"),
        (AIProviderErrorCode.PROVIDER_RATE_LIMITED, "PROVIDER_RATE_LIMITED"),
        (AIProviderErrorCode.PROVIDER_TIMEOUT, "PROVIDER_TIMEOUT"),
        (AIProviderErrorCode.PROVIDER_UNAVAILABLE, "PROVIDER_UNAVAILABLE"),
        (AIProviderErrorCode.PROVIDER_REQUEST_REJECTED, "PROVIDER_REQUEST_REJECTED"),
        (AIProviderErrorCode.INVALID_RESPONSE, "PROVIDER_RESPONSE_REJECTED"),
    ],
)
def test_provider_failures_have_distinct_safe_codes(
    tmp_path: Path,
    provider_code: AIProviderErrorCode,
    product_code: str,
) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    provider = _Provider(_output(), error=AIProviderError(provider_code))

    result = service.interpret_buyer_draft(
        str(draft["market_id"]), environment=_ENVIRONMENT, provider=provider
    )

    assert result["code"] == product_code
    serialized = json.dumps(result)
    assert _ENVIRONMENT["CLEAR_AI_API_KEY"] not in serialized
    assert _ENVIRONMENT["CLEAR_AI_BASE_URL"] not in serialized


def test_concurrent_interpretation_invokes_provider_at_most_once(tmp_path: Path) -> None:
    clock = _Clock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    draft = _draft(service, clock, _merchants(service))
    market_id = str(draft["market_id"])
    entered = Event()
    release = Event()
    provider = _Provider(_output(), entered=entered, release=release)

    def interpret() -> dict[str, object] | ProductErrorCode:
        try:
            return service.interpret_buyer_draft(
                market_id,
                environment=_ENVIRONMENT,
                provider=provider,
            )
        except ProductServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(interpret)
        assert entered.wait(timeout=10)
        second = executor.submit(interpret)
        second_result = second.result(timeout=10)
        release.set()
        first_result = first.result(timeout=10)

    assert type(first_result) is dict and first_result["result"] == "SUCCESS"
    assert second_result is ProductErrorCode.DRAFT_NOT_INTERPRETABLE
    assert len(provider.calls) == 1
    with service.store.connection() as connection:
        persisted = service.store.get_buyer_draft(connection, market_id)
    assert persisted is not None and persisted.state == "INTERPRETED"


def test_freeze_is_exact_atomic_and_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "product.sqlite3"
    service, clock, merchants, draft, provider = _interpreted_service(tmp_path)
    market_id = str(draft["market_id"])
    with service.store.connection() as connection:
        interpreted = service.store.get_buyer_draft(connection, market_id)
    assert interpreted is not None and interpreted.canonical_interpreted_policy is not None
    reviewed_bytes = interpreted.canonical_interpreted_policy
    calls_before = len(provider.calls)

    frozen = service.freeze_buyer_draft(market_id)

    assert len(provider.calls) == calls_before
    assert frozen["buyer_policy_frozen"] is True
    assert frozen["market_state"] == "OPEN"
    with service.store.connection() as connection:
        market = service.store.get_market(connection, market_id)
        final_draft = service.store.get_buyer_draft(connection, market_id)
    assert market is not None and market.canonical_buyer_policy == reviewed_bytes
    authoritative = ProductService._load_policy(market)
    assert canonical_buyer_policy_v2_bytes(authoritative) == reviewed_bytes
    assert final_draft is not None and final_draft.state == "FROZEN"
    assert authoritative.market_spec.market_id == final_draft.market_id
    assert authoritative.market_spec.buyer_id == final_draft.buyer_id
    assert authoritative.eligible_merchant_ids == final_draft.eligible_merchant_ids
    assert canonical_utc_datetime(authoritative.offer_deadline) == final_draft.offer_deadline
    reopened = ProductService(path, clock=clock).get_market(market_id)
    assert len(reopened["hard_constraints"]) == 1
    assert len(reopened["soft_preferences"]) == 1
    assert reopened["eligible_merchant_ids"] == sorted(merchants)


def test_concurrent_freeze_creates_one_authoritative_market(tmp_path: Path) -> None:
    service, _clock, _merchants_list, draft, _provider = _interpreted_service(tmp_path)
    market_id = str(draft["market_id"])

    def freeze() -> dict[str, object] | ProductErrorCode:
        try:
            return service.freeze_buyer_draft(market_id)
        except ProductServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=10) for future in [executor.submit(freeze) for _ in range(2)]
        ]

    assert len([value for value in outcomes if type(value) is dict]) == 1
    assert [value for value in outcomes if type(value) is ProductErrorCode] == [
        ProductErrorCode.DRAFT_NOT_FREEZABLE
    ]
    with service.store.connection() as connection:
        assert service.store.count_markets(connection, market_id) == 1


def test_offer_is_unavailable_before_freeze_and_uses_frozen_policy_afterward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _clock, merchants, draft, _provider = _interpreted_service(tmp_path, rules=False)
    market_id = str(draft["market_id"])
    offer = SubmitOfferRequest(
        merchant_id=merchants[0],
        proposed_quantity=3,
        proposed_unit_price_paise=500,
    )
    with pytest.raises(ProductServiceError) as before:
        service.submit_offer(market_id, offer)
    assert before.value.code is ProductErrorCode.NOT_FOUND
    service.freeze_buyer_draft(market_id)
    with service.store.connection() as connection:
        market = service.store.get_market(connection, market_id)
    assert market is not None and market.canonical_buyer_policy is not None
    expected = market.canonical_buyer_policy
    loaded: list[bytes] = []
    original = ProductService._load_policy

    def capture(record: object) -> object:
        policy = original(record)  # type: ignore[arg-type]
        loaded.append(canonical_buyer_policy_v2_bytes(policy))
        return policy

    monkeypatch.setattr(ProductService, "_load_policy", staticmethod(capture))

    accepted = service.submit_offer(market_id, offer)

    assert accepted["authenticated"] is True
    assert loaded == [expected]


def test_legacy_null_policy_migrates_and_reconstructs(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    market_id = "a3000000-0000-4000-8000-000000000001"
    buyer_id = "a3000000-0000-4000-8000-000000000002"
    merchants = [
        "a3000000-0000-4000-8000-000000000011",
        "a3000000-0000-4000-8000-000000000012",
    ]
    deadline = "2032-01-01T12:00:00.000000Z"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE product_markets (
            market_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
            requested_quantity INTEGER NOT NULL,
            minimum_acceptable_quantity INTEGER NOT NULL,
            max_winners INTEGER NOT NULL, max_total_payment_paise INTEGER NOT NULL,
            eligible_merchant_ids_json TEXT NOT NULL, offer_deadline TEXT NOT NULL,
            state TEXT NOT NULL, created_at TEXT NOT NULL, closed_at TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO product_markets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            market_id,
            buyer_id,
            5,
            5,
            2,
            10_000,
            json.dumps(merchants),
            deadline,
            "OPEN",
            "2032-01-01T10:00:00.000000Z",
            None,
        ),
    )
    connection.commit()
    connection.close()

    service = ProductService(path, clock=_Clock())
    result = service.get_market(market_id)

    assert result["market_state"] == "OPEN"
    assert result["hard_constraints"] == []
    assert result["soft_preferences"] == []
    with service.store.connection() as migrated:
        columns = {row["name"] for row in migrated.execute("PRAGMA table_info(product_markets)")}
        record = service.store.get_market(migrated, market_id)
    assert "canonical_buyer_policy" in columns
    assert record is not None and record.canonical_buyer_policy is None


def test_malformed_persisted_canonical_policy_fails_closed(tmp_path: Path) -> None:
    service, _clock, _merchants_list, draft, _provider = _interpreted_service(tmp_path)
    market_id = str(draft["market_id"])
    service.freeze_buyer_draft(market_id)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_markets SET canonical_buyer_policy = ? WHERE market_id = ?",
            (b"{}", market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_market(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_buyer_client_has_no_runtime_markup_or_hard_coded_commercial_authority() -> None:
    source = Path("ui/product_app.js").read_text(encoding="utf-8")
    authority_start = source.index("const renderRuntimeCertificateLines")
    authority_end = source.index("const renderClearingSnapshot")
    source_without_authority_renderer = source[:authority_start] + source[authority_end:]

    assert "innerHTML" not in source
    assert (
        re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            source,
            re.IGNORECASE,
        )
        is None
    )
    assert "/api/product-v1/merchants" in source
    assert 'localStorage.setItem("clear-product-market-id"' in source
    assert "/api/product-v1/markets/${encodeURIComponent(marketId)}" in source
    assert "merchant.merchant_id" in source
    assert "merchant.display_name" in source
    assert "merchant.inventory_quantity" in source
    assert "winner_merchant_ids" not in source
    assert "allocated_quantity" not in source_without_authority_renderer
    assert "certificate_digest" not in source_without_authority_renderer
    assert "VERIFIED" not in source_without_authority_renderer
    assert "RUNNING · USER INITIATED" in source
    assert 'data-buyer-field="diagnostic-code"' in Path("ui/index.html").read_text(encoding="utf-8")
    assert "payload.diagnostic_code" in source
    assert "diagnosticCode.textContent" in source
    assert "candidateDiagnostic.replaceChildren" in source
    assert "renderCandidateDiagnostic" in source
    assert "diagnostic.extra_field_count" in source
    assert "shape.extra_rule_field_count" in source
    assert "diagnostic.extra_fields" not in source
    assert "shape.extra_rule_fields" not in source
    assert 'data-buyer-field="candidate-diagnostic"' in Path("ui/index.html").read_text(
        encoding="utf-8"
    )
    assert "textContent" in source
    assert "createElement" in source
    assert "replaceChildren" in source


def test_buyer_and_existing_evidence_views_share_the_working_shell() -> None:
    markup = Path("ui/index.html").read_text(encoding="utf-8")
    client = Path("ui/product_app.js").read_text(encoding="utf-8")

    assert 'data-view-target="buyer"' in markup
    assert 'data-view-target="evidence"' in markup
    assert 'id="buyer-workspace"' in markup
    assert 'id="buyer-draft-form"' in markup
    assert 'id="freeze-buyer-policy"' in markup
    assert '<main id="top" data-app-view="evidence" hidden>' in markup
    assert 'id="run-demo"' in markup
    assert 'id="run-live-evidence"' in markup
    assert 'id="run-merchant-ai"' in markup
    assert 'id="run-explanation-ai"' in markup
    assert '["#buyer", "#buyer-workspace"]' in client
    assert '["#evidence", "#top", "#demo", "#supporting", "#architecture"]' in client
    assert "preserveHash" in client
    assert 'hashMode: "push"' in client
    assert 'window.addEventListener("hashchange", routeFromHash)' in client
    assert 'window.addEventListener("popstate", routeFromHash)' in client


def test_frozen_restore_and_new_draft_have_truthful_control_states() -> None:
    client = Path("ui/product_app.js").read_text(encoding="utf-8")
    set_running_block = client.split("const setRunning = (value, label) =>", 1)[1].split(
        "const canonicalDeadline =", 1
    )[0]
    render_frozen_block = client.split("const renderFrozen = (payload) =>", 1)[1].split(
        "const restoreFrozenMarket = async () =>", 1
    )[0]
    restore_block = client.split("const restoreFrozenMarket = async () =>", 1)[1].split(
        "if (freezeButton instanceof HTMLButtonElement) {", 1
    )[0]
    new_draft_block = client.split('newDraftButton.addEventListener("click", () => {', 1)[1].split(
        "if (deadline instanceof HTMLInputElement) {", 1
    )[0]

    assert "interpretButton.disabled = value || currentMarketId !== null;" in set_running_block
    assert "field.disabled = value || currentMarketId !== null;" in set_running_block
    assert "currentMarketId = String(payload.market_id);" in render_frozen_block
    assert 'setRunning(false, "Interpretation complete");' in render_frozen_block
    assert render_frozen_block.index("currentMarketId = String(payload.market_id);") < (
        render_frozen_block.index('setRunning(false, "Interpretation complete");')
    )
    assert "newDraftButton.hidden = false;" in render_frozen_block
    assert "renderFrozen(response.payload);" in restore_block
    assert 'setRunning(false, "Interpret request");' not in restore_block
    assert 'method: "POST"' not in restore_block
    assert "currentMarketId = null;" in new_draft_block
    assert 'localStorage.removeItem("clear-product-market-id");' in new_draft_block
    assert "form.reset();" in new_draft_block
    assert "input.checked = true;" in new_draft_block
    assert 'setRunning(false, "Interpret request");' in new_draft_block
    assert new_draft_block.index("currentMarketId = null;") < new_draft_block.index(
        'setRunning(false, "Interpret request");'
    )


def test_freeze_failure_reconciles_without_clearing_market_identity() -> None:
    client = Path("ui/product_app.js").read_text(encoding="utf-8")
    freeze_block = client.split("if (freezeButton instanceof HTMLButtonElement) {", 1)[1].split(
        "if (newDraftButton instanceof HTMLButtonElement) {", 1
    )[0]
    reconcile_block = client.split("const reconcileFreezeOutcome = async () =>", 1)[1].split(
        "const renderInterpretation =", 1
    )[0]
    restore_block = client.split("const restoreFrozenMarket = async () =>", 1)[1].split(
        "if (freezeButton instanceof HTMLButtonElement) {", 1
    )[0]

    assert "const reconcileFreezeOutcome = async () =>" in client
    assert "/api/product-v1/markets/${encodeURIComponent(marketId)}" in client
    assert "response.status === 404" in client
    assert "buyer_policy_frozen === true" in client
    assert "FREEZE OUTCOME NOT CONFIRMED" in client
    assert "No browser authority is inferred" in client
    assert "await reconcileFreezeOutcome();" in client
    assert "renderInterpretationFailure(response.payload)" not in freeze_block
    assert "renderInterpretationFailure(productErrorPayload(error))" not in freeze_block
    assert "return { ok: response.ok, status: response.status, payload };" in client
    assert 'window.localStorage.removeItem("clear-product-market-id");' in client
    assert 'method: "POST"' not in reconcile_block
    assert restore_block.index("if (response.status === 404)") < restore_block.index(
        'window.localStorage.removeItem("clear-product-market-id");'
    )
    assert restore_block.count('window.localStorage.removeItem("clear-product-market-id");') == 1
