import hashlib
import json
from collections.abc import Callable

import pytest

from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    CatalogAttributeV2,
    MerchantOfferLineV2,
    MerchantOfferV2,
    ProvenanceLabel,
    canonical_merchant_offer_v2_bytes,
)
from clear_market.domain import Money
from tests.commerce.test_merchant import (
    _build,
    _evidence_id,
    _offer_line,
)

_GOLDEN_MERCHANT_OFFER_V2_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"buyer_policy_commitment_sha256":"a5b'
    b'e3c6061223d007ef18a66652e14b14969a5c6f5272c6ba12907cb93eabf6b","buyer_policy_commitment_vers'
    b'ion":"sha256-buyer-policy-v2-clear-json-v1","catalog_id":"44000000-0000-4000-8000-0000000000'
    b'01","inventory_snapshot_commitment_sha256":"27486a21f4e9d14afcd5a6ad43271812076dad8355cb46f9'
    b'ac7b0879f8526dd7","inventory_snapshot_commitment_version":"sha256-inventory-snapshot-v2-clea'
    b'r-json-v1","inventory_snapshot_id":"45000000-0000-4000-8000-000000000001","lines":[{"attribu'
    b'tes":[{"attribute_key":"brand","catalog_attribute_version":"catalog-attribute-v2","evidence_'
    b'reference_id":"50000000-0000-4000-8000-000000000001","provenance":"CLAIMED","schema_version"'
    b':"2","value":{"attribute_value_version":"attribute-value-v1","schema_version":"1","value":"C'
    b'lear","value_type":"string"}},{"attribute_key":"ram_gb","catalog_attribute_version":"catalog'
    b'-attribute-v2","evidence_reference_id":"50000000-0000-4000-8000-000000000002","provenance":"'
    b'VERIFIED","schema_version":"2","value":{"attribute_value_version":"attribute-value-v1","sche'
    b'ma_version":"1","value":16,"value_type":"integer"}}],"inventory_evidence_reference_id":"5000'
    b'0000-0000-4000-8000-000000000065","inventory_provenance":"VERIFIED","max_offer_quantity":5,"'
    b'merchant_offer_line_version":"merchant-offer-line-v2","schema_version":"2","sku_id":"4900000'
    b'0-0000-4000-8000-000000000001","unit_price":{"amount_paise":500,"currency":"INR"}},{"attribu'
    b'tes":[{"attribute_key":"ports","catalog_attribute_version":"catalog-attribute-v2","evidence_'
    b'reference_id":"50000000-0000-4000-8000-000000000003","provenance":"CLAIMED","schema_version"'
    b':"2","value":{"attribute_value_version":"attribute-value-v1","schema_version":"1","value":4,'
    b'"value_type":"integer"}}],"inventory_evidence_reference_id":"50000000-0000-4000-8000-0000000'
    b'00066","inventory_provenance":"CLAIMED","max_offer_quantity":3,"merchant_offer_line_version"'
    b':"merchant-offer-line-v2","schema_version":"2","sku_id":"49000000-0000-4000-8000-00000000000'
    b'2","unit_price":{"amount_paise":600,"currency":"INR"}}],"market_id":"41000000-0000-4000-8000'
    b'-000000000001","merchant_catalog_commitment_sha256":"28b872098401ae891495d67eb27396379022f7a'
    b'5460a850d01de0014ee320452","merchant_catalog_commitment_version":"sha256-merchant-catalog-v2'
    b'-clear-json-v1","merchant_id":"43000000-0000-4000-8000-000000000001","merchant_offer_version'
    b'":"merchant-offer-v2","offer_id":"47000000-0000-4000-8000-000000000001","schema_version":"2"'
    b'},"payload_type":"merchant_offer_v2"}'
)
_GOLDEN_MERCHANT_OFFER_V2_SHA256 = (
    "11941a30a627bbfc0d20e0455d4c0e065f791a2c594b582d84b2bee1946b6ff8"
)


def test_golden_merchant_offer_v2_bytes_length_and_hash_are_frozen() -> None:
    encoded = canonical_merchant_offer_v2_bytes(_build())

    assert encoded == _GOLDEN_MERCHANT_OFFER_V2_BYTES
    assert len(encoded) == 2_521
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_MERCHANT_OFFER_V2_SHA256


def test_offer_envelope_is_exact_compact_deterministic_utf8() -> None:
    offer = _build()
    encoded = canonical_merchant_offer_v2_bytes(offer)
    envelope = json.loads(encoded)

    assert set(envelope) == {"canonicalization_version", "payload", "payload_type"}
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == "merchant_offer_v2"
    assert encoded.decode("utf-8").encode("utf-8") == encoded
    assert b": " not in encoded
    assert b", " not in encoded
    assert b"\n" not in encoded
    assert canonical_merchant_offer_v2_bytes(offer) == encoded


def test_offer_projection_binds_every_top_level_field() -> None:
    payload = json.loads(canonical_merchant_offer_v2_bytes(_build()))["payload"]

    assert set(payload) == {
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
    assert payload["schema_version"] == "2"
    assert payload["merchant_offer_version"] == "merchant-offer-v2"
    assert payload["buyer_policy_commitment_version"] == ("sha256-buyer-policy-v2-clear-json-v1")
    assert payload["merchant_catalog_commitment_version"] == (
        "sha256-merchant-catalog-v2-clear-json-v1"
    )
    assert payload["inventory_snapshot_commitment_version"] == (
        "sha256-inventory-snapshot-v2-clear-json-v1"
    )


def test_offer_line_and_attribute_projections_are_explicit() -> None:
    line = json.loads(canonical_merchant_offer_v2_bytes(_build()))["payload"]["lines"][0]

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
    assert set(line["attributes"][0]) == {
        "schema_version",
        "catalog_attribute_version",
        "attribute_key",
        "value",
        "provenance",
        "evidence_reference_id",
    }
    assert set(line["attributes"][0]["value"]) == {
        "schema_version",
        "attribute_value_version",
        "value_type",
        "value",
    }
    assert line["unit_price"] == {"amount_paise": 500, "currency": "INR"}
    assert line["inventory_provenance"] == "VERIFIED"
    assert line["inventory_evidence_reference_id"] == _evidence_id(101)
    assert [attribute["attribute_key"] for attribute in line["attributes"]] == [
        "brand",
        "ram_gb",
    ]


def test_offer_projection_contains_no_catalog_prose_or_internal_economics() -> None:
    encoded = canonical_merchant_offer_v2_bytes(_build())

    for excluded in (
        b"display_name",
        b"description",
        b"Laptop display prose",
        b"Dock SKU prose",
        b"unit_cost_basis",
        b"minimum_margin",
        b"economic_policy_id",
    ):
        assert excluded not in encoded


def _offer_from_lines(lines: tuple[MerchantOfferLineV2, ...]) -> MerchantOfferV2:
    source = _build()
    return MerchantOfferV2(
        offer_id=source.offer_id,
        market_id=source.market_id,
        merchant_id=source.merchant_id,
        catalog_id=source.catalog_id,
        inventory_snapshot_id=source.inventory_snapshot_id,
        buyer_policy_commitment_sha256=source.buyer_policy_commitment_sha256,
        merchant_catalog_commitment_sha256=source.merchant_catalog_commitment_sha256,
        inventory_snapshot_commitment_sha256=source.inventory_snapshot_commitment_sha256,
        lines=lines,
    )


def test_line_input_order_does_not_change_offer_bytes() -> None:
    offer = _build()

    assert canonical_merchant_offer_v2_bytes(offer) == canonical_merchant_offer_v2_bytes(
        _offer_from_lines(tuple(reversed(offer.lines)))
    )


def test_attribute_input_order_does_not_change_offer_bytes() -> None:
    offer = _build()
    first = offer.lines[0]
    reordered_first = MerchantOfferLineV2(
        sku_id=first.sku_id,
        max_offer_quantity=first.max_offer_quantity,
        unit_price=first.unit_price,
        attributes=tuple(reversed(first.attributes)),
        inventory_provenance=first.inventory_provenance,
        inventory_evidence_reference_id=first.inventory_evidence_reference_id,
    )
    reordered = _offer_from_lines((reordered_first, offer.lines[1]))

    assert canonical_merchant_offer_v2_bytes(offer) == canonical_merchant_offer_v2_bytes(reordered)


def test_every_offer_top_level_field_changes_bytes() -> None:
    offer = _build()
    original = canonical_merchant_offer_v2_bytes(offer)
    changed = (
        offer.model_copy(update={"schema_version": "3"}),
        offer.model_copy(update={"merchant_offer_version": "merchant-offer-v3"}),
        offer.model_copy(update={"offer_id": "47000000-0000-4000-8000-000000000002"}),
        offer.model_copy(update={"market_id": "41000000-0000-4000-8000-000000000002"}),
        offer.model_copy(update={"merchant_id": "43000000-0000-4000-8000-000000000002"}),
        offer.model_copy(update={"catalog_id": "44000000-0000-4000-8000-000000000002"}),
        offer.model_copy(update={"inventory_snapshot_id": "45000000-0000-4000-8000-000000000002"}),
        offer.model_copy(update={"buyer_policy_commitment_version": "changed"}),
        offer.model_copy(update={"buyer_policy_commitment_sha256": "0" * 64}),
        offer.model_copy(update={"merchant_catalog_commitment_version": "changed"}),
        offer.model_copy(update={"merchant_catalog_commitment_sha256": "1" * 64}),
        offer.model_copy(update={"inventory_snapshot_commitment_version": "changed"}),
        offer.model_copy(update={"inventory_snapshot_commitment_sha256": "2" * 64}),
        offer.model_copy(update={"lines": (offer.lines[0],)}),
    )

    assert all(canonical_merchant_offer_v2_bytes(value) != original for value in changed)


def test_every_offer_line_field_changes_bytes() -> None:
    offer = _build()
    original = canonical_merchant_offer_v2_bytes(offer)
    line = offer.lines[0]

    def changed_offer(changed_line: MerchantOfferLineV2) -> MerchantOfferV2:
        return offer.model_copy(update={"lines": (changed_line, offer.lines[1])})

    changed = (
        changed_offer(line.model_copy(update={"schema_version": "3"})),
        changed_offer(line.model_copy(update={"merchant_offer_line_version": "changed"})),
        changed_offer(line.model_copy(update={"sku_id": "49000000-0000-4000-8000-000000000009"})),
        changed_offer(line.model_copy(update={"max_offer_quantity": 6})),
        changed_offer(line.model_copy(update={"unit_price": Money(amount_paise=501)})),
        changed_offer(line.model_copy(update={"attributes": (line.attributes[0],)})),
        changed_offer(line.model_copy(update={"inventory_provenance": ProvenanceLabel.CLAIMED})),
        changed_offer(
            line.model_copy(update={"inventory_evidence_reference_id": _evidence_id(999)})
        ),
    )

    assert all(canonical_merchant_offer_v2_bytes(value) != original for value in changed)


def test_every_catalog_attribute_field_changes_offer_bytes() -> None:
    offer = _build()
    original = canonical_merchant_offer_v2_bytes(offer)
    line = offer.lines[0]
    attribute = line.attributes[0]

    def changed_offer(changed_attribute: CatalogAttributeV2) -> MerchantOfferV2:
        changed_line = line.model_copy(
            update={"attributes": (changed_attribute, line.attributes[1])}
        )
        return offer.model_copy(update={"lines": (changed_line, offer.lines[1])})

    changed = (
        changed_offer(attribute.model_copy(update={"schema_version": "3"})),
        changed_offer(attribute.model_copy(update={"catalog_attribute_version": "changed"})),
        changed_offer(attribute.model_copy(update={"attribute_key": "manufacturer"})),
        changed_offer(
            attribute.model_copy(
                update={"value": attribute.value.model_copy(update={"schema_version": "2"})}
            )
        ),
        changed_offer(
            attribute.model_copy(
                update={
                    "value": attribute.value.model_copy(
                        update={"attribute_value_version": "changed"}
                    )
                }
            )
        ),
        changed_offer(
            attribute.model_copy(
                update={"value": AttributeValue(value_type=AttributeValueType.BOOLEAN, value=True)}
            )
        ),
        changed_offer(
            attribute.model_copy(
                update={
                    "value": AttributeValue(value_type=AttributeValueType.STRING, value="Other")
                }
            )
        ),
        changed_offer(attribute.model_copy(update={"provenance": ProvenanceLabel.VERIFIED})),
        changed_offer(attribute.model_copy(update={"evidence_reference_id": _evidence_id(998)})),
    )

    assert all(canonical_merchant_offer_v2_bytes(value) != original for value in changed)


class _MerchantOfferSubclass(MerchantOfferV2):
    pass


def _offer_subclass() -> _MerchantOfferSubclass:
    offer = _build()
    return _MerchantOfferSubclass(
        offer_id=offer.offer_id,
        market_id=offer.market_id,
        merchant_id=offer.merchant_id,
        catalog_id=offer.catalog_id,
        inventory_snapshot_id=offer.inventory_snapshot_id,
        buyer_policy_commitment_sha256=offer.buyer_policy_commitment_sha256,
        merchant_catalog_commitment_sha256=offer.merchant_catalog_commitment_sha256,
        inventory_snapshot_commitment_sha256=offer.inventory_snapshot_commitment_sha256,
        lines=offer.lines,
    )


@pytest.mark.parametrize(
    ("serializer", "wrong_value"),
    [
        (canonical_merchant_offer_v2_bytes, None),
        (canonical_merchant_offer_v2_bytes, {}),
        (canonical_merchant_offer_v2_bytes, _offer_line()),
        (canonical_merchant_offer_v2_bytes, _offer_subclass()),
    ],
)
def test_offer_serializer_requires_exact_type(
    serializer: Callable[..., bytes],
    wrong_value: object,
) -> None:
    with pytest.raises(TypeError):
        serializer(wrong_value)
