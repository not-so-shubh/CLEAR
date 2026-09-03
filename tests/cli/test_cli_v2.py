import json
from pathlib import Path

import pytest

from clear_market.certificate import (
    allocation_certificate_digest,
    canonical_allocation_certificate_bytes,
)
from clear_market.certificate.v2 import (
    MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES,
    MerchantOfferAdmissionDecisionV2,
    allocation_certificate_v2_digest,
    canonical_allocation_certificate_v2_bytes,
)
from clear_market.cli import main
from tests.certificate.test_serialization import _golden_certificate
from tests.certificate.v2.test_serialization import (
    _certificate,
    _identity,
    _offer_id,
    _validated_copy,
)

_V1_DIGEST = "53a6342dd1d719bea7b15dd4c5ae66a392cf2a862febc49a16f233ca632d1796"
_V2_DIGEST = "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
_OUTPUT_KEYS = {
    "certificate_digest",
    "failed_admission_index",
    "parse_failure_code",
    "status",
    "verification_failure_code",
    "verified",
}
_V1_VERIFIED_STDOUT = (
    '{"certificate_digest":"53a6342dd1d719bea7b15dd4c5ae66a392cf2a862febc49a16f233ca632d1796",'
    '"failed_admission_index":null,"parse_failure_code":null,"status":"verified",'
    '"verification_failure_code":null,"verified":true}\n'
)
_V2_VERIFIED_STDOUT = (
    '{"certificate_digest":"1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353",'
    '"failed_admission_index":null,"parse_failure_code":null,"status":"verified",'
    '"verification_failure_code":null,"verified":true}\n'
)
_V2_NO_TRUST_STDOUT = (
    '{"certificate_digest":"1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353",'
    '"failed_admission_index":0,"parse_failure_code":null,'
    '"status":"verification_failed",'
    '"verification_failure_code":"TRANSCRIPT_REPLAY_MISMATCH","verified":false}\n'
)
_V2_CONFIGURATION_FAILED_STDOUT = (
    '{"certificate_digest":"1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353",'
    '"failed_admission_index":null,"parse_failure_code":null,'
    '"status":"configuration_failed","verification_failure_code":null,'
    '"verified":false}\n'
)


def _write_v2(path: Path) -> None:
    data = canonical_allocation_certificate_v2_bytes(_certificate())
    assert len(data) == 14_454
    assert allocation_certificate_v2_digest(_certificate()) == _V2_DIGEST
    path.write_bytes(data)


def _trusted_identity_argument(index: int) -> str:
    identity = _identity(index)
    return f"{identity.merchant_id}={identity.ed25519_public_key_hex}"


def _decoded_output(stdout: str) -> dict[str, object]:
    parsed = json.loads(stdout)
    assert type(parsed) is dict
    assert set(parsed) == _OUTPUT_KEYS
    return parsed


def _assert_no_sensitive_output(stdout: str, path: Path, *values: str) -> None:
    assert str(path) not in stdout
    assert "merchant_id" not in stdout
    assert "public_key" not in stdout
    for value in values:
        assert value not in stdout


def test_v2_golden_verifies_with_explicit_external_trust(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = _certificate()
    assert certificate.merchant_offer_evidence[2].admission_decision is (
        MerchantOfferAdmissionDecisionV2.REJECTED
    )
    assert certificate.merchant_offer_evidence[2].signed_offer.offer.offer_id == _offer_id(3)
    assert (
        certificate.merchant_offer_evidence[2].signed_offer.offer.lines[0].unit_price.amount_paise
        == 1
    )
    path = tmp_path / "certificate-v2.json"
    _write_v2(path)
    trust = (_trusted_identity_argument(1), _trusted_identity_argument(2))

    exit_code = main(
        [
            "verify",
            str(path),
            "--trusted-identity",
            trust[0],
            "--trusted-identity",
            trust[1],
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == _V2_VERIFIED_STDOUT
    assert captured.err == ""
    _assert_no_sensitive_output(captured.out, path, *trust)


def test_v2_trust_argument_order_is_semantically_irrelevant(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "certificate-v2.json"
    _write_v2(path)
    first = _trusted_identity_argument(1)
    second = _trusted_identity_argument(2)

    first_code = main(
        ["verify", str(path), "--trusted-identity", first, "--trusted-identity", second]
    )
    first_output = capsys.readouterr()
    second_code = main(
        ["verify", str(path), "--trusted-identity", second, "--trusted-identity", first]
    )
    second_output = capsys.readouterr()

    assert first_code == second_code == 0
    assert first_output.out == second_output.out == _V2_VERIFIED_STDOUT
    assert first_output.err == second_output.err == ""


def test_empty_v2_trust_is_valid_configuration_but_cannot_authenticate_embedded_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "certificate-v2.json"
    _write_v2(path)

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == _V2_NO_TRUST_STDOUT
    assert captured.err == ""
    _assert_no_sensitive_output(captured.out, path)


def test_altered_external_v2_trust_causes_transcript_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "certificate-v2.json"
    _write_v2(path)
    merchant_one = _identity(1)
    altered = f"{merchant_one.merchant_id}={_identity(2).ed25519_public_key_hex}"

    exit_code = main(
        [
            "verify",
            str(path),
            "--trusted-identity",
            altered,
            "--trusted-identity",
            _trusted_identity_argument(2),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == _V2_NO_TRUST_STDOUT
    assert captured.err == ""
    _assert_no_sensitive_output(captured.out, path, altered)


def _invalid_trust_arguments() -> tuple[tuple[str, ...], ...]:
    identity = _identity(1)
    valid = _trusted_identity_argument(1)
    return (
        ("missing-equals",),
        (f"={identity.ed25519_public_key_hex}",),
        (f"{identity.merchant_id}=",),
        (f"{identity.merchant_id.upper()}={identity.ed25519_public_key_hex}",),
        (f"not-a-uuid={identity.ed25519_public_key_hex}",),
        (f"{identity.merchant_id}={identity.ed25519_public_key_hex.upper()}",),
        (f"{identity.merchant_id}={'0' * 62}",),
        (f"{identity.merchant_id}={'g' * 64}",),
        (valid, valid),
    )


@pytest.mark.parametrize("trust_values", _invalid_trust_arguments())
def test_invalid_v2_trust_configuration_returns_exit_five_without_leak(
    trust_values: tuple[str, ...],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "certificate-v2.json"
    _write_v2(path)
    argv = ["verify", str(path)]
    for value in trust_values:
        argv.extend(("--trusted-identity", value))

    exit_code = main(argv)
    captured = capsys.readouterr()

    assert exit_code == 5
    assert captured.out == _V2_CONFIGURATION_FAILED_STDOUT
    assert captured.err == ""
    _assert_no_sensitive_output(captured.out, path, *trust_values)


def test_v1_with_trust_argument_is_configuration_failure_after_v1_dispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = _golden_certificate()
    path = tmp_path / "certificate-v1.json"
    path.write_bytes(canonical_allocation_certificate_bytes(certificate))
    trust = _trusted_identity_argument(1)

    exit_code = main(["verify", str(path), "--trusted-identity", trust])
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 5
    assert captured.err == ""
    assert output == {
        "certificate_digest": allocation_certificate_digest(certificate),
        "failed_admission_index": None,
        "parse_failure_code": None,
        "status": "configuration_failed",
        "verification_failure_code": None,
        "verified": False,
    }
    assert output["certificate_digest"] == _V1_DIGEST
    _assert_no_sensitive_output(captured.out, path, trust)


def test_valid_v1_falls_back_from_v2_envelope_check_and_preserves_exact_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "certificate-v1.json"
    path.write_bytes(canonical_allocation_certificate_bytes(_golden_certificate()))

    exit_code = main(["verify", str(path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == _V1_VERIFIED_STDOUT
    assert captured.err == ""


@pytest.mark.parametrize(
    ("name", "data", "failure_code"),
    [
        (
            "noncanonical-v2.json",
            canonical_allocation_certificate_v2_bytes(_certificate()) + b"\n",
            "non_canonical",
        ),
        ("malformed-v2.json", b'{"canonicalization_version":', "invalid_json"),
        (
            "invalid-certificate-v2.json",
            b'{"canonicalization_version":"clear-json-v1","payload":{},'
            b'"payload_type":"allocation_certificate_v2"}',
            "invalid_certificate",
        ),
        (
            "oversized-v2.json",
            b"x" * (MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES + 1),
            "input_too_large",
        ),
    ],
)
def test_v2_non_envelope_parse_failures_do_not_fall_back_to_v1(
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

    assert exit_code == 3
    assert captured.err == ""
    assert _decoded_output(captured.out) == {
        "certificate_digest": None,
        "failed_admission_index": None,
        "parse_failure_code": failure_code,
        "status": "parse_failed",
        "verification_failure_code": None,
        "verified": False,
    }
    _assert_no_sensitive_output(captured.out, path)


def test_parse_failure_precedes_unusable_trust_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "malformed-v2.json"
    path.write_bytes(b'{"canonicalization_version":')

    exit_code = main(["verify", str(path), "--trusted-identity", "not-valid"])
    captured = capsys.readouterr()

    assert exit_code == 3
    assert _decoded_output(captured.out)["parse_failure_code"] == "invalid_json"
    assert captured.err == ""


def test_false_stored_v2_admission_maps_evidence_index_to_legacy_output_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = _certificate()
    first = _validated_copy(
        certificate.merchant_offer_evidence[0],
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    false_certificate = _validated_copy(
        certificate,
        merchant_offer_evidence=(first, *certificate.merchant_offer_evidence[1:]),
    )
    path = tmp_path / "false-admission-v2.json"
    path.write_bytes(canonical_allocation_certificate_v2_bytes(false_certificate))

    exit_code = main(
        [
            "verify",
            str(path),
            "--trusted-identity",
            _trusted_identity_argument(1),
            "--trusted-identity",
            _trusted_identity_argument(2),
        ]
    )
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert output == {
        "certificate_digest": allocation_certificate_v2_digest(false_certificate),
        "failed_admission_index": 0,
        "parse_failure_code": None,
        "status": "verification_failed",
        "verification_failure_code": "TRANSCRIPT_REPLAY_MISMATCH",
        "verified": False,
    }


def test_false_v2_allocation_returns_uppercase_allocation_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = _certificate()
    false_allocation = _validated_copy(
        certificate.allocation,
        soft_preference_unit_score=1,
    )
    false_certificate = _validated_copy(certificate, allocation=false_allocation)
    path = tmp_path / "false-allocation-v2.json"
    path.write_bytes(canonical_allocation_certificate_v2_bytes(false_certificate))

    exit_code = main(
        [
            "verify",
            str(path),
            "--trusted-identity",
            _trusted_identity_argument(1),
            "--trusted-identity",
            _trusted_identity_argument(2),
        ]
    )
    captured = capsys.readouterr()
    output = _decoded_output(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert output == {
        "certificate_digest": allocation_certificate_v2_digest(false_certificate),
        "failed_admission_index": None,
        "parse_failure_code": None,
        "status": "verification_failed",
        "verification_failure_code": "ALLOCATION_MISMATCH",
        "verified": False,
    }
