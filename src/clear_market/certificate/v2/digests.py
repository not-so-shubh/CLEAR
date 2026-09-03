import hashlib
from typing import Final

from clear_market.certificate.v2.models import AllocationCertificateV2
from clear_market.certificate.v2.serialization import canonical_allocation_certificate_v2_bytes

ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION: Final[str] = (
    "sha256-allocation-certificate-v2-clear-json-v1"
)


def allocation_certificate_v2_digest(certificate: AllocationCertificateV2) -> str:
    """Identify exact canonical certificate bytes; this digest is not authentication."""
    if type(certificate) is not AllocationCertificateV2:
        raise TypeError("certificate must be exactly an AllocationCertificateV2")
    return hashlib.sha256(canonical_allocation_certificate_v2_bytes(certificate)).hexdigest()
