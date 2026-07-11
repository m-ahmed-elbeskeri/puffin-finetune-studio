"use client";
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { LayoutDashboard, Activity, Database, FlaskConical, History, Rocket, Send, Settings, BookOpen, Wrench, Compass, List, Sparkle, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { useLiveTraining } from "@/lib/hooks/useLiveTraining";
import { useUiStore } from "@/lib/stores/uiStore";
import type { ProjectStatus, StepStatus } from "@/lib/types";
import { ProjectPicker } from "./ProjectPicker";
import { ThemeToggle } from "./ThemeToggle";

type StepKey = "data" | "train" | "evaluate" | "deploy" | "monitor";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  // If present, the item's enabled-state is driven by this pipeline step.
  stepKey?: StepKey;
  // Optional reason shown as a tooltip when the step is blocked.
  blockedHint?: string;
}

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  // Project brief sits before the pipeline: it frames everything below.
  { href: "/overview", label: "Overview", icon: Compass },
  // Pipeline order: data → train → evaluate → deploy → monitor.
  { href: "/data", label: "Data", icon: Database, stepKey: "data" },
  { href: "/train", label: "Train", icon: Wrench, stepKey: "train",
    blockedHint: "Build the data pipeline first." },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/evaluate", label: "Evaluate", icon: FlaskConical, stepKey: "evaluate",
    blockedHint: "Train an adapter first." },
  { href: "/deploy", label: "Deploy", icon: Rocket, stepKey: "deploy",
    blockedHint: "Gate must PASS before deploy." },
  { href: "/monitor", label: "Monitor", icon: Activity, stepKey: "monitor",
    blockedHint: "Deploy something first." },
  // Auxiliary: after the pipeline.
  { href: "/playground", label: "Playground", icon: Send },
  { href: "/settings", label: "Settings", icon: Settings },
];

// The sidebar is a permanently-dark surface in BOTH themes, so its text and
// dots use theme-independent white-alpha (never the invertible `ink` scale).
// Semantic colours (emerald/amber/red) stay — they read on the dark ground.
const STATUS_BADGE: Record<StepStatus, string> = {
  done: "text-emerald-400",
  current: "text-amber-300",
  pending: "text-white/40",
  fail: "text-red-400",
};

const STATUS_DOT: Record<StepStatus, string> = {
  done: "bg-emerald-400",
  current: "bg-amber-300",
  pending: "bg-white/25",
  fail: "bg-red-400",
};

export function Sidebar() {
  const pathname = usePathname();
  const live = useLiveTraining();
  const isTraining = Boolean(live?.active);
  const toggleDrawer = useUiStore((s) => s.toggleDrawer);

  // Below lg the sidebar is an off-canvas drawer opened from the mobile top
  // bar. Any navigation closes it so you land on the new page, not the menu.
  const [navOpen, setNavOpen] = React.useState(false);
  React.useEffect(() => { setNavOpen(false); }, [pathname]);

  // Project status drives the grey-out logic. Cached + revalidated
  // every 10s; SWR de-dupes against the Topbar's same-key subscription.
  const { data } = useSWR<{ status: ProjectStatus }>("state", () => api.state(),
    { refreshInterval: 10_000 });
  const stepsByKey = React.useMemo(() => {
    const m = new Map<StepKey, StepStatus>();
    for (const s of data?.status?.steps ?? []) {
      m.set(s.key as StepKey, s.status);
    }
    return m;
  }, [data?.status?.steps]);

  return (
    <>
      {/* Mobile top bar (hamburger + brand + Ask AI). Hidden from lg up. */}
      <div className="lg:hidden fixed inset-x-0 top-0 z-40 flex h-14 items-center gap-3
                      border-b border-white/10 bg-sidebar px-4 text-white">
        <button type="button" onClick={() => setNavOpen(true)} aria-label="Open menu"
          className="-ml-1.5 p-1.5 text-white/80 hover:text-white">
          <List size={22} />
        </button>
        <div className="min-w-0">
          <div className="text-[9px] font-bold uppercase tracking-widest text-accent leading-none">
            Puffin
          </div>
          <div className="text-sm font-extrabold leading-tight text-white">Fine-tune Studio</div>
        </div>
        <button type="button" onClick={() => toggleDrawer()}
          className="ml-auto inline-flex items-center gap-1.5 bg-accent/25 px-2.5 py-1.5
                     text-xs font-semibold text-white hover:bg-accent/35">
          <Sparkle size={14} /> Ask AI
        </button>
      </div>

      {/* Drawer backdrop (mobile only). */}
      {navOpen ? (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setNavOpen(false)} aria-hidden />
      ) : null}

    <aside className={cn(
      "fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-sidebar text-white/85",
      "transition-transform duration-200 ease-out",
      "lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:w-60 lg:translate-x-0 lg:transition-none",
      navOpen ? "translate-x-0" : "-translate-x-full",
    )}>
      {/* Close button (mobile drawer only). */}
      <button type="button" onClick={() => setNavOpen(false)} aria-label="Close menu"
        className="lg:hidden absolute right-2 top-2 p-1.5 text-white/60 hover:text-white">
        <X size={18} />
      </button>
      <div className="px-4 py-5 border-b border-white/5">
        <div className="text-[10px] uppercase tracking-widest text-accent font-bold">
          Puffin
        </div>
        <div className="text-white font-extrabold text-lg leading-tight mt-1">
          Fine-tune Studio
        </div>
      </div>

      {/* Project switcher: moved here from the (removed) top header. */}
      <div className="px-3 py-3 border-b border-white/5">
        <ProjectPicker />
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {NAV.map((item) => {
          const Active = pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
          const status = item.stepKey ? stepsByKey.get(item.stepKey) : undefined;
          // Blocked = pending step that's not the current focus. Greyed
          // visually + tooltip explains why. Still clickable so the user
          // can peek if they want.
          const isBlocked = status === "pending";

          return (
            <Link
              key={item.href}
              href={item.href}
              title={isBlocked ? item.blockedHint : undefined}
              aria-disabled={isBlocked ? true : undefined}
              className={cn(
                "flex items-center gap-3 px-4 py-2 mx-2 rounded-lg text-sm",
                "transition-colors group",
                Active
                  ? "bg-accent/20 text-white font-semibold"
                  : isBlocked
                    ? "text-white/40 hover:bg-white/5 hover:text-white/80"
                    : "text-white/65 hover:bg-white/5 hover:text-white",
              )}
            >
              <Icon size={16} strokeWidth={2}
                    className={isBlocked ? "opacity-50" : undefined} />
              <span className={cn(
                "flex-1",
                isBlocked && !Active && "opacity-60",
              )}>{item.label}</span>

              {/* Status dot for pipeline items */}
              {status ? (
                <span
                  className={cn(
                    "w-1.5 h-1.5 rounded-full shrink-0",
                    STATUS_DOT[status],
                    status === "current" && "animate-pulseDot",
                  )}
                  aria-label={status}
                />
              ) : null}

              {/* "LIVE" badge on Train/Runs when a training run is active */}
              {(item.href === "/train" || item.href === "/runs") && isTraining ? (
                <span className={cn(
                  "inline-flex items-center gap-1 text-[10px] font-bold",
                  STATUS_BADGE.done,
                )}>
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulseDot" />
                  LIVE
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-3 border-t border-white/5 space-y-2.5">
        {/* Compact status: replaces the training/GPU badges from the old header. */}
        <div className="space-y-1 text-[10px] text-white/55">
          {isTraining ? (
            <div className="flex items-center gap-1.5 font-semibold text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulseDot" />
              Training running
            </div>
          ) : null}
          <div className="flex items-center gap-1.5">
            <span className={cn("w-1.5 h-1.5 rounded-full",
              data?.status?.hardware.gpu.available ? "bg-emerald-400" : "bg-white/25")} />
            {data?.status?.hardware.gpu.available
              ? data.status.hardware.gpu.name?.split(" ").slice(-3).join(" ")
              : "CPU only"}
          </div>
        </div>
        <Link
          href="/docs"
          className="flex items-center gap-2 text-xs text-white/55 hover:text-white"
        >
          <BookOpen size={14} />
          Docs & shortcuts
        </Link>
        <ThemeToggle />
      </div>
    </aside>
    </>
  );
}
