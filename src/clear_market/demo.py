"""Deterministic judge-facing composition of CLEAR production authority paths."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Literal, cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.ai import (
    BuyerIntentCandidateV1,
    BuyerPolicyFreezeContextV1,
    freeze_buyer_policy_v2,
)
from clear_market.certificate.v2 import (
    ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    AllocationCertificateV2,
    AllocationClaimV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
    allocation_certificate_v2_digest,
    build_allocation_certificate_v2,
)
from clear_market.commerce import (
    BuyerPolicyV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
    MerchantEconomicPolicyV2,
    MerchantOfferCandidateLineV2,
    MerchantOfferCandidateV2,
    MerchantSigningIdentityV2,
    MerchantSkuEconomicRuleV2,
    ProvenanceLabel,
    SignedMerchantOfferV2,
    build_and_sign_merchant_offer_v2,
    canonical_signed_merchant_offer_v2_bytes,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.domain import Money
from clear_market.execution import (
    BuyerFinancialAuthorizationV1,
    ExecutionAuthorizationRequestV1,
    MarketExecutionAuthorizationV1,
    MarketExecutionStateV1,
    MerchantRecipientAuthorizationV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
)
from clear_market.mechanism.v2 import AllocationStatusV2, allocate_market_v2
from clear_market.payments.razorpay import (
    RazorpayOrderResolutionV1,
    RazorpayTestCredentialsV1,
    create_razorpay_test_order_v1,
)
from clear_market.persistence import open_sqlite_financial_ledger_v1
from clear_market.verification.v2 import verify_allocation_certificate_v2

_DEMO_VERSION: Final[str] = "clear-demo-v1"
_INVARIANT: Final[str] = "NO VALID CERTIFICATE = NO MONEY ACTION"
_SOURCE_TIME: Final[datetime] = datetime(2027, 1, 1, 11, 0, tzinfo=UTC)
_OFFER_DEADLINE: Final[datetime] = datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
_DECISION_TIME: Final[datetime] = datetime(2027, 1, 1, 13, 0, tzinfo=UTC)
_MARKET_ID: Final[str] = "10000000-0001-4000-8000-000000000001"
_BUYER_ID: Final[str] = "20000000-0001-4000-8000-000000000001"
_MERCHANT_IDS: Final[tuple[str, str]] = (
    "30000000-0001-4000-8000-000000000001",
    "30000000-0002-4000-8000-000000000001",
)
_VALID_EXECUTION_ID: Final[str] = "a1000000-0001-4000-8000-000000000001"
_TAMPER_EXECUTION_ID: Final[str] = "a1000000-0002-4000-8000-000000000001"
_CERTIFICATE_ID: Final[str] = "a2000000-0001-4000-8000-000000000001"
_TAMPER_CERTIFICATE_ID: Final[str] = "a2000000-0002-4000-8000-000000000001"
_PROVIDER_ORDER_ID: Final[str] = "order_CLEARDemoV1"
_ORDER_IDEMPOTENCY_NAMESPACE: Final[str] = "razorpay.order.create.v1"
_CERTIFICATE_DIGEST_VERSION: Final[Literal["sha256-allocation-certificate-v2-clear-json-v1"]] = (
    cast(
        Literal["sha256-allocation-certificate-v2-clear-json-v1"],
        ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    )
)
_KEY_ID: Final[str] = "rzp_test_demo_key"
_KEY_SECRET: Final[str] = "demo-secret"
_PRIVATE_KEY_BYTES: Final[tuple[bytes, bytes]] = (
    bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
    bytes.fromhex("202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f"),
)


def _uuid(prefix: str, index: int) -> str:
    return f"{prefix}-{index:04x}-4000-8000-000000000001"


def _buyer_policy() -> BuyerPolicyV2:
    context = BuyerPolicyFreezeContextV1(
        market_id=_MARKET_ID,
        buyer_id=_BUYER_ID,
        eligible_merchant_ids=_MERCHANT_IDS,
        offer_deadline=_OFFER_DEADLINE,
        mechanism_version="heterogeneous-pay-as-bid-v2",
        objective_version="quantity-cost-soft-objective-v2",
    )
    candidate = BuyerIntentCandidateV1(
        requested_quantity=5,
        minimum_acceptable_quantity=5,
        max_winners=2,
        max_total_payment_paise=5_000,
        hard_constraints=(),
        soft_preferences=(),
    )
    return freeze_buyer_policy_v2(context=context, candidate=candidate)


def _private_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_PRIVATE_KEY_BYTES[index - 1])


def _identity(index: int) -> MerchantSigningIdentityV2:
    public_key = (
        _private_key(index)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return MerchantSigningIdentityV2(
        merchant_id=_MERCHANT_IDS[index - 1],
        ed25519_public_key_hex=public_key.hex(),
    )


def _merchant_source(
    index: int,
) -> tuple[
    MerchantCatalogV2,
    InventorySnapshotV2,
    MerchantEconomicPolicyV2,
    MerchantOfferCandidateV2,
]:
    merchant_id = _MERCHANT_IDS[index - 1]
    catalog_id = _uuid("40000000", index)
    product_id = _uuid("50000000", index)
    sku_id = _uuid("60000000", index)
    snapshot_id = _uuid("70000000", index)
    evidence_id = _uuid("80000000", index)
    price = 500 if index == 1 else 600
    catalog = MerchantCatalogV2(
        catalog_id=catalog_id,
        merchant_id=merchant_id,
        generated_at=_SOURCE_TIME,
        products=(
            CatalogProductV2(
                product_id=product_id,
                display_name=f"Demo product {index}",
                description="Deterministic local demo fixture",
            ),
        ),
        skus=(
            CatalogSkuV2(
                sku_id=sku_id,
                product_id=product_id,
                merchant_sku=f"DEMO-{index}",
                display_name=f"Demo SKU {index}",
                attributes=(),
            ),
        ),
    )
    inventory = InventorySnapshotV2(
        snapshot_id=snapshot_id,
        catalog_id=catalog_id,
        merchant_id=merchant_id,
        captured_at=_SOURCE_TIME,
        lines=(
            InventoryLineV2(
                sku_id=sku_id,
                quantity_available=3,
                provenance=ProvenanceLabel.ATTESTED,
                evidence_reference_id=evidence_id,
            ),
        ),
    )
    economic_policy = MerchantEconomicPolicyV2(
        economic_policy_id=_uuid("90000000", index),
        merchant_id=merchant_id,
        catalog_id=catalog_id,
        sku_rules=(
            MerchantSkuEconomicRuleV2(
                sku_id=sku_id,
                unit_cost_basis=Money(amount_paise=price - 100),
                minimum_margin=Money(amount_paise=100),
                max_quantity_per_offer=3,
            ),
        ),
    )
    candidate = MerchantOfferCandidateV2(
        lines=(
            MerchantOfferCandidateLineV2(
                sku_id=sku_id,
                proposed_quantity=3,
                proposed_unit_price=Money(amount_paise=price),
            ),
        ),
    )
    return catalog, inventory, economic_policy, candidate


def _offers_and_evidence(
    policy: BuyerPolicyV2,
) -> tuple[tuple[SignedMerchantOfferV2, ...], tuple[MerchantOfferEvidenceV2, ...]]:
    signed_offers: list[SignedMerchantOfferV2] = []
    evidence: list[MerchantOfferEvidenceV2] = []
    for index in (1, 2):
        catalog, inventory, economic_policy, candidate = _merchant_source(index)
        identity = _identity(index)
        signed = build_and_sign_merchant_offer_v2(
            offer_id=_uuid("a3000000", index),
            buyer_policy=policy,
            catalog=catalog,
            inventory=inventory,
            economic_policy=economic_policy,
            candidate=candidate,
            signing_identity=identity,
            private_key=_private_key(index),
        )
        authenticated = verify_canonical_signed_merchant_offer_v2(
            data=canonical_signed_merchant_offer_v2_bytes(signed),
            signing_identity=identity,
            buyer_policy=policy,
            catalog=catalog,
            inventory=inventory,
        )
        signed_offers.append(authenticated)
        evidence.append(
            MerchantOfferEvidenceV2(
                received_at=_SOURCE_TIME + timedelta(minutes=1, seconds=index),
                admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
                signing_identity=identity,
                catalog=catalog,
                inventory=inventory,
                signed_offer=authenticated,
            )
        )
    return tuple(signed_offers), tuple(evidence)


def _assert_fixture_chronology(
    policy: BuyerPolicyV2,
    evidence: tuple[MerchantOfferEvidenceV2, ...],
) -> None:
    source_times = tuple(
        timestamp
        for item in evidence
        for timestamp in (item.catalog.generated_at, item.inventory.captured_at)
    )
    receipt_times = tuple(item.received_at for item in evidence)
    if (
        not source_times
        or not receipt_times
        or any(source > receipt for source in source_times for receipt in receipt_times)
        or any(received > policy.offer_deadline for received in receipt_times)
        or not policy.offer_deadline < _DECISION_TIME
    ):
        raise RuntimeError("deterministic demo fixture chronology is incoherent")


def _certificate_fixture() -> tuple[
    BuyerPolicyV2,
    tuple[SignedMerchantOfferV2, ...],
    AllocationCertificateV2,
]:
    policy = _buyer_policy()
    signed_offers, evidence = _offers_and_evidence(policy)
    _assert_fixture_chronology(policy, evidence)
    allocation = allocate_market_v2(
        buyer_policy=policy,
        signed_offers=signed_offers,
    )
    if (
        allocation.status is not AllocationStatusV2.FEASIBLE
        or allocation.fulfilled_quantity != policy.market_spec.requested_quantity
        or allocation.winner_count != 2
    ):
        raise RuntimeError(
            "deterministic demo fixture did not produce the required split allocation"
        )
    certificate = build_allocation_certificate_v2(
        certificate_id=_CERTIFICATE_ID,
        buyer_policy=policy,
        merchant_offer_evidence=evidence,
        allocation=allocation,
    )
    verification = verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=(_identity(1), _identity(2)),
    )
    if not verification.verified:
        raise RuntimeError("deterministic demo certificate did not verify")
    return policy, tuple(signed_offers), certificate


def _execution_request(
    certificate: AllocationCertificateV2, execution_id: str
) -> ExecutionAuthorizationRequestV1:
    digest = allocation_certificate_v2_digest(certificate)
    market_id = certificate.buyer_policy.market_spec.market_id
    market_authorization = MarketExecutionAuthorizationV1(
        authorization_id=_uuid("b1000000", 1 if execution_id == _VALID_EXECUTION_ID else 2),
        market_id=market_id,
        certificate_digest_version=_CERTIFICATE_DIGEST_VERSION,
        certificate_digest_sha256=digest,
        state=MarketExecutionStateV1.EXECUTABLE,
        valid_from=_DECISION_TIME - timedelta(hours=1),
        valid_until=_DECISION_TIME + timedelta(hours=1),
    )
    buyer_authorization = BuyerFinancialAuthorizationV1(
        authorization_id=_uuid("b2000000", 1 if execution_id == _VALID_EXECUTION_ID else 2),
        buyer_id=certificate.buyer_policy.market_spec.buyer_id,
        market_id=market_id,
        certificate_digest_version=_CERTIFICATE_DIGEST_VERSION,
        certificate_digest_sha256=digest,
        maximum_total_payment=Money(amount_paise=5_000),
        valid_from=_DECISION_TIME - timedelta(hours=1),
        valid_until=_DECISION_TIME + timedelta(hours=1),
    )
    recipients = tuple(
        MerchantRecipientAuthorizationV1(
            authorization_id=_uuid(
                "b3000000", index + (0 if execution_id == _VALID_EXECUTION_ID else 2)
            ),
            merchant_id=line.merchant_id,
            recipient_id=f"clear.demo.recipient.m{index}",
            market_id=market_id,
            certificate_digest_version=_CERTIFICATE_DIGEST_VERSION,
            certificate_digest_sha256=digest,
            maximum_transfer=Money(amount_paise=5_000),
            valid_from=_DECISION_TIME - timedelta(hours=1),
            valid_until=_DECISION_TIME + timedelta(hours=1),
        )
        for index, line in enumerate(certificate.allocation.lines, start=1)
    )
    return ExecutionAuthorizationRequestV1(
        execution_id=execution_id,
        certificate_digest_version=_CERTIFICATE_DIGEST_VERSION,
        certificate_digest_sha256=digest,
        market_id=market_id,
        market_execution_authorization=market_authorization,
        buyer_financial_authorization=buyer_authorization,
        merchant_recipient_authorizations=recipients,
    )


class _ControlledOrderTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []

    @property
    def post_count(self) -> int:
        return sum(method == "POST" for method, _path, _body in self.calls)

    @property
    def get_count(self) -> int:
        return sum(method == "GET" for method, _path, _body in self.calls)

    def __call__(
        self,
        *,
        method: str,
        path: str,
        credentials: RazorpayTestCredentialsV1,
        body: bytes | None,
    ) -> tuple[int, bytes]:
        del credentials
        self.calls.append((method, path, body))
        if method == "POST" and path == "/v1/orders" and body is not None:
            return 200, _provider_order_body()
        if method == "GET" and path == f"/v1/orders/{_PROVIDER_ORDER_ID}" and body is None:
            return 200, _provider_order_body()
        raise RuntimeError("unexpected controlled provider request")


def _provider_order_body() -> bytes:
    return json.dumps(
        {
            "amount": 2700,
            "amount_due": 2700,
            "amount_paid": 0,
            "attempts": 0,
            "currency": "INR",
            "entity": "order",
            "id": _PROVIDER_ORDER_ID,
            "partial_payment": False,
            "receipt": _VALID_EXECUTION_ID,
            "status": "created",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _tampered_certificate(certificate: AllocationCertificateV2) -> AllocationCertificateV2:
    claim_values = {
        name: getattr(certificate.allocation, name) for name in AllocationClaimV2.model_fields
    }
    claim_values["soft_preference_unit_score"] = (
        certificate.allocation.soft_preference_unit_score + 1
    )
    tampered_claim = AllocationClaimV2(**claim_values)
    return AllocationCertificateV2(
        certificate_id=_TAMPER_CERTIFICATE_ID,
        buyer_policy=certificate.buyer_policy,
        buyer_policy_commitment_sha256=certificate.buyer_policy_commitment_sha256,
        merchant_offer_evidence=certificate.merchant_offer_evidence,
        allocation=tampered_claim,
    )


def _valid_path() -> dict[str, object]:
    policy, _signed_offers, certificate = _certificate_fixture()
    trusted = (_identity(1), _identity(2))
    credentials = RazorpayTestCredentialsV1(key_id=_KEY_ID, key_secret=_KEY_SECRET)
    transport = _ControlledOrderTransport()
    with TemporaryDirectory() as temporary_directory:
        ledger_path = Path(temporary_directory) / "ledger.db"
        with open_sqlite_financial_ledger_v1(str(ledger_path)) as ledger:
            request = _execution_request(certificate, _VALID_EXECUTION_ID)
            first = create_razorpay_test_order_v1(
                certificate=certificate,
                trusted_signing_identities=trusted,
                execution_request=request,
                decision_time=_DECISION_TIME,
                ledger=ledger,
                credentials=credentials,
                transport=transport,
            )
            if (
                first.resolution is not RazorpayOrderResolutionV1.CREATED
                or transport.post_count != 1
                or transport.get_count != 0
                or first.order.provider_order_id != _PROVIDER_ORDER_ID
            ):
                raise RuntimeError("deterministic demo first order proof failed")
            second = create_razorpay_test_order_v1(
                certificate=certificate,
                trusted_signing_identities=trusted,
                execution_request=request,
                decision_time=_DECISION_TIME,
                ledger=ledger,
                credentials=credentials,
                transport=transport,
            )
            if (
                second.resolution is not RazorpayOrderResolutionV1.EXISTING
                or transport.post_count != 1
                or transport.get_count != 1
                or first.order.provider_order_id != _PROVIDER_ORDER_ID
                or second.order.provider_order_id != _PROVIDER_ORDER_ID
                or first.order.provider_order_id != second.order.provider_order_id
            ):
                raise RuntimeError("deterministic demo second order proof failed")
            reservation = ledger.get_execution_reservation(_VALID_EXECUTION_ID)
    if reservation is None:
        raise RuntimeError("Money Governor did not create an execution reservation")
    return {
        "buyer_policy_frozen": True,
        "authenticated_offer_count": 2,
        "allocation_status": certificate.allocation.status.value,
        "fulfilled_quantity": certificate.allocation.fulfilled_quantity,
        "requested_quantity": policy.market_spec.requested_quantity,
        "winner_count": certificate.allocation.winner_count,
        "winner_merchant_ids": [line.merchant_id for line in certificate.allocation.lines],
        "total_payment_paise": certificate.allocation.total_payment.amount_paise,
        "certificate_digest_sha256": allocation_certificate_v2_digest(certificate),
        "certificate_verified": True,
        "execution_reserved": True,
        "first_order_resolution": first.resolution.value,
        "second_order_resolution": second.resolution.value,
        "provider_order_id": first.order.provider_order_id,
        "provider_post_count": transport.post_count,
        "provider_get_count": transport.get_count,
    }


def _tamper_path() -> dict[str, object]:
    _policy, _signed_offers, certificate = _certificate_fixture()
    tampered = _tampered_certificate(certificate)
    transport = _ControlledOrderTransport()
    credentials = RazorpayTestCredentialsV1(key_id=_KEY_ID, key_secret=_KEY_SECRET)
    with TemporaryDirectory() as temporary_directory:
        ledger_path = Path(temporary_directory) / "tamper-ledger.db"
        with open_sqlite_financial_ledger_v1(str(ledger_path)) as ledger:
            request = _execution_request(tampered, _TAMPER_EXECUTION_ID)
            try:
                create_razorpay_test_order_v1(
                    certificate=tampered,
                    trusted_signing_identities=(_identity(1), _identity(2)),
                    execution_request=request,
                    decision_time=_DECISION_TIME,
                    ledger=ledger,
                    credentials=credentials,
                    transport=transport,
                )
            except MoneyGovernorError as error:
                if error.code is not MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED:
                    raise
                failure_code = error.code.value
            else:
                raise RuntimeError("tampered certificate unexpectedly passed the Money Governor")
            reservation = ledger.get_execution_reservation(_TAMPER_EXECUTION_ID)
            idempotency = ledger.get_idempotency_record(
                namespace=_ORDER_IDEMPOTENCY_NAMESPACE,
                idempotency_key=_TAMPER_EXECUTION_ID,
            )
            if (
                reservation is not None
                or idempotency is not None
                or transport.post_count != 0
                or transport.get_count != 0
            ):
                raise RuntimeError("tampered certificate caused an unexpected money action")
    return {
        "certificate_verification_expected": False,
        "governor_failure_code": failure_code,
        "execution_reserved": reservation is not None,
        "order_idempotency_record_present": idempotency is not None,
        "provider_post_count": transport.post_count,
        "provider_get_count": transport.get_count,
    }


def run_demo_v1() -> dict[str, object]:
    return {
        "demo_version": _DEMO_VERSION,
        "invariant": _INVARIANT,
        "truth_labels": {
            "buyer_ai": "HISTORICAL LIVE EVIDENCE ONLY",
            "buyer_candidate_and_context": "DETERMINISTIC FIXTURE",
            "buyer_policy_freeze": "REAL LOCAL PRODUCTION LOGIC",
            "merchant_ai": "NOT DEMONSTRATED",
            "merchant_catalog_inventory_policy_candidates": "DETERMINISTIC FIXTURE",
            "merchant_offer_build_sign_authenticate": "REAL LOCAL PRODUCTION LOGIC",
            "merchant_receipt_and_admission": "DETERMINISTIC FIXTURE",
            "allocation": "REAL LOCAL PRODUCTION LOGIC",
            "certificate_construction": "REAL LOCAL PRODUCTION LOGIC",
            "certificate_verification": "REAL LOCAL PRODUCTION LOGIC",
            "financial_and_recipient_authorizations": "DETERMINISTIC FIXTURE",
            "decision_time": "DETERMINISTIC FIXTURE",
            "financial_ledger": "REAL LOCAL PRODUCTION LOGIC",
            "money_governor": "REAL LOCAL PRODUCTION LOGIC",
            "razorpay_order_adapter": "REAL LOCAL PRODUCTION LOGIC",
            "razorpay_provider_transport": "FAKE/CONTROLLED EXTERNAL TRANSPORT",
            "razorpay_live_test_mode": "NOT DEMONSTRATED",
            "merchant_ai_live": "NOT DEMONSTRATED",
            "certificate_explanation_ai_live": "NOT DEMONSTRATED",
        },
        "valid_path": _valid_path(),
        "tamper_path": _tamper_path(),
        "limitations": {
            "live Razorpay Test Mode execution": "NOT DEMONSTRATED",
            "payment capture": "NOT DEMONSTRATED",
            "transfer creation/settlement in this demo": "NOT DEMONSTRATED",
            "settlement": "NOT DEMONSTRATED",
            "refunds/reversals": "NOT DEMONSTRATED",
            "physical fulfillment": "NOT DEMONSTRATED",
            "transcript completeness": "NOT DEMONSTRATED",
            "exactly-once external delivery": "NOT DEMONSTRATED",
            "server-attested decision time": "NOT DEMONSTRATED",
            "live merchant AI": "NOT DEMONSTRATED",
            "live certificate explanation AI": "NOT DEMONSTRATED",
            "remaining hostile/full-system audit": "NOT DEMONSTRATED / STILL REQUIRED",
        },
    }


def main() -> int:
    print(json.dumps(run_demo_v1(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
