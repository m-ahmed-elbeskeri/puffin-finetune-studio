"""Start/stop the local serving app (llmops.serving.app) from the UI.

Spawns the same OpenAI-compatible serving server the CLI runs, on :8089 where
the Playground and health checks already look. State (pid, port, backend, log)
lives in artifacts/copilot/serving.json so status survives a UI reload. The
`transformers` backend loads the real model + adapter from configs/deploy.yaml;
`vllm` uses the vLLM image for high-throughput serving.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8089


class ServingError(RuntimeError):
    """Bad serving request; maps to HTTP 400."""


def _state_path(repo_root: Path) -> Path:
    return Path(repo_root) / "artifacts" / "copilot" / "serving.json"


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True


def _port_pid(port: int) -> int | None:
    """PID listening on a local port, or None. Best-effort (may need psutil)."""
    try:
        import psutil
        for c in psutil.net_connections(kind="inet"):
            try:
                if (c.status == psutil.CONN_LISTEN and c.laddr
                        and c.laddr.port == port):
                    return c.pid
            except (AttributeError, ValueError):
                continue
    except Exception:  # noqa: BLE001 - psutil perms/platform; skip the check
        return None
    return None


async def _await_port_free(port: int, timeout: float = 5.0) -> None:
    for _ in range(int(timeout * 4)):
        if _port_pid(port) is None:
            return
        await asyncio.sleep(0.25)


def _kill(pid: int) -> None:
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_state(repo_root: Path) -> dict[str, Any]:
    """Current serving state: whether our managed process is alive + its info."""
    p = _state_path(repo_root)
    base = {"kind": "serving_status", "running": False, "port": DEFAULT_PORT,
            "url": f"http://127.0.0.1:{DEFAULT_PORT}"}
    if not p.exists():
        return base
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    st["kind"] = "serving_status"
    st["running"] = _pid_alive(st.get("pid"))
    st.setdefault("port", DEFAULT_PORT)
    st.setdefault("url", f"http://127.0.0.1:{st['port']}")
    return st


async def start(
    repo_root: Path, *, backend: str = "transformers",
    port: int = DEFAULT_PORT, config: str = "configs/deploy.yaml",
) -> dict[str, Any]:
    """Spawn the serving app. Idempotent: if it's already up, returns as-is."""
    if backend not in {"transformers", "vllm"}:
        raise ServingError(f"unknown serving backend: {backend!r}")

    # Restart semantics: if we already manage a server, stop it first so Start
    # doubles as "switch backend / restart" instead of colliding on the port.
    cur = read_state(repo_root)
    if cur.get("running") and isinstance(cur.get("pid"), int):
        _kill(int(cur["pid"]))
        _clear(repo_root)
        await _await_port_free(port)

    # Don't spawn into a bind failure. If a stale copy of OUR serving app still
    # holds the port, reclaim it; if it's a foreign process, say so clearly.
    holder = _port_pid(port)
    if holder is not None:
        if _is_our_serving(holder):
            _kill(holder)
            await _await_port_free(port)
        else:
            raise ServingError(
                f"Port {port} is already in use by PID {holder} (not a Puffin "
                "serving process). Free that port or pick another.")

    cfg = (Path(repo_root) / config).resolve()
    if not cfg.exists():
        raise ServingError(f"config not found: {config}")

    logs = repo_root / "artifacts" / "copilot" / "serving-logs"
    logs.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = logs / f"serving_{ts}.log"

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PUFFIN_SERVE_BACKEND"] = backend
    env["PUFFIN_SERVE_HOST"] = "127.0.0.1"
    env["PUFFIN_SERVE_PORT"] = str(port)

    cmd = [sys.executable, "-m", "llmops.serving.app",
           "--config", str(cfg), "--host", "127.0.0.1", "--port", str(port)]

    fh = log_path.open("wb")
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(repo_root), env=env,
        stdout=fh, stderr=asyncio.subprocess.STDOUT,
        start_new_session=os.name != "nt")
    proc._puffin_log_fh = fh  # type: ignore[attr-defined]

    rel = str(log_path.relative_to(repo_root)).replace("\\", "/")
    state = {
        "kind": "serving_status", "running": True, "pid": proc.pid,
        "port": port, "backend": backend, "config": config,
        "url": f"http://127.0.0.1:{port}", "started_at": _now(),
        "log_path": rel,
    }
    sp = _state_path(repo_root)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {
        **state,
        "message": (
            f"Serving started on :{port} with the {backend} backend (PID "
            f"{proc.pid}). The model is loading; give it a moment before chatting."
        ),
    }


def _is_our_serving(pid: Any) -> bool:
    """True only if the process is our serving app — so we never kill a
    foreign process that happens to hold the port."""
    if not isinstance(pid, int):
        return False
    try:
        import psutil
        return "llmops.serving.app" in " ".join(psutil.Process(pid).cmdline())
    except Exception:  # noqa: BLE001 - process gone / no perms
        return False


def stop(repo_root: Path) -> dict[str, Any]:
    """Terminate the managed serving process."""
    st = read_state(repo_root)
    pid = st.get("pid")
    if not st.get("running") or not isinstance(pid, int) or not _pid_alive(pid):
        _clear(repo_root)
        return {"kind": "serving_stop", "stopped": False,
                "message": "Serving isn't running."}
    _kill(pid)
    _clear(repo_root)
    return {"kind": "serving_stop", "stopped": True,
            "message": f"Stopped serving (PID {pid})."}


def _clear(repo_root: Path) -> None:
    p = _state_path(repo_root)
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


def read_log(repo_root: Path, *, tail: int = 300) -> dict[str, Any]:
    """Tail the serving process log so model-load progress and errors (the
    transformers backend especially) are visible in-app."""
    repo = Path(repo_root)
    log: Path | None = None
    rel = read_state(repo).get("log_path")
    if rel:
        cand = repo / rel
        if cand.exists():
            log = cand
    if log is None:
        logs = repo / "artifacts" / "copilot" / "serving-logs"
        found = sorted(logs.glob("serving_*.log")) if logs.exists() else []
        if found:
            log = found[-1]
    if log is None:
        return {"kind": "serving_log", "present": False, "lines": [],
                "message": "No serving log yet. Start serving first."}
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"kind": "serving_log", "present": False, "lines": [],
                "message": f"Couldn't read log: {exc}"}
    lines = text.splitlines()
    tail = max(1, min(2000, tail))
    return {
        "kind": "serving_log", "present": True,
        "log_path": str(log.relative_to(repo)).replace("\\", "/"),
        "total_lines": len(lines), "lines": lines[-tail:],
    }
