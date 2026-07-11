"""Screenshot every copilot page so we can see what the React UI looks like."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


BASE = "http://127.0.0.1:3000"

PAGES = [
    ("chat",       "/"),
    ("dashboard",  "/dashboard"),
    ("runs",       "/runs"),
    ("monitor",    "/monitor"),
    ("deploy",     "/deploy"),
    ("playground", "/playground"),
    ("data",       "/data"),
    ("evaluate",   "/evaluate"),
    ("settings",   "/settings"),
    ("docs",       "/docs"),
]


def main() -> None:
    out = Path("artifacts/ui-review/copilot")
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        for name, route in PAGES:
            url = BASE + route
            print(f"-> {name}: {url}")
            # `networkidle` never fires because LiveTraining keeps an SSE
            # connection open — use domcontentloaded and a longer settle wait.
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(3500)  # let SWR fetch data + render
            # Tall viewport so charts + tables render fully.
            page.set_viewport_size({"width": 1440, "height": 1600})
            page.wait_for_timeout(400)
            page.evaluate("window.scrollTo(0, 0)")
            png = out / f"{name}.png"
            page.screenshot(path=str(png), full_page=False)
            print(f"   saved {png.name}")
            page.set_viewport_size({"width": 1440, "height": 900})
        b.close()


if __name__ == "__main__":
    main()
