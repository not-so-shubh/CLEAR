"""Strict advisory buyer intent and deterministic BuyerPolicyV2 freezing."""

import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from clear_market.ai.provider import (
    AIProvider,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderTask,
    invoke_ai_provider_v1,
)
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    ComparisonOperator,
    HardConstraint,
    MarketSpecV2,
    ProvenanceLabel,
    SoftPreference,
)
from clear_market.commerce.primitives import AttributeKey
from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_SELLERS,
    MIN_SELLERS,
    CanonicalUUID4,
    Money,
    PositiveQuantity,
    UTCDateTime,
)

BUYER_INTENT_RULE_CANDIDATE_V1_VERSION: Final[str] = "buyer-intent-rule-candidate-v1"
BUYER_INTENT_CANDIDATE_V1_VERSION: Final[str] = "buyer-intent-candidate-v1"
BUYER_POLICY_FREEZE_CONTEXT_V1_VERSION: Final[str] = "buyer-policy-freeze-context-v1"
BUYER_INTENT_INSTRUCTION_V1_VERSION: Final[str] = "buyer-intent-instruction-v1"

MAX_BUYER_INTENT_RULES_PER_KIND: Final[int] = 64
MAX_BUYER_INTENT_STRING_VALUE_BYTES: Final[int] = 4_096
MAX_BUYER_INTENT_JSON_BYTES: Final[int] = 65_536

_VERSION_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}", flags=re.ASCII)
_ORDERED_OPERATORS = frozenset(
    {
        ComparisonOperator.LT,
        ComparisonOperator.LTE,
        ComparisonOperator.GT,
        ComparisonOperator.GTE,
    }
)

_BUYER_INTENT_INSTRUCTION_V1: Final[str] = """\
Return exactly one JSON object and no markdown, code fences, or prose.
Use schema_version "1" and buyer_intent_candidate_version "buyer-intent-candidate-v1".
Each rule must use schema_version "1", buyer_intent_rule_candidate_version
"buyer-intent-rule-candidate-v1", and a valid canonical UUIDv4 rule_id.
Use integer quantities and integer INR paise for max_total_payment_paise.
Keep hard_constraints distinct from soft_preferences.
Use only operators: eq, ne, lt, lte, gt, gte.
Use only value types: string, integer, boolean.
Use only provenance labels: VERIFIED, ATTESTED, CLAIMED, DERIVED, PREDICTED.
Never include PREDICTED in hard-constraint allowed_provenance.
allowed_provenance states which evidence categories the buyer accepts; it does not assign
provenance to merchant facts. Never claim that a product or merchant fact is VERIFIED.
Do not output catalog, SKU, merchant, or merchant-fact data. Do not output winners or payments.
Do not output trusted context fields: market_id, buyer_id, eligible_merchant_ids, offer_deadline,
mechanism_version, or objective_version.
Do not invent a budget or requested quantity when absent. If essential economic information is
unavailable, return an object that fails the strict candidate schema rather than guessing.
Unless partial fulfillment is clearly allowed, set minimum_acceptable_quantity equal to
requested_quantity. Unless multiple winners or split fulfillment is clearly requested, set
max_winners to 1.
"""


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as an exact tuple")
    return value


def _validate_version_identifier(value: object) -> str:
    if type(value) is not str or _VERSION_IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError("version identifier is not canonical")
    return value


type _RuleScalar = StrictStr | StrictInt | StrictBool
type _AllowedProvenance = Annotated[
    tuple[ProvenanceLabel, ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1),
]
type _RuleCandidates = Annotated[
    tuple["BuyerIntentRuleCandidateV1", ...],
    BeforeValidator(_require_tuple),
    Field(max_length=MAX_BUYER_INTENT_RULES_PER_KIND),
]
type _MaxWinners = Annotated[int, Field(strict=True, ge=1, le=MAX_SELLERS)]
type _BudgetPaise = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_PAISE)]
type _EligibleMerchantIds = Annotated[
    tuple[CanonicalUUID4, ...],
    BeforeValidator(_require_tuple),
    Field(min_length=MIN_SELLERS, max_length=MAX_SELLERS),
]
type _VersionIdentifier = Annotated[str, BeforeValidator(_validate_version_identifier)]


class BuyerIntentRuleCandidateV1(BaseModel):
    """Untrusted advisory representation of one buyer policy rule."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    buyer_intent_rule_candidate_version: Literal["buyer-intent-rule-candidate-v1"] = (
        "buyer-intent-rule-candidate-v1"
    )
    rule_id: CanonicalUUID4
    attribute_key: AttributeKey
    operator: ComparisonOperator
    value_type: AttributeValueType
    value: _RuleScalar
    allowed_provenance: _AllowedProvenance

    @field_validator("allowed_provenance")
    @classmethod
    def _validate_allowed_provenance(
        cls,
        labels: tuple[ProvenanceLabel, ...],
    ) -> tuple[ProvenanceLabel, ...]:
        if len(set(labels)) != len(labels):
            raise ValueError("allowed provenance labels must be unique")
        return tuple(sorted(labels, key=lambda label: label.value))

    @model_validator(mode="after")
    def _validate_value_and_operator(self) -> Self:
        expected_type = {
            AttributeValueType.STRING: str,
            AttributeValueType.INTEGER: int,
            AttributeValueType.BOOLEAN: bool,
        }[self.value_type]
        if type(self.value) is not expected_type:
            raise ValueError("declared value type does not match the scalar")

        if type(self.value) is str:
            if "\x00" in self.value:
                raise ValueError("string value must not contain NUL")
            try:
                encoded = self.value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as error:
                raise ValueError("string value must be valid UTF-8") from error
            if len(encoded) > MAX_BUYER_INTENT_STRING_VALUE_BYTES:
                raise ValueError("string value exceeds its UTF-8 byte bound")

        if (
            self.operator in _ORDERED_OPERATORS
            and self.value_type is not AttributeValueType.INTEGER
        ):
            raise ValueError("ordered comparisons require an integer value")
        return self


class BuyerIntentCandidateV1(BaseModel):
    """Strict advisory demand semantics with no trusted market context."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    buyer_intent_candidate_version: Literal["buyer-intent-candidate-v1"] = (
        "buyer-intent-candidate-v1"
    )
    requested_quantity: PositiveQuantity
    minimum_acceptable_quantity: PositiveQuantity
    max_winners: _MaxWinners
    max_total_payment_paise: _BudgetPaise
    hard_constraints: _RuleCandidates
    soft_preferences: _RuleCandidates

    @field_validator("hard_constraints", "soft_preferences")
    @classmethod
    def _validate_and_normalize_rules(
        cls,
        rules: tuple[BuyerIntentRuleCandidateV1, ...],
    ) -> tuple[BuyerIntentRuleCandidateV1, ...]:
        rule_ids = tuple(rule.rule_id for rule in rules)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule IDs within a collection must be unique")
        return tuple(sorted(rules, key=lambda rule: rule.rule_id))

    @model_validator(mode="after")
    def _validate_candidate_semantics(self) -> Self:
        if self.minimum_acceptable_quantity > self.requested_quantity:
            raise ValueError("minimum acceptable quantity exceeds requested quantity")
        if self.max_winners > self.requested_quantity:
            raise ValueError("maximum winner count exceeds requested quantity")

        hard_ids = {rule.rule_id for rule in self.hard_constraints}
        soft_ids = {rule.rule_id for rule in self.soft_preferences}
        if hard_ids & soft_ids:
            raise ValueError("hard and soft rules must use distinct IDs")
        if any(
            ProvenanceLabel.PREDICTED in rule.allowed_provenance for rule in self.hard_constraints
        ):
            raise ValueError("predicted provenance is not allowed for hard constraints")
        return self


class BuyerPolicyFreezeContextV1(BaseModel):
    """Trusted caller-owned market identity, population, deadline, and protocol versions."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    buyer_policy_freeze_context_version: Literal["buyer-policy-freeze-context-v1"] = (
        "buyer-policy-freeze-context-v1"
    )
    market_id: CanonicalUUID4
    buyer_id: CanonicalUUID4
    eligible_merchant_ids: _EligibleMerchantIds
    offer_deadline: UTCDateTime
    mechanism_version: _VersionIdentifier
    objective_version: _VersionIdentifier

    @field_validator("eligible_merchant_ids")
    @classmethod
    def _validate_and_normalize_merchant_ids(
        cls,
        merchant_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(merchant_ids)) != len(merchant_ids):
            raise ValueError("eligible merchant IDs must be unique")
        return tuple(sorted(merchant_ids))


class BuyerIntentFreezeErrorCode(StrEnum):
    INVALID_CONTEXT = "INVALID_CONTEXT"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    MAX_WINNERS_EXCEEDS_ELIGIBLE_MERCHANTS = "MAX_WINNERS_EXCEEDS_ELIGIBLE_MERCHANTS"


class BuyerIntentFreezeError(ValueError):
    """Stable deterministic freeze failure without raw validation prose."""

    __slots__ = ("_code",)

    def __init__(self, code: BuyerIntentFreezeErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> BuyerIntentFreezeErrorCode:
        return self._code


def _validate_freeze_context(
    context: BuyerPolicyFreezeContextV1,
) -> BuyerPolicyFreezeContextV1:
    try:
        return BuyerPolicyFreezeContextV1.model_validate(context)
    except ValidationError:
        raise BuyerIntentFreezeError(BuyerIntentFreezeErrorCode.INVALID_CONTEXT) from None


def _validate_intent_candidate(candidate: BuyerIntentCandidateV1) -> BuyerIntentCandidateV1:
    try:
        return BuyerIntentCandidateV1.model_validate(candidate)
    except ValidationError:
        raise BuyerIntentFreezeError(BuyerIntentFreezeErrorCode.INVALID_CANDIDATE) from None


def freeze_buyer_policy_v2(
    *,
    context: BuyerPolicyFreezeContextV1,
    candidate: BuyerIntentCandidateV1,
) -> BuyerPolicyV2:
    """Freeze advisory demand under trusted context without repair or economic evaluation."""
    if type(context) is not BuyerPolicyFreezeContextV1:
        raise TypeError("context must be exactly a BuyerPolicyFreezeContextV1")
    validated_context = _validate_freeze_context(context)

    if type(candidate) is not BuyerIntentCandidateV1:
        raise TypeError("candidate must be exactly a BuyerIntentCandidateV1")
    validated_candidate = _validate_intent_candidate(candidate)

    if validated_candidate.max_winners > len(validated_context.eligible_merchant_ids):
        raise BuyerIntentFreezeError(
            BuyerIntentFreezeErrorCode.MAX_WINNERS_EXCEEDS_ELIGIBLE_MERCHANTS
        )

    hard_constraints = tuple(
        HardConstraint(
            constraint_id=rule.rule_id,
            attribute_key=rule.attribute_key,
            operator=rule.operator,
            operand=AttributeValue(value_type=rule.value_type, value=rule.value),
            allowed_provenance=rule.allowed_provenance,
        )
        for rule in validated_candidate.hard_constraints
    )
    soft_preferences = tuple(
        SoftPreference(
            preference_id=rule.rule_id,
            attribute_key=rule.attribute_key,
            operator=rule.operator,
            operand=AttributeValue(value_type=rule.value_type, value=rule.value),
            allowed_provenance=rule.allowed_provenance,
        )
        for rule in validated_candidate.soft_preferences
    )
    market_spec = MarketSpecV2(
        market_id=validated_context.market_id,
        buyer_id=validated_context.buyer_id,
        requested_quantity=validated_candidate.requested_quantity,
        minimum_acceptable_quantity=validated_candidate.minimum_acceptable_quantity,
        max_winners=validated_candidate.max_winners,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
    )
    return BuyerPolicyV2(
        market_spec=market_spec,
        max_total_payment=Money(amount_paise=validated_candidate.max_total_payment_paise),
        eligible_merchant_ids=validated_context.eligible_merchant_ids,
        offer_deadline=validated_context.offer_deadline,
        mechanism_version=validated_context.mechanism_version,
        objective_version=validated_context.objective_version,
    )


def interpret_buyer_intent_v1(
    *,
    provider: AIProvider,
    request_id: CanonicalUUID4,
    provider_name: str,
    model: str,
    buyer_text: str,
    freeze_context: BuyerPolicyFreezeContextV1,
) -> BuyerPolicyV2:
    """Interpret untrusted model output, parse it strictly, then freeze trusted policy."""
    if type(freeze_context) is not BuyerPolicyFreezeContextV1:
        raise TypeError("freeze_context must be exactly a BuyerPolicyFreezeContextV1")
    validated_context = _validate_freeze_context(freeze_context)

    request = AIProviderRequestV1(
        request_id=request_id,
        task=AIProviderTask.BUYER_INTENT,
        provider_name=provider_name,
        model=model,
        response_format=AIProviderResponseFormat.JSON_OBJECT,
        instruction_text=_BUYER_INTENT_INSTRUCTION_V1,
        input_text=buyer_text,
        max_output_bytes=MAX_BUYER_INTENT_JSON_BYTES,
    )
    response = invoke_ai_provider_v1(provider=provider, request=request)

    from clear_market.ai.buyer_intent_parsing import parse_buyer_intent_candidate_v1

    candidate = parse_buyer_intent_candidate_v1(response.output_text)
    return freeze_buyer_policy_v2(context=validated_context, candidate=candidate)
