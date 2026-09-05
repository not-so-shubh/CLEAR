"""Opt-in presentation boundaries for current-run advisory AI evidence."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from clear_market.ai import (
    AIProvider,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderResponseV1,
    AIProviderTask,
    CertificateExplanationError,
    CertificateExplanationErrorCode,
    CertificateExplanationParseError,
    MerchantAIContextError,
    MerchantOfferProposalFreezeError,
    MerchantOfferProposalParseError,
    explain_verified_allocation_certificate_v1,
    propose_merchant_offer_candidate_v1,
)
from clear_market.ai.live_profile import PROFILE_TIMEOUT_SECONDS
from clear_market.ai.openai_compatible import OpenAICompatibleProvider
from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import (
    BuyerPolicyV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
    MerchantEconomicPolicyV2,
    MerchantOfferBuildError,
    MerchantSigningIdentityV2,
    build_merchant_offer_v2,
)
from clear_market.demo import _buyer_policy, _certificate_fixture, _identity, _merchant_source
from clear_market.verification.v2 import verify_allocation_certificate_v2

_MERCHANT_PRESENTATION_VERSION = "clear-ai-merchant-proposal-evidence-v1"
_EXPLANATION_PRESENTATION_VERSION = "clear-ai-certificate-explanation-evidence-v1"
_MODE = "CURRENT_RUN"
_PROVIDER_PROTOCOL = "OPENAI_COMPATIBLE"
_PROVIDER_IDENTITY = "EXTERNALLY SUPPLIED OPENAI-COMPATIBLE PROVIDER"
_AUTHORITY = "ADVISORY_ONLY"
_EXPLANATION_QUESTION = (
    "Explain what this certificate establishes about the allocation and what it does not establish."
)
_MERCHANT_OFFER_ID = "c1000000-0001-4000-8000-000000000001"


class _AIConfigurationError(ValueError):
    """Safe configuration failure without credential details."""


@dataclass(frozen=True, slots=True, repr=False)
class _AIConfig:
    base_url: str
    api_key: str = field(repr=False)
    provider_name: str
    model: str


@dataclass(frozen=True, slots=True)
class _MerchantInputs:
    buyer_policy: BuyerPolicyV2
    catalog: MerchantCatalogV2
    inventory: InventorySnapshotV2
    economic_policy: MerchantEconomicPolicyV2


@dataclass(frozen=True, slots=True)
class _CertificateInputs:
    certificate: AllocationCertificateV2
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...]


class _OneCallProvider:
    """Permit no more than one delegated provider invocation for one explicit action."""

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self._delegated_calls = 0

    @property
    def delegated_calls(self) -> int:
        return self._delegated_calls

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        if self._delegated_calls != 0:
            raise AIProviderError(AIProviderErrorCode.INVALID_REQUEST)
        self._delegated_calls = 1
        return self._provider.complete(request)


def _config_and_provider(
    environment: Mapping[str, str],
    provider: AIProvider | None,
) -> tuple[_AIConfig, AIProvider]:
    names = (
        "CLEAR_AI_BASE_URL",
        "CLEAR_AI_API_KEY",
        "CLEAR_AI_PROVIDER_NAME",
        "CLEAR_AI_MODELS",
    )
    if any(
        type(environment.get(name)) is not str or environment.get(name, "").strip() == ""
        for name in names
    ):
        raise _AIConfigurationError

    models = tuple(environment["CLEAR_AI_MODELS"].split(","))
    if len(models) != 1 or models[0] == "" or models[0].strip() != models[0]:
        raise _AIConfigurationError

    config = _AIConfig(
        base_url=environment["CLEAR_AI_BASE_URL"],
        api_key=environment["CLEAR_AI_API_KEY"],
        provider_name=environment["CLEAR_AI_PROVIDER_NAME"],
        model=models[0],
    )
    try:
        configured_provider = OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout_seconds=PROFILE_TIMEOUT_SECONDS,
        )
        AIProviderRequestV1(
            request_id=str(uuid4()),
            task=AIProviderTask.MERCHANT_OFFER,
            provider_name=config.provider_name,
            model=config.model,
            response_format=AIProviderResponseFormat.JSON_OBJECT,
            instruction_text="Validate the configured provider and model identifiers.",
            input_text="",
            max_output_bytes=1,
        )
    except (ValueError, ValidationError):
        raise _AIConfigurationError from None
    return config, configured_provider if provider is None else provider


def _merchant_inputs() -> _MerchantInputs:
    buyer_policy = _buyer_policy()
    catalog, inventory, economic_policy, _candidate = _merchant_source(1)
    return _MerchantInputs(
        buyer_policy=buyer_policy,
        catalog=catalog,
        inventory=inventory,
        economic_policy=economic_policy,
    )


def _certificate_inputs() -> _CertificateInputs:
    _policy, _signed_offers, certificate = _certificate_fixture()
    return _CertificateInputs(
        certificate=certificate,
        trusted_signing_identities=(_identity(1), _identity(2)),
    )


def _base_presentation(version: str, *, provider_invoked: bool) -> dict[str, Any]:
    return {
        "presentation_version": version,
        "mode": _MODE,
        "provider_protocol": _PROVIDER_PROTOCOL,
        "provider_identity": _PROVIDER_IDENTITY,
        "authority": _AUTHORITY,
        "provider_invoked": provider_invoked,
    }


def _failure(
    version: str,
    *,
    result: str,
    code: str,
    message: str,
    provider_invoked: bool,
) -> dict[str, Any]:
    return {
        **_base_presentation(version, provider_invoked=provider_invoked),
        "result": result,
        "code": code,
        "message": message,
    }


def merchant_unavailable_presentation(code: str, message: str) -> dict[str, Any]:
    """Build a safe endpoint-level merchant unavailable response."""

    return _failure(
        _MERCHANT_PRESENTATION_VERSION,
        result="UNAVAILABLE",
        code=code,
        message=message,
        provider_invoked=False,
    )


def explanation_unavailable_presentation(code: str, message: str) -> dict[str, Any]:
    """Build a safe endpoint-level explanation unavailable response."""

    return _failure(
        _EXPLANATION_PRESENTATION_VERSION,
        result="UNAVAILABLE",
        code=code,
        message=message,
        provider_invoked=False,
    )


def _provider_failure(
    version: str,
    error: AIProviderError,
    *,
    provider_invoked: bool,
) -> dict[str, Any]:
    details = {
        AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED: (
            "PROVIDER_AUTHENTICATION_FAILURE",
            "The externally supplied provider rejected the server-side credentials.",
        ),
        AIProviderErrorCode.PROVIDER_RATE_LIMITED: (
            "PROVIDER_RATE_LIMITED",
            "The externally supplied provider rate limited this request.",
        ),
        AIProviderErrorCode.PROVIDER_TIMEOUT: (
            "PROVIDER_TIMEOUT",
            "The bounded provider request timed out.",
        ),
        AIProviderErrorCode.PROVIDER_UNAVAILABLE: (
            "PROVIDER_UNAVAILABLE",
            "The externally supplied provider was unavailable over the network.",
        ),
        AIProviderErrorCode.INVALID_RESPONSE: (
            "INVALID_PROVIDER_RESPONSE",
            "The provider response did not pass the production response boundary.",
        ),
        AIProviderErrorCode.OUTPUT_TOO_LARGE: (
            "INVALID_PROVIDER_RESPONSE",
            "The provider response did not pass the production response boundary.",
        ),
        AIProviderErrorCode.PROVIDER_REQUEST_REJECTED: (
            "PROVIDER_REQUEST_REJECTED",
            "The externally supplied provider rejected this request.",
        ),
        AIProviderErrorCode.OUTPUT_INCOMPLETE: (
            "PROVIDER_RESPONSE_REJECTED",
            "The provider did not return a complete response.",
        ),
        AIProviderErrorCode.OUTPUT_REFUSED: (
            "PROVIDER_RESPONSE_REJECTED",
            "The provider did not return an acceptable response.",
        ),
        AIProviderErrorCode.INVALID_REQUEST: (
            "INVALID_PROVIDER_RESPONSE",
            "The provider boundary rejected this request or response.",
        ),
    }
    code, message = details[error.code]
    return _failure(
        version,
        result="FAILED",
        code=code,
        message=message,
        provider_invoked=provider_invoked,
    )


def build_ai_merchant_proposal_evidence(
    *,
    environment: Mapping[str, str] | None = None,
    provider: AIProvider | None = None,
    merchant_inputs: _MerchantInputs | None = None,
) -> dict[str, Any]:
    """Run one production merchant-proposal call and deterministic build boundary."""

    try:
        config, selected_provider = _config_and_provider(
            os.environ if environment is None else environment,
            provider,
        )
    except _AIConfigurationError:
        return merchant_unavailable_presentation(
            "LIVE_AI_UNAVAILABLE",
            "Exactly one valid server-side AI model and provider configuration are required.",
        )

    inputs = _merchant_inputs() if merchant_inputs is None else merchant_inputs
    bounded_provider = _OneCallProvider(selected_provider)
    try:
        candidate = propose_merchant_offer_candidate_v1(
            provider=bounded_provider,
            request_id=str(uuid4()),
            provider_name=config.provider_name,
            model=config.model,
            buyer_policy=inputs.buyer_policy,
            catalog=inputs.catalog,
            inventory=inputs.inventory,
            economic_policy=inputs.economic_policy,
        )
    except AIProviderError as error:
        return _provider_failure(
            _MERCHANT_PRESENTATION_VERSION,
            error,
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except MerchantOfferProposalParseError:
        return _failure(
            _MERCHANT_PRESENTATION_VERSION,
            result="FAILED",
            code="STRICT_PROPOSAL_PARSE_FAILURE",
            message="The provider output did not pass strict MerchantOfferProposalV1 parsing.",
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except MerchantOfferProposalFreezeError:
        return _failure(
            _MERCHANT_PRESENTATION_VERSION,
            result="FAILED",
            code="STRICT_PROPOSAL_REJECTION",
            message="The parsed proposal did not freeze into valid advisory merchant semantics.",
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except MerchantAIContextError:
        return _failure(
            _MERCHANT_PRESENTATION_VERSION,
            result="FAILED",
            code="MERCHANT_CONTEXT_REJECTION",
            message="The server-owned merchant context did not pass the production boundary.",
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except Exception:
        return _failure(
            _MERCHANT_PRESENTATION_VERSION,
            result="FAILED",
            code="LIVE_AI_INTERNAL_FAILURE",
            message="The merchant proposal evidence path failed closed.",
            provider_invoked=bounded_provider.delegated_calls == 1,
        )

    if candidate is None:
        decision = "NO_OFFER"
        line_count = 0
        deterministic_boundary = "NO_OFFER"
    else:
        decision = "OFFER"
        line_count = len(candidate.lines)
        try:
            build_merchant_offer_v2(
                offer_id=_MERCHANT_OFFER_ID,
                buyer_policy=inputs.buyer_policy,
                catalog=inputs.catalog,
                inventory=inputs.inventory,
                economic_policy=inputs.economic_policy,
                candidate=candidate,
            )
        except MerchantOfferBuildError:
            return _failure(
                _MERCHANT_PRESENTATION_VERSION,
                result="FAILED",
                code="DETERMINISTIC_MERCHANT_REJECTION",
                message="Deterministic merchant rules rejected the advisory candidate.",
                provider_invoked=True,
            )
        except Exception:
            return _failure(
                _MERCHANT_PRESENTATION_VERSION,
                result="FAILED",
                code="LIVE_AI_INTERNAL_FAILURE",
                message="The deterministic merchant boundary failed closed.",
                provider_invoked=True,
            )
        deterministic_boundary = "ACCEPTED"

    return {
        **_base_presentation(_MERCHANT_PRESENTATION_VERSION, provider_invoked=True),
        "result": "SUCCESS",
        "provider_name": config.provider_name,
        "model": config.model,
        "task": "MERCHANT_PROPOSAL",
        "proposal_parse": "ACCEPTED",
        "decision": decision,
        "proposal_line_count": line_count,
        "deterministic_merchant_boundary": deterministic_boundary,
        "scope": (
            "AI proposed an advisory candidate; deterministic merchant rules decide whether it "
            "becomes an admissible offer input."
        ),
    }


def build_ai_certificate_explanation_evidence(
    *,
    environment: Mapping[str, str] | None = None,
    provider: AIProvider | None = None,
    certificate_inputs: _CertificateInputs | None = None,
) -> dict[str, Any]:
    """Explain one independently verified fixture certificate with one provider call."""

    try:
        config, selected_provider = _config_and_provider(
            os.environ if environment is None else environment,
            provider,
        )
    except _AIConfigurationError:
        return explanation_unavailable_presentation(
            "LIVE_AI_UNAVAILABLE",
            "Exactly one valid server-side AI model and provider configuration are required.",
        )

    inputs = _certificate_inputs() if certificate_inputs is None else certificate_inputs
    verification = verify_allocation_certificate_v2(
        inputs.certificate,
        trusted_signing_identities=inputs.trusted_signing_identities,
    )
    if not verification.verified:
        return _failure(
            _EXPLANATION_PRESENTATION_VERSION,
            result="FAILED",
            code="CERTIFICATE_NOT_VERIFIED",
            message="AllocationCertificateV2 did not pass independent replay verification.",
            provider_invoked=False,
        )

    bounded_provider = _OneCallProvider(selected_provider)
    try:
        explanation = explain_verified_allocation_certificate_v1(
            provider=bounded_provider,
            request_id=str(uuid4()),
            provider_name=config.provider_name,
            model=config.model,
            certificate=inputs.certificate,
            trusted_signing_identities=inputs.trusted_signing_identities,
            question=_EXPLANATION_QUESTION,
        )
    except AIProviderError as error:
        return _provider_failure(
            _EXPLANATION_PRESENTATION_VERSION,
            error,
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except CertificateExplanationParseError:
        return _failure(
            _EXPLANATION_PRESENTATION_VERSION,
            result="FAILED",
            code="STRICT_EXPLANATION_PARSE_FAILURE",
            message="The provider output did not pass strict explanation parsing.",
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except CertificateExplanationError as error:
        if error.code is CertificateExplanationErrorCode.CERTIFICATE_NOT_VERIFIED:
            code = "CERTIFICATE_NOT_VERIFIED"
            message = "AllocationCertificateV2 did not pass independent replay verification."
        elif error.code is CertificateExplanationErrorCode.UNKNOWN_CITATION:
            code = "EXPLANATION_CITATION_REJECTION"
            message = "The explanation contained a citation outside the verified context."
        else:
            code = "STRICT_EXPLANATION_REJECTION"
            message = "The explanation did not pass the production acceptance boundary."
        return _failure(
            _EXPLANATION_PRESENTATION_VERSION,
            result="FAILED",
            code=code,
            message=message,
            provider_invoked=bounded_provider.delegated_calls == 1,
        )
    except Exception:
        return _failure(
            _EXPLANATION_PRESENTATION_VERSION,
            result="FAILED",
            code="LIVE_AI_INTERNAL_FAILURE",
            message="The certificate explanation evidence path failed closed.",
            provider_invoked=bounded_provider.delegated_calls == 1,
        )

    claims_count = len(explanation.claims)
    displayed_claims = [
        {"text": claim.text, "citation_ids": list(claim.citation_ids)}
        for claim in explanation.claims
        if not any(citation_id.startswith("allocation.line.") for citation_id in claim.citation_ids)
    ]
    return {
        **_base_presentation(_EXPLANATION_PRESENTATION_VERSION, provider_invoked=True),
        "result": "SUCCESS",
        "provider_name": config.provider_name,
        "model": config.model,
        "task": "CERTIFICATE_EXPLANATION",
        "certificate_verified_before_ai": True,
        "certificate_digest_sha256": explanation.certificate_digest_sha256,
        "claims_count": claims_count,
        "displayed_claims_count": len(displayed_claims),
        "citation_references_validated": True,
        "claims": displayed_claims,
        "scope": (
            "The model explains already-verified evidence; it does not verify the certificate "
            "and cannot alter allocation or authorize money."
        ),
    }
