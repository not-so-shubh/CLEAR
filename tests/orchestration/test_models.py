from enum import StrEnum

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.orchestration as orchestration
from clear_market.domain import Money
from clear_market.orchestration import (
    RAZORPAY_EXECUTION_ORCHESTRATION_RESULT_V1_VERSION,
    RAZORPAY_EXECUTION_ORCHESTRATOR_V1_VERSION,
    RazorpayExecutionOrchestrationResultV1,
    RazorpayExecutionStageV1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderResolutionV1,
    RazorpayOrderResultV1,
    RazorpayOrderStatusV1,
    RazorpayOrderV1,
    RazorpayWebhookEventTypeV1,
)
from clear_market.payments.state import ClearPaymentStateSnapshotV1, ClearPaymentStateV1
from clear_market.payments.transfers import RazorpayTransferBatchResultV1
from tests.execution.test_models import ExecutionPlanV1, _plan
from tests.payments.state.test_models import _evidence
from tests.payments.transfers.test_models import _result as _transfer_result

_ACCOUNT_ID = "acc_CLEARPRIMARY01"
_ORDER_ID = "order_CLEARReview1"
_PAYMENT_ID = "pay_CLEARReview1"
_CONFIG = {
    "frozen": True,
    "extra": "forbid",
    "strict": True,
    "revalidate_instances": "always",
}


class _PlanSubclass(ExecutionPlanV1):
    pass


class _OrderResultSubclass(RazorpayOrderResultV1):
    pass


class _PaymentStateSubclass(ClearPaymentStateSnapshotV1):
    pass


class _TransferBatchSubclass(RazorpayTransferBatchResultV1):
    pass


def _validated_copy[ModelT: BaseModel](model: ModelT, **changes: object) -> ModelT:
    fields = {name: model.__dict__[name] for name in type(model).model_fields}
    fields.update(changes)
    return type(model).model_validate(fields)


def _order_result(
    *,
    resolution: RazorpayOrderResolutionV1 = RazorpayOrderResolutionV1.CREATED,
    execution_id: str | None = None,
    amount: Money | None = None,
    provider_order_id: str = _ORDER_ID,
) -> RazorpayOrderResultV1:
    plan = _plan()
    selected_execution = execution_id or plan.execution_id
    return RazorpayOrderResultV1(
        resolution=resolution,
        order=RazorpayOrderV1(
            execution_id=selected_execution,
            provider_order_id=provider_order_id,
            amount=amount or plan.order_amount,
            receipt=selected_execution,
            status=RazorpayOrderStatusV1.CREATED,
        ),
    )


def _payment_state(
    state: ClearPaymentStateV1 = ClearPaymentStateV1.ORDER_CREATED,
    **changes: object,
) -> ClearPaymentStateSnapshotV1:
    plan = _plan()
    if state is ClearPaymentStateV1.ORDER_CREATED:
        effective_payment_id = None
        evidence = ()
    elif state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED:
        effective_payment_id = None
        evidence = (_evidence(event_type=RazorpayWebhookEventTypeV1.PAYMENT_FAILED),)
    elif state is ClearPaymentStateV1.PAYMENT_AUTHORIZED:
        effective_payment_id = _PAYMENT_ID
        evidence = (_evidence(event_type=RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED),)
    else:
        effective_payment_id = _PAYMENT_ID
        evidence = (_evidence(),)
    values: dict[str, object] = {
        "execution_id": plan.execution_id,
        "certificate_digest_version": plan.certificate_digest_version,
        "certificate_digest_sha256": plan.certificate_digest_sha256,
        "provider_account_id": _ACCOUNT_ID,
        "provider_order_id": _ORDER_ID,
        "expected_amount": plan.order_amount,
        "state": state,
        "effective_payment_id": effective_payment_id,
        "evidence": evidence,
        **changes,
    }
    return ClearPaymentStateSnapshotV1(**values)


def _result(
    *,
    stage: RazorpayExecutionStageV1 = (RazorpayExecutionStageV1.ORDER_READY),
    plan: object | None = None,
    order: object | None = None,
    state: object | None = None,
    transfer: object | None = None,
) -> RazorpayExecutionOrchestrationResultV1:
    return RazorpayExecutionOrchestrationResultV1(
        stage=stage,
        execution_plan=_plan() if plan is None else plan,
        order_result=_order_result() if order is None else order,
        payment_state=_payment_state() if state is None else state,
        transfer_batch=transfer,
    )


def test_versions_enum_and_public_api_are_exact() -> None:
    assert RAZORPAY_EXECUTION_ORCHESTRATOR_V1_VERSION == "razorpay-execution-orchestrator-v1"
    assert RAZORPAY_EXECUTION_ORCHESTRATION_RESULT_V1_VERSION == (
        "razorpay-execution-orchestration-result-v1"
    )
    assert issubclass(RazorpayExecutionStageV1, StrEnum)
    assert tuple(RazorpayExecutionStageV1) == tuple(
        RazorpayExecutionStageV1[name]
        for name in (
            "ORDER_READY",
            "PAYMENT_FAILED_OBSERVED",
            "PAYMENT_AUTHORIZED",
            "TRANSFER_BATCH_RECONCILED",
        )
    )
    assert tuple(item.value for item in RazorpayExecutionStageV1) == tuple(
        item.name for item in RazorpayExecutionStageV1
    )
    assert orchestration.__all__ == (
        "RAZORPAY_EXECUTION_ORCHESTRATOR_V1_VERSION",
        "RAZORPAY_EXECUTION_ORCHESTRATION_RESULT_V1_VERSION",
        "RazorpayExecutionStageV1",
        "RazorpayExecutionOrchestrationResultV1",
        "run_razorpay_test_execution_v1",
    )


def test_result_fields_versions_and_configuration_are_exact() -> None:
    value = _result()
    assert tuple(RazorpayExecutionOrchestrationResultV1.model_fields) == (
        "schema_version",
        "razorpay_execution_orchestration_result_version",
        "orchestrator_version",
        "stage",
        "execution_plan",
        "order_result",
        "payment_state",
        "transfer_batch",
    )
    assert RazorpayExecutionOrchestrationResultV1.model_config == _CONFIG
    assert value.schema_version == "1"
    assert value.razorpay_execution_orchestration_result_version == (
        RAZORPAY_EXECUTION_ORCHESTRATION_RESULT_V1_VERSION
    )
    assert value.orchestrator_version == RAZORPAY_EXECUTION_ORCHESTRATOR_V1_VERSION


def test_result_is_frozen_and_forbids_extras() -> None:
    value = _result()
    with pytest.raises(ValidationError):
        value.stage = RazorpayExecutionStageV1.PAYMENT_AUTHORIZED  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RazorpayExecutionOrchestrationResultV1(
            stage=RazorpayExecutionStageV1.ORDER_READY,
            execution_plan=_plan(),
            order_result=_order_result(),
            payment_state=_payment_state(),
            transfer_batch=None,
            extra="forbidden",
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("execution_plan", _plan().model_dump(mode="python")),
        ("order_result", _order_result().model_dump(mode="python")),
        ("payment_state", _payment_state().model_dump(mode="python")),
        ("transfer_batch", _transfer_result().model_dump(mode="python")),
    ),
)
def test_nested_artifacts_require_exact_model_types(field: str, invalid: object) -> None:
    values: dict[str, object] = {
        "stage": RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
        "execution_plan": _plan(),
        "order_result": _order_result(),
        "payment_state": _payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
        "transfer_batch": _transfer_result(),
    }
    values[field] = invalid
    with pytest.raises(ValidationError):
        RazorpayExecutionOrchestrationResultV1(**values)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("execution_plan", _plan().model_construct()),
        ("order_result", RazorpayOrderResultV1.model_construct()),
        ("payment_state", ClearPaymentStateSnapshotV1.model_construct()),
        ("transfer_batch", RazorpayTransferBatchResultV1.model_construct()),
    ),
)
def test_constructed_nested_corruption_fails_closed(field: str, invalid: object) -> None:
    values: dict[str, object] = {
        "stage": RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
        "execution_plan": _plan(),
        "order_result": _order_result(),
        "payment_state": _payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
        "transfer_batch": _transfer_result(),
    }
    values[field] = invalid
    with pytest.raises(ValidationError):
        RazorpayExecutionOrchestrationResultV1(**values)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("execution_plan", _PlanSubclass.model_construct(**_plan().__dict__)),
        (
            "order_result",
            _OrderResultSubclass.model_construct(**_order_result().__dict__),
        ),
        (
            "payment_state",
            _PaymentStateSubclass.model_construct(**_payment_state().__dict__),
        ),
        (
            "transfer_batch",
            _TransferBatchSubclass.model_construct(**_transfer_result().__dict__),
        ),
    ),
)
def test_nested_artifact_subclasses_are_rejected(field: str, invalid: object) -> None:
    values: dict[str, object] = {
        "stage": RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
        "execution_plan": _plan(),
        "order_result": _order_result(),
        "payment_state": _payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
        "transfer_batch": _transfer_result(),
    }
    values[field] = invalid
    with pytest.raises(ValidationError):
        RazorpayExecutionOrchestrationResultV1(**values)


@pytest.mark.parametrize(
    ("stage", "state"),
    (
        (
            RazorpayExecutionStageV1.ORDER_READY,
            ClearPaymentStateV1.ORDER_CREATED,
        ),
        (
            RazorpayExecutionStageV1.PAYMENT_FAILED_OBSERVED,
            ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED,
        ),
        (
            RazorpayExecutionStageV1.PAYMENT_AUTHORIZED,
            ClearPaymentStateV1.PAYMENT_AUTHORIZED,
        ),
    ),
)
def test_nontransfer_stage_invariants_are_exact(
    stage: RazorpayExecutionStageV1,
    state: ClearPaymentStateV1,
) -> None:
    result = _result(stage=stage, state=_payment_state(state))
    assert result.stage is stage
    assert result.payment_state.state is state
    assert result.transfer_batch is None
    with pytest.raises(ValidationError):
        _result(stage=stage, state=_payment_state(state), transfer=_transfer_result())


def test_transfer_stage_requires_captured_state_and_matching_batch() -> None:
    result = _result(
        stage=RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
        state=_payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
        transfer=_transfer_result(),
    )
    assert result.transfer_batch == _transfer_result()
    with pytest.raises(ValidationError):
        _result(
            stage=RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
            state=_payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
        )
    with pytest.raises(ValidationError):
        _result(
            stage=RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
            state=_payment_state(ClearPaymentStateV1.PAYMENT_AUTHORIZED),
            transfer=_transfer_result(),
        )


@pytest.mark.parametrize(
    ("order", "state", "transfer"),
    (
        (
            _order_result(execution_id="e1000000-0000-4000-8000-000000000002"),
            _payment_state(),
            None,
        ),
        (
            _order_result(amount=Money(amount_paise=2_701)),
            _payment_state(),
            None,
        ),
        (
            _order_result(),
            _payment_state(execution_id="e1000000-0000-4000-8000-000000000002"),
            None,
        ),
        (
            _order_result(),
            _payment_state(certificate_digest_sha256="2" * 64),
            None,
        ),
        (
            _order_result(),
            _payment_state(expected_amount=Money(amount_paise=2_701)),
            None,
        ),
        (
            _order_result(),
            _payment_state(provider_order_id="order_OtherReview1"),
            None,
        ),
    ),
)
def test_cross_artifact_mismatches_fail_closed(
    order: RazorpayOrderResultV1,
    state: ClearPaymentStateSnapshotV1,
    transfer: RazorpayTransferBatchResultV1 | None,
) -> None:
    with pytest.raises(ValidationError, match="orchestration artifact mismatch"):
        _result(order=order, state=state, transfer=transfer)


@pytest.mark.parametrize(
    "transfer",
    (
        _validated_copy(
            _transfer_result(),
            execution_id="e1000000-0000-4000-8000-000000000002",
        ),
        _validated_copy(_transfer_result(), provider_order_id="order_OtherReview1"),
        _validated_copy(
            _transfer_result(),
            provider_payment_id="pay_OtherReview1",
            transfers=tuple(
                _validated_copy(item, provider_payment_id="pay_OtherReview1")
                for item in _transfer_result().transfers
            ),
        ),
    ),
)
def test_transfer_artifact_mismatches_fail_closed(
    transfer: RazorpayTransferBatchResultV1,
) -> None:
    with pytest.raises(ValidationError, match="orchestration artifact mismatch"):
        _result(
            stage=RazorpayExecutionStageV1.TRANSFER_BATCH_RECONCILED,
            state=_payment_state(ClearPaymentStateV1.PAYMENT_CAPTURED),
            transfer=transfer,
        )


def test_result_authority_limitation_is_explicit() -> None:
    documentation = RazorpayExecutionOrchestrationResultV1.__doc__ or ""
    assert "composition snapshot of already-authoritative subsystem outputs" in documentation
    assert "does not establish certificate validity" in documentation
    assert "financial authorization" in documentation
    assert "provider payment truth" in documentation
    assert "routing authority" in documentation
    assert "transfer authority" in documentation
    assert "settlement" in documentation
    assert "fulfillment" in documentation
    assert "must call the authoritative underlying subsystem APIs" in documentation
    assert (
        not {
            "authorize",
            "create_order",
            "derive_payment_state",
            "create_transfers",
            "execute",
            "persist",
        }
        & RazorpayExecutionOrchestrationResultV1.__dict__.keys()
    )
