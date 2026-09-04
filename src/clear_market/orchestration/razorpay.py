"""Composition-only Razorpay Test Mode execution orchestration."""

from datetime import datetime
from typing import Final

from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.execution import (
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    authorize_execution_v1,
)
from clear_market.orchestration.models import (
    RazorpayExecutionOrchestrationResultV1,
    RazorpayExecutionStageV1,
    _common_artifacts_match,
    _validated_execution_plan,
    _validated_order_result,
    _validated_payment_state,
    _validated_transfer_batch,
)
from clear_market.payments.razorpay import (
    RazorpayLinkedAccountBindingV1,
    RazorpayOrderResultV1,
    RazorpayTestCredentialsV1,
    create_razorpay_test_order_v1,
)
from clear_market.payments.state import (
    ClearPaymentStateSnapshotV1,
    ClearPaymentStateV1,
    derive_razorpay_payment_state_v1,
)
from clear_market.payments.transfers import (
    RazorpayTransferBatchResultV1,
    create_or_reconcile_razorpay_test_transfers_v1,
)
from clear_market.persistence import SQLiteFinancialLedgerV1

_ARTIFACT_MISMATCH: Final[str] = "orchestration artifact mismatch"


def _result(
    *,
    stage: RazorpayExecutionStageV1,
    execution_plan: ExecutionPlanV1,
    order_result: RazorpayOrderResultV1,
    payment_state: ClearPaymentStateSnapshotV1,
    transfer_batch: RazorpayTransferBatchResultV1 | None,
) -> RazorpayExecutionOrchestrationResultV1:
    try:
        return RazorpayExecutionOrchestrationResultV1(
            stage=stage,
            execution_plan=execution_plan,
            order_result=order_result,
            payment_state=payment_state,
            transfer_batch=transfer_batch,
        )
    except ValueError:
        raise ValueError(_ARTIFACT_MISMATCH) from None


def run_razorpay_test_execution_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_request: ExecutionAuthorizationRequestV1,
    linked_account_bindings: tuple[RazorpayLinkedAccountBindingV1, ...],
    expected_razorpay_account_id: str,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayExecutionOrchestrationResultV1:
    """Compose authoritative Test Mode subsystems without replacing any authority boundary."""
    plan = _validated_execution_plan(
        authorize_execution_v1(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            request=execution_request,
            decision_time=decision_time,
            ledger=ledger,
        )
    )
    order = _validated_order_result(
        create_razorpay_test_order_v1(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            execution_request=execution_request,
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
        )
    )
    state = _validated_payment_state(
        derive_razorpay_payment_state_v1(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            execution_id=plan.execution_id,
            expected_razorpay_account_id=expected_razorpay_account_id,
            ledger=ledger,
        )
    )
    if not _common_artifacts_match(plan, order, state):
        raise ValueError(_ARTIFACT_MISMATCH)

    if state.state is ClearPaymentStateV1.ORDER_CREATED:
        return _result(
            stage=RazorpayExecutionStageV1.ORDER_READY,
            execution_plan=plan,
            order_result=order,
            payment_state=state,
            transfer_batch=None,
        )
    if state.state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED:
        return _result(
            stage=RazorpayExecutionStageV1.PAYMENT_FAILED_OBSERVED,
            execution_plan=plan,
            order_result=order,
            payment_state=state,
            transfer_batch=None,
        )
    if state.state is ClearPaymentStateV1.PAYMENT_AUTHORIZED:
        return _result(
            stage=RazorpayExecutionStageV1.PAYMENT_AUTHORIZED,
            execution_plan=plan,
            order_result=order,
            payment_state=state,
            transfer_batch=None,
        )
    if state.state is not ClearPaymentStateV1.PAYMENT_CAPTURED:
        raise ValueError(_ARTIFACT_MISMATCH)

    transfers = _validated_transfer_batch(
        create_or_reconcile_razorpay_test_transfers_v1(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            execution_request=execution_request,
            linked_account_bindings=linked_account_bindings,
            expected_razorpay_account_id=expected_razorpay_account_id,
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
        )
    )
    return _result(
        stage=RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
        execution_plan=plan,
        order_result=order,
        payment_state=state,
        transfer_batch=transfers,
    )
