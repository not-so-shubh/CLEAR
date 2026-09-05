import os
from datetime import UTC, datetime

import pytest

from clear_market.ai.buyer_intent import (
    BuyerPolicyFreezeContextV1,
    interpret_buyer_intent_v1,
)
from clear_market.ai.openai_compatible import OpenAICompatibleProvider
from clear_market.mechanism.v2 import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
)

_REQUIRED_ENVIRONMENT = (
    "CLEAR_AI_BASE_URL",
    "CLEAR_AI_API_KEY",
    "CLEAR_AI_PROVIDER_NAME",
    "CLEAR_AI_MODEL",
)


def _live_configuration() -> dict[str, str]:
    if os.environ.get("CLEAR_AI_LIVE") != "1":
        pytest.skip("live AI smoke test requires explicit CLEAR_AI_LIVE=1 opt-in")
    values = {name: os.environ.get(name, "") for name in _REQUIRED_ENVIRONMENT}
    if any(value == "" for value in values.values()):
        pytest.skip("live AI smoke test requires all provider configuration variables")
    return values


def test_live_buyer_intent_provider_path() -> None:
    values = _live_configuration()
    provider = OpenAICompatibleProvider(
        base_url=values["CLEAR_AI_BASE_URL"],
        api_key=values["CLEAR_AI_API_KEY"],
        timeout_seconds=60,
    )
    context = BuyerPolicyFreezeContextV1(
        market_id="82000000-0000-4000-8000-000000000001",
        buyer_id="82000000-0000-4000-8000-000000000002",
        eligible_merchant_ids=(
            "82000000-0000-4000-8000-000000000011",
            "82000000-0000-4000-8000-000000000012",
        ),
        offer_deadline=datetime(2030, 1, 1, 12, 0, tzinfo=UTC),
        mechanism_version=HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
        objective_version=QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    )
    policy = interpret_buyer_intent_v1(
        provider=provider,
        request_id="82000000-0000-4000-8000-000000000003",
        provider_name=values["CLEAR_AI_PROVIDER_NAME"],
        model=values["CLEAR_AI_MODEL"],
        buyer_text=(
            "Buy exactly 2 units. Maximum total payment is INR 500. "
            "Partial fulfillment is not allowed. Use one winner. "
            "I have no additional product constraints."
        ),
        freeze_context=context,
    )

    assert policy.market_spec.requested_quantity == 2
    assert policy.market_spec.minimum_acceptable_quantity == 2
    assert policy.market_spec.max_winners == 1
    assert policy.max_total_payment.amount_paise == 50_000
    assert policy.market_spec.market_id == context.market_id
    assert policy.market_spec.buyer_id == context.buyer_id
    assert policy.eligible_merchant_ids == context.eligible_merchant_ids
    assert policy.offer_deadline == context.offer_deadline
    assert policy.mechanism_version == context.mechanism_version
    assert policy.objective_version == context.objective_version
