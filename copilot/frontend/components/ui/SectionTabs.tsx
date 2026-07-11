"use client";
import * as React from "react";
import { cn } from "@/lib/cn";

export interface SectionTab {
  key: string;
  label: React.ReactNode;
  icon?: React.ComponentType<{ size?: number; className?: string }>;
  badge?: React.ReactNode;
}

/**
 * Riso section tabs — the top-of-page switcher that replaces long vertical
 * scrolls of stacked sub-sections. The active marker is drawn in two inks:
 * a blue pill and a coral ghost that lags then settles (see .rtabs-* in
 * globals.css). Panels enter from the travel direction; children stagger up.
 *
 * Controlled (`value` + `onChange`) or uncontrolled. Full tablist a11y:
 * roving tabindex, arrow / Home / End keys, visible focus. Honours
 * prefers-reduced-motion via the global reduced-motion rule.
 */
export function SectionTabs({
  tabs,
  panels,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  tabs: SectionTab[];
  panels: Record<string, React.ReactNode>;
  value?: string;
  onChange?: (key: string) => void;
  ariaLabel?: string;
  className?: string;
}) {
  const [internal, setInternal] = React.useState(tabs[0]?.key ?? "");
  const active = value ?? internal;
  const activeIndex = Math.max(0, tabs.findIndex((t) => t.key === active));

  // Travel direction: compare the new active index against the previous one so
  // panels slide in from the side you're moving toward.
  const prevIndexRef = React.useRef(activeIndex);
  const forward = activeIndex >= prevIndexRef.current;

  const stripRef = React.useRef<HTMLDivElement>(null);
  const btnRefs = React.useRef<Array<HTMLButtonElement | null>>([]);
  const indRef = React.useRef<HTMLSpanElement>(null);
  const ghostRef = React.useRef<HTMLSpanElement>(null);

  const place = React.useCallback(() => {
    const btn = btnRefs.current[activeIndex];
    if (!btn) return;
    const x = btn.offsetLeft;
    const w = btn.offsetWidth;
    [indRef.current, ghostRef.current].forEach((el) => {
      if (!el) return;
      el.style.setProperty("--rx", `${x}px`);
      el.style.setProperty("--rw", `${w}px`);
    });
  }, [activeIndex]);

  React.useLayoutEffect(() => { place(); }, [place]);
  React.useEffect(() => {
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [place]);

  function select(i: number, focus?: boolean) {
    const k = tabs[i]?.key;
    if (!k) return;
    prevIndexRef.current = activeIndex;
    if (value === undefined) setInternal(k);
    onChange?.(k);
    if (focus) btnRefs.current[i]?.focus();
  }

  function onKey(e: React.KeyboardEvent, i: number) {
    let n: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = tabs.length - 1;
    if (n !== null) { e.preventDefault(); select(n, true); }
  }

  return (
    <div className={className}>
      <div
        ref={stripRef}
        role="tablist"
        aria-label={ariaLabel}
        className="relative flex flex-wrap gap-1 border-b-2 border-ink-200"
      >
        <span ref={ghostRef} className="rtabs-ghost" aria-hidden />
        <span ref={indRef} className="rtabs-ind" aria-hidden />
        {tabs.map((t, i) => {
          const on = t.key === active;
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              role="tab"
              type="button"
              aria-selected={on}
              tabIndex={on ? 0 : -1}
              ref={(el) => { btnRefs.current[i] = el; }}
              onClick={() => select(i)}
              onKeyDown={(e) => onKey(e, i)}
              className={cn(
                "relative z-[2] -mb-0.5 flex items-center gap-2 whitespace-nowrap px-4 py-2.5",
                "font-display text-[15px] font-semibold uppercase tracking-wide",
                "transition-[color,transform] duration-300 ease-out",
                on
                  ? "text-ink-50"
                  : "text-ink-500 hover:-translate-y-px hover:text-ink",
              )}
            >
              {Icon ? <Icon size={15} /> : null}
              <span>{t.label}</span>
              {t.badge}
            </button>
          );
        })}
      </div>

      <div className="pt-5">
        {/* key forces a remount so the entrance animation replays each switch */}
        <div key={active} className={cn("rtab-panel", !forward && "rev")}>
          {panels[active]}
        </div>
      </div>
    </div>
  );
}
