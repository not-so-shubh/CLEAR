from __future__ import annotations

import os
from pathlib import Path

import pytest

import ui.judge_demo as judge_demo
from ui.demo_bootstrap import financial_ledger_path_for_product_db
from ui.product.service import ProductService


class _InterruptingServer:
    def __init__(self) -> None:
        self.serve_calls = 0
        self.close_calls = 0

    def serve_forever(self) -> None:
        self.serve_calls += 1
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.close_calls += 1


def _temp_directory_factory(session_dir: Path):
    def create(*, prefix: str) -> str:
        assert prefix == "clear-judge-demo-"
        session_dir.mkdir()
        return str(session_dir)

    return create


def _prepare_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> judge_demo.JudgeDemoSession:
    session_dir = tmp_path / "clear-judge-demo-session"
    monkeypatch.setattr(
        judge_demo.tempfile,
        "mkdtemp",
        _temp_directory_factory(session_dir),
    )
    return judge_demo.prepare_session()


def test_prepare_session_creates_only_an_open_bootstrapped_market(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _prepare_in(tmp_path, monkeypatch)
    ledger_path = financial_ledger_path_for_product_db(session.product_db_path)
    service = ProductService(session.product_db_path)

    assert session.session_dir.name == "clear-judge-demo-session"
    assert session.product_db_path == session.session_dir / "product.sqlite3"
    assert session.product_db_path.is_file()
    assert not ledger_path.exists()
    assert session.market_state == "OPEN"
    assert session.submitted_offer_count == 2

    snapshot = service.get_clearing_snapshot(session.market_id)
    assert snapshot["market"]["state"] == "OPEN"
    assert snapshot["result"] is None
    offers = snapshot["submitted_offers"]
    assert isinstance(offers, list)
    assert len(offers) == 2
    assert all(offer["signed"] is True and offer["authenticated"] is True for offer in offers)
    assert {(offer["display_name"], offer["unit_price_paise"]) for offer in offers} == {
        ("Alpha Systems", 45_000),
        ("Beta Systems", 50_000),
    }


def test_runner_isolates_environment_and_never_prints_seeded_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_dir = tmp_path / "isolated-session"
    monkeypatch.setattr(
        judge_demo.tempfile,
        "mkdtemp",
        _temp_directory_factory(session_dir),
    )
    seeded = {
        "CLEAR_PRODUCT_DB_PATH": "old-product-path-do-not-print",
        "CLEAR_AI_BASE_URL": "https://provider-value-do-not-print.invalid",
        "CLEAR_AI_API_KEY": "fake-ai-key-do-not-print",
        "CLEAR_AI_PROVIDER_NAME": "fake-provider-do-not-print",
        "CLEAR_AI_MODELS": "fake-model-do-not-print",
        "RAZORPAY_TEST_KEY_ID": "fake-razorpay-id-do-not-print",
        "RAZORPAY_TEST_KEY_SECRET": "fake-razorpay-secret-do-not-print",
    }
    for name, value in seeded.items():
        monkeypatch.setenv(name, value)
    server = _InterruptingServer()
    environment_at_server_start: dict[str, str] = {}

    def server_factory(_host: str, _port: int) -> _InterruptingServer:
        environment_at_server_start.update(os.environ)
        return server

    monkeypatch.setattr(judge_demo, "create_server", server_factory)

    assert judge_demo.run_judge_demo() == 0

    assert os.environ["CLEAR_PRODUCT_DB_PATH"] == str(session_dir / "product.sqlite3")
    for variable in seeded.keys() - {"CLEAR_PRODUCT_DB_PATH"}:
        assert variable not in os.environ
        assert variable not in environment_at_server_start
    assert environment_at_server_start["CLEAR_PRODUCT_DB_PATH"] == str(
        session_dir / "product.sqlite3"
    )
    captured = capsys.readouterr()
    for value in seeded.values():
        assert value not in captured.out
        assert value not in captured.err


def test_host_and_port_defaults_and_overrides_pass_through_exactly() -> None:
    defaults = judge_demo._parser().parse_args([])
    overridden = judge_demo._parser().parse_args(["--host", "127.0.0.2", "--port", "9876"])

    assert (defaults.host, defaults.port) == ("127.0.0.1", 8765)
    assert (overridden.host, overridden.port) == ("127.0.0.2", 9876)


def test_ctrl_c_closes_once_and_preserves_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_dir = tmp_path / "interrupt-session"
    monkeypatch.setattr(
        judge_demo.tempfile,
        "mkdtemp",
        _temp_directory_factory(session_dir),
    )
    server = _InterruptingServer()
    received: list[tuple[str, int]] = []

    def server_factory(host: str, port: int) -> _InterruptingServer:
        received.append((host, port))
        return server

    monkeypatch.setattr(judge_demo, "create_server", server_factory)

    assert judge_demo.run_judge_demo(host="127.0.0.2", port=9876) == 0

    assert received == [("127.0.0.2", 9876)]
    assert server.serve_calls == 1
    assert server.close_calls == 1
    assert session_dir.is_dir()
    assert (session_dir / "product.sqlite3").is_file()
    assert "CLEAR judge demo stopped. Session preserved at:" in capsys.readouterr().out


def test_bind_failure_is_safe_and_preserves_bootstrapped_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_dir = tmp_path / "bind-failure-session"
    monkeypatch.setattr(
        judge_demo.tempfile,
        "mkdtemp",
        _temp_directory_factory(session_dir),
    )
    secret = "bind-secret-must-not-print"
    monkeypatch.setenv("RAZORPAY_TEST_KEY_SECRET", secret)

    def failing_server(_host: str, _port: int) -> None:
        raise OSError("unsafe provider detail must not be printed")

    monkeypatch.setattr(judge_demo, "create_server", failing_server)

    assert judge_demo.run_judge_demo() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SERVER_BIND_FAILED" in captured.err
    assert str(session_dir) in captured.err
    assert secret not in captured.err
    assert "unsafe provider detail" not in captured.err
    assert session_dir.is_dir()
    assert (session_dir / "product.sqlite3").is_file()


def test_startup_output_is_bounded_and_points_directly_to_clearing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_dir = tmp_path / "output-session"
    monkeypatch.setattr(
        judge_demo.tempfile,
        "mkdtemp",
        _temp_directory_factory(session_dir),
    )
    monkeypatch.setattr(judge_demo, "create_server", lambda _host, _port: _InterruptingServer())

    assert judge_demo.run_judge_demo() == 0

    output = capsys.readouterr().out
    assert "CLEAR judge demo ready" in output
    assert "URL: http://127.0.0.1:8765/#clearing" in output
    assert "State: OPEN" in output
    assert "Offers: 2 authenticated submissions" in output
    assert "AI: disabled for this rehearsal" in output
    assert "Razorpay: disabled for this rehearsal" in output
    assert "Next: open Clearing and explicitly close the market" in output
    for forbidden in (
        "winner",
        "allocation",
        "certificate",
        "payment",
        "private key",
        "credential",
    ):
        assert forbidden not in output.lower()


def test_source_uses_only_reviewed_bootstrap_and_server_boundaries() -> None:
    source = Path("ui/judge_demo.py").read_text(encoding="utf-8")

    assert 'importlib.import_module("ui.demo_bootstrap")' in source
    assert "bootstrap_module.bootstrap_demo" in source
    assert 'importlib.import_module("ui.server")' in source
    assert "server_module.create_server" in source
    assert "HTTPServer" not in source
    assert ".env.local" not in source
    assert "load_dotenv" not in source
    assert "TemporaryDirectory" not in source
    assert "rmtree" not in source
    assert ".unlink(" not in source
    for forbidden in (
        "ProductService",
        "allocate_market_v2",
        "build_allocation_certificate_v2",
        "authorize_execution_v1",
        "create_razorpay_test_order_v1",
        "recover_razorpay_test_order_v1",
        "interpret_buyer_intent_v1",
        "propose_merchant_offer_candidate_v1",
    ):
        assert forbidden not in source
