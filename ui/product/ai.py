"""Credential-safe product adapter for one-call buyer-intent interpretation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from clear_market.ai import (
    BUYER_INTENT_CANDIDATE_V1_VERSION,
    BUYER_INTENT_RULE_CANDIDATE_V1_VERSION,
    AIProvider,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderResponseV1,
    AIProviderTask,
)
from clear_market.ai.live_profile import PROFILE_TIMEOUT_SECONDS
from clear_market.ai.openai_compatible import OpenAICompatibleProvider
from clear_market.commerce import AttributeValueType, ComparisonOperator
from clear_market.domain import CanonicalUUID4

PROVIDER_PROTOCOL = "OPENAI_COMPATIBLE"
PROVIDER_IDENTITY = "EXTERNALLY SUPPLIED OPENAI-COMPATIBLE PROVIDER"
_BUYER_INTENT_PRODUCT_COMPLIANCE_SUFFIX = """\
Product buyer-intent response schema compliance:
Return exactly one JSON object containing exactly these top-level keys and no others:
schema_version
buyer_intent_candidate_version
requested_quantity
minimum_acceptable_quantity
max_winners
max_total_payment_paise
hard_constraints
soft_preferences
Do not include description, item_description, item description, summary, explanation,
reasoning, metadata, merchant data, catalog data, SKU data, winner fields, allocation fields,
payment fields, trusted market context, or any other top-level key.
Each hard_constraints or soft_preferences item may contain exactly these keys:
schema_version
buyer_intent_rule_candidate_version
rule_id
attribute_key
operator
value_type
value
allowed_provenance
No other rule keys are permitted.
When there are no hard constraints, hard_constraints must be [].
When there are no soft preferences, soft_preferences must be [].
"""
_CANDIDATE_FIELDS = frozenset(
    {
        "schema_version",
        "buyer_intent_candidate_version",
        "requested_quantity",
        "minimum_acceptable_quantity",
        "max_winners",
        "max_total_payment_paise",
        "hard_constraints",
        "soft_preferences",
    }
)
_RULE_FIELDS = frozenset(
    {
        "schema_version",
        "buyer_intent_rule_candidate_version",
        "rule_id",
        "attribute_key",
        "operator",
        "value_type",
        "value",
        "allowed_provenance",
    }
)
_CANONICAL_SCHEMA_VERSION = "1"
_UUID_ADAPTER = TypeAdapter(CanonicalUUID4)
_OPERATOR_VALUES = frozenset(operator.value for operator in ComparisonOperator)
_VALUE_TYPE_VALUES = frozenset(value_type.value for value_type in AttributeValueType)


class ProductAIConfigurationError(ValueError):
    """AI configuration is absent or malformed without exposing its contents."""


@dataclass(frozen=True, slots=True, repr=False)
class ProductAIConfig:
    base_url: str
    api_key: str = field(repr=False)
    provider_name: str
    model: str

    def __repr__(self) -> str:
        return f"ProductAIConfig(provider_name={self.provider_name!r}, model={self.model!r})"


class BuyerIntentPromptGuardProvider:
    """Append product schema guidance without changing production request data."""

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        guarded_request = AIProviderRequestV1(
            request_id=request.request_id,
            task=request.task,
            provider_name=request.provider_name,
            model=request.model,
            response_format=request.response_format,
            instruction_text=(
                request.instruction_text + "\n" + _BUYER_INTENT_PRODUCT_COMPLIANCE_SUFFIX
            ),
            input_text=request.input_text,
            max_output_bytes=request.max_output_bytes,
        )
        return self._provider.complete(guarded_request)


class OneCallProvider:
    """Permit one delegated provider call for one explicit interpretation action."""

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self._delegated_calls = 0
        self._response: AIProviderResponseV1 | None = None

    @property
    def delegated_calls(self) -> int:
        return self._delegated_calls

    @property
    def captured_response(self) -> AIProviderResponseV1 | None:
        return self._response

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        if self._delegated_calls != 0:
            raise AIProviderError(AIProviderErrorCode.INVALID_REQUEST)
        self._delegated_calls = 1
        response = self._provider.complete(request)
        self._response = response
        return response


def _json_type_label(value: object) -> str:
    if type(value) is str:
        return "string"
    if type(value) is int:
        return "integer"
    if type(value) is bool:
        return "boolean"
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    if value is None:
        return "null"
    return "number_other"


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _nonnegative_integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _valid_uuid(value: object) -> bool:
    try:
        _UUID_ADAPTER.validate_python(value)
    except (TypeError, ValueError, ValidationError):
        return False
    return True


def _rule_fingerprint(value: object) -> dict[str, object]:
    items = value if type(value) is list else []
    object_items = [item for item in items if type(item) is dict]
    missing_fields: set[str] = set()
    extra_rule_field_count = 0
    invalid_schema_version_count = 0
    invalid_candidate_version_count = 0
    invalid_rule_id_format_count = 0
    invalid_operator_count = 0
    invalid_value_type_count = 0
    invalid_allowed_provenance_shape_count = 0
    for item in object_items:
        missing_fields.update(_RULE_FIELDS - set(item))
        extra_rule_field_count += len(set(item) - _RULE_FIELDS)
        if item.get("schema_version") != _CANONICAL_SCHEMA_VERSION:
            invalid_schema_version_count += 1
        if item.get("buyer_intent_rule_candidate_version") != (
            BUYER_INTENT_RULE_CANDIDATE_V1_VERSION
        ):
            invalid_candidate_version_count += 1
        if not _valid_uuid(item.get("rule_id")):
            invalid_rule_id_format_count += 1
        if type(item.get("operator")) is not str or item["operator"] not in _OPERATOR_VALUES:
            invalid_operator_count += 1
        if type(item.get("value_type")) is not str or item["value_type"] not in _VALUE_TYPE_VALUES:
            invalid_value_type_count += 1
        allowed_provenance = item.get("allowed_provenance")
        if type(allowed_provenance) is not list or len(allowed_provenance) == 0:
            invalid_allowed_provenance_shape_count += 1
    return {
        "is_array": type(value) is list,
        "item_count": len(items),
        "non_object_item_count": len(items) - len(object_items),
        "missing_rule_fields": sorted(missing_fields),
        "extra_rule_field_count": extra_rule_field_count,
        "invalid_rule_schema_version_count": invalid_schema_version_count,
        "invalid_rule_candidate_version_count": invalid_candidate_version_count,
        "invalid_rule_id_format_count": invalid_rule_id_format_count,
        "invalid_operator_count": invalid_operator_count,
        "invalid_value_type_count": invalid_value_type_count,
        "invalid_allowed_provenance_shape_count": invalid_allowed_provenance_shape_count,
    }


def fingerprint_invalid_candidate(output_text: str) -> dict[str, object] | None:
    """Return bounded structural facts for an already parser-rejected candidate."""
    try:
        parsed = json.loads(output_text)
        if type(parsed) is not dict:
            return None
        present_fields = set(parsed)
        fingerprint: dict[str, object] = {
            "missing_fields": sorted(_CANDIDATE_FIELDS - present_fields),
            "extra_field_count": len(present_fields - _CANDIDATE_FIELDS),
            "field_types": {
                field_name: _json_type_label(parsed[field_name])
                for field_name in sorted(_CANDIDATE_FIELDS & present_fields)
            },
            "schema_version_valid": (
                type(parsed.get("schema_version")) is str
                and parsed.get("schema_version") == _CANONICAL_SCHEMA_VERSION
            ),
            "candidate_version_valid": (
                type(parsed.get("buyer_intent_candidate_version")) is str
                and parsed.get("buyer_intent_candidate_version")
                == BUYER_INTENT_CANDIDATE_V1_VERSION
            ),
            "requested_quantity_positive_integer": _positive_integer(
                parsed.get("requested_quantity")
            ),
            "minimum_acceptable_quantity_positive_integer": _positive_integer(
                parsed.get("minimum_acceptable_quantity")
            ),
            "max_winners_positive_integer": _positive_integer(parsed.get("max_winners")),
            "max_total_payment_paise_nonnegative_integer": _nonnegative_integer(
                parsed.get("max_total_payment_paise")
            ),
            "hard_constraints": _rule_fingerprint(parsed.get("hard_constraints")),
            "soft_preferences": _rule_fingerprint(parsed.get("soft_preferences")),
        }
        requested = parsed.get("requested_quantity")
        minimum = parsed.get("minimum_acceptable_quantity")
        max_winners = parsed.get("max_winners")
        if _positive_integer(requested) and _positive_integer(minimum):
            fingerprint["minimum_lte_requested"] = minimum <= requested
        if _positive_integer(requested) and _positive_integer(max_winners):
            fingerprint["max_winners_lte_requested"] = max_winners <= requested
        return fingerprint
    except (TypeError, ValueError, RecursionError):
        return None


def configured_external_product_ai(
    environment: Mapping[str, str],
    provider: AIProvider | None = None,
) -> tuple[ProductAIConfig, AIProvider]:
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
        raise ProductAIConfigurationError
    models = tuple(environment["CLEAR_AI_MODELS"].split(","))
    if len(models) != 1 or models[0] == "" or models[0].strip() != models[0]:
        raise ProductAIConfigurationError
    config = ProductAIConfig(
        base_url=environment["CLEAR_AI_BASE_URL"],
        api_key=environment["CLEAR_AI_API_KEY"],
        provider_name=environment["CLEAR_AI_PROVIDER_NAME"],
        model=models[0],
    )
    try:
        live_provider = OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout_seconds=PROFILE_TIMEOUT_SECONDS,
        )
        AIProviderRequestV1(
            request_id=str(uuid4()),
            task=AIProviderTask.BUYER_INTENT,
            provider_name=config.provider_name,
            model=config.model,
            response_format=AIProviderResponseFormat.JSON_OBJECT,
            instruction_text="Validate the configured buyer-intent provider and model.",
            input_text="",
            max_output_bytes=1,
        )
    except (ValueError, ValidationError):
        raise ProductAIConfigurationError from None
    return config, live_provider if provider is None else provider


def configured_product_ai(
    environment: Mapping[str, str],
    provider: AIProvider | None = None,
) -> tuple[ProductAIConfig, AIProvider]:
    config, selected_provider = configured_external_product_ai(environment, provider)
    return config, BuyerIntentPromptGuardProvider(selected_provider)
