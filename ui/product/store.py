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
                    created_at TEXT NOT NULL
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
                    closed_at TEXT
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
                """
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
            INSERT INTO product_merchants VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
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
            ),
        )

    @staticmethod
    def get_merchant(connection: sqlite3.Connection, merchant_id: str) -> MerchantRecord | None:
        row = connection.execute(
            "SELECT * FROM product_merchants WHERE merchant_id = ?", (merchant_id,)
        ).fetchone()
        return None if row is None else MerchantRecord(**dict(row))

    @staticmethod
    def insert_market(connection: sqlite3.Connection, record: MarketRecord) -> None:
        connection.execute(
            """
            INSERT INTO product_markets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
