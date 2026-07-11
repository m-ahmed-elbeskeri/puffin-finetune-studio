"""Quick DOM-inspect to understand how the CTA button sits below puffin-next."""
from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        p = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
        p.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=30_000)
        p.wait_for_timeout(1500)
        outer = p.evaluate(
            """
            () => {
                const panel = document.querySelector('.puffin-next');
                if (!panel) return 'NO PANEL';
                // Walk up to find the closest stVerticalBlock or stElementContainer
                let anc = panel;
                const trail = [];
                while (anc && trail.length < 12) {
                    trail.push({
                        tag: anc.tagName,
                        cls: (anc.className || '').slice(0, 80),
                        data: anc.getAttribute && anc.getAttribute('data-testid'),
                        nextSib: anc.nextElementSibling
                            ? (anc.nextElementSibling.getAttribute('data-testid') || anc.nextElementSibling.tagName)
                            : null,
                    });
                    anc = anc.parentElement;
                }
                // Find the button anywhere on page with the CTA text
                const btns = Array.from(document.querySelectorAll('button'));
                const cta = btns.find(b => /Open\\s+\\w+\\s+page|Get started|Promote/.test(b.textContent));
                let ctaPath = null;
                if (cta) {
                    let a = cta;
                    ctaPath = [];
                    while (a && ctaPath.length < 12) {
                        ctaPath.push({
                            tag: a.tagName,
                            data: a.getAttribute && a.getAttribute('data-testid'),
                        });
                        a = a.parentElement;
                    }
                }
                return JSON.stringify({trail, ctaPath}, null, 2);
            }
            """
        )
        print(outer)
        b.close()


if __name__ == "__main__":
    main()
