from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from clear_market.benchmark.seeds import MAX_GENERATOR_SEED
from clear_market.domain import BuyerPolicy, SignedMerchantBid
from clear_market.lifecycle import AdmissionContext

type _GeneratorSeed = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_GENERATOR_SEED),
]


class GeneratedAdmissionAttempt(BaseModel):
    """A correctly authenticated bid paired with explicit receipt evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signed_bid: SignedMerchantBid
    context: AdmissionContext


class GeneratedMarketCase(BaseModel):
    """Immutable benchmark input evidence without an economic answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generator_version: Literal["deterministic-market-generator-v1"] = (
        "deterministic-market-generator-v1"
    )
    seed: _GeneratorSeed
    buyer_policy: BuyerPolicy
    admission_attempts: tuple[GeneratedAdmissionAttempt, ...]
