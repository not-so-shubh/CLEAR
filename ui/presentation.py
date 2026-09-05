"""Allowlisted presentation data built from the frozen CLEAR demo entrypoint."""

from collections.abc import Mapping
from typing import Final, cast

from clear_market.demo import run_demo_v1

_EXPECTED_DEMO_VERSION: Final[str] = "clear-demo-v1"
_INVARIANT: Final[str] = "NO VALID CERTIFICATE = NO MONEY ACTION"
_EVIDENCE_LABELS: Final[tuple[str, ...]] = (
    "REAL LOCAL PRODUCTION LOGIC",
    "DETERMINISTIC FIXTURE",
    "FAKE/CONTROLLED EXTERNAL TRANSPORT",
    "HISTORICAL LIVE EVIDENCE ONLY",
    "NOT DEMONSTRATED",
)
_STALE_LIMITATION: Final[str] = "remaining hostile/full-system audit"
_DISPLAY_MERCHANTS: Final[tuple[tuple[str, int, int], ...]] = (
    ("Merchant A", 3, 500),
    ("Merchant B", 3, 600),
)
_OUTPUT_EVIDENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "candidate_and_context_evidence",
        "computed_evidence",
        "construction_evidence",
        "evidence",
        "governor_evidence",
        "label",
        "offer_evidence",
        "policy_freeze_evidence",
        "provider_boundary",
        "requested_quantity_evidence",
        "resolution_evidence",
        "verification_evidence",
    }
)
_CURRENT_LIMITATIONS: Final[tuple[str, ...]] = (
    "live Razorpay Test Mode execution",
    "payment capture",
    "transfer creation/settlement in this demo",
    "settlement",
    "refunds/reversals",
    "physical fulfillment",
    "transcript completeness",
    "exactly-once external delivery",
    "server-attested decision time",
    "live merchant AI",
    "live certificate explanation AI",
)
_HISTORICAL_RAZORPAY_CLAIM: Final[str] = (
    "CLEAR\u2019s Governor-gated Razorpay order path was exercised against real Razorpay "
    "Test Mode: order creation succeeded and a second identical call resolved the "
    "existing provider order through provider-backed retrieval."
)


def _mapping_value(source: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = source.get(key)
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"demo field {key!r} is not a string-keyed object")
    return cast(dict[str, object], value)


def _typed_value[T](source: Mapping[str, object], key: str, expected_type: type[T]) -> T:
    value = source.get(key)
    if expected_type is int:
        valid = isinstance(value, int) and not isinstance(value, bool)
    else:
        valid = isinstance(value, expected_type)
    if not valid:
        raise RuntimeError(f"demo field {key!r} has an unexpected type")
    return cast(T, value)


def _exact_value[T](source: Mapping[str, object], key: str, expected: T) -> T:
    value = source.get(key)
    if type(value) is not type(expected) or value != expected:
        raise RuntimeError(f"demo field {key!r} contradicts presentation metadata")
    return value


def _string_list(source: Mapping[str, object], key: str) -> list[str]:
    value = source.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"demo field {key!r} is not a string list")
    return list(value)


def _truth_label(truth_labels: Mapping[str, object], key: str, expected: str) -> str:
    return _exact_value(truth_labels, key, expected)


def _validate_fixture_consistency(valid: Mapping[str, object]) -> list[str]:
    requested = _typed_value(valid, "requested_quantity", int)
    fulfilled = _typed_value(valid, "fulfilled_quantity", int)
    winner_count = _typed_value(valid, "winner_count", int)
    authenticated_offer_count = _typed_value(valid, "authenticated_offer_count", int)
    total_payment = _typed_value(valid, "total_payment_paise", int)
    winner_ids = _string_list(valid, "winner_merchant_ids")

    total_capacity = sum(capacity for _, capacity, _ in _DISPLAY_MERCHANTS)
    unit_prices = tuple(unit_price for _, _, unit_price in _DISPLAY_MERCHANTS)
    max_winners = 2
    if (
        requested != 5
        or fulfilled != requested
        or fulfilled > total_capacity
        or winner_count != max_winners
        or authenticated_offer_count != len(_DISPLAY_MERCHANTS)
        or len(winner_ids) != winner_count
        or len(set(winner_ids)) != winner_count
        or not min(unit_prices) * fulfilled <= total_payment <= max(unit_prices) * fulfilled
    ):
        raise RuntimeError("demo output contradicts display-only fixture metadata")
    return winner_ids


def _validate_output_evidence(value: object, field_name: str | None = None) -> None:
    if field_name == "evidence_labels":
        if value != list(_EVIDENCE_LABELS):
            raise RuntimeError("presentation evidence label list is invalid")
        return
    if field_name in _OUTPUT_EVIDENCE_FIELDS:
        if not isinstance(value, str) or value not in _EVIDENCE_LABELS:
            raise RuntimeError("presentation contains an unknown evidence class")
        return
    if isinstance(value, dict):
        for child_name, child_value in value.items():
            _validate_output_evidence(child_value, child_name)
    elif isinstance(value, list):
        for child_value in value:
            _validate_output_evidence(child_value)


def build_demo_presentation_v1() -> dict[str, object]:
    """Run the authority demo once and return a validated presentation allowlist."""

    raw = run_demo_v1()
    demo_version = _exact_value(raw, "demo_version", _EXPECTED_DEMO_VERSION)
    invariant = _exact_value(raw, "invariant", _INVARIANT)

    truth = _mapping_value(raw, "truth_labels")
    valid = _mapping_value(raw, "valid_path")
    tamper = _mapping_value(raw, "tamper_path")
    raw_limitations = _mapping_value(raw, "limitations")

    if any(value not in _EVIDENCE_LABELS for value in truth.values()):
        raise RuntimeError("demo contains an unknown evidence label")

    fixture_label = _truth_label(truth, "buyer_candidate_and_context", "DETERMINISTIC FIXTURE")
    policy_label = _truth_label(truth, "buyer_policy_freeze", "REAL LOCAL PRODUCTION LOGIC")
    supply_fixture_label = _truth_label(
        truth,
        "merchant_catalog_inventory_policy_candidates",
        "DETERMINISTIC FIXTURE",
    )
    offer_label = _truth_label(
        truth, "merchant_offer_build_sign_authenticate", "REAL LOCAL PRODUCTION LOGIC"
    )
    allocation_label = _truth_label(truth, "allocation", "REAL LOCAL PRODUCTION LOGIC")
    construction_label = _truth_label(
        truth, "certificate_construction", "REAL LOCAL PRODUCTION LOGIC"
    )
    verification_label = _truth_label(
        truth, "certificate_verification", "REAL LOCAL PRODUCTION LOGIC"
    )
    governor_label = _truth_label(truth, "money_governor", "REAL LOCAL PRODUCTION LOGIC")
    adapter_label = _truth_label(truth, "razorpay_order_adapter", "REAL LOCAL PRODUCTION LOGIC")
    transport_label = _truth_label(
        truth,
        "razorpay_provider_transport",
        "FAKE/CONTROLLED EXTERNAL TRANSPORT",
    )
    _truth_label(truth, "razorpay_live_test_mode", "NOT DEMONSTRATED")

    buyer_policy_frozen = _exact_value(valid, "buyer_policy_frozen", True)
    allocation_status = _exact_value(valid, "allocation_status", "FEASIBLE")
    certificate_verified = _exact_value(valid, "certificate_verified", True)
    execution_reserved = _exact_value(valid, "execution_reserved", True)
    first_order_resolution = _exact_value(valid, "first_order_resolution", "CREATED")
    second_order_resolution = _exact_value(valid, "second_order_resolution", "EXISTING")
    provider_post_count = _exact_value(valid, "provider_post_count", 1)
    provider_get_count = _exact_value(valid, "provider_get_count", 1)
    winner_ids = _validate_fixture_consistency(valid)

    certificate_digest = _typed_value(valid, "certificate_digest_sha256", str)
    if len(certificate_digest) != 64 or any(
        character not in "0123456789abcdef" for character in certificate_digest
    ):
        raise RuntimeError("demo certificate digest is not lowercase SHA-256")

    tamper_verification_expected = _exact_value(tamper, "certificate_verification_expected", False)
    tamper_failure_code = _exact_value(tamper, "governor_failure_code", "CERTIFICATE_NOT_VERIFIED")
    tamper_execution_reserved = _exact_value(tamper, "execution_reserved", False)
    tamper_idempotency_present = _exact_value(tamper, "order_idempotency_record_present", False)
    tamper_post_count = _exact_value(tamper, "provider_post_count", 0)
    tamper_get_count = _exact_value(tamper, "provider_get_count", 0)

    _exact_value(
        raw_limitations,
        _STALE_LIMITATION,
        "NOT DEMONSTRATED / STILL REQUIRED",
    )
    limitations = []
    for claim in _CURRENT_LIMITATIONS:
        limitation_evidence = _exact_value(raw_limitations, claim, "NOT DEMONSTRATED")
        limitations.append({"claim": claim, "evidence": limitation_evidence})

    merchants = [
        {
            "display_name": display_name,
            "capacity": capacity,
            "unit_price_paise": unit_price,
            "evidence": supply_fixture_label,
        }
        for display_name, capacity, unit_price in _DISPLAY_MERCHANTS
    ]

    presentation: dict[str, object] = {
        "demo_version": demo_version,
        "invariant": invariant,
        "evidence_labels": list(_EVIDENCE_LABELS),
        "fixture_context": {
            "evidence": fixture_label,
            "requested_quantity": 5,
            "max_winners": 2,
            "merchants": merchants,
            "authority_boundary": (
                "Display-only context. These values are never passed into the authority demo."
            ),
        },
        "valid_path": {
            "intent": {
                "advisory_boundary": (
                    "AI is not invoked by this deterministic run. The displayed input "
                    "context is fixture-backed. AI output can never authorize money."
                ),
                "candidate_and_context_evidence": fixture_label,
                "policy_type": "BuyerPolicyV2",
                "buyer_policy_frozen": buyer_policy_frozen,
                "policy_freeze_evidence": policy_label,
            },
            "authenticated_supply": {
                "authenticated_offer_count": _typed_value(valid, "authenticated_offer_count", int),
                "offer_evidence": offer_label,
            },
            "deterministic_clearing": {
                "allocation_status": allocation_status,
                "requested_quantity": _typed_value(valid, "requested_quantity", int),
                "requested_quantity_evidence": fixture_label,
                "fulfilled_quantity": _typed_value(valid, "fulfilled_quantity", int),
                "winner_count": _typed_value(valid, "winner_count", int),
                "winner_merchant_ids": winner_ids,
                "total_payment_paise": _typed_value(valid, "total_payment_paise", int),
                "computed_evidence": allocation_label,
            },
            "proof": {
                "certificate_type": "AllocationCertificateV2",
                "certificate_digest_sha256": certificate_digest,
                "certificate_verified": certificate_verified,
                "construction_evidence": construction_label,
                "verification_evidence": verification_label,
            },
            "money_authority": {
                "authority": "Money Governor",
                "execution_reserved": execution_reserved,
                "evidence": governor_label,
            },
            "controlled_provider_path": {
                "orders": [
                    {
                        "resolution": first_order_resolution,
                        "resolution_evidence": adapter_label,
                        "provider_boundary": transport_label,
                        "copy": ("First controlled order attempt resolved as CREATED locally."),
                    },
                    {
                        "resolution": second_order_resolution,
                        "resolution_evidence": adapter_label,
                        "provider_boundary": transport_label,
                        "copy": (
                            "Second identical call resolved EXISTING through controlled retrieval."
                        ),
                    },
                ],
                "counter_label": "CONTROLLED TRANSPORT COUNTERS",
                "provider_post_count": provider_post_count,
                "provider_get_count": provider_get_count,
            },
        },
        "tamper_path": {
            "altered_claim": "ALTERED CLAIM",
            "verifier": "INDEPENDENT VERIFIER",
            "certificate_verification_expected": tamper_verification_expected,
            "governor_failure_code": tamper_failure_code,
            "execution_reserved": tamper_execution_reserved,
            "governor_state": "MONEY GOVERNOR CLOSED",
            "provider_state": "PROVIDER NOT CALLED",
            "order_idempotency_record_present": tamper_idempotency_present,
            "provider_post_count": tamper_post_count,
            "provider_get_count": tamper_get_count,
            "verification_evidence": verification_label,
            "governor_evidence": governor_label,
            "provider_boundary": transport_label,
            "outcome": "NO MONEY ACTION",
        },
        "limitations": limitations,
        "historical_evidence": {
            "label": "HISTORICAL LIVE EVIDENCE ONLY",
            "claim": _HISTORICAL_RAZORPAY_CLAIM,
            "current_run_notice": "The current authority demo does not contact Razorpay.",
        },
    }
    _validate_output_evidence(presentation)
    return presentation
