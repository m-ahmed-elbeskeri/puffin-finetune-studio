"""Console entry point: `puffin-copilot` runs the FastAPI app via uvicorn."""
from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="puffin-copilot",
        description="Run the Puffin Studio backend (FastAPI).",
    )
    parser.add_argument("--host", default=None,
                        help="Override PUFFIN_COPILOT_HOST (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=None,
                        help="Override PUFFIN_COPILOT_PORT (default 8765).")
    parser.add_argument("--reload", action="store_true",
                        help="Enable uvicorn auto-reload (dev only).")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "uvicorn not installed. Run:\n"
            '  pip install -e ".[copilot]"\n'
        )
        return 1

    from copilot.backend.settings import get_settings
    s = get_settings()
    host = args.host or s.host
    port = args.port or s.port

    run_kwargs: dict = dict(
        factory=True,
        host=host, port=port,
        reload=args.reload,
        log_level=s.log_level.lower(),
    )
    # Windows: keep asyncio on a subprocess-capable ProactorEventLoop. Under
    # --reload (use_subprocess=True) uvicorn otherwise forces
    # WindowsSelectorEventLoopPolicy, and a SelectorEventLoop cannot spawn
    # subprocesses on Windows -- breaking the claude_code / codex_cli providers
    # (claude-agent-sdk -> anyio.open_process) with a bare empty-message
    # NotImplementedError seen as "CLIConnectionError: Failed to start Claude Code:".
    # loop="none" skips uvicorn's loop-policy setup so the process default
    # (Proactor) stands; we also set it explicitly for the single-process path.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        run_kwargs["loop"] = "none"

    uvicorn.run("copilot.backend.app:create_app", **run_kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
