import hashlib
from typing import Final

from clear_market.certificate.models import AllocationCertificate
from clear_market.certificate.serialization import canonical_allocation_certificate_bytes

ALLOCATION_CERTIFICATE_DIGEST_VERSION: Final[str] = "sha256-allocation-certificate-clear-json-v1"


def allocation_certificate_digest(certificate: AllocationCertificate) -> str:
    """Identify the exact canonical certificate bytes with an unsalted SHA-256 digest."""
    return hashlib.sha256(canonical_allocation_certificate_bytes(certificate)).hexdigest()
