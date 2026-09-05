"""Application orchestration for runtime CLEAR authority construction."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Never, cast
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import TypeAdapter, ValidationError

from clear_market.ai import (
    AIProvider,
    AIProviderError,
    AIProviderErrorCode,
    BuyerIntentFreezeError,
    BuyerIntentParseError,
    BuyerIntentParseFailureCode,
    BuyerPolicyFreezeContextV1,
    MerchantAIContextError,
    MerchantOfferProposalFreezeError,
    MerchantOfferProposalParseError,
    interpret_buyer_intent_v1,
    propose_merchant_offer_candidate_v1,
)
from clear_market.canonical import CANONICALIZATION_VERSION, canonical_json_bytes
from clear_market.canonical.serialization import canonical_utc_datetime
from clear_market.certificate.v2 import (
    ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    AllocationCertificateV2,
    AllocationClaimStatusV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
    allocation_certificate_v2_digest,
    build_allocation_certificate_v2,
    canonical_allocation_certificate_v2_bytes,
    parse_canonical_allocation_certificate_v2,
)
from clear_market.commerce import (
    MERCHANT_OFFER_CANDIDATE_LINE_V2_VERSION,
    MERCHANT_OFFER_CANDIDATE_V2_VERSION,
    AttributeValue,
    AttributeValueType,
    BuyerPolicyV2,
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MarketSpecV2,
    MerchantCatalogV2,
    MerchantEconomicPolicyV2,
    MerchantOfferBuildError,
    MerchantOfferCandidateLineV2,
    MerchantOfferCandidateV2,
    MerchantOfferSigningError,
    MerchantOfferVerificationError,
    MerchantSigningIdentityV2,
    MerchantSkuEconomicRuleV2,
    ProvenanceLabel,
    SignedMerchantOfferParseError,
    SignedMerchantOfferV2,
    build_and_sign_merchant_offer_v2,
    buyer_policy_v2_commitment,
    canonical_buyer_policy_v2_bytes,
    canonical_signed_merchant_offer_v2_bytes,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.domain import CanonicalUUID4, Money
from clear_market.execution import (
    BuyerFinancialAuthorizationV1,
    ExecutionAuthorizationRequestV1,
    ExecutionPlanV1,
    ExecutionTransferLineV1,
    MarketExecutionAuthorizationV1,
    MarketExecutionStateV1,
    MerchantRecipientAuthorizationV1,
    MoneyGovernorError,
    MoneyGovernorFailureCode,
    authorize_execution_v1,
    canonical_execution_authorization_request_v1_bytes,
    execution_request_fingerprint_v1,
)
from clear_market.mechanism.v2 import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    allocate_market_v2,
)
from clear_market.payments.razorpay import (
    RazorpayOrderError,
    RazorpayOrderFailureCode,
    RazorpayOrderResolutionV1,
    RazorpayOrderResultV1,
    RazorpayOrderStatusV1,
    RazorpayOrderTransportV1,
    RazorpayOrderV1,
    RazorpayTestCredentialsV1,
    RazorpayWebhookError,
    RazorpayWebhookVerificationConfigV1,
    authenticate_and_record_razorpay_webhook_v1,
    create_razorpay_test_order_v1,
    razorpay_order_create_fingerprint_v1,
)
from clear_market.payments.recovery import (
    RazorpayOrderRecoveryDispositionV1,
    RazorpayOrderRecoveryError,
    RazorpayOrderRecoveryResultV1,
    recover_razorpay_test_order_v1,
)
from clear_market.payments.state import (
    ClearPaymentStateSnapshotV1,
    PaymentStateError,
    derive_razorpay_payment_state_v1,
)
from clear_market.persistence import (
    ExecutionReservationV1,
    IdempotencyRecordV1,
    PersistenceError,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
)
from clear_market.persistence.sqlite import (
    SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION,
    _verify_foreign_key_integrity,
    _verify_schema,
)
from clear_market.verification.v2 import (
    AllocationCertificateVerificationResultV2,
    verify_allocation_certificate_v2,
)

from .ai import (
    PROVIDER_IDENTITY,
    PROVIDER_PROTOCOL,
    OneCallProvider,
    ProductAIConfig,
    ProductAIConfigurationError,
    configured_external_product_ai,
    configured_product_ai,
    fingerprint_invalid_candidate,
)
from .models import (
    CreateBuyerDraftRequest,
    CreateMarketRequest,
    CreateMerchantRequest,
    SubmitOfferRequest,
)
from .policy import CanonicalBuyerPolicyError, parse_canonical_buyer_policy_v2
from .store import (
    BuyerDraftRecord,
    ExecutionAuthorityRecord,
    MarketRecord,
    MerchantProposalRecord,
    MerchantRecord,
    OfferRecord,
    ProductStore,
    ResultRecord,
    configured_product_db_path,
)

_UUID_ADAPTER = TypeAdapter(CanonicalUUID4)
_CATALOG_ATTRIBUTE_FIELDS = frozenset(
    {
        "schema_version",
        "catalog_attribute_version",
        "attribute_key",
        "value_type",
        "value",
        "provenance",
        "evidence_reference_id",
    }
)
_CANDIDATE_FIELDS = frozenset({"schema_version", "merchant_offer_candidate_version", "lines"})
_CANDIDATE_LINE_FIELDS = frozenset(
    {
        "schema_version",
        "merchant_offer_candidate_line_version",
        "sku_id",
        "proposed_quantity",
        "proposed_unit_price_paise",
    }
)
_RAZORPAY_SCOPE = "Razorpay Test Mode order creation and existing-order resolution only."
_RAZORPAY_LIMITATIONS = (
    "This does not demonstrate payment capture, customer payment, webhook handling, "
    "transfers, settlement, refunds, fulfillment, or real-money movement."
)
_RAZORPAY_WEBHOOK_SECRET_ENV = "RAZORPAY_TEST_WEBHOOK_SECRET"
_RAZORPAY_ACCOUNT_ID_ENV = "RAZORPAY_TEST_ACCOUNT_ID"


class ProductErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    MERCHANT_NOT_ELIGIBLE = "MERCHANT_NOT_ELIGIBLE"
    MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
    OFFER_DEADLINE_PASSED = "OFFER_DEADLINE_PASSED"
    DUPLICATE_OFFER = "DUPLICATE_OFFER"
    MERCHANT_OFFER_REJECTED = "MERCHANT_OFFER_REJECTED"
    OFFER_AUTHENTICATION_FAILED = "OFFER_AUTHENTICATION_FAILED"
    CERTIFICATE_NOT_VERIFIED = "CERTIFICATE_NOT_VERIFIED"
    PERSISTED_DATA_INVALID = "PERSISTED_DATA_INVALID"
    DRAFT_NOT_INTERPRETABLE = "DRAFT_NOT_INTERPRETABLE"
    DRAFT_NOT_FREEZABLE = "DRAFT_NOT_FREEZABLE"
    PROPOSAL_NOT_AVAILABLE = "PROPOSAL_NOT_AVAILABLE"
    PROPOSAL_NOT_SUBMITTABLE = "PROPOSAL_NOT_SUBMITTABLE"
    MARKET_NOT_CLOSED = "MARKET_NOT_CLOSED"
    ALLOCATION_NOT_EXECUTABLE = "ALLOCATION_NOT_EXECUTABLE"
    EXECUTION_NOT_AUTHORIZED = "EXECUTION_NOT_AUTHORIZED"


class ProductServiceError(ValueError):
    __slots__ = ("code",)

    def __init__(self, code: ProductErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class _MerchantAuthority:
    record: MerchantRecord
    identity: MerchantSigningIdentityV2
    catalog: MerchantCatalogV2
    inventory: InventorySnapshotV2
    economic_policy: MerchantEconomicPolicyV2


@dataclass(frozen=True)
class _ClosedAuthorityContext:
    market: MarketRecord
    policy: BuyerPolicyV2
    result: ResultRecord
    certificate: AllocationCertificateV2
    trusted_identities: tuple[MerchantSigningIdentityV2, ...]
    verification: AllocationCertificateVerificationResultV2


@dataclass(frozen=True)
class _RazorpayLedgerState:
    create_intent_exists: bool
    provider_order_id: str | None


def _new_uuid() -> str:
    return str(uuid4())


def _parse_uuid(value: str) -> str:
    try:
        return cast(str, _UUID_ADAPTER.validate_python(value, strict=True))
    except ValidationError as error:
        raise ProductServiceError(ProductErrorCode.INVALID_REQUEST) from error


def _parse_timestamp(value: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ProductServiceError(ProductErrorCode.INVALID_REQUEST)
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise ProductServiceError(ProductErrorCode.INVALID_REQUEST) from error
    if canonical_utc_datetime(parsed) != value:
        raise ProductServiceError(ProductErrorCode.INVALID_REQUEST)
    return parsed


def _parse_persisted_timestamp(value: str) -> datetime:
    try:
        return _parse_timestamp(value)
    except ProductServiceError as error:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate persisted JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-JSON persisted number")


def _load_json(data: bytes) -> object:
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error


def _canonical_catalog_attributes(attributes: tuple[CatalogAttributeV2, ...]) -> bytes:
    return canonical_json_bytes(
        [
            {
                "schema_version": attribute.schema_version,
                "catalog_attribute_version": attribute.catalog_attribute_version,
                "attribute_key": attribute.attribute_key,
                "value_type": attribute.value.value_type.value,
                "value": attribute.value.value,
                "provenance": attribute.provenance.value,
                "evidence_reference_id": attribute.evidence_reference_id,
            }
            for attribute in sorted(attributes, key=lambda value: value.attribute_key)
        ]
    )


def _parse_catalog_attributes(data: bytes | None) -> tuple[CatalogAttributeV2, ...]:
    if data is None:
        return ()
    parsed = _load_json(data)
    if type(parsed) is not list:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
    attributes: list[CatalogAttributeV2] = []
    try:
        for value in parsed:
            if type(value) is not dict or set(value) != _CATALOG_ATTRIBUTE_FIELDS:
                raise ValueError("invalid persisted catalog attribute shape")
            if (
                value["schema_version"] != "2"
                or value["catalog_attribute_version"] != "catalog-attribute-v2"
                or type(value["value_type"]) is not str
                or type(value["provenance"]) is not str
                or value["provenance"] not in {"CLAIMED", "ATTESTED"}
            ):
                raise ValueError("invalid persisted catalog attribute version")
            attributes.append(
                CatalogAttributeV2(
                    attribute_key=value["attribute_key"],
                    value=AttributeValue(
                        value_type=AttributeValueType(value["value_type"]),
                        value=value["value"],
                    ),
                    provenance=ProvenanceLabel(value["provenance"]),
                    evidence_reference_id=value["evidence_reference_id"],
                )
            )
        keys = [attribute.attribute_key for attribute in attributes]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate persisted catalog attribute")
        normalized = tuple(sorted(attributes, key=lambda attribute: attribute.attribute_key))
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
    if _canonical_catalog_attributes(normalized) != data:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
    return normalized


def _canonical_merchant_candidate(candidate: MerchantOfferCandidateV2) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": candidate.schema_version,
            "merchant_offer_candidate_version": candidate.merchant_offer_candidate_version,
            "lines": [
                {
                    "schema_version": line.schema_version,
                    "merchant_offer_candidate_line_version": (
                        line.merchant_offer_candidate_line_version
                    ),
                    "sku_id": line.sku_id,
                    "proposed_quantity": line.proposed_quantity,
                    "proposed_unit_price_paise": line.proposed_unit_price.amount_paise,
                }
                for line in candidate.lines
            ],
        }
    )


def _parse_merchant_candidate(data: bytes) -> MerchantOfferCandidateV2:
    parsed = _load_json(data)
    if type(parsed) is not dict or set(parsed) != _CANDIDATE_FIELDS:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
    lines = parsed.get("lines")
    if (
        parsed.get("schema_version") != "2"
        or parsed.get("merchant_offer_candidate_version") != MERCHANT_OFFER_CANDIDATE_V2_VERSION
        or type(lines) is not list
    ):
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
    try:
        candidate = MerchantOfferCandidateV2(
            lines=tuple(
                MerchantOfferCandidateLineV2(
                    sku_id=line["sku_id"],
                    proposed_quantity=line["proposed_quantity"],
                    proposed_unit_price=Money(amount_paise=line["proposed_unit_price_paise"]),
                )
                for line in lines
                if type(line) is dict
                and set(line) == _CANDIDATE_LINE_FIELDS
                and line.get("schema_version") == "2"
                and line.get("merchant_offer_candidate_line_version")
                == MERCHANT_OFFER_CANDIDATE_LINE_V2_VERSION
            )
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
    if len(candidate.lines) != len(lines) or _canonical_merchant_candidate(candidate) != data:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
    return candidate


class _PersistedDuplicateKeyError(ValueError):
    pass


def _reject_persisted_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _PersistedDuplicateKeyError
        result[key] = value
    return result


def _reject_persisted_non_json_number(_value: str) -> Never:
    raise ValueError("persisted value contains a non-JSON number")


def _exact_persisted_object(
    value: object,
    expected_fields: frozenset[str],
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("persisted value must be an object")
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping) or set(mapping) != expected_fields:
        raise ValueError("persisted object fields do not match")
    return cast(dict[str, object], mapping)


def _decode_persisted_json_object(data: object) -> dict[str, object]:
    if type(data) is not bytes:
        raise TypeError("persisted JSON must be bytes")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_persisted_duplicate_keys,
            parse_constant=_reject_persisted_non_json_number,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _PersistedDuplicateKeyError,
        RecursionError,
        ValueError,
    ) as error:
        raise ValueError("persisted JSON is invalid") from error
    if type(value) is not dict:
        raise ValueError("persisted JSON root must be an object")
    return cast(dict[str, object], value)


def _persisted_datetime(value: object) -> datetime:
    if type(value) is not str:
        raise TypeError("persisted timestamp must be text")
    return _parse_persisted_timestamp(value)


def _persisted_money(value: object) -> Money:
    fields = _exact_persisted_object(value, frozenset({"amount_paise", "currency"}))
    amount = fields["amount_paise"]
    if type(amount) is not int or fields["currency"] != "INR":
        raise ValueError("persisted money is invalid")
    return Money(amount_paise=amount)


def _parse_execution_request(data: object) -> ExecutionAuthorizationRequestV1:
    try:
        envelope = _exact_persisted_object(
            _decode_persisted_json_object(data),
            frozenset({"canonicalization_version", "payload_type", "payload"}),
        )
        if (
            envelope["canonicalization_version"] != CANONICALIZATION_VERSION
            or envelope["payload_type"] != "execution_authorization_request_v1"
        ):
            raise ValueError("persisted request envelope is invalid")
        payload = _exact_persisted_object(
            envelope["payload"],
            frozenset(ExecutionAuthorizationRequestV1.model_fields),
        )

        market_values = dict(
            _exact_persisted_object(
                payload["market_execution_authorization"],
                frozenset(MarketExecutionAuthorizationV1.model_fields),
            )
        )
        state = market_values["state"]
        if type(state) is not str:
            raise ValueError("persisted market authorization state is invalid")
        market_values["state"] = MarketExecutionStateV1(state)
        market_values["valid_from"] = _persisted_datetime(market_values["valid_from"])
        market_values["valid_until"] = _persisted_datetime(market_values["valid_until"])
        market_authorization = MarketExecutionAuthorizationV1.model_validate(market_values)

        buyer_values = dict(
            _exact_persisted_object(
                payload["buyer_financial_authorization"],
                frozenset(BuyerFinancialAuthorizationV1.model_fields),
            )
        )
        buyer_values["maximum_total_payment"] = _persisted_money(
            buyer_values["maximum_total_payment"]
        )
        buyer_values["valid_from"] = _persisted_datetime(buyer_values["valid_from"])
        buyer_values["valid_until"] = _persisted_datetime(buyer_values["valid_until"])
        buyer_authorization = BuyerFinancialAuthorizationV1.model_validate(buyer_values)

        raw_recipients = payload["merchant_recipient_authorizations"]
        if type(raw_recipients) is not list:
            raise ValueError("persisted recipient authorizations must be an array")
        recipients = []
        for raw_recipient in cast(list[object], raw_recipients):
            recipient_values = dict(
                _exact_persisted_object(
                    raw_recipient,
                    frozenset(MerchantRecipientAuthorizationV1.model_fields),
                )
            )
            recipient_values["maximum_transfer"] = _persisted_money(
                recipient_values["maximum_transfer"]
            )
            recipient_values["valid_from"] = _persisted_datetime(recipient_values["valid_from"])
            recipient_values["valid_until"] = _persisted_datetime(recipient_values["valid_until"])
            recipients.append(MerchantRecipientAuthorizationV1.model_validate(recipient_values))

        request_values = dict(payload)
        request_values["market_execution_authorization"] = market_authorization
        request_values["buyer_financial_authorization"] = buyer_authorization
        request_values["merchant_recipient_authorizations"] = tuple(recipients)
        request = ExecutionAuthorizationRequestV1.model_validate(request_values)
        if canonical_execution_authorization_request_v1_bytes(request) != data:
            raise ValueError("persisted request is not canonical")
        return request
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error


def _canonical_execution_plan_bytes(plan: ExecutionPlanV1) -> bytes:
    if type(plan) is not ExecutionPlanV1:
        raise TypeError("plan must be exactly ExecutionPlanV1")
    return canonical_json_bytes(plan.model_dump(mode="json", warnings=False))


def _parse_execution_plan(data: object) -> ExecutionPlanV1:
    try:
        payload = _exact_persisted_object(
            _decode_persisted_json_object(data),
            frozenset(ExecutionPlanV1.model_fields),
        )
        raw_lines = payload["transfer_lines"]
        if type(raw_lines) is not list:
            raise ValueError("persisted transfer lines must be an array")
        lines = []
        for raw_line in cast(list[object], raw_lines):
            line_values = dict(
                _exact_persisted_object(
                    raw_line,
                    frozenset(ExecutionTransferLineV1.model_fields),
                )
            )
            line_values["transfer_amount"] = _persisted_money(line_values["transfer_amount"])
            lines.append(ExecutionTransferLineV1.model_validate(line_values))
        plan_values = dict(payload)
        plan_values["order_amount"] = _persisted_money(plan_values["order_amount"])
        plan_values["transfer_lines"] = tuple(lines)
        plan = ExecutionPlanV1.model_validate(plan_values)
        if _canonical_execution_plan_bytes(plan) != data:
            raise ValueError("persisted plan is not canonical")
        return plan
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error


class ProductService:
    """Runtime application path around frozen production CLEAR functions."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
        financial_ledger_path: Path | None = None,
    ) -> None:
        self.store = ProductStore(db_path if db_path is not None else configured_product_db_path())
        store_path = self.store.path
        default_ledger_name = (
            f"{store_path.stem}-financial-ledger{store_path.suffix}"
            if store_path.suffix
            else f"{store_path.name}-financial-ledger"
        )
        self._financial_ledger_path = (
            financial_ledger_path
            if financial_ledger_path is not None
            else store_path.with_name(default_ledger_name)
        )
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("product clock must return an aware datetime")
        return now.astimezone(UTC)

    @staticmethod
    def _merchant_authority(record: MerchantRecord) -> _MerchantAuthority:
        try:
            created_at = _parse_timestamp(record.created_at)
            identity = MerchantSigningIdentityV2(
                merchant_id=record.merchant_id,
                ed25519_public_key_hex=record.signing_public_key_hex,
            )
            product = CatalogProductV2(
                product_id=record.product_id,
                display_name=record.product_display_name,
                description="",
            )
            sku = CatalogSkuV2(
                sku_id=record.sku_id,
                product_id=record.product_id,
                merchant_sku=record.merchant_sku,
                display_name=record.product_display_name,
                attributes=_parse_catalog_attributes(record.canonical_catalog_attributes),
            )
            catalog = MerchantCatalogV2(
                catalog_id=record.catalog_id,
                merchant_id=record.merchant_id,
                generated_at=created_at,
                products=(product,),
                skus=(sku,),
            )
            inventory = InventorySnapshotV2(
                snapshot_id=record.snapshot_id,
                catalog_id=record.catalog_id,
                merchant_id=record.merchant_id,
                captured_at=created_at,
                lines=(
                    InventoryLineV2(
                        sku_id=record.sku_id,
                        quantity_available=record.inventory_quantity,
                        provenance=ProvenanceLabel.ATTESTED,
                        evidence_reference_id=record.inventory_evidence_reference_id,
                    ),
                ),
            )
            economic_policy = MerchantEconomicPolicyV2(
                economic_policy_id=record.economic_policy_id,
                merchant_id=record.merchant_id,
                catalog_id=record.catalog_id,
                sku_rules=(
                    MerchantSkuEconomicRuleV2(
                        sku_id=record.sku_id,
                        unit_cost_basis=Money(amount_paise=record.unit_cost_basis_paise),
                        minimum_margin=Money(amount_paise=record.minimum_margin_paise),
                        max_quantity_per_offer=record.max_quantity_per_offer,
                    ),
                ),
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        return _MerchantAuthority(
            record=record,
            identity=identity,
            catalog=catalog,
            inventory=inventory,
            economic_policy=economic_policy,
        )

    @staticmethod
    def _load_private_signing_key(
        record: MerchantRecord,
        identity: MerchantSigningIdentityV2,
    ) -> Ed25519PrivateKey:
        try:
            private_key = Ed25519PrivateKey.from_private_bytes(
                bytes.fromhex(record.signing_private_key_hex)
            )
            derived_public_hex = (
                private_key.public_key()
                .public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
                .hex()
            )
            if derived_public_hex != identity.ed25519_public_key_hex:
                raise ValueError("persisted signing identity mismatch")
        except (TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        return private_key

    @staticmethod
    def _load_policy(record: MarketRecord) -> BuyerPolicyV2:
        if record.canonical_buyer_policy is not None:
            try:
                policy = parse_canonical_buyer_policy_v2(record.canonical_buyer_policy)
            except (CanonicalBuyerPolicyError, TypeError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            spec = policy.market_spec
            persisted = (
                record.market_id,
                record.buyer_id,
                record.requested_quantity,
                record.minimum_acceptable_quantity,
                record.max_winners,
                record.max_total_payment_paise,
                record.eligible_merchant_ids,
                record.offer_deadline,
            )
            canonical = (
                spec.market_id,
                spec.buyer_id,
                spec.requested_quantity,
                spec.minimum_acceptable_quantity,
                spec.max_winners,
                policy.max_total_payment.amount_paise,
                policy.eligible_merchant_ids,
                canonical_utc_datetime(policy.offer_deadline),
            )
            if persisted != canonical:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            if (
                policy.mechanism_version != HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION
                or policy.objective_version != QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION
            ):
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            return policy
        try:
            return BuyerPolicyV2(
                market_spec=MarketSpecV2(
                    market_id=record.market_id,
                    buyer_id=record.buyer_id,
                    requested_quantity=record.requested_quantity,
                    minimum_acceptable_quantity=record.minimum_acceptable_quantity,
                    max_winners=record.max_winners,
                    hard_constraints=(),
                    soft_preferences=(),
                ),
                max_total_payment=Money(amount_paise=record.max_total_payment_paise),
                eligible_merchant_ids=record.eligible_merchant_ids,
                offer_deadline=_parse_timestamp(record.offer_deadline),
                mechanism_version=HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
                objective_version=QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error

    @staticmethod
    def _public_merchant_presentation(authority: _MerchantAuthority) -> dict[str, object]:
        record = authority.record
        sku = authority.catalog.skus[0]
        return {
            "merchant_id": record.merchant_id,
            "display_name": record.display_name,
            "product_display_name": record.product_display_name,
            "merchant_sku": record.merchant_sku,
            "inventory_quantity": record.inventory_quantity,
            "attributes": [
                {
                    "attribute_key": attribute.attribute_key,
                    "value_type": attribute.value.value_type.value,
                    "value": attribute.value.value,
                    "provenance": attribute.provenance.value,
                }
                for attribute in sku.attributes
            ],
            "created_at": record.created_at,
        }

    @staticmethod
    def _merchant_workspace_presentation(authority: _MerchantAuthority) -> dict[str, object]:
        presentation = ProductService._public_merchant_presentation(authority)
        rule = authority.economic_policy.sku_rules[0]
        return {
            **presentation,
            "minimum_allowed_unit_price_paise": (
                rule.unit_cost_basis.amount_paise + rule.minimum_margin.amount_paise
            ),
            "max_quantity_per_offer": rule.max_quantity_per_offer,
        }

    @staticmethod
    def _draft_context(draft: BuyerDraftRecord) -> BuyerPolicyFreezeContextV1:
        try:
            return BuyerPolicyFreezeContextV1(
                market_id=draft.market_id,
                buyer_id=draft.buyer_id,
                eligible_merchant_ids=draft.eligible_merchant_ids,
                offer_deadline=_parse_timestamp(draft.offer_deadline),
                mechanism_version=HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
                objective_version=QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error

    @staticmethod
    def _require_policy_matches_draft(
        policy: BuyerPolicyV2,
        draft: BuyerDraftRecord,
    ) -> None:
        context = ProductService._draft_context(draft)
        if (
            policy.market_spec.market_id != context.market_id
            or policy.market_spec.buyer_id != context.buyer_id
            or policy.eligible_merchant_ids != context.eligible_merchant_ids
            or policy.offer_deadline != context.offer_deadline
            or policy.mechanism_version != context.mechanism_version
            or policy.objective_version != context.objective_version
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)

    @staticmethod
    def _rules_presentation(
        policy: BuyerPolicyV2,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        def rule(
            value: object,
            *,
            identifier: str,
        ) -> dict[str, object]:
            rule_id = getattr(value, identifier)
            operand = value.operand
            return {
                "rule_id": rule_id,
                "attribute_key": value.attribute_key,
                "operator": value.operator.value,
                "value_type": operand.value_type.value,
                "value": operand.value,
                "allowed_provenance": [label.value for label in value.allowed_provenance],
            }

        return (
            [
                rule(value, identifier="constraint_id")
                for value in policy.market_spec.hard_constraints
            ],
            [
                rule(value, identifier="preference_id")
                for value in policy.market_spec.soft_preferences
            ],
        )

    def create_merchant(self, request: CreateMerchantRequest) -> dict[str, object]:
        now_text = canonical_utc_datetime(self._now())
        private_key = Ed25519PrivateKey.generate()
        public_key_hex = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )
        private_key_hex = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        try:
            attributes = tuple(
                CatalogAttributeV2(
                    attribute_key=value.attribute_key,
                    value=AttributeValue(
                        value_type=AttributeValueType(value.value_type),
                        value=value.value,
                    ),
                    provenance=ProvenanceLabel(value.provenance),
                    evidence_reference_id=_new_uuid(),
                )
                for value in request.attributes
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProductServiceError(ProductErrorCode.INVALID_REQUEST) from error
        record = MerchantRecord(
            merchant_id=_new_uuid(),
            display_name=request.display_name,
            product_id=_new_uuid(),
            catalog_id=_new_uuid(),
            sku_id=_new_uuid(),
            snapshot_id=_new_uuid(),
            inventory_evidence_reference_id=_new_uuid(),
            economic_policy_id=_new_uuid(),
            product_display_name=request.product_display_name,
            merchant_sku=request.merchant_sku,
            inventory_quantity=request.inventory_quantity,
            unit_cost_basis_paise=request.unit_cost_basis_paise,
            minimum_margin_paise=request.minimum_margin_paise,
            max_quantity_per_offer=request.max_quantity_per_offer,
            signing_public_key_hex=public_key_hex,
            signing_private_key_hex=private_key_hex,
            created_at=now_text,
            canonical_catalog_attributes=_canonical_catalog_attributes(attributes),
        )
        try:
            authority = self._merchant_authority(record)
        except ProductServiceError as error:
            raise ProductServiceError(ProductErrorCode.INVALID_REQUEST) from error
        with self.store.connection(write=True) as connection:
            self.store.insert_merchant(connection, record)
        workspace_presentation = self._merchant_workspace_presentation(authority)
        return {
            "merchant_id": record.merchant_id,
            "display_name": record.display_name,
            "product_id": record.product_id,
            "catalog_id": record.catalog_id,
            "sku_id": record.sku_id,
            "product_display_name": record.product_display_name,
            "merchant_sku": record.merchant_sku,
            "inventory_quantity": record.inventory_quantity,
            "unit_cost_basis_paise": record.unit_cost_basis_paise,
            "minimum_margin_paise": record.minimum_margin_paise,
            "max_quantity_per_offer": record.max_quantity_per_offer,
            "attributes": workspace_presentation["attributes"],
            "minimum_allowed_unit_price_paise": workspace_presentation[
                "minimum_allowed_unit_price_paise"
            ],
            "signing_public_key_hex": authority.identity.ed25519_public_key_hex,
            "created_at": record.created_at,
        }

    def list_merchants(self) -> dict[str, object]:
        with self.store.connection() as connection:
            records = self.store.list_merchants(connection)
            authorities = [self._merchant_authority(record) for record in records]
        return {"merchants": [self._public_merchant_presentation(value) for value in authorities]}

    @staticmethod
    def _require_market_offerable(
        *,
        market: MarketRecord,
        policy: BuyerPolicyV2,
        merchant_id: str,
        now: datetime,
    ) -> None:
        if market.state != "OPEN":
            raise ProductServiceError(ProductErrorCode.MARKET_NOT_OPEN)
        if merchant_id not in policy.eligible_merchant_ids:
            raise ProductServiceError(ProductErrorCode.MERCHANT_NOT_ELIGIBLE)
        if now > policy.offer_deadline:
            raise ProductServiceError(ProductErrorCode.OFFER_DEADLINE_PASSED)

    @staticmethod
    def _candidate_presentation(candidate: MerchantOfferCandidateV2) -> dict[str, object]:
        return {
            "lines": [
                {
                    "sku_id": line.sku_id,
                    "proposed_quantity": line.proposed_quantity,
                    "proposed_unit_price_paise": line.proposed_unit_price.amount_paise,
                }
                for line in candidate.lines
            ]
        }

    @staticmethod
    def _authenticate_offer_record(
        record: OfferRecord,
        *,
        authority: _MerchantAuthority,
        policy: BuyerPolicyV2,
    ) -> SignedMerchantOfferV2:
        try:
            authenticated = verify_canonical_signed_merchant_offer_v2(
                data=record.canonical_signed_offer,
                signing_identity=authority.identity,
                buyer_policy=policy,
                catalog=authority.catalog,
                inventory=authority.inventory,
            )
        except (MerchantOfferVerificationError, SignedMerchantOfferParseError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if (
            authenticated.offer.offer_id != record.offer_id
            or authenticated.offer.market_id != record.market_id
            or authenticated.offer.merchant_id != record.merchant_id
            or len(authenticated.offer.lines) != 1
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        line = authenticated.offer.lines[0]
        if (
            line.max_offer_quantity != record.proposed_quantity
            or line.unit_price.amount_paise != record.proposed_unit_price_paise
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        return authenticated

    @classmethod
    def _proposal_presentation(
        cls,
        proposal: MerchantProposalRecord | None,
        *,
        offer: OfferRecord | None,
        authority: _MerchantAuthority,
        policy: BuyerPolicyV2,
    ) -> dict[str, object]:
        if offer is not None:
            cls._authenticate_offer_record(offer, authority=authority, policy=policy)
            if proposal is not None and (
                proposal.state != "SUBMITTED" or proposal.submitted_offer_id != offer.offer_id
            ):
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            return {
                "state": "SUBMITTED",
                "authority": "AUTHENTICATED_OFFER",
                "signed": True,
                "authenticated": True,
                "submitted": True,
                "market_cleared": False,
                "offer": {
                    "offer_id": offer.offer_id,
                    "proposed_quantity": offer.proposed_quantity,
                    "proposed_unit_price_paise": offer.proposed_unit_price_paise,
                    "received_at": offer.received_at,
                },
                "provider_name": None if proposal is None else proposal.provider_name,
                "model": None if proposal is None else proposal.model,
                "provider_invoked": False if proposal is None else proposal.provider_invoked,
            }
        if proposal is None:
            return {"state": "NO_PROPOSAL", "provider_invoked": False}
        base: dict[str, object] = {
            "state": proposal.state,
            "provider_identity": PROVIDER_IDENTITY,
            "provider_name": proposal.provider_name,
            "model": proposal.model,
            "provider_invoked": proposal.provider_invoked,
        }
        if proposal.state == "PROPOSING":
            return base
        if proposal.state == "NO_OFFER":
            return {
                **base,
                "decision": "NO_OFFER",
                "valid": True,
                "signed": False,
                "submitted": False,
            }
        if proposal.state != "PROPOSED" or proposal.canonical_candidate is None:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        candidate = _parse_merchant_candidate(proposal.canonical_candidate)
        return {
            **base,
            "decision": "OFFER",
            "authority": "ADVISORY_ONLY",
            "signed": False,
            "submitted": False,
            "candidate": cls._candidate_presentation(candidate),
        }

    @classmethod
    def _merchant_market_presentation(
        cls,
        *,
        market: MarketRecord,
        policy: BuyerPolicyV2,
        proposal: MerchantProposalRecord | None,
        offer: OfferRecord | None,
        authority: _MerchantAuthority,
    ) -> dict[str, object]:
        hard, soft = cls._rules_presentation(policy)
        return {
            "market_id": market.market_id,
            "market_state": market.state,
            "buyer_policy_frozen": True,
            "requested_quantity": policy.market_spec.requested_quantity,
            "minimum_acceptable_quantity": policy.market_spec.minimum_acceptable_quantity,
            "max_winners": policy.market_spec.max_winners,
            "max_total_payment_paise": policy.max_total_payment.amount_paise,
            "offer_deadline": canonical_utc_datetime(policy.offer_deadline),
            "hard_constraints": hard,
            "soft_preferences": soft,
            "proposal": cls._proposal_presentation(
                proposal,
                offer=offer,
                authority=authority,
                policy=policy,
            ),
        }

    def list_merchant_markets(self, merchant_id: str) -> dict[str, object]:
        merchant_id = _parse_uuid(merchant_id)
        with self.store.connection() as connection:
            merchant = self.store.get_merchant(connection, merchant_id)
            if merchant is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            authority = self._merchant_authority(merchant)
            markets: list[dict[str, object]] = []
            for market in self.store.list_open_markets(connection):
                policy = self._load_policy(market)
                if merchant_id not in policy.eligible_merchant_ids:
                    continue
                proposal = self.store.get_merchant_proposal(
                    connection,
                    market_id=market.market_id,
                    merchant_id=merchant_id,
                )
                offer = self.store.get_offer_for_merchant(
                    connection,
                    market_id=market.market_id,
                    merchant_id=merchant_id,
                )
                markets.append(
                    self._merchant_market_presentation(
                        market=market,
                        policy=policy,
                        proposal=proposal,
                        offer=offer,
                        authority=authority,
                    )
                )
        return {
            "merchant": self._merchant_workspace_presentation(authority),
            "markets": markets,
        }

    def _merchant_proposal_target(
        self,
        connection: sqlite3.Connection,
        *,
        merchant_id: str,
        market_id: str,
        now: datetime,
    ) -> tuple[MarketRecord, BuyerPolicyV2, _MerchantAuthority]:
        merchant = self.store.get_merchant(connection, merchant_id)
        market = self.store.get_market(connection, market_id)
        if merchant is None or market is None:
            raise ProductServiceError(ProductErrorCode.NOT_FOUND)
        authority = self._merchant_authority(merchant)
        policy = self._load_policy(market)
        self._require_market_offerable(
            market=market,
            policy=policy,
            merchant_id=merchant_id,
            now=now,
        )
        return market, policy, authority

    @staticmethod
    def _merchant_ai_failure(
        *,
        market_id: str,
        merchant_id: str,
        config: ProductAIConfig | None,
        provider_invoked: bool,
        code: str,
        message: str,
        unavailable: bool = False,
        diagnostic_code: str | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "result": "UNAVAILABLE" if unavailable else "FAILED",
            "market_id": market_id,
            "merchant_id": merchant_id,
            "state": "NO_PROPOSAL",
            "authority": "ADVISORY_ONLY",
            "provider_protocol": PROVIDER_PROTOCOL,
            "provider_identity": PROVIDER_IDENTITY,
            "provider_name": None if config is None else config.provider_name,
            "model": None if config is None else config.model,
            "provider_invoked": provider_invoked,
            "code": code,
            "message": message,
        }
        if diagnostic_code is not None:
            result["diagnostic_code"] = diagnostic_code
        return result

    def _reset_merchant_proposal(self, *, market_id: str, merchant_id: str) -> None:
        with self.store.connection(write=True) as connection:
            self.store.reset_merchant_proposal(
                connection,
                market_id=market_id,
                merchant_id=merchant_id,
            )

    def propose_merchant_offer(
        self,
        merchant_id: str,
        market_id: str,
        *,
        environment: Mapping[str, str] | None = None,
        provider: AIProvider | None = None,
    ) -> dict[str, object]:
        merchant_id = _parse_uuid(merchant_id)
        market_id = _parse_uuid(market_id)
        now = self._now()
        with self.store.connection() as connection:
            self._merchant_proposal_target(
                connection,
                merchant_id=merchant_id,
                market_id=market_id,
                now=now,
            )
        try:
            config, selected_provider = configured_external_product_ai(
                os.environ if environment is None else environment,
                provider,
            )
        except ProductAIConfigurationError:
            return self._merchant_ai_failure(
                market_id=market_id,
                merchant_id=merchant_id,
                config=None,
                provider_invoked=False,
                code="LIVE_AI_UNAVAILABLE",
                message=(
                    "Exactly one valid server-side AI model and provider configuration is required."
                ),
                unavailable=True,
            )
        now_text = canonical_utc_datetime(now)
        with self.store.connection(write=True) as connection:
            self._merchant_proposal_target(
                connection,
                merchant_id=merchant_id,
                market_id=market_id,
                now=now,
            )
            if (
                self.store.get_merchant_proposal(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                )
                is not None
                or self.store.get_offer_for_merchant(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                )
                is not None
            ):
                raise ProductServiceError(ProductErrorCode.PROPOSAL_NOT_AVAILABLE)
            try:
                self.store.claim_merchant_proposal(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                    provider_name=config.provider_name,
                    model=config.model,
                    now=now_text,
                )
            except sqlite3.IntegrityError as error:
                raise ProductServiceError(ProductErrorCode.PROPOSAL_NOT_AVAILABLE) from error

        bounded_provider = OneCallProvider(selected_provider)
        try:
            with self.store.connection() as connection:
                _market, policy, authority = self._merchant_proposal_target(
                    connection,
                    merchant_id=merchant_id,
                    market_id=market_id,
                    now=now,
                )
            candidate = propose_merchant_offer_candidate_v1(
                provider=bounded_provider,
                request_id=_new_uuid(),
                provider_name=config.provider_name,
                model=config.model,
                buyer_policy=policy,
                catalog=authority.catalog,
                inventory=authority.inventory,
                economic_policy=authority.economic_policy,
            )
            if bounded_provider.delegated_calls != 1:
                raise RuntimeError("merchant proposal did not make exactly one provider call")
        except AIProviderError as error:
            invoked = bounded_provider.delegated_calls == 1
            self._reset_merchant_proposal(market_id=market_id, merchant_id=merchant_id)
            code, message = self._provider_failure_details(error)
            return self._merchant_ai_failure(
                market_id=market_id,
                merchant_id=merchant_id,
                config=config,
                provider_invoked=invoked,
                code=code,
                message=message,
            )
        except MerchantOfferProposalParseError as error:
            self._reset_merchant_proposal(market_id=market_id, merchant_id=merchant_id)
            return self._merchant_ai_failure(
                market_id=market_id,
                merchant_id=merchant_id,
                config=config,
                provider_invoked=True,
                code="STRICT_MERCHANT_OFFER_PARSE_FAILURE",
                message="The provider output failed the strict merchant-offer parser.",
                diagnostic_code=error.code.value,
            )
        except MerchantOfferProposalFreezeError as error:
            self._reset_merchant_proposal(market_id=market_id, merchant_id=merchant_id)
            return self._merchant_ai_failure(
                market_id=market_id,
                merchant_id=merchant_id,
                config=config,
                provider_invoked=True,
                code="STRICT_MERCHANT_OFFER_REJECTION",
                message="The parsed merchant offer proposal was rejected.",
                diagnostic_code=error.code.value,
            )
        except MerchantAIContextError as error:
            self._reset_merchant_proposal(market_id=market_id, merchant_id=merchant_id)
            return self._merchant_ai_failure(
                market_id=market_id,
                merchant_id=merchant_id,
                config=config,
                provider_invoked=bounded_provider.delegated_calls == 1,
                code="MERCHANT_AI_CONTEXT_REJECTED",
                message="The authoritative merchant AI context was rejected.",
                diagnostic_code=error.code.value,
            )
        except Exception:
            invoked = bounded_provider.delegated_calls == 1
            self._reset_merchant_proposal(market_id=market_id, merchant_id=merchant_id)
            return self._merchant_ai_failure(
                market_id=market_id,
                merchant_id=merchant_id,
                config=config,
                provider_invoked=invoked,
                code="LIVE_AI_INTERNAL_FAILURE",
                message="The merchant-offer AI boundary failed closed.",
            )

        canonical_candidate = (
            None if candidate is None else _canonical_merchant_candidate(candidate)
        )
        try:
            with self.store.connection(write=True) as connection:
                self._merchant_proposal_target(
                    connection,
                    merchant_id=merchant_id,
                    market_id=market_id,
                    now=self._now(),
                )
                self.store.complete_merchant_proposal(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                    state="NO_OFFER" if candidate is None else "PROPOSED",
                    canonical_candidate=canonical_candidate,
                    now=canonical_utc_datetime(self._now()),
                )
        except Exception:
            self._reset_merchant_proposal(market_id=market_id, merchant_id=merchant_id)
            raise
        inbox = self.list_merchant_markets(merchant_id)
        market_result = next(item for item in inbox["markets"] if item["market_id"] == market_id)
        return {"result": "SUCCESS", **market_result["proposal"]}

    def submit_merchant_proposal(self, merchant_id: str, market_id: str) -> dict[str, object]:
        merchant_id = _parse_uuid(merchant_id)
        market_id = _parse_uuid(market_id)
        received_at = self._now()
        with self.store.connection(write=True) as connection:
            _market, buyer_policy, authority = self._merchant_proposal_target(
                connection,
                merchant_id=merchant_id,
                market_id=market_id,
                now=received_at,
            )
            proposal = self.store.get_merchant_proposal(
                connection,
                market_id=market_id,
                merchant_id=merchant_id,
            )
            if (
                proposal is None
                or proposal.state != "PROPOSED"
                or proposal.canonical_candidate is None
            ):
                raise ProductServiceError(ProductErrorCode.PROPOSAL_NOT_SUBMITTABLE)
            if (
                self.store.get_offer_for_merchant(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                )
                is not None
            ):
                raise ProductServiceError(ProductErrorCode.DUPLICATE_OFFER)
            candidate = _parse_merchant_candidate(proposal.canonical_candidate)
            private_key = self._load_private_signing_key(authority.record, authority.identity)
            offer_id = _new_uuid()
            try:
                signed_offer = build_and_sign_merchant_offer_v2(
                    offer_id=offer_id,
                    buyer_policy=buyer_policy,
                    catalog=authority.catalog,
                    inventory=authority.inventory,
                    economic_policy=authority.economic_policy,
                    candidate=candidate,
                    signing_identity=authority.identity,
                    private_key=private_key,
                )
            except MerchantOfferBuildError as error:
                raise ProductServiceError(ProductErrorCode.MERCHANT_OFFER_REJECTED) from error
            except MerchantOfferSigningError as error:
                raise ProductServiceError(ProductErrorCode.OFFER_AUTHENTICATION_FAILED) from error
            canonical_offer = canonical_signed_merchant_offer_v2_bytes(signed_offer)
            try:
                authenticated = verify_canonical_signed_merchant_offer_v2(
                    data=canonical_offer,
                    signing_identity=authority.identity,
                    buyer_policy=buyer_policy,
                    catalog=authority.catalog,
                    inventory=authority.inventory,
                )
            except (MerchantOfferVerificationError, SignedMerchantOfferParseError) as error:
                raise ProductServiceError(ProductErrorCode.OFFER_AUTHENTICATION_FAILED) from error
            if len(authenticated.offer.lines) != 1:
                raise ProductServiceError(ProductErrorCode.MERCHANT_OFFER_REJECTED)
            line = authenticated.offer.lines[0]
            offer_record = OfferRecord(
                offer_id=authenticated.offer.offer_id,
                market_id=market_id,
                merchant_id=merchant_id,
                proposed_quantity=line.max_offer_quantity,
                proposed_unit_price_paise=line.unit_price.amount_paise,
                received_at=canonical_utc_datetime(received_at),
                canonical_signed_offer=canonical_offer,
            )
            try:
                self.store.insert_offer(connection, offer_record)
                self.store.mark_merchant_proposal_submitted(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                    offer_id=offer_record.offer_id,
                    now=offer_record.received_at,
                )
            except (sqlite3.IntegrityError, RuntimeError) as error:
                raise ProductServiceError(ProductErrorCode.PROPOSAL_NOT_SUBMITTABLE) from error
        return {
            "result": "SUCCESS",
            "state": "SUBMITTED",
            "market_id": market_id,
            "merchant_id": merchant_id,
            "offer_id": offer_record.offer_id,
            "signed": True,
            "authenticated": True,
            "submitted": True,
            "market_cleared": False,
            "proposed_quantity": offer_record.proposed_quantity,
            "proposed_unit_price_paise": offer_record.proposed_unit_price_paise,
            "received_at": offer_record.received_at,
        }

    def create_buyer_draft(self, request: CreateBuyerDraftRequest) -> dict[str, object]:
        eligible_ids = tuple(_parse_uuid(value) for value in request.eligible_merchant_ids)
        deadline = _parse_timestamp(request.offer_deadline)
        now = self._now()
        if deadline <= now:
            raise ProductServiceError(ProductErrorCode.INVALID_REQUEST)
        draft = BuyerDraftRecord(
            market_id=_new_uuid(),
            buyer_id=_new_uuid(),
            buyer_text=request.buyer_text,
            eligible_merchant_ids=eligible_ids,
            offer_deadline=canonical_utc_datetime(deadline),
            state="DRAFT",
            canonical_interpreted_policy=None,
            provider_name=None,
            model=None,
            provider_invoked=False,
            created_at=canonical_utc_datetime(now),
            updated_at=canonical_utc_datetime(now),
        )
        context = self._draft_context(draft)
        draft = replace(draft, eligible_merchant_ids=context.eligible_merchant_ids)
        with self.store.connection(write=True) as connection:
            merchants = []
            for merchant_id in draft.eligible_merchant_ids:
                merchant = self.store.get_merchant(connection, merchant_id)
                if merchant is None:
                    raise ProductServiceError(ProductErrorCode.NOT_FOUND)
                self._merchant_authority(merchant)
                merchants.append(merchant)
            if self.store.count_markets(connection, draft.market_id) != 0:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            self.store.insert_buyer_draft(connection, draft)
        return {
            "market_id": draft.market_id,
            "buyer_id": draft.buyer_id,
            "state": draft.state,
            "buyer_text": draft.buyer_text,
            "eligible_merchants": [
                self._public_merchant_presentation(self._merchant_authority(record))
                for record in merchants
            ],
            "offer_deadline": draft.offer_deadline,
            "authority": "ADVISORY_ONLY",
        }

    @staticmethod
    def _interpretation_failure(
        *,
        market_id: str,
        code: str,
        message: str,
        provider_invoked: bool,
        config: ProductAIConfig | None,
        unavailable: bool = False,
        diagnostic_code: str | None = None,
        candidate_diagnostic: dict[str, object] | None = None,
    ) -> dict[str, object]:
        presentation: dict[str, object] = {
            "market_id": market_id,
            "result": "UNAVAILABLE" if unavailable else "FAILED",
            "state": "DRAFT",
            "authority": "ADVISORY_ONLY",
            "policy_state": "NOT_FROZEN",
            "provider_protocol": PROVIDER_PROTOCOL,
            "provider_identity": PROVIDER_IDENTITY,
            "provider_name": None if config is None else config.provider_name,
            "model": None if config is None else config.model,
            "provider_invoked": provider_invoked,
            "code": code,
            "message": message,
        }
        if diagnostic_code is not None:
            presentation["diagnostic_code"] = diagnostic_code
        if candidate_diagnostic is not None:
            presentation["candidate_diagnostic"] = candidate_diagnostic
        return presentation

    @staticmethod
    def _provider_failure_details(error: AIProviderError) -> tuple[str, str]:
        return {
            AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED: (
                "PROVIDER_AUTHENTICATION_FAILURE",
                "The externally supplied provider rejected the server-side credentials.",
            ),
            AIProviderErrorCode.PROVIDER_RATE_LIMITED: (
                "PROVIDER_RATE_LIMITED",
                "The externally supplied provider rate limited this request.",
            ),
            AIProviderErrorCode.PROVIDER_TIMEOUT: (
                "PROVIDER_TIMEOUT",
                "The bounded provider request timed out.",
            ),
            AIProviderErrorCode.PROVIDER_UNAVAILABLE: (
                "PROVIDER_UNAVAILABLE",
                "The externally supplied provider was unavailable over the network.",
            ),
            AIProviderErrorCode.PROVIDER_REQUEST_REJECTED: (
                "PROVIDER_REQUEST_REJECTED",
                "The externally supplied provider rejected this request.",
            ),
            AIProviderErrorCode.INVALID_RESPONSE: (
                "PROVIDER_RESPONSE_REJECTED",
                "The provider response did not pass the production response boundary.",
            ),
            AIProviderErrorCode.OUTPUT_TOO_LARGE: (
                "PROVIDER_RESPONSE_REJECTED",
                "The provider response did not pass the production response boundary.",
            ),
            AIProviderErrorCode.OUTPUT_INCOMPLETE: (
                "PROVIDER_RESPONSE_REJECTED",
                "The provider did not return a complete response.",
            ),
            AIProviderErrorCode.OUTPUT_REFUSED: (
                "PROVIDER_RESPONSE_REJECTED",
                "The provider did not return an acceptable response.",
            ),
            AIProviderErrorCode.INVALID_REQUEST: (
                "LIVE_AI_INTERNAL_FAILURE",
                "The buyer-intent AI boundary failed closed.",
            ),
        }[error.code]

    def _reset_interpretation_failure(self, market_id: str, *, invoked: bool) -> None:
        with self.store.connection(write=True) as connection:
            self.store.reset_buyer_draft_after_failure(
                connection,
                market_id=market_id,
                provider_invoked=invoked,
                updated_at=canonical_utc_datetime(self._now()),
            )

    def interpret_buyer_draft(
        self,
        market_id: str,
        *,
        environment: Mapping[str, str] | None = None,
        provider: AIProvider | None = None,
    ) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            draft = self.store.get_buyer_draft(connection, market_id)
            if draft is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            if draft.state != "DRAFT":
                raise ProductServiceError(ProductErrorCode.DRAFT_NOT_INTERPRETABLE)
            self._draft_context(draft)
        try:
            config, selected_provider = configured_product_ai(
                os.environ if environment is None else environment,
                provider,
            )
        except ProductAIConfigurationError:
            return self._interpretation_failure(
                market_id=market_id,
                code="LIVE_AI_UNAVAILABLE",
                message=(
                    "Exactly one valid server-side AI model and provider configuration is required."
                ),
                provider_invoked=False,
                config=None,
                unavailable=True,
            )

        with self.store.connection(write=True) as connection:
            draft = self.store.get_buyer_draft(connection, market_id)
            if draft is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            if draft.state != "DRAFT":
                raise ProductServiceError(ProductErrorCode.DRAFT_NOT_INTERPRETABLE)
            self.store.claim_buyer_draft_interpretation(
                connection,
                market_id=market_id,
                provider_name=config.provider_name,
                model=config.model,
                updated_at=canonical_utc_datetime(self._now()),
            )

        bounded_provider = OneCallProvider(selected_provider)
        try:
            policy = interpret_buyer_intent_v1(
                provider=bounded_provider,
                request_id=_new_uuid(),
                provider_name=config.provider_name,
                model=config.model,
                buyer_text=draft.buyer_text,
                freeze_context=self._draft_context(draft),
            )
            if bounded_provider.delegated_calls != 1:
                raise RuntimeError("buyer interpretation did not make exactly one provider call")
            self._require_policy_matches_draft(policy, draft)
            canonical_policy = canonical_buyer_policy_v2_bytes(policy)
            policy = parse_canonical_buyer_policy_v2(canonical_policy)
        except AIProviderError as error:
            invoked = bounded_provider.delegated_calls == 1
            self._reset_interpretation_failure(market_id, invoked=invoked)
            code, message = self._provider_failure_details(error)
            return self._interpretation_failure(
                market_id=market_id,
                code=code,
                message=message,
                provider_invoked=invoked,
                config=config,
            )
        except BuyerIntentParseError as error:
            self._reset_interpretation_failure(market_id, invoked=True)
            candidate_diagnostic = None
            if error.code is BuyerIntentParseFailureCode.INVALID_CANDIDATE:
                response = bounded_provider.captured_response
                if response is not None:
                    try:
                        candidate_diagnostic = fingerprint_invalid_candidate(response.output_text)
                    except Exception:
                        candidate_diagnostic = None
            return self._interpretation_failure(
                market_id=market_id,
                code="STRICT_BUYER_INTENT_PARSE_FAILURE",
                message="The provider output failed the strict buyer-intent parser.",
                provider_invoked=True,
                config=config,
                diagnostic_code=error.code.value,
                candidate_diagnostic=candidate_diagnostic,
            )
        except BuyerIntentFreezeError:
            self._reset_interpretation_failure(market_id, invoked=True)
            return self._interpretation_failure(
                market_id=market_id,
                code="STRICT_BUYER_INTENT_REJECTION",
                message="The parsed interpretation was rejected by the production freeze boundary.",
                provider_invoked=True,
                config=config,
            )
        except Exception:
            invoked = bounded_provider.delegated_calls == 1
            self._reset_interpretation_failure(market_id, invoked=invoked)
            return self._interpretation_failure(
                market_id=market_id,
                code="LIVE_AI_INTERNAL_FAILURE",
                message="The buyer-intent AI boundary failed closed.",
                provider_invoked=invoked,
                config=config,
            )

        with self.store.connection(write=True) as connection:
            current = self.store.get_buyer_draft(connection, market_id)
            if current is None or current.state != "INTERPRETING":
                raise ProductServiceError(ProductErrorCode.DRAFT_NOT_INTERPRETABLE)
            self._require_policy_matches_draft(policy, current)
            self.store.complete_buyer_draft_interpretation(
                connection,
                market_id=market_id,
                canonical_policy=canonical_policy,
                provider_name=config.provider_name,
                model=config.model,
                updated_at=canonical_utc_datetime(self._now()),
            )
        return self._interpreted_presentation(
            market_id=market_id,
            policy=policy,
            config=config,
        )

    @classmethod
    def _interpreted_presentation(
        cls,
        *,
        market_id: str,
        policy: BuyerPolicyV2,
        config: ProductAIConfig,
    ) -> dict[str, object]:
        hard, soft = cls._rules_presentation(policy)
        return {
            "market_id": market_id,
            "result": "SUCCESS",
            "state": "INTERPRETED",
            "authority": "ADVISORY_ONLY",
            "provider_protocol": PROVIDER_PROTOCOL,
            "provider_identity": PROVIDER_IDENTITY,
            "provider_name": config.provider_name,
            "model": config.model,
            "provider_invoked": True,
            "interpretation": {
                "requested_quantity": policy.market_spec.requested_quantity,
                "minimum_acceptable_quantity": (policy.market_spec.minimum_acceptable_quantity),
                "max_winners": policy.market_spec.max_winners,
                "max_total_payment_paise": policy.max_total_payment.amount_paise,
                "hard_constraints": hard,
                "soft_preferences": soft,
            },
            "policy_state": "NOT_FROZEN",
        }

    def freeze_buyer_draft(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        now_text = canonical_utc_datetime(self._now())
        with self.store.connection(write=True) as connection:
            draft = self.store.get_buyer_draft(connection, market_id)
            if draft is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            if draft.state != "INTERPRETED" or draft.canonical_interpreted_policy is None:
                raise ProductServiceError(ProductErrorCode.DRAFT_NOT_FREEZABLE)
            try:
                policy = parse_canonical_buyer_policy_v2(draft.canonical_interpreted_policy)
            except (CanonicalBuyerPolicyError, TypeError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            self._require_policy_matches_draft(policy, draft)
            for merchant_id in draft.eligible_merchant_ids:
                merchant = self.store.get_merchant(connection, merchant_id)
                if merchant is None:
                    raise ProductServiceError(ProductErrorCode.NOT_FOUND)
                self._merchant_authority(merchant)
            if self.store.count_markets(connection, market_id) != 0:
                raise ProductServiceError(ProductErrorCode.DRAFT_NOT_FREEZABLE)
            market = MarketRecord(
                market_id=policy.market_spec.market_id,
                buyer_id=policy.market_spec.buyer_id,
                requested_quantity=policy.market_spec.requested_quantity,
                minimum_acceptable_quantity=policy.market_spec.minimum_acceptable_quantity,
                max_winners=policy.market_spec.max_winners,
                max_total_payment_paise=policy.max_total_payment.amount_paise,
                eligible_merchant_ids=policy.eligible_merchant_ids,
                offer_deadline=canonical_utc_datetime(policy.offer_deadline),
                state="OPEN",
                created_at=now_text,
                closed_at=None,
                canonical_buyer_policy=draft.canonical_interpreted_policy,
            )
            try:
                self.store.insert_market(connection, market)
                self.store.mark_buyer_draft_frozen(
                    connection,
                    market_id=market_id,
                    updated_at=now_text,
                )
            except (RuntimeError, sqlite3.IntegrityError) as error:
                raise ProductServiceError(ProductErrorCode.DRAFT_NOT_FREEZABLE) from error
        hard, soft = self._rules_presentation(policy)
        return {
            "market_id": market_id,
            "market_state": "OPEN",
            "buyer_policy_frozen": True,
            "buyer_policy_commitment_sha256": buyer_policy_v2_commitment(policy),
            "requested_quantity": policy.market_spec.requested_quantity,
            "minimum_acceptable_quantity": policy.market_spec.minimum_acceptable_quantity,
            "max_winners": policy.market_spec.max_winners,
            "max_total_payment_paise": policy.max_total_payment.amount_paise,
            "hard_constraints": hard,
            "soft_preferences": soft,
            "eligible_merchant_ids": list(policy.eligible_merchant_ids),
            "offer_deadline": canonical_utc_datetime(policy.offer_deadline),
        }

    def create_market(self, request: CreateMarketRequest) -> dict[str, object]:
        eligible_ids = tuple(_parse_uuid(value) for value in request.eligible_merchant_ids)
        now_text = canonical_utc_datetime(self._now())
        deadline = _parse_timestamp(request.offer_deadline)
        record = MarketRecord(
            market_id=_new_uuid(),
            buyer_id=_new_uuid(),
            requested_quantity=request.requested_quantity,
            minimum_acceptable_quantity=request.minimum_acceptable_quantity,
            max_winners=request.max_winners,
            max_total_payment_paise=request.max_total_payment_paise,
            eligible_merchant_ids=eligible_ids,
            offer_deadline=canonical_utc_datetime(deadline),
            state="OPEN",
            created_at=now_text,
            closed_at=None,
        )
        try:
            policy = self._load_policy(record)
        except ProductServiceError as error:
            raise ProductServiceError(ProductErrorCode.INVALID_REQUEST) from error
        record = replace(
            record,
            eligible_merchant_ids=policy.eligible_merchant_ids,
            canonical_buyer_policy=canonical_buyer_policy_v2_bytes(policy),
        )
        with self.store.connection(write=True) as connection:
            for merchant_id in eligible_ids:
                merchant = self.store.get_merchant(connection, merchant_id)
                if merchant is None:
                    raise ProductServiceError(ProductErrorCode.NOT_FOUND)
                self._merchant_authority(merchant)
            self.store.insert_market(connection, record)
        return self._market_presentation(record, None, policy)

    @staticmethod
    def _validate_market_lifecycle(market: MarketRecord) -> None:
        _parse_persisted_timestamp(market.created_at)
        _parse_persisted_timestamp(market.offer_deadline)
        if market.state == "OPEN":
            if market.closed_at is not None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            return
        if market.state != "CLOSED" or market.closed_at is None:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        _parse_persisted_timestamp(market.closed_at)

    @classmethod
    def _clearing_market_presentation(
        cls,
        market: MarketRecord,
        policy: BuyerPolicyV2,
    ) -> dict[str, object]:
        hard, soft = cls._rules_presentation(policy)
        return {
            "market_id": market.market_id,
            "state": market.state,
            "requested_quantity": policy.market_spec.requested_quantity,
            "minimum_acceptable_quantity": policy.market_spec.minimum_acceptable_quantity,
            "max_winners": policy.market_spec.max_winners,
            "max_total_payment_paise": policy.max_total_payment.amount_paise,
            "offer_deadline": canonical_utc_datetime(policy.offer_deadline),
            "hard_constraints": hard,
            "soft_preferences": soft,
        }

    def list_markets(self) -> dict[str, object]:
        with self.store.connection() as connection:
            try:
                records = self.store.list_markets(connection)
            except (TypeError, ValueError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            markets = []
            for market in records:
                self._validate_market_lifecycle(market)
                policy = self._load_policy(market)
                markets.append(
                    {
                        "market_id": market.market_id,
                        "state": market.state,
                        "requested_quantity": policy.market_spec.requested_quantity,
                        "minimum_acceptable_quantity": (
                            policy.market_spec.minimum_acceptable_quantity
                        ),
                        "max_winners": policy.market_spec.max_winners,
                        "max_total_payment_paise": policy.max_total_payment.amount_paise,
                        "offer_deadline": canonical_utc_datetime(policy.offer_deadline),
                        "submitted_offer_count": self.store.count_offers(
                            connection, market.market_id
                        ),
                        "created_at": market.created_at,
                        "closed_at": market.closed_at,
                    }
                )
        return {"markets": markets}

    def _authenticated_clearing_offers(
        self,
        connection: sqlite3.Connection,
        *,
        market: MarketRecord,
        policy: BuyerPolicyV2,
    ) -> tuple[
        list[dict[str, object]],
        tuple[MerchantOfferEvidenceV2, ...],
        dict[str, SignedMerchantOfferV2],
        dict[str, _MerchantAuthority],
    ]:
        presentations: list[dict[str, object]] = []
        evidence: list[MerchantOfferEvidenceV2] = []
        authenticated_by_offer: dict[str, SignedMerchantOfferV2] = {}
        authorities_by_merchant: dict[str, _MerchantAuthority] = {}
        for record in self.store.list_offers(connection, market.market_id):
            merchant = self.store.get_merchant(connection, record.merchant_id)
            if merchant is None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            authority = self._merchant_authority(merchant)
            authenticated = self._authenticate_offer_record(
                record,
                authority=authority,
                policy=policy,
            )
            received_at = _parse_persisted_timestamp(record.received_at)
            if received_at > policy.offer_deadline:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            line = authenticated.offer.lines[0]
            sku = next(
                (value for value in authority.catalog.skus if value.sku_id == line.sku_id),
                None,
            )
            if sku is None or authenticated.offer.offer_id in authenticated_by_offer:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            authenticated_by_offer[authenticated.offer.offer_id] = authenticated
            authorities_by_merchant[record.merchant_id] = authority
            presentations.append(
                {
                    "offer_id": authenticated.offer.offer_id,
                    "merchant_id": record.merchant_id,
                    "display_name": merchant.display_name,
                    "sku_id": line.sku_id,
                    "merchant_sku": sku.merchant_sku,
                    "product_display_name": sku.display_name,
                    "submitted_quantity": line.max_offer_quantity,
                    "unit_price_paise": line.unit_price.amount_paise,
                    "received_at": record.received_at,
                    "signed": True,
                    "authenticated": True,
                    "submitted": True,
                }
            )
            evidence.append(
                MerchantOfferEvidenceV2(
                    received_at=received_at,
                    admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
                    signing_identity=authority.identity,
                    catalog=authority.catalog,
                    inventory=authority.inventory,
                    signed_offer=authenticated,
                )
            )
        return (
            presentations,
            tuple(evidence),
            authenticated_by_offer,
            authorities_by_merchant,
        )

    def get_clearing_snapshot(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            try:
                market = self.store.get_market(connection, market_id)
            except (TypeError, ValueError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            if market is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            self._validate_market_lifecycle(market)
            policy = self._load_policy(market)
            (
                submitted_offers,
                expected_evidence,
                authenticated_by_offer,
                authorities_by_merchant,
            ) = self._authenticated_clearing_offers(
                connection,
                market=market,
                policy=policy,
            )
            try:
                result = self.store.get_result(connection, market_id)
            except (TypeError, ValueError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            if market.state == "OPEN":
                if result is not None:
                    raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
                return {
                    "market": self._clearing_market_presentation(market, policy),
                    "submitted_offers": submitted_offers,
                    "result": None,
                }
            if result is None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            certificate = self._validated_persisted_certificate(
                connection,
                market=market,
                policy=policy,
                result=result,
            )
            if certificate.merchant_offer_evidence != expected_evidence:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)

            winners = []
            seen_merchants: set[str] = set()
            for allocation_line in certificate.allocation.lines:
                authenticated = authenticated_by_offer.get(allocation_line.offer_id)
                authority = authorities_by_merchant.get(allocation_line.merchant_id)
                if authenticated is None or authority is None:
                    raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
                signed_line = authenticated.offer.lines[0]
                if (
                    allocation_line.merchant_id in seen_merchants
                    or authenticated.offer.merchant_id != allocation_line.merchant_id
                    or signed_line.sku_id != allocation_line.sku_id
                    or signed_line.unit_price != allocation_line.unit_payment
                    or allocation_line.allocated_quantity > signed_line.max_offer_quantity
                    or authority.record.sku_id != allocation_line.sku_id
                ):
                    raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
                seen_merchants.add(allocation_line.merchant_id)
                winners.append(
                    {
                        "merchant_id": allocation_line.merchant_id,
                        "display_name": authority.record.display_name,
                    }
                )
            if tuple(value["merchant_id"] for value in winners) != result.winner_merchant_ids:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            return {
                "market": self._clearing_market_presentation(market, policy),
                "submitted_offers": submitted_offers,
                "result": {
                    "allocation_status": result.allocation_status,
                    "requested_quantity": result.requested_quantity,
                    "fulfilled_quantity": result.fulfilled_quantity,
                    "winner_count": result.winner_count,
                    "total_payment_paise": result.total_payment_paise,
                    "winners": winners,
                },
            }

    def submit_offer(
        self,
        market_id: str,
        request: SubmitOfferRequest,
    ) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        merchant_id = _parse_uuid(request.merchant_id)
        received_at = self._now()
        with self.store.connection(write=True) as connection:
            market = self.store.get_market(connection, market_id)
            if market is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            if market.state != "OPEN":
                raise ProductServiceError(ProductErrorCode.MARKET_NOT_OPEN)
            if merchant_id not in market.eligible_merchant_ids:
                raise ProductServiceError(ProductErrorCode.MERCHANT_NOT_ELIGIBLE)
            if received_at > _parse_timestamp(market.offer_deadline):
                raise ProductServiceError(ProductErrorCode.OFFER_DEADLINE_PASSED)
            if any(
                offer.merchant_id == merchant_id
                for offer in self.store.list_offers(connection, market_id)
            ):
                raise ProductServiceError(ProductErrorCode.DUPLICATE_OFFER)
            merchant_record = self.store.get_merchant(connection, merchant_id)
            if merchant_record is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            if (
                self.store.get_merchant_proposal(
                    connection,
                    market_id=market_id,
                    merchant_id=merchant_id,
                )
                is not None
            ):
                raise ProductServiceError(ProductErrorCode.PROPOSAL_NOT_SUBMITTABLE)
            authority = self._merchant_authority(merchant_record)
            private_key = self._load_private_signing_key(merchant_record, authority.identity)
            buyer_policy = self._load_policy(market)
            candidate = MerchantOfferCandidateV2(
                lines=(
                    MerchantOfferCandidateLineV2(
                        sku_id=merchant_record.sku_id,
                        proposed_quantity=request.proposed_quantity,
                        proposed_unit_price=Money(amount_paise=request.proposed_unit_price_paise),
                    ),
                )
            )
            offer_id = _new_uuid()
            try:
                signed_offer = build_and_sign_merchant_offer_v2(
                    offer_id=offer_id,
                    buyer_policy=buyer_policy,
                    catalog=authority.catalog,
                    inventory=authority.inventory,
                    economic_policy=authority.economic_policy,
                    candidate=candidate,
                    signing_identity=authority.identity,
                    private_key=private_key,
                )
            except MerchantOfferBuildError as error:
                raise ProductServiceError(ProductErrorCode.MERCHANT_OFFER_REJECTED) from error
            except MerchantOfferSigningError as error:
                raise ProductServiceError(ProductErrorCode.OFFER_AUTHENTICATION_FAILED) from error
            canonical_offer = canonical_signed_merchant_offer_v2_bytes(signed_offer)
            try:
                authenticated = verify_canonical_signed_merchant_offer_v2(
                    data=canonical_offer,
                    signing_identity=authority.identity,
                    buyer_policy=buyer_policy,
                    catalog=authority.catalog,
                    inventory=authority.inventory,
                )
            except (MerchantOfferVerificationError, SignedMerchantOfferParseError) as error:
                raise ProductServiceError(ProductErrorCode.OFFER_AUTHENTICATION_FAILED) from error
            record = OfferRecord(
                offer_id=authenticated.offer.offer_id,
                market_id=market_id,
                merchant_id=merchant_id,
                proposed_quantity=request.proposed_quantity,
                proposed_unit_price_paise=request.proposed_unit_price_paise,
                received_at=canonical_utc_datetime(received_at),
                canonical_signed_offer=canonical_offer,
            )
            try:
                self.store.insert_offer(connection, record)
            except sqlite3.IntegrityError as error:
                raise ProductServiceError(ProductErrorCode.DUPLICATE_OFFER) from error
        line = authenticated.offer.lines[0]
        return {
            "offer_id": authenticated.offer.offer_id,
            "market_id": market_id,
            "merchant_id": merchant_id,
            "authenticated": True,
            "proposed_quantity": request.proposed_quantity,
            "max_offer_quantity": line.max_offer_quantity,
            "proposed_unit_price_paise": line.unit_price.amount_paise,
            "received_at": record.received_at,
        }

    def close_market(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        closed_at = canonical_utc_datetime(self._now())
        with self.store.connection(write=True) as connection:
            market = self.store.get_market(connection, market_id)
            if market is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            if market.state != "OPEN":
                raise ProductServiceError(ProductErrorCode.MARKET_NOT_OPEN)
            self.store.transition_market_to_closed(
                connection,
                market_id=market_id,
                closed_at=closed_at,
            )

        with self.store.connection() as connection:
            closed_market = self.store.get_market(connection, market_id)
            if closed_market is None or closed_market.state != "CLOSED":
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            buyer_policy = self._load_policy(closed_market)
            authenticated_offers = []
            evidence = []
            for offer_record in self.store.list_offers(connection, market_id):
                merchant_record = self.store.get_merchant(connection, offer_record.merchant_id)
                if merchant_record is None:
                    raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
                authority = self._merchant_authority(merchant_record)
                try:
                    authenticated = verify_canonical_signed_merchant_offer_v2(
                        data=offer_record.canonical_signed_offer,
                        signing_identity=authority.identity,
                        buyer_policy=buyer_policy,
                        catalog=authority.catalog,
                        inventory=authority.inventory,
                    )
                except (MerchantOfferVerificationError, SignedMerchantOfferParseError) as error:
                    raise ProductServiceError(
                        ProductErrorCode.OFFER_AUTHENTICATION_FAILED
                    ) from error
                authenticated_offers.append(authenticated)
                evidence.append(
                    MerchantOfferEvidenceV2(
                        received_at=_parse_timestamp(offer_record.received_at),
                        admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
                        signing_identity=authority.identity,
                        catalog=authority.catalog,
                        inventory=authority.inventory,
                        signed_offer=authenticated,
                    )
                )
            allocation = allocate_market_v2(
                buyer_policy=buyer_policy,
                signed_offers=tuple(authenticated_offers),
            )
            certificate = build_allocation_certificate_v2(
                certificate_id=_new_uuid(),
                buyer_policy=buyer_policy,
                merchant_offer_evidence=tuple(evidence),
                allocation=allocation,
            )
            canonical_certificate = canonical_allocation_certificate_v2_bytes(certificate)
            try:
                persisted_certificate = parse_canonical_allocation_certificate_v2(
                    canonical_certificate
                )
            except ValueError as error:
                raise ProductServiceError(ProductErrorCode.CERTIFICATE_NOT_VERIFIED) from error
            trusted_identities = []
            for merchant_id in closed_market.eligible_merchant_ids:
                trusted_record = self.store.get_merchant(connection, merchant_id)
                if trusted_record is None:
                    raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
                trusted_identities.append(self._merchant_authority(trusted_record).identity)
            verification = verify_allocation_certificate_v2(
                persisted_certificate,
                trusted_signing_identities=tuple(trusted_identities),
            )
            if not verification.verified:
                raise ProductServiceError(ProductErrorCode.CERTIFICATE_NOT_VERIFIED)
            winner_ids = tuple(dict.fromkeys(line.merchant_id for line in allocation.lines))
            result = ResultRecord(
                market_id=market_id,
                certificate_id=persisted_certificate.certificate_id,
                canonical_certificate=canonical_certificate,
                certificate_digest=allocation_certificate_v2_digest(persisted_certificate),
                certificate_verified=True,
                allocation_status=allocation.status.value,
                requested_quantity=closed_market.requested_quantity,
                fulfilled_quantity=allocation.fulfilled_quantity,
                winner_count=allocation.winner_count,
                winner_merchant_ids=winner_ids,
                total_payment_paise=allocation.total_payment.amount_paise,
            )

        with self.store.connection(write=True) as connection:
            persisted_market = self.store.get_market(connection, market_id)
            if persisted_market is None or persisted_market.state != "CLOSED":
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            if self.store.get_result(connection, market_id) is not None:
                raise ProductServiceError(ProductErrorCode.MARKET_NOT_OPEN)
            try:
                self.store.insert_result(connection, result)
            except sqlite3.IntegrityError as error:
                raise ProductServiceError(ProductErrorCode.MARKET_NOT_OPEN) from error
        return self._market_presentation(closed_market, result, buyer_policy)

    def _replayed_persisted_certificate(
        self,
        connection: sqlite3.Connection,
        *,
        market: MarketRecord,
        policy: BuyerPolicyV2,
        result: ResultRecord,
    ) -> tuple[
        AllocationCertificateV2,
        tuple[MerchantSigningIdentityV2, ...],
        AllocationCertificateVerificationResultV2,
    ]:
        try:
            certificate = parse_canonical_allocation_certificate_v2(result.canonical_certificate)
        except ValueError as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if allocation_certificate_v2_digest(
            certificate
        ) != result.certificate_digest or canonical_buyer_policy_v2_bytes(
            certificate.buyer_policy
        ) != canonical_buyer_policy_v2_bytes(policy):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        self._validate_result_against_certificate(result, certificate)
        trusted_identities = []
        for merchant_id in market.eligible_merchant_ids:
            merchant = self.store.get_merchant(connection, merchant_id)
            if merchant is None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            trusted_identities.append(self._merchant_authority(merchant).identity)
        verification = verify_allocation_certificate_v2(
            certificate,
            trusted_signing_identities=tuple(trusted_identities),
        )
        if not verification.verified or not result.certificate_verified:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        return certificate, tuple(trusted_identities), verification

    def _validated_persisted_certificate(
        self,
        connection: sqlite3.Connection,
        *,
        market: MarketRecord,
        policy: BuyerPolicyV2,
        result: ResultRecord,
    ) -> AllocationCertificateV2:
        certificate, _trusted_identities, _verification = self._replayed_persisted_certificate(
            connection,
            market=market,
            policy=policy,
            result=result,
        )
        return certificate

    def _load_closed_authority_context(
        self,
        connection: sqlite3.Connection,
        market_id: str,
    ) -> _ClosedAuthorityContext:
        try:
            market = self.store.get_market(connection, market_id)
        except (TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if market is None:
            raise ProductServiceError(ProductErrorCode.NOT_FOUND)
        self._validate_market_lifecycle(market)
        if market.state != "CLOSED":
            raise ProductServiceError(ProductErrorCode.MARKET_NOT_CLOSED)
        policy = self._load_policy(market)
        try:
            result = self.store.get_result(connection, market_id)
        except (TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if result is None:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        certificate, trusted_identities, verification = self._replayed_persisted_certificate(
            connection,
            market=market,
            policy=policy,
            result=result,
        )
        return _ClosedAuthorityContext(
            market=market,
            policy=policy,
            result=result,
            certificate=certificate,
            trusted_identities=trusted_identities,
            verification=verification,
        )

    @staticmethod
    def _certified_payments_by_merchant(
        certificate: AllocationCertificateV2,
    ) -> dict[str, int]:
        payments: dict[str, int] = {}
        for line in certificate.allocation.lines:
            payments[line.merchant_id] = (
                payments.get(line.merchant_id, 0) + line.line_payment.amount_paise
            )
        return payments

    def _new_execution_request(
        self,
        context: _ClosedAuthorityContext,
        decision_time: datetime,
    ) -> ExecutionAuthorizationRequestV1:
        certificate = context.certificate
        digest = context.result.certificate_digest
        market_id = context.market.market_id
        payments = self._certified_payments_by_merchant(certificate)
        market_authorization = MarketExecutionAuthorizationV1(
            authorization_id=_new_uuid(),
            market_id=market_id,
            certificate_digest_version=ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
            certificate_digest_sha256=digest,
            state=MarketExecutionStateV1.EXECUTABLE,
            valid_from=decision_time,
            valid_until=decision_time,
        )
        buyer_authorization = BuyerFinancialAuthorizationV1(
            authorization_id=_new_uuid(),
            buyer_id=context.policy.market_spec.buyer_id,
            market_id=market_id,
            certificate_digest_version=ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
            certificate_digest_sha256=digest,
            maximum_total_payment=context.policy.max_total_payment,
            valid_from=decision_time,
            valid_until=decision_time,
        )
        recipients = tuple(
            MerchantRecipientAuthorizationV1(
                authorization_id=_new_uuid(),
                merchant_id=merchant_id,
                recipient_id=f"clear.merchant:{merchant_id}",
                market_id=market_id,
                certificate_digest_version=ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
                certificate_digest_sha256=digest,
                maximum_transfer=Money(amount_paise=payments[merchant_id]),
                valid_from=decision_time,
                valid_until=decision_time,
            )
            for merchant_id in sorted(payments)
        )
        return ExecutionAuthorizationRequestV1(
            execution_id=_new_uuid(),
            certificate_digest_version=ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
            certificate_digest_sha256=digest,
            market_id=market_id,
            market_execution_authorization=market_authorization,
            buyer_financial_authorization=buyer_authorization,
            merchant_recipient_authorizations=recipients,
        )

    def _validate_execution_request(
        self,
        context: _ClosedAuthorityContext,
        record: ExecutionAuthorityRecord,
        request: ExecutionAuthorizationRequestV1,
        decision_time: datetime,
    ) -> None:
        certificate = context.certificate
        payments = self._certified_payments_by_merchant(certificate)
        market_authorization = request.market_execution_authorization
        buyer_authorization = request.buyer_financial_authorization
        recipients = {
            authorization.merchant_id: authorization
            for authorization in request.merchant_recipient_authorizations
        }
        if (
            request.execution_id != record.execution_id
            or request.market_id != context.market.market_id
            or request.certificate_digest_version != ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION
            or request.certificate_digest_sha256 != context.result.certificate_digest
            or market_authorization.state is not MarketExecutionStateV1.EXECUTABLE
            or market_authorization.valid_from != decision_time
            or market_authorization.valid_until != decision_time
            or buyer_authorization.buyer_id != context.policy.market_spec.buyer_id
            or buyer_authorization.maximum_total_payment != context.policy.max_total_payment
            or buyer_authorization.valid_from != decision_time
            or buyer_authorization.valid_until != decision_time
            or set(recipients) != set(payments)
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        for merchant_id, authorization in recipients.items():
            if (
                authorization.recipient_id != f"clear.merchant:{merchant_id}"
                or authorization.maximum_transfer != Money(amount_paise=payments[merchant_id])
                or authorization.valid_from != decision_time
                or authorization.valid_until != decision_time
            ):
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)

    def _validate_execution_plan(
        self,
        context: _ClosedAuthorityContext,
        request: ExecutionAuthorizationRequestV1,
        plan: ExecutionPlanV1,
        fingerprint: str,
    ) -> None:
        if type(plan) is not ExecutionPlanV1:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        recipients = {
            authorization.merchant_id: authorization
            for authorization in request.merchant_recipient_authorizations
        }
        expected_lines = tuple(
            (
                index,
                line.offer_id,
                line.merchant_id,
                line.sku_id,
                recipients[line.merchant_id].authorization_id,
                recipients[line.merchant_id].recipient_id,
                line.allocated_quantity,
                line.line_payment,
            )
            for index, line in enumerate(context.certificate.allocation.lines)
        )
        observed_lines = tuple(
            (
                line.allocation_line_index,
                line.offer_id,
                line.merchant_id,
                line.sku_id,
                line.recipient_authorization_id,
                line.recipient_id,
                line.allocated_quantity,
                line.transfer_amount,
            )
            for line in plan.transfer_lines
        )
        if (
            plan.execution_id != request.execution_id
            or plan.certificate_id != context.certificate.certificate_id
            or plan.certificate_digest_version != ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION
            or plan.certificate_digest_sha256 != context.result.certificate_digest
            or plan.market_id != context.market.market_id
            or plan.buyer_id != context.policy.market_spec.buyer_id
            or plan.market_execution_authorization_id
            != request.market_execution_authorization.authorization_id
            or plan.buyer_financial_authorization_id
            != request.buyer_financial_authorization.authorization_id
            or plan.execution_request_fingerprint_sha256 != fingerprint
            or plan.order_amount != context.certificate.allocation.total_payment
            or observed_lines != expected_lines
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)

    def _validated_execution_record(
        self,
        context: _ClosedAuthorityContext,
        record: ExecutionAuthorityRecord,
    ) -> tuple[ExecutionAuthorizationRequestV1, datetime, ExecutionPlanV1 | None]:
        try:
            decision_time = _persisted_datetime(record.decision_time)
            created_at = _persisted_datetime(record.created_at)
            decision_text = canonical_utc_datetime(decision_time)
        except (TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        request = _parse_execution_request(record.canonical_request)
        try:
            fingerprint = execution_request_fingerprint_v1(request)
        except (TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if (
            record.market_id != context.market.market_id
            or record.state not in {"AUTHORIZING", "AUTHORIZED"}
            or record.decision_time != decision_text
            or created_at != decision_time
            or record.execution_request_fingerprint_sha256 != fingerprint
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        self._validate_execution_request(context, record, request, decision_time)
        if record.state == "AUTHORIZING":
            if record.canonical_plan is not None or record.authorized_at is not None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            return request, decision_time, None
        if record.canonical_plan is None or record.authorized_at != decision_text:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        plan = _parse_execution_plan(record.canonical_plan)
        self._validate_execution_plan(context, request, plan, fingerprint)
        return request, decision_time, plan

    def _validate_financial_reservation(
        self,
        context: _ClosedAuthorityContext,
        record: ExecutionAuthorityRecord,
        decision_time: datetime,
        plan: ExecutionPlanV1,
    ) -> _RazorpayLedgerState:
        if not self._financial_ledger_path.is_file():
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        try:
            ledger_uri = f"{self._financial_ledger_path.resolve().as_uri()}?mode=ro"
            reservation_columns = {
                "execution_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "market_id",
                "execution_request_fingerprint_sha256",
                "reserved_at",
            }
            reference_columns = {
                "provider_name",
                "reference_kind",
                "reference_id",
                "execution_id",
                "recorded_at",
            }
            idempotency_columns = {
                "namespace",
                "idempotency_key",
                "request_fingerprint_sha256",
                "execution_id",
                "recorded_at",
            }
            with closing(
                sqlite3.connect(
                    ledger_uri,
                    uri=True,
                    isolation_level=None,
                )
            ) as connection:
                connection.row_factory = sqlite3.Row
                version_row = connection.execute("PRAGMA user_version").fetchone()
                if (
                    version_row is None
                    or type(version_row[0]) is not int
                    or version_row[0] != SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION
                ):
                    raise ValueError("financial ledger schema version is invalid")
                _verify_schema(connection)
                _verify_foreign_key_integrity(connection)
                reservation_rows = connection.execute(
                    """
                    SELECT * FROM clear_execution_reservations_v1
                    WHERE execution_id = ?
                    LIMIT 2
                    """,
                    (record.execution_id,),
                ).fetchall()
                reference_rows = connection.execute(
                    """
                    SELECT * FROM clear_provider_references_v1
                    WHERE execution_id = ?
                      AND provider_name = 'razorpay'
                      AND reference_kind = 'order'
                    LIMIT 2
                    """,
                    (record.execution_id,),
                ).fetchall()
                idempotency_rows = connection.execute(
                    """
                    SELECT * FROM clear_idempotency_records_v1
                    WHERE namespace = 'razorpay.order.create.v1'
                      AND idempotency_key = ?
                    LIMIT 2
                    """,
                    (record.execution_id,),
                ).fetchall()
            if len(reservation_rows) != 1 or set(reservation_rows[0].keys()) != reservation_columns:
                raise ValueError("financial reservation row is missing or malformed")
            if len(reference_rows) > 1 or any(
                set(row.keys()) != reference_columns for row in reference_rows
            ):
                raise ValueError("Razorpay provider reference is conflicting or malformed")
            if len(idempotency_rows) > 1 or any(
                set(row.keys()) != idempotency_columns for row in idempotency_rows
            ):
                raise ValueError("Razorpay create intent is conflicting or malformed")
            row = reservation_rows[0]
            reservation = ExecutionReservationV1(
                execution_id=row["execution_id"],
                certificate_digest_version=row["certificate_digest_version"],
                certificate_digest_sha256=row["certificate_digest_sha256"],
                market_id=row["market_id"],
                execution_request_fingerprint_sha256=(row["execution_request_fingerprint_sha256"]),
                reserved_at=_persisted_datetime(row["reserved_at"]),
            )
            reference = None
            if reference_rows:
                reference_row = reference_rows[0]
                reference = ProviderReferenceV1(
                    provider_name=reference_row["provider_name"],
                    reference_kind=reference_row["reference_kind"],
                    reference_id=reference_row["reference_id"],
                    execution_id=reference_row["execution_id"],
                    recorded_at=_persisted_datetime(reference_row["recorded_at"]),
                )
            create_intent = None
            if idempotency_rows:
                intent_row = idempotency_rows[0]
                create_intent = IdempotencyRecordV1(
                    namespace=intent_row["namespace"],
                    idempotency_key=intent_row["idempotency_key"],
                    request_fingerprint_sha256=intent_row["request_fingerprint_sha256"],
                    execution_id=intent_row["execution_id"],
                    recorded_at=_persisted_datetime(intent_row["recorded_at"]),
                )
        except (
            PersistenceError,
            sqlite3.Error,
            OSError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if (
            reservation.execution_id != record.execution_id
            or reservation.market_id != context.market.market_id
            or reservation.certificate_digest_version != ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION
            or reservation.certificate_digest_sha256 != context.result.certificate_digest
            or reservation.execution_request_fingerprint_sha256
            != record.execution_request_fingerprint_sha256
            or reservation.reserved_at != decision_time
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        expected_order_fingerprint = razorpay_order_create_fingerprint_v1(plan)
        if create_intent is not None and (
            create_intent.namespace != "razorpay.order.create.v1"
            or create_intent.idempotency_key != plan.execution_id
            or create_intent.request_fingerprint_sha256 != expected_order_fingerprint
            or create_intent.execution_id != plan.execution_id
            or create_intent.recorded_at != decision_time
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        if reference is not None:
            if (
                create_intent is None
                or reference.provider_name != "razorpay"
                or reference.reference_kind != "order"
                or reference.execution_id != plan.execution_id
                or reference.recorded_at != decision_time
            ):
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            try:
                RazorpayOrderV1(
                    execution_id=plan.execution_id,
                    provider_order_id=reference.reference_id,
                    amount=plan.order_amount,
                    receipt=plan.execution_id,
                    status=RazorpayOrderStatusV1.CREATED,
                )
            except (TypeError, ValueError, ValidationError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        return _RazorpayLedgerState(
            create_intent_exists=create_intent is not None,
            provider_order_id=None if reference is None else reference.reference_id,
        )

    def _merchant_display_names(
        self,
        connection: sqlite3.Connection,
        certificate: AllocationCertificateV2,
    ) -> dict[str, str]:
        names: dict[str, str] = {}
        for line in certificate.allocation.lines:
            merchant = self.store.get_merchant(connection, line.merchant_id)
            if merchant is None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            names[line.merchant_id] = merchant.display_name
        return names

    @staticmethod
    def _certificate_authority_presentation(
        context: _ClosedAuthorityContext,
        merchant_names: dict[str, str],
    ) -> dict[str, object]:
        certificate = context.certificate
        allocation = certificate.allocation
        verification = context.verification
        return {
            "market": {"market_id": context.market.market_id, "state": "CLOSED"},
            "certificate": {
                "certificate_version": certificate.certificate_version,
                "certificate_id": certificate.certificate_id,
                "digest_version": ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
                "digest_sha256": context.result.certificate_digest,
                "buyer_policy_commitment_sha256": (certificate.buyer_policy_commitment_sha256),
                "merchant_offer_evidence_count": len(certificate.merchant_offer_evidence),
                "allocation": {
                    "status": allocation.status.value,
                    "requested_quantity": context.policy.market_spec.requested_quantity,
                    "fulfilled_quantity": allocation.fulfilled_quantity,
                    "winner_count": allocation.winner_count,
                    "total_payment_paise": allocation.total_payment.amount_paise,
                    "lines": [
                        {
                            "offer_id": line.offer_id,
                            "merchant_id": line.merchant_id,
                            "display_name": merchant_names[line.merchant_id],
                            "sku_id": line.sku_id,
                            "allocated_quantity": line.allocated_quantity,
                            "unit_payment_paise": line.unit_payment.amount_paise,
                            "line_payment_paise": line.line_payment.amount_paise,
                        }
                        for line in allocation.lines
                    ],
                },
                "truth_class": "REAL LOCAL PRODUCTION LOGIC",
            },
            "verifier": {
                "verified": verification.verified,
                "failure_code": (
                    None if verification.failure_code is None else verification.failure_code.value
                ),
                "failed_evidence_index": verification.failed_evidence_index,
                "truth_class": "REAL LOCAL PRODUCTION LOGIC",
            },
        }

    @staticmethod
    def _execution_plan_presentation(
        plan: ExecutionPlanV1,
        merchant_names: dict[str, str],
    ) -> dict[str, object]:
        return {
            "execution_plan_version": plan.execution_plan_version,
            "execution_id": plan.execution_id,
            "certificate_digest_version": plan.certificate_digest_version,
            "certificate_digest_sha256": plan.certificate_digest_sha256,
            "execution_request_fingerprint_version": (plan.execution_request_fingerprint_version),
            "execution_request_fingerprint_sha256": (plan.execution_request_fingerprint_sha256),
            "idempotency_key": plan.idempotency_key,
            "order_amount_paise": plan.order_amount.amount_paise,
            "transfer_obligations": [
                {
                    "merchant_id": line.merchant_id,
                    "display_name": merchant_names[line.merchant_id],
                    "offer_id": line.offer_id,
                    "sku_id": line.sku_id,
                    "allocated_quantity": line.allocated_quantity,
                    "transfer_amount_paise": line.transfer_amount.amount_paise,
                    "recipient_id": line.recipient_id,
                }
                for line in plan.transfer_lines
            ],
            "truth_class": "REAL LOCAL PRODUCTION LOGIC",
            "provider_action": "NOT DEMONSTRATED",
        }

    @staticmethod
    def _razorpay_order_presentation(
        plan: ExecutionPlanV1,
        ledger_state: _RazorpayLedgerState,
    ) -> dict[str, object]:
        if ledger_state.provider_order_id is not None:
            return {
                "state": "ORDER_REFERENCE_PERSISTED",
                "provider_order_id": ledger_state.provider_order_id,
                "execution_id": plan.execution_id,
                "order_amount_paise": plan.order_amount.amount_paise,
                "currency": "INR",
                "receipt": plan.execution_id,
                "provider_status_refreshed": False,
                "scope": _RAZORPAY_SCOPE,
                "limitations": _RAZORPAY_LIMITATIONS,
            }
        if ledger_state.create_intent_exists:
            return {
                "state": "RECOVERY_REQUIRED",
                "provider_status_refreshed": False,
                "message": (
                    "A prior order-create intent exists without a persisted provider reference. "
                    "An explicit retry will use GET-only recovery."
                ),
                "scope": _RAZORPAY_SCOPE,
                "limitations": _RAZORPAY_LIMITATIONS,
            }
        return {
            "state": "NOT_DEMONSTRATED",
            "provider_status_refreshed": False,
            "message": "No Razorpay order action has been requested.",
            "scope": _RAZORPAY_SCOPE,
            "limitations": _RAZORPAY_LIMITATIONS,
        }

    def _authority_presentation(
        self,
        connection: sqlite3.Connection,
        context: _ClosedAuthorityContext,
        record: ExecutionAuthorityRecord | None,
    ) -> dict[str, object]:
        merchant_names = self._merchant_display_names(connection, context.certificate)
        presentation = self._certificate_authority_presentation(context, merchant_names)
        allocation = context.certificate.allocation
        if allocation.status is AllocationClaimStatusV2.INFEASIBLE:
            if record is not None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            presentation["governor"] = {
                "state": "NOT_EXECUTABLE",
                "failure_code": ProductErrorCode.ALLOCATION_NOT_EXECUTABLE.value,
            }
            return presentation
        if record is None:
            presentation["governor"] = {"state": "NOT_AUTHORIZED"}
            return presentation
        _request, decision_time, plan = self._validated_execution_record(context, record)
        if plan is None:
            presentation["governor"] = {"state": "AUTHORIZING"}
            return presentation
        ledger_state = self._validate_financial_reservation(
            context,
            record,
            decision_time,
            plan,
        )
        execution_plan = self._execution_plan_presentation(plan, merchant_names)
        razorpay_order = self._razorpay_order_presentation(plan, ledger_state)
        if razorpay_order["state"] != "NOT_DEMONSTRATED":
            execution_plan["provider_action"] = razorpay_order["state"]
        presentation["governor"] = {
            "state": "AUTHORIZED",
            "execution_plan": execution_plan,
        }
        presentation["razorpay_order"] = razorpay_order
        return presentation

    def get_market_authority(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            context = self._load_closed_authority_context(connection, market_id)
            record = self.store.get_execution_authority(connection, market_id)
            return self._authority_presentation(connection, context, record)

    def test_market_authority_tamper(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            context = self._load_closed_authority_context(connection, market_id)
            original_bytes = context.result.canonical_certificate
            original_authority = self.store.get_execution_authority(connection, market_id)
            altered_commitment = (
                "0" * 64
                if context.certificate.buyer_policy_commitment_sha256 != "0" * 64
                else "1" * 64
            )
            certificate_values = {
                name: context.certificate.__dict__[name]
                for name in AllocationCertificateV2.model_fields
            }
            certificate_values["buyer_policy_commitment_sha256"] = altered_commitment
            try:
                altered = AllocationCertificateV2.model_validate(certificate_values)
                verification = verify_allocation_certificate_v2(
                    altered,
                    trusted_signing_identities=context.trusted_identities,
                )
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            if (
                verification.verified
                or verification.failure_code is None
                or verification.failure_code.value != "POLICY_COMMITMENT_MISMATCH"
            ):
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            decision_time = self._now()
            request = self._new_execution_request(context, decision_time)
            governor_failure: MoneyGovernorFailureCode | None = None
            try:
                with SQLiteFinancialLedgerV1(":memory:") as ephemeral_ledger:
                    try:
                        plan = authorize_execution_v1(
                            certificate=altered,
                            trusted_signing_identities=context.trusted_identities,
                            request=request,
                            decision_time=decision_time,
                            ledger=ephemeral_ledger,
                        )
                    except MoneyGovernorError as error:
                        governor_failure = error.code
                        plan = None
                    ephemeral_reservation = ephemeral_ledger.get_execution_reservation(
                        request.execution_id
                    )
            except (PersistenceError, TypeError, ValueError) as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
            unchanged_result = self.store.get_result(connection, market_id)
            unchanged_authority = self.store.get_execution_authority(connection, market_id)
            if (
                governor_failure is not MoneyGovernorFailureCode.CERTIFICATE_NOT_VERIFIED
                or plan is not None
                or ephemeral_reservation is not None
                or unchanged_result is None
                or unchanged_result.canonical_certificate != original_bytes
                or unchanged_authority != original_authority
            ):
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        return {
            "market_id": market_id,
            "tamper_target": "buyer_policy_commitment_sha256",
            "persisted_certificate_mutated": False,
            "verifier": {
                "verified": verification.verified,
                "failure_code": verification.failure_code.value,
            },
            "governor": {
                "invoked": True,
                "authorized": False,
                "failure_code": governor_failure.value,
                "execution_plan_created": False,
                "persistent_reservation_created": False,
            },
            "provider_invoked": False,
            "altered_copy_authority": "THE MONEY GOVERNOR REJECTED THIS ALTERED COPY.",
            "altered_copy_money_action": "NO MONEY ACTION FOR THE ALTERED COPY.",
            "truth_class": "DETERMINISTIC FIXTURE",
        }

    @staticmethod
    def _razorpay_credentials(
        environment: Mapping[str, str],
    ) -> RazorpayTestCredentialsV1 | None:
        key_id = environment.get("RAZORPAY_TEST_KEY_ID")
        key_secret = environment.get("RAZORPAY_TEST_KEY_SECRET")
        if key_id is None or key_secret is None:
            return None
        try:
            return RazorpayTestCredentialsV1(key_id=key_id, key_secret=key_secret)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _razorpay_failure_presentation(
        *,
        market_id: str,
        code: str,
        message: str,
        provider_contacted: bool | None,
        unavailable: bool = False,
    ) -> dict[str, object]:
        return {
            "result": "UNAVAILABLE" if unavailable else "FAILED",
            "market_id": market_id,
            "mode": "RAZORPAY TEST MODE",
            "observation": "NOT DEMONSTRATED",
            "provider_contacted": provider_contacted,
            "code": code,
            "message": message,
            "scope": _RAZORPAY_SCOPE,
            "limitations": _RAZORPAY_LIMITATIONS,
        }

    @staticmethod
    def _razorpay_success_presentation(
        *,
        market_id: str,
        plan: ExecutionPlanV1,
        resolution: str,
        order: RazorpayOrderV1,
        checkout_key_id: str,
    ) -> dict[str, object]:
        if (
            type(order) is not RazorpayOrderV1
            or resolution not in {"CREATED", "EXISTING", "RECOVERED"}
            or order.execution_id != plan.execution_id
            or order.amount != plan.order_amount
            or order.currency != "INR"
            or order.receipt != plan.execution_id
        ):
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        try:
            validated_order = RazorpayOrderV1.model_validate(
                {name: order.__dict__[name] for name in RazorpayOrderV1.model_fields}
            )
        except (AttributeError, KeyError, TypeError, ValueError, ValidationError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        if validated_order != order:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        return {
            "result": "SUCCESS",
            "market_id": market_id,
            "mode": "RAZORPAY TEST MODE",
            "observation": "CURRENT-RUN PROVIDER OBSERVATION",
            "resolution": resolution,
            "provider_order_id": order.provider_order_id,
            "execution_id": plan.execution_id,
            "order_amount_paise": plan.order_amount.amount_paise,
            "currency": "INR",
            "receipt": plan.execution_id,
            "provider_contacted": True,
            "checkout": {
                "key_id": checkout_key_id,
                "provider_order_id": order.provider_order_id,
                "amount_paise": plan.order_amount.amount_paise,
                "currency": "INR",
                "execution_id": plan.execution_id,
            },
            "scope": _RAZORPAY_SCOPE,
            "limitations": _RAZORPAY_LIMITATIONS,
        }

    def create_market_razorpay_order(
        self,
        market_id: str,
        *,
        environment: Mapping[str, str] | None = None,
        transport: RazorpayOrderTransportV1 | None = None,
    ) -> dict[str, object]:
        """Run one explicit current-market action through the production order boundary."""
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            context = self._load_closed_authority_context(connection, market_id)
            if context.certificate.allocation.status is not AllocationClaimStatusV2.FEASIBLE:
                raise ProductServiceError(ProductErrorCode.ALLOCATION_NOT_EXECUTABLE)
            record = self.store.get_execution_authority(connection, market_id)
            if record is None:
                raise ProductServiceError(ProductErrorCode.EXECUTION_NOT_AUTHORIZED)
            request, decision_time, plan = self._validated_execution_record(context, record)
            if plan is None:
                raise ProductServiceError(ProductErrorCode.EXECUTION_NOT_AUTHORIZED)
            self._validate_financial_reservation(
                context,
                record,
                decision_time,
                plan,
            )

        credential_environment = os.environ if environment is None else environment
        credentials = self._razorpay_credentials(credential_environment)
        if credentials is None:
            return self._razorpay_failure_presentation(
                market_id=market_id,
                code="RAZORPAY_TEST_MODE_UNAVAILABLE",
                message="Valid server-side Razorpay Test Mode credentials are required.",
                provider_contacted=False,
                unavailable=True,
            )

        try:
            with SQLiteFinancialLedgerV1(str(self._financial_ledger_path)) as ledger:
                try:
                    created = create_razorpay_test_order_v1(
                        certificate=context.certificate,
                        trusted_signing_identities=context.trusted_identities,
                        execution_request=request,
                        decision_time=decision_time,
                        ledger=ledger,
                        credentials=credentials,
                        transport=transport,
                    )
                except RazorpayOrderError as error:
                    if error.code is not RazorpayOrderFailureCode.ORDER_CREATION_RECOVERY_REQUIRED:
                        return self._razorpay_failure_presentation(
                            market_id=market_id,
                            code=error.code.value,
                            message="The Razorpay Test Mode order boundary failed closed.",
                            provider_contacted=None,
                        )
                    recovered = recover_razorpay_test_order_v1(
                        certificate=context.certificate,
                        trusted_signing_identities=context.trusted_identities,
                        execution_request=request,
                        decision_time=decision_time,
                        ledger=ledger,
                        credentials=credentials,
                    )
                    if type(recovered) is not RazorpayOrderRecoveryResultV1:
                        raise ProductServiceError(
                            ProductErrorCode.PERSISTED_DATA_INVALID
                        ) from error
                    if (
                        recovered.execution_id != plan.execution_id
                        or recovered.order_create_fingerprint_sha256
                        != razorpay_order_create_fingerprint_v1(plan)
                    ):
                        raise ProductServiceError(
                            ProductErrorCode.PERSISTED_DATA_INVALID
                        ) from error
                    if recovered.disposition is RazorpayOrderRecoveryDispositionV1.NOT_FOUND:
                        if recovered.order is not None:
                            raise ProductServiceError(
                                ProductErrorCode.PERSISTED_DATA_INVALID
                            ) from error
                        return self._razorpay_failure_presentation(
                            market_id=market_id,
                            code="ORDER_RECOVERY_NOT_FOUND",
                            message=(
                                "GET-only recovery did not identify a provider order. "
                                "No additional provider mutation was attempted."
                            ),
                            provider_contacted=None,
                        )
                    if recovered.order is None:
                        raise ProductServiceError(
                            ProductErrorCode.PERSISTED_DATA_INVALID
                        ) from error
                    return self._razorpay_success_presentation(
                        market_id=market_id,
                        plan=plan,
                        resolution=recovered.disposition.value,
                        order=recovered.order,
                        checkout_key_id=credential_environment["RAZORPAY_TEST_KEY_ID"],
                    )
        except RazorpayOrderRecoveryError as error:
            return self._razorpay_failure_presentation(
                market_id=market_id,
                code=error.code.value,
                message="GET-only Razorpay Test Mode recovery failed closed.",
                provider_contacted=None,
            )
        except (MoneyGovernorError, PersistenceError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        except ProductServiceError:
            raise
        except (TypeError, ValueError, ValidationError):
            return self._razorpay_failure_presentation(
                market_id=market_id,
                code="RAZORPAY_ORDER_BOUNDARY_FAILED",
                message="The Razorpay Test Mode order boundary failed closed.",
                provider_contacted=None,
            )

        if type(created) is not RazorpayOrderResultV1:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        if created.resolution not in {
            RazorpayOrderResolutionV1.CREATED,
            RazorpayOrderResolutionV1.EXISTING,
        }:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
        return self._razorpay_success_presentation(
            market_id=market_id,
            plan=plan,
            resolution=created.resolution.value,
            order=created.order,
            checkout_key_id=credential_environment["RAZORPAY_TEST_KEY_ID"],
        )

    @staticmethod
    def _razorpay_webhook_config(
        environment: Mapping[str, str] | None = None,
    ) -> RazorpayWebhookVerificationConfigV1 | None:
        values = os.environ if environment is None else environment
        secret = values.get(_RAZORPAY_WEBHOOK_SECRET_ENV)
        account_id = values.get(_RAZORPAY_ACCOUNT_ID_ENV)
        if secret is None or account_id is None:
            return None
        try:
            return RazorpayWebhookVerificationConfigV1(
                expected_account_id=account_id,
                secrets=(secret,),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _razorpay_payment_state_presentation(
        *,
        market_id: str,
        snapshot: ClearPaymentStateSnapshotV1,
        webhook_disposition: str | None = None,
    ) -> dict[str, object]:
        payment_id = snapshot.effective_payment_id
        if payment_id is None and snapshot.evidence:
            payment_id = snapshot.evidence[-1].provider_payment_id
        payload: dict[str, object] = {
            "result": "SUCCESS",
            "mode": "RAZORPAY TEST MODE",
            "market_id": market_id,
            "execution_id": snapshot.execution_id,
            "provider_order_id": snapshot.provider_order_id,
            "provider_payment_id": payment_id,
            "payment_state": snapshot.state.value,
            "expected_amount_paise": snapshot.expected_amount.amount_paise,
            "currency": snapshot.expected_amount.currency.value,
            "truth_class": "REAL LOCAL PRODUCTION LOGIC",
        }
        if webhook_disposition is not None:
            payload["webhook_disposition"] = webhook_disposition
        return payload

    @staticmethod
    def _razorpay_payment_state_failure(
        *,
        code: str,
        message: str,
        market_id: str | None = None,
        execution_id: str | None = None,
        provider_order_id: str | None = None,
        provider_payment_id: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "result": "FAILED",
            "mode": "RAZORPAY TEST MODE",
            "code": code,
            "message": message,
        }
        if market_id is not None:
            payload["market_id"] = market_id
        if execution_id is not None:
            payload["execution_id"] = execution_id
        if provider_order_id is not None:
            payload["provider_order_id"] = provider_order_id
        if provider_payment_id is not None:
            payload["provider_payment_id"] = provider_payment_id
        return payload

    @staticmethod
    def _razorpay_payment_state_unavailable(
        *,
        code: str,
        message: str,
        market_id: str | None = None,
        execution_id: str | None = None,
        provider_order_id: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "result": "UNAVAILABLE",
            "mode": "RAZORPAY TEST MODE",
            "code": code,
            "message": message,
            "payment_state": "NOT AVAILABLE",
        }
        if market_id is not None:
            payload["market_id"] = market_id
        if execution_id is not None:
            payload["execution_id"] = execution_id
        if provider_order_id is not None:
            payload["provider_order_id"] = provider_order_id
        return payload

    def _validated_razorpay_execution(
        self,
        market_id: str,
    ) -> tuple[
        str,
        _ClosedAuthorityContext,
        ExecutionAuthorityRecord,
        ExecutionAuthorizationRequestV1,
        datetime,
        ExecutionPlanV1,
        _RazorpayLedgerState,
    ]:
        validated_market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            context = self._load_closed_authority_context(connection, validated_market_id)
            record = self.store.get_execution_authority(connection, validated_market_id)
            if record is None:
                raise ProductServiceError(ProductErrorCode.EXECUTION_NOT_AUTHORIZED)
            request, decision_time, plan = self._validated_execution_record(context, record)
            if plan is None:
                raise ProductServiceError(ProductErrorCode.EXECUTION_NOT_AUTHORIZED)
            ledger_state = self._validate_financial_reservation(
                context,
                record,
                decision_time,
                plan,
            )
        return (
            validated_market_id,
            context,
            record,
            request,
            decision_time,
            plan,
            ledger_state,
        )

    def record_razorpay_webhook(
        self,
        raw_body: bytes,
        *,
        signature_header: str,
        event_id_header: str,
        environment: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        verification_config = self._razorpay_webhook_config(environment)
        if verification_config is None:
            return self._razorpay_payment_state_unavailable(
                code="RAZORPAY_TEST_WEBHOOK_CONFIGURATION_UNAVAILABLE",
                message="Razorpay Test Mode webhook configuration is unavailable.",
            )

        try:
            with SQLiteFinancialLedgerV1(str(self._financial_ledger_path)) as ledger:
                ingress = authenticate_and_record_razorpay_webhook_v1(
                    raw_body=raw_body,
                    signature_header=signature_header,
                    event_id_header=event_id_header,
                    verification_config=verification_config,
                    received_at=self._now(),
                    ledger=ledger,
                )
                reservation = ledger.get_execution_reservation(ingress.event.execution_id)
                if reservation is None:
                    return self._razorpay_payment_state_failure(
                        code="EXECUTION_NOT_FOUND",
                        message="Authenticated Razorpay webhook execution was not found.",
                        execution_id=ingress.event.execution_id,
                        provider_order_id=ingress.event.provider_order_id,
                        provider_payment_id=ingress.event.provider_payment_id,
                    )
                (
                    market_id,
                    context,
                    _record,
                    _request,
                    _decision_time,
                    plan,
                    _ledger_state,
                ) = self._validated_razorpay_execution(reservation.market_id)
                if plan.execution_id != ingress.event.execution_id:
                    return self._razorpay_payment_state_failure(
                        code="EXECUTION_BINDING_MISMATCH",
                        message="Authenticated Razorpay webhook execution binding failed.",
                        market_id=market_id,
                        execution_id=ingress.event.execution_id,
                        provider_order_id=ingress.event.provider_order_id,
                        provider_payment_id=ingress.event.provider_payment_id,
                    )
                snapshot = derive_razorpay_payment_state_v1(
                    certificate=context.certificate,
                    trusted_signing_identities=context.trusted_identities,
                    execution_id=ingress.event.execution_id,
                    expected_razorpay_account_id=verification_config.expected_account_id,
                    ledger=ledger,
                )
                return self._razorpay_payment_state_presentation(
                    market_id=market_id,
                    snapshot=snapshot,
                    webhook_disposition=ingress.disposition.value,
                )
        except RazorpayWebhookError as error:
            return self._razorpay_payment_state_failure(
                code=error.code.value,
                message="Razorpay webhook authentication or validation failed closed.",
            )
        except PaymentStateError as error:
            return self._razorpay_payment_state_failure(
                code=error.code.value,
                message="Authenticated Razorpay payment evidence failed deterministic replay.",
            )
        except ProductServiceError as error:
            return self._razorpay_payment_state_failure(
                code=error.code.value,
                message="Razorpay payment execution context failed closed.",
            )
        except (OSError, PersistenceError, TypeError, ValueError):
            return self._razorpay_payment_state_failure(
                code="RAZORPAY_PAYMENT_STATE_FAILED",
                message="Razorpay payment state failed closed.",
            )

    def get_market_razorpay_payment_state(
        self,
        market_id: str,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        (
            validated_market_id,
            context,
            _record,
            _request,
            _decision_time,
            plan,
            ledger_state,
        ) = self._validated_razorpay_execution(market_id)
        if ledger_state.provider_order_id is None:
            return self._razorpay_payment_state_unavailable(
                code="RAZORPAY_PAYMENT_NOT_AVAILABLE",
                message="No persisted Razorpay provider order is available.",
                market_id=validated_market_id,
                execution_id=plan.execution_id,
            )
        verification_config = self._razorpay_webhook_config(environment)
        if verification_config is None:
            return self._razorpay_payment_state_unavailable(
                code="RAZORPAY_TEST_WEBHOOK_CONFIGURATION_UNAVAILABLE",
                message="Razorpay Test Mode webhook configuration is unavailable.",
                market_id=validated_market_id,
                execution_id=plan.execution_id,
                provider_order_id=ledger_state.provider_order_id,
            )
        try:
            with SQLiteFinancialLedgerV1(str(self._financial_ledger_path)) as ledger:
                snapshot = derive_razorpay_payment_state_v1(
                    certificate=context.certificate,
                    trusted_signing_identities=context.trusted_identities,
                    execution_id=plan.execution_id,
                    expected_razorpay_account_id=verification_config.expected_account_id,
                    ledger=ledger,
                )
        except PaymentStateError as error:
            return self._razorpay_payment_state_failure(
                code=error.code.value,
                message="Razorpay payment evidence failed deterministic replay.",
                market_id=validated_market_id,
                execution_id=plan.execution_id,
                provider_order_id=ledger_state.provider_order_id,
            )
        except (OSError, PersistenceError, TypeError, ValueError):
            return self._razorpay_payment_state_failure(
                code="RAZORPAY_PAYMENT_STATE_FAILED",
                message="Razorpay payment state failed closed.",
                market_id=validated_market_id,
                execution_id=plan.execution_id,
                provider_order_id=ledger_state.provider_order_id,
            )
        return self._razorpay_payment_state_presentation(
            market_id=validated_market_id,
            snapshot=snapshot,
        )

    def authorize_market_execution(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection(write=True) as connection:
            context = self._load_closed_authority_context(connection, market_id)
            if context.certificate.allocation.status is not AllocationClaimStatusV2.FEASIBLE:
                raise ProductServiceError(ProductErrorCode.ALLOCATION_NOT_EXECUTABLE)
            record = self.store.get_execution_authority(connection, market_id)
            if record is None:
                decision_time = self._now()
                request = self._new_execution_request(context, decision_time)
                canonical_request = canonical_execution_authorization_request_v1_bytes(request)
                fingerprint = execution_request_fingerprint_v1(request)
                decision_text = canonical_utc_datetime(decision_time)
                record = ExecutionAuthorityRecord(
                    market_id=market_id,
                    execution_id=request.execution_id,
                    decision_time=decision_text,
                    canonical_request=canonical_request,
                    execution_request_fingerprint_sha256=fingerprint,
                    state="AUTHORIZING",
                    canonical_plan=None,
                    created_at=decision_text,
                    authorized_at=None,
                )
                self.store.insert_execution_authority(connection, record)
            request, decision_time, existing_plan = self._validated_execution_record(
                context, record
            )

        if existing_plan is not None:
            return self.get_market_authority(market_id)

        try:
            with SQLiteFinancialLedgerV1(str(self._financial_ledger_path)) as ledger:
                plan = authorize_execution_v1(
                    certificate=context.certificate,
                    trusted_signing_identities=context.trusted_identities,
                    request=request,
                    decision_time=decision_time,
                    ledger=ledger,
                )
        except MoneyGovernorError as error:
            if error.code is MoneyGovernorFailureCode.ALLOCATION_NOT_EXECUTABLE:
                raise ProductServiceError(ProductErrorCode.ALLOCATION_NOT_EXECUTABLE) from error
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        except (PersistenceError, TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error

        fingerprint = record.execution_request_fingerprint_sha256
        self._validate_execution_plan(context, request, plan, fingerprint)
        try:
            canonical_plan = _canonical_execution_plan_bytes(plan)
        except (TypeError, ValueError) as error:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        with self.store.connection(write=True) as connection:
            current_context = self._load_closed_authority_context(connection, market_id)
            current_record = self.store.get_execution_authority(connection, market_id)
            if current_record is None:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            current_request, current_decision_time, _current_plan = (
                self._validated_execution_record(current_context, current_record)
            )
            if current_request != request or current_decision_time != decision_time:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)
            self._validate_execution_plan(current_context, current_request, plan, fingerprint)
            try:
                self.store.mark_execution_authorized(
                    connection,
                    market_id=market_id,
                    execution_id=request.execution_id,
                    canonical_plan=canonical_plan,
                    authorized_at=canonical_utc_datetime(decision_time),
                )
            except RuntimeError as error:
                raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
        return self.get_market_authority(market_id)

    def get_market(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            market = self.store.get_market(connection, market_id)
            if market is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            policy = self._load_policy(market)
            result = self.store.get_result(connection, market_id)
            if result is not None:
                self._validated_persisted_certificate(
                    connection,
                    market=market,
                    policy=policy,
                    result=result,
                )
            return self._market_presentation(market, result, policy)

    @staticmethod
    def _validate_result_against_certificate(
        result: ResultRecord,
        certificate: AllocationCertificateV2,
    ) -> None:
        allocation = certificate.allocation
        winner_ids = tuple(dict.fromkeys(line.merchant_id for line in allocation.lines))
        expected = (
            certificate.certificate_id,
            allocation.status.value,
            certificate.buyer_policy.market_spec.requested_quantity,
            allocation.fulfilled_quantity,
            allocation.winner_count,
            winner_ids,
            allocation.total_payment.amount_paise,
        )
        observed = (
            result.certificate_id,
            result.allocation_status,
            result.requested_quantity,
            result.fulfilled_quantity,
            result.winner_count,
            result.winner_merchant_ids,
            result.total_payment_paise,
        )
        if observed != expected:
            raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID)

    @staticmethod
    def _market_presentation(
        market: MarketRecord,
        result: ResultRecord | None,
        policy: BuyerPolicyV2,
    ) -> dict[str, object]:
        hard, soft = ProductService._rules_presentation(policy)
        presentation: dict[str, object] = {
            "market_id": market.market_id,
            "buyer_id": market.buyer_id,
            "market_state": market.state,
            "requested_quantity": market.requested_quantity,
            "minimum_acceptable_quantity": market.minimum_acceptable_quantity,
            "max_winners": market.max_winners,
            "max_total_payment_paise": market.max_total_payment_paise,
            "eligible_merchant_ids": list(market.eligible_merchant_ids),
            "offer_deadline": market.offer_deadline,
            "created_at": market.created_at,
            "closed_at": market.closed_at,
            "buyer_policy_frozen": True,
            "buyer_policy_commitment_sha256": buyer_policy_v2_commitment(policy),
            "hard_constraints": hard,
            "soft_preferences": soft,
        }
        if result is not None:
            presentation.update(
                {
                    "allocation_status": result.allocation_status,
                    "fulfilled_quantity": result.fulfilled_quantity,
                    "winner_count": result.winner_count,
                    "winner_merchant_ids": list(result.winner_merchant_ids),
                    "total_payment_paise": result.total_payment_paise,
                    "certificate_id": result.certificate_id,
                    "certificate_digest": result.certificate_digest,
                    "certificate_verified": result.certificate_verified,
                }
            )
        return presentation
