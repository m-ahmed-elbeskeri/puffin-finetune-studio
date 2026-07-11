"""Unit tests for the `finetune-copilot` launcher.

These cover the pure, deterministic helpers (port selection, readiness polling,
arg defaulting, doctor) without spawning real servers.
"""

from __future__ import annotations

import socket

import pytest
from copilot.backend import launcher


# --------------------------------------------------------------------------
# port selection
# --------------------------------------------------------------------------
def test_pick_port_returns_preferred_when_free():
    # Grab a free port from the OS, release it, then assert we pick it back.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert launcher._pick_port("127.0.0.1", free, label="test") == free


def test_pick_port_bumps_when_busy():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        chosen = launcher._pick_port("127.0.0.1", taken, label="test")
        assert chosen != taken
        assert taken < chosen <= taken + 50
        # And the chosen port is actually free.
        assert launcher._port_is_free("127.0.0.1", chosen)


def test_port_is_free_detects_listener():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert launcher._port_is_free("127.0.0.1", taken) is False


# --------------------------------------------------------------------------
# readiness polling
# --------------------------------------------------------------------------
def test_wait_until_true_immediately():
    assert launcher._wait_until(lambda: True, timeout=1.0) is True


def test_wait_until_times_out():
    assert launcher._wait_until(lambda: False, timeout=0.2, interval=0.05) is False


def test_wait_until_bails_when_process_dead():
    calls = {"n": 0}

    def check() -> bool:
        calls["n"] += 1
        return False

    # alive() is False from the start -> we should return immediately, without
    # ever calling check().
    assert launcher._wait_until(check, timeout=5.0, interval=0.01, alive=lambda: False) is False
    assert calls["n"] == 0


def test_http_ok_false_on_dead_port():
    # Nothing is listening on this ephemeral port.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert launcher._http_ok(f"http://127.0.0.1:{port}/healthz", timeout=0.3) is False


def test_http_ok_accepts_redirect(monkeypatch):
    # The frontend root returns 307 -> /dashboard; readiness must treat that as up.
    class _Resp:
        status = 307

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(launcher, "urlopen", lambda *a, **k: _Resp())
    assert launcher._http_ok("http://x/") is True


# --------------------------------------------------------------------------
# arg parsing / defaulting
# --------------------------------------------------------------------------
def test_bare_invocation_defaults_to_up(monkeypatch):
    # Drive main() itself so a regression in its "up"-defaulting is caught.
    captured = {}

    def fake_up(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(launcher, "cmd_up", fake_up)
    assert launcher.main([]) == 0
    assert captured["args"].func is fake_up
    assert captured["args"].prod is False


def test_leading_flags_default_to_up(monkeypatch):
    captured = {}

    def fake_up(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(launcher, "cmd_up", fake_up)
    # Leading flags (no subcommand) must still route to `up` via main().
    assert launcher.main(["--no-browser", "--prod"]) == 0
    args = captured["args"]
    assert args.no_browser is True
    assert args.prod is True


def test_subcommands_registered():
    parser = launcher._build_parser()
    for cmd, func in [
        ("up", launcher.cmd_up),
        ("build", launcher.cmd_build),
        ("doctor", launcher.cmd_doctor),
    ]:
        args = parser.parse_args([cmd])
        assert args.func is func


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------
def test_doctor_runs_and_returns_int():
    parser = launcher._build_parser()
    args = parser.parse_args(["doctor"])
    rc = launcher.cmd_doctor(args)
    assert rc in (0, 1)


# --------------------------------------------------------------------------
# environment wiring
# --------------------------------------------------------------------------
def test_base_env_sets_backend_url():
    env = launcher._base_env("http://localhost:9999")
    assert env["PUFFIN_COPILOT_BACKEND"] == "http://localhost:9999"
    assert env["PYTHONUTF8"] == "1"


def test_init_stdio_is_idempotent_and_safe():
    # Should never raise, even called twice.
    launcher._init_stdio()
    launcher._init_stdio()


def test_install_shutdown_signals_routes_sigterm(monkeypatch):
    import signal

    captured = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: captured.setdefault(sig, handler))
    launcher._install_shutdown_signals()
    assert signal.SIGTERM in captured
    # The handler must convert the signal into a KeyboardInterrupt so cmd_up's
    # `finally` teardown runs.
    with pytest.raises(KeyboardInterrupt):
        captured[signal.SIGTERM](signal.SIGTERM, None)


# --------------------------------------------------------------------------
# --prod single-origin serving (integration; needs a built static export)
# --------------------------------------------------------------------------
def _served_app(tmp_path):
    from copilot.backend.app import create_app
    from copilot.backend.settings import Settings
    from starlette.testclient import TestClient

    return TestClient(
        create_app(
            settings=Settings(
                anthropic_api_key="",
                repo_root=launcher.REPO_ROOT,
                db_path=tmp_path / "threads.sqlite3",
                frontend_dist=launcher.STATIC_OUT,
            )
        )
    )


@pytest.mark.skipif(
    not (launcher.STATIC_OUT / "dashboard" / "index.html").exists(),
    reason="static export not built (run `finetune-copilot build`)",
)
def test_prod_landing_is_not_error_shell(tmp_path):
    """The page --prod actually opens must be the real dashboard, never Next's
    `__next_error__` shell. This is the regression guard for the root-redirect
    bug the reviewer caught."""
    with _served_app(tmp_path) as client:
        # This is exactly the URL cmd_up opens in prod.
        r = client.get("/dashboard/")
        assert r.status_code == 200
        assert "__next_error__" not in r.text
        assert "Puffin Studio" in r.text

        # And a hard load of "/" must also be a clean document, not the shell.
        root = client.get("/", follow_redirects=True)
        assert "__next_error__" not in root.text


@pytest.mark.skipif(
    not (launcher.STATIC_OUT / "index.html").exists(), reason="static export not built"
)
def test_prod_disables_api_docs(tmp_path):
    """With the frontend mounted, FastAPI's Swagger/OpenAPI must be off so it
    neither collides with the app's /docs page nor leaks the schema."""
    with _served_app(tmp_path) as client:
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/healthz").status_code == 200  # API still works
