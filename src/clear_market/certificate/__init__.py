from clear_market.certificate.builder import build_allocation_certificate
from clear_market.certificate.digests import (
    ALLOCATION_CERTIFICATE_DIGEST_VERSION,
    allocation_certificate_digest,
)
from clear_market.certificate.models import (
    ALLOCATION_CERTIFICATE_VERSION,
    AllocationCertificate,
)
from clear_market.certificate.parsing import (
    MAX_CANONICAL_CERTIFICATE_BYTES,
    AllocationCertificateParseError,
    AllocationCertificateParseFailureCode,
    parse_canonical_allocation_certificate,
)
from clear_market.certificate.serialization import canonical_allocation_certificate_bytes

# The architect-frozen public API order is protocol review evidence, not alphabetical order.
__all__ = (  # noqa: RUF022
    "ALLOCATION_CERTIFICATE_DIGEST_VERSION",
    "ALLOCATION_CERTIFICATE_VERSION",
    "AllocationCertificate",
    "AllocationCertificateParseError",
    "AllocationCertificateParseFailureCode",
    "MAX_CANONICAL_CERTIFICATE_BYTES",
    "allocation_certificate_digest",
    "build_allocation_certificate",
    "canonical_allocation_certificate_bytes",
    "parse_canonical_allocation_certificate",
)
