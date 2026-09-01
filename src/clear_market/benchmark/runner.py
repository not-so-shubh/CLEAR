import hashlib

from clear_market.benchmark.generator import generate_market_case
from clear_market.benchmark.report import (
    BENCHMARK_FINGERPRINT_VERSION,
    BENCHMARK_RUNNER_VERSION,
    BenchmarkHardFailureCode,
    BenchmarkReport,
)
from clear_market.benchmark.seeds import MARKET_GENERATOR_VERSION, MAX_GENERATOR_SEED
from clear_market.canonical import canonical_json_bytes
from clear_market.crypto import buyer_policy_commitment
from clear_market.domain import MAX_SELLERS, MIN_SELLERS, Money
from clear_market.lifecycle import AdmissionDecision, AdmissionState, admit_signed_bid
from clear_market.mechanism import Allocation, AllocationStatus, allocate_market
from clear_market.oracle import OracleAllocation, compute_oracle_allocation


def _allocations_match(production: Allocation, oracle: OracleAllocation) -> bool:
    """Compare every architect-frozen semantic result field explicitly."""
    return (
        production.schema_version == oracle.schema_version
        and production.market_id == oracle.market_id
        and production.buyer_policy_commitment_version == oracle.buyer_policy_commitment_version
        and production.buyer_policy_commitment == oracle.buyer_policy_commitment
        and production.mechanism_version == oracle.mechanism_version
        and production.status.value == oracle.status.value
        and production.winner_merchant_id == oracle.winner_merchant_id
        and production.winning_bid_id == oracle.winning_bid_id
        and production.allocated_quantity == oracle.allocated_quantity
        and production.winning_unit_price == oracle.winning_unit_price
        and production.payment_unit_price == oracle.payment_unit_price
        and production.total_payment == oracle.total_payment
    )


def _money_projection(money: Money | None) -> dict[str, object] | None:
    if money is None:
        return None
    return {
        "amount_paise": money.amount_paise,
        "currency": money.currency.value,
    }


def _allocation_projection(allocation: Allocation | OracleAllocation) -> dict[str, object]:
    return {
        "schema_version": allocation.schema_version,
        "market_id": allocation.market_id,
        "buyer_policy_commitment_version": allocation.buyer_policy_commitment_version,
        "buyer_policy_commitment": allocation.buyer_policy_commitment,
        "mechanism_version": allocation.mechanism_version,
        "status": allocation.status.value,
        "winner_merchant_id": allocation.winner_merchant_id,
        "winning_bid_id": allocation.winning_bid_id,
        "allocated_quantity": allocation.allocated_quantity,
        "winning_unit_price": _money_projection(allocation.winning_unit_price),
        "payment_unit_price": _money_projection(allocation.payment_unit_price),
        "total_payment": _money_projection(allocation.total_payment),
    }


def _seed_sequence_digest(seeds: tuple[int, ...]) -> str:
    encoded = canonical_json_bytes(
        {
            "fingerprint_version": BENCHMARK_FINGERPRINT_VERSION,
            "seed_sequence": list(seeds),
        }
    )
    return hashlib.sha256(encoded).hexdigest()


def _run_fingerprint(seller_count: int, records: list[dict[str, object]]) -> str:
    encoded = canonical_json_bytes(
        {
            "fingerprint_version": BENCHMARK_FINGERPRINT_VERSION,
            "runner_version": BENCHMARK_RUNNER_VERSION,
            "generator_version": MARKET_GENERATOR_VERSION,
            "seller_count": seller_count,
            "records": records,
        }
    )
    return hashlib.sha256(encoded).hexdigest()


def run_differential_benchmark(
    seeds: tuple[int, ...],
    seller_count: int = 5,
) -> BenchmarkReport:
    """Replay generated inputs and aggregate deterministic differential evidence."""
    if type(seeds) is not tuple:
        raise TypeError("seeds must be an exact tuple")
    if not seeds:
        raise ValueError("seeds must not be empty")
    for seed in seeds:
        if type(seed) is not int:
            raise TypeError("each seed must be an exact integer")
        if not 0 <= seed <= MAX_GENERATOR_SEED:
            raise ValueError("seed is outside the generator domain")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must not contain duplicates")
    if type(seller_count) is not int:
        raise TypeError("seller_count must be an exact integer")
    if not MIN_SELLERS <= seller_count <= MAX_SELLERS:
        raise ValueError("seller_count is outside the market domain")

    admission_attempt_count = 0
    admission_rejection_count = 0
    feasible_market_count = 0
    infeasible_market_count = 0
    differential_mismatch_count = 0
    budget_violation_count = 0
    allocation_quantity_violation_count = 0
    winner_evidence_violation_count = 0
    failed_seeds: list[int] = []
    records: list[dict[str, object]] = []

    for seed in seeds:
        case = generate_market_case(seed, seller_count=seller_count)
        state = AdmissionState(case.buyer_policy)
        decisions: list[AdmissionDecision] = []
        hard_failures: list[BenchmarkHardFailureCode] = []
        market_rejection_count = 0

        for attempt in case.admission_attempts:
            decision = admit_signed_bid(state, attempt.signed_bid, attempt.context)
            decisions.append(decision)
            admission_attempt_count += 1
            if decision.rejection_code is not None:
                admission_rejection_count += 1
                market_rejection_count += 1

        if market_rejection_count > 0:
            hard_failures.append(BenchmarkHardFailureCode.ADMISSION_REJECTION)

        production = allocate_market(state)
        oracle = compute_oracle_allocation(state)

        if not _allocations_match(production, oracle):
            differential_mismatch_count += 1
            hard_failures.append(BenchmarkHardFailureCode.DIFFERENTIAL_MISMATCH)

        if production.status is AllocationStatus.FEASIBLE:
            feasible_market_count += 1
            assert production.total_payment is not None
            assert production.allocated_quantity is not None
            assert production.winner_merchant_id is not None
            assert production.winning_bid_id is not None
            assert production.winning_unit_price is not None

            if (
                production.total_payment.amount_paise
                > case.buyer_policy.max_total_payment.amount_paise
            ):
                budget_violation_count += 1
                hard_failures.append(BenchmarkHardFailureCode.BUDGET_EXCEEDED)

            if production.allocated_quantity != case.buyer_policy.market_spec.requested_quantity:
                allocation_quantity_violation_count += 1
                hard_failures.append(BenchmarkHardFailureCode.ALLOCATION_QUANTITY_MISMATCH)

            matching_decisions = tuple(
                decision
                for decision in state.accepted_decisions
                if decision.signed_bid.bid.merchant_id == production.winner_merchant_id
                and decision.signed_bid.bid.bid_id == production.winning_bid_id
            )
            winner_evidence_matches = len(matching_decisions) == 1
            if winner_evidence_matches:
                winner_evidence_matches = (
                    matching_decisions[0].signed_bid.bid.unit_price_paise
                    == production.winning_unit_price.amount_paise
                )
            if not winner_evidence_matches:
                winner_evidence_violation_count += 1
                hard_failures.append(BenchmarkHardFailureCode.WINNER_EVIDENCE_MISMATCH)
        else:
            infeasible_market_count += 1

        if hard_failures:
            failed_seeds.append(seed)

        records.append(
            {
                "seed": case.seed,
                "market_id": case.buyer_policy.market_spec.market_id,
                "buyer_policy_commitment": buyer_policy_commitment(case.buyer_policy),
                "attempts": [
                    {
                        "bid_id": decision.signed_bid.bid.bid_id,
                        "merchant_id": decision.signed_bid.bid.merchant_id,
                        "quantity_available": decision.signed_bid.bid.quantity_available,
                        "unit_price_paise": decision.signed_bid.bid.unit_price_paise,
                        "signature_hex": decision.signed_bid.signature_hex,
                        "rejection_code": (
                            decision.rejection_code.value
                            if decision.rejection_code is not None
                            else None
                        ),
                    }
                    for decision in decisions
                ],
                "production": _allocation_projection(production),
                "oracle": _allocation_projection(oracle),
                "hard_failures": [failure.value for failure in hard_failures],
            }
        )

    hard_failure_count = (
        admission_rejection_count
        + differential_mismatch_count
        + budget_violation_count
        + allocation_quantity_violation_count
        + winner_evidence_violation_count
    )
    return BenchmarkReport(
        seller_count=seller_count,
        seed_count=len(seeds),
        seed_sequence_sha256=_seed_sequence_digest(seeds),
        admission_attempt_count=admission_attempt_count,
        admission_rejection_count=admission_rejection_count,
        feasible_market_count=feasible_market_count,
        infeasible_market_count=infeasible_market_count,
        differential_mismatch_count=differential_mismatch_count,
        budget_violation_count=budget_violation_count,
        allocation_quantity_violation_count=allocation_quantity_violation_count,
        winner_evidence_violation_count=winner_evidence_violation_count,
        hard_failure_count=hard_failure_count,
        failed_market_count=len(failed_seeds),
        failed_seeds=tuple(failed_seeds),
        reproducibility_fingerprint=_run_fingerprint(seller_count, records),
    )
