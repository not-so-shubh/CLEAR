import argparse
import json
import sys
from collections.abc import Sequence

from clear_market.certificate import (
    MAX_CANONICAL_CERTIFICATE_BYTES,
    AllocationCertificateParseError,
    allocation_certificate_digest,
    parse_canonical_allocation_certificate,
)
from clear_market.verification import verify_allocation_certificate


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


def _verify_file(path: str) -> int:
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_CANONICAL_CERTIFICATE_BYTES + 1)
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
        certificate = parse_canonical_allocation_certificate(data)
    except AllocationCertificateParseError as error:
        _write_outcome(
            certificate_digest=None,
            failed_admission_index=None,
            parse_failure_code=error.code.value,
            status="parse_failed",
            verification_failure_code=None,
            verified=False,
        )
        return 3

    digest = allocation_certificate_digest(certificate)
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


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clear")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("certificate_file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the thin canonical-certificate verification command."""
    arguments = _argument_parser().parse_args(argv)
    if arguments.command == "verify":
        return _verify_file(arguments.certificate_file)
    raise AssertionError("argparse accepted an unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
