"use client";
import * as React from "react";
import { cn } from "@/lib/cn";

type Tone = "ok" | "warn" | "fail" | "info" | "muted" | "accent";

const TONES: Record<Tone, string> = {
  ok: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warn: "bg-amber-50 text-amber-700 border-amber-200",
  fail: "bg-red-50 text-red-700 border-red-200",
  info: "bg-cyan-50 text-cyan-700 border-cyan-200",
  muted: "bg-ink-100 text-ink-700 border-ink-200",
  accent: "bg-amber-100 text-amber-900 border-amber-300",
};

export function Badge({
  tone = "muted",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 border px-2 py-0.5",
        "text-[10px] font-bold uppercase tracking-wider",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
