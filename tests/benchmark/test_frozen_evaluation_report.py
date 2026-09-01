import hashlib
import json
from pathlib import Path

from clear_market.benchmark import (
    BENCHMARK_FINGERPRINT_VERSION,
    BENCHMARK_RUNNER_VERSION,
    FROZEN_EVALUATION_SEEDS,
    MARKET_GENERATOR_VERSION,
    BenchmarkReport,
)
from clear_market.canonical import canonical_json_bytes

_ARTIFACT_PATH = Path("benchmarks/frozen_evaluation_report_v1.json")

_EXPECTED_KEYS = {
    "schema_version",
    "runner_version",
    "generator_version",
    "fingerprint_version",
    "seller_count",
    "seed_count",
    "seed_sequence_sha256",
    "admission_attempt_count",
    "admission_rejection_count",
    "feasible_market_count",
    "infeasible_market_count",
    "differential_mismatch_count",
    "budget_violation_count",
    "allocation_quantity_violation_count",
    "winner_evidence_violation_count",
    "hard_failure_count",
    "failed_market_count",
    "failed_seeds",
    "reproducibility_fingerprint",
}

_EXPECTED_FROZEN_REPORT = {
    "admission_attempt_count": 24_990,
    "admission_rejection_count": 0,
    "allocation_quantity_violation_count": 0,
    "budget_violation_count": 0,
    "differential_mismatch_count": 0,
    "failed_market_count": 0,
    "failed_seeds": [],
    "feasible_market_count": 6_271,
    "fingerprint_version": "sha256-clear-benchmark-records-v1",
    "generator_version": "deterministic-market-generator-v1",
    "hard_failure_count": 0,
    "infeasible_market_count": 3_729,
    "reproducibility_fingerprint": (
        "89cb65d3accaba76d90a1c6091503480ab6c3edeabf8e863613e86c9d2703867"
    ),
    "runner_version": "differential-benchmark-runner-v1",
    "schema_version": "1",
    "seed_count": 10_000,
    "seed_sequence_sha256": ("75e00e23b222fe03242ac7d115909c0a12abc50ba10844337ec9d0ea4dd507f2"),
    "seller_count": 5,
    "winner_evidence_violation_count": 0,
}


def _read_artifact() -> tuple[str, dict[str, object]]:
    text = _ARTIFACT_PATH.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")

    parsed = json.loads(text)
    assert type(parsed) is dict
    return text, parsed


def test_frozen_evaluation_report_is_exact() -> None:
    _, parsed = _read_artifact()

    assert set(parsed) == _EXPECTED_KEYS
    assert parsed == _EXPECTED_FROZEN_REPORT


def test_frozen_evaluation_report_validates_protocol_and_outcome() -> None:
    _, parsed = _read_artifact()
    report = BenchmarkReport.model_validate(parsed)

    assert report.schema_version == "1"
    assert report.runner_version == BENCHMARK_RUNNER_VERSION
    assert report.generator_version == MARKET_GENERATOR_VERSION
    assert report.fingerprint_version == BENCHMARK_FINGERPRINT_VERSION
    assert report.seller_count == 5
    assert report.seed_count == 10_000

    assert report.admission_rejection_count == 0
    assert report.differential_mismatch_count == 0
    assert report.budget_violation_count == 0
    assert report.allocation_quantity_violation_count == 0
    assert report.winner_evidence_violation_count == 0
    assert report.hard_failure_count == 0
    assert report.failed_market_count == 0
    assert report.failed_seeds == ()
    assert report.feasible_market_count + report.infeasible_market_count == 10_000


def test_frozen_evaluation_report_binds_exact_seed_sequence() -> None:
    _, parsed = _read_artifact()
    report = BenchmarkReport.model_validate(parsed)
    expected_seed_sequence_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                "fingerprint_version": BENCHMARK_FINGERPRINT_VERSION,
                "seed_sequence": list(FROZEN_EVALUATION_SEEDS),
            }
        )
    ).hexdigest()

    assert report.seed_sequence_sha256 == expected_seed_sequence_sha256


def test_frozen_evaluation_report_uses_compact_sorted_json() -> None:
    _, parsed = _read_artifact()
    expected_bytes = (
        json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    assert _ARTIFACT_PATH.read_bytes() == expected_bytes
