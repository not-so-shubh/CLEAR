from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest

from clear_market.certificate.v2 import (
    AllocationCertificateV2,
    AllocationClaimStatusV2,
    MerchantOfferAdmissionDecisionV2,
    allocation_certificate_v2_digest,
)
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.domain import Money
from clear_market.execution import (
    BuyerFinancialAuthorizationV1,
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    MarketExecutionAuthorizationV1,
    MarketExecutionStateV1,
    MerchantRecipientAuthorizationV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
    authorize_execution_v1,
    execution_request_fingerprint_v1,
)
from clear_market.persistence import (
    ExecutionReservationDispositionV1,
    ExecutionReservationV1,
    PersistenceError,
    PersistenceErrorCode,
    open_sqlite_financial_ledger_v1,
)
from clear_market.verification.v2 import verify_allocation_certificate_v2
from tests.certificate.v2.test_serialization import (
    _certificate,
    _identity,
    _policy,
    _validated_copy,
)
from tests.execution.test_models import (
    _BUYER_AUTHORIZATION_ID,
    _DIGEST_VERSION,
    _EXECUTION_ID,
    _MARKET_AUTHORIZATION_ID,
    _TIME,
    _VALID_FROM,
    _VALID_UNTIL,
    _uuid,
)
from tests.verification.v2.test_verifier import (
    _certificate_for,
    _tampered_allocation,
    _trusted,
)


def _recipient_for_merchant(
    merchant_id: str,
    *,
    digest: str,
    market_id: str,
    index: int,
    maximum: int,
    valid_from: datetime = _VALID_FROM,
    valid_until: datetime = _VALID_UNTIL,
) -> MerchantRecipientAuthorizationV1:
    return MerchantRecipientAuthorizationV1(
        authorization_id=_uuid(4, index),
        merchant_id=merchant_id,
        recipient_id=f"clear.recipient.m{index}",
        market_id=market_id,
        certificate_digest_version=_DIGEST_VERSION,
        certificate_digest_sha256=digest,
        maximum_transfer=Money(amount_paise=maximum),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _request_for(
    certificate: AllocationCertificateV2,
    *,
    execution_id: str = _EXECUTION_ID,
    digest: str | None = None,
    market_id: str | None = None,
    market_state: MarketExecutionStateV1 = MarketExecutionStateV1.EXECUTABLE,
    market_authorization_id: str = _MARKET_AUTHORIZATION_ID,
    market_valid_from: datetime = _VALID_FROM,
    market_valid_until: datetime = _VALID_UNTIL,
    buyer_id: str | None = None,
    buyer_maximum: int = 2_700,
    buyer_valid_from: datetime = _VALID_FROM,
    buyer_valid_until: datetime = _VALID_UNTIL,
    recipients: tuple[MerchantRecipientAuthorizationV1, ...] | None = None,
) -> ExecutionAuthorizationRequestV1:
    bound_digest = digest or allocation_certificate_v2_digest(certificate)
    bound_market = market_id or certificate.buyer_policy.market_spec.market_id
    market = MarketExecutionAuthorizationV1(
        authorization_id=market_authorization_id,
        market_id=bound_market,
        certificate_digest_version=_DIGEST_VERSION,
        certificate_digest_sha256=bound_digest,
        state=market_state,
        valid_from=market_valid_from,
        valid_until=market_valid_until,
    )
    buyer = BuyerFinancialAuthorizationV1(
        authorization_id=_BUYER_AUTHORIZATION_ID,
        buyer_id=buyer_id or certificate.buyer_policy.market_spec.buyer_id,
        market_id=bound_market,
        certificate_digest_version=_DIGEST_VERSION,
        certificate_digest_sha256=bound_digest,
        maximum_total_payment=Money(amount_paise=buyer_maximum),
        valid_from=buyer_valid_from,
        valid_until=buyer_valid_until,
    )
    if recipients is None:
        recipient_values = (
            _recipient_for_merchant(
                certificate.allocation.lines[0].merchant_id,
                digest=bound_digest,
                market_id=bound_market,
                index=1,
                maximum=1_500,
            ),
            _recipient_for_merchant(
                certificate.allocation.lines[1].merchant_id,
                digest=bound_digest,
                market_id=bound_market,
                index=2,
                maximum=1_200,
            ),
        )
    else:
        recipient_values = recipients
    return ExecutionAuthorizationRequestV1(
        execution_id=execution_id,
        certificate_digest_version=_DIGEST_VERSION,
        certificate_digest_sha256=bound_digest,
        market_id=bound_market,
        market_execution_authorization=market,
        buyer_financial_authorization=buyer,
        merchant_recipient_authorizations=recipient_values,
    )


def _assert_governor_failure(
    *,
    certificate: AllocationCertificateV2,
    trusted: tuple[MerchantSigningIdentityV2, ...],
    request: ExecutionAuthorizationRequestV1,
    path: Path,
    expected: MoneyGovernorFailureCode,
    decision_time: datetime = _TIME,
) -> None:
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        with pytest.raises(MoneyGovernorError) as caught:
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=trusted,
                request=request,
                decision_time=decision_time,
                ledger=ledger,
            )
        assert caught.value.code is expected
        assert str(caught.value) == expected.value
        assert ledger.get_execution_reservation(request.execution_id) is None


def test_successful_governor_plan_and_durable_reservation_are_exact(tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        plan = authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=request,
            decision_time=_TIME,
            ledger=ledger,
        )
        reservation = ledger.get_execution_reservation(request.execution_id)

    assert isinstance(plan, ExecutionPlanV1)
    assert plan.order_amount == Money(amount_paise=2_700)
    assert tuple(line.transfer_amount.amount_paise for line in plan.transfer_lines) == (
        1_500,
        1_200,
    )
    assert tuple(line.allocated_quantity for line in plan.transfer_lines) == (3, 2)
    assert tuple(line.recipient_id for line in plan.transfer_lines) == (
        "clear.recipient.m1",
        "clear.recipient.m2",
    )
    assert tuple(line.offer_id for line in plan.transfer_lines) == tuple(
        line.offer_id for line in certificate.allocation.lines
    )
    assert tuple(line.sku_id for line in plan.transfer_lines) == tuple(
        line.sku_id for line in certificate.allocation.lines
    )
    assert plan.idempotency_key == f"clear.execution.v1:{request.execution_id}"
    assert not hasattr(plan.transfer_lines[0], "provider_account_id")
    assert reservation is not None
    assert reservation.execution_id == request.execution_id
    assert reservation.certificate_digest_sha256 == allocation_certificate_v2_digest(certificate)
    assert reservation.market_id == request.market_id
    assert reservation.execution_request_fingerprint_sha256 == execution_request_fingerprint_v1(
        request
    )
    assert reservation.reserved_at == _TIME
    assert "approved_at" not in type(plan).model_fields
    assert "reserved_at" not in type(plan).model_fields
    assert "decision_time" not in type(plan).model_fields


@pytest.mark.parametrize(
    "kind", ["empty_trust", "altered_key", "false_admission", "false_allocation"]
)
def test_invalid_certificate_never_creates_reservation(kind: str, tmp_path: Path) -> None:
    certificate = _certificate()
    trusted = _trusted()
    if kind == "empty_trust":
        trusted = ()
    elif kind == "altered_key":
        trusted = (
            _identity(1, public_key_hex=_identity(2).ed25519_public_key_hex),
            _identity(2),
        )
    elif kind == "false_admission":
        first = _validated_copy(
            certificate.merchant_offer_evidence[0],
            admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
        )
        certificate = _validated_copy(
            certificate,
            merchant_offer_evidence=(first, *certificate.merchant_offer_evidence[1:]),
        )
    elif kind == "false_allocation":
        certificate = _validated_copy(certificate, allocation=_tampered_allocation("soft_score"))
    else:
        raise AssertionError(kind)
    _assert_governor_failure(
        certificate=certificate,
        trusted=trusted,
        request=_request_for(certificate),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED,
    )


def test_verified_infeasible_certificate_is_not_executable(tmp_path: Path) -> None:
    policy = _policy()
    certificate = _certificate_for(policy=policy, evidence=(), admitted_offers=())
    assert certificate.allocation.status is AllocationClaimStatusV2.INFEASIBLE
    assert verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=_trusted(),
    ).verified
    digest = allocation_certificate_v2_digest(certificate)
    recipient = _recipient_for_merchant(
        policy.eligible_merchant_ids[0],
        digest=digest,
        market_id=policy.market_spec.market_id,
        index=1,
        maximum=0,
    )
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(certificate, recipients=(recipient,)),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.ALLOCATION_NOT_EXECUTABLE,
    )


@pytest.mark.parametrize("kind", ["digest", "market"])
def test_request_must_bind_actual_certificate_digest_and_market(kind: str, tmp_path: Path) -> None:
    certificate = _certificate()
    changes: dict[str, str] = (
        {"digest": "f" * 64}
        if kind == "digest"
        else {"market_id": "e9000000-0000-4000-8000-000000000001"}
    )
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(certificate, **changes),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.EXECUTION_REQUEST_MISMATCH,
    )


@pytest.mark.parametrize("state", [MarketExecutionStateV1.PAUSED, MarketExecutionStateV1.CLOSED])
def test_nonexecutable_market_state_fails_without_reservation(
    state: MarketExecutionStateV1,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(certificate, market_state=state),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.MARKET_NOT_EXECUTABLE,
    )


@pytest.mark.parametrize("decision_time", [_VALID_FROM, _VALID_UNTIL])
def test_market_authorization_time_bounds_are_inclusive(
    decision_time: datetime,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert isinstance(
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=decision_time,
                ledger=ledger,
            ),
            ExecutionPlanV1,
        )
        reservation = ledger.get_execution_reservation(request.execution_id)
    assert reservation is not None
    assert reservation.reserved_at == decision_time


@pytest.mark.parametrize(
    "decision_time",
    [_VALID_FROM - timedelta(microseconds=1), _VALID_UNTIL + timedelta(microseconds=1)],
)
def test_market_authorization_outside_window_fails(
    decision_time: datetime,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(certificate),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.MARKET_AUTHORIZATION_NOT_ACTIVE,
        decision_time=decision_time,
    )


def test_buyer_identity_must_match_verified_policy(tmp_path: Path) -> None:
    certificate = _certificate()
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(
            certificate=certificate,
            buyer_id="e8000000-0000-4000-8000-000000000001",
        ),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.BUYER_AUTHORIZATION_MISMATCH,
    )


@pytest.mark.parametrize("decision_time", [_VALID_FROM, _VALID_UNTIL])
def test_buyer_and_recipient_time_bounds_are_inclusive(
    decision_time: datetime,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert isinstance(
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=decision_time,
                ledger=ledger,
            ),
            ExecutionPlanV1,
        )
        reservation = ledger.get_execution_reservation(request.execution_id)
    assert reservation is not None
    assert reservation.reserved_at == decision_time


@pytest.mark.parametrize(
    "decision_time",
    [_VALID_FROM - timedelta(microseconds=1), _VALID_UNTIL + timedelta(microseconds=1)],
)
def test_buyer_authorization_outside_window_fails_after_active_market(
    decision_time: datetime,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(
        certificate,
        market_valid_from=_VALID_FROM - timedelta(hours=1),
        market_valid_until=_VALID_UNTIL + timedelta(hours=1),
    )
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=request,
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.BUYER_AUTHORIZATION_NOT_ACTIVE,
        decision_time=decision_time,
    )


@pytest.mark.parametrize(
    ("maximum", "expected"),
    [(2_700, None), (2_699, MoneyGovernorFailureCode.BUYER_BUDGET_EXCEEDED)],
)
def test_buyer_payment_ceiling_is_inclusive(
    maximum: int,
    expected: MoneyGovernorFailureCode | None,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(certificate, buyer_maximum=maximum)
    path = tmp_path / "ledger.db"
    if expected is not None:
        _assert_governor_failure(
            certificate=certificate,
            trusted=_trusted(),
            request=request,
            path=path,
            expected=expected,
        )
        return
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert (
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=_TIME,
                ledger=ledger,
            ).order_amount.amount_paise
            == 2_700
        )


@pytest.mark.parametrize("kind", ["missing", "extra"])
def test_recipient_authorization_set_must_exactly_equal_winners(kind: str, tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    first, second = request.merchant_recipient_authorizations
    recipients = (first,)
    if kind == "extra":
        recipients = (
            first,
            second,
            _recipient_for_merchant(
                "b3000000-0003-4000-8000-000000000001",
                digest=request.certificate_digest_sha256,
                market_id=request.market_id,
                index=3,
                maximum=100,
            ),
        )
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(certificate, recipients=recipients),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.RECIPIENT_SET_MISMATCH,
    )


@pytest.mark.parametrize("boundary", ["from", "until"])
def test_recipient_authorization_time_bounds_are_inclusive(boundary: str, tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    decision_time = _VALID_FROM if boundary == "from" else _VALID_UNTIL
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert isinstance(
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=decision_time,
                ledger=ledger,
            ),
            ExecutionPlanV1,
        )
        reservation = ledger.get_execution_reservation(request.execution_id)
    assert reservation is not None
    assert reservation.reserved_at == decision_time


@pytest.mark.parametrize("offset", [-1, 1])
def test_recipient_authorization_outside_window_fails(offset: int, tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    first, second = request.merchant_recipient_authorizations
    if offset < 0:
        first = _validated_copy(first, valid_from=_TIME + timedelta(microseconds=1))
    else:
        first = _validated_copy(first, valid_until=_TIME - timedelta(microseconds=1))
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=_request_for(certificate, recipients=(first, second)),
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.RECIPIENT_AUTHORIZATION_NOT_ACTIVE,
    )


@pytest.mark.parametrize(
    ("maximum", "expected"),
    [(1_500, None), (1_499, MoneyGovernorFailureCode.RECIPIENT_TRANSFER_LIMIT_EXCEEDED)],
)
def test_merchant_aggregate_transfer_ceiling_is_inclusive(
    maximum: int,
    expected: MoneyGovernorFailureCode | None,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    first, second = request.merchant_recipient_authorizations
    first = _validated_copy(first, maximum_transfer=Money(amount_paise=maximum))
    request = _request_for(certificate, recipients=(first, second))
    path = tmp_path / "ledger.db"
    if expected is not None:
        _assert_governor_failure(
            certificate=certificate,
            trusted=_trusted(),
            request=request,
            path=path,
            expected=expected,
        )
        return
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert (
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=_TIME,
                ledger=ledger,
            ).order_amount.amount_paise
            == 2_700
        )


def test_idempotent_retry_uses_original_reservation_time_and_same_plan(tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    later = _TIME + timedelta(minutes=10)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        first = authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=request,
            decision_time=_TIME,
            ledger=ledger,
        )
        second = authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=request,
            decision_time=later,
            ledger=ledger,
        )
        reservation = ledger.get_execution_reservation(request.execution_id)
    assert first == second
    assert reservation is not None
    assert reservation.reserved_at == _TIME


def test_compatible_preexisting_reservation_timestamp_is_not_plan_authority(
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    stale_reserved_at = request.market_execution_authorization.valid_from - timedelta(days=1)
    reservation = ExecutionReservationV1(
        execution_id=request.execution_id,
        certificate_digest_version=request.certificate_digest_version,
        certificate_digest_sha256=request.certificate_digest_sha256,
        market_id=request.market_id,
        execution_request_fingerprint_sha256=execution_request_fingerprint_v1(request),
        reserved_at=stale_reserved_at,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert (
            ledger.reserve_execution(reservation).disposition
            is ExecutionReservationDispositionV1.CREATED
        )
        plan = authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=request,
            decision_time=_TIME,
            ledger=ledger,
        )
        stored = ledger.get_execution_reservation(request.execution_id)
    assert isinstance(plan, ExecutionPlanV1)
    assert "approved_at" not in type(plan).model_fields
    assert "reserved_at" not in type(plan).model_fields
    assert "decision_time" not in type(plan).model_fields
    assert stored == reservation
    assert stored.reserved_at == stale_reserved_at


def test_same_execution_with_materially_changed_request_conflicts(tmp_path: Path) -> None:
    certificate = _certificate()
    first = _request_for(certificate)
    changed = _request_for(certificate, market_authorization_id=_uuid(2, 9))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=first,
            decision_time=_TIME,
            ledger=ledger,
        )
        with pytest.raises(MoneyGovernorError) as caught:
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=changed,
                decision_time=_TIME,
                ledger=ledger,
            )
        assert caught.value.code is MoneyGovernorFailureCode.EXECUTION_ID_CONFLICT
        stored = ledger.get_execution_reservation(first.execution_id)
        assert stored is not None
        assert stored.execution_request_fingerprint_sha256 == execution_request_fingerprint_v1(
            first
        )


def test_different_execution_for_same_certificate_is_rejected(tmp_path: Path) -> None:
    certificate = _certificate()
    first = _request_for(certificate)
    second = _request_for(certificate, execution_id=_uuid(1, 2))
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=first,
            decision_time=_TIME,
            ledger=ledger,
        )
        with pytest.raises(MoneyGovernorError) as caught:
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=second,
                decision_time=_TIME,
                ledger=ledger,
            )
        assert caught.value.code is MoneyGovernorFailureCode.CERTIFICATE_ALREADY_EXECUTED
        assert ledger.get_execution_reservation(second.execution_id) is None


def test_preexisting_other_certificate_for_market_causes_market_conflict(tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    other = ExecutionReservationV1(
        execution_id=_uuid(1, 9),
        certificate_digest_version=_DIGEST_VERSION,
        certificate_digest_sha256="f" * 64,
        market_id=request.market_id,
        execution_request_fingerprint_sha256="e" * 64,
        reserved_at=_TIME,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert (
            ledger.reserve_execution(other).disposition is ExecutionReservationDispositionV1.CREATED
        )
        with pytest.raises(MoneyGovernorError) as caught:
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=_TIME,
                ledger=ledger,
            )
        assert caught.value.code is MoneyGovernorFailureCode.MARKET_ALREADY_EXECUTED
        assert ledger.get_execution_reservation(request.execution_id) is None


def test_concurrent_requests_for_same_certificate_create_one_plan(tmp_path: Path) -> None:
    certificate = _certificate()
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)):
        pass
    requests = (
        _request_for(certificate, execution_id=_uuid(1, 1)),
        _request_for(certificate, execution_id=_uuid(1, 2)),
    )
    barrier = Barrier(2)

    def run(request: ExecutionAuthorizationRequestV1) -> ExecutionPlanV1 | MoneyGovernorFailureCode:
        barrier.wait()
        with open_sqlite_financial_ledger_v1(str(path)) as ledger:
            try:
                return authorize_execution_v1(
                    certificate=certificate,
                    trusted_signing_identities=_trusted(),
                    request=request,
                    decision_time=_TIME,
                    ledger=ledger,
                )
            except MoneyGovernorError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(run, requests))
    assert sum(type(result) is ExecutionPlanV1 for result in results) == 1
    assert results.count(MoneyGovernorFailureCode.CERTIFICATE_ALREADY_EXECUTED) == 1
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert (
            sum(
                ledger.get_execution_reservation(request.execution_id) is not None
                for request in requests
            )
            == 1
        )


def test_existing_reservation_cannot_bypass_invalid_certificate(tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    reservation = ExecutionReservationV1(
        execution_id=request.execution_id,
        certificate_digest_version=request.certificate_digest_version,
        certificate_digest_sha256=request.certificate_digest_sha256,
        market_id=request.market_id,
        execution_request_fingerprint_sha256=execution_request_fingerprint_v1(request),
        reserved_at=_TIME,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(reservation)
        with pytest.raises(MoneyGovernorError) as caught:
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=(),
                request=request,
                decision_time=_TIME,
                ledger=ledger,
            )
        assert caught.value.code is MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
        assert ledger.get_execution_reservation(request.execution_id) == reservation


def test_retry_after_buyer_authorization_expiry_fails(tmp_path: Path) -> None:
    certificate = _certificate()
    buyer_until = _TIME + timedelta(minutes=1)
    request = _request_for(
        certificate,
        market_valid_until=_VALID_UNTIL + timedelta(hours=1),
        buyer_valid_until=buyer_until,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert isinstance(
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=_TIME,
                ledger=ledger,
            ),
            ExecutionPlanV1,
        )
        reservation = ledger.get_execution_reservation(request.execution_id)
        assert reservation is not None
        with pytest.raises(MoneyGovernorError) as caught:
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=request,
                decision_time=buyer_until + timedelta(microseconds=1),
                ledger=ledger,
            )
        assert caught.value.code is MoneyGovernorFailureCode.BUYER_AUTHORIZATION_NOT_ACTIVE
        assert ledger.get_execution_reservation(request.execution_id) == reservation


def test_closed_ledger_error_propagates_without_governor_wrapping(tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(certificate)
    ledger = open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db"))
    ledger.close()
    with pytest.raises(PersistenceError) as caught:
        authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            request=request,
            decision_time=_TIME,
            ledger=ledger,
        )
    assert caught.value.code is PersistenceErrorCode.CLOSED


@pytest.mark.parametrize("decision_time", [datetime(2026, 9, 1, 11, 30), "now", None])
def test_decision_time_must_be_caller_supplied_aware_datetime(
    decision_time: object,
    tmp_path: Path,
) -> None:
    certificate = _certificate()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        with pytest.raises(ValueError):
            authorize_execution_v1(
                certificate=certificate,
                trusted_signing_identities=_trusted(),
                request=_request_for(certificate),
                decision_time=cast(Any, decision_time),
                ledger=ledger,
            )


def test_failure_precedence_is_market_then_buyer_then_recipient(tmp_path: Path) -> None:
    certificate = _certificate()
    request = _request_for(
        certificate,
        market_state=MarketExecutionStateV1.PAUSED,
        buyer_id="e8000000-0000-4000-8000-000000000001",
        buyer_maximum=1,
        recipients=(_request_for(certificate).merchant_recipient_authorizations[0],),
    )
    _assert_governor_failure(
        certificate=certificate,
        trusted=_trusted(),
        request=request,
        path=tmp_path / "ledger.db",
        expected=MoneyGovernorFailureCode.MARKET_NOT_EXECUTABLE,
    )
