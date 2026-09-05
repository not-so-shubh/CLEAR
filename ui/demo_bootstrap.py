"""Create a fresh deterministic judge-demo product database."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

_PROFILE = "CLEAR_JUDGE_DEMO_V1"


class _RequestModel(Protocol):
    def model_validate(self, value: object) -> object: ...


class _ProductRuntime(Protocol):
    def create_merchant(self, request: object) -> dict[str, object]: ...

    def create_market(self, request: object) -> dict[str, object]: ...

    def submit_offer(self, market_id: str, request: object) -> dict[str, object]: ...


class _ProductServiceFactory(Protocol):
    def __call__(
        self,
        db_path: Path,
        *,
        clock: Callable[[], datetime],
    ) -> _ProductRuntime: ...


def _load_public_runtime() -> tuple[
    Callable[[datetime], str],
    _RequestModel,
    _RequestModel,
    _RequestModel,
    _ProductServiceFactory,
]:
    canonical_module = importlib.import_module("clear_market.canonical.serialization")
    models_module = importlib.import_module("ui.product.models")
    service_module = importlib.import_module("ui.product.service")
    return (
        cast(Callable[[datetime], str], canonical_module.canonical_utc_datetime),
        cast(_RequestModel, models_module.CreateMerchantRequest),
        cast(_RequestModel, models_module.CreateMarketRequest),
        cast(_RequestModel, models_module.SubmitOfferRequest),
        cast(_ProductServiceFactory, service_module.ProductService),
    )


(
    _canonical_utc_datetime,
    _create_merchant_request,
    _create_market_request,
    _submit_offer_request,
    _product_service,
) = _load_public_runtime()


class DemoBootstrapError(RuntimeError):
    """A demo target failed a non-destructive bootstrap precondition."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _MerchantFixture:
    display_name: str
    merchant_sku: str
    unit_cost_basis_paise: int
    minimum_margin_paise: int
    offer_unit_price_paise: int | None


_MERCHANTS = (
    _MerchantFixture(
        display_name="Alpha Systems",
        merchant_sku="ALPHA-EDGE-32",
        unit_cost_basis_paise=40_000,
        minimum_margin_paise=5_000,
        offer_unit_price_paise=45_000,
    ),
    _MerchantFixture(
        display_name="Beta Systems",
        merchant_sku="BETA-EDGE-32",
        unit_cost_basis_paise=45_000,
        minimum_margin_paise=5_000,
        offer_unit_price_paise=50_000,
    ),
    _MerchantFixture(
        display_name="Gamma Systems",
        merchant_sku="GAMMA-EDGE-32",
        unit_cost_basis_paise=50_000,
        minimum_margin_paise=5_000,
        offer_unit_price_paise=None,
    ),
)


def financial_ledger_path_for_product_db(product_db_path: Path) -> Path:
    """Return the default ProductService sibling-ledger path."""
    ledger_name = (
        f"{product_db_path.stem}-financial-ledger{product_db_path.suffix}"
        if product_db_path.suffix
        else f"{product_db_path.name}-financial-ledger"
    )
    return product_db_path.with_name(ledger_name)


def _merchant_request(fixture: _MerchantFixture) -> object:
    attributes = [
        {
            "attribute_key": "ram_gb",
            "value_type": "integer",
            "value": 32,
            "provenance": "ATTESTED",
        },
        {
            "attribute_key": "storage_gb",
            "value_type": "integer",
            "value": 1024,
            "provenance": "ATTESTED",
        },
    ]
    return _create_merchant_request.model_validate(
        {
            "display_name": fixture.display_name,
            "product_display_name": "EdgeBox 32",
            "merchant_sku": fixture.merchant_sku,
            "inventory_quantity": 5,
            "unit_cost_basis_paise": fixture.unit_cost_basis_paise,
            "minimum_margin_paise": fixture.minimum_margin_paise,
            "max_quantity_per_offer": 5,
            "attributes": attributes,
        }
    )


def _normalized_target(db_path: Path) -> Path:
    return db_path.expanduser().absolute()


def _reserve_product_db(product_db_path: Path, ledger_path: Path) -> None:
    if os.path.lexists(product_db_path):
        raise DemoBootstrapError("DEMO_TARGET_EXISTS")
    if os.path.lexists(ledger_path):
        raise DemoBootstrapError("DEMO_LEDGER_EXISTS")
    if not product_db_path.parent.is_dir():
        raise DemoBootstrapError("DEMO_PARENT_MISSING")
    try:
        descriptor = os.open(
            product_db_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as error:
        raise DemoBootstrapError("DEMO_TARGET_EXISTS") from error
    except OSError as error:
        raise DemoBootstrapError("DEMO_TARGET_UNAVAILABLE") from error
    os.close(descriptor)


def bootstrap_demo(
    db_path: Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Populate a new product DB with the open judge-rehearsal fixture."""
    supplied_time = datetime.now(UTC) if clock is None else clock()
    if supplied_time.tzinfo is None or supplied_time.utcoffset() is None:
        raise DemoBootstrapError("DEMO_CLOCK_INVALID")
    bootstrap_time = supplied_time.astimezone(UTC)
    product_db_path = _normalized_target(db_path)
    ledger_path = financial_ledger_path_for_product_db(product_db_path)
    merchant_requests = tuple(_merchant_request(fixture) for fixture in _MERCHANTS)

    _reserve_product_db(product_db_path, ledger_path)

    def fixed_clock() -> datetime:
        return bootstrap_time

    service = _product_service(product_db_path, clock=fixed_clock)

    merchants: list[dict[str, str]] = []
    merchant_ids: list[str] = []
    for fixture, request in zip(_MERCHANTS, merchant_requests, strict=True):
        created = service.create_merchant(request)
        merchant_id = created.get("merchant_id")
        if type(merchant_id) is not str:
            raise DemoBootstrapError("DEMO_BOOTSTRAP_FAILED")
        merchant_ids.append(merchant_id)
        merchants.append(
            {
                "merchant_id": merchant_id,
                "display_name": fixture.display_name,
            }
        )

    market = service.create_market(
        _create_market_request.model_validate(
            {
                "requested_quantity": 5,
                "minimum_acceptable_quantity": 1,
                "max_winners": 2,
                "max_total_payment_paise": 500_000,
                "eligible_merchant_ids": merchant_ids,
                "offer_deadline": _canonical_utc_datetime(bootstrap_time + timedelta(hours=24)),
            }
        )
    )
    market_id = market.get("market_id")
    if type(market_id) is not str:
        raise DemoBootstrapError("DEMO_BOOTSTRAP_FAILED")

    submitted_offer_count = 0
    for fixture, merchant_id in zip(_MERCHANTS, merchant_ids, strict=True):
        if fixture.offer_unit_price_paise is None:
            continue
        offer = service.submit_offer(
            market_id,
            _submit_offer_request.model_validate(
                {
                    "merchant_id": merchant_id,
                    "proposed_quantity": 5,
                    "proposed_unit_price_paise": fixture.offer_unit_price_paise,
                }
            ),
        )
        if offer.get("authenticated") is not True:
            raise DemoBootstrapError("DEMO_BOOTSTRAP_FAILED")
        submitted_offer_count += 1

    return {
        "profile": _PROFILE,
        "input_evidence": "DETERMINISTIC FIXTURE",
        "runtime_logic": "REAL LOCAL PRODUCTION LOGIC",
        "ai_action": "NOT INVOKED BY BOOTSTRAP",
        "provider_action": "NOT DEMONSTRATED",
        "product_db_path": str(product_db_path),
        "market_id": market_id,
        "market_state": "OPEN",
        "submitted_offer_count": submitted_offer_count,
        "merchants": merchants,
        "next_action": "CLOSE_MARKET_IN_UI",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a fresh CLEAR judge-demo database")
    parser.add_argument("--db", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = bootstrap_demo(args.db)
    except DemoBootstrapError as error:
        print(json.dumps({"error": error.code}, separators=(",", ":")), file=sys.stderr)
        return 2
    except Exception:
        print('{"error":"DEMO_BOOTSTRAP_FAILED"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
