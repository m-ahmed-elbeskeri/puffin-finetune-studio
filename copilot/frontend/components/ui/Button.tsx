"use client";
import * as React from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANT_STYLES: Record<Variant, string> = {
  // Solid Klein-blue with paper-coloured text (ink-50 inverts to stay legible
  // on the accent in both light and dark). text-ink here reads as faded purple.
  primary:
    "bg-accent text-ink-50 hover:bg-accent-600 font-semibold shadow-glow",
  secondary:
    "bg-ink-50 text-ink border border-ink-200 hover:bg-ink-100",
  ghost:
    "bg-transparent text-ink hover:bg-ink-100",
  danger:
    "bg-fail text-ink-50 hover:bg-red-700",
};

const SIZE_STYLES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
  lg: "h-11 px-5 text-base",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ className, variant = "secondary", size = "md", ...rest }, ref) {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-lg transition-colors",
          // Disabled reads as clearly inert grey (not a dimmed primary), so an
          // enabled solid-blue CTA is never confused with a locked one.
          "disabled:cursor-not-allowed disabled:border-transparent disabled:bg-ink-200",
          "disabled:text-ink-400 disabled:shadow-none disabled:hover:bg-ink-200",
          VARIANT_STYLES[variant], SIZE_STYLES[size], className,
        )}
        {...rest}
      />
    );
  },
);
