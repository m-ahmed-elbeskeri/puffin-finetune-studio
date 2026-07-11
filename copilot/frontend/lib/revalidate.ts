"use client";
import { mutate } from "swr";

/**
 * Instant cross-panel refresh.
 *
 * Every panel that reflects project data or state is keyed with one of these
 * prefixes. After any mutation, by the AI's tools or a manual edit, we
 * revalidate all matching SWR keys so the UI updates immediately instead of
 * waiting for a poll interval. Chat threads (`thread:*`) and liveness
 * (`healthz`) are deliberately excluded so we never disturb the conversation
 * or the offline watchdog.
 */
const DATA_KEY_RE =
  /^(data|inspect|config|state|capabilities|registry|runs|eval|monitor|quality|drift|projects)/;

export function revalidateData(): void {
  void mutate(
    (key) => typeof key === "string" && DATA_KEY_RE.test(key),
    undefined,
    { revalidate: true },
  );
}
