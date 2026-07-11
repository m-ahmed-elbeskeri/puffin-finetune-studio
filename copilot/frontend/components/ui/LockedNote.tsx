"use client";
import * as React from "react";
import { Lock, Copy, Check } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

const ENV_TOKEN = "PUFFIN_COPILOT_ENABLE_DANGEROUS=1";

/**
 * The single canonical "state-changing tools are locked" note. One caution
 * treatment (amber/gold hairline + lock icon, NOT coral — coral is reserved
 * for failure/error) reused on every page so the lock message reads the same
 * everywhere. `action` names what is blocked, e.g. "Running evals",
 * "Launching training", "Building splits". The env token carries a one-click
 * copy so the fix is a paste away from any page.
 */
export function LockedNote({
  action, className,
}: {
  action: string;
  className?: string;
}) {
  const [copied, setCopied] = React.useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(ENV_TOKEN).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border-l-2 border-warn/60",
        "bg-warn/10 px-2.5 py-1 text-[11px] leading-tight text-ink-600",
        className,
      )}
    >
      <Lock size={12} className="shrink-0 text-warn" />
      <span className="min-w-0">
        {action} is locked (state-changing tools disabled).
      </span>
      <span className="inline-flex shrink-0 items-center overflow-hidden rounded border border-warn/30">
        <code className="bg-card px-1.5 py-px font-mono text-[10px] [overflow-wrap:anywhere]">
          {ENV_TOKEN}
        </code>
        <button
          type="button"
          onClick={copy}
          title="Copy, then restart the backend to unlock"
          aria-label="Copy env var"
          className="flex shrink-0 items-center gap-1 border-l border-warn/30 bg-warn/10
                     px-1.5 py-px font-semibold text-warn transition-colors hover:bg-warn/20"
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? "copied" : "copy"}
        </button>
      </span>
    </div>
  );
}
