"use client";
/**
 * Ask-AI-anywhere UI:
 *   <AskAIButton prompt="…">Run evals with AI</AskAIButton>
 *      : one-click page actions. Opens the AI side panel (right drawer)
 *         and sends the prompt there, so the user never loses their place.
 *   <AskAIBar />
 *      : Topbar trigger for the side panel (Ctrl/Cmd+K works anywhere).
 */
import * as React from "react";
import { Sparkles } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/lib/stores/uiStore";
import { Button } from "@/components/ui/Button";
import type { ButtonProps } from "@/components/ui/Button";

export function AskAIButton({
  prompt, children, className, variant = "secondary", size = "sm", ...rest
}: ButtonProps & { prompt: string }) {
  const openDrawer = useUiStore((s) => s.openDrawer);
  return (
    <Button
      variant={variant}
      size={size}
      className={className}
      onClick={() => openDrawer(prompt)}
      {...rest}
    >
      <Sparkles size={13} className="text-amber-500" />
      {children}
    </Button>
  );
}

export function AskAIBar() {
  const toggle = useUiStore((s) => s.toggleDrawer);
  const open = useUiStore((s) => s.drawerOpen);
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={open}
      title="Copilot (Ctrl+K)"
      className={cn(
        "inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-xs",
        "font-semibold transition-colors",
        open
          ? "border-accent bg-amber-50 text-amber-800"
          : "border-ink-200 bg-card text-ink-700 hover:border-accent",
      )}
    >
      <Sparkles size={13} className="text-coral" />
      Copilot
      <span className="kbd hidden md:inline-block">Ctrl K</span>
    </button>
  );
}
