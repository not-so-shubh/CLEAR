import inspect
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import clear_market.orchestration.graceful.razorpay as graceful_module
import clear_market.payments.razorpay.orders as orders_module
import clear_market.payments.transfers.razorpay as transfers_module
from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.execution import MoneyGovernorError
from clear_market.orchestration import (
    RazorpayExecutionOrchestrationResultV1,
    RazorpayExecutionStageV1,
    run_razorpay_test_execution_v1,
)
from clear_market.orchestration.graceful import (
    RazorpayGracefulExecutionDispositionV1,
    RazorpayGracefulRecoveryReasonV1,
    run_razorpay_test_execution_with_recovery_v1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    RazorpayRouteMappingError,
    RazorpayRouteMappingFailureCode,
)
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryError,
    RazorpayOrderRecoveryFailureCode,
    RazorpayOrderRecoveryResultV1,
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
from tests.orchestration.test_models import (
    _payment_state,
)
from tests.orchestration.test_models import (
    _result as _execution_result,
)
from tests.orchestration.test_razorpay import (
    _bindings,
    _mapping,
    _record_webhook,
)
from tests.payments.razorpay.test_orders import (
    _Boundary as _OrderBoundary,
)
from tests.payments.razorpay.test_orders import _credentials, _response
from tests.payments.recovery.test_models import _result as _order_recovery_result
from tests.payments.recovery.test_razorpay_orders import (
    _candidate,
    _query_path,
)
from tests.payments.recovery.test_razorpay_orders import (
    _collection as _order_collection,
)
from tests.payments.recovery.test_razorpay_orders import (
    _install_boundary as _install_recovery_boundary,
)
from tests.payments.transfers.test_models import _result as _transfer_result
from tests.payments.transfers.test_razorpay import (
    _Boundary as _TransferBoundary,
)
from tests.payments.transfers.test_razorpay import _transfer_item
from tests.verification.v2.test_verifier import _tampered_allocation, _trusted

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"


@pytest.fixture
def ledger(tmp_path: Path):
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as value:
        yield value


def _call(
    ledger: SQLiteFinancialLedgerV1,
    *,
    certificate: AllocationCertificateV2 | None = None,
    trusted: Any | None = None,
    decision_time: Any = _TIME,
):
    selected = certificate or _certificate()
    return run_razorpay_test_execution_with_recovery_v1(
        certificate=selected,
        trusted_signing_identities=_trusted() if trusted is None else trusted,
        execution_request=_request_for(selected),
        linked_account_bindings=_bindings(),
        expected_razorpay_account_id="acc_CLEARPRIMARY01",
        decision_time=decision_time,
        ledger=ledger,
        credentials=_credentials(),
    )


def _not_found_result() -> RazorpayOrderRecoveryResultV1:
    return _order_recovery_result(
        disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
        order=None,
    )


def _reconciled_execution_result() -> RazorpayExecutionOrchestrationResultV1:
    return _execution_result(
        stage=RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
        state=_payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
        transfer=_transfer_result(disposition=RazorpayTransferBatchDispositionV1.RECOVERED),
    )


def _install_unit_sequence(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runs: list[RazorpayExecutionOrchestrationResultV1 | BaseException],
    recoveries: list[RazorpayOrderRecoveryResultV1 | BaseException],
) -> list[str]:
    trace: list[str] = []

    def run(**kwargs: object) -> RazorpayExecutionOrchestrationResultV1:
        trace.append("run")
        assert kwargs["decision_time"] is _TIME
        outcome = runs.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def recover(**kwargs: object) -> RazorpayOrderRecoveryResultV1:
        trace.append("recover_order")
        assert kwargs["decision_time"] is _TIME
        outcome = recoveries.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(graceful_module, "run_razorpay_test_execution_v1", run)
    monkeypatch.setattr(graceful_module, "recover_razorpay_test_order_v1", recover)
    return trace


def test_public_function_accepts_only_raw_authority_inputs() -> None:
    signature = inspect.signature(run_razorpay_test_execution_with_recovery_v1)
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
            "orchestration_result",
            "payment_state",
            "route_mapping_plan",
            "transfer_batch",
            "provider_order_id",
            "provider_payment_id",
            "retry_count",
        }
        & signature.parameters.keys()
    )


@pytest.mark.parametrize(
    ("runs", "recoveries", "expected_trace", "disposition", "reason"),
    (
        (
            [_execution_result()],
            [],
            ["run"],
            RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
            None,
        ),
        (
            [
                RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED),
                _execution_result(),
            ],
            [_order_recovery_result()],
            ["run", "recover_order", "run"],
            RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
            None,
        ),
        (
            [RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)],
            [_not_found_result()],
            ["run", "recover_order"],
            RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING,
            RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND,
        ),
        (
            [
                RazorpayTransferError(
                    RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
                ),
                _reconciled_execution_result(),
            ],
            [],
            ["run", "run"],
            RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
            None,
        ),
        (
            [
                RazorpayTransferError(
                    RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
                ),
                RazorpayTransferError(
                    RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
                ),
            ],
            [],
            ["run", "run"],
            RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING,
            RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING,
        ),
        (
            [
                RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED),
                RazorpayTransferError(
                    RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
                ),
                _reconciled_execution_result(),
            ],
            [_order_recovery_result()],
            ["run", "recover_order", "run", "run"],
            RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
            None,
        ),
    ),
)
def test_fixed_budget_call_traces_are_exact(
    runs: list[RazorpayExecutionOrchestrationResultV1 | BaseException],
    recoveries: list[RazorpayOrderRecoveryResultV1 | BaseException],
    expected_trace: list[str],
    disposition: RazorpayGracefulExecutionDispositionV1,
    reason: RazorpayGracefulRecoveryReasonV1 | None,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _install_unit_sequence(
        monkeypatch,
        runs=list(runs),
        recoveries=list(recoveries),
    )
    result = _call(ledger)
    assert trace == expected_trace
    assert result.disposition is disposition
    assert result.recovery_reason is reason


def test_existing_order_recovery_resumes_execution_once(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = _order_recovery_result(disposition=RazorpayOrderRecoveryDispositionV1.EXISTING)
    trace = _install_unit_sequence(
        monkeypatch,
        runs=[
            RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED),
            _execution_result(),
        ],
        recoveries=[recovery],
    )
    result = _call(ledger)
    assert trace == ["run", "recover_order", "run"]
    assert result.order_recovery_result == recovery


def test_order_recovery_is_preserved_when_transfer_remains_pending(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = _order_recovery_result()
    transfer_uncertainty = RazorpayTransferError(
        RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
    )
    trace = _install_unit_sequence(
        monkeypatch,
        runs=[
            RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED),
            transfer_uncertainty,
            RazorpayTransferError(RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED),
        ],
        recoveries=[recovery],
    )
    result = _call(ledger)
    assert trace == ["run", "recover_order", "run", "run"]
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING
    assert result.order_recovery_result == recovery


@pytest.mark.parametrize(
    ("code", "reason"),
    (
        (
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED,
            RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED,
        ),
        (
            RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED,
            RazorpayGracefulRecoveryReasonV1.ORDER_FETCH_FAILED,
        ),
    ),
)
def test_temporary_order_recovery_errors_become_sanitized_pending_results(
    code: RazorpayOrderRecoveryFailureCode,
    reason: RazorpayGracefulRecoveryReasonV1,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _install_unit_sequence(
        monkeypatch,
        runs=[RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)],
        recoveries=[RazorpayOrderRecoveryError(code)],
    )
    result = _call(ledger)
    assert trace == ["run", "recover_order"]
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING
    assert result.recovery_reason is reason
    assert result.execution_result is None
    assert result.order_recovery_result is None
    assert code.value not in result.model_dump_json()


@pytest.mark.parametrize(
    "code",
    (
        RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
        RazorpayOrderRecoveryFailureCode.CREATE_INTENT_MISSING,
        RazorpayOrderRecoveryFailureCode.CREATE_INTENT_CONFLICT,
        RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_AMBIGUOUS,
        RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH,
    ),
)
def test_hard_order_recovery_contradictions_propagate_unchanged(
    code: RazorpayOrderRecoveryFailureCode,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RazorpayOrderRecoveryError(code)
    trace = _install_unit_sequence(
        monkeypatch,
        runs=[RazorpayOrderError(RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED)],
        recoveries=[error],
    )
    with pytest.raises(RazorpayOrderRecoveryError) as caught:
        _call(ledger)
    assert caught.value is error
    assert trace == ["run", "recover_order"]


@pytest.mark.parametrize(
    "error",
    (
        RazorpayOrderError(RazorpayOrderFailureCode.EXISTING_ORDER_FETCH_FAILED),
        RazorpayTransferError(RazorpayTransferFailureCode.PROVIDER_TRANSFER_SET_CONFLICT),
        PaymentStateError(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID),
        RazorpayRouteMappingError(RazorpayRouteMappingFailureCode.BINDING_SET_MISMATCH),
        PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED),
        ValueError("orchestration artifact mismatch"),
    ),
)
def test_non_target_errors_propagate_unchanged(
    error: BaseException,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _install_unit_sequence(monkeypatch, runs=[error], recoveries=[])
    with pytest.raises(type(error)) as caught:
        _call(ledger)
    assert caught.value is error
    assert trace == ["run"]


def test_non_target_transfer_error_on_recovery_pass_propagates_without_third_run(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_error = RazorpayTransferError(RazorpayTransferFailureCode.PROVIDER_TRANSFER_SET_CONFLICT)
    trace = _install_unit_sequence(
        monkeypatch,
        runs=[
            RazorpayTransferError(RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED),
            final_error,
        ],
        recoveries=[],
    )
    with pytest.raises(RazorpayTransferError) as caught:
        _call(ledger)
    assert caught.value is final_error
    assert trace == ["run", "run"]


class _UncertainOrderBoundary:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        self.calls.append(kwargs)
        if kwargs["method"] == "POST":
            raise TimeoutError
        return 200, _response()

    @property
    def post_count(self) -> int:
        return sum(call["method"] == "POST" for call in self.calls)

    @property
    def get_count(self) -> int:
        return sum(call["method"] == "GET" for call in self.calls)


def _install_uncertain_order(monkeypatch: pytest.MonkeyPatch) -> _UncertainOrderBoundary:
    boundary = _UncertainOrderBoundary()
    monkeypatch.setattr(orders_module, "_https_request", boundary)
    return boundary


def test_real_uncertain_order_is_recovered_and_resumed_without_second_post(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _install_uncertain_order(monkeypatch)
    recovery_boundary = _install_recovery_boundary(
        monkeypatch,
        query=(200, _order_collection([_candidate()])),
        fetch=(200, _response()),
    )
    result = _call(ledger)
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT
    assert result.execution_result is not None
    assert result.execution_result.order_result.resolution is RazorpayOrderResolutionV1.EXISTING
    assert result.order_recovery_result is not None
    assert result.order_recovery_result.disposition is RazorpayOrderRecoveryDispositionV1.RECOVERED
    assert order_boundary.post_count == 1
    assert order_boundary.get_count == 1
    assert tuple(call["path"] for call in recovery_boundary.calls) == (
        _query_path(),
        "/v1/orders/order_CLEARReview1",
    )


def test_real_uncertain_order_not_found_remains_pending_without_second_post(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _install_uncertain_order(monkeypatch)
    recovery_boundary = _install_recovery_boundary(
        monkeypatch,
        query=(200, _order_collection([])),
    )
    result = _call(ledger)
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING
    assert result.recovery_reason is RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND
    assert result.execution_result is None
    assert result.order_recovery_result is not None
    assert result.order_recovery_result.disposition is RazorpayOrderRecoveryDispositionV1.NOT_FOUND
    assert order_boundary.post_count == 1
    assert order_boundary.get_count == 0
    assert len(recovery_boundary.calls) == 1
    assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == ()


@pytest.mark.parametrize(
    ("query", "fetch", "reason", "expected_recovery_gets"),
    (
        (
            TimeoutError(),
            None,
            RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED,
            1,
        ),
        (
            (200, _order_collection([_candidate()])),
            TimeoutError(),
            RazorpayGracefulRecoveryReasonV1.ORDER_FETCH_FAILED,
            2,
        ),
    ),
)
def test_real_temporary_order_recovery_failures_return_pending(
    query: tuple[int, bytes] | BaseException,
    fetch: tuple[int, bytes] | BaseException | None,
    reason: RazorpayGracefulRecoveryReasonV1,
    expected_recovery_gets: int,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _install_uncertain_order(monkeypatch)
    recovery_boundary = _install_recovery_boundary(
        monkeypatch,
        query=query,
        fetch=fetch,
    )
    result = _call(ledger)
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING
    assert result.recovery_reason is reason
    assert result.execution_result is None
    assert result.order_recovery_result is None
    assert order_boundary.post_count == 1
    assert order_boundary.get_count == 0
    assert len(recovery_boundary.calls) == expected_recovery_gets


class _UncertainTransferBoundary:
    def __init__(self, base: _TransferBoundary, *, visible_after_post: bool) -> None:
        self.base = base
        self.visible_after_post = visible_after_post

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        if kwargs["method"] == "POST" and self.visible_after_post:
            self.base.transfers = [
                _transfer_item(self.base.mapping, 0),
                _transfer_item(self.base.mapping, 1),
            ]
        return self.base(**kwargs)

    @property
    def post_count(self) -> int:
        return self.base.post_count

    @property
    def paths(self) -> tuple[str, ...]:
        return self.base.paths


def _prepare_captured_execution(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
):
    order_boundary = _OrderBoundary((200, _response()))
    monkeypatch.setattr(orders_module, "_https_request", order_boundary)
    ready = _call(ledger)
    assert ready.execution_result is not None
    _record_webhook(ledger, "payment.captured", event_id="event-graceful-captured")
    return order_boundary, _mapping(ready.execution_result)


def test_real_uncertain_transfer_recovers_with_get_and_never_posts_twice(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary, mapping = _prepare_captured_execution(ledger, monkeypatch)
    boundary = _UncertainTransferBoundary(
        _TransferBoundary(mapping, post=TimeoutError()),
        visible_after_post=True,
    )
    monkeypatch.setattr(transfers_module, "_https_request", boundary)
    result = _call(ledger)
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT
    assert result.execution_result is not None
    assert result.execution_result.transfer_batch is not None
    assert (
        result.execution_result.transfer_batch.disposition
        is RazorpayTransferBatchDispositionV1.RECOVERED
    )
    assert boundary.post_count == 1
    assert boundary.paths.count("/v1/payments/pay_CLEARReview1/transfers") == 3
    assert order_boundary.post_count == 1


def test_real_uncertain_transfer_still_invisible_returns_pending_after_one_safe_rerun(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _order_boundary, mapping = _prepare_captured_execution(ledger, monkeypatch)
    boundary = _UncertainTransferBoundary(
        _TransferBoundary(mapping, post=TimeoutError()),
        visible_after_post=False,
    )
    monkeypatch.setattr(transfers_module, "_https_request", boundary)
    result = _call(ledger)
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING
    assert (
        result.recovery_reason is RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING
    )
    assert result.execution_result is None
    assert boundary.post_count == 1
    assert boundary.paths.count("/v1/payments/pay_CLEARReview1/transfers") == 3


def test_preexisting_transfer_intent_gets_twice_but_never_posts_during_graceful_invocation(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _order_boundary, mapping = _prepare_captured_execution(ledger, monkeypatch)
    base = _TransferBoundary(mapping, post=TimeoutError())
    monkeypatch.setattr(transfers_module, "_https_request", base)
    with pytest.raises(RazorpayTransferError) as initial:
        run_razorpay_test_execution_v1(
            certificate=_certificate(),
            trusted_signing_identities=_trusted(),
            execution_request=_request_for(_certificate()),
            linked_account_bindings=_bindings(),
            expected_razorpay_account_id="acc_CLEARPRIMARY01",
            decision_time=_TIME,
            ledger=ledger,
            credentials=_credentials(),
        )
    assert initial.value.code is RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
    posts_before = base.post_count
    paths_before = len(base.paths)
    result = _call(ledger)
    assert result.disposition is RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING
    assert base.post_count == posts_before == 1
    assert base.paths[paths_before:] == (
        "/v1/payments/pay_CLEARReview1/transfers",
        "/v1/payments/pay_CLEARReview1/transfers",
    )


@pytest.mark.parametrize("failure", ("invalid_certificate", "empty_trust", "expired"))
def test_authority_failures_propagate_before_every_provider_call(
    failure: str,
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_boundary = _OrderBoundary((200, _response()))
    monkeypatch.setattr(orders_module, "_https_request", order_boundary)
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
        _call(
            ledger,
            certificate=certificate,
            trusted=trusted,
            decision_time=decision_time,
        )
    assert order_boundary.calls == []
