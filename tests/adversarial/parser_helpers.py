from clear_market.certificate import canonical_allocation_certificate_bytes
from tests.properties.certificate_helpers import build_property_certificate_fixture
from tests.properties.market_strategies import PropertyMarketCase


def valid_adversarial_certificate_bytes() -> bytes:
    case = PropertyMarketCase(
        case_tag=901,
        seller_count=2,
        requested_quantity=10,
        reserve_unit_price_paise=500,
        participates=(True, True),
        quantity_available=(10, 11),
        unit_price_paise=(400, 450),
    )
    fixture = build_property_certificate_fixture(case, certificate_variant=1)
    return canonical_allocation_certificate_bytes(fixture.certificate)


def replace_once(data: bytes, old: bytes, new: bytes) -> bytes:
    if type(data) is not bytes or type(old) is not bytes or type(new) is not bytes:
        raise TypeError("wire mutation inputs must be exactly bytes")
    assert old
    assert data.count(old) == 1
    return data.replace(old, new, 1)
