"""Narrow, fail-closed DTO for the local CLEAR authority demo.

This module is deliberately a presentation boundary. Authority decisions remain in
``clear_market.demo`` and its production modules; this adapter only selects and
validates facts that the judge-facing page needs to display.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from clear_market.demo import _certificate_fixture, run_demo_v1

REAL_LOCAL = "REAL LOCAL PRODUCTION LOGIC"
FIXTURE = "DETERMINISTIC FIXTURE"
CONTROLLED = "FAKE/CONTROLLED EXTERNAL TRANSPORT"
HISTORICAL = "HISTORICAL LIVE EVIDENCE ONLY"
NOT_DEMONSTRATED = "NOT DEMONSTRATED"

EVIDENCE_CLASSES = frozenset({REAL_LOCAL, FIXTURE, CONTROLLED, HISTORICAL, NOT_DEMONSTRATED})


class PresentationError(RuntimeError):
    """Raised when the production demo cannot provide a safe presentation DTO."""


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PresentationError(f"missing presentation fact: {path}")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise PresentationError(f"invalid presentation fact: {path}")
    return value


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise PresentationError(f"invalid presentation fact: {path}")
    return value


def _boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise PresentationError(f"invalid presentation fact: {path}")
    return value


def _evidence(value: object, path: str) -> str:
    label = _text(value, path)
    if label not in EVIDENCE_CLASSES:
        raise PresentationError(f"unsupported evidence class: {path}")
    return label


def _validate_demo_summary(result: object) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    root = _mapping(result, "demo")
    if _text(root.get("demo_version"), "demo_version") != "clear-demo-v1":
        raise PresentationError("unexpected production demo version")
    if _text(root.get("invariant"), "invariant") != "NO VALID CERTIFICATE = NO MONEY ACTION":
        raise PresentationError("production invariant is unavailable")
    truth = _mapping(root.get("truth_labels"), "truth_labels")
    expected_truth = {
        "buyer_candidate_and_context": FIXTURE,
        "buyer_policy_freeze": REAL_LOCAL,
        "merchant_offer_build_sign_authenticate": REAL_LOCAL,
        "allocation": REAL_LOCAL,
        "certificate_construction": REAL_LOCAL,
        "certificate_verification": REAL_LOCAL,
        "money_governor": REAL_LOCAL,
        "razorpay_provider_transport": CONTROLLED,
        "razorpay_live_test_mode": NOT_DEMONSTRATED,
    }
    for key, expected in expected_truth.items():
        if _evidence(truth.get(key), f"truth_labels.{key}") != expected:
            raise PresentationError(f"production evidence classification changed: {key}")
    valid = _mapping(root.get("valid_path"), "valid_path")
    tamper = _mapping(root.get("tamper_path"), "tamper_path")
    if not _boolean(valid.get("certificate_verified"), "valid_path.certificate_verified"):
        raise PresentationError("valid certificate was not verified")
    if not _boolean(valid.get("execution_reserved"), "valid_path.execution_reserved"):
        raise PresentationError("valid execution reservation is unavailable")
    if _text(valid.get("first_order_resolution"), "valid_path.first_order_resolution") != "CREATED":
        raise PresentationError("valid first provider resolution is unavailable")
    if (
        _text(valid.get("second_order_resolution"), "valid_path.second_order_resolution")
        != "EXISTING"
    ):
        raise PresentationError("valid second provider resolution is unavailable")
    if _integer(valid.get("provider_post_count"), "valid_path.provider_post_count") != 1:
        raise PresentationError("valid provider POST count is not the expected proof")
    if _integer(valid.get("provider_get_count"), "valid_path.provider_get_count") != 1:
        raise PresentationError("valid provider GET count is not the expected proof")
    if _text(valid.get("allocation_status"), "valid_path.allocation_status") != "FEASIBLE":
        raise PresentationError("valid allocation status is unavailable")
    if _text(tamper.get("governor_failure_code"), "tamper_path.governor_failure_code") != (
        "CERTIFICATE_NOT_VERIFIED"
    ):
        raise PresentationError("tamper branch did not fail with the required code")
    if any(
        _integer(tamper.get(key), f"tamper_path.{key}") != 0
        for key in ("provider_post_count", "provider_get_count")
    ):
        raise PresentationError("tamper branch provider counters are not closed")
    return valid, tamper


def build_authority_demo_presentation() -> dict[str, Any]:
    """Run the real demo once and return the only DTO the browser can consume."""

    valid, tamper = _validate_demo_summary(run_demo_v1())

    # The fixture is the same production-backed certificate used by the demo. It is
    # consulted only to expose offer and certificate identity fields absent from the
    # intentionally compact CLI summary; no authority decision is made here.
    policy, signed_offers, certificate = _certificate_fixture()
    market = policy.market_spec
    if (
        _integer(valid.get("requested_quantity"), "valid_path.requested_quantity")
        != market.requested_quantity
    ):
        raise PresentationError("requested quantity disagrees across production facts")
    if _integer(valid.get("fulfilled_quantity"), "valid_path.fulfilled_quantity") != 5:
        raise PresentationError("fulfilled quantity is not available")
    if _integer(valid.get("winner_count"), "valid_path.winner_count") != len(
        certificate.allocation.lines
    ):
        raise PresentationError("winner count disagrees across production facts")
    if _integer(valid.get("total_payment_paise"), "valid_path.total_payment_paise") <= 0:
        raise PresentationError("total payment is not available")
    if _integer(
        valid.get("authenticated_offer_count"), "valid_path.authenticated_offer_count"
    ) != len(signed_offers):
        raise PresentationError("authenticated offer count disagrees across production facts")

    offers: list[dict[str, Any]] = []
    for signed in signed_offers:
        offer = signed.offer
        if len(offer.lines) != 1:
            raise PresentationError("unexpected offer line shape")
        line = offer.lines[0]
        offers.append(
            {
                "offer_id": offer.offer_id,
                "merchant_id": offer.merchant_id,
                "capacity": line.max_offer_quantity,
                "unit_price_paise": line.unit_price.amount_paise,
                "authenticated": True,
                "evidence_class": REAL_LOCAL,
            }
        )

    winner_ids = valid.get("winner_merchant_ids")
    if (
        not isinstance(winner_ids, list)
        or not winner_ids
        or any(not isinstance(item, str) for item in winner_ids)
    ):
        raise PresentationError("winner IDs are not available")
    certificate_winner_ids = [line.merchant_id for line in certificate.allocation.lines]
    if winner_ids != certificate_winner_ids:
        raise PresentationError("winner IDs disagree across production facts")

    return {
        "presentation_version": "clear-authority-presentation-v1",
        "current_run": {
            "evidence_class": REAL_LOCAL,
            "ai_invoked": False,
            "razorpay_contacted": False,
            "ai_statement": "AI is not invoked by this deterministic run.",
            "razorpay_statement": "Live Razorpay was not contacted by this deterministic run.",
            "fixture_context": "Displayed input context is fixture-backed.",
        },
        "intent": {
            "requested_quantity": market.requested_quantity,
            "max_winners": market.max_winners,
            "evidence_class": FIXTURE,
        },
        "policy": {
            "identity": "BuyerPolicyV2",
            "status": "DETERMINISTICALLY FROZEN",
            "evidence_class": REAL_LOCAL,
        },
        "offers": offers,
        "allocation": {
            "requested_quantity": valid["requested_quantity"],
            "fulfilled_quantity": valid["fulfilled_quantity"],
            "winner_count": valid["winner_count"],
            "total_payment_paise": valid["total_payment_paise"],
            "winner_merchant_ids": winner_ids,
            "evidence_class": REAL_LOCAL,
        },
        "certificate": {
            "identity": "AllocationCertificateV2",
            "version": certificate.certificate_version,
            "certificate_id": certificate.certificate_id,
            "state": "PRODUCED",
            "evidence_class": REAL_LOCAL,
        },
        "verification": {
            "identity": "AllocationCertificateV2 verifier",
            "verified": valid["certificate_verified"],
            "state": "VERIFIED",
            "copy": "Independently replayed and verified.",
        },
        "governor": {
            "identity": "Money Governor",
            "state": "EXECUTION RESERVED",
            "execution_plan_identity": "ExecutionPlanV1",
            "execution_plan_state": "PRODUCED",
            "without_verified_proof": "CLOSED",
        },
        "valid_provider_branch": {
            "evidence_class": CONTROLLED,
            "controlled_order_id": valid["provider_order_id"],
            "first_invocation": {
                "resolution": valid["first_order_resolution"],
                "post_count": 1,
                "get_count": 0,
            },
            "second_invocation": {
                "resolution": valid["second_order_resolution"],
                "post_count": 0,
                "get_count": 1,
            },
            "cumulative_after_second": {
                "post_count": valid["provider_post_count"],
                "get_count": valid["provider_get_count"],
            },
        },
        "tamper_branch": {
            "evidence_class": REAL_LOCAL,
            "altered_claim": "Semantically altered AllocationCertificateV2 claim.",
            "verification_state": "CERTIFICATE NOT VERIFIED",
            "failure_code": tamper["governor_failure_code"],
            "governor_state": "CLOSED",
            "execution_reservation": "NONE" if not tamper["execution_reserved"] else "PRESENT",
            "idempotency_record": (
                "NONE" if not tamper["order_idempotency_record_present"] else "PRESENT"
            ),
            "provider_counters": {
                "post_count": tamper["provider_post_count"],
                "get_count": tamper["provider_get_count"],
            },
        },
    }


def build_presentation() -> dict[str, Any]:
    """Compatibility name for callers that treat the boundary as a builder."""

    return build_authority_demo_presentation()


def build_demo_presentation_v1() -> dict[str, Any]:
    """Legacy entrypoint retained for small local callers of the old UI module."""

    return build_authority_demo_presentation()
