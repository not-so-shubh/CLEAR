from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock
from uuid import uuid4

import pytest

import ui.product.service as service_module
from clear_market.canonical.serialization import canonical_utc_datetime
from clear_market.certificate.v2 import parse_canonical_allocation_certificate_v2
from clear_market.commerce import (
    MerchantOfferVerificationError,
    MerchantOfferVerificationErrorCode,
)
from clear_market.verification.v2 import (
    AllocationCertificateVerificationFailureCodeV2,
    AllocationCertificateVerificationResultV2,
)
from ui.product.models import CreateMarketRequest, CreateMerchantRequest, SubmitOfferRequest
from ui.product.service import ProductErrorCode, ProductService, ProductServiceError


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _merchant_request(
    name: str,
    *,
    inventory: int = 3,
    cost: int = 100,
    margin: int = 0,
    cap: int = 3,
) -> CreateMerchantRequest:
    return CreateMerchantRequest(
        display_name=name,
        product_display_name=f"{name} EdgeBox",
        merchant_sku=f"{name.upper()}-EDGE",
        inventory_quantity=inventory,
        unit_cost_basis_paise=cost,
        minimum_margin_paise=margin,
        max_quantity_per_offer=cap,
    )


def _three_merchants(service: ProductService) -> dict[str, str]:
    return {
        name: str(service.create_merchant(_merchant_request(name))["merchant_id"])
        for name in ("Alpha", "Beta", "Gamma")
    }


def _market_request(clock: MutableClock, merchant_ids: list[str]) -> CreateMarketRequest:
    return CreateMarketRequest(
        requested_quantity=5,
        minimum_acceptable_quantity=5,
        max_winners=2,
        max_total_payment_paise=10_000,
        eligible_merchant_ids=merchant_ids,
        offer_deadline=canonical_utc_datetime(clock.now + timedelta(hours=1)),
    )


def _submit_prices(
    service: ProductService,
    market_id: str,
    merchants: dict[str, str],
    prices: dict[str, int],
) -> None:
    for name, price in prices.items():
        service.submit_offer(
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants[name],
                proposed_quantity=3,
                proposed_unit_price_paise=price,
            ),
        )


def test_runtime_inputs_change_real_allocation_and_certificate(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)

    first_market = service.create_market(_market_request(clock, list(merchants.values())))
    first_market_id = str(first_market["market_id"])
    _submit_prices(
        service,
        first_market_id,
        merchants,
        {"Alpha": 500, "Beta": 600, "Gamma": 700},
    )
    first = service.close_market(first_market_id)

    second_market = service.create_market(_market_request(clock, list(merchants.values())))
    second_market_id = str(second_market["market_id"])
    _submit_prices(
        service,
        second_market_id,
        merchants,
        {"Alpha": 500, "Beta": 1_000, "Gamma": 700},
    )
    second = service.close_market(second_market_id)

    assert first["allocation_status"] == "FEASIBLE"
    assert first["fulfilled_quantity"] == 5
    assert first["winner_count"] == 2
    assert set(first["winner_merchant_ids"]) == {merchants["Alpha"], merchants["Beta"]}
    assert first["total_payment_paise"] == 2_700
    assert first["certificate_verified"] is True

    assert second["allocation_status"] == "FEASIBLE"
    assert second["fulfilled_quantity"] == 5
    assert second["winner_count"] == 2
    assert set(second["winner_merchant_ids"]) == {merchants["Alpha"], merchants["Gamma"]}
    assert second["total_payment_paise"] == 2_900
    assert second["certificate_verified"] is True
    assert first["winner_merchant_ids"] != second["winner_merchant_ids"]
    assert first["total_payment_paise"] != second["total_payment_paise"]
    assert first["certificate_digest"] != second["certificate_digest"]


def test_closed_market_result_survives_store_reopen(tmp_path: Path) -> None:
    clock = MutableClock()
    path = tmp_path / "product.sqlite3"
    service = ProductService(path, clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    _submit_prices(
        service,
        market_id,
        merchants,
        {"Alpha": 500, "Beta": 600, "Gamma": 700},
    )
    closed = service.close_market(market_id)

    reloaded = ProductService(path, clock=clock).get_market(market_id)

    assert reloaded == closed
    assert reloaded["certificate_digest"] == closed["certificate_digest"]
    assert reloaded["certificate_verified"] is True


def test_product_package_has_no_demo_fixture_dependency() -> None:
    product_root = Path(service_module.__file__).parent
    forbidden = (
        "clear_market.demo",
        "_certificate_fixture",
        "_buyer_policy",
        "_merchant_source",
        "run_demo_v1",
    )
    sources = "\n".join(path.read_text(encoding="utf-8") for path in product_root.glob("*.py"))
    for name in forbidden:
        assert name not in sources


@pytest.mark.parametrize(
    ("merchant_options", "quantity", "price"),
    [
        ({"inventory": 3, "cap": 3}, 4, 500),
        ({"cost": 400, "margin": 100}, 3, 499),
    ],
)
def test_production_merchant_boundary_rejects_unsafe_offer_without_persistence(
    tmp_path: Path,
    merchant_options: dict[str, int],
    quantity: int,
    price: int,
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    target = str(
        service.create_merchant(_merchant_request("Target", **merchant_options))["merchant_id"]
    )
    other = str(service.create_merchant(_merchant_request("Other"))["merchant_id"])
    market = service.create_market(_market_request(clock, [target, other]))

    with pytest.raises(ProductServiceError) as raised:
        service.submit_offer(
            str(market["market_id"]),
            SubmitOfferRequest(
                merchant_id=target,
                proposed_quantity=quantity,
                proposed_unit_price_paise=price,
            ),
        )

    assert raised.value.code is ProductErrorCode.MERCHANT_OFFER_REJECTED
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, str(market["market_id"])) == 0


def test_duplicate_offer_fails_closed(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    request = SubmitOfferRequest(
        merchant_id=merchants["Alpha"],
        proposed_quantity=3,
        proposed_unit_price_paise=500,
    )
    service.submit_offer(str(market["market_id"]), request)

    with pytest.raises(ProductServiceError) as raised:
        service.submit_offer(str(market["market_id"]), request)

    assert raised.value.code is ProductErrorCode.DUPLICATE_OFFER
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, str(market["market_id"])) == 1


def test_concurrent_duplicate_offer_is_database_safe(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    request = SubmitOfferRequest(
        merchant_id=merchants["Alpha"],
        proposed_quantity=3,
        proposed_unit_price_paise=500,
    )
    start = Barrier(3)

    def submit() -> dict[str, object] | ProductErrorCode:
        start.wait()
        try:
            return service.submit_offer(market_id, request)
        except ProductServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        start.wait()
        outcomes = [future.result(timeout=10) for future in futures]

    successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, ProductErrorCode)]
    assert len(successes) == 1
    assert failures == [ProductErrorCode.DUPLICATE_OFFER]
    with service.store.connection() as connection:
        offers = service.store.list_offers(connection, market_id)
    assert len(offers) == 1
    assert offers[0].offer_id == successes[0]["offer_id"]


def test_offer_after_deadline_is_not_signed_or_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    build_calls = 0
    original = service_module.build_and_sign_merchant_offer_v2

    def counting_builder(**kwargs: object) -> object:
        nonlocal build_calls
        build_calls += 1
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "build_and_sign_merchant_offer_v2", counting_builder)
    clock.now += timedelta(hours=2)

    with pytest.raises(ProductServiceError) as raised:
        service.submit_offer(
            str(market["market_id"]),
            SubmitOfferRequest(
                merchant_id=merchants["Alpha"],
                proposed_quantity=3,
                proposed_unit_price_paise=500,
            ),
        )

    assert raised.value.code is ProductErrorCode.OFFER_DEADLINE_PASSED
    assert build_calls == 0
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, str(market["market_id"])) == 0


def test_offer_after_close_fails_closed(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    service.close_market(market_id)

    with pytest.raises(ProductServiceError) as raised:
        service.submit_offer(
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants["Alpha"],
                proposed_quantity=3,
                proposed_unit_price_paise=500,
            ),
        )

    assert raised.value.code is ProductErrorCode.MARKET_NOT_OPEN


def test_unknown_and_ineligible_merchants_fail_closed(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    unknown = str(uuid4())
    invalid_market_request = _market_request(clock, [merchants["Alpha"], unknown])

    with pytest.raises(ProductServiceError) as unknown_error:
        service.create_market(invalid_market_request)
    assert unknown_error.value.code is ProductErrorCode.NOT_FOUND

    market = service.create_market(_market_request(clock, [merchants["Alpha"], merchants["Beta"]]))
    with pytest.raises(ProductServiceError) as ineligible_error:
        service.submit_offer(
            str(market["market_id"]),
            SubmitOfferRequest(
                merchant_id=merchants["Gamma"],
                proposed_quantity=3,
                proposed_unit_price_paise=500,
            ),
        )
    assert ineligible_error.value.code is ProductErrorCode.MERCHANT_NOT_ELIGIBLE


def test_private_key_is_absent_from_every_public_dto(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = [service.create_merchant(_merchant_request(name)) for name in ("One", "Two")]
    market = service.create_market(
        _market_request(clock, [str(item["merchant_id"]) for item in merchants])
    )
    offer = service.submit_offer(
        str(market["market_id"]),
        SubmitOfferRequest(
            merchant_id=str(merchants[0]["merchant_id"]),
            proposed_quantity=3,
            proposed_unit_price_paise=500,
        ),
    )
    closed = service.close_market(str(market["market_id"]))
    public_text = json.dumps([*merchants, market, offer, closed])

    assert "private" not in public_text.lower()
    with service.store.connection() as connection:
        record = service.store.get_merchant(connection, str(merchants[0]["merchant_id"]))
    assert record is not None
    assert record.signing_private_key_hex not in public_text
    with service.store.connection() as connection:
        offers = service.store.list_offers(connection, str(market["market_id"]))
        result = service.store.get_result(connection, str(market["market_id"]))
    assert result is not None
    assert record.signing_private_key_hex.encode() not in offers[0].canonical_signed_offer
    assert record.signing_private_key_hex.encode() not in result.canonical_certificate


def test_private_key_is_loaded_only_for_offer_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    path = tmp_path / "product.sqlite3"
    service = ProductService(path, clock=clock)
    loaded = 0
    original = ProductService._load_private_signing_key

    def counting_loader(record: object, identity: object) -> object:
        nonlocal loaded
        loaded += 1
        return original(record, identity)  # type: ignore[arg-type]

    monkeypatch.setattr(
        ProductService,
        "_load_private_signing_key",
        staticmethod(counting_loader),
    )
    merchants = _three_merchants(service)
    assert loaded == 0
    market = service.create_market(_market_request(clock, list(merchants.values())))
    assert loaded == 0
    service.submit_offer(
        str(market["market_id"]),
        SubmitOfferRequest(
            merchant_id=merchants["Alpha"],
            proposed_quantity=3,
            proposed_unit_price_paise=500,
        ),
    )
    assert loaded == 1
    service.close_market(str(market["market_id"]))
    ProductService(path, clock=clock).get_market(str(market["market_id"]))
    assert loaded == 1


def test_close_invokes_production_allocation_certificate_and_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    _submit_prices(
        service,
        market_id,
        merchants,
        {"Alpha": 500, "Beta": 600, "Gamma": 700},
    )
    counts = {"allocate": 0, "build_certificate": 0, "verify_certificate": 0, "auth": 0}

    def wrap(name: str, function: object) -> object:
        def wrapped(*args: object, **kwargs: object) -> object:
            counts[name] += 1
            return function(*args, **kwargs)  # type: ignore[operator]

        return wrapped

    monkeypatch.setattr(
        service_module,
        "allocate_market_v2",
        wrap("allocate", service_module.allocate_market_v2),
    )
    monkeypatch.setattr(
        service_module,
        "build_allocation_certificate_v2",
        wrap("build_certificate", service_module.build_allocation_certificate_v2),
    )
    monkeypatch.setattr(
        service_module,
        "verify_allocation_certificate_v2",
        wrap("verify_certificate", service_module.verify_allocation_certificate_v2),
    )
    monkeypatch.setattr(
        service_module,
        "verify_canonical_signed_merchant_offer_v2",
        wrap("auth", service_module.verify_canonical_signed_merchant_offer_v2),
    )

    result = service.close_market(market_id)

    assert counts == {"allocate": 1, "build_certificate": 1, "verify_certificate": 1, "auth": 3}
    assert result["certificate_verified"] is True
    assert "allocated_quantity" not in json.dumps(result)


def test_authentication_failure_prevents_offer_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))

    def reject(**_kwargs: object) -> object:
        raise MerchantOfferVerificationError(MerchantOfferVerificationErrorCode.INVALID_SIGNATURE)

    monkeypatch.setattr(service_module, "verify_canonical_signed_merchant_offer_v2", reject)
    with pytest.raises(ProductServiceError) as raised:
        service.submit_offer(
            str(market["market_id"]),
            SubmitOfferRequest(
                merchant_id=merchants["Alpha"],
                proposed_quantity=3,
                proposed_unit_price_paise=500,
            ),
        )

    assert raised.value.code is ProductErrorCode.OFFER_AUTHENTICATION_FAILED
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, str(market["market_id"])) == 0


def test_unverified_certificate_leaves_market_closed_without_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    _submit_prices(
        service,
        market_id,
        merchants,
        {"Alpha": 500, "Beta": 600},
    )

    monkeypatch.setattr(
        service_module,
        "verify_allocation_certificate_v2",
        lambda *_args, **_kwargs: AllocationCertificateVerificationResultV2(
            verified=False,
            failure_code=AllocationCertificateVerificationFailureCodeV2.ALLOCATION_MISMATCH,
        ),
    )
    with pytest.raises(ProductServiceError) as raised:
        service.close_market(market_id)

    assert raised.value.code is ProductErrorCode.CERTIFICATE_NOT_VERIFIED
    reloaded = ProductService(tmp_path / "product.sqlite3", clock=clock)
    assert reloaded.get_market(market_id)["market_state"] == "CLOSED"
    with reloaded.store.connection() as connection:
        assert reloaded.store.get_result(connection, market_id) is None
    with pytest.raises(ProductServiceError) as later_offer:
        reloaded.submit_offer(
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants["Gamma"],
                proposed_quantity=3,
                proposed_unit_price_paise=700,
            ),
        )
    assert later_offer.value.code is ProductErrorCode.MARKET_NOT_OPEN


def test_close_commits_before_concurrent_offer_can_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    allocation_entered = Event()
    release_allocation = Event()
    original = service_module.allocate_market_v2

    def blocked_allocator(**kwargs: object) -> object:
        allocation_entered.set()
        assert release_allocation.wait(timeout=10)
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "allocate_market_v2", blocked_allocator)
    with ThreadPoolExecutor(max_workers=2) as executor:
        close_future = executor.submit(service.close_market, market_id)
        assert allocation_entered.wait(timeout=10)
        offer_future = executor.submit(
            service.submit_offer,
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants["Alpha"],
                proposed_quantity=3,
                proposed_unit_price_paise=500,
            ),
        )
        with pytest.raises(ProductServiceError) as offer_error:
            offer_future.result(timeout=10)
        release_allocation.set()
        closed = close_future.result(timeout=10)

    assert offer_error.value.code is ProductErrorCode.MARKET_NOT_OPEN
    assert closed["market_state"] == "CLOSED"
    with service.store.connection() as connection:
        assert service.store.count_offers(connection, market_id) == 0
        assert service.store.count_results(connection, market_id) == 1


def test_offer_committing_first_is_included_by_concurrent_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    authentication_entered = Event()
    release_authentication = Event()
    call_lock = Lock()
    blocked = False
    original = service_module.verify_canonical_signed_merchant_offer_v2

    def blocked_authenticator(**kwargs: object) -> object:
        nonlocal blocked
        with call_lock:
            should_block = not blocked
            blocked = True
        if should_block:
            authentication_entered.set()
            assert release_authentication.wait(timeout=10)
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        service_module,
        "verify_canonical_signed_merchant_offer_v2",
        blocked_authenticator,
    )
    close_started = Event()

    def close() -> dict[str, object]:
        close_started.set()
        return service.close_market(market_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        offer_future = executor.submit(
            service.submit_offer,
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants["Alpha"],
                proposed_quantity=3,
                proposed_unit_price_paise=500,
            ),
        )
        assert authentication_entered.wait(timeout=10)
        close_future = executor.submit(close)
        assert close_started.wait(timeout=10)
        release_authentication.set()
        offer = offer_future.result(timeout=10)
        close_future.result(timeout=10)

    with service.store.connection() as connection:
        offers = service.store.list_offers(connection, market_id)
        result = service.store.get_result(connection, market_id)
    assert len(offers) == 1
    assert result is not None
    certificate = parse_canonical_allocation_certificate_v2(result.canonical_certificate)
    assert tuple(
        item.signed_offer.offer.offer_id for item in certificate.merchant_offer_evidence
    ) == (offer["offer_id"],)


def test_concurrent_close_persists_at_most_one_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    allocation_entered = Event()
    release_allocation = Event()
    original = service_module.allocate_market_v2

    def blocked_allocator(**kwargs: object) -> object:
        allocation_entered.set()
        assert release_allocation.wait(timeout=10)
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "allocate_market_v2", blocked_allocator)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.close_market, market_id)
        assert allocation_entered.wait(timeout=10)
        second = executor.submit(service.close_market, market_id)
        with pytest.raises(ProductServiceError) as second_error:
            second.result(timeout=10)
        release_allocation.set()
        first_result = first.result(timeout=10)

    assert second_error.value.code is ProductErrorCode.MARKET_NOT_OPEN
    with service.store.connection() as connection:
        result = service.store.get_result(connection, market_id)
        assert service.store.count_results(connection, market_id) == 1
    assert result is not None
    assert result.certificate_id == first_result["certificate_id"]
    assert result.certificate_digest == first_result["certificate_digest"]


def test_evidence_is_ordered_by_receipt_then_offer_id(tmp_path: Path) -> None:
    clock = MutableClock()
    service = ProductService(tmp_path / "product.sqlite3", clock=clock)
    merchants = _three_merchants(service)
    market = service.create_market(_market_request(clock, list(merchants.values())))
    market_id = str(market["market_id"])
    offer_ids = []
    for name, price in (("Gamma", 700), ("Alpha", 500), ("Beta", 600)):
        offer = service.submit_offer(
            market_id,
            SubmitOfferRequest(
                merchant_id=merchants[name],
                proposed_quantity=3,
                proposed_unit_price_paise=price,
            ),
        )
        offer_ids.append(str(offer["offer_id"]))
    service.close_market(market_id)

    with service.store.connection() as connection:
        result = service.store.get_result(connection, market_id)
    assert result is not None
    certificate = parse_canonical_allocation_certificate_v2(result.canonical_certificate)
    evidence_ids = tuple(
        item.signed_offer.offer.offer_id for item in certificate.merchant_offer_evidence
    )
    assert evidence_ids == tuple(sorted(offer_ids))
