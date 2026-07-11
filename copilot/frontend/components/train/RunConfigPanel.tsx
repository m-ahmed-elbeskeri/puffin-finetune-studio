"use client";
/**
 * Reproducibility panel for a run: the exact config snapshot it used plus its
 * data fingerprint (from run_config.yaml + run_meta.json next to the adapter).
 * Answers "what settings and data produced this adapter?".
 */
import * as React from "react";
import useSWR from "swr";
import { FileCode2, Fingerprint } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { RunConfigPayload } from "@/lib/api";

export function RunConfigPanel({ adapterDir }: { adapterDir: string }) {
  const [open, setOpen] = React.useState(false);
  const { data } = useSWR<RunConfigPayload>(
    open ? ["run-config", adapterDir] : null,
    () => api.trainRunConfig(adapterDir));
  const meta = data?.meta;
  return (
    <div className="rounded-lg border border-ink-200 bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-bold
                   uppercase tracking-wider text-ink-500 hover:text-ink"
      >
        <FileCode2 size={13} className={open ? "text-accent-600" : "text-ink-400"} />
        Config used
        {meta?.dataset_hash ? (
          <span className="inline-flex items-center gap-1 font-normal normal-case tracking-normal text-ink-400">
            <Fingerprint size={11} /> data {meta.dataset_hash}
          </span>
        ) : null}
        <span className="ml-auto text-[10px] font-semibold text-accent-600">
          {open ? "hide" : "view"}
        </span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-ink-100 p-2">
          {data && !data.present ? (
            <div className="px-1 py-3 text-[11px] text-ink-400">
              {data.message ?? "No config snapshot for this run."}
            </div>
          ) : (
            <>
              {meta?.dataset_splits && Object.keys(meta.dataset_splits).length ? (
                <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 text-[10px] text-ink-500">
                  {Object.entries(meta.dataset_splits).map(([k, v]) => (
                    <span key={k}>
                      {k}: <b className="tabular-nums text-ink-600">{v.records.toLocaleString()}</b>
                      {" "}rows · <span className="font-mono">{v.sha256}</span>
                    </span>
                  ))}
                </div>
              ) : null}
              {data?.yaml ? (
                <pre className="max-h-72 overflow-auto rounded-md bg-ink-50 p-2.5 font-mono
                                text-[10px] leading-relaxed text-ink-700">
                  {data.yaml}
                </pre>
              ) : (
                <div className="px-1 py-2 text-[11px] text-ink-400">Loading…</div>
              )}
              {data?.config_path ? (
                <div className="px-1 text-[10px] text-ink-400">
                  <code>{data.config_path}</code>
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
