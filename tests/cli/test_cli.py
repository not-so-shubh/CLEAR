import json
import tomllib
from pathlib import Path

import pytest

from clear_market.certificate import (
    MAX_CANONICAL_CERTIFICATE_BYTES,
    AllocationCertificate,
    allocation_certificate_digest,
    canonical_allocation_certificate_bytes,
)
from clear_market.cli import main
from clear_market.domain import Money, SignedMerchantBid
from clear_market.lifecycle import AdmissionDecision
from clear_market.mechanism import Allocation, AllocationStatus
from tests.certificate.test_serialization import (
    _accepted_order_certificate,
    _golden_certificate,
)
from tests.verification.test_verifier import _one_accepted_certificate

_GOLDEN_STDOUT = (
    '{"certificate_digest":"53a6342dd1d719bea7b15dd4c5ae66a392cf2a862febc49a16f233ca632d1796",'
    '"failed_admission_index":null,"parse_failure_code":null,"status":"verified",'
    '"verification_failure_code":null,"verified":true}\n'
)
_OUTPUT_KEYS = {
    "certificate_digest",
    "failed_admission_index",
    "parse_failure_code",
    "status",
    "verification_failure_code",
    "verified",
}
_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def _write_certificate(path: Path, certificate: AllocationCertificate) -> None:
    path.write_bytes(canonical_allocation_certificate_bytes(certificate))


def _decoded_output(stdout: str) -> dict[str, object]:
    parsed = json.loads(stdout)
    assert type(parsed) is dict
    assert set(parsed) == _OUTPUT_KEYS
    return parsed


def _assert_no_content_leak(stdout: str, path: Path) -> None:
    for forbidden in (
        "market_id",
        "merchant_id",
        "buyer_id",
        "signature_hex",
        str(path),
    ):
        assert forbidden not in stdout


def _false_payment_certificate() -> AllocationCertificate:
    original = _accepted_order_certificate((0, 1))
    wrong_allocation = Allocation(
        market_id=original.allocation.market_id,
        buyer_policy_commitment=original.buyer_policy_commitment,
        mechanism_version=original.buyer_policy.mechanism_version,
        status=AllocationStatus.FEASIBLE,
        winner_merchant_id=original.allocation.winner_merchant_id,
        winning_bid_id=original.allocation.winning_bid_id,
        allocated_quantity=4,
        winning_unit_price=Money(amount_paise=100),
        payment_unit_price=Money(amount_paise=125),
        total_payment=Money(amount_paise=500),
    )
    return AllocationCertificate(
        certificate_id=original.certificate_id,
        buyer_policy=original.buyer_policy,
        buyer_policy_commitment=original.buyer_policy_commitment,
        admission_decisions=original.admission_decisions,
        allocation=wrong_allocation,
    )


def _tampered_signature_certificate() -> AllocationCertificate:
    original = _one_accepted_certificate()
    accepted = original.admission_decisions[0]
    tampered_signed_bid = SignedMerchantBid(
        bid=accepted.signed_bid.bid,
        signature_hex="0" * 128,
    )
    corrupted = AdmissionDecision(
        signed_bid=tampered_signed_bid,
        context=accepted.context,
        rejection_code=None,
    )
    return AllocationCertificate(
        certificate_id=original.certificate_id,
        buyer_policy=original.buyer_policy,
        buyer_policy_commitment=original.buyer_policy_commitment,
        admission_decisions=(corrupted,),
        allocation=original.allocation,
    )


def test_pyproject_exposes_exact_clear_console_script() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["scripts"]["clear"] == "clear_market.cli:main"


def test_golden_certificate_emits_exact_verified_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "golden.json"
    _write_certificate(path, _golden_certificate())

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == _GOLDEN_STDOUT
    assert captured.err == ""
    _assert_no_content_leak(captured.out, path)


def test_false_payment_returns_allocation_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = _false_payment_certificate()
    path = tmp_path / "false-payment.json"
    _write_certificate(path, certificate)

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert output == {
        "certificate_digest": allocation_certificate_digest(certificate),
        "failed_admission_index": None,
        "parse_failure_code": None,
        "status": "verification_failed",
        "verification_failure_code": "allocation_mismatch",
        "verified": False,
    }
    digest = output["certificate_digest"]
    assert type(digest) is str
    assert len(digest) == 64
    assert all(character in _LOWERCASE_HEX_DIGITS for character in digest)
    _assert_no_content_leak(captured.out, path)


def test_tampered_signature_preserves_transcript_failure_index(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = _tampered_signature_certificate()
    path = tmp_path / "tampered-signature.json"
    _write_certificate(path, certificate)

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert output == {
        "certificate_digest": allocation_certificate_digest(certificate),
        "failed_admission_index": 0,
        "parse_failure_code": None,
        "status": "verification_failed",
        "verification_failure_code": "transcript_replay_mismatch",
        "verified": False,
    }
    _assert_no_content_leak(captured.out, path)


@pytest.mark.parametrize(
    ("name", "data", "failure_code"),
    [
        (
            "noncanonical.json",
            canonical_allocation_certificate_bytes(_golden_certificate()) + b"\n",
            "non_canonical",
        ),
        ("malformed.json", b"{", "invalid_json"),
        ("invalid-utf8.json", b"\xff", "invalid_utf8"),
        (
            "oversized.json",
            b"x" * (MAX_CANONICAL_CERTIFICATE_BYTES + 1),
            "input_too_large",
        ),
        (
            "bounded-read.json",
            b"x" * (MAX_CANONICAL_CERTIFICATE_BYTES + 100),
            "input_too_large",
        ),
    ],
)
def test_parse_failures_emit_stable_json(
    name: str,
    data: bytes,
    failure_code: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / name
    path.write_bytes(data)

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 3
    assert captured.err == ""
    assert output == {
        "certificate_digest": None,
        "failed_admission_index": None,
        "parse_failure_code": failure_code,
        "status": "parse_failed",
        "verification_failure_code": None,
        "verified": False,
    }
    _assert_no_content_leak(captured.out, path)


def test_nonexistent_path_returns_stable_io_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "missing.json"

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 4
    assert captured.err == ""
    assert captured.out == (
        '{"certificate_digest":null,"failed_admission_index":null,'
        '"parse_failure_code":null,"status":"io_failed",'
        '"verification_failure_code":null,"verified":false}\n'
    )
    _assert_no_content_leak(captured.out, path)


def test_directory_path_returns_stable_io_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["verify", str(tmp_path)])
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 4
    assert captured.err == ""
    assert output == {
        "certificate_digest": None,
        "failed_admission_index": None,
        "parse_failure_code": None,
        "status": "io_failed",
        "verification_failure_code": None,
        "verified": False,
    }
    _assert_no_content_leak(captured.out, tmp_path)


def test_output_is_deterministic_for_repeated_verification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "golden.json"
    _write_certificate(path, _golden_certificate())

    first_code = main(["verify", str(path)])
    first = capsys.readouterr()
    second_code = main(["verify", str(path)])
    second = capsys.readouterr()

    assert first_code == second_code == 0
    assert first.out == second.out == _GOLDEN_STDOUT
    assert first.err == second.err == ""


@pytest.mark.parametrize("argv", [[], ["verify"], ["unknown"]])
def test_argparse_usage_errors_remain_exit_code_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == 2
