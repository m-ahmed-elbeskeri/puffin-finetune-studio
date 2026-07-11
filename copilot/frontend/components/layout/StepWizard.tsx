"use client";
import * as React from "react";
import { Check, CaretLeft, CaretRight } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

/**
 * The shared "studio" shell used by Train, Data, Evaluate and Deploy: a left
 * step-rail beside the content. It's a paged wizard — only the active step's
 * section is shown; clicking a rail item (or Back / Next) opens that section.
 * Page-level state lives in the page, so switching steps never loses run
 * results or edits — sections are just the presentation for each step.
 *
 * Children are the <WizardSection> for each step, in `steps` order. Any other
 * child (a modal, a banner) is rendered on every step so overlays keep working.
 */

export type StepStatus = "done" | "current" | "pending" | "optional";

export interface WizardStepDef {
  id: string;
  label: string;
  status?: StepStatus;
  badge?: React.ReactNode;
}

export function StepWizard({
  steps, children,
}: {
  steps: WizardStepDef[];
  children: React.ReactNode;
}) {
  const [active, setActive] = React.useState(steps[0]?.id);
  const topRef = React.useRef<HTMLDivElement>(null);

  // If the steps change and the active one disappears, fall back to the first.
  React.useEffect(() => {
    if (!steps.some((s) => s.id === active)) setActive(steps[0]?.id);
  }, [steps, active]);

  const idx = Math.max(0, steps.findIndex((s) => s.id === active));

  // Travel direction drives the panel slide (see .rtab-panel in globals.css).
  const prevIdxRef = React.useRef(idx);
  const forward = idx >= prevIdxRef.current;

  // Two-ink indicator: measure the active tab and drive --rx/--rw.
  const stripRef = React.useRef<HTMLDivElement>(null);
  const btnRefs = React.useRef<Array<HTMLButtonElement | null>>([]);
  const indRef = React.useRef<HTMLSpanElement>(null);
  const ghostRef = React.useRef<HTMLSpanElement>(null);
  const place = React.useCallback(() => {
    const btn = btnRefs.current[idx];
    if (!btn) return;
    [indRef.current, ghostRef.current].forEach((el) => {
      if (!el) return;
      el.style.setProperty("--rx", `${btn.offsetLeft}px`);
      el.style.setProperty("--rw", `${btn.offsetWidth}px`);
    });
  }, [idx]);
  React.useLayoutEffect(() => { place(); }, [place]);
  React.useEffect(() => {
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [place]);

  const select = (id: string | undefined) => {
    if (!id) return;
    prevIdxRef.current = idx;
    setActive(id);
    // Reset scroll to the top of the wizard so a tall previous step doesn't
    // leave you scrolled past the new (shorter) one.
    topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const onKey = (e: React.KeyboardEvent, i: number) => {
    let n: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % steps.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + steps.length) % steps.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = steps.length - 1;
    if (n !== null) { e.preventDefault(); select(steps[n]?.id); btnRefs.current[n]?.focus(); }
  };

  const items = React.Children.toArray(children);
  const sections = items.filter(
    (c) => React.isValidElement(c) && c.type === WizardSection);
  const passthrough = items.filter(
    (c) => !(React.isValidElement(c) && c.type === WizardSection));
  const isFirst = idx === 0;
  const isLast = idx === steps.length - 1;

  return (
    <div ref={topRef} className="scroll-mt-6">
      {/* Top tab strip — the step nav, printed in two inks. */}
      <div
        ref={stripRef} role="tablist" aria-label="Steps"
        className="relative flex flex-wrap gap-1 border-b-2 border-ink-200"
      >
        <span ref={ghostRef} className="rtabs-ghost" aria-hidden />
        <span ref={indRef} className="rtabs-ind" aria-hidden />
        {steps.map((s, i) => {
          const on = s.id === active;
          const done = s.status === "done" && !on;
          return (
            <button
              key={s.id} type="button" role="tab"
              aria-selected={on} aria-current={on ? "step" : undefined}
              tabIndex={on ? 0 : -1}
              ref={(el) => { btnRefs.current[i] = el; }}
              onClick={() => select(s.id)}
              onKeyDown={(e) => onKey(e, i)}
              className={cn(
                "relative z-[2] -mb-0.5 flex items-center gap-2 whitespace-nowrap px-3.5 py-2.5",
                "font-display text-[15px] font-semibold uppercase tracking-wide",
                "transition-[color,transform] duration-300 ease-out",
                on ? "text-ink-50" : "text-ink-500 hover:-translate-y-px hover:text-ink",
              )}
            >
              <span className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                on ? "bg-ink-50/25 text-ink-50"
                   : done ? "bg-emerald-100 text-emerald-700"
                   : "bg-ink-100 text-ink-500",
              )}>
                {done ? <Check size={11} weight="bold" /> : i + 1}
              </span>
              <span>{s.label}</span>
              {s.badge != null ? (
                <span className={cn(
                  "rounded-full px-1.5 text-[9px] font-bold tabular-nums",
                  on ? "bg-coral text-white" : "bg-coral/15 text-coral",
                )}>
                  {s.badge}
                </span>
              ) : s.status === "optional" ? (
                <span className="text-[9px] uppercase tracking-wide opacity-70">opt</span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="min-w-0 pt-5">
        {/* Only the active section renders; keyed so the entrance replays.
           A min-height frames short steps so the Back/Next footer anchors at a
           natural depth instead of floating high over empty page; tall steps
           grow past it (min-height never clips). */}
        <div key={active} className={cn("rtab-panel min-h-[24rem]", !forward && "rev")}>
          {sections.map((child) => {
            const sectionId = React.isValidElement(child)
              ? (child.props as { id?: string }).id : undefined;
            return sectionId === active ? child : null;
          })}
        </div>

        {/* Modals, banners: render on every step so overlays keep working. */}
        {passthrough}

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-ink-100 pt-4">
          <Button size="sm" variant="secondary"
            disabled={isFirst} onClick={() => select(steps[idx - 1]?.id)}>
            <CaretLeft size={14} /> Back
          </Button>
          <span className="text-[11px] text-ink-400">
            Step {idx + 1} of {steps.length}
          </span>
          {!isLast ? (
            // Secondary, not primary: wizard nav must not compete with each
            // page's solid-blue content action (only one primary per screen).
            <Button size="sm" variant="secondary"
              className="ml-auto font-semibold text-accent-600 hover:text-accent"
              onClick={() => select(steps[idx + 1]?.id)}>
              Next <CaretRight size={14} />
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function WizardSection({
  id, title, hint, status = "pending", action, children,
}: {
  id: string;
  /** Retained for API compatibility; the tab now carries the step number. */
  n?: number;
  title: string;
  hint?: React.ReactNode;
  status?: StepStatus;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  // No number circle / indent here anymore: the top tab already shows the
  // step number and its done/current state, so the panel is a clean section.
  return (
    <section id={id} className="scroll-mt-6 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-extrabold text-ink">{title}</h2>
        {status === "optional" ? (
          <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink-500">
            optional
          </span>
        ) : null}
        {action ? <div className="ml-auto">{action}</div> : null}
      </div>
      {hint ? (
        <p className="-mt-1 max-w-prose text-xs leading-relaxed text-ink-500">{hint}</p>
      ) : null}
      <div className="space-y-3">{children}</div>
    </section>
  );
}
