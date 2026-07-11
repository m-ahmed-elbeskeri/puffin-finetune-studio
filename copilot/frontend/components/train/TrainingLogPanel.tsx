"use client";
/**
 * Tail a training run's log file in-app. This is the "why did it fail?"
 * surface: the backend writes a durable .log_path pointer next to every
 * adapter dir, and GET /api/train/log tails it. When `live` is set the panel
 * polls so you can watch a run scroll.
 */
import * as React from "react";
import useSWR from "swr";
import { Loader2, RefreshCw, ScrollText, Terminal } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { TrainingLogPayload } from "@/lib/api";
import { cn } from "@/lib/cn";

export function TrainingLogPanel({
  adapterDir, live = false, tail = 400, defaultOpen = false,
}: {
  adapterDir: string;
  live?: boolean;
  tail?: number;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const { data, error, isLoading, mutate } = useSWR<TrainingLogPayload>(
    open ? ["train-log", adapterDir, tail] : null,
    () => api.trainLog(adapterDir, tail),
    { refreshInterval: open && live ? 3_000 : 0 },
  );
  const preRef = React.useRef<HTMLPreElement>(null);

  // Keep the view pinned to the newest line while a run is live.
  React.useEffect(() => {
    if (live && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [data, live]);

  return (
    <div className="rounded-lg border border-ink-200 bg-card">
      <div className="flex w-full items-center gap-2 px-3 py-2 text-xs font-bold
                      uppercase tracking-wider text-ink-500">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-center gap-2 text-left hover:text-ink"
        >
          <ScrollText size={13} className={open ? "text-accent-600" : "text-ink-400"} />
          Training log
          {data?.present && typeof data.total_lines === "number" ? (
            <span className="font-normal normal-case tracking-normal text-ink-400">
              {data.total_lines.toLocaleString()} lines
            </span>
          ) : null}
        </button>
        {open ? (
          <button
            type="button"
            onClick={() => void mutate()}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5
                       text-[10px] font-semibold text-ink-500 hover:bg-ink-100 hover:text-ink"
          >
            <RefreshCw size={11} /> Refresh
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="text-[10px] font-semibold text-accent-600 hover:underline"
          >
            view
          </button>
        )}
      </div>
      {open ? (
        <div className="border-t border-ink-100 p-2">
          {isLoading && !data ? (
            <div className="flex items-center gap-2 px-2 py-6 text-xs text-ink-500">
              <Loader2 size={13} className="animate-spin" /> Reading log…
            </div>
          ) : error ? (
            <div className="px-2 py-4 text-xs text-red-700">
              Couldn&apos;t read the log: {String(error instanceof Error ? error.message : error)}
            </div>
          ) : !data?.present ? (
            <div className="flex items-center gap-2 px-2 py-6 text-xs text-ink-400">
              <Terminal size={13} />
              {data?.message ?? "No log file for this run yet."}
            </div>
          ) : (
            <>
              <pre
                ref={preRef}
                className="max-h-96 overflow-auto rounded-md bg-[#0f172a] p-3 font-mono
                           text-[11px] leading-relaxed text-slate-100"
              >
                {data.lines.length
                  ? data.lines.map((ln, i) => (
                      <div key={i} className={cn(logLineTone(ln))}>{ln || " "}</div>
                    ))
                  : "(log is empty)"}
              </pre>
              {data.log_path ? (
                <div className="mt-1 px-1 text-[10px] text-ink-400">
                  <code>{data.log_path}</code>
                  {live ? " · auto-refreshing" : ""}
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** Tint the lines that matter so a traceback jumps out of the scroll. */
function logLineTone(line: string): string {
  const l = line.toLowerCase();
  if (/\b(error|traceback|exception|failed|cuda out of memory|oom)\b/.test(l)) {
    return "text-red-300";
  }
  if (/\b(warn|warning)\b/.test(l)) return "text-amber-300";
  return "";
}
