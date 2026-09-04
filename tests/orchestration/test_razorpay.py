import inspect
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import clear_market.orchestration.razorpay as orchestration_module
import clear_market.payments.razorpay.orders as orders_module
import clear_market.payments.transfers.razorpay as transfers_module
from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.domain import Money
from clear_market.execution import (
    MoneyGovernorError,
    MoneyGovernorFailureCode,
)
from clear_market.orchestration import (
    RazorpayExecutionStageV1,
    run_razorpay_test_execution_v1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    RazorpayRouteMappingError,
    RazorpayRouteMappingFailureCode,
    RazorpayRouteMappingRequestV1,
    build_razorpay_route_mapping_v1,
)
from clear_market.payments.state import (
    ClearPaymentStateV1,
    PaymentStateError,
    PaymentStateFailureCode,
)
from clear_market.payments.transfers import (
    RazorpayTransferBatchDispositionV1,
    RazorpayTransferError,
    RazorpayTransferFailureCode,
)
from clear_market.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)
from tests.certificate.v2.test_serialization import _certificate, _validated_copy
from tests.execution.test_governor import _request_for
from tests.execution.test_models import _TIME, _VALID_UNTIL
from tests.orchestration.test_models import _order_result, _payment_state
from tests.payments.razorpay.test_orders import (
    _Boundary as _OrderBoundary,
)
from tests.payments.razorpay.test_orders import (
    _credentials,
    _response,
)
from tests.payments.razorpay.test_route_models import _binding
from tests.payments.razorpay.test_webhooks import (
    _ACCOUNT_ID,
    _body,
    _ingest,
    _signature,
)
from tests.payments.transfers.test_razorpay import (
    _Boundary as _TransferBoundary,
)
from tests.verification.v2.test_verifier import _tampered_allocation, _trusted


@pytest.fixture
def ledger(tmp_path: Path):
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as value:
        yield value


def _bindings():
    return (_binding(2), _binding(1))


def _run(
    ledger: SQLiteFinancialLedgerV1,
    *,
    certificate: AllocationCertificateV2 | None = None,
    trusted: Any | None = None,
    decision_time: Any = _TIME,
):
    selected = certificate or _certificate()
    return run_razorpay_test_execution_v1(
        certificate=selected,
        trusted_signing_identities=_trusted() if trusted is None else trusted,
        execution_request=_request_for(selected),
        linked_account_bindings=_bindings(),
        expected_razorpay_account_id=_ACCOUNT_ID,
        decision_time=decision_time,
        ledger=ledger,
        credentials=_credentials(),
    )


def _install_order(
    monkeypatch: pytest.MonkeyPatch,
    outcome: tuple[int, bytes] | BaseException | None = None,
) -> _OrderBoundary:
    boundary = _OrderBoundary(outcome or (200, _response()))
    monkeypatch.setattr(orders_module, "_https_request", boundary)
    return boundary


def _record_webhook(
    ledger: SQLiteFinancialLedgerV1,
    event_type: str,
    *,
    event_id: str,
) -> None:
    raw_body = _body(event_type=event_type)
    _ingest(
        ledger,
        raw_body=raw_body,
        signature_header=_signature(raw_body),
        event_id_header=event_id,
    )


def _mapping(result: Any):
    return build_razorpay_route_mapping_v1(
        request=RazorpayRouteMappingRequestV1(
            execution_plan=result.execution_plan,
            linked_account_bindings=_bindings(),
        ),
        decision_time=_TIME,
    )


def test_public_function_accepts_only_raw_authority_inputs() -> None:
    signature = inspect.signature(run_razorpay_test_execution_v1)
    assert tuple(signature.parameters) == (
        "certificate",
        "trusted_signing_identities",
        "execution_request",
        "linked_account_bindings",
        "expected_razorpay_account_id",
        "decision_time",
        "ledger",
        "credentials",
    )
    assert (
        not {
            "execution_plan",
            "order_result",
            "payment_state",
            "route_mapping_plan",
            "transfer_batch",
        }
        & signature.parameters.keys()
    )


def test_order_ready_creation_and_rerun_use_post_then_get_without_transfers(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _install_order(monkeypatch)

    def no_transfers(**_kwargs: object) -> None:
        raise AssertionError("transfer adapter must not run before capture")

    monkeypatch.setattr(
        orchestration_module,
        "create_or_reconcile_razorpay_test_transfers_v1",
        no_transfers,
    )
    created = _run(ledger)
    existing = _run(ledger)

    assert created.stage is RazorpayExecutionStageV1.ORDER_READY
    assert created.order_result.resolution is RazorpayOrderResolutionV1.CREATED
    assert created.payment_state.state is ClearPaymentStateV1.ORDER_CREATED
    assert created.transfer_batch is None
    assert existing.stage is RazorpayExecutionStageV1.ORDER_READY
    assert existing.order_result.resolution is RazorpayOrderResolutionV1.EXISTING
    assert existing.payment_state.state is ClearPaymentStateV1.ORDER_CREATED
    assert existing.transfer_batch is None
    assert [call["method"] for call in order_boundary.calls] == ["POST", "GET"]


@pytest.mark.parametrize(
    ("event_type", "expected_stage", "expected_state"),
    (
        (
            "payment.authorized",
            RazorpayExecutionStageV1.PAYMENT_AUTHORIZED,
            ClearPaymentStateV1.PAYMENT_AUTHORIZED,
        ),
        (
            "payment.failed",
            RazorpayExecutionStageV1.PAYMENT_FAILED_OBSERVED,
            ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED,
        ),
    ),
)
def test_noncaptured_payment_observations_never_invoke_transfer_adapter(
    event_type: str,
    expected_stage: RazorpayExecutionStageV1,
    expected_state: ClearPaymentStateV1,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _install_order(monkeypatch)
    _run(ledger)
    _record_webhook(ledger, event_type, event_id=f"event-{event_type}")

    def no_transfers(**_kwargs: object) -> None:
        raise AssertionError("transfer adapter must not run without captured payment")

    monkeypatch.setattr(
        orchestration_module,
        "create_or_reconcile_razorpay_test_transfers_v1",
        no_transfers,
    )
    result = _run(ledger)
    assert result.stage is expected_stage
    assert result.order_result.resolution is RazorpayOrderResolutionV1.EXISTING
    assert result.payment_state.state is expected_state
    assert result.transfer_batch is None
    assert [call["method"] for call in order_boundary.calls] == ["POST", "GET"]


def test_captured_payment_creates_then_reconciles_transfer_batch_without_second_post(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _install_order(monkeypatch)
    ready = _run(ledger)
    _record_webhook(ledger, "payment.captured", event_id="event-captured")
    transfer_boundary = _TransferBoundary(_mapping(ready))
    monkeypatch.setattr(transfers_module, "_https_request", transfer_boundary)

    created = _run(ledger)
    existing = _run(ledger)

    assert created.stage is RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED
    assert created.payment_state.state is ClearPaymentStateV1.PAYMENT_CAPTURED
    assert created.transfer_batch is not None
    assert created.transfer_batch.disposition is RazorpayTransferBatchDispositionV1.CREATED
    assert existing.stage is RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED
    assert existing.transfer_batch is not None
    assert existing.transfer_batch.disposition is RazorpayTransferBatchDispositionV1.EXISTING
    assert transfer_boundary.post_count == 1
    assert transfer_boundary.paths.count("/v1/payments/pay_CLEARReview1/transfers") == 3
    assert [call["method"] for call in order_boundary.calls] == ["POST", "GET", "GET"]


def test_order_creation_uncertainty_propagates_and_orchestrator_never_recovers_or_posts_twice(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_order(monkeypatch, ConnectionError("provider transport"))
    with pytest.raises(RazorpayOrderError) as first:
        _run(ledger)
    assert first.value.code is RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED
    assert boundary.post_count == 1

    with pytest.raises(RazorpayOrderError) as retry:
        _run(ledger)
    assert retry.value.code is RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED
    assert boundary.post_count == 1
    assert boundary.get_count == 0


def test_transfer_creation_uncertainty_reconciles_with_get_only_and_propagates(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_order(monkeypatch)
    ready = _run(ledger)
    _record_webhook(ledger, "payment.captured", event_id="event-captured")
    boundary = _TransferBoundary(_mapping(ready), post=ConnectionError("provider transport"))
    monkeypatch.setattr(transfers_module, "_https_request", boundary)

    with pytest.raises(RazorpayTransferError) as first:
        _run(ledger)
    assert first.value.code is RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
    assert boundary.post_count == 1
    with pytest.raises(RazorpayTransferError) as retry:
        _run(ledger)
    assert retry.value.code is RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
    assert boundary.post_count == 1
    assert boundary.paths[-1] == "/v1/payments/pay_CLEARReview1/transfers"


@pytest.mark.parametrize("failure", ("invalid_certificate", "empty_trust", "expired"))
def test_governor_failures_precede_every_provider_call(
    failure: str,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _install_order(monkeypatch)
    certificate = _certificate()
    trusted: Any = _trusted()
    decision_time = _TIME
    if failure == "invalid_certificate":
        certificate = _validated_copy(
            certificate,
            allocation=_tampered_allocation("payment"),
        )
    elif failure == "empty_trust":
        trusted = ()
    else:
        decision_time = _VALID_UNTIL + timedelta(microseconds=1)

    with pytest.raises(MoneyGovernorError):
        _run(
            ledger,
            certificate=certificate,
            trusted=trusted,
            decision_time=decision_time,
        )
    assert boundary.calls == []


def _mocked_run(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: Any,
    order: Any,
    state: Any,
    transfer: Any = None,
):
    monkeypatch.setattr(orchestration_module, "authorize_execution_v1", lambda **_kwargs: plan)
    monkeypatch.setattr(
        orchestration_module,
        "create_razorpay_test_order_v1",
        lambda **_kwargs: order,
    )
    monkeypatch.setattr(
        orchestration_module,
        "derive_razorpay_payment_state_v1",
        lambda **_kwargs: state,
    )
    if transfer is not None:
        monkeypatch.setattr(
            orchestration_module,
            "create_or_reconcile_razorpay_test_transfers_v1",
            lambda **_kwargs: transfer,
        )
    return _run(ledger)


@pytest.mark.parametrize(
    ("order", "state"),
    (
        (
            _order_result(execution_id="e1000000-0000-4000-8000-000000000002"),
            _payment_state(),
        ),
        (_order_result(amount=Money(amount_paise=2_701)), _payment_state()),
        (_order_result(), _payment_state(certificate_digest_sha256="2" * 64)),
        (_order_result(), _payment_state(expected_amount=Money(amount_paise=2_701))),
        (_order_result(), _payment_state(provider_order_id="order_OtherReview1")),
    ),
)
def test_orchestrator_rejects_corrupt_common_subsystem_artifacts(
    order: Any,
    state: Any,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.execution.test_models import _plan

    with pytest.raises(ValueError) as caught:
        _mocked_run(
            ledger,
            monkeypatch,
            plan=_plan(),
            order=order,
            state=state,
        )
    assert str(caught.value) == "orchestration artifact mismatch"


def test_captured_common_artifact_mismatch_is_rejected_before_transfer_adapter(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.execution.test_models import _plan

    monkeypatch.setattr(orchestration_module, "authorize_execution_v1", lambda **_kwargs: _plan())
    monkeypatch.setattr(
        orchestration_module,
        "create_razorpay_test_order_v1",
        lambda **_kwargs: _order_result(),
    )
    monkeypatch.setattr(
        orchestration_module,
        "derive_razorpay_payment_state_v1",
        lambda **_kwargs: _payment_state(
            ClearPaymentStateV1.PAYMENT_CAPTURED,
            certificate_digest_sha256="2" * 64,
        ),
    )

    def transfers_must_not_run(**_kwargs: object) -> None:
        raise AssertionError("corrupt common artifacts must stop before transfers")

    monkeypatch.setattr(
        orchestration_module,
        "create_or_reconcile_razorpay_test_transfers_v1",
        transfers_must_not_run,
    )
    with pytest.raises(ValueError) as caught:
        _run(ledger)
    assert str(caught.value) == "orchestration artifact mismatch"


@pytest.mark.parametrize("kind", ("execution", "payment"))
def test_orchestrator_rejects_corrupt_transfer_artifacts(
    kind: str,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.execution.test_models import _plan
    from tests.payments.transfers.test_models import _result as _transfer_result

    transfer = _transfer_result()
    if kind == "execution":
        transfer = _validated_copy(
            transfer,
            execution_id="e1000000-0000-4000-8000-000000000002",
        )
    else:
        changed_observations = tuple(
            _validated_copy(item, provider_payment_id="pay_OtherReview1")
            for item in transfer.transfers
        )
        transfer = _validated_copy(
            transfer,
            provider_payment_id="pay_OtherReview1",
            transfers=changed_observations,
        )
    with pytest.raises(ValueError) as caught:
        _mocked_run(
            ledger,
            monkeypatch,
            plan=_plan(),
            order=_order_result(),
            state=_payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
            transfer=transfer,
        )
    assert str(caught.value) == "orchestration artifact mismatch"


def test_mocked_captured_call_order_is_authorize_order_state_transfers(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.execution.test_models import _plan
    from tests.payments.transfers.test_models import _result as _transfer_result

    calls: list[str] = []

    def returning(name: str, value: object):
        def call(**_kwargs: object) -> object:
            calls.append(name)
            return value

        return call

    monkeypatch.setattr(
        orchestration_module,
        "authorize_execution_v1",
        returning("authorize", _plan()),
    )
    monkeypatch.setattr(
        orchestration_module,
        "create_razorpay_test_order_v1",
        returning("order", _order_result()),
    )
    monkeypatch.setattr(
        orchestration_module,
        "derive_razorpay_payment_state_v1",
        returning("payment_state", _payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED)),
    )
    monkeypatch.setattr(
        orchestration_module,
        "create_or_reconcile_razorpay_test_transfers_v1",
        returning("transfers", _transfer_result()),
    )
    result = _run(ledger)
    assert result.stage is RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED
    assert calls == ["authorize", "order", "payment_state", "transfers"]


def test_mocked_noncaptured_call_order_stops_after_payment_state(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.execution.test_models import _plan

    calls: list[str] = []

    def returning(name: str, value: object):
        def call(**_kwargs: object) -> object:
            calls.append(name)
            return value

        return call

    monkeypatch.setattr(
        orchestration_module,
        "authorize_execution_v1",
        returning("authorize", _plan()),
    )
    monkeypatch.setattr(
        orchestration_module,
        "create_razorpay_test_order_v1",
        returning("order", _order_result()),
    )
    monkeypatch.setattr(
        orchestration_module,
        "derive_razorpay_payment_state_v1",
        returning("payment_state", _payment_state()),
    )

    def transfers_must_not_run(**_kwargs: object) -> None:
        raise AssertionError("transfers must not run")

    monkeypatch.setattr(
        orchestration_module,
        "create_or_reconcile_razorpay_test_transfers_v1",
        transfers_must_not_run,
    )
    result = _run(ledger)
    assert result.stage is RazorpayExecutionStageV1.ORDER_READY
    assert calls == ["authorize", "order", "payment_state"]


@pytest.mark.parametrize(
    ("target", "error"),
    (
        (
            "authorize",
            MoneyGovernorError(MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED),
        ),
        (
            "order",
            RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED),
        ),
        (
            "state",
            PaymentStateError(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID),
        ),
        (
            "transfer",
            RazorpayRouteMappingError(RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH),
        ),
        (
            "transfer",
            RazorpayTransferError(RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED),
        ),
        (
            "transfer",
            PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED),
        ),
    ),
)
def test_subsystem_errors_propagate_unchanged(
    target: str,
    error: BaseException,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.execution.test_models import _plan

    monkeypatch.setattr(orchestration_module, "authorize_execution_v1", lambda **_kwargs: _plan())
    monkeypatch.setattr(
        orchestration_module,
        "create_razorpay_test_order_v1",
        lambda **_kwargs: _order_result(),
    )
    monkeypatch.setattr(
        orchestration_module,
        "derive_razorpay_payment_state_v1",
        lambda **_kwargs: _payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
    )
    monkeypatch.setattr(
        orchestration_module,
        "create_or_reconcile_razorpay_test_transfers_v1",
        lambda **_kwargs: None,
    )

    def fail(**_kwargs: object) -> None:
        raise error

    name = {
        "authorize": "authorize_execution_v1",
        "order": "create_razorpay_test_order_v1",
        "state": "derive_razorpay_payment_state_v1",
        "transfer": "create_or_reconcile_razorpay_test_transfers_v1",
    }[target]
    monkeypatch.setattr(orchestration_module, name, fail)
    with pytest.raises(type(error)) as caught:
        _run(ledger)
    assert caught.value is error
