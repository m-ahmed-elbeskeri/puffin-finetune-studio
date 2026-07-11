"use client";
/**
 * Pre-launch readiness: answers "will this even start?" (preflight checks
 * against the materialized config) and "will it fit?" (a rough VRAM estimate).
 * Both recompute as you edit knobs so you catch a doomed run before spending
 * GPU time. Purely advisory: it never blocks the launch buttons.
 */
import * as React from "react";
import useSWR from "swr";
import { AlertTriangle, CheckCircle2, Cpu, Gauge, Loader2, XCircle } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type {
  PreflightCheck, StudioMethod, TrainEstimate, TrainPreflight,
} from "@/lib/api";
import { cn } from "@/lib/cn";

/** Debounce a value so we don't refetch on every keystroke. */
function useDebounced<T>(value: T, ms = 500): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function ReadinessPanel({
  method, edits, local,
}: {
  method: StudioMethod;
  edits: Record<string, unknown>;
  local: boolean;
}) {
  const key = useDebounced(JSON.stringify({ method, edits, local }), 500);
  const { data: pre, isLoading: preLoading } = useSWR<TrainPreflight>(
    ["preflight", key], () => api.trainPreflight({ method, overrides: edits, local }),
    { keepPreviousData: true },
  );
  const { data: est, isLoading: estLoading } = useSWR<TrainEstimate>(
    ["estimate", key], () => api.trainEstimate({ method, overrides: edits }),
    { keepPreviousData: true },
  );

  const loading = (preLoading && !pre) || (estLoading && !est);

  return (
    <div className="rounded-xl border border-ink-200 bg-card">
      <div className="flex items-center gap-2 border-b border-ink-100 px-3 py-2">
        <Gauge size={14} className="text-accent-600" />
        <span className="text-xs font-bold uppercase tracking-wider text-ink-500">
          Pre-launch check
        </span>
        {loading ? <Loader2 size={12} className="animate-spin text-ink-400" /> : null}
        {pre ? (
          <span className={cn(
            "ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
            pre.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700",
          )}>
            {pre.ok ? "ready" : "not ready"}
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2">
        <div className="space-y-1.5">
          {(pre?.checks ?? []).map((c) => <CheckRow key={c.id} check={c} />)}
          {!pre && !loading ? (
            <div className="text-xs text-ink-400">No checks yet.</div>
          ) : null}
        </div>
        <EstimateBlock est={est} />
      </div>
    </div>
  );
}

function CheckRow({ check }: { check: PreflightCheck }) {
  const Icon = check.status === "ok" ? CheckCircle2
    : check.status === "warn" ? AlertTriangle : XCircle;
  const tone = check.status === "ok" ? "text-emerald-600"
    : check.status === "warn" ? "text-amber-600" : "text-red-600";
  return (
    <div className="flex items-start gap-2">
      <Icon size={14} className={cn("mt-0.5 shrink-0", tone)} />
      <div className="min-w-0">
        <div className="text-xs font-semibold text-ink">{check.label}</div>
        <div className="text-[11px] leading-snug text-ink-500">{check.detail}</div>
      </div>
    </div>
  );
}

function EstimateBlock({ est }: { est: TrainEstimate | undefined }) {
  if (!est) {
    return <div className="text-xs text-ink-400">Estimating…</div>;
  }
  if (!est.known) {
    return (
      <div className="rounded-lg bg-ink-50 p-2.5 text-[11px] leading-relaxed text-ink-500">
        <div className="mb-1 flex items-center gap-1.5 font-bold uppercase tracking-wider">
          <Cpu size={12} /> Resource estimate
        </div>
        {est.note ?? "Can't estimate VRAM for this model."}
      </div>
    );
  }
  const fitsTone = est.fits == null ? "text-ink-500"
    : est.fits ? "text-emerald-700" : "text-red-700";
  return (
    <div className="rounded-lg bg-ink-50 p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-500">
        <Cpu size={12} /> Resource estimate
      </div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        <span>
          <b className="tabular-nums text-ink">~{est.vram_gb} GB</b>
          <span className="text-ink-500"> VRAM</span>
        </span>
        <span className="text-ink-500">
          {est.params_b}B · {est.lora ? "LoRA" : "full"} · {est.quantization}
        </span>
        {est.gpu_vram_gb != null ? (
          <span className={cn("font-semibold", fitsTone)}>
            {est.fits ? "fits" : "over budget"} your {est.gpu_vram_gb} GB GPU
          </span>
        ) : null}
      </div>
      {est.method_note ? (
        <p className="mt-1.5 text-[11px] leading-snug text-ink-500">{est.method_note}</p>
      ) : null}
      {(est.warnings ?? []).map((w, i) => (
        <p key={i} className="mt-1.5 flex items-start gap-1 text-[11px] leading-snug text-amber-700">
          <AlertTriangle size={11} className="mt-0.5 shrink-0" /> {w}
        </p>
      ))}
    </div>
  );
}
