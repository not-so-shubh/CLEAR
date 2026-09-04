from enum import StrEnum
from types import MappingProxyType

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.orchestration.graceful as graceful
from clear_market.orchestration import RazorpayExecutionOrchestrationResultV1
from clear_market.orchestration.graceful import (
    RAZORPAY_GRACEFUL_EXECUTION_ORCHESTRATOR_V1_VERSION,
    RAZORPAY_GRACEFUL_EXECUTION_RESULT_V1_VERSION,
    RazorpayGracefulExecutionDispositionV1,
    RazorpayGracefulExecutionResultV1,
    RazorpayGracefulRecoveryReasonV1,
)
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryResultV1,
)
from tests.orchestration.test_models import (
    _order_result,
    _payment_state,
)
from tests.orchestration.test_models import (
    _result as _execution_result,
)
from tests.payments.recovery.test_models import _result as _order_recovery_result

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_OTHER_EXECUTION_ID = "e1000000-0000-4000-8000-000000000002"
_CONFIG = MappingProxyType(
    {
        "frozen": True,
        "extra": "forbid",
        "strict": True,
        "revalidate_instances": "always",
    }
)


class _ExecutionResultSubclass(RazorpayExecutionOrchestrationResultV1):
    pass


class _OrderRecoveryResultSubclass(RazorpayOrderRecoveryResultV1):
    pass


def _validated_copy[ModelT: BaseModel](model: ModelT, **changes: object) -> ModelT:
    fields = {name: model.__dict__[name] for name in type(model).model_fields}
    fields.update(changes)
    return type(model).model_validate(fields)


def _result(
    *,
    disposition: RazorpayGracefulExecutionDispositionV1 = (
        RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT
    ),
    execution_id: str = _EXECUTION_ID,
    execution_result: object | None = None,
    order_recovery_result: object | None = None,
    recovery_reason: RazorpayGracefulRecoveryReasonV1 | None = None,
) -> RazorpayGracefulExecutionResultV1:
    selected_execution = _execution_result() if execution_result is None else execution_result
    return RazorpayGracefulExecutionResultV1(
        disposition=disposition,
        execution_id=execution_id,
        execution_result=selected_execution,
        order_recovery_result=order_recovery_result,
        recovery_reason=recovery_reason,
    )


def _pending(
    *,
    disposition: RazorpayGracefulExecutionDispositionV1,
    reason: RazorpayGracefulRecoveryReasonV1,
    recovery: object | None = None,
) -> RazorpayGracefulExecutionResultV1:
    return RazorpayGracefulExecutionResultV1(
        disposition=disposition,
        execution_id=_EXECUTION_ID,
        execution_result=None,
        order_recovery_result=recovery,
        recovery_reason=reason,
    )


def _other_order_recovery() -> RazorpayOrderRecoveryResultV1:
    order = _order_recovery_result().order
    assert order is not None
    return _order_recovery_result(
        execution_id=_OTHER_EXECUTION_ID,
        order=_validated_copy(
            order,
            execution_id=_OTHER_EXECUTION_ID,
            receipt=_OTHER_EXECUTION_ID,
        ),
    )


def test_versions_enums_and_public_api_are_exact() -> None:
    assert RAZORPAY_GRACEFUL_EXECUTION_ORCHESTRATOR_V1_VERSION == (
        "razorpay-graceful-execution-orchestrator-v1"
    )
    assert RAZORPAY_GRACEFUL_EXECUTION_RESULT_V1_VERSION == (
        "razorpay-graceful-execution-result-v1"
    )
    assert issubclass(RazorpayGracefulExecutionDispositionV1, StrEnum)
    assert tuple(RazorpayGracefulExecutionDispositionV1) == (
        RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
        RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING,
        RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING,
    )
    assert tuple(item.value for item in RazorpayGracefulExecutionDispositionV1) == tuple(
        item.name for item in RazorpayGracefulExecutionDispositionV1
    )
    assert tuple(RazorpayGracefulRecoveryReasonV1) == (
        RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND,
        RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED,
        RazorpayGracefulRecoveryReasonV1.ORDER_FETCH_FAILED,
        RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING,
    )
    assert tuple(item.value for item in RazorpayGracefulRecoveryReasonV1) == tuple(
        item.name for item in RazorpayGracefulRecoveryReasonV1
    )
    assert graceful.__all__ == (
        "RAZORPAY_GRACEFUL_EXECUTION_ORCHESTRATOR_V1_VERSION",
        "RAZORPAY_GRACEFUL_EXECUTION_RESULT_V1_VERSION",
        "RazorpayGracefulExecutionDispositionV1",
        "RazorpayGracefulRecoveryReasonV1",
        "RazorpayGracefulExecutionResultV1",
        "run_razorpay_test_execution_with_recovery_v1",
    )


def test_result_fields_versions_and_configuration_are_exact() -> None:
    value = _result()
    assert tuple(RazorpayGracefulExecutionResultV1.model_fields) == (
        "schema_version",
        "razorpay_graceful_execution_result_version",
        "graceful_orchestrator_version",
        "disposition",
        "execution_id",
        "execution_result",
        "order_recovery_result",
        "recovery_reason",
    )
    assert MappingProxyType(dict(RazorpayGracefulExecutionResultV1.model_config)) == _CONFIG
    assert value.schema_version == "1"
    assert value.razorpay_graceful_execution_result_version == (
        RAZORPAY_GRACEFUL_EXECUTION_RESULT_V1_VERSION
    )
    assert value.graceful_orchestrator_version == (
        RAZORPAY_GRACEFUL_EXECUTION_ORCHESTRATOR_V1_VERSION
    )


def test_result_is_strict_frozen_and_forbids_extra() -> None:
    value = _result()
    with pytest.raises(ValidationError):
        value.execution_id = _OTHER_EXECUTION_ID  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RazorpayGracefulExecutionResultV1(
            disposition="EXECUTION_RESULT",  # type: ignore[arg-type]
            execution_id=_EXECUTION_ID,
            execution_result=_execution_result(),
            order_recovery_result=None,
            recovery_reason=None,
        )
    with pytest.raises(ValidationError):
        RazorpayGracefulExecutionResultV1(
            disposition=RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
            execution_id=_EXECUTION_ID,
            execution_result=_execution_result(),
            order_recovery_result=None,
            recovery_reason=None,
            extra="forbidden",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("execution_result", _execution_result().model_dump(mode="python")),
        ("order_recovery_result", _order_recovery_result().model_dump(mode="python")),
        ("execution_result", RazorpayExecutionOrchestrationResultV1.model_construct()),
        ("order_recovery_result", RazorpayOrderRecoveryResultV1.model_construct()),
        (
            "execution_result",
            _ExecutionResultSubclass.model_construct(**_execution_result().__dict__),
        ),
        (
            "order_recovery_result",
            _OrderRecoveryResultSubclass.model_construct(**_order_recovery_result().__dict__),
        ),
    ),
)
def test_nested_results_require_fresh_exact_models(field: str, invalid: object) -> None:
    values: dict[str, object] = {
        "disposition": RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
        "execution_id": _EXECUTION_ID,
        "execution_result": _execution_result(),
        "order_recovery_result": _order_recovery_result(),
        "recovery_reason": None,
    }
    values[field] = invalid
    with pytest.raises(ValidationError, match="graceful orchestration result mismatch"):
        RazorpayGracefulExecutionResultV1(**values)  # type: ignore[arg-type]


def test_stale_invalid_nested_models_fail_closed() -> None:
    stale = RazorpayOrderRecoveryResultV1.model_construct(
        **{
            **_order_recovery_result().__dict__,
            "execution_id": _OTHER_EXECUTION_ID,
        }
    )
    with pytest.raises(ValidationError, match="graceful orchestration result mismatch"):
        _result(order_recovery_result=stale)


@pytest.mark.parametrize(
    "recovery",
    (
        None,
        _order_recovery_result(),
        _order_recovery_result(disposition=RazorpayOrderRecoveryDispositionV1.EXISTING),
    ),
)
def test_execution_result_accepts_no_recovery_or_successful_order_recovery(
    recovery: RazorpayOrderRecoveryResultV1 | None,
) -> None:
    value = _result(order_recovery_result=recovery)
    assert value.disposition is RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT
    assert value.execution_result == _execution_result()
    assert value.order_recovery_result == recovery
    assert value.recovery_reason is None


@pytest.mark.parametrize(
    "changes",
    (
        {"execution_result": None},
        {"execution_id": _OTHER_EXECUTION_ID},
        {"recovery_reason": RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND},
        {
            "order_recovery_result": _order_recovery_result(
                disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
                order=None,
            )
        },
        {"order_recovery_result": _other_order_recovery()},
    ),
)
def test_execution_result_rejects_invalid_shapes(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "disposition": RazorpayGracefulExecutionDispositionV1.EXECUTION_RESULT,
        "execution_id": _EXECUTION_ID,
        "execution_result": _execution_result(),
        "order_recovery_result": None,
        "recovery_reason": None,
    }
    values.update(changes)
    with pytest.raises(ValidationError, match="graceful orchestration result mismatch"):
        RazorpayGracefulExecutionResultV1(**values)  # type: ignore[arg-type]


def test_execution_result_rejects_order_provider_mismatch() -> None:
    different_execution = _execution_result(
        order=_order_result(provider_order_id="order_OtherReview1"),
        state=_payment_state(provider_order_id="order_OtherReview1"),
    )
    with pytest.raises(ValidationError, match="graceful orchestration result mismatch"):
        _result(
            execution_result=different_execution, order_recovery_result=_order_recovery_result()
        )


def test_order_not_found_pending_shape_is_exact() -> None:
    recovery = _order_recovery_result(
        disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
        order=None,
    )
    value = _pending(
        disposition=RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING,
        reason=RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND,
        recovery=recovery,
    )
    assert value.execution_result is None
    assert value.order_recovery_result == recovery


@pytest.mark.parametrize(
    "reason",
    (
        RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED,
        RazorpayGracefulRecoveryReasonV1.ORDER_FETCH_FAILED,
    ),
)
def test_temporary_order_pending_shapes_are_exact(
    reason: RazorpayGracefulRecoveryReasonV1,
) -> None:
    value = _pending(
        disposition=RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING,
        reason=reason,
    )
    assert value.execution_result is None
    assert value.order_recovery_result is None


@pytest.mark.parametrize(
    ("reason", "recovery"),
    (
        (RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND, None),
        (
            RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND,
            _order_recovery_result(),
        ),
        (
            RazorpayGracefulRecoveryReasonV1.ORDER_QUERY_FAILED,
            _order_recovery_result(
                disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
                order=None,
            ),
        ),
        (RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING, None),
    ),
)
def test_order_pending_rejects_inconsistent_reason_and_recovery(
    reason: RazorpayGracefulRecoveryReasonV1,
    recovery: RazorpayOrderRecoveryResultV1 | None,
) -> None:
    with pytest.raises(ValidationError, match="graceful orchestration result mismatch"):
        _pending(
            disposition=RazorpayGracefulExecutionDispositionV1.ORDER_RECOVERY_PENDING,
            reason=reason,
            recovery=recovery,
        )


@pytest.mark.parametrize(
    "recovery",
    (
        None,
        _order_recovery_result(),
        _order_recovery_result(disposition=RazorpayOrderRecoveryDispositionV1.EXISTING),
    ),
)
def test_transfer_pending_accepts_optional_successful_order_recovery(
    recovery: RazorpayOrderRecoveryResultV1 | None,
) -> None:
    value = _pending(
        disposition=RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING,
        reason=RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING,
        recovery=recovery,
    )
    assert value.execution_result is None
    assert value.order_recovery_result == recovery


@pytest.mark.parametrize(
    ("reason", "recovery"),
    (
        (RazorpayGracefulRecoveryReasonV1.ORDER_NOT_FOUND, None),
        (
            RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING,
            _order_recovery_result(
                disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
                order=None,
            ),
        ),
        (
            RazorpayGracefulRecoveryReasonV1.TRANSFER_RECONCILIATION_PENDING,
            _other_order_recovery(),
        ),
    ),
)
def test_transfer_pending_rejects_invalid_shape(
    reason: RazorpayGracefulRecoveryReasonV1,
    recovery: RazorpayOrderRecoveryResultV1 | None,
) -> None:
    with pytest.raises(ValidationError, match="graceful orchestration result mismatch"):
        _pending(
            disposition=RazorpayGracefulExecutionDispositionV1.TRANSFER_RECOVERY_PENDING,
            reason=reason,
            recovery=recovery,
        )


def test_result_authority_limitations_are_explicit_and_no_side_effect_methods_exist() -> None:
    documentation = RazorpayGracefulExecutionResultV1.__doc__ or ""
    normalized = " ".join(documentation.split())
    for claim in (
        "bounded orchestration and recovery outcomes",
        "does not establish certificate validity",
        "financial authorization",
        "provider truth",
        "payment capture",
        "routing authority",
        "transfer authority",
        "settlement",
        "fulfillment",
        "permission to retry a provider mutation",
        "must invoke the authoritative subsystem APIs",
        "must not use this result as money-movement authority",
    ):
        assert claim in normalized
    assert (
        not {
            "authorize",
            "create_order",
            "recover_order",
            "create_transfers",
            "retry",
            "execute",
            "persist",
        }
        & RazorpayGracefulExecutionResultV1.__dict__.keys()
    )
