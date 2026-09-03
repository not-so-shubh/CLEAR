import argparse
import json
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from clear_market.certificate import (
    MAX_CANONICAL_CERTIFICATE_BYTES,
    AllocationCertificate,
    AllocationCertificateParseError,
    allocation_certificate_digest,
    parse_canonical_allocation_certificate,
)
from clear_market.certificate.v2 import (
    MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES,
    AllocationCertificateV2,
    AllocationCertificateV2ParseError,
    AllocationCertificateV2ParseFailureCode,
    allocation_certificate_v2_digest,
    parse_canonical_allocation_certificate_v2,
)
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.verification import verify_allocation_certificate
from clear_market.verification.v2 import verify_allocation_certificate_v2

_MAX_CERTIFICATE_BYTES = max(
    MAX_CANONICAL_CERTIFICATE_BYTES,
    MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES,
)


class _TrustConfigurationError(ValueError):
    pass


def _write_outcome(
    *,
    certificate_digest: str | None,
    failed_admission_index: int | None,
    parse_failure_code: str | None,
    status: str,
    verification_failure_code: str | None,
    verified: bool,
) -> None:
    payload: dict[str, object] = {
        "certificate_digest": certificate_digest,
        "failed_admission_index": failed_admission_index,
        "parse_failure_code": parse_failure_code,
        "status": status,
        "verification_failure_code": verification_failure_code,
        "verified": verified,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stdout.write(f"{serialized}\n")


def _write_parse_failure(code: str) -> int:
    _write_outcome(
        certificate_digest=None,
        failed_admission_index=None,
        parse_failure_code=code,
        status="parse_failed",
        verification_failure_code=None,
        verified=False,
    )
    return 3


def _write_configuration_failure(certificate_digest: str) -> int:
    _write_outcome(
        certificate_digest=certificate_digest,
        failed_admission_index=None,
        parse_failure_code=None,
        status="configuration_failed",
        verification_failure_code=None,
        verified=False,
    )
    return 5


def _parse_trusted_identities(
    values: Sequence[str],
) -> tuple[MerchantSigningIdentityV2, ...]:
    identities: list[MerchantSigningIdentityV2] = []
    for value in values:
        if value.count("=") != 1:
            raise _TrustConfigurationError
        merchant_id, public_key_hex = value.split("=", maxsplit=1)
        try:
            identity = MerchantSigningIdentityV2(
                merchant_id=merchant_id,
                ed25519_public_key_hex=public_key_hex,
            )
        except ValidationError:
            raise _TrustConfigurationError from None
        identities.append(identity)

    merchant_ids = tuple(identity.merchant_id for identity in identities)
    if len(set(merchant_ids)) != len(merchant_ids):
        raise _TrustConfigurationError
    return tuple(identities)


def _verify_v1_certificate(
    certificate: AllocationCertificate,
    *,
    trusted_identity_values: Sequence[str],
) -> int:
    digest = allocation_certificate_digest(certificate)
    if trusted_identity_values:
        return _write_configuration_failure(digest)

    result = verify_allocation_certificate(certificate)
    if result.verified:
        _write_outcome(
            certificate_digest=digest,
            failed_admission_index=None,
            parse_failure_code=None,
            status="verified",
            verification_failure_code=None,
            verified=True,
        )
        return 0

    _write_outcome(
        certificate_digest=digest,
        failed_admission_index=result.failed_admission_index,
        parse_failure_code=None,
        status="verification_failed",
        verification_failure_code=(
            result.failure_code.value if result.failure_code is not None else None
        ),
        verified=False,
    )
    return 1


def _verify_v2_certificate(
    certificate: AllocationCertificateV2,
    *,
    trusted_identity_values: Sequence[str],
) -> int:
    digest = allocation_certificate_v2_digest(certificate)
    try:
        trusted_identities = _parse_trusted_identities(trusted_identity_values)
    except _TrustConfigurationError:
        return _write_configuration_failure(digest)

    result = verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=trusted_identities,
    )
    if result.verified:
        _write_outcome(
            certificate_digest=digest,
            failed_admission_index=None,
            parse_failure_code=None,
            status="verified",
            verification_failure_code=None,
            verified=True,
        )
        return 0

    # The legacy CLI output key failed_admission_index carries the version-specific transcript
    # failure index; for V2 this is failed_evidence_index.
    _write_outcome(
        certificate_digest=digest,
        failed_admission_index=result.failed_evidence_index,
        parse_failure_code=None,
        status="verification_failed",
        verification_failure_code=(
            result.failure_code.value if result.failure_code is not None else None
        ),
        verified=False,
    )
    return 1


def _verify_file(path: str, *, trusted_identity_values: Sequence[str]) -> int:
    try:
        with open(path, "rb") as handle:
            data = handle.read(_MAX_CERTIFICATE_BYTES + 1)
    except OSError:
        _write_outcome(
            certificate_digest=None,
            failed_admission_index=None,
            parse_failure_code=None,
            status="io_failed",
            verification_failure_code=None,
            verified=False,
        )
        return 4

    try:
        v2_certificate = parse_canonical_allocation_certificate_v2(data)
    except AllocationCertificateV2ParseError as v2_error:
        if v2_error.code is not AllocationCertificateV2ParseFailureCode.INVALID_ENVELOPE:
            return _write_parse_failure(v2_error.code.value)
    else:
        return _verify_v2_certificate(
            v2_certificate,
            trusted_identity_values=trusted_identity_values,
        )

    try:
        v1_certificate = parse_canonical_allocation_certificate(data)
    except AllocationCertificateParseError as v1_error:
        return _write_parse_failure(v1_error.code.value)
    return _verify_v1_certificate(
        v1_certificate,
        trusted_identity_values=trusted_identity_values,
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clear")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("certificate_file")
    verify_parser.add_argument("--trusted-identity", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the thin canonical-certificate verification command."""
    arguments = _argument_parser().parse_args(argv)
    if arguments.command == "verify":
        return _verify_file(
            arguments.certificate_file,
            trusted_identity_values=arguments.trusted_identity,
        )
    raise AssertionError("argparse accepted an unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
