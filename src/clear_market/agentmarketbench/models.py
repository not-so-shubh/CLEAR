"""Foundational AgentMarketBench protocol and case models."""

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from clear_market.commerce.authentication import MerchantSigningIdentityV2, SignedMerchantOfferV2
from clear_market.commerce.catalog import (
    MAX_ATTRIBUTES_PER_SKU,
    InventorySnapshotV2,
    MerchantCatalogV2,
)
from clear_market.commerce.market import BuyerPolicyV2
from clear_market.commerce.primitives import AttributeKey, AttributeValue
from clear_market.domain import CanonicalUUID4, Money, Quantity, UTCDateTime

AGENT_MARKET_BENCH_PROTOCOL_V1_VERSION: Final[str] = "agent-market-bench-protocol-v1"
AGENT_MARKET_BENCH_GENERATOR_V1_VERSION: Final[str] = "agent-market-bench-generator-v1"
AGENT_MARKET_BENCH_CASE_V1_VERSION: Final[str] = "agent-market-bench-case-v1"
AGENT_MARKET_BENCH_MARKET_INPUT_V1_VERSION: Final[str] = "agent-market-bench-market-input-v1"
AGENT_MARKET_BENCH_LATENT_ATTRIBUTE_V1_VERSION: Final[str] = (
    "agent-market-bench-latent-attribute-v1"
)
AGENT_MARKET_BENCH_LATENT_LINE_V1_VERSION: Final[str] = "agent-market-bench-latent-line-v1"
AGENT_MARKET_BENCH_OBSERVED_MERCHANT_V1_VERSION: Final[str] = (
    "agent-market-bench-observed-merchant-v1"
)
AGENT_MARKET_BENCH_REPORTED_OFFER_V1_VERSION: Final[str] = "agent-market-bench-reported-offer-v1"
AGENT_MARKET_BENCH_CASE_DIGEST_V1_VERSION: Final[str] = (
    "sha256-agent-market-bench-case-v1-clear-json-v1"
)
MAX_AGENT_MARKET_BENCH_SEED: Final[int] = 2_147_483_647


class AgentMarketBenchBaselineV1(StrEnum):
    RANDOM_QUALIFYING_SELLER = "RANDOM_QUALIFYING_SELLER"
    CHEAPEST_QUALIFYING = "CHEAPEST_QUALIFYING"
    STATIC_WEIGHTED_SCORE = "STATIC_WEIGHTED_SCORE"
    BILATERAL_NEGOTIATION = "BILATERAL_NEGOTIATION"
    SEQUENTIAL_NEGOTIATION = "SEQUENTIAL_NEGOTIATION"
    FIRST_PRICE_REVERSE_AUCTION = "FIRST_PRICE_REVERSE_AUCTION"
    REVERSE_VICKREY = "REVERSE_VICKREY"
    CLEAR = "CLEAR"
    FULL_INFORMATION_ORACLE = "FULL_INFORMATION_ORACLE"


class AgentMarketBenchMetricV1(StrEnum):
    ALLOCATIVE_EFFICIENCY = "ALLOCATIVE_EFFICIENCY"
    REGRET = "REGRET"
    BUYER_SURPLUS = "BUYER_SURPLUS"
    MERCHANT_SURPLUS = "MERCHANT_SURPLUS"
    WELFARE = "WELFARE"
    COMPLETION = "COMPLETION"
    HARD_CONSTRAINT_VIOLATIONS = "HARD_CONSTRAINT_VIOLATIONS"
    MANIPULATION_SUCCESS = "MANIPULATION_SUCCESS"
    PAYMENT_CORRECTNESS = "PAYMENT_CORRECTNESS"
    DUPLICATE_FINANCIAL_SIDE_EFFECTS = "DUPLICATE_FINANCIAL_SIDE_EFFECTS"
    LATENCY = "LATENCY"


class AgentMarketBenchAdversarialClassificationV1(StrEnum):
    PREVENTED = "PREVENTED"
    DETECTED = "DETECTED"
    MITIGATED = "MITIGATED"
    MEASURED = "MEASURED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class AgentMarketBenchAdversarialScenarioV1(StrEnum):
    ALTERED_OFFER = "ALTERED_OFFER"
    LATE_OFFER = "LATE_OFFER"
    REPLAYED_OFFER = "REPLAYED_OFFER"
    FORGED_MERCHANT = "FORGED_MERCHANT"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    MALICIOUS_CATALOG_TEXT = "MALICIOUS_CATALOG_TEXT"
    SCHEMA_MANIPULATION = "SCHEMA_MANIPULATION"
    STRATEGIC_SHADING = "STRATEGIC_SHADING"
    SELLER_DROPOUT = "SELLER_DROPOUT"
    FAKE_INVENTORY = "FAKE_INVENTORY"
    SLA_OVERPROMISE = "SLA_OVERPROMISE"
    SYBIL_SENSITIVITY = "SYBIL_SENSITIVITY"
    COLLUSION_SENSITIVITY = "COLLUSION_SENSITIVITY"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    EVENT_REORDERING = "EVENT_REORDERING"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PAYMENT_FAILURE = "PAYMENT_FAILURE"
    TRANSFER_FAILURE = "TRANSFER_FAILURE"
    RETRY = "RETRY"
    RECONCILIATION = "RECONCILIATION"
    RECOVERY = "RECOVERY"


def _fresh_exact[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT:
    """Require an exact model and reconstruct it through its complete schema."""
    if type(value) is not model_type:
        raise ValueError(f"value must be exactly {model_type.__name__}")

    model = value
    try:
        if model_type.__module__ == __name__:
            raw = {field_name: getattr(model, field_name) for field_name in model_type.model_fields}
        else:
            raw = model.model_dump(mode="python")
        fresh = model_type.model_validate(raw)
    except Exception as error:
        raise ValueError(f"{model_type.__name__} failed fresh validation") from error
    if type(fresh) is not model_type:
        raise ValueError(f"value must revalidate to exactly {model_type.__name__}")
    return fresh


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as a tuple")
    return value


def _require_exact_enum(enum_type: type[StrEnum], value: object) -> StrEnum:
    if type(value) is not enum_type:
        raise ValueError(f"value must be exactly {enum_type.__name__}")
    return value


def _validate_buyer_text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("buyer_text must be supplied as an exact string")
    if "\x00" in value:
        raise ValueError("buyer_text must not contain NUL")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("buyer_text must be valid UTF-8") from error
    if len(encoded) > 262_144:
        raise ValueError("buyer_text exceeds the UTF-8 byte limit")
    return value


_FreshAttributeValue = Annotated[
    AttributeValue,
    BeforeValidator(lambda value: _fresh_exact(AttributeValue, value)),
]
_FreshMoney = Annotated[
    Money,
    BeforeValidator(lambda value: _fresh_exact(Money, value)),
]
_FreshBuyerPolicy = Annotated[
    BuyerPolicyV2,
    BeforeValidator(lambda value: _fresh_exact(BuyerPolicyV2, value)),
]
_FreshCatalog = Annotated[
    MerchantCatalogV2,
    BeforeValidator(lambda value: _fresh_exact(MerchantCatalogV2, value)),
]
_FreshInventory = Annotated[
    InventorySnapshotV2,
    BeforeValidator(lambda value: _fresh_exact(InventorySnapshotV2, value)),
]
_FreshSigningIdentity = Annotated[
    MerchantSigningIdentityV2,
    BeforeValidator(lambda value: _fresh_exact(MerchantSigningIdentityV2, value)),
]
_FreshSignedOffer = Annotated[
    SignedMerchantOfferV2,
    BeforeValidator(lambda value: _fresh_exact(SignedMerchantOfferV2, value)),
]


class AgentMarketBenchLatentAttributeV1(BaseModel):
    """Hidden benchmark ground truth, not reported catalog provenance or method input."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_latent_attribute_version: Literal[
        "agent-market-bench-latent-attribute-v1"
    ] = "agent-market-bench-latent-attribute-v1"
    attribute_key: AttributeKey
    value: _FreshAttributeValue


_FreshLatentAttribute = Annotated[
    AgentMarketBenchLatentAttributeV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchLatentAttributeV1, value)),
]


class AgentMarketBenchLatentLineV1(BaseModel):
    """Hidden economic truth for one merchant SKU, reserved for oracle and metrics."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_latent_line_version: Literal["agent-market-bench-latent-line-v1"] = (
        "agent-market-bench-latent-line-v1"
    )
    economic_principal_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    sku_id: CanonicalUUID4
    true_available_quantity: Quantity
    true_unit_cost: _FreshMoney
    true_unit_buyer_value: _FreshMoney
    true_attributes: Annotated[
        tuple[_FreshLatentAttribute, ...],
        BeforeValidator(_require_tuple),
        Field(max_length=MAX_ATTRIBUTES_PER_SKU),
    ]

    @model_validator(mode="after")
    def _normalize_and_validate_attributes(self) -> "AgentMarketBenchLatentLineV1":
        keys = tuple(attribute.attribute_key for attribute in self.true_attributes)
        if len(set(keys)) != len(keys):
            raise ValueError("latent attribute keys must be unique within a SKU")
        normalized = tuple(
            sorted(self.true_attributes, key=lambda attribute: attribute.attribute_key)
        )
        if normalized != self.true_attributes:
            object.__setattr__(self, "true_attributes", normalized)
        return self


_FreshLatentLine = Annotated[
    AgentMarketBenchLatentLineV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchLatentLineV1, value)),
]


class AgentMarketBenchObservedMerchantV1(BaseModel):
    """Public merchant state visible to evaluated methods, with no latent economics or
    secret material."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_observed_merchant_version: Literal[
        "agent-market-bench-observed-merchant-v1"
    ] = "agent-market-bench-observed-merchant-v1"
    merchant_id: CanonicalUUID4
    catalog: _FreshCatalog
    inventory_snapshot: _FreshInventory
    signing_identity: _FreshSigningIdentity

    @model_validator(mode="after")
    def _validate_source_identity(self) -> "AgentMarketBenchObservedMerchantV1":
        if self.catalog.merchant_id != self.merchant_id:
            raise ValueError("catalog merchant does not match observed merchant")
        if self.inventory_snapshot.merchant_id != self.merchant_id:
            raise ValueError("inventory merchant does not match observed merchant")
        if self.inventory_snapshot.catalog_id != self.catalog.catalog_id:
            raise ValueError("inventory catalog identity does not match catalog")
        if self.signing_identity.merchant_id != self.merchant_id:
            raise ValueError("signing identity merchant does not match observed merchant")
        return self


class AgentMarketBenchReportedOfferV1(BaseModel):
    """A structural offer receipt that deliberately permits invalid, late, and replayed offers."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_reported_offer_version: Literal["agent-market-bench-reported-offer-v1"] = (
        "agent-market-bench-reported-offer-v1"
    )
    submission_index: Annotated[int, Field(strict=True, ge=0)]
    received_at: UTCDateTime
    signed_offer: _FreshSignedOffer


_FreshReportedOffer = Annotated[
    AgentMarketBenchReportedOfferV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchReportedOfferV1, value)),
]


_FreshCaseObservedMerchant = Annotated[
    AgentMarketBenchObservedMerchantV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchObservedMerchantV1, value)),
]


class AgentMarketBenchMarketInputV1(BaseModel):
    """This is the complete benchmark-visible economic method input.

    Absence of latent truth and adversarial labels is an authority boundary, not a convenience.
    Direct construction carries no certificate, allocation, financial, payment, routing,
    settlement, or fulfillment authority. Future evaluated methods receive this object as
    benchmark-visible input only.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_market_input_version: Literal["agent-market-bench-market-input-v1"] = (
        "agent-market-bench-market-input-v1"
    )
    buyer_policy: _FreshBuyerPolicy
    observed_merchants: Annotated[
        tuple[_FreshCaseObservedMerchant, ...],
        BeforeValidator(_require_tuple),
    ]
    reported_offers: Annotated[
        tuple[_FreshReportedOffer, ...],
        BeforeValidator(_require_tuple),
    ]


class AgentMarketBenchCaseV1(BaseModel):
    """Evaluation evidence only.

    Direct construction does not authenticate reported offers, establish latent truth in the
    physical world, verify an allocation certificate, authorize money movement, or prove
    fulfillment.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_case_version: Literal["agent-market-bench-case-v1"] = (
        "agent-market-bench-case-v1"
    )
    generator_version: Literal["agent-market-bench-generator-v1"] = (
        "agent-market-bench-generator-v1"
    )
    seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    case_id: CanonicalUUID4
    buyer_text: Annotated[str, BeforeValidator(_validate_buyer_text)]
    buyer_policy: _FreshBuyerPolicy
    observed_merchants: Annotated[
        tuple[_FreshCaseObservedMerchant, ...],
        BeforeValidator(_require_tuple),
    ]
    latent_lines: Annotated[
        tuple[_FreshLatentLine, ...],
        BeforeValidator(_require_tuple),
    ]
    reported_offers: Annotated[
        tuple[_FreshReportedOffer, ...],
        BeforeValidator(_require_tuple),
    ]
    adversarial_scenarios: Annotated[
        tuple[
            Annotated[
                AgentMarketBenchAdversarialScenarioV1,
                BeforeValidator(
                    lambda value: _require_exact_enum(AgentMarketBenchAdversarialScenarioV1, value)
                ),
            ],
            ...,
        ],
        BeforeValidator(_require_tuple),
    ]

    @model_validator(mode="after")
    def _validate_and_normalize_case(self) -> "AgentMarketBenchCaseV1":
        observed_ids = tuple(merchant.merchant_id for merchant in self.observed_merchants)
        if len(set(observed_ids)) != len(observed_ids):
            raise ValueError("observed merchant IDs must be unique")
        eligible_ids = set(self.buyer_policy.eligible_merchant_ids)
        if set(observed_ids) != eligible_ids:
            raise ValueError("observed merchant IDs must equal eligible merchant IDs")
        normalized_merchants = tuple(
            sorted(self.observed_merchants, key=lambda merchant: merchant.merchant_id)
        )

        latent_keys = tuple((line.merchant_id, line.sku_id) for line in self.latent_lines)
        if len(set(latent_keys)) != len(latent_keys):
            raise ValueError("latent merchant/SKU keys must be unique")
        normalized_latent = tuple(
            sorted(self.latent_lines, key=lambda line: (line.merchant_id, line.sku_id))
        )

        observed_sku_keys = {
            (merchant.merchant_id, sku.sku_id)
            for merchant in self.observed_merchants
            for sku in merchant.catalog.skus
        }
        latent_key_set = set(latent_keys)
        if latent_key_set != observed_sku_keys:
            raise ValueError("latent keys must exactly cover observed catalog SKUs")

        observed_by_id = {merchant.merchant_id: merchant for merchant in self.observed_merchants}
        principal_by_merchant: dict[str, str] = {}
        for line in self.latent_lines:
            if line.merchant_id not in observed_by_id:
                raise ValueError("latent merchant must be observed")
            previous_principal = principal_by_merchant.setdefault(
                line.merchant_id, line.economic_principal_id
            )
            if previous_principal != line.economic_principal_id:
                raise ValueError("one merchant must map to one economic principal")
            catalog = observed_by_id[line.merchant_id].catalog
            catalog_sku = next((sku for sku in catalog.skus if sku.sku_id == line.sku_id), None)
            if catalog_sku is None:
                raise ValueError("latent SKU must be present in observed catalog")
            if {attribute.attribute_key for attribute in line.true_attributes} != {
                attribute.attribute_key for attribute in catalog_sku.attributes
            }:
                raise ValueError("latent attribute keys must match observed catalog SKU")

        submission_indexes = tuple(offer.submission_index for offer in self.reported_offers)
        if submission_indexes != tuple(range(len(self.reported_offers))):
            raise ValueError("reported submission indexes must equal tuple order")

        if len(set(self.adversarial_scenarios)) != len(self.adversarial_scenarios):
            raise ValueError("adversarial scenarios must be unique")
        normalized_scenarios = tuple(
            sorted(self.adversarial_scenarios, key=lambda scenario: scenario.value)
        )

        if normalized_merchants != self.observed_merchants:
            object.__setattr__(self, "observed_merchants", normalized_merchants)
        if normalized_latent != self.latent_lines:
            object.__setattr__(self, "latent_lines", normalized_latent)
        if normalized_scenarios != self.adversarial_scenarios:
            object.__setattr__(self, "adversarial_scenarios", normalized_scenarios)
        return self
