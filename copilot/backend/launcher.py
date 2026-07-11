"""`finetune-copilot` - one command that opens the Puffin Studio web UI.

This is the friendly front door to the whole platform. Typing::

    finetune-copilot

starts the FastAPI backend, brings up the Next.js frontend, waits until both
are actually serving, and opens your browser at the dashboard. Ctrl+C tears
everything down cleanly.

Two serving modes:

* **dev** (default): runs the Next.js dev server (hot reload) on its own port
  and proxies ``/api`` to the backend. Requires Node.js. This is what you want
  while iterating on the UI.
* **prod** (``--prod``): serves a pre-built static export of the frontend
  directly from the FastAPI process - a single port, no Node.js needed at
  runtime. Build the export once with ``finetune-copilot build``.

Subcommands::

    finetune-copilot            # = `up`: launch and open the browser
    finetune-copilot up         # explicit
    finetune-copilot build      # static-export the frontend for --prod
    finetune-copilot doctor     # preflight: node, deps, ports, API key
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import psutil

# --------------------------------------------------------------------------
# Paths & small terminal helpers
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "copilot" / "frontend"
STATIC_OUT = FRONTEND_DIR / "out"

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _init_stdio() -> None:
    """Force UTF-8 output so status glyphs survive a redirected/cp1252 console
    (the default on Windows). errors='replace' means we never crash on output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def info(msg: str) -> None:
    print(f"{_c('36', '==>')} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{_c('33', 'warning:')} {msg}", file=sys.stderr, flush=True)


def die(msg: str, code: int = 1) -> int:
    print(f"{_c('31', 'error:')} {msg}", file=sys.stderr, flush=True)
    return code


# --------------------------------------------------------------------------
# Networking helpers
# --------------------------------------------------------------------------
def _port_is_free(host: str, port: int) -> bool:
    # No SO_REUSEADDR here: we're probing availability, not reusing. On Windows
    # SO_REUSEADDR lets you bind an already-bound port, which would falsely
    # report a busy port as free.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _pick_port(host: str, preferred: int, *, label: str) -> int:
    """Return `preferred` if free, otherwise the next free port above it."""
    if _port_is_free(host, preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 50):
        if _port_is_free(host, candidate):
            warn(f"{label} port {preferred} is busy; using {candidate} instead.")
            return candidate
    raise RuntimeError(f"no free {label} port near {preferred}")


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (URLError, OSError, ValueError):
        return False


def _wait_until(
    check: Callable[[], bool],
    *,
    timeout: float,
    interval: float = 0.4,
    alive: Callable[[], bool] | None = None,
) -> bool:
    """Poll `check` until it returns True or we time out. If `alive` is given
    and returns False, bail early (the process we're waiting on has died)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if alive is not None and not alive():
            return False
        if check():
            return True
        time.sleep(interval)
    return False


# --------------------------------------------------------------------------
# Process management
# --------------------------------------------------------------------------
@dataclass
class Proc:
    name: str
    popen: subprocess.Popen
    color: str

    def alive(self) -> bool:
        return self.popen.poll() is None


# On Windows we assign every child to a Job Object flagged KILL_ON_JOB_CLOSE.
# The OS closes our handles when this process dies for *any* reason (Ctrl+C,
# window close, taskkill, crash), which kills the whole job with us -- so the
# backend/frontend can never be orphaned holding their ports. This is belt to
# the psutil-teardown suspenders in _terminate().
_win_job = None
_win_job_tried = False


def _win_job_handle():
    global _win_job, _win_job_tried
    if _win_job_tried:
        return _win_job
    _win_job_tried = True
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]

        class _BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _EXT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC),
                ("IoInfo", _IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = _EXT()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        # 9 == JobObjectExtendedLimitInformation
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(limits),
                                           ctypes.sizeof(limits)):
            return None
        _win_job = job
    except Exception:  # never let job setup break the launcher
        _win_job = None
    return _win_job


def _assign_to_win_job(pid: int) -> None:
    handle = _win_job_handle()
    if not handle:
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        # PROCESS_SET_QUOTA (0x0100) | PROCESS_TERMINATE (0x0001)
        hproc = k32.OpenProcess(0x0101, False, pid)
        if hproc:
            k32.AssignProcessToJobObject(handle, hproc)
            k32.CloseHandle(hproc)
    except Exception:
        pass


def _spawn(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    color: str,
    prefix_output: bool,
) -> Proc:
    """Start a child process. When `prefix_output` is set, its stdout/stderr are
    merged into ours with a coloured ``[name]`` prefix so both servers are
    legible in one console; otherwise the child inherits our streams."""
    creationflags = 0
    extra: dict = {}
    if sys.platform == "win32":
        # Own process group so we can deliver CTRL_BREAK_EVENT to the whole
        # tree for a graceful shutdown before falling back to a hard kill.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # New session/process-group so os.killpg() can stop the tree at once.
        extra["start_new_session"] = True

    stdout = subprocess.PIPE if prefix_output else None
    popen = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=stdout,
        stderr=subprocess.STDOUT if prefix_output else None,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        **extra,
    )
    if sys.platform == "win32":
        # Tie the child's lifetime to ours: if this launcher dies for any
        # reason, the OS closes the job and kills the child with it.
        _assign_to_win_job(popen.pid)
    proc = Proc(name=name, popen=popen, color=color)
    if prefix_output and popen.stdout is not None:
        threading.Thread(
            target=_pump, args=(proc,), daemon=True, name=f"pump-{name}"
        ).start()
    return proc


def _pump(proc: Proc) -> None:
    tag = _c(proc.color, f"[{proc.name}]")
    assert proc.popen.stdout is not None
    for line in proc.popen.stdout:
        print(f"{tag} {line.rstrip()}", flush=True)


def _install_shutdown_signals() -> None:
    """Route SIGTERM/SIGHUP through KeyboardInterrupt so our teardown `finally`
    runs when a process manager (or `kill`) stops us -- not just on Ctrl+C.
    Without this, a POSIX SIGTERM would exit immediately and orphan the child
    servers (the Windows Job Object already covers the Windows side)."""
    def _raise(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    sigs = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        sigs.append(signal.SIGHUP)
    for sig in sigs:
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _raise)


def _terminate(proc: Proc, *, timeout: float = 8.0) -> None:
    """Stop a process and its children, gracefully first then forcibly.

    We ask the whole tree to shut down (CTRL_BREAK_EVENT on Windows, SIGTERM to
    the process group on POSIX) so uvicorn can drain SSE streams and flush the
    DB, then wait, then hard-kill anything that ignored us. On Windows the break
    maps to SIGBREAK, which uvicorn/node may not treat as graceful, so the drain
    there is best-effort -- the timeout hard-kill (and the Job Object) backstop
    it."""
    if not proc.alive():
        return
    info(f"stopping {proc.name}...")
    # Enumerate the whole tree first: `next dev` and uvicorn --reload both spawn
    # workers that must die too, or ports stay held after we exit.
    children: list = []
    with contextlib.suppress(psutil.Error):
        children = psutil.Process(proc.popen.pid).children(recursive=True)

    # 1) Polite, tree-wide shutdown request.
    with contextlib.suppress(OSError, ValueError):
        if sys.platform == "win32":
            proc.popen.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(proc.popen.pid), signal.SIGTERM)

    try:
        proc.popen.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # 2) Force-kill the leader and anything still standing.
        with contextlib.suppress(OSError):
            proc.popen.kill()
    for child in children:
        with contextlib.suppress(psutil.Error):
            if child.is_running():
                child.kill()


# --------------------------------------------------------------------------
# Environment / preflight
# --------------------------------------------------------------------------
def _base_env(backend_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    # The frontend dev proxy and the client both read these.
    env["PUFFIN_COPILOT_BACKEND"] = backend_url
    return env


def _node_available() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def _frontend_deps_installed() -> bool:
    return (FRONTEND_DIR / "node_modules").is_dir()


def _npm_cmd() -> str:
    # On Windows the executable is npm.cmd; shutil.which resolves it.
    return shutil.which("npm") or shutil.which("npm.cmd") or "npm"


def _npm(*args: str) -> list[str]:
    # shutil.which resolves npm.cmd on Windows, so we can run it with
    # shell=False (no cmd quoting, no injection surface).
    return [_npm_cmd(), *args]


def _next_bin() -> str | None:
    """Path to the project-local `next` CLI, or None if deps aren't installed."""
    name = "next.cmd" if sys.platform == "win32" else "next"
    candidate = FRONTEND_DIR / "node_modules" / ".bin" / name
    return str(candidate) if candidate.exists() else None


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True

    def check(label: str, good: bool, detail: str = "", *, advisory: bool = False) -> None:
        # advisory checks are shown for information but never fail the exit code
        # (they're optional per mode: an API key only gates chat, a static
        # export only gates --prod).
        nonlocal ok
        if good:
            mark = _c("32", "ok")
        elif advisory:
            mark = _c("33", "note")
        else:
            mark = _c("31", "MISSING")
        print(f"  [{mark}] {label}" + (f"  {detail}" if detail else ""))
        if not advisory:
            ok = ok and good

    print("finetune-copilot doctor\n")
    node = _node_available()
    check("Node.js / npm", node is not None,
          node or "install from https://nodejs.org (needed for the dev UI)")
    deps = _frontend_deps_installed()
    check("frontend dependencies", deps,
          "" if deps else "installed automatically on first `finetune-copilot`",
          advisory=True)
    check("static export present (for --prod)", STATIC_OUT.is_dir(),
          str(STATIC_OUT) if STATIC_OUT.is_dir() else "optional; run: finetune-copilot build",
          advisory=True)

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        check("backend dependencies", True)
    except ImportError:
        check("backend dependencies", False, 'run: pip install -e ".[copilot]"')

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    check("ANTHROPIC_API_KEY", has_key,
          "" if has_key else "optional; chat is disabled until set (dashboard still works)",
          advisory=True)

    host = args.host
    check(f"backend port {args.backend_port} free", _port_is_free(host, args.backend_port))
    check(f"frontend port {args.frontend_port} free",
          _port_is_free(host, args.frontend_port))

    print()
    if ok:
        info("all good - run `finetune-copilot` to launch.")
        return 0
    warn("some checks failed; see hints above.")
    return 1


# --------------------------------------------------------------------------
# build (static export for --prod)
# --------------------------------------------------------------------------
def cmd_build(args: argparse.Namespace) -> int:
    if _node_available() is None:
        return die("Node.js/npm not found. Install from https://nodejs.org")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    # Signals next.config.js to switch on `output: 'export'`.
    env["PUFFIN_COPILOT_STATIC"] = "1"

    if not _frontend_deps_installed() or args.clean:
        info("installing frontend dependencies (npm install)...")
        rc = subprocess.call(_npm("install"), cwd=str(FRONTEND_DIR), env=env)
        if rc != 0:
            return die("npm install failed")

    info("building static export (npx next build)...")
    rc = subprocess.call(_npm("run", "build"), cwd=str(FRONTEND_DIR), env=env)
    if rc != 0:
        return die("frontend build failed")

    if not STATIC_OUT.is_dir():
        return die(
            f"build finished but {STATIC_OUT} was not produced - "
            "is `output: 'export'` wired in next.config.js?")
    info(f"static export ready: {STATIC_OUT}")
    info("launch it with:  finetune-copilot --prod")
    return 0


# --------------------------------------------------------------------------
# up (the default) - launch and open the browser
# --------------------------------------------------------------------------
def _start_backend(
    host: str, port: int, env: dict[str, str], *, reload: bool, prefix: bool,
    frontend_dist: Path | None,
) -> Proc:
    env = dict(env)
    env["PUFFIN_COPILOT_HOST"] = host
    env["PUFFIN_COPILOT_PORT"] = str(port)
    if frontend_dist is not None:
        env["PUFFIN_COPILOT_FRONTEND_DIST"] = str(frontend_dist)
    argv = [sys.executable, "-m", "copilot.backend.main", "--host", host,
            "--port", str(port)]
    if reload:
        argv.append("--reload")
    return _spawn("backend", argv, cwd=REPO_ROOT, env=env, color="35",
                  prefix_output=prefix)


def _start_frontend(port: int, env: dict[str, str], *, prefix: bool) -> Proc:
    # Invoke the project-local `next` directly so we set the port exactly once.
    # (`npm run dev` hardcodes `-p 3000` in package.json; appending another -p
    # would leave two conflicting flags.)
    next_bin = _next_bin()
    if next_bin is not None:
        argv = [next_bin, "dev", "--turbo", "-p", str(port)]
    else:  # deps not installed via the .bin shim; fall back to npm exec
        argv = _npm("exec", "--", "next", "dev", "--turbo", "-p", str(port))
    return _spawn("frontend", argv, cwd=FRONTEND_DIR, env=env, color="36",
                  prefix_output=prefix)


def cmd_up(args: argparse.Namespace) -> int:
    _install_shutdown_signals()
    host = args.host
    # localhost is friendlier than 127.0.0.1 in the address bar and matches
    # the default CORS allow-list.
    browse_host = "localhost" if host in {"127.0.0.1", "0.0.0.0"} else host

    prod = args.prod
    if prod and not STATIC_OUT.is_dir():
        return die(
            "no static export found for --prod. Build it first:\n"
            "    finetune-copilot build")
    if not prod and _node_available() is None:
        if STATIC_OUT.is_dir():
            warn("Node.js not found - falling back to --prod (static export).")
            prod = True
        else:
            return die(
                "Node.js/npm not found, needed for the dev UI.\n"
                "Install Node from https://nodejs.org, or build a static "
                "export on a machine that has it:  finetune-copilot build")
    if not prod and not _frontend_deps_installed():
        info("frontend dependencies missing - installing once (npm install)...")
        rc = subprocess.call(_npm("install"), cwd=str(FRONTEND_DIR),
                             env=os.environ.copy())
        if rc != 0:
            return die("npm install failed")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        warn("ANTHROPIC_API_KEY not set - the dashboard works, but chat will "
             "refuse until you set it.")

    if host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get(
            "PUFFIN_COPILOT_API_KEY"):
        warn(f"binding {host} exposes the API (which can run training/deploy "
             "actions) on your network with no auth. Set PUFFIN_COPILOT_API_KEY "
             "to require a bearer token.")

    backend_port = _pick_port(host, args.backend_port, label="backend")
    backend_url = f"http://{browse_host}:{backend_port}"
    env = _base_env(backend_url)
    prefix = not args.no_prefix

    procs: list[Proc] = []
    try:
        if prod:
            info(f"serving on {backend_url} (single-origin static UI)")
            backend = _start_backend(
                host, backend_port, env, reload=False, prefix=prefix,
                frontend_dist=STATIC_OUT)
            procs.append(backend)
            # Land on /dashboard/ directly. The static export's root index.html
            # is a JS-only redirect shell (a hard load of "/" flashes an error
            # page before hydrating), so we skip it entirely.
            app_url = f"{backend_url}/dashboard/"
        else:
            frontend_port = _pick_port(host, args.frontend_port, label="frontend")
            info(f"backend  -> {backend_url}")
            info(f"frontend -> http://{browse_host}:{frontend_port}")
            backend = _start_backend(
                host, backend_port, env, reload=args.reload, prefix=prefix,
                frontend_dist=None)
            procs.append(backend)
            frontend = _start_frontend(frontend_port, env, prefix=prefix)
            procs.append(frontend)
            app_url = f"http://{browse_host}:{frontend_port}"

        info("waiting for backend to come up...")
        if not _wait_until(lambda: _http_ok(f"{backend_url}/healthz"), timeout=40,
                           alive=backend.alive):
            reason = "crashed on startup" if not backend.alive() else "timed out"
            return die(f"backend {reason} - see logs above.")

        info("waiting for the web UI to come up...")
        # The dev server compiles on first request; poll the page we'll open.
        target = procs[-1]
        if not _wait_until(lambda: _http_ok(app_url), timeout=120,
                           alive=target.alive):
            reason = "crashed" if not target.alive() else "did not come up in time"
            return die(f"web UI {reason} - see logs above.")

        print()
        info(_c("32", f"Puffin Studio is ready -> {app_url}"))
        if not args.no_browser:
            webbrowser.open(app_url)
        info("Press Ctrl+C to stop.")
        print()

        # Block until Ctrl+C or a child dies.
        while True:
            for p in procs:
                if not p.alive():
                    warn(f"{p.name} exited (code {p.popen.returncode}); shutting down.")
                    return p.popen.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        info("received Ctrl+C")
        return 0
    finally:
        for p in reversed(procs):
            _terminate(p)


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------
def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--host", default=os.environ.get("PUFFIN_COPILOT_HOST", "127.0.0.1"),
                     help="Bind host (default 127.0.0.1).")
    sub.add_argument("--backend-port", type=int,
                     default=int(os.environ.get("PUFFIN_COPILOT_PORT", "8765")),
                     help="Backend port (default 8765; auto-bumps if busy).")
    sub.add_argument("--frontend-port", type=int,
                     default=int(os.environ.get("PUFFIN_FRONTEND_PORT", "3000")),
                     help="Frontend dev-server port (default 3000; auto-bumps if busy).")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finetune-copilot",
        description="Open Puffin Studio (backend + frontend web UI, one command).",
    )
    sub = parser.add_subparsers(dest="command")

    up = sub.add_parser("up", help="Launch the app and open the browser (default).")
    _add_common(up)
    up.add_argument("--prod", action="store_true",
                    help="Serve the pre-built static UI from the backend (no Node).")
    up.add_argument("--reload", action="store_true",
                    help="Backend hot-reload (dev only).")
    up.add_argument("--no-browser", action="store_true",
                    help="Do not open a browser window.")
    up.add_argument("--no-prefix", action="store_true",
                    help="Inherit child stdout instead of prefixing [backend]/[frontend].")
    up.set_defaults(func=cmd_up)

    build = sub.add_parser("build", help="Static-export the frontend for --prod.")
    build.add_argument("--clean", action="store_true",
                       help="Reinstall node_modules before building.")
    build.set_defaults(func=cmd_build)

    doc = sub.add_parser("doctor", help="Check node, deps, ports, and API key.")
    _add_common(doc)
    doc.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    _init_stdio()
    parser = _build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    # Bare `finetune-copilot` (and any leading flags) default to `up`.
    known = {"up", "build", "doctor", "-h", "--help"}
    if not raw or raw[0] not in known:
        raw = ["up", *raw]
    args = parser.parse_args(raw)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError) as exc:
        # e.g. no free port (RuntimeError), or Popen failing to find a binary
        # (FileNotFoundError/OSError) - report cleanly instead of a traceback.
        return die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
