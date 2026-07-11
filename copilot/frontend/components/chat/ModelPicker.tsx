"use client";
import * as React from "react";
import useSWR from "swr";
import { AlertTriangle, Check, ChevronDown, Sparkles } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

interface CatalogModel {
  id: string; label: string; vendor: string;
  requires: string; description: string; available: boolean;
}

const API_VENDORS = new Set(["anthropic", "openai"]);

/**
 * Dropdown listing every wired vendor + model, grouped into API providers
 * and local agent CLIs. Unavailable models are greyed out with the exact
 * requirement to unlock them; the trigger warns when the current selection
 * can't actually run.
 */
export function ModelPicker({
  value, onChange, compact,
}: {
  value: string;
  onChange: (modelId: string) => void;
  compact?: boolean;
}) {
  const { data } = useSWR("models", () => api.models());
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const all = React.useMemo(() => data?.models ?? [], [data?.models]);
  const current = all.find((m) => m.id === value);
  const currentUnusable = Boolean(data && value && (!current || !current.available));

  const sections = React.useMemo(() => {
    const apiModels = all.filter((m) => API_VENDORS.has(m.vendor));
    const cliModels = all.filter((m) => !API_VENDORS.has(m.vendor));
    return [
      { label: "API providers", models: apiModels },
      { label: "Local agent CLIs", models: cliModels },
    ].filter((s) => s.models.length > 0);
  }, [all]);

  const renderRow = (m: CatalogModel) => {
    const isActive = m.id === value;
    return (
      <button
        key={m.id}
        type="button"
        onClick={() => { onChange(m.id); setOpen(false); }}
        disabled={!m.available}
        className={cn(
          "flex w-full items-start gap-2 px-3 py-2 text-left",
          "hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-45",
          isActive && "bg-amber-50/60",
        )}
        title={m.available ? m.description : `Requires: ${m.requires}`}
      >
        <Check size={14} className={cn(
          "mt-1 shrink-0",
          isActive ? "text-amber-500" : "text-transparent",
        )} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <span
              className={cn(
                "h-1.5 w-1.5 shrink-0 rounded-full",
                m.available ? "bg-emerald-500" : "bg-ink-300",
              )}
              aria-hidden="true"
            />
            <span className="truncate">{m.label}</span>
            {m.id === data?.default ? (
              <span className="shrink-0 rounded bg-ink-100 px-1 py-px text-[8px]
                               font-bold uppercase tracking-wider text-ink-500">
                default
              </span>
            ) : null}
          </div>
          <div className="text-[11px] leading-snug text-ink-500">
            {m.description}
          </div>
          {!m.available ? (
            <div className="mt-0.5 text-[10px] text-amber-700">
              Needs: <code className="font-mono">{m.requires}</code>
            </div>
          ) : null}
        </div>
      </button>
    );
  };

  return (
    <div ref={rootRef} className={cn("relative", compact ? "" : "w-full")}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Pick a model"
        title={currentUnusable
          ? `${current?.label ?? value} isn't usable: ${current?.requires ? `needs ${current.requires}` : "not in the catalog"}`
          : (current?.description ?? "Pick a model")}
        className={cn(
          "inline-flex items-center gap-2 rounded-lg border bg-card px-3 text-sm",
          "transition-colors hover:border-accent",
          currentUnusable ? "border-amber-300" : "border-ink-200",
          compact ? "h-8 max-w-56 text-xs" : "h-9 w-full",
        )}
      >
        {currentUnusable ? (
          <AlertTriangle size={12} className="shrink-0 text-amber-500" />
        ) : (
          <Sparkles size={12} className="shrink-0 text-amber-500" />
        )}
        <span className="min-w-0 flex-1 truncate text-left">
          {current?.label ?? (value || "Pick a model")}
        </span>
        <ChevronDown size={12} className="shrink-0 text-ink-500" />
      </button>
      {open ? (
        <div className="absolute right-0 z-50 mt-1 w-80 overflow-hidden rounded-xl
                        border border-ink-200 bg-card shadow-card animate-fadeInUp">
          <div className="max-h-96 overflow-y-auto py-1">
            {sections.map((s) => (
              <div key={s.label}>
                <div className="border-b border-ink-100 bg-ink-50/60 px-3 py-1.5
                                text-[10px] font-bold uppercase tracking-wider text-ink-500">
                  {s.label}
                </div>
                {s.models.map(renderRow)}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
