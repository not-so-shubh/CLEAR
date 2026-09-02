import hashlib
import json
from collections.abc import Callable

import pytest

from clear_market.commerce import (
    SignedMerchantOfferV2,
    canonical_merchant_offer_v2_bytes,
    canonical_signed_merchant_offer_v2_bytes,
)
from tests.commerce.test_authentication import _signed

_GOLDEN_SIGNATURE_HEX = (
    "8e9cfd410f5287beae413556be453b5040beb6699db1dafd1c580aadc3de7149"
    "945da76d6dfda3c30cdf893df05da64f5108d80945c5547911a2681a363cfe01"
)
_GOLDEN_SIGNED_MERCHANT_OFFER_V2_BYTES = (
    b'{"canonicalization_version":"clear-json-'
    b'v1","payload":{"offer":{"buyer_policy_commitment_sha256":"a5be3c6061223d007ef18a66652e14b149'
    b'69a5c6f5272c6ba12907cb93eabf6b","buyer_policy_commitment_version":"sha256-buyer-'
    b'policy-v2-clear-json-v1","catalog_id":"44000000-0000-4000-8000-'
    b'000000000001","inventory_snapshot_commitment_sha256":"27486a21f4e9d14afcd5a6ad43271812076dad'
    b'8355cb46f9ac7b0879f8526dd7","inventory_snapshot_commitment_version":"sha256-inventory-'
    b'snapshot-v2-clear-json-v1","inventory_snapshot_id":"45000000-0000-4000-8000-'
    b'000000000001","lines":[{"attributes":[{"attribute_key":"brand","catalog_attribute_version":"'
    b'catalog-attribute-v2","evidence_reference_id":"50000000-0000-4000-8000-'
    b'000000000001","provenance":"CLAIMED","schema_version":"2","value":{"attribute_value_version"'
    b':"attribute-value-'
    b'v1","schema_version":"1","value":"Clear","value_type":"string"}},{"attribute_key":"ram_gb","'
    b'catalog_attribute_version":"catalog-attribute-v2","evidence_reference_id":"50000000-0000-'
    b"4000-8000-"
    b'000000000002","provenance":"VERIFIED","schema_version":"2","value":{"attribute_value_version'
    b'":"attribute-value-'
    b'v1","schema_version":"1","value":16,"value_type":"integer"}}],"inventory_evidence_reference_'
    b'id":"50000000-0000-4000-8000-'
    b'000000000065","inventory_provenance":"VERIFIED","max_offer_quantity":5,"merchant_offer_line_'
    b'version":"merchant-offer-line-v2","schema_version":"2","sku_id":"49000000-0000-4000-8000-'
    b'000000000001","unit_price":{"amount_paise":500,"currency":"INR"}},{"attributes":[{"attribute'
    b'_key":"ports","catalog_attribute_version":"catalog-attribute-'
    b'v2","evidence_reference_id":"50000000-0000-4000-8000-'
    b'000000000003","provenance":"CLAIMED","schema_version":"2","value":{"attribute_value_version"'
    b':"attribute-value-'
    b'v1","schema_version":"1","value":4,"value_type":"integer"}}],"inventory_evidence_reference_i'
    b'd":"50000000-0000-4000-8000-'
    b'000000000066","inventory_provenance":"CLAIMED","max_offer_quantity":3,"merchant_offer_line_v'
    b'ersion":"merchant-offer-line-v2","schema_version":"2","sku_id":"49000000-0000-4000-8000-'
    b'000000000002","unit_price":{"amount_paise":600,"currency":"INR"}}],"market_id":"41000000-'
    b"0000-4000-8000-"
    b'000000000001","merchant_catalog_commitment_sha256":"28b872098401ae891495d67eb27396379022f7a5'
    b'460a850d01de0014ee320452","merchant_catalog_commitment_version":"sha256-merchant-'
    b'catalog-v2-clear-json-v1","merchant_id":"43000000-0000-4000-8000-'
    b'000000000001","merchant_offer_version":"merchant-offer-v2","offer_id":"47000000-0000-4000-'
    b"8000-"
    b'000000000001","schema_version":"2"},"schema_version":"2","signature_hex":"8e9cfd410f5287beae'
    b"413556be453b5040beb6699db1dafd1c580aadc3de7149945da76d6dfda3c30cdf893df05da64f5108d80945c554"
    b'7911a2681a363cfe01","signature_version":"ed25519-raw-merchant-offer-v2-clear-'
    b'json-v1","signed_merchant_offer_version":"signed-merchant-'
    b'offer-v2"},"payload_type":"signed_merchant_offer_v2"}'
)
_GOLDEN_SIGNED_MERCHANT_OFFER_V2_SHA256 = (
    "76ec413842b3779bbeef728677bf7e4ba6c783cf14458153d7713be7a6fc54c3"
)


def test_golden_signed_offer_bytes_signature_length_and_hash_are_frozen() -> None:
    signed = _signed()
    encoded = canonical_signed_merchant_offer_v2_bytes(signed)

    assert signed.signature_hex == _GOLDEN_SIGNATURE_HEX
    assert encoded == _GOLDEN_SIGNED_MERCHANT_OFFER_V2_BYTES
    assert len(encoded) == 2_831
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_SIGNED_MERCHANT_OFFER_V2_SHA256


def test_signed_offer_envelope_is_exact_compact_deterministic_utf8() -> None:
    signed = _signed()
    encoded = canonical_signed_merchant_offer_v2_bytes(signed)
    envelope = json.loads(encoded)

    assert set(envelope) == {"canonicalization_version", "payload", "payload_type"}
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == "signed_merchant_offer_v2"
    assert encoded.decode("utf-8").encode("utf-8") == encoded
    assert b": " not in encoded
    assert b", " not in encoded
    assert b"\n" not in encoded
    assert canonical_signed_merchant_offer_v2_bytes(signed) == encoded


def test_signed_offer_payload_binds_exact_fields_and_versions() -> None:
    signed = _signed()
    payload = json.loads(canonical_signed_merchant_offer_v2_bytes(signed))["payload"]

    assert set(payload) == {
        "schema_version",
        "signed_merchant_offer_version",
        "signature_version",
        "offer",
        "signature_hex",
    }
    assert payload["schema_version"] == "2"
    assert payload["signed_merchant_offer_version"] == "signed-merchant-offer-v2"
    assert payload["signature_version"] == "ed25519-raw-merchant-offer-v2-clear-json-v1"
    assert payload["signature_hex"] == signed.signature_hex


def test_nested_offer_projection_exactly_matches_slice_16b_offer_payload() -> None:
    signed = _signed()
    signed_offer_payload = json.loads(canonical_signed_merchant_offer_v2_bytes(signed))["payload"][
        "offer"
    ]
    unsigned_offer_payload = json.loads(canonical_merchant_offer_v2_bytes(signed.offer))["payload"]

    assert signed_offer_payload == unsigned_offer_payload


def test_nested_offer_line_money_attribute_and_value_projections_are_complete() -> None:
    offer = json.loads(canonical_signed_merchant_offer_v2_bytes(_signed()))["payload"]["offer"]
    line = offer["lines"][0]
    attribute = line["attributes"][0]

    assert set(offer) == {
        "schema_version",
        "merchant_offer_version",
        "offer_id",
        "market_id",
        "merchant_id",
        "catalog_id",
        "inventory_snapshot_id",
        "buyer_policy_commitment_version",
        "buyer_policy_commitment_sha256",
        "merchant_catalog_commitment_version",
        "merchant_catalog_commitment_sha256",
        "inventory_snapshot_commitment_version",
        "inventory_snapshot_commitment_sha256",
        "lines",
    }
    assert set(line) == {
        "schema_version",
        "merchant_offer_line_version",
        "sku_id",
        "max_offer_quantity",
        "unit_price",
        "attributes",
        "inventory_provenance",
        "inventory_evidence_reference_id",
    }
    assert line["unit_price"] == {"amount_paise": 500, "currency": "INR"}
    assert set(attribute) == {
        "schema_version",
        "catalog_attribute_version",
        "attribute_key",
        "value",
        "provenance",
        "evidence_reference_id",
    }
    assert set(attribute["value"]) == {
        "schema_version",
        "attribute_value_version",
        "value_type",
        "value",
    }


def test_signed_wire_excludes_keys_and_private_merchant_policy() -> None:
    encoded = canonical_signed_merchant_offer_v2_bytes(_signed())

    for excluded in (
        b"ed25519_public_key_hex",
        b"private_key",
        b"economic_policy",
        b"candidate",
        b"unit_cost_basis",
        b"minimum_margin",
    ):
        assert excluded not in encoded


def test_signature_mutation_changes_canonical_bytes() -> None:
    signed = _signed()
    changed = signed.model_copy(update={"signature_hex": "0" * 128})

    assert canonical_signed_merchant_offer_v2_bytes(changed) != (
        canonical_signed_merchant_offer_v2_bytes(signed)
    )


class _SignedOfferSubclass(SignedMerchantOfferV2):
    pass


def _signed_subclass() -> _SignedOfferSubclass:
    signed = _signed()
    return _SignedOfferSubclass(offer=signed.offer, signature_hex=signed.signature_hex)


@pytest.mark.parametrize(
    ("serializer", "wrong_value"),
    [
        (canonical_signed_merchant_offer_v2_bytes, None),
        (canonical_signed_merchant_offer_v2_bytes, {}),
        (canonical_signed_merchant_offer_v2_bytes, _signed().offer),
        (canonical_signed_merchant_offer_v2_bytes, _signed_subclass()),
    ],
)
def test_signed_offer_serializer_requires_exact_type(
    serializer: Callable[..., bytes],
    wrong_value: object,
) -> None:
    with pytest.raises(TypeError):
        serializer(wrong_value)
