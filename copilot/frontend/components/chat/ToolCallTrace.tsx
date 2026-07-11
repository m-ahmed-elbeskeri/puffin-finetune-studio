"use client";
import * as React from "react";
import { ChevronDown, ChevronRight, Loader2, Wrench } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import type { Artifact } from "@/lib/types";

/**
 * Collapsible "the assistant called tool X with args Y" trace, shown above
 * the actual ArtifactRouter render. Expanded by default while pending.
 */
export function ToolCallTrace({
  name, input, result, pending,
}: {
  name: string;
  input?: Record<string, unknown>;
  result?: Artifact;
  pending?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const error = result?.kind === "error";

  return (
    <div className={cn(
      "border rounded-lg text-xs",
      pending ? "border-amber-200 bg-amber-50/40" :
      error ? "border-red-200 bg-red-50/40" :
      "border-ink-200 bg-ink-50",
    )}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5"
      >
        {pending ? (
          <Loader2 size={12} className="animate-spin text-amber-600" />
        ) : error ? (
          <Wrench size={12} className="text-red-600" />
        ) : (
          <Wrench size={12} className="text-ink-500" />
        )}
        <code className="font-semibold text-ink-700">{name}</code>
        <span className="text-ink-500 truncate flex-1 text-left">
          {pending ? "calling..." :
           error ? `error: ${(result as { message?: string })?.message ?? "unknown"}` :
           "done"}
        </span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open ? (
        <div className="px-3 pb-2 space-y-2">
          {input && Object.keys(input).length > 0 ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider font-bold text-ink-500">
                input
              </div>
              <pre className="bg-card border border-ink-200 rounded p-2 overflow-x-auto text-[11px]">
{JSON.stringify(input, null, 2)}
              </pre>
            </div>
          ) : null}
          {result ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider font-bold text-ink-500">
                result (raw)
              </div>
              <pre className="bg-card border border-ink-200 rounded p-2 overflow-x-auto text-[11px] max-h-64">
{JSON.stringify(result, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
