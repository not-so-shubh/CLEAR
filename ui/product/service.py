"""Application orchestration for runtime CLEAR authority construction."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast
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
    interpret_buyer_intent_v1,
)
from clear_market.canonical.serialization import canonical_utc_datetime
from clear_market.certificate.v2 import (
    AllocationCertificateV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
    allocation_certificate_v2_digest,
    build_allocation_certificate_v2,
    canonical_allocation_certificate_v2_bytes,
    parse_canonical_allocation_certificate_v2,
)
from clear_market.commerce import (
    BuyerPolicyV2,
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
    build_and_sign_merchant_offer_v2,
    buyer_policy_v2_commitment,
    canonical_buyer_policy_v2_bytes,
    canonical_signed_merchant_offer_v2_bytes,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.domain import CanonicalUUID4, Money
from clear_market.mechanism.v2 import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    allocate_market_v2,
)
from clear_market.verification.v2 import verify_allocation_certificate_v2

from .ai import (
    PROVIDER_IDENTITY,
    PROVIDER_PROTOCOL,
    OneCallProvider,
    ProductAIConfig,
    ProductAIConfigurationError,
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
    MarketRecord,
    MerchantRecord,
    OfferRecord,
    ProductStore,
    ResultRecord,
    configured_product_db_path,
)

_UUID_ADAPTER = TypeAdapter(CanonicalUUID4)


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


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProductService:
    """Runtime application path around frozen production CLEAR functions."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store = ProductStore(db_path if db_path is not None else configured_product_db_path())
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
                attributes=(),
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
    def _merchant_presentation(record: MerchantRecord) -> dict[str, object]:
        return {
            "merchant_id": record.merchant_id,
            "display_name": record.display_name,
            "product_display_name": record.product_display_name,
            "merchant_sku": record.merchant_sku,
            "inventory_quantity": record.inventory_quantity,
            "created_at": record.created_at,
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
        )
        try:
            authority = self._merchant_authority(record)
        except ProductServiceError as error:
            raise ProductServiceError(ProductErrorCode.INVALID_REQUEST) from error
        with self.store.connection(write=True) as connection:
            self.store.insert_merchant(connection, record)
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
            "signing_public_key_hex": authority.identity.ed25519_public_key_hex,
            "created_at": record.created_at,
        }

    def list_merchants(self) -> dict[str, object]:
        with self.store.connection() as connection:
            records = self.store.list_merchants(connection)
            for record in records:
                self._merchant_authority(record)
        return {"merchants": [self._merchant_presentation(record) for record in records]}

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
            "eligible_merchants": [self._merchant_presentation(record) for record in merchants],
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

    def get_market(self, market_id: str) -> dict[str, object]:
        market_id = _parse_uuid(market_id)
        with self.store.connection() as connection:
            market = self.store.get_market(connection, market_id)
            if market is None:
                raise ProductServiceError(ProductErrorCode.NOT_FOUND)
            policy = self._load_policy(market)
            result = self.store.get_result(connection, market_id)
            if result is not None:
                try:
                    certificate = parse_canonical_allocation_certificate_v2(
                        result.canonical_certificate
                    )
                except ValueError as error:
                    raise ProductServiceError(ProductErrorCode.PERSISTED_DATA_INVALID) from error
                if allocation_certificate_v2_digest(certificate) != result.certificate_digest:
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
