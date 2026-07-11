"use client";
import { useEffect, useState } from "react";
import type { LiveTrainingPayload } from "@/lib/types";
import { api } from "@/lib/api";

/**
 * EventSource subscription to the backend's /api/live/training endpoint.
 * Pushes a fresh payload every ~2s while a run is going; null when idle.
 *
 * EventSource only auto-reconnects on *transient* errors: an HTTP error
 * response (e.g. the proxy 500ing while the backend is down) fails the
 * connection permanently. We rebuild the source ourselves with exponential
 * backoff so live updates recover without a page reload.
 */
export function useLiveTraining(): LiveTrainingPayload | null {
  const [state, setState] = useState<LiveTrainingPayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let retryTimer: number | null = null;
    let backoffMs = 1_000;

    const connect = () => {
      if (cancelled) return;
      try {
        es = new EventSource(api.liveTrainingURL(2.0));
      } catch {
        scheduleRetry();
        return;
      }
      es.onopen = () => { backoffMs = 1_000; };
      es.addEventListener("training_state", (evt: MessageEvent) => {
        if (cancelled) return;
        backoffMs = 1_000;
        try {
          setState(JSON.parse(evt.data) as LiveTrainingPayload);
        } catch {
          /* ignore malformed frames */
        }
      });
      es.onerror = () => {
        // CONNECTING means the browser is retrying on its own; only step in
        // once the source is CLOSED (permanent failure).
        if (es?.readyState === EventSource.CLOSED) {
          es.close();
          es = null;
          scheduleRetry();
        }
      };
    };

    const scheduleRetry = () => {
      if (cancelled || retryTimer !== null) return;
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        connect();
      }, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 15_000);
    };

    connect();
    return () => {
      cancelled = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      es?.close();
    };
  }, []);

  return state;
}
