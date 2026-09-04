"""Bounded recovery composition over reviewed Razorpay Test Mode subsystems."""

from datetime import datetime

from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.execution import ExecutionAuthorizationRequestV1
from clear_market.orchestration import (
    RazorpayExecutionOrchestrationResultV1,
    run_razorpay_test_execution_v1,
)
from clear_market.orchestration.graceful.models import (
    RazorpayGracefulExecutionDispositionV1,
    RazorpayGracefulExecutionResultV1,
    RazorpayGracefulRecoveryReasonV1,
)
from clear_market.payments.razorpay import (
    RazorpayLinkedAccountBindingV1,
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayTestCredentialsV1,
)
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryError,
    RazorpayOrderRecoveryFailureCode,
    RazorpayOrderRecoveryResultV1,
    recover_razorpay_test_order_v1,
)
from clear_market.payments.transfers import (
    RazorpayTransferError,
    RazorpayTransferFailureCode,
)
from clear_market.persistence import SQLiteFinancialLedgerV1


def _execution_result(
    value: RazorpayExecutionOrchestrationResultV1,
    order_recovery_result: RazorpayOrderRecoveryResultV1 | None,
) -> RazorpayGracefulExecutionResultV1:
    return RazorpayGracefulExecutionResultV1(
        disposition=RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
        execution_id=value.execution_plan.execution_id,
        execution_result=value,
        order_recovery_result=order_recovery_result,
        recovery_reason=None,
    )


def _order_pending(
    *,
    execution_id: str,
    reason: RazorpayGracefulRecoveryReasonV1,
    recovery: RazorpayOrderRecoveryResultV1 | None,
) -> RazorpayGracefulExecutionResultV1:
    return RazorpayGracefulExecutionResultV1(
        disposition=RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING,
        execution_id=execution_id,
        execution_result=None,
        order_recovery_result=recovery,
        recovery_reason=reason,
    )


def _transfer_pending(
    *,
    execution_id: str,
    recovery: RazorpayOrderRecoveryResultV1 | None,
) -> RazorpayGracefulExecutionResultV1:
    return RazorpayGracefulExecutionResultV1(
        disposition=RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING,
        execution_id=execution_id,
        execution_result=None,
        order_recovery_result=recovery,
        recovery_reason=RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING,
    )


def _run_once(
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
    return run_razorpay_test_execution_v1(
        certificate=certificate,
        trusted_signing_identities=trusted_signing_identities,
        execution_request=execution_request,
        linked_account_bindings=linked_account_bindings,
        expected_razorpay_account_id=expected_razorpay_account_id,
        decision_time=decision_time,
        ledger=ledger,
        credentials=credentials,
    )


def run_razorpay_test_execution_with_recovery_v1(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_request: ExecutionAuthorizationRequestV1,
    linked_account_bindings: tuple[RazorpayLinkedAccountBindingV1, ...],
    expected_razorpay_account_id: str,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
) -> RazorpayGracefulExecutionResultV1:
    """Run 23A with one bounded, authority-preserving recovery opportunity."""
    order_recovery: RazorpayOrderRecoveryResultV1 | None = None
    try:
        initial = _run_once(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            execution_request=execution_request,
            linked_account_bindings=linked_account_bindings,
            expected_razorpay_account_id=expected_razorpay_account_id,
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
        )
    except RazorpayOrderError as error:
        if error.code is not RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED:
            raise
        try:
            order_recovery = recover_razorpay_test_order_v1(
                certificate=certificate,
                trusted_signing_identities=trusted_signing_identities,
                execution_request=execution_request,
                decision_time=decision_time,
                ledger=ledger,
                credentials=credentials,
            )
        except RazorpayOrderRecoveryError as recovery_error:
            reason = {
                RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED: (
                    RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED
                ),
                RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED: (
                    RazorpayGracefulRecoveryReasonV1.ORDER_FETCH_FAILED
                ),
            }.get(recovery_error.code)
            if reason is None:
                raise
            return _order_pending(
                execution_id=execution_request.execution_id,
                reason=reason,
                recovery=None,
            )
        if order_recovery.disposition is RazorpayOrderRecoveryDispositionV1.NOT_FOUND:
            return _order_pending(
                execution_id=execution_request.execution_id,
                reason=RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND,
                recovery=order_recovery,
            )
        try:
            resumed = _run_once(
                certificate=certificate,
                trusted_signing_identities=trusted_signing_identities,
                execution_request=execution_request,
                linked_account_bindings=linked_account_bindings,
                expected_razorpay_account_id=expected_razorpay_account_id,
                decision_time=decision_time,
                ledger=ledger,
                credentials=credentials,
            )
        except RazorpayTransferError as transfer_error:
            if (
                transfer_error.code
                is not RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
            ):
                raise
            return _reconcile_transfer_once(
                certificate=certificate,
                trusted_signing_identities=trusted_signing_identities,
                execution_request=execution_request,
                linked_account_bindings=linked_account_bindings,
                expected_razorpay_account_id=expected_razorpay_account_id,
                decision_time=decision_time,
                ledger=ledger,
                credentials=credentials,
                execution_id=execution_request.execution_id,
                order_recovery=order_recovery,
            )
        return _execution_result(resumed, order_recovery)
    except RazorpayTransferError as transfer_error:
        if (
            transfer_error.code
            is not RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED
        ):
            raise
        return _reconcile_transfer_once(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            execution_request=execution_request,
            linked_account_bindings=linked_account_bindings,
            expected_razorpay_account_id=expected_razorpay_account_id,
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
            execution_id=execution_request.execution_id,
            order_recovery=None,
        )
    return _execution_result(initial, None)


def _reconcile_transfer_once(
    *,
    certificate: AllocationCertificateV2,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
    execution_request: ExecutionAuthorizationRequestV1,
    linked_account_bindings: tuple[RazorpayLinkedAccountBindingV1, ...],
    expected_razorpay_account_id: str,
    decision_time: datetime,
    ledger: SQLiteFinancialLedgerV1,
    credentials: RazorpayTestCredentialsV1,
    execution_id: str,
    order_recovery: RazorpayOrderRecoveryResultV1 | None,
) -> RazorpayGracefulExecutionResultV1:
    try:
        result = _run_once(
            certificate=certificate,
            trusted_signing_identities=trusted_signing_identities,
            execution_request=execution_request,
            linked_account_bindings=linked_account_bindings,
            expected_razorpay_account_id=expected_razorpay_account_id,
            decision_time=decision_time,
            ledger=ledger,
            credentials=credentials,
        )
    except RazorpayTransferError as error:
        if error.code is not RazorpayTransferFailureCode.TRANSFER_CREATION_RECOVERY_REQUIRED:
            raise
        return _transfer_pending(
            execution_id=execution_id,
            recovery=order_recovery,
        )
    return _execution_result(result, order_recovery)
