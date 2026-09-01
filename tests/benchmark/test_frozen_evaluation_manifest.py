import hashlib
import json
from pathlib import Path

from clear_market.benchmark import (
    BENCHMARK_FINGERPRINT_VERSION,
    BENCHMARK_RUNNER_VERSION,
    MARKET_GENERATOR_VERSION,
    BenchmarkReport,
)

_MANIFEST_PATH = Path("benchmarks/frozen_evaluation_manifest_v1.json")
_REPORT_PATH = Path("benchmarks/frozen_evaluation_report_v1.json")

_EXPECTED_EVALUATED_SOURCE_COMMIT = "67f1f6f772e52d9207a6555e403a9edb53e7bf63"
_EXPECTED_EVIDENCE_FREEZE_COMMIT = "97e1113520f08b645885e3e6aa46d72eab5caaab"
_EXPECTED_REPORT_SHA256 = "d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe"

_EXPECTED_KEYS = {
    "schema_version",
    "evaluated_source_commit",
    "evidence_freeze_commit",
    "report_path",
    "report_sha256",
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

_EXPECTED_FROZEN_MANIFEST = {
    "admission_attempt_count": 24_990,
    "admission_rejection_count": 0,
    "allocation_quantity_violation_count": 0,
    "budget_violation_count": 0,
    "differential_mismatch_count": 0,
    "evaluated_source_commit": _EXPECTED_EVALUATED_SOURCE_COMMIT,
    "evidence_freeze_commit": _EXPECTED_EVIDENCE_FREEZE_COMMIT,
    "failed_market_count": 0,
    "failed_seeds": [],
    "feasible_market_count": 6_271,
    "fingerprint_version": "sha256-clear-benchmark-records-v1",
    "generator_version": "deterministic-market-generator-v1",
    "hard_failure_count": 0,
    "infeasible_market_count": 3_729,
    "report_path": "benchmarks/frozen_evaluation_report_v1.json",
    "report_sha256": _EXPECTED_REPORT_SHA256,
    "reproducibility_fingerprint": (
        "89cb65d3accaba76d90a1c6091503480ab6c3edeabf8e863613e86c9d2703867"
    ),
    "runner_version": "differential-benchmark-runner-v1",
    "schema_version": "1",
    "seed_count": 10_000,
    "seed_sequence_sha256": "75e00e23b222fe03242ac7d115909c0a12abc50ba10844337ec9d0ea4dd507f2",
    "seller_count": 5,
    "winner_evidence_violation_count": 0,
}


def _read_manifest() -> tuple[bytes, dict[str, object]]:
    data = _MANIFEST_PATH.read_bytes()
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n")

    parsed = json.loads(data)
    assert type(parsed) is dict
    return data, parsed


def test_frozen_evaluation_manifest_is_exact_compact_sorted_json() -> None:
    data, manifest = _read_manifest()
    expected_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    assert len(_EXPECTED_KEYS) == 23
    assert set(manifest) == _EXPECTED_KEYS
    assert manifest == _EXPECTED_FROZEN_MANIFEST
    assert data == expected_bytes


def test_manifest_freezes_source_revisions_and_report_digest() -> None:
    _, manifest = _read_manifest()
    for field, expected in (
        ("evaluated_source_commit", _EXPECTED_EVALUATED_SOURCE_COMMIT),
        ("evidence_freeze_commit", _EXPECTED_EVIDENCE_FREEZE_COMMIT),
    ):
        value = manifest[field]
        assert value == expected
        assert type(value) is str
        assert len(value) == 40
        assert value == value.lower()
        assert all(character in "0123456789abcdef" for character in value)

    actual_report_sha256 = hashlib.sha256(_REPORT_PATH.read_bytes()).hexdigest()
    assert actual_report_sha256 == _EXPECTED_REPORT_SHA256
    assert manifest["report_path"] == str(_REPORT_PATH)
    assert manifest["report_sha256"] == actual_report_sha256


def test_manifest_metadata_matches_typed_frozen_report() -> None:
    _, manifest = _read_manifest()
    report = BenchmarkReport.model_validate(json.loads(_REPORT_PATH.read_bytes()))

    assert manifest["schema_version"] == report.schema_version == "1"
    assert manifest["runner_version"] == report.runner_version == BENCHMARK_RUNNER_VERSION
    assert manifest["generator_version"] == report.generator_version == MARKET_GENERATOR_VERSION
    assert (
        manifest["fingerprint_version"]
        == report.fingerprint_version
        == BENCHMARK_FINGERPRINT_VERSION
    )
    assert manifest["seller_count"] == report.seller_count
    assert manifest["seed_count"] == report.seed_count
    assert manifest["seed_sequence_sha256"] == report.seed_sequence_sha256
    assert manifest["admission_attempt_count"] == report.admission_attempt_count
    assert manifest["admission_rejection_count"] == report.admission_rejection_count
    assert manifest["feasible_market_count"] == report.feasible_market_count
    assert manifest["infeasible_market_count"] == report.infeasible_market_count
    assert manifest["differential_mismatch_count"] == report.differential_mismatch_count
    assert manifest["budget_violation_count"] == report.budget_violation_count
    assert (
        manifest["allocation_quantity_violation_count"]
        == report.allocation_quantity_violation_count
    )
    assert manifest["winner_evidence_violation_count"] == report.winner_evidence_violation_count
    assert manifest["hard_failure_count"] == report.hard_failure_count
    assert manifest["failed_market_count"] == report.failed_market_count
    assert manifest["failed_seeds"] == []
    assert report.failed_seeds == ()
    assert manifest["reproducibility_fingerprint"] == report.reproducibility_fingerprint


def test_manifest_freezes_zero_failures_and_market_accounting() -> None:
    _, manifest = _read_manifest()

    assert manifest["admission_rejection_count"] == 0
    assert manifest["differential_mismatch_count"] == 0
    assert manifest["budget_violation_count"] == 0
    assert manifest["allocation_quantity_violation_count"] == 0
    assert manifest["winner_evidence_violation_count"] == 0
    assert manifest["hard_failure_count"] == 0
    assert manifest["failed_market_count"] == 0
    assert manifest["failed_seeds"] == []
    assert (
        manifest["feasible_market_count"] + manifest["infeasible_market_count"]
        == manifest["seed_count"]
        == 10_000
    )
