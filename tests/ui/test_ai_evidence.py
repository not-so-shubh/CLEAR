import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

import clear_market.execution.governor as governor_module
import clear_market.payments.razorpay.orders as orders_module
import clear_market.payments.transfers.razorpay as transfers_module
import ui.ai_evidence as evidence_module
from clear_market.ai import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseV1,
)
from clear_market.demo import _tampered_certificate
from ui.ai_evidence import (
    _certificate_inputs,
    _CertificateInputs,
    _merchant_inputs,
    build_ai_certificate_explanation_evidence,
    build_ai_merchant_proposal_evidence,
)

_ENVIRONMENT = {
    "CLEAR_AI_BASE_URL": "https://gateway.example/v1",
    "CLEAR_AI_API_KEY": "server-side-ai-secret",
    "CLEAR_AI_PROVIDER_NAME": "external-gateway",
    "CLEAR_AI_MODELS": "judge-model-v1",
}


class _Provider:
    def __init__(
        self,
        output: str,
        *,
        error: AIProviderError | None = None,
        before_complete: Callable[[], None] | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.before_complete = before_complete
        self.calls: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        self.calls.append(request)
        if self.before_complete is not None:
            self.before_complete()
        if self.error is not None:
            raise self.error
        return AIProviderResponseV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            finish_reason=AIProviderFinishReason.COMPLETED,
            output_text=self.output,
        )


def _merchant_output(
    *,
    decision: str = "OFFER",
    sku_id: str | None = None,
    quantity: int = 2,
    price: int = 500,
    extra: bool = False,
) -> str:
    selected_sku = sku_id or _merchant_inputs().catalog.skus[0].sku_id
    payload: dict[str, object] = {
        "schema_version": "1",
        "merchant_offer_proposal_version": "merchant-offer-proposal-v1",
        "decision": decision,
        "lines": (
            []
            if decision == "NO_OFFER"
            else [
                {
                    "schema_version": "1",
                    "merchant_offer_proposal_line_version": "merchant-offer-proposal-line-v1",
                    "sku_id": selected_sku,
                    "proposed_quantity": quantity,
                    "proposed_unit_price_paise": price,
                }
            ]
        ),
    }
    if extra:
        payload["unexpected"] = "must be rejected"
    return json.dumps(payload)


def _explanation_output(citation_id: str = "allocation") -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "certificate_explanation_candidate_version": ("certificate-explanation-candidate-v1"),
            "claims": [
                {
                    "schema_version": "1",
                    "certificate_explanation_claim_version": ("certificate-explanation-claim-v1"),
                    "text": "The certificate records a feasible allocation.",
                    "citation_ids": [citation_id],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {**_ENVIRONMENT, "CLEAR_AI_MODELS": ""},
        {**_ENVIRONMENT, "CLEAR_AI_MODELS": "model-a,model-b"},
    ],
)
def test_missing_or_non_single_model_config_is_unavailable_with_zero_calls(
    environment: dict[str, str],
) -> None:
    provider = _Provider(_merchant_output())

    result = build_ai_merchant_proposal_evidence(
        environment=environment,
        provider=provider,
    )

    assert result["result"] == "UNAVAILABLE"
    assert result["code"] == "LIVE_AI_UNAVAILABLE"
    assert result["provider_invoked"] is False
    assert provider.calls == []


def test_valid_offer_uses_one_production_call_and_deterministic_builder() -> None:
    provider = _Provider(_merchant_output())

    result = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result == {
        "presentation_version": "clear-ai-merchant-proposal-evidence-v1",
        "mode": "CURRENT_RUN",
        "provider_protocol": "OPENAI_COMPATIBLE",
        "provider_identity": "EXTERNALLY SUPPLIED OPENAI-COMPATIBLE PROVIDER",
        "authority": "ADVISORY_ONLY",
        "provider_invoked": True,
        "result": "SUCCESS",
        "provider_name": "external-gateway",
        "model": "judge-model-v1",
        "task": "MERCHANT_PROPOSAL",
        "proposal_parse": "ACCEPTED",
        "decision": "OFFER",
        "proposal_line_count": 1,
        "deterministic_merchant_boundary": "ACCEPTED",
        "scope": (
            "AI proposed an advisory candidate; deterministic merchant rules decide whether it "
            "becomes an admissible offer input."
        ),
    }
    serialized = json.dumps(result)
    assert _ENVIRONMENT["CLEAR_AI_API_KEY"] not in serialized
    assert _ENVIRONMENT["CLEAR_AI_BASE_URL"] not in serialized
    assert "Authorization" not in serialized
    assert "merchant_offer_proposal_version" not in serialized


def test_valid_no_offer_is_a_successful_advisory_result() -> None:
    provider = _Provider(_merchant_output(decision="NO_OFFER"))

    result = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result["result"] == "SUCCESS"
    assert result["decision"] == "NO_OFFER"
    assert result["proposal_line_count"] == 0
    assert result["deterministic_merchant_boundary"] == "NO_OFFER"


@pytest.mark.parametrize("output", ["not json", _merchant_output(extra=True)])
def test_malformed_or_additional_merchant_fields_fail_strict_parse(output: str) -> None:
    provider = _Provider(output)

    result = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result["result"] == "FAILED"
    assert result["code"] == "STRICT_PROPOSAL_PARSE_FAILURE"
    assert "decision" not in result


@pytest.mark.parametrize(
    "output",
    [
        _merchant_output(sku_id="d1000000-0001-4000-8000-000000000001"),
        _merchant_output(quantity=4),
        _merchant_output(price=499),
    ],
)
def test_invalid_sku_quantity_or_price_cannot_cross_deterministic_boundary(
    output: str,
) -> None:
    provider = _Provider(output)

    result = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result["result"] == "FAILED"
    assert result["code"] == "DETERMINISTIC_MERCHANT_REJECTION"
    assert "deterministic_merchant_boundary" not in result


@pytest.mark.parametrize(
    ("error_code", "presentation_code"),
    [
        (
            AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
            "PROVIDER_AUTHENTICATION_FAILURE",
        ),
        (AIProviderErrorCode.PROVIDER_TIMEOUT, "PROVIDER_TIMEOUT"),
        (AIProviderErrorCode.PROVIDER_RATE_LIMITED, "PROVIDER_RATE_LIMITED"),
        (AIProviderErrorCode.PROVIDER_UNAVAILABLE, "PROVIDER_UNAVAILABLE"),
        (AIProviderErrorCode.INVALID_RESPONSE, "INVALID_PROVIDER_RESPONSE"),
    ],
)
def test_provider_failures_are_distinct_safe_states(
    error_code: AIProviderErrorCode,
    presentation_code: str,
) -> None:
    provider = _Provider(
        "private raw response",
        error=AIProviderError(error_code),
    )

    result = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result["result"] == "FAILED"
    assert result["code"] == presentation_code
    serialized = json.dumps(result)
    assert "private raw response" not in serialized
    assert _ENVIRONMENT["CLEAR_AI_API_KEY"] not in serialized
    assert _ENVIRONMENT["CLEAR_AI_BASE_URL"] not in serialized


def test_unexpected_provider_failure_is_safe_and_preserves_one_call_observation() -> None:
    class _UnexpectedProvider:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, _request: AIProviderRequestV1) -> AIProviderResponseV1:
            self.calls += 1
            raise RuntimeError("private provider failure")

    provider = _UnexpectedProvider()

    result = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert provider.calls == 1
    assert result["result"] == "FAILED"
    assert result["code"] == "LIVE_AI_INTERNAL_FAILURE"
    assert result["provider_invoked"] is True
    assert "private provider failure" not in json.dumps(result)


def test_certificate_is_independently_verified_before_provider_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _certificate_inputs()
    events: list[str] = []
    verifier = evidence_module.verify_allocation_certificate_v2

    def observed_verifier(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        result = verifier(*args, **kwargs)
        events.append("verified")
        return result

    provider = _Provider(
        _explanation_output(),
        before_complete=lambda: events.append("provider"),
    )
    monkeypatch.setattr(evidence_module, "verify_allocation_certificate_v2", observed_verifier)

    result = build_ai_certificate_explanation_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
        certificate_inputs=inputs,
    )

    assert result["result"] == "SUCCESS"
    assert events == ["verified", "provider"]
    assert len(provider.calls) == 1


def test_unverified_certificate_makes_zero_ai_calls() -> None:
    inputs = _certificate_inputs()
    tampered = _tampered_certificate(inputs.certificate)
    provider = _Provider(_explanation_output())

    result = build_ai_certificate_explanation_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
        certificate_inputs=_CertificateInputs(
            certificate=tampered,
            trusted_signing_identities=inputs.trusted_signing_identities,
        ),
    )

    assert result["result"] == "FAILED"
    assert result["code"] == "CERTIFICATE_NOT_VERIFIED"
    assert result["provider_invoked"] is False
    assert provider.calls == []


def test_valid_explanation_returns_only_allowlisted_advisory_claim_projection() -> None:
    provider = _Provider(_explanation_output())

    result = build_ai_certificate_explanation_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result["result"] == "SUCCESS"
    assert result["authority"] == "ADVISORY_ONLY"
    assert result["certificate_verified_before_ai"] is True
    assert result["citation_references_validated"] is True
    assert result["claims_count"] == 1
    assert result["displayed_claims_count"] == 1
    assert result["claims"] == [
        {
            "text": "The certificate records a feasible allocation.",
            "citation_ids": ["allocation"],
        }
    ]
    assert set(result) == {
        "presentation_version",
        "mode",
        "provider_protocol",
        "provider_identity",
        "authority",
        "provider_invoked",
        "result",
        "provider_name",
        "model",
        "task",
        "certificate_verified_before_ai",
        "certificate_digest_sha256",
        "claims_count",
        "displayed_claims_count",
        "citation_references_validated",
        "claims",
        "scope",
    }
    assert set(result["claims"][0]) == {"text", "citation_ids"}
    serialized = json.dumps(result)
    assert _ENVIRONMENT["CLEAR_AI_API_KEY"] not in serialized
    assert _ENVIRONMENT["CLEAR_AI_BASE_URL"] not in serialized
    assert "signature" not in serialized.lower()
    assert "public_key" not in serialized
    assert "certificate_explanation_candidate_version" not in serialized


def test_allocation_line_claims_are_omitted_from_the_presentation_projection() -> None:
    provider = _Provider(
        json.dumps(
            {
                "schema_version": "1",
                "certificate_explanation_candidate_version": (
                    "certificate-explanation-candidate-v1"
                ),
                "claims": [
                    {
                        "schema_version": "1",
                        "certificate_explanation_claim_version": (
                            "certificate-explanation-claim-v1"
                        ),
                        "text": "The allocation fulfilled 5 units for 2700 paise.",
                        "citation_ids": ["allocation"],
                    },
                    {
                        "schema_version": "1",
                        "certificate_explanation_claim_version": (
                            "certificate-explanation-claim-v1"
                        ),
                        "text": "The first merchant received 3 awarded units.",
                        "citation_ids": ["allocation.line.0"],
                    },
                    {
                        "schema_version": "1",
                        "certificate_explanation_claim_version": (
                            "certificate-explanation-claim-v1"
                        ),
                        "text": "The second merchant received 2 awarded units.",
                        "citation_ids": ["allocation.line.1", "policy"],
                    },
                    {
                        "schema_version": "1",
                        "certificate_explanation_claim_version": (
                            "certificate-explanation-claim-v1"
                        ),
                        "text": "The buyer requested 5 units with at most 2 winners.",
                        "citation_ids": ["policy"],
                    },
                ],
            }
        )
    )

    result = build_ai_certificate_explanation_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert result["result"] == "SUCCESS"
    assert result["claims_count"] == 4
    assert result["displayed_claims_count"] == 2
    assert result["claims"] == [
        {
            "text": "The allocation fulfilled 5 units for 2700 paise.",
            "citation_ids": ["allocation"],
        },
        {
            "text": "The buyer requested 5 units with at most 2 winners.",
            "citation_ids": ["policy"],
        },
    ]
    assert all(
        not citation_id.startswith("allocation.line.")
        for claim in result["claims"]
        for citation_id in claim["citation_ids"]
    )
    serialized = json.dumps(result)
    assert "3 awarded units" not in serialized
    assert "2 awarded units" not in serialized
    assert "allocation.line." not in serialized


@pytest.mark.parametrize(
    ("output", "expected_code"),
    [
        ("not json", "STRICT_EXPLANATION_PARSE_FAILURE"),
        (_explanation_output("unknown.citation"), "EXPLANATION_CITATION_REJECTION"),
    ],
)
def test_invalid_explanation_or_unknown_citation_fails_closed(
    output: str,
    expected_code: str,
) -> None:
    provider = _Provider(output)

    result = build_ai_certificate_explanation_evidence(
        environment=_ENVIRONMENT,
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert result["result"] == "FAILED"
    assert result["code"] == expected_code
    assert result["authority"] == "ADVISORY_ONLY"
    assert "claims" not in result


def test_ai_evidence_paths_have_zero_financial_or_payment_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("AI evidence reached a financial or payment boundary")

    monkeypatch.setattr(governor_module, "authorize_execution_v1", forbidden)
    monkeypatch.setattr(orders_module, "create_razorpay_test_order_v1", forbidden)
    monkeypatch.setattr(
        transfers_module, "create_or_reconcile_razorpay_test_transfers_v1", forbidden
    )

    merchant = build_ai_merchant_proposal_evidence(
        environment=_ENVIRONMENT,
        provider=_Provider(_merchant_output()),
    )
    explanation = build_ai_certificate_explanation_evidence(
        environment=_ENVIRONMENT,
        provider=_Provider(_explanation_output()),
    )

    assert merchant["result"] == "SUCCESS"
    assert explanation["result"] == "SUCCESS"


def test_client_actions_are_explicit_shared_guarded_and_safely_render_claims() -> None:
    source = Path("ui/app.js").read_text(encoding="utf-8")
    ai_function = source.split("async function runAIEvidence(taskId)", maxsplit=1)[1].split(
        '$("#run-demo")', maxsplit=1
    )[0]
    demo_function = source.split("async function runDemo()", maxsplit=1)[1].split(
        "const LiveState", maxsplit=1
    )[0]
    live_function = source.split("async function runLiveEvidence()", maxsplit=1)[1].split(
        "const AIState", maxsplit=1
    )[0]
    tamper_handler = source.split('$("#reveal-tamper").addEventListener("click",', maxsplit=1)[
        1
    ].split('$("#run-live-evidence")', maxsplit=1)[0]

    assert source.count('endpoint: "/api/ai-merchant-proposal-evidence"') == 1
    assert source.count('endpoint: "/api/ai-certificate-explanation-evidence"') == 1
    assert "fetch(task.endpoint" in ai_function
    assert 'body: "{}"' in ai_function
    assert "if (activeAITask !== null) return;" in ai_function
    assert "clearAIResult(task);" in ai_function
    assert ai_function.index("clearAIResult(task);") < ai_function.index("fetch(task.endpoint")
    assert "button.disabled = activeAITask !== null;" in source
    assert "fetch(" not in tamper_handler
    assert "/api/ai-" not in demo_function
    assert "/api/ai-" not in live_function
    assert "text.textContent = claim.text;" in source
    assert "document.createTextNode" in source
    assert "innerHTML" not in source
    assert "allocated_quantity" not in source
    assert 'setAIField(task, "claims-count", data.claims_count);' in source
    assert 'setAIField(task, "displayed-claims-count", data.displayed_claims_count);' in source
    assert 'runAIEvidence("merchant")' in source
    assert 'runAIEvidence("explanation")' in source


def test_ui_preserves_exact_evidence_taxonomy() -> None:
    source = Path("ui/index.html").read_text(encoding="utf-8")
    canonical = {
        "REAL LOCAL PRODUCTION LOGIC",
        "DETERMINISTIC FIXTURE",
        "FAKE/CONTROLLED EXTERNAL TRANSPORT",
        "HISTORICAL LIVE EVIDENCE ONLY",
        "NOT DEMONSTRATED",
    }
    labels = {
        value.strip()
        for value in re.findall(r'<span class="evidence-label"[^>]*>([^<]+)</span>', source)
    }

    assert labels - {"AWAITING RUN"} == canonical - {"NOT DEMONSTRATED"}
    assert labels <= canonical | {"AWAITING RUN"}
    assert (
        '<span>Merchant proposal AI</span><span class="evidence-label">'
        "HISTORICAL LIVE EVIDENCE ONLY</span>"
    ) in source
    assert (
        '<span>Certificate explanation AI</span><span class="evidence-label">'
        "HISTORICAL LIVE EVIDENCE ONLY</span>"
    ) in source
    assert "CLAIMS VALIDATED" in source
    assert "CLAIMS DISPLAYED" in source
    assert "CURRENT RUN · EXTERNALLY SUPPLIED OPENAI-COMPATIBLE PROVIDER" in source
    assert 'class="evidence-label">CURRENT RUN' not in source


def test_reviewed_historical_ai_wording_is_bounded_and_not_official_openai() -> None:
    expected_merchant = (
        "CLEAR's merchant-proposal task was exercised through an externally supplied "
        "OpenAI-compatible provider. The reviewed run returned a schema-valid"
    )
    expected_explanation = (
        "CLEAR's certificate-explanation task was exercised through an externally supplied "
        "OpenAI-compatible provider after independent certificate verification."
    )
    sources = [
        Path(path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/ARCHITECTURE.md", "ui/index.html")
    ]

    for source in sources:
        assert expected_merchant in source.replace("\n", " ")
        assert expected_explanation in source.replace("\n", " ")
        assert "through an official OpenAI" not in source
        assert "official OpenAI provider" not in source
        assert "official OpenAI API" not in source
