"""Secure standard-library HTTP boundary for the CLEAR presentation."""

import argparse
import ipaddress
import json
import os
import sys
import threading
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit

from ui.presentation import build_demo_presentation_v1

_UI_DIRECTORY: Final[Path] = Path(__file__).resolve().parent
_STATIC_ROUTES: Final = MappingProxyType(
    {
        "/": (_UI_DIRECTORY / "index.html", "text/html; charset=utf-8"),
        "/app.js": (_UI_DIRECTORY / "app.js", "text/javascript; charset=utf-8"),
        "/styles.css": (_UI_DIRECTORY / "styles.css", "text/css; charset=utf-8"),
    }
)
_KNOWN_ROUTES: Final[frozenset[str]] = frozenset(
    {"/", "/app.js", "/styles.css", "/api/demo", "/healthz"}
)
_CONTENT_SECURITY_POLICY: Final[str] = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
_DEMO_EXECUTION_LOCK: Final = threading.Lock()


class PresentationRequestHandler(BaseHTTPRequestHandler):
    """Serve only the allowlisted presentation routes."""

    server_version = "CLEARPresentation"
    sys_version = ""

    def do_GET(self) -> None:
        route = self._route()
        if route in _STATIC_ROUTES:
            path, content_type = _STATIC_ROUTES[route]
            self._send_static(path, content_type, include_body=True)
            return
        if route == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if route == "/api/demo":
            if self._demo_request_is_invalid():
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
                return
            self._send_demo()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_HEAD(self) -> None:
        route = self._route()
        if route in _STATIC_ROUTES:
            path, content_type = _STATIC_ROUTES[route]
            self._send_static(path, content_type, include_body=False)
            return
        if route == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"}, include_body=False)
            return
        if route == "/api/demo":
            self._send_method_not_allowed()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, include_body=False)

    def do_POST(self) -> None:
        self._send_route_or_method_error()

    def do_PUT(self) -> None:
        self._send_route_or_method_error()

    def do_PATCH(self) -> None:
        self._send_route_or_method_error()

    def do_DELETE(self) -> None:
        self._send_route_or_method_error()

    def do_OPTIONS(self) -> None:
        self._send_route_or_method_error()

    def do_TRACE(self) -> None:
        self._send_route_or_method_error()

    def do_CONNECT(self) -> None:
        self._send_route_or_method_error()

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        if code == HTTPStatus.NOT_IMPLEMENTED:
            self._send_route_or_method_error()
            return
        super().send_error(code, message, explain)

    def log_message(self, _format: str, *_args: object) -> None:
        """Suppress BaseHTTPRequestHandler's raw request-target logging."""

    def _route(self) -> str:
        return urlsplit(self.path).path

    def _demo_request_is_invalid(self) -> bool:
        if urlsplit(self.path).query:
            return True
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            return False
        try:
            return int(content_length) != 0
        except ValueError:
            return True

    def _route_for_log(self) -> str:
        route = self._route()
        return route if route in _KNOWN_ROUTES else "rejected-route"

    def _record_request(self, status: HTTPStatus) -> None:
        print(
            f"{self.command} {self._route_for_log()} {status.value}",
            file=sys.stderr,
            flush=True,
        )

    def _send_headers(
        self,
        status: HTTPStatus,
        *,
        content_type: str,
        content_length: int,
        cache_control: str,
        allow: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        if allow is not None:
            self.send_header("Allow", allow)
        self.end_headers()
        self._record_request(status)

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        *,
        content_type: str,
        cache_control: str,
        include_body: bool = True,
        allow: str | None = None,
    ) -> None:
        self._send_headers(
            status,
            content_type=content_type,
            content_length=len(body),
            cache_control=cache_control,
            allow=allow,
        )
        if include_body:
            self.wfile.write(body)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, object],
        *,
        include_body: bool = True,
        allow: str | None = None,
    ) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self._send_bytes(
            status,
            body,
            content_type="application/json; charset=utf-8",
            cache_control="no-store",
            include_body=include_body,
            allow=allow,
        )

    def _send_static(self, path: Path, content_type: str, *, include_body: bool) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "static_unavailable"},
                include_body=include_body,
            )
            return
        self._send_bytes(
            HTTPStatus.OK,
            body,
            content_type=content_type,
            cache_control="no-cache",
            include_body=include_body,
        )

    def _send_demo(self) -> None:
        try:
            with _DEMO_EXECUTION_LOCK:
                payload = build_demo_presentation_v1()
        except Exception:  # The public API deliberately sanitizes all demo failures.
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "demo_unavailable"})
            return
        self._send_json(HTTPStatus.OK, payload)

    def _send_method_not_allowed(self) -> None:
        route = self._route()
        allow = "GET, HEAD" if route != "/api/demo" else "GET"
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": "method_not_allowed"},
            include_body=self.command != "HEAD",
            allow=allow,
        )

    def _send_route_or_method_error(self) -> None:
        if self._route() not in _KNOWN_ROUTES:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._send_method_not_allowed()


def _host(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as error:
        raise argparse.ArgumentTypeError(
            "host must be a valid IPv4 address such as 127.0.0.1 or 0.0.0.0"
        ) from error


def _port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local CLEAR authority demo")
    parser.add_argument("--host", type=_host, default="127.0.0.1")
    parser.add_argument("--port", type=_port)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.port is not None:
        port = arguments.port
    else:
        try:
            port = _port(os.environ.get("PORT", "8000"))
        except argparse.ArgumentTypeError as error:
            parser.error(f"invalid PORT environment variable: {error}")
    try:
        server = ThreadingHTTPServer((arguments.host, port), PresentationRequestHandler)
    except OSError as error:
        raise SystemExit(f"unable to bind presentation server: {error}") from error
    print(f"CLEAR presentation listening on http://{arguments.host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
