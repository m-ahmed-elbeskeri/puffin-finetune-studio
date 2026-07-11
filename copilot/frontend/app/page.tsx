"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// The dedicated chat page was removed; the AI now lives in the right-side
// "Ask AI" panel on every page, so the root just forwards to the dashboard.
//
// This is a *client* redirect on purpose. A server `redirect("/dashboard")`
// works in dev, but under `output: 'export'` (the `finetune-copilot --prod`
// static build) it emits a Next error shell as index.html, so a hard load of
// "/" flashes an error page. Rendering a real loading state and navigating on
// the client keeps the root clean in every mode.
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center text-ink-500">
      <p className="font-display uppercase tracking-wide">Loading Puffin Studio…</p>
      {/* If JS is disabled the client redirect never fires; give a way through. */}
      <noscript>
        <a href="/dashboard/">Continue to the dashboard</a>
      </noscript>
    </div>
  );
}
