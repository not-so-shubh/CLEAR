"""Small standard-library server for the CLEAR static judge UI."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from .presentation import PresentationError, build_authority_demo_presentation
from .razorpay_evidence import (
    build_razorpay_test_order_evidence,
    unavailable_presentation,
)

UI_ROOT = Path(__file__).resolve().parent
_LIVE_EVIDENCE_LOCK = Lock()


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
        if requested not in {
            "/api/authority-demo",
            "/api/razorpay-test-order-evidence",
        }:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            self._send_json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        if length:
            self.rfile.read(length)
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
                    if payload["result"] == "SUCCESS":
                        status = HTTPStatus.OK
                    elif payload["result"] == "UNAVAILABLE":
                        status = HTTPStatus.SERVICE_UNAVAILABLE
                    else:
                        status = HTTPStatus.BAD_GATEWAY
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

    def do_GET(self) -> None:
        requested = urlparse(self.path).path
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
