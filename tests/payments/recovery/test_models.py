from types import MappingProxyType

import pytest
from pydantic import ValidationError

import clear_market.payments.recovery as recovery
from clear_market.domain import Money
from clear_market.payments.razorpay import RazorpayOrderStatusV1, RazorpayOrderV1
from clear_market.payments.recovery import (
    RAZORPAY_ORDER_RECOVERY_RESULT_V1_VERSION,
    RAZORPAY_ORDER_RECOVERY_V1_VERSION,
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryFailureCode,
    RazorpayOrderRecoveryResultV1,
)

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_OTHER_EXECUTION_ID = "e1000000-0000-4000-8000-000000000002"
_FINGERPRINT = "9a5897d3c79273ee2e5a331f3a36bb65093f41f7ed9b1c6e5d898af555ebd45c"


def _order(*, execution_id: str = _EXECUTION_ID) -> RazorpayOrderV1:
    return RazorpayOrderV1(
        execution_id=execution_id,
        provider_order_id="order_CLEARReview1",
        amount=Money(amount_paise=2_700),
        receipt=execution_id,
        status=RazorpayOrderStatusV1.CREATED,
    )


def _result(**changes: object) -> RazorpayOrderRecoveryResultV1:
    values: dict[str, object] = {
        "disposition": RazorpayOrderRecoveryDispositionV1.RECOVERED,
        "execution_id": _EXECUTION_ID,
        "order_create_fingerprint_sha256": _FINGERPRINT,
        "order": _order(),
    }
    values.update(changes)
    return RazorpayOrderRecoveryResultV1(**values)  # type: ignore[arg-type]


def test_versions_enums_failure_codes_and_public_api_are_exact() -> None:
    assert RAZORPAY_ORDER_RECOVERY_V1_VERSION == "razorpay-order-recovery-v1"
    assert RAZORPAY_ORDER_RECOVERY_RESULT_V1_VERSION == "razorpay-order-recovery-result-v1"
    assert tuple(RazorpayOrderRecoveryDispositionV1) == (
        RazorpayOrderRecoveryDispositionV1.RECOVERED,
        RazorpayOrderRecoveryDispositionV1.EXISTING,
        RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
    )
    assert tuple(item.value for item in RazorpayOrderRecoveryDispositionV1) == (
        "RECOVERED",
        "EXISTING",
        "NOT_FOUND",
    )
    assert tuple(RazorpayOrderRecoveryFailureCode) == (
        RazorpayOrderRecoveryFailureCode.LOCAL_PROVIDER_REFERENCE_CONFLICT,
        RazorpayOrderRecoveryFailureCode.CREATE_INTENT_MISSING,
        RazorpayOrderRecoveryFailureCode.CREATE_INTENT_CONFLICT,
        RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_QUERY_FAILED,
        RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_AMBIGUOUS,
        RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_FETCH_FAILED,
        RazorpayOrderRecoveryFailureCode.PROVIDER_ORDER_MISMATCH,
    )
    assert tuple(item.value for item in RazorpayOrderRecoveryFailureCode) == tuple(
        item.name for item in RazorpayOrderRecoveryFailureCode
    )
    assert recovery.__all__ == (
        "RAZORPAY_ORDER_RECOVERY_V1_VERSION",
        "RAZORPAY_ORDER_RECOVERY_RESULT_V1_VERSION",
        "RazorpayOrderRecoveryDispositionV1",
        "RazorpayOrderRecoveryResultV1",
        "RazorpayOrderRecoveryFailureCode",
        "RazorpayOrderRecoveryError",
        "recover_razorpay_test_order_v1",
    )


def test_result_field_order_and_exact_versions_are_frozen() -> None:
    assert tuple(RazorpayOrderRecoveryResultV1.model_fields) == (
        "schema_version",
        "razorpay_order_recovery_result_version",
        "recovery_version",
        "disposition",
        "execution_id",
        "order_create_fingerprint_version",
        "order_create_fingerprint_sha256",
        "order",
    )
    assert _result().model_dump(mode="json") == {
        "schema_version": "1",
        "razorpay_order_recovery_result_version": "razorpay-order-recovery-result-v1",
        "recovery_version": "razorpay-order-recovery-v1",
        "disposition": "RECOVERED",
        "execution_id": _EXECUTION_ID,
        "order_create_fingerprint_version": (
            "sha256-razorpay-order-create-intent-v1-clear-json-v1"
        ),
        "order_create_fingerprint_sha256": _FINGERPRINT,
        "order": {
            "schema_version": "1",
            "razorpay_order_version": "razorpay-order-v1",
            "execution_id": _EXECUTION_ID,
            "provider_order_id": "order_CLEARReview1",
            "amount": {"amount_paise": 2_700, "currency": "INR"},
            "currency": "INR",
            "receipt": _EXECUTION_ID,
            "status": "created",
        },
    }


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "razorpay_order_recovery_result_version",
        "recovery_version",
        "order_create_fingerprint_version",
    ),
)
def test_versions_reject_wrong_values(field: str) -> None:
    with pytest.raises(ValidationError):
        _result(**{field: "wrong"})


def test_result_is_strict_frozen_and_forbids_extra() -> None:
    value = _result()
    with pytest.raises(ValidationError):
        value.execution_id = _OTHER_EXECUTION_ID  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _result(disposition="RECOVERED")
    with pytest.raises(ValidationError):
        _result(extra="forbidden")


@pytest.mark.parametrize(
    "fingerprint",
    ("0" * 63, "0" * 65, "A" * 64, "g" * 64, 1, None),
)
def test_fingerprint_is_exact_lowercase_sha256(fingerprint: object) -> None:
    with pytest.raises(ValidationError):
        _result(order_create_fingerprint_sha256=fingerprint)


@pytest.mark.parametrize(
    "disposition",
    (
        RazorpayOrderRecoveryDispositionV1.RECOVERED,
        RazorpayOrderRecoveryDispositionV1.EXISTING,
    ),
)
def test_recovered_and_existing_require_order(
    disposition: RazorpayOrderRecoveryDispositionV1,
) -> None:
    assert _result(disposition=disposition).order == _order()
    with pytest.raises(ValidationError):
        _result(disposition=disposition, order=None)


def test_not_found_requires_no_order() -> None:
    value = _result(
        disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND,
        order=None,
    )
    assert value.order is None
    with pytest.raises(ValidationError):
        _result(disposition=RazorpayOrderRecoveryDispositionV1.NOT_FOUND)


def test_order_execution_must_match_result() -> None:
    with pytest.raises(ValidationError):
        _result(order=_order(execution_id=_OTHER_EXECUTION_ID))


def test_order_requires_fresh_exact_type() -> None:
    class _OrderSubclass(RazorpayOrderV1):
        pass

    with pytest.raises(ValidationError):
        _result(order=_OrderSubclass.model_construct(**_order().__dict__))
    with pytest.raises(ValidationError):
        _result(order=_order().model_dump(mode="python"))


@pytest.mark.parametrize(
    "malformed",
    (
        RazorpayOrderV1.model_construct(),
        RazorpayOrderV1.model_construct(
            execution_id=_EXECUTION_ID,
            provider_order_id="order_CLEARReview1",
            amount=Money.model_construct(amount_paise="2700", currency="INR"),
            currency="INR",
            receipt=_EXECUTION_ID,
            status=RazorpayOrderStatusV1.CREATED,
        ),
    ),
)
def test_model_construct_order_corruption_fails_closed(malformed: RazorpayOrderV1) -> None:
    with pytest.raises(ValidationError):
        _result(order=malformed)


def test_model_configuration_is_exact() -> None:
    config = RazorpayOrderRecoveryResultV1.model_config
    assert MappingProxyType(dict(config)) == MappingProxyType(
        {
            "frozen": True,
            "extra": "forbid",
            "strict": True,
            "revalidate_instances": "always",
        }
    )


def test_authority_limitation_is_documented() -> None:
    doc = RazorpayOrderRecoveryResultV1.__doc__ or ""
    assert "not Money Governor authority" in doc
    for action in (
        "payment",
        "capture",
        "transfer",
        "refund",
        "reversal",
        "fulfillment",
        "settlement",
    ):
        assert action in doc
