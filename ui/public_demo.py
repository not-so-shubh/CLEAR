"""Run the full CLEAR judge product as one public container process."""

from __future__ import annotations

import os
import sys

from ui.judge_demo import JudgeDemoSession, create_server, prepare_session

_PUBLIC_HOST = "0.0.0.0"
_DEFAULT_PORT = 8765
_FAILURE_EXIT = 2


def _port_from_environment(value: str | None) -> int:
    if value is None:
        return _DEFAULT_PORT
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("invalid PORT")
    port = int(value)
    if not 1 <= port <= 65_535:
        raise ValueError("invalid PORT")
    return port


def _print_failure(code: str) -> None:
    print(f"CLEAR public demo failed: {code}", file=sys.stderr, flush=True)


def _print_startup(session: JudgeDemoSession, *, port: int) -> None:
    print("CLEAR public demo ready", flush=True)
    print(f"Listen: http://{_PUBLIC_HOST}:{port}/#clearing", flush=True)
    print(f"Market: {session.market_id}", flush=True)
    print(f"State: {session.market_state}", flush=True)
    print(f"Offers: {session.submitted_offer_count} authenticated submissions", flush=True)
    print("AI: server configuration preserved; no startup call", flush=True)
    print("Razorpay Test Mode: server configuration preserved; no startup call", flush=True)
    print("Mode: shared ephemeral single-process sandbox", flush=True)


def run_public_demo(*, port: int) -> int:
    """Bootstrap one public demo session and serve it until stopped or failed."""
    try:
        session = prepare_session()
    except Exception:
        _print_failure("SESSION_PREPARATION_FAILED")
        return _FAILURE_EXIT

    try:
        os.environ["CLEAR_PRODUCT_DB_PATH"] = str(session.product_db_path)
    except Exception:
        _print_failure("SESSION_CONFIGURATION_FAILED")
        return _FAILURE_EXIT

    try:
        server = create_server(_PUBLIC_HOST, port)
    except Exception:
        _print_failure("SERVER_BIND_FAILED")
        return _FAILURE_EXIT

    _print_startup(session, port=port)
    serve_failed = False
    close_failed = False
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:
        serve_failed = True
    finally:
        try:
            server.server_close()
        except Exception:
            close_failed = True

    if serve_failed or close_failed:
        _print_failure("SERVER_RUNTIME_FAILED")
        return _FAILURE_EXIT
    print("CLEAR public demo stopped", flush=True)
    return 0


def main() -> int:
    try:
        port = _port_from_environment(os.environ.get("PORT"))
    except ValueError:
        _print_failure("INVALID_PORT")
        return _FAILURE_EXIT
    return run_public_demo(port=port)


if __name__ == "__main__":
    raise SystemExit(main())
