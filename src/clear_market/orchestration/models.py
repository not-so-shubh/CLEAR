"""Strict composition snapshots for Razorpay Test Mode execution orchestration."""

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError, model_validator

from clear_market.execution import ExecutionPlanV1
from clear_market.payments.razorpay import RazorpayOrderResultV1
from clear_market.payments.state import ClearPaymentStateSnapshotV1, ClearPaymentStateV1
from clear_market.payments.transfers import RazorpayTransferBatchResultV1

RAZORPAY_EXECUTION_ORCHESTRATOR_V1_VERSION: Final[str] = "razorpay-execution-orchestrator-v1"
RAZORPAY_EXECUTION_ORCHESTRATION_RESULT_V1_VERSION: Final[str] = (
    "razorpay-execution-orchestration-result-v1"
)

_ARTIFACT_MISMATCH: Final[str] = "orchestration artifact mismatch"


class RazorpayExecutionStageV1(StrEnum):
    ORDER_READY = "ORDER_READY"
    PAYMENT_FAILED_OBSERVED = "PAYMENT_FAILED_OBSERVED"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    TRANSFER_BATCH_RECONCILED = "TRANSFER_BATCH_RECONCILED"


def _fresh_exact_model[ModelT: BaseModel](
    value: object,
    expected_type: type[ModelT],
) -> ModelT:
    if type(value) is not expected_type:
        raise ValueError(_ARTIFACT_MISMATCH)
    try:
        fields = {name: value.__dict__[name] for name in expected_type.model_fields}
        return expected_type.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(_ARTIFACT_MISMATCH) from None


def _fresh_execution_plan(value: object) -> ExecutionPlanV1:
    return _fresh_exact_model(value, ExecutionPlanV1)


def _fresh_order_result(value: object) -> RazorpayOrderResultV1:
    return _fresh_exact_model(value, RazorpayOrderResultV1)


def _fresh_payment_state(value: object) -> ClearPaymentStateSnapshotV1:
    return _fresh_exact_model(value, ClearPaymentStateSnapshotV1)


def _fresh_transfer_batch(value: object) -> RazorpayTransferBatchResultV1 | None:
    if value is None:
        return None
    return _fresh_exact_model(value, RazorpayTransferBatchResultV1)


type _ExecutionPlan = Annotated[ExecutionPlanV1, BeforeValidator(_fresh_execution_plan)]
type _OrderResult = Annotated[RazorpayOrderResultV1, BeforeValidator(_fresh_order_result)]
type _PaymentState = Annotated[
    ClearPaymentStateSnapshotV1,
    BeforeValidator(_fresh_payment_state),
]
type _TransferBatch = Annotated[
    RazorpayTransferBatchResultV1 | None,
    BeforeValidator(_fresh_transfer_batch),
]


def _common_artifacts_match(
    plan: ExecutionPlanV1,
    order_result: RazorpayOrderResultV1,
    state: ClearPaymentStateSnapshotV1,
) -> bool:
    order = order_result.order
    return (
        order.execution_id == plan.execution_id
        and state.execution_id == plan.execution_id
        and state.certificate_digest_version == plan.certificate_digest_version
        and state.certificate_digest_sha256 == plan.certificate_digest_sha256
        and state.expected_amount == plan.order_amount
        and state.provider_order_id == order.provider_order_id
        and order.amount == plan.order_amount
    )


class RazorpayExecutionOrchestrationResultV1(BaseModel):
    """A composition snapshot of already-authoritative subsystem outputs.

    Direct construction does not establish certificate validity, financial authorization,
    provider payment truth, routing authority, transfer authority, settlement, or fulfillment.
    Future side-effect code must call the authoritative underlying subsystem APIs rather than
    trusting this result object.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_execution_orchestration_result_version: Literal[
        "razorpay-execution-orchestration-result-v1"
    ] = "razorpay-execution-orchestration-result-v1"
    orchestrator_version: Literal["razorpay-execution-orchestrator-v1"] = (
        "razorpay-execution-orchestrator-v1"
    )
    stage: RazorpayExecutionStageV1
    execution_plan: _ExecutionPlan
    order_result: _OrderResult
    payment_state: _PaymentState
    transfer_batch: _TransferBatch

    @model_validator(mode="after")
    def _validate_artifact_bindings(self) -> Self:
        plan = self.execution_plan
        state = self.payment_state
        if not _common_artifacts_match(plan, self.order_result, state):
            raise ValueError(_ARTIFACT_MISMATCH)

        expected_state = {
            RazorpayExecutionStageV1.ORDER_READY: (ClearPaymentStateV1.ORDER_CREATED),
            RazorpayExecutionStageV1.PAYMENT_FAILED_OBSERVED: (
                ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED
            ),
            RazorpayExecutionStageV1.PAYMENT_AUTHORIZED: (ClearPaymentStateV1.PAYMENT_AUTHORIZED),
            RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED: (
                ClearPaymentStateV1.PAYMENT_CAPTURED
            ),
        }[self.stage]
        if state.state is not expected_state:
            raise ValueError(_ARTIFACT_MISMATCH)

        batch = self.transfer_batch
        if self.stage is not RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED:
            if batch is not None:
                raise ValueError(_ARTIFACT_MISMATCH)
            return self
        if (
            batch is None
            or state.effective_payment_id is None
            or batch.execution_id != plan.execution_id
            or batch.provider_order_id != state.provider_order_id
            or batch.provider_payment_id != state.effective_payment_id
        ):
            raise ValueError(_ARTIFACT_MISMATCH)
        return self


def _validated_execution_plan(value: object) -> ExecutionPlanV1:
    return _fresh_execution_plan(value)


def _validated_order_result(value: object) -> RazorpayOrderResultV1:
    return _fresh_order_result(value)


def _validated_payment_state(value: object) -> ClearPaymentStateSnapshotV1:
    return _fresh_payment_state(value)


def _validated_transfer_batch(value: object) -> RazorpayTransferBatchResultV1:
    validated = _fresh_transfer_batch(value)
    if validated is None:
        raise ValueError(_ARTIFACT_MISMATCH)
    return validated
