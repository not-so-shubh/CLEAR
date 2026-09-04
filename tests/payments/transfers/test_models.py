from datetime import UTC, datetime
from enum import StrEnum

import pytest
from pydantic import ValidationError

import clear_market.payments.transfers as transfers
from clear_market.domain import Currency, Money
from clear_market.payments.transfers import (
    RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION,
    RAZORPAY_TRANSFER_BATCH_RESULT_V1_VERSION,
    RAZORPAY_TRANSFER_OBSERVATION_V1_VERSION,
    RAZORPAY_TRANSFER_REQUEST_FINGERPRINT_V1_VERSION,
    RazorpaySettlementStatusV1,
    RazorpayTransferBatchDispositionV1,
    RazorpayTransferBatchResultV1,
    RazorpayTransferObservationV1,
    RazorpayTransferStatusV1,
)

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_ORDER_ID = "order_CLEARReview1"
_PAYMENT_ID = "pay_CLEARReview1"
_CONFIG = {
    "frozen": True,
    "extra": "forbid",
    "strict": True,
    "revalidate_instances": "always",
}


def _observation(index: int = 0, **changes: object) -> RazorpayTransferObservationV1:
    values: dict[str, object] = {
        "allocation_line_index": index,
        "provider_transfer_id": f"trf_CLEARReview{index + 1}",
        "provider_payment_id": _PAYMENT_ID,
        "razorpay_account_id": f"acc_CLEAR{index + 1:08d}",
        "amount": Money(amount_paise=1_500 if index == 0 else 1_200),
        "transfer_status": RazorpayTransferStatusV1.CREATED,
        "settlement_status": None,
        "amount_reversed": 0,
        "created_at_unix": 1_788_262_300 + index,
        **changes,
    }
    return RazorpayTransferObservationV1(**values)


def _result(**changes: object) -> RazorpayTransferBatchResultV1:
    values: dict[str, object] = {
        "disposition": RazorpayTransferBatchDispositionV1.CREATED,
        "execution_id": _EXECUTION_ID,
        "provider_order_id": _ORDER_ID,
        "provider_payment_id": _PAYMENT_ID,
        "transfer_request_fingerprint_sha256": "a" * 64,
        "route_mapping_fingerprint_version": (
            "sha256-razorpay-route-mapping-request-v1-clear-json-v1"
        ),
        "route_mapping_fingerprint_sha256": "b" * 64,
        "transfers": (_observation(0), _observation(1)),
        **changes,
    }
    return RazorpayTransferBatchResultV1(**values)


def test_versions_enums_and_public_api_are_exact() -> None:
    assert RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION == (
        "razorpay-payment-transfer-execution-v1"
    )
    assert RAZORPAY_TRANSFER_OBSERVATION_V1_VERSION == "razorpay-transfer-observation-v1"
    assert RAZORPAY_TRANSFER_BATCH_RESULT_V1_VERSION == "razorpay-transfer-batch-result-v1"
    assert RAZORPAY_TRANSFER_REQUEST_FINGERPRINT_V1_VERSION == (
        "sha256-razorpay-payment-transfer-request-v1-clear-json-v1"
    )
    assert issubclass(RazorpayTransferStatusV1, StrEnum)
    assert tuple(item.value for item in RazorpayTransferStatusV1) == (
        "created",
        "pending",
        "processed",
        "failed",
        "reversed",
        "partially_reversed",
    )
    assert tuple(item.value for item in RazorpaySettlementStatusV1) == (
        "pending",
        "on_hold",
        "settled",
    )
    assert tuple(item.value for item in RazorpayTransferBatchDispositionV1) == (
        "CREATED",
        "RECOVERED",
        "EXISTING",
    )
    assert transfers.__all__ == (
        "RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION",
        "RAZORPAY_TRANSFER_OBSERVATION_V1_VERSION",
        "RAZORPAY_TRANSFER_BATCH_RESULT_V1_VERSION",
        "RAZORPAY_TRANSFER_REQUEST_FINGERPRINT_V1_VERSION",
        "RazorpayTransferStatusV1",
        "RazorpaySettlementStatusV1",
        "RazorpayTransferBatchDispositionV1",
        "RazorpayTransferObservationV1",
        "RazorpayTransferBatchResultV1",
        "RazorpayTransferFailureCode",
        "RazorpayTransferError",
        "canonical_razorpay_payment_transfer_request_v1_bytes",
        "razorpay_payment_transfer_request_fingerprint_v1",
        "create_or_reconcile_razorpay_test_transfers_v1",
    )


def test_model_fields_versions_and_configuration_are_exact() -> None:
    assert tuple(RazorpayTransferObservationV1.model_fields) == (
        "schema_version",
        "razorpay_transfer_observation_version",
        "allocation_line_index",
        "provider_transfer_id",
        "provider_payment_id",
        "razorpay_account_id",
        "amount",
        "transfer_status",
        "settlement_status",
        "amount_reversed",
        "created_at_unix",
    )
    assert tuple(RazorpayTransferBatchResultV1.model_fields) == (
        "schema_version",
        "razorpay_transfer_batch_result_version",
        "transfer_execution_version",
        "disposition",
        "execution_id",
        "provider_order_id",
        "provider_payment_id",
        "transfer_request_fingerprint_version",
        "transfer_request_fingerprint_sha256",
        "route_mapping_fingerprint_version",
        "route_mapping_fingerprint_sha256",
        "transfers",
    )
    assert RazorpayTransferObservationV1.model_config == _CONFIG
    assert RazorpayTransferBatchResultV1.model_config == _CONFIG
    assert _observation().schema_version == "1"
    assert _result().transfer_execution_version == RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION


def test_observation_is_strict_frozen_and_extra_forbidden() -> None:
    value = _observation()
    with pytest.raises(ValidationError):
        value.amount_reversed = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _observation(extra="forbidden")
    for name, invalid in (
        ("allocation_line_index", True),
        ("amount_reversed", False),
        ("created_at_unix", True),
    ):
        with pytest.raises(ValidationError):
            _observation(**{name: invalid})


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("provider_transfer_id", "bad"),
        ("provider_transfer_id", "trf_é"),
        ("provider_payment_id", "bad"),
        ("razorpay_account_id", "bad"),
        ("allocation_line_index", -1),
        ("amount_reversed", -1),
        ("created_at_unix", -1),
        ("created_at_unix", 10**30),
    ),
)
def test_observation_rejects_invalid_provider_facts(field: str, invalid: object) -> None:
    with pytest.raises(ValidationError):
        _observation(**{field: invalid})


def test_observation_freshly_revalidates_money_and_reversal_bound() -> None:
    with pytest.raises(ValidationError):
        _observation(amount={"amount_paise": 1_500, "currency": "INR"})
    with pytest.raises(ValidationError):
        _observation(amount=Money.model_construct(currency=Currency.INR))
    with pytest.raises(ValidationError):
        _observation(amount_reversed=1_501)


@pytest.mark.parametrize("status", tuple(RazorpayTransferStatusV1))
def test_every_transfer_status_is_an_observed_provider_fact(
    status: RazorpayTransferStatusV1,
) -> None:
    assert _observation(transfer_status=status).transfer_status is status


@pytest.mark.parametrize("status", (None, *tuple(RazorpaySettlementStatusV1)))
def test_every_settlement_status_is_an_observed_provider_fact(
    status: RazorpaySettlementStatusV1 | None,
) -> None:
    assert _observation(settlement_status=status).settlement_status is status


def test_result_requires_exact_nonempty_ordered_observation_tuple() -> None:
    with pytest.raises(ValidationError):
        _result(transfers=[])
    with pytest.raises(ValidationError):
        _result(transfers=())
    with pytest.raises(ValidationError):
        _result(transfers=(_observation(1), _observation(0)))
    with pytest.raises(ValidationError):
        _result(transfers=(_observation(0), _observation(0)))


def test_result_rejects_payment_mismatch_duplicate_ids_and_bad_hashes() -> None:
    with pytest.raises(ValidationError):
        _result(transfers=(_observation(0), _observation(1, provider_payment_id="pay_other")))
    with pytest.raises(ValidationError):
        _result(
            transfers=(_observation(0), _observation(1, provider_transfer_id="trf_CLEARReview1"))
        )
    with pytest.raises(ValidationError):
        _result(transfer_request_fingerprint_sha256="A" * 64)


def test_result_language_does_not_claim_settlement_or_irreversibility() -> None:
    documentation = RazorpayTransferBatchResultV1.__doc__ or ""
    assert "never settlement" in documentation
    assert "None proves bank settlement" in documentation
    assert "irreversibility" in documentation
    assert "future refund or reversal" in documentation


def test_observation_serializes_enums_and_money_without_float() -> None:
    dumped = _observation(
        transfer_status=RazorpayTransferStatusV1.PROCESSED,
        settlement_status=RazorpaySettlementStatusV1.SETTLED,
    ).model_dump(mode="json")
    assert dumped["amount"] == {"amount_paise": 1_500, "currency": "INR"}
    assert dumped["transfer_status"] == "processed"
    assert dumped["settlement_status"] == "settled"
    assert not any(isinstance(value, float) for value in dumped.values())


def test_created_at_unix_has_an_exact_utc_interpretation() -> None:
    value = _observation(created_at_unix=1_788_262_300)
    assert datetime.fromtimestamp(value.created_at_unix, tz=UTC) == datetime(
        2026,
        9,
        1,
        11,
        31,
        40,
        tzinfo=UTC,
    )
