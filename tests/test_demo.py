import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import clear_market.ai.buyer_intent as buyer_intent_module
import clear_market.demo as demo_module
import clear_market.payments.razorpay.orders as orders_module
from clear_market.demo import run_demo_v1

_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_LABELS = {
    "buyer_ai": "HISTORICAL LIVE EVIDENCE ONLY",
    "buyer_candidate_and_context": "DETERMINISTIC FIXTURE",
    "buyer_policy_freeze": "REAL LOCAL PRODUCTION LOGIC",
    "merchant_ai": "NOT DEMONSTRATED",
    "merchant_catalog_inventory_policy_candidates": "DETERMINISTIC FIXTURE",
    "merchant_offer_build_sign_authenticate": "REAL LOCAL PRODUCTION LOGIC",
    "merchant_receipt_and_admission": "DETERMINISTIC FIXTURE",
    "allocation": "REAL LOCAL PRODUCTION LOGIC",
    "certificate_construction": "REAL LOCAL PRODUCTION LOGIC",
    "certificate_verification": "REAL LOCAL PRODUCTION LOGIC",
    "financial_and_recipient_authorizations": "DETERMINISTIC FIXTURE",
    "decision_time": "DETERMINISTIC FIXTURE",
    "financial_ledger": "REAL LOCAL PRODUCTION LOGIC",
    "money_governor": "REAL LOCAL PRODUCTION LOGIC",
    "razorpay_order_adapter": "REAL LOCAL PRODUCTION LOGIC",
    "razorpay_provider_transport": "FAKE/CONTROLLED EXTERNAL TRANSPORT",
    "razorpay_live_test_mode": "NOT DEMONSTRATED",
    "merchant_ai_live": "NOT DEMONSTRATED",
    "certificate_explanation_ai_live": "NOT DEMONSTRATED",
}
_EXPECTED_LIMITATIONS = {
    "live Razorpay Test Mode execution": "NOT DEMONSTRATED",
    "payment capture": "NOT DEMONSTRATED",
    "transfer creation/settlement in this demo": "NOT DEMONSTRATED",
    "settlement": "NOT DEMONSTRATED",
    "refunds/reversals": "NOT DEMONSTRATED",
    "physical fulfillment": "NOT DEMONSTRATED",
    "transcript completeness": "NOT DEMONSTRATED",
    "exactly-once external delivery": "NOT DEMONSTRATED",
    "server-attested decision time": "NOT DEMONSTRATED",
    "live merchant AI": "NOT DEMONSTRATED",
    "live certificate explanation AI": "NOT DEMONSTRATED",
    "remaining hostile/full-system audit": "NOT DEMONSTRATED / STILL REQUIRED",
}


def _run_subprocess() -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "clear_market.demo"],
        cwd=_ROOT,
        capture_output=True,
        check=False,
    )


def _assert_output(output: bytes) -> dict[str, Any]:
    parsed = json.loads(output)
    assert isinstance(parsed, dict)
    assert parsed["demo_version"] == "clear-demo-v1"
    assert parsed["invariant"] == "NO VALID CERTIFICATE = NO MONEY ACTION"
    return parsed


def test_entrypoint_emits_one_json_object() -> None:
    completed = _run_subprocess()
    assert completed.returncode == 0, completed.stderr.decode()
    _assert_output(completed.stdout)


def test_entrypoint_stdout_is_byte_identical_across_runs() -> None:
    first = _run_subprocess()
    second = _run_subprocess()
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout


def test_valid_path_is_split_multiwinner_and_governor_gated() -> None:
    result = run_demo_v1()
    valid = result["valid_path"]
    assert isinstance(valid, dict)
    assert valid["allocation_status"] == "FEASIBLE"
    assert valid["fulfilled_quantity"] == valid["requested_quantity"] == 5
    assert valid["winner_count"] == 2
    assert len(valid["winner_merchant_ids"]) == 2
    assert valid["certificate_verified"] is True
    assert valid["execution_reserved"] is True
    assert valid["first_order_resolution"] == "CREATED"
    assert valid["second_order_resolution"] == "EXISTING"
    assert valid["provider_post_count"] == 1
    assert valid["provider_get_count"] == 1
    assert "plan" not in valid


def test_fixture_timeline_is_causally_coherent() -> None:
    policy, _signed_offers, certificate = demo_module._certificate_fixture()
    evidence = certificate.merchant_offer_evidence
    source_times = tuple(
        timestamp
        for item in evidence
        for timestamp in (item.catalog.generated_at, item.inventory.captured_at)
    )
    receipt_times = tuple(item.received_at for item in evidence)

    assert source_times
    assert receipt_times
    assert all(source <= receipt for source in source_times for receipt in receipt_times)
    assert all(received <= policy.offer_deadline for received in receipt_times)
    assert policy.offer_deadline < demo_module._DECISION_TIME


def test_tamper_path_fails_closed_before_provider_action() -> None:
    tamper = run_demo_v1()["tamper_path"]
    assert tamper == {
        "certificate_verification_expected": False,
        "governor_failure_code": "CERTIFICATE_NOT_VERIFIED",
        "execution_reserved": False,
        "order_idempotency_record_present": False,
        "provider_post_count": 0,
        "provider_get_count": 0,
    }


def test_truth_labels_and_limitations_are_exact() -> None:
    result = run_demo_v1()
    assert result["truth_labels"] == _EXPECTED_LABELS
    assert result["limitations"] == _EXPECTED_LIMITATIONS


def test_controlled_transport_has_no_https_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(**_kwargs: object) -> tuple[int, bytes]:
        raise AssertionError("default HTTPS transport was called")

    monkeypatch.setattr(orders_module, "_https_request", fail_if_called)
    assert run_demo_v1()["valid_path"]["provider_get_count"] == 1


def test_demo_does_not_invoke_ai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("AI provider was called")

    monkeypatch.setattr(buyer_intent_module, "invoke_ai_provider_v1", fail_if_called)
    assert run_demo_v1()["valid_path"]["buyer_policy_frozen"] is True


def test_serialized_output_contains_no_secret_material() -> None:
    serialized = json.dumps(run_demo_v1(), sort_keys=True)
    for forbidden in ("rzp_test_", "key_secret", "private_key", "signature_hex"):
        assert forbidden not in serialized


def test_demo_source_has_no_authority_shortcuts() -> None:
    source_path = _ROOT / "src" / "clear_market" / "demo.py"
    tree = ast.parse(source_path.read_text())
    forbidden_calls = {"AllocationV2", "ExecutionPlanV1", "model_construct", "_https_request"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        assert name not in forbidden_calls
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith(("tests", "benchmarks"))
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith(("tests", "benchmarks")) for alias in node.names)
