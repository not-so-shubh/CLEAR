"""Opt-in presentation boundary for current-run Razorpay Test Mode order evidence."""

from __future__ import annotations

import http.client
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import clear_market.payments.razorpay.orders as orders_module
from clear_market.certificate.v2 import AllocationCertificateV2
from clear_market.commerce import MerchantSigningIdentityV2
from clear_market.demo import _DECISION_TIME, _certificate_fixture, _execution_request, _identity
from clear_market.execution import (
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
    authorize_execution_v1,
)
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    RazorpayOrderTransportV1,
    RazorpayTestCredentialsV1,
    create_razorpay_test_order_v1,
)
from clear_market.persistence import open_sqlite_financial_ledger_v1
from clear_market.verification.v2 import verify_allocation_certificate_v2

_PRESENTATION_VERSION = "clear-razorpay-test-order-evidence-v1"
_MODE = "RAZORPAY TEST MODE"
_NETWORK_ERRORS = (TimeoutError, ssl.SSLError, http.client.HTTPException, OSError)


@dataclass(frozen=True)
class _AuthorityInputs:
    certificate: AllocationCertificateV2
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...]
    execution_request: ExecutionAuthorizationRequestV1
    decision_time: datetime


class _ObservedTransport:
    """Record safe transport facts while delegating all provider work to the existing adapter."""

    def __init__(self, transport: RazorpayOrderTransportV1) -> None:
        self._transport = transport
        self.methods: list[str] = []
        self.statuses: list[int] = []
        self.network_failure = False

    def __call__(
        self,
        *,
        method: str,
        path: str,
        credentials: RazorpayTestCredentialsV1,
        body: bytes | None,
    ) -> tuple[int, bytes]:
        self.methods.append(method)
        try:
            status, data = self._transport(
                method=method,
                path=path,
                credentials=credentials,
                body=body,
            )
        except _NETWORK_ERRORS:
            self.network_failure = True
            raise
        self.statuses.append(status)
        return status, data


def _production_transport(
    *,
    method: str,
    path: str,
    credentials: RazorpayTestCredentialsV1,
    body: bytes | None,
) -> tuple[int, bytes]:
    # Delegate to the production adapter's credential, TLS, size-limit, and timeout boundary.
    return orders_module._https_request(
        method=method,
        path=path,
        credentials=credentials,
        body=body,
    )


def _authority_inputs() -> _AuthorityInputs:
    _policy, _signed_offers, certificate = _certificate_fixture()
    execution_id = str(uuid4())
    return _AuthorityInputs(
        certificate=certificate,
        trusted_signing_identities=(_identity(1), _identity(2)),
        execution_request=_execution_request(certificate, execution_id),
        decision_time=_DECISION_TIME,
    )


def _result(
    *,
    result: str,
    code: str,
    message: str,
    authority_verified: bool,
    governor_state: str,
    execution_reserved: bool,
    provider_contacted: bool,
) -> dict[str, Any]:
    return {
        "presentation_version": _PRESENTATION_VERSION,
        "result": result,
        "code": code,
        "message": message,
        "mode": _MODE,
        "current_run": True,
        "authority_verified": authority_verified,
        "governor_state": governor_state,
        "execution_reserved": execution_reserved,
        "provider_contacted": provider_contacted,
    }


def unavailable_presentation(code: str, message: str) -> dict[str, Any]:
    """Build a safe endpoint-level unavailable response without provider or credential facts."""

    return _result(
        result="UNAVAILABLE",
        code=code,
        message=message,
        authority_verified=False,
        governor_state="NOT REACHED",
        execution_reserved=False,
        provider_contacted=False,
    )


def _credentials(environment: Mapping[str, str]) -> RazorpayTestCredentialsV1 | None:
    key_id = environment.get("RAZORPAY_TEST_KEY_ID")
    key_secret = environment.get("RAZORPAY_TEST_KEY_SECRET")
    if not key_id or not key_secret:
        return None
    try:
        return RazorpayTestCredentialsV1(key_id=key_id, key_secret=key_secret)
    except ValueError:
        return None


def _provider_failure(
    error: RazorpayOrderError,
    observation: _ObservedTransport,
) -> dict[str, Any]:
    contacted = bool(observation.methods)
    common = {
        "authority_verified": True,
        "governor_state": "EXECUTION RESERVED",
        "execution_reserved": True,
        "provider_contacted": contacted,
    }
    if any(status in {401, 403} for status in observation.statuses):
        return _result(
            result="FAILED",
            code="PROVIDER_AUTHENTICATION_FAILURE",
            message="Razorpay Test Mode rejected the server-side credentials.",
            **common,
        )
    if observation.network_failure:
        return _result(
            result="FAILED",
            code="PROVIDER_TIMEOUT_OR_NETWORK_FAILURE",
            message="The bounded Razorpay Test Mode request did not complete over the network.",
            **common,
        )
    if error.code is RazorpayOrderFailureCode.PROVIDER_ORDER_MISMATCH:
        return _result(
            result="FAILED",
            code="PROVIDER_ORDER_MISMATCH",
            message="The provider order identity or its authority-bound facts did not match.",
            **common,
        )
    if observation.statuses and observation.statuses[-1] == 200:
        return _result(
            result="FAILED",
            code="INVALID_PROVIDER_RESPONSE",
            message="Razorpay Test Mode returned facts that did not pass provider validation.",
            **common,
        )
    return _result(
        result="FAILED",
        code="PROVIDER_REQUEST_FAILURE",
        message="Razorpay Test Mode did not return a valid order response.",
        **common,
    )


def build_razorpay_test_order_evidence(
    *,
    environment: Mapping[str, str] | None = None,
    transport: RazorpayOrderTransportV1 | None = None,
    authority_inputs: _AuthorityInputs | None = None,
) -> dict[str, Any]:
    """Run one fresh, Governor-gated create/existing Test Mode evidence pair.

    The default transport is real Razorpay Test Mode. Tests inject a controlled transport, and
    the browser cannot select either authority inputs or provider transport.
    """

    selected_credentials = _credentials(os.environ if environment is None else environment)
    if selected_credentials is None:
        return unavailable_presentation(
            "LIVE_TEST_MODE_UNAVAILABLE",
            "Server-side Razorpay Test Mode credentials are unavailable or invalid.",
        )

    inputs = _authority_inputs() if authority_inputs is None else authority_inputs
    observation = _ObservedTransport(_production_transport if transport is None else transport)
    verification = verify_allocation_certificate_v2(
        inputs.certificate,
        trusted_signing_identities=inputs.trusted_signing_identities,
    )
    if not verification.verified:
        return _result(
            result="FAILED",
            code="AUTHORITY_VERIFICATION_FAILURE",
            message="AllocationCertificateV2 did not pass independent replay verification.",
            authority_verified=False,
            governor_state="CLOSED",
            execution_reserved=False,
            provider_contacted=False,
        )

    with TemporaryDirectory(prefix="clear-razorpay-evidence-") as temporary_directory:
        ledger_path = Path(temporary_directory) / "ledger.db"
        with open_sqlite_financial_ledger_v1(str(ledger_path)) as ledger:
            try:
                plan = authorize_execution_v1(
                    certificate=inputs.certificate,
                    trusted_signing_identities=inputs.trusted_signing_identities,
                    request=inputs.execution_request,
                    decision_time=inputs.decision_time,
                    ledger=ledger,
                )
            except MoneyGovernorError as error:
                code = (
                    "AUTHORITY_VERIFICATION_FAILURE"
                    if error.code is MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
                    else "MONEY_GOVERNOR_REFUSAL"
                )
                return _result(
                    result="FAILED",
                    code=code,
                    message=(
                        "AllocationCertificateV2 did not pass independent replay verification."
                        if code == "AUTHORITY_VERIFICATION_FAILURE"
                        else "The Money Governor refused this execution request."
                    ),
                    authority_verified=code != "AUTHORITY_VERIFICATION_FAILURE",
                    governor_state="CLOSED",
                    execution_reserved=False,
                    provider_contacted=False,
                )

            reservation = ledger.get_execution_reservation(plan.execution_id)
            if type(plan) is not ExecutionPlanV1 or reservation is None:
                return _result(
                    result="FAILED",
                    code="MONEY_GOVERNOR_REFUSAL",
                    message="The Money Governor did not produce and reserve ExecutionPlanV1.",
                    authority_verified=True,
                    governor_state="CLOSED",
                    execution_reserved=False,
                    provider_contacted=False,
                )

            try:
                first = create_razorpay_test_order_v1(
                    certificate=inputs.certificate,
                    trusted_signing_identities=inputs.trusted_signing_identities,
                    execution_request=inputs.execution_request,
                    decision_time=inputs.decision_time,
                    ledger=ledger,
                    credentials=selected_credentials,
                    transport=observation,
                )
                if first.resolution is not RazorpayOrderResolutionV1.CREATED:
                    return _result(
                        result="FAILED",
                        code="INVALID_PROVIDER_RESPONSE",
                        message="The first logical invocation was not resolved as CREATED.",
                        authority_verified=True,
                        governor_state="EXECUTION RESERVED",
                        execution_reserved=True,
                        provider_contacted=bool(observation.methods),
                    )
                second = create_razorpay_test_order_v1(
                    certificate=inputs.certificate,
                    trusted_signing_identities=inputs.trusted_signing_identities,
                    execution_request=inputs.execution_request,
                    decision_time=inputs.decision_time,
                    ledger=ledger,
                    credentials=selected_credentials,
                    transport=observation,
                )
            except RazorpayOrderError as error:
                return _provider_failure(error, observation)

    if second.resolution is not RazorpayOrderResolutionV1.EXISTING:
        return _result(
            result="FAILED",
            code="INVALID_PROVIDER_RESPONSE",
            message="The second identical invocation was not resolved as EXISTING.",
            authority_verified=True,
            governor_state="EXECUTION RESERVED",
            execution_reserved=True,
            provider_contacted=bool(observation.methods),
        )
    if first.order.provider_order_id != second.order.provider_order_id:
        return _result(
            result="FAILED",
            code="PROVIDER_ORDER_MISMATCH",
            message="The two invocations did not resolve the same provider order identity.",
            authority_verified=True,
            governor_state="EXECUTION RESERVED",
            execution_reserved=True,
            provider_contacted=True,
        )
    if tuple(observation.methods) != ("POST", "GET"):
        return _result(
            result="FAILED",
            code="INVALID_PROVIDER_RESPONSE",
            message="The provider path did not produce the required current-run observation.",
            authority_verified=True,
            governor_state="EXECUTION RESERVED",
            execution_reserved=True,
            provider_contacted=bool(observation.methods),
        )

    provider_order_id = first.order.provider_order_id
    return {
        "presentation_version": _PRESENTATION_VERSION,
        "result": "SUCCESS",
        "mode": _MODE,
        "current_run": True,
        "authority_verified": True,
        "governor_state": "EXECUTION RESERVED",
        "execution_reserved": True,
        "execution_plan": "ExecutionPlanV1",
        "first_invocation": {
            "resolution": "CREATED",
            "provider_order_id": provider_order_id,
        },
        "second_identical_invocation": {
            "resolution": "EXISTING",
            "provider_order_id": second.order.provider_order_id,
            "retrieval": "PROVIDER-BACKED",
        },
        "same_provider_order": True,
        "provider_contacted": True,
        "provider_observation": "CURRENT-RUN PROVIDER OBSERVATION",
        "scope": "Razorpay Test Mode order creation and existing-order resolution only.",
    }
