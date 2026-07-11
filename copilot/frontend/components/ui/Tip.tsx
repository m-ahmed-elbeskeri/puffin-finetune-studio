"use client";
import * as React from "react";
import { HelpCircle } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * Styled tooltip: instant on hover/focus, keyboard accessible, no delay
 * and no native-title jank. Wrap any trigger:
 *
 *   <Tip text="p95 latency is what 1-in-20 requests feel."><span>p95</span></Tip>
 *   <Tip text="…" />   // renders a small ? icon as the trigger
 */
export function Tip({
  text, children, side = "top", className,
}: {
  text: string;
  children?: React.ReactNode;
  side?: "top" | "bottom";
  className?: string;
}) {
  if (!text) return <>{children ?? null}</>;
  return (
    <span className={cn("relative inline-flex group/tip", className)} tabIndex={0}>
      {children ?? (
        <HelpCircle
          size={12}
          className="text-ink-400 hover:text-ink-500 cursor-help"
          aria-label="Help"
        />
      )}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 -translate-x-1/2 z-40",
          "w-max max-w-[260px] rounded-lg bg-ink px-2.5 py-1.5",
          "text-[11px] font-medium leading-snug text-ink-50 shadow-lg",
          "opacity-0 scale-95 transition-all duration-100 normal-case tracking-normal text-left whitespace-normal",
          "group-hover/tip:opacity-100 group-hover/tip:scale-100",
          "group-focus-visible/tip:opacity-100 group-focus-visible/tip:scale-100",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {text}
      </span>
    </span>
  );
}
