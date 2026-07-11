"use client";
import * as React from "react";
import { cn } from "@/lib/cn";
import { metricHelp } from "@/lib/format";
import { Tip } from "@/components/ui/Tip";

/**
 * Numeric tile with built-in tooltip help looked up from the metric glossary.
 *
 * Usage:
 *   <Stat label="loss" value="0.6184" />
 *   <Stat label="duration" value={fmtDuration(720)} helpKey="duration_s" />
 */
export function Stat({
  label, value, sub, helpKey, tone, muted, className,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  helpKey?: string;
  tone?: "ok" | "warn" | "fail";
  /** No value yet: recede the tile so live numbers lead (shared null-state language). */
  muted?: boolean;
  className?: string;
}) {
  const help = metricHelp(helpKey ?? label);
  const toneBorder = tone === "ok" ? "border-l-emerald-500" :
                     tone === "warn" ? "border-l-amber-500" :
                     tone === "fail" ? "border-l-red-500" : "";
  return (
    <div
      className={cn(
        "rounded-xl border p-4 shadow-card",
        muted ? "border-ink-200/70 bg-card/50" : "bg-card border-ink-200",
        tone && "border-l-4", toneBorder, className,
      )}
    >
      <div className={cn("flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider",
        muted ? "text-ink-400" : "text-ink-500")}>
        <span>{label}</span>
        {help ? <Tip text={help} /> : null}
      </div>
      <div className={cn("mt-1 text-2xl font-extrabold tabular-nums",
        muted ? "text-ink-400" : "text-ink")}>
        {value}
      </div>
      {sub ? <div className="text-xs text-ink-500 mt-1">{sub}</div> : null}
    </div>
  );
}
