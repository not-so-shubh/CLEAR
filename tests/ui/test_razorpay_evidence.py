import json
from pathlib import Path
from typing import Any

import pytest

import clear_market.payments.razorpay.orders as orders_module
from clear_market.demo import _execution_request, _tampered_certificate
from clear_market.execution import MarketExecutionStateV1
from clear_market.payments.razorpay import RazorpayTestCredentialsV1
from ui.presentation import build_authority_demo_presentation
from ui.razorpay_evidence import (
    _authority_inputs,
    _AuthorityInputs,
    build_razorpay_test_order_evidence,
)

_ENVIRONMENT = {
    "RAZORPAY_TEST_KEY_ID": "rzp_test_current_run_evidence",
    "RAZORPAY_TEST_KEY_SECRET": "server-side-test-secret",
}
_ORDER_ID = "order_CLEARCurrentRun1"


class _Provider:
    def __init__(
        self,
        *,
        second_order_id: str | None = None,
        response_override: bytes | None = None,
        status: int = 200,
        failure: BaseException | None = None,
    ) -> None:
        self.second_order_id = second_order_id
        self.response_override = response_override
        self.status = status
        self.failure = failure
        self.calls: list[dict[str, object]] = []
        self.receipt: str | None = None

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        if self.response_override is not None:
            return self.status, self.response_override
        method = kwargs["method"]
        if method == "POST":
            body = kwargs["body"]
            assert isinstance(body, bytes)
            parsed = json.loads(body)
            self.receipt = parsed["receipt"]
            return self.status, self._response(_ORDER_ID)
        assert method == "GET"
        assert self.receipt is not None
        return self.status, self._response(self.second_order_id or _ORDER_ID)

    def _response(self, order_id: str) -> bytes:
        return json.dumps(
            {
                "amount": 2700,
                "amount_due": 2700,
                "amount_paid": 0,
                "attempts": 0,
                "currency": "INR",
                "entity": "order",
                "id": order_id,
                "partial_payment": False,
                "receipt": self.receipt,
                "status": "created",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    @property
    def methods(self) -> tuple[object, ...]:
        return tuple(call["method"] for call in self.calls)


@pytest.fixture(scope="module")
def authority_inputs() -> _AuthorityInputs:
    return _authority_inputs()


def test_valid_authority_reaches_production_adapter_and_returns_allowlisted_pair(
    authority_inputs: _AuthorityInputs,
) -> None:
    provider = _Provider()

    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=provider,
        authority_inputs=authority_inputs,
    )

    assert result == {
        "presentation_version": "clear-razorpay-test-order-evidence-v1",
        "result": "SUCCESS",
        "mode": "RAZORPAY TEST MODE",
        "current_run": True,
        "authority_verified": True,
        "governor_state": "EXECUTION RESERVED",
        "execution_reserved": True,
        "execution_plan": "ExecutionPlanV1",
        "first_invocation": {
            "resolution": "CREATED",
            "provider_order_id": _ORDER_ID,
        },
        "second_identical_invocation": {
            "resolution": "EXISTING",
            "provider_order_id": _ORDER_ID,
            "retrieval": "PROVIDER-BACKED",
        },
        "same_provider_order": True,
        "provider_contacted": True,
        "provider_observation": "CURRENT-RUN PROVIDER OBSERVATION",
        "scope": "Razorpay Test Mode order creation and existing-order resolution only.",
    }
    assert provider.methods == ("POST", "GET")
    assert set(result) == {
        "presentation_version",
        "result",
        "mode",
        "current_run",
        "authority_verified",
        "governor_state",
        "execution_reserved",
        "execution_plan",
        "first_invocation",
        "second_identical_invocation",
        "same_provider_order",
        "provider_contacted",
        "provider_observation",
        "scope",
    }
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in _ENVIRONMENT.values())
    assert "Authorization" not in serialized


def test_unverified_certificate_makes_zero_provider_calls(
    authority_inputs: _AuthorityInputs,
) -> None:
    certificate = _tampered_certificate(authority_inputs.certificate)
    inputs = _AuthorityInputs(
        certificate=certificate,
        trusted_signing_identities=authority_inputs.trusted_signing_identities,
        execution_request=_execution_request(
            certificate,
            authority_inputs.execution_request.execution_id,
        ),
        decision_time=authority_inputs.decision_time,
    )
    provider = _Provider()

    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=provider,
        authority_inputs=inputs,
    )

    assert result["result"] == "FAILED"
    assert result["code"] == "AUTHORITY_VERIFICATION_FAILURE"
    assert result["authority_verified"] is False
    assert result["execution_reserved"] is False
    assert result["provider_contacted"] is False
    assert provider.calls == []


def test_governor_refusal_makes_zero_provider_calls(
    authority_inputs: _AuthorityInputs,
) -> None:
    request = authority_inputs.execution_request
    closed_market = request.market_execution_authorization.model_copy(
        update={"state": MarketExecutionStateV1.CLOSED}
    )
    inputs = _AuthorityInputs(
        certificate=authority_inputs.certificate,
        trusted_signing_identities=authority_inputs.trusted_signing_identities,
        execution_request=request.model_copy(
            update={"market_execution_authorization": closed_market}
        ),
        decision_time=authority_inputs.decision_time,
    )
    provider = _Provider()

    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=provider,
        authority_inputs=inputs,
    )

    assert result["result"] == "FAILED"
    assert result["code"] == "MONEY_GOVERNOR_REFUSAL"
    assert result["authority_verified"] is True
    assert result["governor_state"] == "CLOSED"
    assert result["execution_reserved"] is False
    assert result["provider_contacted"] is False
    assert provider.calls == []


def test_different_provider_order_ids_fail_closed(
    authority_inputs: _AuthorityInputs,
) -> None:
    provider = _Provider(second_order_id="order_CLEARCurrentRun2")

    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=provider,
        authority_inputs=authority_inputs,
    )

    assert result["result"] == "FAILED"
    assert result["code"] == "PROVIDER_ORDER_MISMATCH"
    assert result["provider_contacted"] is True
    assert provider.methods == ("POST", "GET")
    assert "same_provider_order" not in result


def test_missing_credentials_is_unavailable_and_deterministic_demo_remains_network_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Provider()

    result = build_razorpay_test_order_evidence(environment={}, transport=provider)

    assert result["result"] == "UNAVAILABLE"
    assert result["code"] == "LIVE_TEST_MODE_UNAVAILABLE"
    assert result["provider_contacted"] is False
    assert provider.calls == []

    def reject_network(**_kwargs: object) -> tuple[int, bytes]:
        raise AssertionError("the deterministic demo contacted live Razorpay")

    monkeypatch.setattr(orders_module, "_https_request", reject_network)
    deterministic = build_authority_demo_presentation()
    assert deterministic["current_run"]["razorpay_contacted"] is False
    assert deterministic["allocation"] == {
        "requested_quantity": 5,
        "fulfilled_quantity": 5,
        "winner_count": 2,
        "total_payment_paise": 2700,
        "winner_merchant_ids": [
            "30000000-0001-4000-8000-000000000001",
            "30000000-0002-4000-8000-000000000001",
        ],
        "evidence_class": "REAL LOCAL PRODUCTION LOGIC",
    }


def test_invalid_provider_facts_fail_closed(
    authority_inputs: _AuthorityInputs,
) -> None:
    provider = _Provider(response_override=b"{}")

    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=provider,
        authority_inputs=authority_inputs,
    )

    assert result["result"] == "FAILED"
    assert result["code"] == "INVALID_PROVIDER_RESPONSE"
    assert result["provider_contacted"] is True
    assert provider.methods == ("POST",)
    assert "first_invocation" not in result


@pytest.mark.parametrize(
    ("provider", "expected_code"),
    [
        (_Provider(status=401, response_override=b"{}"), "PROVIDER_AUTHENTICATION_FAILURE"),
        (
            _Provider(failure=TimeoutError("private transport detail")),
            "PROVIDER_TIMEOUT_OR_NETWORK_FAILURE",
        ),
    ],
)
def test_provider_authentication_and_network_failures_are_distinct(
    provider: _Provider,
    expected_code: str,
    authority_inputs: _AuthorityInputs,
) -> None:
    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=provider,
        authority_inputs=authority_inputs,
    )

    assert result["result"] == "FAILED"
    assert result["code"] == expected_code
    assert result["provider_contacted"] is True
    assert "private transport detail" not in json.dumps(result)


def test_browser_live_action_is_opt_in_and_tamper_reveal_remains_zero_fetch() -> None:
    source = Path("ui/app.js").read_text(encoding="utf-8")
    live_function = source.split("async function runLiveEvidence()", maxsplit=1)[1].split(
        '$("#run-demo")', maxsplit=1
    )[0]
    tamper_handler = source.split('$("#reveal-tamper").addEventListener("click",', maxsplit=1)[
        1
    ].split('$("#run-live-evidence")', maxsplit=1)[0]

    assert source.count('fetch("/api/authority-demo"') == 1
    assert source.count('fetch("/api/razorpay-test-order-evidence"') == 1
    assert 'fetch("/api/razorpay-test-order-evidence"' in live_function
    assert "fetch(" not in tamper_handler
    assert '$("#run-live-evidence").addEventListener("click", runLiveEvidence)' in source
    assert "runLiveEvidence();" not in source
    assert 'setText(".live-not-run", liveActionLabels[liveState]);' in source
    assert all(
        label in source
        for label in (
            "NOT RUN · USER INITIATED",
            "RUNNING · USER INITIATED",
            "CURRENT RUN · VALIDATED",
            "CURRENT RUN · NOT VALIDATED",
        )
    )


def test_credentials_are_received_only_by_the_server_side_transport(
    authority_inputs: _AuthorityInputs,
) -> None:
    observed_credentials: list[str] = []
    provider = _Provider()

    def inspect_credentials(**kwargs: Any) -> tuple[int, bytes]:
        credentials = kwargs["credentials"]
        assert type(credentials) is RazorpayTestCredentialsV1
        observed_credentials.append(repr(credentials))
        return provider(**kwargs)

    result = build_razorpay_test_order_evidence(
        environment=_ENVIRONMENT,
        transport=inspect_credentials,
        authority_inputs=authority_inputs,
    )

    assert result["result"] == "SUCCESS"
    assert observed_credentials == [
        "RazorpayTestCredentialsV1(<redacted>)",
        "RazorpayTestCredentialsV1(<redacted>)",
    ]
    assert all(value not in json.dumps(result) for value in _ENVIRONMENT.values())
