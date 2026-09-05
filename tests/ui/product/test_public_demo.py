from __future__ import annotations

import http.client
import os
from collections.abc import Callable
from pathlib import Path

import pytest

import ui.judge_demo as judge_demo
import ui.public_demo as public_demo
from ui.demo_bootstrap import financial_ledger_path_for_product_db
from ui.product.service import ProductService

_PROVIDER_ENVIRONMENT = {
    "CLEAR_AI_BASE_URL": "https://provider-value-must-not-print.invalid/v1",
    "CLEAR_AI_API_KEY": "public-ai-secret-must-not-print",
    "CLEAR_AI_PROVIDER_NAME": "public-provider-must-not-print",
    "CLEAR_AI_MODELS": "public-model-must-not-print",
    "RAZORPAY_TEST_KEY_ID": "public-razorpay-id-must-not-print",
    "RAZORPAY_TEST_KEY_SECRET": "public-razorpay-secret-must-not-print",
}


class _InterruptingServer:
    def __init__(self) -> None:
        self.serve_calls = 0
        self.close_calls = 0

    def serve_forever(self) -> None:
        self.serve_calls += 1
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.close_calls += 1


class _FailingServer(_InterruptingServer):
    def serve_forever(self) -> None:
        self.serve_calls += 1
        raise RuntimeError("runtime detail must not print")


def _session(tmp_path: Path) -> judge_demo.JudgeDemoSession:
    session_dir = tmp_path / "public-session"
    session_dir.mkdir()
    return judge_demo.JudgeDemoSession(
        session_dir=session_dir,
        product_db_path=session_dir / "product.sqlite3",
        market_id="00000000-0000-4000-8000-000000000001",
        market_state="OPEN",
        submitted_offer_count=2,
    )


def _temp_directory_factory(session_dir: Path) -> Callable[..., str]:
    def create(*, prefix: str) -> str:
        assert prefix == "clear-judge-demo-"
        session_dir.mkdir()
        return str(session_dir)

    return create


def test_absent_port_uses_local_container_default(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[int] = []
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(
        public_demo,
        "run_public_demo",
        lambda *, port: received.append(port) or 0,
    )

    assert public_demo.main() == 0
    assert received == [8765]


@pytest.mark.parametrize("configured_port", ["1", "8765", "49152", "65535"])
def test_valid_port_passes_exactly(
    configured_port: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[int] = []
    monkeypatch.setenv("PORT", configured_port)
    monkeypatch.setattr(
        public_demo,
        "run_public_demo",
        lambda *, port: received.append(port) or 0,
    )

    assert public_demo.main() == 0
    assert received == [int(configured_port)]


@pytest.mark.parametrize(
    "invalid_port",
    [
        "",
        "not-an-integer",
        "0",
        "-1",
        "+8765",
        "65536",
        " 8765",
        "8765 ",
        "\uff18\uff17\uff16\uff15",
    ],
)
def test_invalid_port_fails_closed(
    invalid_port: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0

    def unexpected_run(*, port: int) -> int:
        nonlocal calls
        calls += 1
        return port

    monkeypatch.setenv("PORT", invalid_port)
    monkeypatch.setattr(public_demo, "run_public_demo", unexpected_run)

    assert public_demo.main() == 2
    assert calls == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CLEAR public demo failed: INVALID_PORT\n"
    if invalid_port:
        assert invalid_port not in captured.err


def test_main_propagates_runner_return_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8765")
    monkeypatch.setattr(public_demo, "run_public_demo", lambda *, port: 7 if port == 8765 else 9)

    assert public_demo.main() == 7


def test_public_runner_binds_all_interfaces_and_preserves_provider_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _session(tmp_path)
    server = _InterruptingServer()
    received: list[tuple[str, int]] = []
    environment_at_bind: dict[str, str] = {}
    for name, value in _PROVIDER_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("provider network access during startup")

    def server_factory(host: str, port: int) -> _InterruptingServer:
        received.append((host, port))
        environment_at_bind.update(os.environ)
        return server

    monkeypatch.setattr(http.client, "HTTPSConnection", no_network)
    monkeypatch.setattr(public_demo, "prepare_session", lambda: session)
    monkeypatch.setattr(public_demo, "create_server", server_factory)

    assert public_demo.run_public_demo(port=43210) == 0

    assert received == [("0.0.0.0", 43210)]
    assert server.serve_calls == 1
    assert server.close_calls == 1
    assert os.environ["CLEAR_PRODUCT_DB_PATH"] == str(session.product_db_path)
    for name, value in _PROVIDER_ENVIRONMENT.items():
        assert os.environ[name] == value
        assert environment_at_bind[name] == value

    captured = capsys.readouterr()
    assert "AI: server configuration preserved; no startup call" in captured.out
    assert "Razorpay Test Mode: server configuration preserved; no startup call" in captured.out
    for value in _PROVIDER_ENVIRONMENT.values():
        assert value not in captured.out
        assert value not in captured.err


def test_public_runner_uses_fresh_reviewed_bootstrap_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dir = tmp_path / "fresh-public-session"
    server = _InterruptingServer()
    monkeypatch.setattr(
        judge_demo.tempfile,
        "mkdtemp",
        _temp_directory_factory(session_dir),
    )
    monkeypatch.setattr(public_demo, "create_server", lambda _host, _port: server)

    assert public_demo.run_public_demo(port=8765) == 0

    product_db_path = session_dir / "product.sqlite3"
    ledger_path = financial_ledger_path_for_product_db(product_db_path)
    service = ProductService(product_db_path)
    markets = service.list_markets()["markets"]
    assert isinstance(markets, list)
    assert len(markets) == 1
    market_id = str(markets[0]["market_id"])
    snapshot = service.get_clearing_snapshot(market_id)
    assert snapshot["market"]["state"] == "OPEN"
    assert snapshot["result"] is None
    assert len(snapshot["submitted_offers"]) == 2
    assert not ledger_path.exists()
    assert os.environ["CLEAR_PRODUCT_DB_PATH"] == str(product_db_path)


@pytest.mark.parametrize("failure", ["bind", "serve", "close"])
def test_server_failures_return_bounded_error(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _session(tmp_path)
    secret = "server-failure-secret-must-not-print"
    monkeypatch.setenv("CLEAR_AI_API_KEY", secret)
    monkeypatch.setattr(public_demo, "prepare_session", lambda: session)
    if failure == "bind":
        monkeypatch.setattr(
            public_demo,
            "create_server",
            lambda _host, _port: (_ for _ in ()).throw(RuntimeError("unsafe bind detail")),
        )
    else:
        server = _FailingServer() if failure == "serve" else _InterruptingServer()
        if failure == "close":
            server.server_close = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
                RuntimeError("unsafe close detail")
            )
        monkeypatch.setattr(public_demo, "create_server", lambda _host, _port: server)

    assert public_demo.run_public_demo(port=8765) == 2

    captured = capsys.readouterr()
    expected_code = "SERVER_BIND_FAILED" if failure == "bind" else "SERVER_RUNTIME_FAILED"
    assert expected_code in captured.err
    assert secret not in captured.out
    assert secret not in captured.err
    assert "unsafe" not in captured.err


def test_judge_demo_provider_disabled_environment_behavior_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _PROVIDER_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    judge_demo.configure_process_environment(tmp_path / "judge-product.sqlite3")

    assert os.environ["CLEAR_PRODUCT_DB_PATH"] == str(tmp_path / "judge-product.sqlite3")
    for name in _PROVIDER_ENVIRONMENT:
        assert name not in os.environ


def test_source_reuses_reviewed_orchestration_without_provider_actions() -> None:
    source = Path("ui/public_demo.py").read_text(encoding="utf-8")

    assert "from ui.judge_demo import JudgeDemoSession, create_server, prepare_session" in source
    assert "run_judge_demo" not in source
    assert ".env.local" not in source
    assert "load_dotenv" not in source
    for forbidden in (
        "ProductService",
        "bootstrap_demo",
        "allocate_market_v2",
        "build_allocation_certificate_v2",
        "authorize_execution_v1",
        "create_razorpay_test_order_v1",
        "interpret_buyer_intent_v1",
        "propose_merchant_offer_candidate_v1",
    ):
        assert forbidden not in source
