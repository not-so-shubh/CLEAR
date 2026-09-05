"""SQLite persistence adapter for runtime product authority inputs and results."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MerchantRecord:
    merchant_id: str
    display_name: str
    product_id: str
    catalog_id: str
    sku_id: str
    snapshot_id: str
    inventory_evidence_reference_id: str
    economic_policy_id: str
    product_display_name: str
    merchant_sku: str
    inventory_quantity: int
    unit_cost_basis_paise: int
    minimum_margin_paise: int
    max_quantity_per_offer: int
    signing_public_key_hex: str
    signing_private_key_hex: str
    created_at: str
    canonical_catalog_attributes: bytes | None = None


@dataclass(frozen=True)
class MarketRecord:
    market_id: str
    buyer_id: str
    requested_quantity: int
    minimum_acceptable_quantity: int
    max_winners: int
    max_total_payment_paise: int
    eligible_merchant_ids: tuple[str, ...]
    offer_deadline: str
    state: str
    created_at: str
    closed_at: str | None
    canonical_buyer_policy: bytes | None = None


@dataclass(frozen=True)
class BuyerDraftRecord:
    market_id: str
    buyer_id: str
    buyer_text: str
    eligible_merchant_ids: tuple[str, ...]
    offer_deadline: str
    state: str
    canonical_interpreted_policy: bytes | None
    provider_name: str | None
    model: str | None
    provider_invoked: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OfferRecord:
    offer_id: str
    market_id: str
    merchant_id: str
    proposed_quantity: int
    proposed_unit_price_paise: int
    received_at: str
    canonical_signed_offer: bytes


@dataclass(frozen=True)
class MerchantProposalRecord:
    market_id: str
    merchant_id: str
    state: str
    canonical_candidate: bytes | None
    provider_name: str
    model: str
    provider_invoked: bool
    submitted_offer_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ResultRecord:
    market_id: str
    certificate_id: str
    canonical_certificate: bytes
    certificate_digest: str
    certificate_verified: bool
    allocation_status: str
    requested_quantity: int
    fulfilled_quantity: int
    winner_count: int
    winner_merchant_ids: tuple[str, ...]
    total_payment_paise: int


def configured_product_db_path() -> Path:
    configured = os.environ.get("CLEAR_PRODUCT_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".clear" / "product-v1.sqlite3"


class ProductStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS product_merchants (
                    merchant_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    product_id TEXT NOT NULL UNIQUE,
                    catalog_id TEXT NOT NULL UNIQUE,
                    sku_id TEXT NOT NULL UNIQUE,
                    snapshot_id TEXT NOT NULL UNIQUE,
                    inventory_evidence_reference_id TEXT NOT NULL UNIQUE,
                    economic_policy_id TEXT NOT NULL UNIQUE,
                    product_display_name TEXT NOT NULL,
                    merchant_sku TEXT NOT NULL,
                    inventory_quantity INTEGER NOT NULL,
                    unit_cost_basis_paise INTEGER NOT NULL,
                    minimum_margin_paise INTEGER NOT NULL,
                    max_quantity_per_offer INTEGER NOT NULL,
                    signing_public_key_hex TEXT NOT NULL,
                    signing_private_key_hex TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    canonical_catalog_attributes BLOB
                );

                CREATE TABLE IF NOT EXISTS product_markets (
                    market_id TEXT PRIMARY KEY,
                    buyer_id TEXT NOT NULL,
                    requested_quantity INTEGER NOT NULL,
                    minimum_acceptable_quantity INTEGER NOT NULL,
                    max_winners INTEGER NOT NULL,
                    max_total_payment_paise INTEGER NOT NULL,
                    eligible_merchant_ids_json TEXT NOT NULL,
                    offer_deadline TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('OPEN', 'CLOSED')),
                    created_at TEXT NOT NULL,
                    closed_at TEXT,
                    canonical_buyer_policy BLOB
                );

                CREATE TABLE IF NOT EXISTS product_offers (
                    offer_id TEXT PRIMARY KEY,
                    market_id TEXT NOT NULL REFERENCES product_markets(market_id),
                    merchant_id TEXT NOT NULL REFERENCES product_merchants(merchant_id),
                    proposed_quantity INTEGER NOT NULL,
                    proposed_unit_price_paise INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    canonical_signed_offer BLOB NOT NULL,
                    UNIQUE (market_id, merchant_id)
                );

                CREATE TABLE IF NOT EXISTS product_market_results (
                    market_id TEXT PRIMARY KEY REFERENCES product_markets(market_id),
                    certificate_id TEXT NOT NULL UNIQUE,
                    canonical_certificate BLOB NOT NULL,
                    certificate_digest TEXT NOT NULL,
                    certificate_verified INTEGER NOT NULL CHECK (certificate_verified = 1),
                    allocation_status TEXT NOT NULL,
                    requested_quantity INTEGER NOT NULL,
                    fulfilled_quantity INTEGER NOT NULL,
                    winner_count INTEGER NOT NULL,
                    winner_merchant_ids_json TEXT NOT NULL,
                    total_payment_paise INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_buyer_drafts (
                    market_id TEXT PRIMARY KEY,
                    buyer_id TEXT NOT NULL,
                    buyer_text TEXT NOT NULL,
                    eligible_merchant_ids_json TEXT NOT NULL,
                    offer_deadline TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('DRAFT', 'INTERPRETING', 'INTERPRETED', 'FROZEN')
                    ),
                    canonical_interpreted_policy BLOB,
                    provider_name TEXT,
                    model TEXT,
                    provider_invoked INTEGER NOT NULL CHECK (provider_invoked IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_merchant_proposals (
                    market_id TEXT NOT NULL REFERENCES product_markets(market_id),
                    merchant_id TEXT NOT NULL REFERENCES product_merchants(merchant_id),
                    state TEXT NOT NULL CHECK (
                        state IN ('PROPOSING', 'PROPOSED', 'NO_OFFER', 'SUBMITTED')
                    ),
                    canonical_candidate BLOB,
                    provider_name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    provider_invoked INTEGER NOT NULL CHECK (provider_invoked IN (0, 1)),
                    submitted_offer_id TEXT REFERENCES product_offers(offer_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (market_id, merchant_id),
                    CHECK (
                        (state = 'PROPOSING' AND canonical_candidate IS NULL
                            AND submitted_offer_id IS NULL)
                        OR (state = 'NO_OFFER' AND canonical_candidate IS NULL
                            AND submitted_offer_id IS NULL AND provider_invoked = 1)
                        OR (state = 'PROPOSED' AND canonical_candidate IS NOT NULL
                            AND submitted_offer_id IS NULL AND provider_invoked = 1)
                        OR (state = 'SUBMITTED' AND canonical_candidate IS NOT NULL
                            AND submitted_offer_id IS NOT NULL AND provider_invoked = 1)
                    )
                );
                """
            )
            merchant_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(product_merchants)").fetchall()
            }
            if "canonical_catalog_attributes" not in merchant_columns:
                connection.execute(
                    "ALTER TABLE product_merchants ADD COLUMN canonical_catalog_attributes BLOB"
                )
            market_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(product_markets)").fetchall()
            }
            if "canonical_buyer_policy" not in market_columns:
                connection.execute(
                    "ALTER TABLE product_markets ADD COLUMN canonical_buyer_policy BLOB"
                )

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def insert_merchant(connection: sqlite3.Connection, record: MerchantRecord) -> None:
        connection.execute(
            """
            INSERT INTO product_merchants (
                merchant_id, display_name, product_id, catalog_id, sku_id, snapshot_id,
                inventory_evidence_reference_id, economic_policy_id, product_display_name,
                merchant_sku, inventory_quantity, unit_cost_basis_paise, minimum_margin_paise,
                max_quantity_per_offer, signing_public_key_hex, signing_private_key_hex,
                created_at, canonical_catalog_attributes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.merchant_id,
                record.display_name,
                record.product_id,
                record.catalog_id,
                record.sku_id,
                record.snapshot_id,
                record.inventory_evidence_reference_id,
                record.economic_policy_id,
                record.product_display_name,
                record.merchant_sku,
                record.inventory_quantity,
                record.unit_cost_basis_paise,
                record.minimum_margin_paise,
                record.max_quantity_per_offer,
                record.signing_public_key_hex,
                record.signing_private_key_hex,
                record.created_at,
                record.canonical_catalog_attributes,
            ),
        )

    @staticmethod
    def get_merchant(connection: sqlite3.Connection, merchant_id: str) -> MerchantRecord | None:
        row = connection.execute(
            "SELECT * FROM product_merchants WHERE merchant_id = ?", (merchant_id,)
        ).fetchone()
        return None if row is None else MerchantRecord(**dict(row))

    @staticmethod
    def list_merchants(connection: sqlite3.Connection) -> tuple[MerchantRecord, ...]:
        rows = connection.execute(
            "SELECT * FROM product_merchants ORDER BY created_at, merchant_id"
        ).fetchall()
        return tuple(MerchantRecord(**dict(row)) for row in rows)

    @staticmethod
    def insert_market(connection: sqlite3.Connection, record: MarketRecord) -> None:
        connection.execute(
            """
            INSERT INTO product_markets (
                market_id,
                buyer_id,
                requested_quantity,
                minimum_acceptable_quantity,
                max_winners,
                max_total_payment_paise,
                eligible_merchant_ids_json,
                offer_deadline,
                state,
                created_at,
                closed_at,
                canonical_buyer_policy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.market_id,
                record.buyer_id,
                record.requested_quantity,
                record.minimum_acceptable_quantity,
                record.max_winners,
                record.max_total_payment_paise,
                json.dumps(record.eligible_merchant_ids, separators=(",", ":")),
                record.offer_deadline,
                record.state,
                record.created_at,
                record.closed_at,
                record.canonical_buyer_policy,
            ),
        )

    @staticmethod
    def get_market(connection: sqlite3.Connection, market_id: str) -> MarketRecord | None:
        row = connection.execute(
            "SELECT * FROM product_markets WHERE market_id = ?", (market_id,)
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["eligible_merchant_ids"] = tuple(
            json.loads(values.pop("eligible_merchant_ids_json"))
        )
        return MarketRecord(**values)

    @staticmethod
    def insert_buyer_draft(connection: sqlite3.Connection, record: BuyerDraftRecord) -> None:
        connection.execute(
            """
            INSERT INTO product_buyer_drafts (
                market_id,
                buyer_id,
                buyer_text,
                eligible_merchant_ids_json,
                offer_deadline,
                state,
                canonical_interpreted_policy,
                provider_name,
                model,
                provider_invoked,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.market_id,
                record.buyer_id,
                record.buyer_text,
                json.dumps(record.eligible_merchant_ids, separators=(",", ":")),
                record.offer_deadline,
                record.state,
                record.canonical_interpreted_policy,
                record.provider_name,
                record.model,
                int(record.provider_invoked),
                record.created_at,
                record.updated_at,
            ),
        )

    @staticmethod
    def get_buyer_draft(connection: sqlite3.Connection, market_id: str) -> BuyerDraftRecord | None:
        row = connection.execute(
            "SELECT * FROM product_buyer_drafts WHERE market_id = ?", (market_id,)
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["eligible_merchant_ids"] = tuple(
            json.loads(values.pop("eligible_merchant_ids_json"))
        )
        values["provider_invoked"] = bool(values["provider_invoked"])
        return BuyerDraftRecord(**values)

    @staticmethod
    def claim_buyer_draft_interpretation(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        provider_name: str,
        model: str,
        updated_at: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE product_buyer_drafts
            SET state = 'INTERPRETING', canonical_interpreted_policy = NULL,
                provider_name = ?, model = ?, provider_invoked = 0, updated_at = ?
            WHERE market_id = ? AND state = 'DRAFT'
            """,
            (provider_name, model, updated_at, market_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("buyer draft interpretation claim failed")

    @staticmethod
    def complete_buyer_draft_interpretation(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        canonical_policy: bytes,
        provider_name: str,
        model: str,
        updated_at: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE product_buyer_drafts
            SET state = 'INTERPRETED', canonical_interpreted_policy = ?,
                provider_name = ?, model = ?, provider_invoked = 1, updated_at = ?
            WHERE market_id = ? AND state = 'INTERPRETING'
            """,
            (canonical_policy, provider_name, model, updated_at, market_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("buyer draft interpretation completion failed")

    @staticmethod
    def reset_buyer_draft_after_failure(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        provider_invoked: bool,
        updated_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE product_buyer_drafts
            SET state = 'DRAFT', canonical_interpreted_policy = NULL,
                provider_invoked = ?, updated_at = ?
            WHERE market_id = ? AND state = 'INTERPRETING'
            """,
            (int(provider_invoked), updated_at, market_id),
        )

    @staticmethod
    def mark_buyer_draft_frozen(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        updated_at: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE product_buyer_drafts SET state = 'FROZEN', updated_at = ?
            WHERE market_id = ? AND state = 'INTERPRETED'
            """,
            (updated_at, market_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("buyer draft freeze transition failed")

    @staticmethod
    def count_markets(connection: sqlite3.Connection, market_id: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM product_markets WHERE market_id = ?", (market_id,)
        ).fetchone()
        assert row is not None
        return int(row["count"])

    @staticmethod
    def insert_offer(connection: sqlite3.Connection, record: OfferRecord) -> None:
        connection.execute(
            """
            INSERT INTO product_offers VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.offer_id,
                record.market_id,
                record.merchant_id,
                record.proposed_quantity,
                record.proposed_unit_price_paise,
                record.received_at,
                record.canonical_signed_offer,
            ),
        )

    @staticmethod
    def list_offers(connection: sqlite3.Connection, market_id: str) -> tuple[OfferRecord, ...]:
        rows = connection.execute(
            """
            SELECT * FROM product_offers
            WHERE market_id = ?
            ORDER BY received_at, offer_id
            """,
            (market_id,),
        ).fetchall()
        return tuple(OfferRecord(**dict(row)) for row in rows)

    @staticmethod
    def count_offers(connection: sqlite3.Connection, market_id: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM product_offers WHERE market_id = ?", (market_id,)
        ).fetchone()
        assert row is not None
        return int(row["count"])

    @staticmethod
    def get_offer_for_merchant(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        merchant_id: str,
    ) -> OfferRecord | None:
        row = connection.execute(
            """
            SELECT * FROM product_offers
            WHERE market_id = ? AND merchant_id = ?
            """,
            (market_id, merchant_id),
        ).fetchone()
        return None if row is None else OfferRecord(**dict(row))

    @staticmethod
    def list_open_markets(connection: sqlite3.Connection) -> tuple[MarketRecord, ...]:
        rows = connection.execute(
            "SELECT * FROM product_markets WHERE state = 'OPEN' ORDER BY created_at, market_id"
        ).fetchall()
        markets: list[MarketRecord] = []
        for row in rows:
            values = dict(row)
            values["eligible_merchant_ids"] = tuple(
                json.loads(values.pop("eligible_merchant_ids_json"))
            )
            markets.append(MarketRecord(**values))
        return tuple(markets)

    @staticmethod
    def get_merchant_proposal(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        merchant_id: str,
    ) -> MerchantProposalRecord | None:
        row = connection.execute(
            """
            SELECT * FROM product_merchant_proposals
            WHERE market_id = ? AND merchant_id = ?
            """,
            (market_id, merchant_id),
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["provider_invoked"] = bool(values["provider_invoked"])
        return MerchantProposalRecord(**values)

    @staticmethod
    def claim_merchant_proposal(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        merchant_id: str,
        provider_name: str,
        model: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO product_merchant_proposals (
                market_id, merchant_id, state, canonical_candidate, provider_name, model,
                provider_invoked, submitted_offer_id, created_at, updated_at
            ) VALUES (?, ?, 'PROPOSING', NULL, ?, ?, 0, NULL, ?, ?)
            """,
            (market_id, merchant_id, provider_name, model, now, now),
        )

    @staticmethod
    def complete_merchant_proposal(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        merchant_id: str,
        state: str,
        canonical_candidate: bytes | None,
        now: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE product_merchant_proposals
            SET state = ?, canonical_candidate = ?, provider_invoked = 1, updated_at = ?
            WHERE market_id = ? AND merchant_id = ? AND state = 'PROPOSING'
            """,
            (state, canonical_candidate, now, market_id, merchant_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("merchant proposal completion failed")

    @staticmethod
    def reset_merchant_proposal(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        merchant_id: str,
    ) -> None:
        connection.execute(
            """
            DELETE FROM product_merchant_proposals
            WHERE market_id = ? AND merchant_id = ? AND state = 'PROPOSING'
            """,
            (market_id, merchant_id),
        )

    @staticmethod
    def mark_merchant_proposal_submitted(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        merchant_id: str,
        offer_id: str,
        now: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE product_merchant_proposals
            SET state = 'SUBMITTED', submitted_offer_id = ?, updated_at = ?
            WHERE market_id = ? AND merchant_id = ? AND state = 'PROPOSED'
            """,
            (offer_id, now, market_id, merchant_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("merchant proposal submission transition failed")

    @staticmethod
    def transition_market_to_closed(
        connection: sqlite3.Connection,
        *,
        market_id: str,
        closed_at: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE product_markets SET state = 'CLOSED', closed_at = ?
            WHERE market_id = ? AND state = 'OPEN'
            """,
            (closed_at, market_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("market state transition failed")

    @staticmethod
    def insert_result(connection: sqlite3.Connection, result: ResultRecord) -> None:
        connection.execute(
            """
            INSERT INTO product_market_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.market_id,
                result.certificate_id,
                result.canonical_certificate,
                result.certificate_digest,
                int(result.certificate_verified),
                result.allocation_status,
                result.requested_quantity,
                result.fulfilled_quantity,
                result.winner_count,
                json.dumps(result.winner_merchant_ids, separators=(",", ":")),
                result.total_payment_paise,
            ),
        )

    @staticmethod
    def count_results(connection: sqlite3.Connection, market_id: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM product_market_results WHERE market_id = ?",
            (market_id,),
        ).fetchone()
        assert row is not None
        return int(row["count"])

    @staticmethod
    def get_result(connection: sqlite3.Connection, market_id: str) -> ResultRecord | None:
        row = connection.execute(
            "SELECT * FROM product_market_results WHERE market_id = ?", (market_id,)
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["certificate_verified"] = bool(values["certificate_verified"])
        values["winner_merchant_ids"] = tuple(json.loads(values.pop("winner_merchant_ids_json")))
        return ResultRecord(**values)
