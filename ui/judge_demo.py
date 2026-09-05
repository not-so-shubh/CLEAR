"""Start an isolated, provider-disabled CLEAR judge rehearsal."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_SESSION_PREFIX = "clear-judge-demo-"
_PROVIDER_ENVIRONMENT_VARIABLES = (
    "CLEAR_AI_BASE_URL",
    "CLEAR_AI_API_KEY",
    "CLEAR_AI_PROVIDER_NAME",
    "CLEAR_AI_MODELS",
    "RAZORPAY_TEST_KEY_ID",
    "RAZORPAY_TEST_KEY_SECRET",
)


class _Bootstrap(Protocol):
    def __call__(self, db_path: Path) -> dict[str, object]: ...


class _Server(Protocol):
    def serve_forever(self) -> None: ...

    def server_close(self) -> None: ...


class _ServerFactory(Protocol):
    def __call__(self, host: str, port: int) -> _Server: ...


def _load_orchestration_boundaries() -> tuple[_Bootstrap, _ServerFactory]:
    bootstrap_module = importlib.import_module("ui.demo_bootstrap")
    server_module = importlib.import_module("ui.server")
    return (
        cast(_Bootstrap, bootstrap_module.bootstrap_demo),
        cast(_ServerFactory, server_module.create_server),
    )


bootstrap_demo, create_server = _load_orchestration_boundaries()


@dataclass(frozen=True)
class JudgeDemoSession:
    session_dir: Path
    product_db_path: Path
    market_id: str
    market_state: str
    submitted_offer_count: int


def prepare_session() -> JudgeDemoSession:
    """Create and bootstrap one new rehearsal session without cleanup."""
    session_dir = Path(tempfile.mkdtemp(prefix=_SESSION_PREFIX)).absolute()
    product_db_path = session_dir / "product.sqlite3"
    metadata = bootstrap_demo(product_db_path)
    market_id = metadata.get("market_id")
    market_state = metadata.get("market_state")
    submitted_offer_count = metadata.get("submitted_offer_count")
    if (
        type(market_id) is not str
        or market_state != "OPEN"
        or type(submitted_offer_count) is not int
        or submitted_offer_count != 2
    ):
        raise RuntimeError("bootstrap metadata failed closed")
    return JudgeDemoSession(
        session_dir=session_dir,
        product_db_path=product_db_path,
        market_id=market_id,
        market_state=market_state,
        submitted_offer_count=submitted_offer_count,
    )


def configure_process_environment(product_db_path: Path) -> None:
    """Point this process at its session and remove provider configuration."""
    os.environ["CLEAR_PRODUCT_DB_PATH"] = str(product_db_path)
    for variable in _PROVIDER_ENVIRONMENT_VARIABLES:
        os.environ.pop(variable, None)


def _print_startup(session: JudgeDemoSession, *, host: str, port: int) -> None:
    print("CLEAR judge demo ready", flush=True)
    print(f"URL: http://{host}:{port}/#clearing", flush=True)
    print(f"Session: {session.session_dir}", flush=True)
    print(f"Market: {session.market_id}", flush=True)
    print(f"State: {session.market_state}", flush=True)
    print(f"Offers: {session.submitted_offer_count} authenticated submissions", flush=True)
    print("AI: disabled for this rehearsal", flush=True)
    print("Razorpay: disabled for this rehearsal", flush=True)
    print("Next: open Clearing and explicitly close the market", flush=True)


def _print_failure(code: str, session: JudgeDemoSession | None = None) -> None:
    message = f"CLEAR judge demo failed: {code}"
    if session is not None:
        message = f"{message}. Session preserved at: {session.session_dir}"
    print(message, file=sys.stderr, flush=True)


def run_judge_demo(*, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT) -> int:
    """Prepare one session and serve it until stopped or failed."""
    try:
        session = prepare_session()
    except Exception:
        _print_failure("SESSION_PREPARATION_FAILED")
        return 2

    configure_process_environment(session.product_db_path)
    try:
        server = create_server(host, port)
    except Exception:
        _print_failure("SERVER_BIND_FAILED", session)
        return 2

    _print_startup(session, host=host, port=port)
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
        _print_failure("SERVER_RUNTIME_FAILED", session)
        return 2
    print(f"CLEAR judge demo stopped. Session preserved at: {session.session_dir}", flush=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start an isolated CLEAR judge rehearsal")
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_judge_demo(host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
