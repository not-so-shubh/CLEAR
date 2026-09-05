from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "ui" / "product_app.js").read_text(encoding="utf-8")


def test_official_checkout_script_and_safe_controls_are_present() -> None:
    assert 'src="https://checkout.razorpay.com/v1/checkout.js"' in HTML
    assert 'id="open-runtime-razorpay-checkout"' in HTML
    assert 'id="refresh-runtime-payment-state"' in HTML
    assert re.search(
        r'id="open-runtime-razorpay-checkout"[^>]*\bhidden\b[^>]*\bdisabled\b',
        HTML,
    )
    assert re.search(
        r'id="refresh-runtime-payment-state"[^>]*\bhidden\b[^>]*\bdisabled\b',
        HTML,
    )
    for secret_name in ("RAZORPAY_TEST_KEY_SECRET", "RAZORPAY_TEST_WEBHOOK_SECRET"):
        assert secret_name not in HTML
        assert secret_name not in SCRIPT


def test_checkout_facts_are_validated_against_server_order_and_execution() -> None:
    assert 'checkout.key_id.startsWith("rzp_test_")' in SCRIPT
    assert "checkout.provider_order_id !== payload.provider_order_id" in SCRIPT
    assert "checkout.amount_paise !== payload.order_amount_paise" in SCRIPT
    assert "checkout.amount_paise !== orderAmount" in SCRIPT
    assert 'checkout.currency !== "INR"' in SCRIPT
    assert "checkout.execution_id !== executionId" in SCRIPT
    assert "checkout.execution_id !== payload.execution_id" in SCRIPT
    assert "currentRuntimeCheckout = checkout" in SCRIPT
    assert "The server Checkout metadata failed closed." in SCRIPT


def test_checkout_options_are_safe_and_handler_only_starts_server_replay() -> None:
    checkout_block = SCRIPT.split(
        'runtimeRazorpayCheckoutButton.addEventListener("click"',
        1,
    )[1].split(
        "if (runtimePaymentRefreshButton instanceof HTMLButtonElement)",
        1,
    )[0]
    assert 'typeof window.Razorpay !== "function"' in checkout_block
    assert "key: checkout.key_id" in checkout_block
    assert "amount: checkout.amount_paise" in checkout_block
    assert "currency: checkout.currency" in checkout_block
    assert "order_id: checkout.provider_order_id" in checkout_block
    assert 'name: "CLEAR"' in checkout_block
    assert 'description: "Governor-authorized Test Mode payment"' in checkout_block
    assert "handler: () =>" in checkout_block
    assert "startRuntimePaymentPolling" in checkout_block
    assert "razorpay_payment_id" not in checkout_block
    assert "razorpay_signature" not in checkout_block
    assert "/api/product-v1/razorpay/webhook" not in SCRIPT
    assert "/authority/razorpay-payment-state" in SCRIPT


def test_payment_replay_is_bounded_and_proof_requires_server_state() -> None:
    assert "const PAYMENT_POLL_INTERVAL_MS = 1500;" in SCRIPT
    assert "const PAYMENT_POLL_MAX_ATTEMPTS = 24;" in SCRIPT
    assert "const PAYMENT_POLL_WINDOW_MS = 36000;" in SCRIPT
    assert "for (let attempt = 0; attempt < PAYMENT_POLL_MAX_ATTEMPTS; attempt += 1)" in SCRIPT
    assert 'outcome.paymentState === "PAYMENT_CAPTURED"' in SCRIPT
    assert '"PAYMENT_FAILED_OBSERVED"' in SCRIPT
    assert 'payload?.result !== "SUCCESS"' in SCRIPT
    assert 'payload.payment_state === "PAYMENT_CAPTURED"' in SCRIPT
    assert "authenticated webhook and deterministic replay" in SCRIPT
    assert "payment-state" in SCRIPT


def test_failed_observation_is_nonterminal_but_capture_stops_polling() -> None:
    polling_block = SCRIPT.split("const startRuntimePaymentPolling", 1)[1].split(
        "const resetRuntimeTamper",
        1,
    )[0]
    assert 'if (outcome.paymentState === "PAYMENT_CAPTURED") return;' in polling_block
    assert 'outcome.paymentState === "PAYMENT_FAILED_OBSERVED"' not in polling_block
    assert (
        "PAYMENT_FAILED_OBSERVED"
        in SCRIPT.split(
            "const renderRuntimePaymentState",
            1,
        )[1].split("const refreshRuntimePaymentState", 1)[0]
    )


def test_poll_cancellation_resolves_delay_and_aborts_in_flight_get() -> None:
    cancellation_block = SCRIPT.split("const cancelRuntimePaymentPolling", 1)[1].split(
        "const clearRuntimeCheckoutMetadata",
        1,
    )[0]
    assert "runtimePaymentPollDelayResolve" in cancellation_block
    assert "resolveDelay({ cancelled: true })" in cancellation_block
    assert "runtimePaymentPollController.abort()" in cancellation_block
    assert "runtimePaymentPollController = null" in cancellation_block
    assert "if (delayOutcome?.cancelled) return;" in SCRIPT


def test_poll_deadline_aborts_operation_and_passes_signal_to_get() -> None:
    polling_block = SCRIPT.split("const startRuntimePaymentPolling", 1)[1].split(
        "const resetRuntimeTamper",
        1,
    )[0]
    assert "runtimePaymentPollDeadlineTimer = window.setTimeout" in polling_block
    assert "PAYMENT_POLL_WINDOW_MS" in polling_block
    assert "pollController.abort()" in polling_block
    assert "pollController.signal" in polling_block
    assert "runtimePaymentPollDeadlineTimer" in polling_block


def test_current_replay_failures_clear_payment_proof_but_stale_responses_do_not() -> None:
    refresh_block = SCRIPT.split("const refreshRuntimePaymentState", 1)[1].split(
        "const startRuntimePaymentPolling",
        1,
    )[0]
    stale_guard = refresh_block.index("return { stale: true };")
    first_clear = refresh_block.index("clearRuntimePaymentProof();")
    assert stale_guard < first_clear
    assert refresh_block.count("clearRuntimePaymentProof();") >= 2
    assert (
        'runtimeRazorpayStatus.textContent = "Payment state replay failed closed.";'
        in refresh_block
    )


def test_manual_refresh_is_get_only_and_checkout_handler_never_confirms_capture() -> None:
    refresh_block = SCRIPT.split(
        'runtimePaymentRefreshButton.addEventListener("click"',
        1,
    )[1].split("const renderInterpretationFailure", 1)[0]
    assert 'method: "POST"' not in refresh_block
    assert "/authority/razorpay-payment-state" in SCRIPT
    checkout_block = SCRIPT.split(
        "handler: () =>",
        1,
    )[1].split("modal:", 1)[0]
    assert "startRuntimePaymentPolling" in checkout_block
    assert "PAYMENT_CAPTURED" not in checkout_block
    assert "payment_state" not in checkout_block


def test_payment_state_reset_and_static_claims_remain_fail_closed() -> None:
    reset_block = SCRIPT.split("const resetRuntimeRazorpay = () =>", 1)[1].split(
        "const clearRuntimeAuthorityPresentation",
        1,
    )[0]
    assert "++razorpayRequestGeneration" in reset_block
    assert "clearRuntimeCheckoutMetadata()" in reset_block
    assert "cancelRuntimePaymentPolling" in SCRIPT
    assert "runtimePaymentPollController.abort()" in SCRIPT
    assert "runtimePaymentPollDelayResolve" in SCRIPT
    assert "runtimePaymentProof.hidden = true" in SCRIPT
    assert "Checkout was dismissed. No captured payment has been confirmed." in SCRIPT
    assert "settlement" in HTML
    assert "supplier payout/transfers" in HTML
    assert "physical fulfillment" in HTML
    assert "real-money movement" in HTML
    assert "Authenticated Test Mode payment-state replay" in HTML
    assert "PAYMENT_CAPTURED appears only after CLEAR receives an authenticated webhook" in HTML
