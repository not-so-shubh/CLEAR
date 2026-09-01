import random
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from clear_market.benchmark import (
    DEVELOPMENT_SEEDS,
    MARKET_GENERATOR_VERSION,
    MAX_GENERATOR_SEED,
    GeneratedAdmissionAttempt,
    GeneratedMarketCase,
    generate_market_case,
)
from clear_market.crypto import buyer_policy_commitment
from clear_market.domain import MAX_SELLERS, MIN_SELLERS
from clear_market.lifecycle import AdmissionState, admit_signed_bid

_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)
_SEED_ZERO_PUBLIC_KEYS = (
    "9cef79217c9aa74613f0f976d9ead31934320648aab28fe96abe7b95aedc0bb3",
    "8d65f58ad3d7063697d00f30cd16fcd06bbc9406b02cff335faf8e42fb089698",
    "b02bc10ff866b6cba119cbed023d0e9eae81ed614b3ac3b0cffeb8a830d484c8",
    "d82dfc86e42dcd0e3ef7373565a4371185caa3e62a70a115de186a69cb0f7b16",
    "c51e7af2994713c525b39c68d9ca41029a823ae9b3dd1dc6d4771060d729a109",
)


def _rebuild_case(case: GeneratedMarketCase, **updates: object) -> GeneratedMarketCase:
    values: dict[str, object] = {
        "generator_version": case.generator_version,
        "seed": case.seed,
        "buyer_policy": case.buyer_policy,
        "admission_attempts": case.admission_attempts,
    }
    values.update(updates)
    return GeneratedMarketCase.model_validate(values)


def test_generated_models_have_exact_fields_and_configuration() -> None:
    assert tuple(GeneratedAdmissionAttempt.model_fields) == ("signed_bid", "context")
    assert tuple(GeneratedMarketCase.model_fields) == (
        "generator_version",
        "seed",
        "buyer_policy",
        "admission_attempts",
    )
    assert GeneratedAdmissionAttempt.model_config["frozen"] is True
    assert GeneratedAdmissionAttempt.model_config["extra"] == "forbid"
    assert GeneratedMarketCase.model_config["frozen"] is True
    assert GeneratedMarketCase.model_config["extra"] == "forbid"


def test_generated_models_are_frozen() -> None:
    case = generate_market_case(0)
    attempt = case.admission_attempts[0]

    with pytest.raises(ValidationError):
        case.seed = 1
    with pytest.raises(ValidationError):
        attempt.context = attempt.context


def test_generated_models_forbid_extra_fields() -> None:
    case = generate_market_case(0)
    attempt = case.admission_attempts[0]

    with pytest.raises(ValidationError):
        _rebuild_case(case, unexpected=True)
    with pytest.raises(ValidationError):
        GeneratedAdmissionAttempt.model_validate(
            {
                "signed_bid": attempt.signed_bid,
                "context": attempt.context,
                "unexpected": True,
            }
        )


def test_generated_market_case_protocol_version_is_exact() -> None:
    case = generate_market_case(0)

    assert case.generator_version == MARKET_GENERATOR_VERSION
    with pytest.raises(ValidationError):
        _rebuild_case(case, generator_version="deterministic-market-generator-v2")


@pytest.mark.parametrize("seed", [0, MAX_GENERATOR_SEED])
def test_generated_market_case_model_accepts_seed_bounds(seed: int) -> None:
    case = generate_market_case(0)

    assert _rebuild_case(case, seed=seed).seed == seed


@pytest.mark.parametrize("seed", [True, False, 1.0, "1"])
def test_generated_market_case_model_rejects_non_exact_integer_seed(seed: object) -> None:
    case = generate_market_case(0)

    with pytest.raises(ValidationError):
        _rebuild_case(case, seed=seed)


@pytest.mark.parametrize("seed", [-1, MAX_GENERATOR_SEED + 1])
def test_generated_market_case_model_rejects_out_of_range_seed(seed: int) -> None:
    case = generate_market_case(0)

    with pytest.raises(ValidationError):
        _rebuild_case(case, seed=seed)


@pytest.mark.parametrize("seed", [0, MAX_GENERATOR_SEED])
def test_generator_accepts_seed_bounds(seed: int) -> None:
    assert generate_market_case(seed).seed == seed


@pytest.mark.parametrize("seller_count", [MIN_SELLERS, 5, MAX_SELLERS])
def test_generator_accepts_seller_count_bounds(seller_count: int) -> None:
    case = generate_market_case(0, seller_count)

    assert len(case.buyer_policy.eligible_merchants) == seller_count


@pytest.mark.parametrize("seed", [True, False, 1.0, "1"])
def test_generator_rejects_non_exact_integer_seed(seed: object) -> None:
    with pytest.raises(TypeError):
        generate_market_case(seed)


@pytest.mark.parametrize("seller_count", [True, False, 5.0, "5"])
def test_generator_rejects_non_exact_integer_seller_count(seller_count: object) -> None:
    with pytest.raises(TypeError):
        generate_market_case(0, seller_count)


@pytest.mark.parametrize("seed", [-1, MAX_GENERATOR_SEED + 1])
def test_generator_rejects_out_of_range_seed(seed: int) -> None:
    with pytest.raises(ValueError):
        generate_market_case(seed)


@pytest.mark.parametrize("seller_count", [MIN_SELLERS - 1, MAX_SELLERS + 1])
def test_generator_rejects_out_of_range_seller_count(seller_count: int) -> None:
    with pytest.raises(ValueError):
        generate_market_case(0, seller_count)


@pytest.mark.parametrize("seed", [0, 1, 31, 1_000_000, 1_009_999, MAX_GENERATOR_SEED])
def test_complete_generated_case_is_deterministic(seed: int) -> None:
    assert generate_market_case(seed) == generate_market_case(seed)


def test_distinct_seeds_produce_distinct_complete_cases() -> None:
    assert generate_market_case(0) != generate_market_case(1)


def test_zero_participation_market_is_preserved_without_redraw() -> None:
    case = generate_market_case(23)

    assert case.admission_attempts == ()


def test_generator_does_not_change_global_random_state() -> None:
    before = random.getstate()

    generate_market_case(31)

    assert random.getstate() == before


def test_seed_zero_python_prng_draws_are_frozen() -> None:
    rng = random.Random(0)
    requested_quantity = rng.randint(1, 20)
    reserve = rng.randint(0, 25)
    quantity_choices = (0, 12, 13, 14, 15)
    price_choices = (0, 23, 24, 25, 26)
    draws = tuple(
        (
            bool(rng.getrandbits(1)),
            rng.choice(quantity_choices),
            rng.choice(price_choices),
        )
        for _ in range(5)
    )
    participating_indexes = [
        index for index, (participates, _, _) in enumerate(draws) if participates
    ]
    rng.shuffle(participating_indexes)

    assert requested_quantity == 13
    assert reserve == 24
    assert draws == (
        (True, 14, 0),
        (False, 15, 25),
        (False, 13, 25),
        (False, 15, 23),
        (True, 12, 24),
    )
    assert participating_indexes == [4, 0]


def test_seed_zero_generated_economic_shape_is_exact() -> None:
    case = generate_market_case(0)
    policy = case.buyer_policy

    assert policy.market_spec.requested_quantity == 13
    assert policy.reserve_unit_price.amount_paise == 24
    assert policy.max_total_payment.amount_paise == 312
    assert len(policy.eligible_merchants) == 5
    assert tuple(
        (
            attempt.signed_bid.bid.merchant_id,
            attempt.signed_bid.bid.bid_id,
            attempt.signed_bid.bid.quantity_available,
            attempt.signed_bid.bid.unit_price_paise,
        )
        for attempt in case.admission_attempts
    ) == (
        (
            "30000000-0005-4000-8000-000000000000",
            "40000000-0005-4000-8000-000000000000",
            12,
            24,
        ),
        (
            "30000000-0001-4000-8000-000000000000",
            "40000000-0001-4000-8000-000000000000",
            14,
            0,
        ),
    )


def test_seed_zero_public_keys_are_exact() -> None:
    case = generate_market_case(0)

    assert (
        tuple(identity.ed25519_public_key_hex for identity in case.buyer_policy.eligible_merchants)
        == _SEED_ZERO_PUBLIC_KEYS
    )


def test_seed_zero_identifiers_are_exact() -> None:
    case = generate_market_case(0)
    policy = case.buyer_policy

    assert policy.market_spec.market_id == "10000000-0000-4000-8000-000000000000"
    assert policy.market_spec.buyer_id == "20000000-0000-4000-8000-000000000000"
    assert tuple(identity.merchant_id for identity in policy.eligible_merchants) == tuple(
        f"30000000-{index:04x}-4000-8000-000000000000" for index in range(1, 6)
    )
    assert tuple(attempt.signed_bid.bid.bid_id for attempt in case.admission_attempts) == (
        "40000000-0005-4000-8000-000000000000",
        "40000000-0001-4000-8000-000000000000",
    )


def test_maximum_seed_identifiers_pass_domain_model_validation() -> None:
    case = generate_market_case(MAX_GENERATOR_SEED, MAX_SELLERS)

    assert case.seed == MAX_GENERATOR_SEED
    assert case.buyer_policy.market_spec.market_id.endswith("00007fffffff")
    assert case.buyer_policy.market_spec.buyer_id.endswith("00007fffffff")
    assert len(case.buyer_policy.eligible_merchants) == MAX_SELLERS


def test_all_development_seed_attempts_pass_real_lifecycle_admission() -> None:
    for seed in DEVELOPMENT_SEEDS:
        case = generate_market_case(seed)
        state = AdmissionState(case.buyer_policy)

        for attempt in case.admission_attempts:
            decision = admit_signed_bid(state, attempt.signed_bid, attempt.context)
            assert decision.rejection_code is None

        assert len(state.accepted_decisions) == len(case.admission_attempts)


@pytest.mark.parametrize("seed", [0, 1, 7, 15, 31])
def test_generated_policy_and_bid_invariants(seed: int) -> None:
    case = generate_market_case(seed)
    policy = case.buyer_policy
    requested_quantity = policy.market_spec.requested_quantity
    reserve = policy.reserve_unit_price.amount_paise
    quantity_neighborhood = {
        0,
        max(0, requested_quantity - 1),
        requested_quantity,
        requested_quantity + 1,
        requested_quantity + 2,
    }
    price_neighborhood = {0, max(0, reserve - 1), reserve, reserve + 1, reserve + 2}
    merchant_ids = tuple(identity.merchant_id for identity in policy.eligible_merchants)
    public_keys = tuple(identity.ed25519_public_key_hex for identity in policy.eligible_merchants)
    bid_ids = tuple(attempt.signed_bid.bid.bid_id for attempt in case.admission_attempts)
    commitment = buyer_policy_commitment(policy)

    assert len(policy.eligible_merchants) == 5
    assert 1 <= requested_quantity <= 20
    assert 0 <= reserve <= 25
    assert policy.max_total_payment.amount_paise == reserve * requested_quantity
    assert len(set(merchant_ids)) == len(merchant_ids)
    assert len(set(public_keys)) == len(public_keys)
    assert len(set(bid_ids)) == len(bid_ids)
    assert policy.bid_deadline == _DEADLINE

    for attempt in case.admission_attempts:
        bid = attempt.signed_bid.bid
        assert bid.market_id == policy.market_spec.market_id
        assert bid.merchant_id in merchant_ids
        assert bid.buyer_policy_commitment == commitment
        assert bid.submitted_at == _SUBMITTED_AT
        assert attempt.context.received_at == _RECEIVED_AT
        assert bid.quantity_available in quantity_neighborhood
        assert bid.unit_price_paise in price_neighborhood


def test_generated_models_expose_no_private_key_material_fields() -> None:
    assert set(GeneratedAdmissionAttempt.model_fields) == {"signed_bid", "context"}
    assert set(GeneratedMarketCase.model_fields) == {
        "generator_version",
        "seed",
        "buyer_policy",
        "admission_attempts",
    }
