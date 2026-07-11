"use client";
import * as React from "react";
import useSWR, { useSWRConfig } from "swr";
import { CheckCircle2, ServerCrash } from "@/components/ui/icons";
import { api } from "@/lib/api";

/**
 * Floating backend-liveness watchdog.
 *
 * Polls /healthz through the same-origin proxy. When the FastAPI backend is
 * down every API call in the app fails with an opaque 500: this chip tells
 * the user exactly what's wrong and how to fix it, then heals the app
 * (global SWR revalidation) the moment the backend returns.
 */
export function BackendStatus() {
  const { mutate } = useSWRConfig();
  const { data, error } = useSWR("healthz", () => api.healthz(), {
    refreshInterval: 5_000,
    shouldRetryOnError: true,
    errorRetryInterval: 5_000,
    revalidateOnFocus: true,
  });

  const offline = Boolean(error) && !data;
  const wasOffline = React.useRef(false);
  const [justRecovered, setJustRecovered] = React.useState(false);

  React.useEffect(() => {
    if (offline) {
      wasOffline.current = true;
      return;
    }
    if (wasOffline.current) {
      wasOffline.current = false;
      setJustRecovered(true);
      // Backend is back: refetch everything that failed while it was down.
      void mutate(() => true, undefined, { revalidate: true });
      const t = window.setTimeout(() => setJustRecovered(false), 2_500);
      return () => window.clearTimeout(t);
    }
  }, [offline, mutate]);

  if (!offline && !justRecovered) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 animate-fadeInUp"
    >
      {offline ? (
        <div className="flex items-center gap-2.5 rounded-full bg-ink text-ink-50
                        pl-3 pr-4 py-2 shadow-lg text-xs">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full rounded-full
                             bg-red-400 opacity-75 animate-ping" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500" />
          </span>
          <ServerCrash size={14} className="text-red-300" />
          <span>
            Backend offline: start it with{" "}
            <code className="font-mono text-amber-300">copilot/scripts/dev.ps1</code>
            {" "}· retrying…
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-full bg-emerald-600 text-white
                        px-4 py-2 shadow-lg text-xs">
          <CheckCircle2 size={14} />
          Backend reconnected
        </div>
      )}
    </div>
  );
}
