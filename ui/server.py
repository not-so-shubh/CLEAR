"""Small standard-library server for the CLEAR static judge UI."""

from __future__ import annotations

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from .ai_evidence import (
    build_ai_certificate_explanation_evidence,
    build_ai_merchant_proposal_evidence,
    explanation_unavailable_presentation,
    merchant_unavailable_presentation,
)
from .presentation import PresentationError, build_authority_demo_presentation
from .product import (
    CloseMarketRequest,
    CreateMarketRequest,
    CreateMerchantRequest,
    ProductService,
    ProductServiceError,
    SubmitOfferRequest,
    parse_product_json,
)
from .product.models import ProductRequestError
from .product.service import ProductErrorCode
from .razorpay_evidence import (
    build_razorpay_test_order_evidence,
    unavailable_presentation,
)

UI_ROOT = Path(__file__).resolve().parent
_LIVE_EVIDENCE_LOCK = Lock()
_LIVE_AI_EVIDENCE_LOCK = Lock()
_PRODUCT_MARKET_PATH = re.compile(r"/api/product-v1/markets/([^/]+)")
_PRODUCT_OFFER_PATH = re.compile(r"/api/product-v1/markets/([^/]+)/offers")
_PRODUCT_CLOSE_PATH = re.compile(r"/api/product-v1/markets/([^/]+)/close")

_PRODUCT_ERROR_STATUSES = {
    ProductErrorCode.INVALID_REQUEST: HTTPStatus.BAD_REQUEST,
    ProductErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ProductErrorCode.MERCHANT_NOT_ELIGIBLE: HTTPStatus.FORBIDDEN,
    ProductErrorCode.MARKET_NOT_OPEN: HTTPStatus.CONFLICT,
    ProductErrorCode.OFFER_DEADLINE_PASSED: HTTPStatus.CONFLICT,
    ProductErrorCode.DUPLICATE_OFFER: HTTPStatus.CONFLICT,
    ProductErrorCode.MERCHANT_OFFER_REJECTED: HTTPStatus.UNPROCESSABLE_ENTITY,
    ProductErrorCode.OFFER_AUTHENTICATION_FAILED: HTTPStatus.INTERNAL_SERVER_ERROR,
    ProductErrorCode.CERTIFICATE_NOT_VERIFIED: HTTPStatus.INTERNAL_SERVER_ERROR,
    ProductErrorCode.PERSISTED_DATA_INVALID: HTTPStatus.INTERNAL_SERVER_ERROR,
}


def _live_result_status(payload: dict[str, object]) -> HTTPStatus:
    if payload["result"] == "SUCCESS":
        return HTTPStatus.OK
    if payload["result"] == "UNAVAILABLE":
        return HTTPStatus.SERVICE_UNAVAILABLE
    return HTTPStatus.BAD_GATEWAY


class _Handler(BaseHTTPRequestHandler):
    server_version = "CLEARUI/1.0"

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        requested = urlparse(self.path).path
        product_request = requested.startswith("/api/product-v1/")
        if not product_request and requested not in {
            "/api/authority-demo",
            "/api/ai-certificate-explanation-evidence",
            "/api/ai-merchant-proposal-evidence",
            "/api/razorpay-test-order-evidence",
        }:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "invalid content length"}, HTTPStatus.BAD_REQUEST)
            return
        if length < 0:
            self._send_json({"error": "invalid content length"}, HTTPStatus.BAD_REQUEST)
            return
        if length > 1024 * 1024:
            self._send_json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(length) if length else b""
        if product_request:
            self._handle_product_post(requested, body)
            return
        ai_endpoints = {
            "/api/ai-merchant-proposal-evidence": (
                build_ai_merchant_proposal_evidence,
                merchant_unavailable_presentation,
                "Merchant proposal",
            ),
            "/api/ai-certificate-explanation-evidence": (
                build_ai_certificate_explanation_evidence,
                explanation_unavailable_presentation,
                "Certificate explanation",
            ),
        }
        if requested in ai_endpoints:
            builder, unavailable, task_name = ai_endpoints[requested]
            if not _LIVE_AI_EVIDENCE_LOCK.acquire(blocking=False):
                self._send_json(
                    unavailable(
                        "LIVE_AI_BUSY",
                        "Another current-run AI evidence request is already running.",
                    ),
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                try:
                    payload = builder()
                except Exception:
                    payload = unavailable(
                        "LIVE_AI_INTERNAL_FAILURE",
                        f"The {task_name.lower()} evidence path failed closed.",
                    )
                    status = HTTPStatus.INTERNAL_SERVER_ERROR
                else:
                    status = _live_result_status(payload)
                self._send_json(payload, status)
            finally:
                _LIVE_AI_EVIDENCE_LOCK.release()
            return
        if requested == "/api/razorpay-test-order-evidence":
            if not _LIVE_EVIDENCE_LOCK.acquire(blocking=False):
                self._send_json(
                    unavailable_presentation(
                        "LIVE_EVIDENCE_BUSY",
                        "A Razorpay Test Mode evidence request is already running.",
                    ),
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                try:
                    payload = build_razorpay_test_order_evidence()
                except Exception:
                    payload = unavailable_presentation(
                        "LIVE_EVIDENCE_INTERNAL_FAILURE",
                        "The current-run Test Mode evidence path failed closed.",
                    )
                    status = HTTPStatus.INTERNAL_SERVER_ERROR
                else:
                    status = _live_result_status(payload)
                self._send_json(payload, status)
            finally:
                _LIVE_EVIDENCE_LOCK.release()
            return
        try:
            payload = build_authority_demo_presentation()
        except (PresentationError, RuntimeError, ValueError, TypeError) as error:
            self._send_json(
                {"error": "deterministic authority demo unavailable", "detail": str(error)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_json(payload)

    def _send_product_error(self, error: ProductServiceError) -> None:
        self._send_json(
            {"error": {"code": error.code.value, "message": "Product request failed closed."}},
            _PRODUCT_ERROR_STATUSES[error.code],
        )

    def _handle_product_post(self, requested: str, body: bytes) -> None:
        try:
            service = ProductService()
            if requested == "/api/product-v1/merchants":
                payload = service.create_merchant(parse_product_json(body, CreateMerchantRequest))
                self._send_json(payload, HTTPStatus.CREATED)
                return
            if requested == "/api/product-v1/markets":
                payload = service.create_market(parse_product_json(body, CreateMarketRequest))
                self._send_json(payload, HTTPStatus.CREATED)
                return
            offer_match = _PRODUCT_OFFER_PATH.fullmatch(requested)
            if offer_match is not None:
                payload = service.submit_offer(
                    offer_match.group(1),
                    parse_product_json(body, SubmitOfferRequest),
                )
                self._send_json(payload, HTTPStatus.CREATED)
                return
            close_match = _PRODUCT_CLOSE_PATH.fullmatch(requested)
            if close_match is not None:
                if body:
                    parse_product_json(body, CloseMarketRequest)
                self._send_json(service.close_market(close_match.group(1)))
                return
        except ProductRequestError:
            self._send_product_error(ProductServiceError(ProductErrorCode.INVALID_REQUEST))
            return
        except ProductServiceError as error:
            self._send_product_error(error)
            return
        except Exception:
            self._send_json(
                {
                    "error": {
                        "code": "PRODUCT_INTERNAL_FAILURE",
                        "message": "Product request failed closed.",
                    }
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        requested = urlparse(self.path).path
        if requested.startswith("/api/product-v1/"):
            market_match = _PRODUCT_MARKET_PATH.fullmatch(requested)
            if market_match is None:
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                payload = ProductService().get_market(market_match.group(1))
            except ProductServiceError as error:
                self._send_product_error(error)
                return
            except Exception:
                self._send_json(
                    {
                        "error": {
                            "code": "PRODUCT_INTERNAL_FAILURE",
                            "message": "Product request failed closed.",
                        }
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(payload)
            return
        relative = "index.html" if requested in ("/", "") else requested.removeprefix("/")
        candidate = (UI_ROOT / relative).resolve()
        if UI_ROOT not in candidate.parents and candidate != UI_ROOT:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        content_header = (
            f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type
        )
        self.send_header("Content-Type", content_header)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[clear-ui] {format % args}")


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Serve the CLEAR authority demo UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"CLEAR UI listening at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
