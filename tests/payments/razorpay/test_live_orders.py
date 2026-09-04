import os
from pathlib import Path
from uuid import uuid4

import pytest

from clear_market.payments.razorpay import (
    RazorpayOrderResolutionV1,
    RazorpayTestCredentialsV1,
    create_razorpay_test_order_v1,
)
from clear_market.persistence import open_sqlite_financial_ledger_v1
from tests.certificate.v2.test_serialization import _certificate
from tests.execution.test_governor import _request_for
from tests.execution.test_models import _TIME
from tests.verification.v2.test_verifier import _trusted


def test_live_razorpay_test_mode_order_create_then_existing_get(tmp_path: Path) -> None:
    if os.environ.get("CLEAR_RUN_RAZORPAY_TEST_MODE") != "1":
        pytest.skip("Razorpay Test Mode live test is not enabled")
    key_id = os.environ.get("RAZORPAY_TEST_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_TEST_KEY_SECRET")
    if key_id is None or key_secret is None:
        pytest.skip("Razorpay Test Mode credentials are unavailable")

    certificate = _certificate()
    request = _request_for(certificate, execution_id=str(uuid4()))
    credentials = RazorpayTestCredentialsV1(key_id=key_id, key_secret=key_secret)
    database_path = tmp_path / "live-ledger.db"
    with open_sqlite_financial_ledger_v1(str(database_path)) as ledger:
        created = create_razorpay_test_order_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            execution_request=request,
            decision_time=_TIME,
            ledger=ledger,
            credentials=credentials,
        )
        existing = create_razorpay_test_order_v1(
            certificate=certificate,
            trusted_signing_identities=_trusted(),
            execution_request=request,
            decision_time=_TIME,
            ledger=ledger,
            credentials=credentials,
        )

    assert created.resolution is RazorpayOrderResolutionV1.CREATED
    assert existing.resolution is RazorpayOrderResolutionV1.EXISTING
    assert existing.order.provider_order_id == created.order.provider_order_id
    assert created.order.amount.amount_paise == 2_700
    assert created.order.currency == "INR"
    assert created.order.receipt == request.execution_id
