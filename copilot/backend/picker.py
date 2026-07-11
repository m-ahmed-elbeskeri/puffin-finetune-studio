"""Native OS folder picker for the project-creation flow.

The copilot runs locally as the user — we can pop a tk dialog on their
desktop instead of forcing them to type an absolute path. tkinter ships
with the Python stdlib on Windows/macOS, and on Linux it's a one-package
install; if it's unavailable we surface a clear error so the UI can fall
back to manual entry.

Implementation notes:
- `tk.Tk()` must spin up its event loop on the calling thread, so we run
  inside `asyncio.to_thread` to keep the FastAPI worker responsive.
- `-topmost` raises the dialog above the browser; `withdraw` hides the
  empty root window that tk would otherwise leave on screen.
- `askdirectory()` returns "" on cancel — we map that to None.
"""
from __future__ import annotations

import asyncio
from typing import Optional


def _tk_pick_folder(title: str, initial: Optional[str]) -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.attributes("-topmost", True)
        root.withdraw()
        kwargs: dict[str, str] = {"title": title}
        if initial:
            kwargs["initialdir"] = initial
        path = filedialog.askdirectory(**kwargs)
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
    return path or None


async def pick_folder(
    *,
    title: str = "Pick project folder",
    initial: Optional[str] = None,
) -> Optional[str]:
    """Open the OS folder picker and return the chosen absolute path, or
    None if the user cancelled. Raises RuntimeError if no GUI is available."""
    try:
        return await asyncio.to_thread(_tk_pick_folder, title, initial)
    except ImportError as exc:
        raise RuntimeError(
            "tkinter is not available; install python3-tk (Linux) or use "
            "a Python build with tk support."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Folder picker failed to open: {exc}") from exc
