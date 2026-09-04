"""Strict results for bounded Razorpay Test Mode recovery orchestration."""

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError, model_validator

from clear_market.domain import CanonicalUUID4
from clear_market.orchestration import RazorpayExecutionOrchestrationResultV1
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryResultV1,
)

RAZORPAY_GRACEFUL_EXECUTION_ORCHESTRATOR_V1_VERSION: Final[str] = (
    "razorpay-graceful-execution-orchestrator-v1"
)
RAZORPAY_GRACEFUL_EXECUTION_RESULT_V1_VERSION: Final[str] = "razorpay-graceful-execution-result-v1"

_RESULT_MISMATCH: Final[str] = "graceful orchestration result mismatch"


class RazorpayGracefulExecutionDispositionV1(StrEnum):
    EXECUTION_RESULT = "EXECUTION_RESULT"
    ORDER_RECOVERY_PENDING = "ORDER_RECOVERY_PENDING"
    TRANSFER_RECOVERY_PENDING = "TRANSFER_RECOVERY_PENDING"


class RazorpayGracefulRecoveryReasonV1(StrEnum):
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_QUERY_FAILED = "ORDER_QUERY_FAILED"
    ORDER_FETCH_FAILED = "ORDER_FETCH_FAILED"
    TRANSFER_RECONCILIATION_PENDING = "TRANSFER_RECONCILIATION_PENDING"


def _fresh_exact_model[ModelT: BaseModel](
    value: object,
    expected_type: type[ModelT],
) -> ModelT:
    if type(value) is not expected_type:
        raise ValueError(_RESULT_MISMATCH)
    try:
        fields = {name: value.__dict__[name] for name in expected_type.model_fields}
        return expected_type.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(_RESULT_MISMATCH) from None


def _fresh_execution_result(
    value: object,
) -> RazorpayExecutionOrchestrationResultV1 | None:
    if value is None:
        return None
    return _fresh_exact_model(value, RazorpayExecutionOrchestrationResultV1)


def _fresh_order_recovery_result(
    value: object,
) -> RazorpayOrderRecoveryResultV1 | None:
    if value is None:
        return None
    return _fresh_exact_model(value, RazorpayOrderRecoveryResultV1)


type _ExecutionResult = Annotated[
    RazorpayExecutionOrchestrationResultV1 | None,
    BeforeValidator(_fresh_execution_result),
]
type _OrderRecoveryResult = Annotated[
    RazorpayOrderRecoveryResultV1 | None,
    BeforeValidator(_fresh_order_recovery_result),
]


class RazorpayGracefulExecutionResultV1(BaseModel):
    """This result records bounded orchestration and recovery outcomes.

    Direct construction does not establish certificate validity, financial authorization,
    provider truth, payment capture, routing authority, transfer authority, settlement,
    fulfillment, or permission to retry a provider mutation. Future side-effect code must invoke the
    authoritative subsystem APIs and must not use this result as money-movement authority.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_graceful_execution_result_version: Literal["razorpay-graceful-execution-result-v1"] = (
        "razorpay-graceful-execution-result-v1"
    )
    graceful_orchestrator_version: Literal["razorpay-graceful-execution-orchestrator-v1"] = (
        "razorpay-graceful-execution-orchestrator-v1"
    )
    disposition: RazorpayGracefulExecutionDispositionV1
    execution_id: CanonicalUUID4
    execution_result: _ExecutionResult
    order_recovery_result: _OrderRecoveryResult
    recovery_reason: RazorpayGracefulRecoveryReasonV1 | None

    @model_validator(mode="after")
    def _validate_result(self) -> Self:
        if self.disposition is RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT:
            self._validate_execution_result()
            return self
        if self.disposition is RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING:
            self._validate_order_pending()
            return self
        self._validate_transfer_pending()
        return self

    def _validate_execution_result(self) -> None:
        result = self.execution_result
        recovery = self.order_recovery_result
        if (
            result is None
            or result.execution_plan.execution_id != self.execution_id
            or self.recovery_reason is not None
        ):
            raise ValueError(_RESULT_MISMATCH)
        if recovery is None:
            return
        if recovery.disposition not in {
            RazorpayOrderRecoveryDispositionV1.RECOVERED,
            RazorpayOrderRecoveryDispositionV1.EXISTING,
        }:
            raise ValueError(_RESULT_MISMATCH)
        if (
            recovery.execution_id != self.execution_id
            or recovery.order is None
            or recovery.order.provider_order_id != result.order_result.order.provider_order_id
        ):
            raise ValueError(_RESULT_MISMATCH)

    def _validate_order_pending(self) -> None:
        reason = self.recovery_reason
        recovery = self.order_recovery_result
        if self.execution_result is not None or reason not in {
            RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND,
            RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED,
            RazorpayGracefulRecoveryReasonV1.ORDER_FETCH_FAILED,
        }:
            raise ValueError(_RESULT_MISMATCH)
        if reason is RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND:
            if (
                recovery is None
                or recovery.disposition is not RazorpayOrderRecoveryDispositionV1.NOT_FOUND
                or recovery.execution_id != self.execution_id
            ):
                raise ValueError(_RESULT_MISMATCH)
            return
        if recovery is not None:
            raise ValueError(_RESULT_MISMATCH)

    def _validate_transfer_pending(self) -> None:
        recovery = self.order_recovery_result
        if (
            self.execution_result is not None
            or self.recovery_reason
            is not RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING
        ):
            raise ValueError(_RESULT_MISMATCH)
        if recovery is None:
            return
        if (
            recovery.disposition
            not in {
                RazorpayOrderRecoveryDispositionV1.RECOVERED,
                RazorpayOrderRecoveryDispositionV1.EXISTING,
            }
            or recovery.execution_id != self.execution_id
            or recovery.order is None
        ):
            raise ValueError(_RESULT_MISMATCH)
