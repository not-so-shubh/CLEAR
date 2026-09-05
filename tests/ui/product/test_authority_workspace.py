from __future__ import annotations

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

import ui.product.service as service_module
from clear_market.canonical.serialization import canonical_utc_datetime
from clear_market.certificate.v2 import parse_canonical_allocation_certificate_v2
from clear_market.execution import (
    ExecutionPlanV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
)
from clear_market.persistence import SQLiteFinancialLedgerV1
from ui.product.models import CreateMarketRequest, CreateMerchantRequest, SubmitOfferRequest
from ui.product.service import ProductErrorCode, ProductService, ProductServiceError


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2036, 4, 5, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _merchant(name: str) -> CreateMerchantRequest:
    return CreateMerchantRequest(
        display_name=f"{name} Compute",
        product_display_name=f"{name} EdgeBox",
        merchant_sku=f"{name.upper()}-EDGE",
        inventory_quantity=3,
        unit_cost_basis_paise=100,
        minimum_margin_paise=0,
        max_quantity_per_offer=3,
        attributes=[],
    )


def _market(
    service: ProductService,
    clock: _Clock,
    merchant_ids: list[str],
    *,
    requested_quantity: int = 5,
    minimum_acceptable_quantity: int = 5,
) -> str:
    result = service.create_market(
        CreateMarketRequest(
            requested_quantity=requested_quantity,
            minimum_acceptable_quantity=minimum_acceptable_quantity,
            max_winners=2,
            max_total_payment_paise=20_000,
            eligible_merchant_ids=merchant_ids,
            offer_deadline=canonical_utc_datetime(clock.now + timedelta(hours=1)),
        )
    )
    return str(result["market_id"])


def _runtime(tmp_path: Path) -> tuple[ProductService, _Clock, dict[str, str], Path, Path]:
    clock = _Clock()
    product_path = tmp_path / "product.sqlite3"
    ledger_path = tmp_path / "product-financial-ledger.sqlite3"
    service = ProductService(
        product_path,
        clock=clock,
        financial_ledger_path=ledger_path,
    )
    merchants = {
        name: str(service.create_merchant(_merchant(name))["merchant_id"])
        for name in ("Alpha", "Beta", "Gamma")
    }
    return service, clock, merchants, product_path, ledger_path


def _closed_feasible(
    tmp_path: Path,
    *,
    prices: tuple[int, int, int] = (500, 600, 700),
) -> tuple[ProductService, _Clock, dict[str, str], str, Path, Path]:
    service, clock, merchants, product_path, ledger_path = _runtime(tmp_path)
    market_id = _market(service, clock, list(merchants.values()))
    for merchant_id, price in zip(merchants.values(), prices, strict=True):
        service.submit_offer(
            market_id,
            SubmitOfferRequest(
                merchant_id=merchant_id,
                proposed_quantity=3,
                proposed_unit_price_paise=price,
            ),
        )
    service.close_market(market_id)
    return service, clock, merchants, market_id, product_path, ledger_path


def _result_record(service: ProductService, market_id: str) -> object:
    with service.store.connection() as connection:
        result = service.store.get_result(connection, market_id)
    assert result is not None
    return result


def test_closed_authority_replays_persisted_certificate_and_survives_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLEAR_AI_BASE_URL",
        "CLEAR_AI_API_KEY",
        "CLEAR_AI_PROVIDER_NAME",
        "CLEAR_AI_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)
    service, clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)
    result = _result_record(service, market_id)
    original_verify = service_module.verify_allocation_certificate_v2
    replay_calls = 0

    def counted_verify(*args: object, **kwargs: object) -> object:
        nonlocal replay_calls
        replay_calls += 1
        return original_verify(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "verify_allocation_certificate_v2", counted_verify)

    authority = service.get_market_authority(market_id)

    assert replay_calls == 1
    assert authority["market"] == {"market_id": market_id, "state": "CLOSED"}
    assert authority["certificate"]["certificate_id"] == result.certificate_id  # type: ignore[attr-defined,index]
    assert authority["certificate"]["digest_sha256"] == result.certificate_digest  # type: ignore[attr-defined,index]
    certificate = parse_canonical_allocation_certificate_v2(result.canonical_certificate)  # type: ignore[attr-defined]
    projected = authority["certificate"]["allocation"]  # type: ignore[index]
    assert projected["status"] == certificate.allocation.status.value
    assert projected["total_payment_paise"] == certificate.allocation.total_payment.amount_paise
    assert [line["merchant_id"] for line in projected["lines"]] == [
        line.merchant_id for line in certificate.allocation.lines
    ]
    assert {line["display_name"] for line in projected["lines"]} == {
        "Alpha Compute",
        "Beta Compute",
    }
    assert authority["verifier"] == {
        "verified": True,
        "failure_code": None,
        "failed_evidence_index": None,
        "truth_class": "REAL LOCAL PRODUCTION LOGIC",
    }
    assert authority["governor"] == {"state": "NOT_AUTHORIZED"}
    serialized = json.dumps(authority)
    for forbidden in (
        "signing_private_key",
        "unit_cost_basis",
        "minimum_margin",
        str(product_path),
        str(ledger_path),
    ):
        assert forbidden not in serialized

    reopened = ProductService(product_path, clock=clock, financial_ledger_path=ledger_path)
    assert reopened.get_market_authority(market_id) == authority


def test_open_market_cannot_expose_downstream_authority(tmp_path: Path) -> None:
    service, clock, merchants, _product_path, _ledger_path = _runtime(tmp_path)
    market_id = _market(service, clock, list(merchants.values()))

    with pytest.raises(ProductServiceError) as raised:
        service.get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.MARKET_NOT_CLOSED


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("canonical_certificate", b"{}"),
        ("total_payment_paise", 1),
        ("winner_merchant_ids_json", "[]"),
    ),
)
def test_authority_rejects_corrupt_certificate_result_or_winner_mapping(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    service, _clock, _merchants, market_id, _product_path, _ledger_path = _closed_feasible(tmp_path)
    assert column in {
        "canonical_certificate",
        "total_payment_paise",
        "winner_merchant_ids_json",
    }
    with service.store.connection(write=True) as connection:
        connection.execute(
            f"UPDATE product_market_results SET {column} = ? WHERE market_id = ?",
            (value, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


@pytest.mark.parametrize("winner_json", ("{", "{}", '"merchant-id"'))
def test_closed_clearing_rejects_malformed_or_wrong_shape_winner_ids(
    tmp_path: Path, winner_json: str
) -> None:
    service, _clock, _merchants, market_id, _product_path, _ledger_path = _closed_feasible(tmp_path)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_market_results SET winner_merchant_ids_json = ? WHERE market_id = ?",
            (winner_json, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_clearing_snapshot(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


@pytest.mark.parametrize("eligible_json", ("{", "{}", '"merchant-id"'))
def test_clearing_rejects_malformed_or_wrong_shape_eligible_ids(
    tmp_path: Path, eligible_json: str
) -> None:
    service, _clock, _merchants, market_id, _product_path, _ledger_path = _closed_feasible(tmp_path)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_markets SET eligible_merchant_ids_json = ? WHERE market_id = ?",
            (eligible_json, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_clearing_snapshot(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


@pytest.mark.parametrize("eligible_json", ("{", "{}"))
def test_market_listing_rejects_malformed_or_wrong_shape_eligible_ids(
    tmp_path: Path, eligible_json: str
) -> None:
    service, _clock, _merchants, market_id, _product_path, _ledger_path = _closed_feasible(tmp_path)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_markets SET eligible_merchant_ids_json = ? WHERE market_id = ?",
            (eligible_json, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.list_markets()

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_tamper_invokes_real_governor_once_per_call_before_any_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _clock, _merchants, market_id, _product_path, ledger_path = _closed_feasible(tmp_path)
    before = _result_record(service, market_id).canonical_certificate  # type: ignore[attr-defined]
    original_authorize = service_module.authorize_execution_v1
    governor_calls = 0

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("forbidden path invoked")

    def counted_authorize(**kwargs: object) -> ExecutionPlanV1:
        nonlocal governor_calls
        governor_calls += 1
        ledger = kwargs["ledger"]
        request = kwargs["request"]
        assert type(ledger) is SQLiteFinancialLedgerV1
        try:
            return original_authorize(**kwargs)  # type: ignore[arg-type]
        except MoneyGovernorError as error:
            assert error.code is MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
            assert ledger.get_execution_reservation(request.execution_id) is None  # type: ignore[attr-defined]
            raise

    monkeypatch.setattr(service_module, "authorize_execution_v1", counted_authorize)
    monkeypatch.setattr(service_module, "interpret_buyer_intent_v1", forbidden)
    monkeypatch.setattr(service_module, "propose_merchant_offer_candidate_v1", forbidden)

    tamper = service.test_market_authority_tamper(market_id)
    assert governor_calls == 1
    repeated = service.test_market_authority_tamper(market_id)

    after = _result_record(service, market_id).canonical_certificate  # type: ignore[attr-defined]
    assert governor_calls == 2
    assert repeated == tamper
    assert after == before
    assert tamper == {
        "market_id": market_id,
        "tamper_target": "buyer_policy_commitment_sha256",
        "persisted_certificate_mutated": False,
        "verifier": {
            "verified": False,
            "failure_code": "POLICY_COMMITMENT_MISMATCH",
        },
        "governor": {
            "invoked": True,
            "authorized": False,
            "failure_code": "CERTIFICATE_NOT_VERIFIED",
            "execution_plan_created": False,
            "persistent_reservation_created": False,
        },
        "provider_invoked": False,
        "altered_copy_authority": "THE MONEY GOVERNOR REJECTED THIS ALTERED COPY.",
        "altered_copy_money_action": "NO MONEY ACTION FOR THE ALTERED COPY.",
        "truth_class": "DETERMINISTIC FIXTURE",
    }
    with service.store.connection() as connection:
        assert service.store.get_execution_authority(connection, market_id) is None
    assert not ledger_path.exists()


def test_tamper_after_authorization_preserves_valid_certificate_and_reservation(
    tmp_path: Path,
) -> None:
    service, _clock, _merchants, market_id, _product_path, ledger_path = _closed_feasible(tmp_path)
    authorized = service.authorize_market_execution(market_id)
    plan = authorized["governor"]["execution_plan"]  # type: ignore[index]
    certificate_before = _result_record(service, market_id).canonical_certificate  # type: ignore[attr-defined]
    with service.store.connection() as connection:
        authority_before = service.store.get_execution_authority(connection, market_id)
    assert authority_before is not None
    ledger_before = ledger_path.read_bytes()
    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        reservation_before = ledger.get_execution_reservation(plan["execution_id"])
    assert reservation_before is not None

    tamper = service.test_market_authority_tamper(market_id)

    certificate_after = _result_record(service, market_id).canonical_certificate  # type: ignore[attr-defined]
    with service.store.connection() as connection:
        authority_after = service.store.get_execution_authority(connection, market_id)
    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        reservation_after = ledger.get_execution_reservation(plan["execution_id"])
    with sqlite3.connect(ledger_path) as connection:
        reservation_count = connection.execute(
            "SELECT COUNT(*) FROM clear_execution_reservations_v1"
        ).fetchone()
    assert certificate_after == certificate_before
    assert authority_after == authority_before
    assert ledger_path.read_bytes() == ledger_before
    assert reservation_after == reservation_before
    assert reservation_count == (1,)
    assert tamper["governor"] == {
        "invoked": True,
        "authorized": False,
        "failure_code": "CERTIFICATE_NOT_VERIFIED",
        "execution_plan_created": False,
        "persistent_reservation_created": False,
    }
    assert tamper["persisted_certificate_mutated"] is False
    assert tamper["altered_copy_authority"] == "THE MONEY GOVERNOR REJECTED THIS ALTERED COPY."


def test_explicit_authorize_uses_production_governor_and_persists_exact_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLEAR_AI_BASE_URL",
        "CLEAR_AI_API_KEY",
        "CLEAR_AI_PROVIDER_NAME",
        "CLEAR_AI_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)
    service, clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)
    events: list[str] = []
    captured: dict[str, object] = {}
    original_verify = service_module.verify_allocation_certificate_v2
    original_authorize = service_module.authorize_execution_v1

    def counted_verify(*args: object, **kwargs: object) -> object:
        events.append("verify")
        return original_verify(*args, **kwargs)  # type: ignore[arg-type]

    def counted_authorize(**kwargs: object) -> ExecutionPlanV1:
        events.append("governor")
        captured.update(kwargs)
        return original_authorize(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "verify_allocation_certificate_v2", counted_verify)
    monkeypatch.setattr(service_module, "authorize_execution_v1", counted_authorize)

    authority = service.authorize_market_execution(market_id)

    assert events[:2] == ["verify", "governor"]
    request = captured["request"]
    plan = authority["governor"]["execution_plan"]  # type: ignore[index]
    certificate = captured["certificate"]
    assert type(captured["ledger"]) is SQLiteFinancialLedgerV1
    assert UUID(request.execution_id).version == 4  # type: ignore[attr-defined]
    assert UUID(request.market_execution_authorization.authorization_id).version == 4  # type: ignore[attr-defined]
    assert UUID(request.buyer_financial_authorization.authorization_id).version == 4  # type: ignore[attr-defined]
    assert all(
        UUID(value.authorization_id).version == 4
        for value in request.merchant_recipient_authorizations  # type: ignore[attr-defined]
    )
    assert request.market_id == market_id  # type: ignore[attr-defined]
    assert request.certificate_digest_sha256 == plan["certificate_digest_sha256"]  # type: ignore[attr-defined]
    assert (
        request.buyer_financial_authorization.buyer_id
        == certificate.buyer_policy.market_spec.buyer_id
    )  # type: ignore[attr-defined]
    assert (
        request.buyer_financial_authorization.maximum_total_payment
        == certificate.buyer_policy.max_total_payment
    )  # type: ignore[attr-defined]
    certified_by_merchant: dict[str, int] = {}
    for line in certificate.allocation.lines:  # type: ignore[attr-defined]
        certified_by_merchant[line.merchant_id] = (
            certified_by_merchant.get(line.merchant_id, 0) + line.line_payment.amount_paise
        )
    assert {
        value.merchant_id: value.maximum_transfer.amount_paise
        for value in request.merchant_recipient_authorizations  # type: ignore[attr-defined]
    } == certified_by_merchant
    assert plan["order_amount_paise"] == certificate.allocation.total_payment.amount_paise  # type: ignore[attr-defined]
    assert [value["transfer_amount_paise"] for value in plan["transfer_obligations"]] == [
        line.line_payment.amount_paise
        for line in certificate.allocation.lines  # type: ignore[attr-defined]
    ]
    assert authority["governor"]["state"] == "AUTHORIZED"  # type: ignore[index]
    assert plan["provider_action"] == "NOT DEMONSTRATED"

    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        reservation = ledger.get_execution_reservation(plan["execution_id"])
    assert reservation is not None
    assert reservation.market_id == market_id
    assert reservation.certificate_digest_sha256 == plan["certificate_digest_sha256"]
    assert (
        reservation.execution_request_fingerprint_sha256
        == plan["execution_request_fingerprint_sha256"]
    )

    reopened = ProductService(product_path, clock=clock, financial_ledger_path=ledger_path)
    monkeypatch.setattr(service_module, "authorize_execution_v1", forbidden_governor)
    ledger_before = ledger_path.read_bytes()
    ledger_hash_before = sha256(ledger_before).hexdigest()
    assert reopened.get_market_authority(market_id) == authority
    ledger_after = ledger_path.read_bytes()
    assert ledger_after == ledger_before
    assert sha256(ledger_after).hexdigest() == ledger_hash_before


def forbidden_governor(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("GET invoked the Governor")


def test_concurrent_first_authorization_converges_on_one_request_and_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)
    with service.store.connection() as connection:
        assert service.store.get_execution_authority(connection, market_id) is None
        result = service.store.get_result(connection, market_id)
    assert result is not None
    assert not ledger_path.exists()

    services = [
        ProductService(product_path, clock=clock, financial_ledger_path=ledger_path)
        for _index in range(2)
    ]
    barrier = Barrier(2)
    original_authorize = service_module.authorize_execution_v1
    governor_execution_ids: list[str] = []

    def synchronized_authorize(**kwargs: object) -> ExecutionPlanV1:
        request = kwargs["request"]
        governor_execution_ids.append(request.execution_id)  # type: ignore[attr-defined]
        barrier.wait(timeout=5)
        return original_authorize(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "authorize_execution_v1", synchronized_authorize)

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(
            executor.map(
                lambda index: services[index].authorize_market_execution(market_id),
                range(2),
            )
        )

    plans = [value["governor"]["execution_plan"] for value in concurrent]  # type: ignore[index]
    assert [value["governor"]["state"] for value in concurrent] == [  # type: ignore[index]
        "AUTHORIZED",
        "AUTHORIZED",
    ]
    assert plans[0] == plans[1]
    assert plans[0]["execution_id"] == plans[1]["execution_id"]  # type: ignore[index]
    assert (
        plans[0]["execution_request_fingerprint_sha256"]  # type: ignore[index]
        == plans[1]["execution_request_fingerprint_sha256"]  # type: ignore[index]
    )
    assert governor_execution_ids == [plans[0]["execution_id"]] * 2  # type: ignore[index]
    with sqlite3.connect(product_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM product_execution_authorities WHERE market_id = ?",
            (market_id,),
        ).fetchone() == (1,)
    with sqlite3.connect(ledger_path) as connection:
        rows = connection.execute(
            """
            SELECT execution_id, market_id, certificate_digest_sha256,
                execution_request_fingerprint_sha256
            FROM clear_execution_reservations_v1
            WHERE market_id = ?
            """,
            (market_id,),
        ).fetchall()
    assert rows == [
        (
            plans[0]["execution_id"],  # type: ignore[index]
            market_id,
            result.certificate_digest,
            plans[0]["execution_request_fingerprint_sha256"],  # type: ignore[index]
        )
    ]
    assert services[0].authorize_market_execution(market_id) == concurrent[0]


def test_authorizing_recovery_reuses_request_execution_and_decision_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)

    def interrupt_persist(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(service.store, "mark_execution_authorized", interrupt_persist)
    with pytest.raises(ProductServiceError) as interrupted:
        service.authorize_market_execution(market_id)
    assert interrupted.value.code is ProductErrorCode.PERSISTED_DATA_INVALID
    with service.store.connection() as connection:
        claimed = service.store.get_execution_authority(connection, market_id)
    assert claimed is not None and claimed.state == "AUTHORIZING"

    recovered_service = ProductService(
        product_path,
        clock=clock,
        financial_ledger_path=ledger_path,
    )
    recovered = recovered_service.authorize_market_execution(market_id)
    with recovered_service.store.connection() as connection:
        authorized = recovered_service.store.get_execution_authority(connection, market_id)
    assert authorized is not None and authorized.state == "AUTHORIZED"
    assert authorized.execution_id == claimed.execution_id
    assert authorized.decision_time == claimed.decision_time
    assert authorized.canonical_request == claimed.canonical_request
    assert recovered["governor"]["execution_plan"]["execution_id"] == claimed.execution_id  # type: ignore[index]


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("canonical_request", b"{"),
        ("canonical_request", b'{"duplicate":1,"duplicate":2}'),
        ("canonical_plan", b"{"),
        ("execution_request_fingerprint_sha256", "0" * 64),
    ),
)
def test_authority_rejects_corrupt_persisted_request_plan_or_fingerprint(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    service, _clock, _merchants, market_id, _product_path, _ledger_path = _closed_feasible(tmp_path)
    service.authorize_market_execution(market_id)
    assert column in {
        "canonical_request",
        "canonical_plan",
        "execution_request_fingerprint_sha256",
    }
    with service.store.connection(write=True) as connection:
        connection.execute(
            f"UPDATE product_execution_authorities SET {column} = ? WHERE market_id = ?",
            (value, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        service.get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_authority_rejects_canonical_plan_bound_to_wrong_certificate(
    tmp_path: Path,
) -> None:
    service, clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)
    service.authorize_market_execution(market_id)
    with service.store.connection() as connection:
        record = service.store.get_execution_authority(connection, market_id)
    assert record is not None and record.canonical_plan is not None
    plan = service_module._parse_execution_plan(record.canonical_plan)
    altered = plan.model_copy(update={"certificate_digest_sha256": "0" * 64})
    altered_bytes = service_module._canonical_execution_plan_bytes(altered)
    with service.store.connection(write=True) as connection:
        connection.execute(
            "UPDATE product_execution_authorities SET canonical_plan = ? WHERE market_id = ?",
            (altered_bytes, market_id),
        )

    with pytest.raises(ProductServiceError) as raised:
        ProductService(
            product_path,
            clock=clock,
            financial_ledger_path=ledger_path,
        ).get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID


def test_authorized_product_record_requires_matching_financial_reservation(tmp_path: Path) -> None:
    service, clock, _merchants, market_id, product_path, _ledger_path = _closed_feasible(tmp_path)
    service.authorize_market_execution(market_id)
    missing_ledger = tmp_path / "missing-financial-ledger.sqlite3"

    with pytest.raises(ProductServiceError) as raised:
        ProductService(
            product_path,
            clock=clock,
            financial_ledger_path=missing_ledger,
        ).get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID
    assert not missing_ledger.exists()


def test_authority_get_does_not_initialize_existing_zero_byte_ledger(tmp_path: Path) -> None:
    service, clock, _merchants, market_id, product_path, _ledger_path = _closed_feasible(tmp_path)
    service.authorize_market_execution(market_id)
    zero_ledger = tmp_path / "zero-byte-financial-ledger.sqlite3"
    zero_ledger.touch()
    before = zero_ledger.read_bytes()

    with pytest.raises(ProductServiceError) as raised:
        ProductService(
            product_path,
            clock=clock,
            financial_ledger_path=zero_ledger,
        ).get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID
    assert before == b""
    assert zero_ledger.read_bytes() == before
    assert zero_ledger.stat().st_size == 0


def test_authority_get_does_not_mutate_wrong_schema_ledger(tmp_path: Path) -> None:
    service, clock, _merchants, market_id, product_path, _ledger_path = _closed_feasible(tmp_path)
    service.authorize_market_execution(market_id)
    wrong_ledger = tmp_path / "wrong-schema-financial-ledger.sqlite3"
    connection = sqlite3.connect(wrong_ledger)
    try:
        connection.execute(
            "CREATE TABLE clear_execution_reservations_v1 (execution_id TEXT NOT NULL)"
        )
        connection.commit()
    finally:
        connection.close()
    before = wrong_ledger.read_bytes()
    before_hash = sha256(before).hexdigest()

    with pytest.raises(ProductServiceError) as raised:
        ProductService(
            product_path,
            clock=clock,
            financial_ledger_path=wrong_ledger,
        ).get_market_authority(market_id)

    after = wrong_ledger.read_bytes()
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID
    assert after == before
    assert sha256(after).hexdigest() == before_hash


def test_authority_get_rejects_semantically_valid_lookalike_ledger(
    tmp_path: Path,
) -> None:
    service, clock, _merchants, market_id, product_path, ledger_path = _closed_feasible(tmp_path)
    authorized = service.authorize_market_execution(market_id)
    execution_id = authorized["governor"]["execution_plan"]["execution_id"]  # type: ignore[index]
    with SQLiteFinancialLedgerV1(str(ledger_path)) as ledger:
        reservation = ledger.get_execution_reservation(execution_id)
    assert reservation is not None

    lookalike_ledger = tmp_path / "lookalike-financial-ledger.sqlite3"
    connection = sqlite3.connect(lookalike_ledger)
    try:
        connection.execute(
            """
            CREATE TABLE clear_execution_reservations_v1 (
                execution_id TEXT,
                certificate_digest_version TEXT,
                certificate_digest_sha256 TEXT,
                market_id TEXT,
                execution_request_fingerprint_sha256 TEXT,
                reserved_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO clear_execution_reservations_v1
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                reservation.execution_id,
                reservation.certificate_digest_version,
                reservation.certificate_digest_sha256,
                reservation.market_id,
                reservation.execution_request_fingerprint_sha256,
                canonical_utc_datetime(reservation.reserved_at),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    before = lookalike_ledger.read_bytes()
    before_hash = sha256(before).hexdigest()

    with pytest.raises(ProductServiceError) as raised:
        ProductService(
            product_path,
            clock=clock,
            financial_ledger_path=lookalike_ledger,
        ).get_market_authority(market_id)

    after = lookalike_ledger.read_bytes()
    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID
    assert after == before
    assert sha256(after).hexdigest() == before_hash


def test_authority_get_rejects_malformed_reservation_without_mutating_ledger(
    tmp_path: Path,
) -> None:
    service, clock, _merchants, market_id, product_path, _ledger_path = _closed_feasible(tmp_path)
    authorized = service.authorize_market_execution(market_id)
    plan = authorized["governor"]["execution_plan"]  # type: ignore[index]
    malformed_ledger = tmp_path / "malformed-financial-ledger.sqlite3"
    connection = sqlite3.connect(malformed_ledger)
    try:
        connection.execute(
            """
            CREATE TABLE clear_execution_reservations_v1 (
                execution_id TEXT,
                certificate_digest_version TEXT,
                certificate_digest_sha256 TEXT,
                market_id TEXT,
                execution_request_fingerprint_sha256 TEXT,
                reserved_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO clear_execution_reservations_v1
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                plan["execution_id"],
                plan["certificate_digest_version"],
                plan["certificate_digest_sha256"],
                market_id,
                plan["execution_request_fingerprint_sha256"],
                "not-a-canonical-timestamp",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    before = malformed_ledger.read_bytes()

    with pytest.raises(ProductServiceError) as raised:
        ProductService(
            product_path,
            clock=clock,
            financial_ledger_path=malformed_ledger,
        ).get_market_authority(market_id)

    assert raised.value.code is ProductErrorCode.PERSISTED_DATA_INVALID
    assert malformed_ledger.read_bytes() == before


def test_infeasible_certificate_verifies_but_cannot_create_money_authority(
    tmp_path: Path,
) -> None:
    service, clock, merchants, _product_path, ledger_path = _runtime(tmp_path)
    market_id = _market(service, clock, list(merchants.values()))
    service.close_market(market_id)

    authority = service.get_market_authority(market_id)

    assert authority["certificate"]["allocation"]["status"] == "INFEASIBLE"  # type: ignore[index]
    assert authority["certificate"]["allocation"]["lines"] == []  # type: ignore[index]
    assert authority["verifier"]["verified"] is True  # type: ignore[index]
    assert authority["governor"] == {
        "state": "NOT_EXECUTABLE",
        "failure_code": "ALLOCATION_NOT_EXECUTABLE",
    }
    with pytest.raises(ProductServiceError) as raised:
        service.authorize_market_execution(market_id)
    assert raised.value.code is ProductErrorCode.ALLOCATION_NOT_EXECUTABLE
    with service.store.connection() as connection:
        assert service.store.get_execution_authority(connection, market_id) is None
    assert not ledger_path.exists()


def test_different_offer_prices_produce_dynamic_certificate_and_plan_facts(
    tmp_path: Path,
) -> None:
    first = _closed_feasible(tmp_path / "first", prices=(500, 600, 700))
    second = _closed_feasible(tmp_path / "second", prices=(800, 900, 1_000))

    first_authority = first[0].authorize_market_execution(first[3])
    second_authority = second[0].authorize_market_execution(second[3])

    assert (
        first_authority["certificate"]["digest_sha256"]
        != second_authority["certificate"][  # type: ignore[index]
            "digest_sha256"
        ]
    )
    assert (
        first_authority["certificate"]["allocation"]["total_payment_paise"]
        != second_authority[  # type: ignore[index]
            "certificate"
        ]["allocation"]["total_payment_paise"]
    )
    assert (
        first_authority["governor"]["execution_plan"]["order_amount_paise"]
        != second_authority[  # type: ignore[index]
            "governor"
        ]["execution_plan"]["order_amount_paise"]
    )


def test_frontend_authority_surface_is_server_read_only_until_explicit_actions() -> None:
    root = Path(__file__).resolve().parents[3]
    script = (root / "ui" / "product_app.js").read_text(encoding="utf-8")
    markup = (root / "ui" / "index.html").read_text(encoding="utf-8")
    tamper_block = script.split('runtimeTamperButton.addEventListener("click"', 1)[1].split(
        "if (runtimeAuthorizeButton instanceof HTMLButtonElement)", 1
    )[0]
    post_response_block = tamper_block.split("const response = await requestJSON", 1)[1]
    before_successful_render = post_response_block.split(
        'setRuntimeTamperText("verifier-failure-code", verifier.failure_code)', 1
    )[0]
    reset_block = script.split("const resetRuntimeTamper = () =>", 1)[1].split(
        "const setAuthorityRunning =", 1
    )[0]
    clear_authority_block = script.split("const clearRuntimeAuthorityPresentation = () =>", 1)[
        1
    ].split("const runtimeFact =", 1)[0]
    authorize_block = script.split('runtimeAuthorizeButton.addEventListener("click"', 1)[1].split(
        "const renderInterpretationFailure =", 1
    )[0]
    authorize_after_post = authorize_block.split("const response = await requestJSON", 1)[1]
    authorize_before_response_use = authorize_after_post.split("if (!response.ok)", 1)[0]
    authorize_catch = authorize_after_post.split("} catch (_error) {", 1)[1].split(
        "} finally {", 1
    )[0]
    authorize_finally = authorize_after_post.split("} finally {", 1)[1]

    assert "/authority" in script
    assert "/authority/tamper" in script
    assert "/authority/authorize" in script
    assert 'method: "POST", body: "{}"' in script
    assert "innerHTML" not in script
    assert ".sort(" not in script
    assert ".reduce(" not in script
    assert "allocated_quantity *" not in script
    assert "unit_payment_paise *" not in script
    assert "line.allocated_quantity" in script
    assert "certificate.certificate_id" in script
    assert "plan.certificate_digest_sha256" in script
    assert 'setRuntimeAuthorityText("replay-state", "VERIFIED")' in script
    assert '["allocated_" + "quantity"]' not in script
    assert '["certificate_" + "id"]' not in script
    assert '"VERI" + "FIED"' not in script
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        script,
        flags=re.IGNORECASE,
    )
    assert "AllocationCertificateV2" in markup
    assert "Money Governor" in markup
    assert "NO VALID CERTIFICATE = NO MONEY ACTION" in markup
    assert "INDEPENDENT REPLAY" in markup
    assert "NO RAZORPAY ACTION YET" in markup
    assert 'class="runtime-fixture-badge">DETERMINISTIC FIXTURE' in markup
    assert "renderRuntimeHeadings" not in script

    for required_contract in (
        "requestGeneration !== tamperRequestGeneration",
        "currentClearingMarketId !== marketId",
        "payload?.market_id !== marketId",
        "payload.persisted_certificate_mutated !== false",
        'typeof verifier !== "object"',
        "Array.isArray(verifier)",
        "verifier.verified !== false",
        'verifier.failure_code !== "POLICY_COMMITMENT_MISMATCH"',
        "!governor ||",
        'typeof governor !== "object"',
        "Array.isArray(governor)",
        "governor.invoked !== true",
        "governor.authorized !== false",
        "governor.failure_code !== tamperGovernorFailureCode",
        "governor.execution_plan_created !== false",
        "governor.persistent_reservation_created !== false",
        "payload.provider_invoked !== false",
        'payload.truth_class !== "DETERMINISTIC FIXTURE"',
        'typeof payload.altered_copy_authority !== "string"',
        "payload.altered_copy_authority.trim().length === 0",
        'typeof payload.altered_copy_money_action !== "string"',
        "payload.altered_copy_money_action.trim().length === 0",
    ):
        assert required_contract in before_successful_render
    assert 'const tamperGovernorFailureCode = "CERTIFICATE_NOT_VERIFIED"' in script
    assert (
        'setRuntimeTamperText("verifier-failure-code", verifier.failure_code)'
        in post_response_block
    )
    assert (
        'setRuntimeTamperText("governor-failure-code", governor.failure_code)'
        in post_response_block
    )
    assert (
        'setRuntimeTamperText("control-copy", payload.altered_copy_authority)'
        in post_response_block
    )
    assert (
        'setRuntimeTamperText("money-copy", payload.altered_copy_money_action)'
        in post_response_block
    )
    assert "THE MONEY GOVERNOR REJECTED THIS ALTERED COPY." not in script
    assert "NO MONEY ACTION FOR THE ALTERED COPY." not in script
    assert "THE MONEY GOVERNOR REJECTED THIS ALTERED COPY." not in markup
    assert "NO MONEY ACTION FOR THE ALTERED COPY." not in markup
    assert "INDEPENDENT VERIFIER" in markup
    assert "MONEY GOVERNOR" in markup
    assert 'data-tamper-field="verifier-failure-code">—' in markup
    assert 'data-tamper-field="governor-failure-code">—' in markup
    assert 'setRuntimeTamperText("verifier-failure-code", "—")' in reset_block
    assert 'setRuntimeTamperText("governor-failure-code", "—")' in reset_block
    assert 'setRuntimeTamperText("control-copy", "—")' in reset_block
    assert 'setRuntimeTamperText("money-copy", "—")' in reset_block

    assert "++authorizeRequestGeneration" in clear_authority_block
    assert "const requestGeneration = ++authorizeRequestGeneration" in authorize_block
    for stale_contract in (
        "requestGeneration !== authorizeRequestGeneration",
        "currentClearingMarketId !== marketId",
    ):
        assert stale_contract in authorize_before_response_use
        assert stale_contract in authorize_catch.split("if (runtimeAuthorityStatus)", 1)[0]
        assert stale_contract in authorize_catch.split("await loadRuntimeAuthority", 1)[0]
    assert (
        "requestGeneration === authorizeRequestGeneration"
        in authorize_finally.split("setAuthorityRunning(false)", 1)[0]
    )
    assert (
        "currentClearingMarketId === marketId"
        in authorize_finally.split("setAuthorityRunning(false)", 1)[0]
    )
