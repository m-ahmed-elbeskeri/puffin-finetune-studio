"use client";
import * as React from "react";
import useSWR from "swr";
import { AlertCircle, BadgeCheck, ChevronDown, ChevronRight, Copy, Download, Loader2, Lock, PackageCheck, Terminal } from "@/components/ui/icons";
import { api, type EnvGroup } from "@/lib/api";
import { iterateSse } from "@/lib/sseClient";
import { cn } from "@/lib/cn";

interface InstallState {
  lines: string[];
  done: number | null; // exit code
  running: boolean;
}

/**
 * Readiness + one-click install for ONE capability group (e.g. local training,
 * or a specific cloud provider's SDK). Shown next to the thing that needs it,
 * so the user only ever sees the dependency for where they chose to run.
 */
export function EnvGroupInstaller({ groupId }: { groupId: string }) {
  const { data, mutate } = useSWR("environment", () => api.environment());
  const { data: caps } = useSWR("capabilities", () => api.capabilities());
  const dangerous = caps?.dangerous_enabled ?? true;
  const [expanded, setExpanded] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [install, setInstall] = React.useState<InstallState | null>(null);
  const logRef = React.useRef<HTMLPreElement>(null);

  const group = data?.groups.find((g) => g.id === groupId);

  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [install?.lines.length]);

  const runInstall = async () => {
    if (!group) return;
    setInstall({ lines: [], done: null, running: true });
    try {
      const resp = await api.installEnvironment(group.id);
      for await (const evt of iterateSse(resp) as AsyncGenerator<{
        event: string; data: { line: string };
      }>) {
        if (evt.event === "log") {
          setInstall((s) => s && { ...s, lines: [...s.lines, evt.data.line] });
        } else if (evt.event === "error") {
          setInstall((s) => s && { ...s, lines: [...s.lines, `! ${evt.data.line}`] });
        } else if (evt.event === "done") {
          setInstall((s) => s && { ...s, done: Number(evt.data.line), running: false });
          void mutate();
        }
      }
    } catch (e) {
      setInstall((s) => s && {
        ...s, running: false, done: -1,
        lines: [...s.lines, `! ${(e as Error).message}`],
      });
    } finally {
      setInstall((s) => s && { ...s, running: false });
    }
  };

  const copy = async () => {
    if (!group) return;
    try {
      await navigator.clipboard.writeText(group.install_command);
      setCopied(true); window.setTimeout(() => setCopied(false), 1_400);
    } catch { /* clipboard unavailable */ }
  };

  if (!data) {
    return (
      <div className="flex items-center gap-2 text-xs text-ink-400">
        <Loader2 size={12} className="animate-spin" /> checking packages…
      </div>
    );
  }
  if (!group) return null;

  // Ready: a quiet one-line confirmation.
  if (group.ready) {
    return (
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
        <PackageCheck size={13} /> {group.label} packages installed
      </div>
    );
  }

  // Not ready: the actionable card.
  return (
    <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <AlertCircle size={14} className="shrink-0 text-amber-600" />
        <span className="text-xs font-semibold text-amber-900">
          {group.label} needs {group.total - group.installed_count} more package
          {group.total - group.installed_count === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="text-[10px] font-semibold text-ink-500 hover:text-ink"
        >
          {expanded ? "hide" : "details"}
        </button>
        {dangerous ? (
          <button
            type="button"
            onClick={runInstall}
            disabled={Boolean(install?.running)}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1
                       text-[11px] font-bold text-ink shadow-glow transition-colors
                       hover:bg-accent-400 disabled:opacity-50"
          >
            {install?.running
              ? <Loader2 size={12} className="animate-spin" />
              : <Download size={12} />}
            Install
          </button>
        ) : (
          <button
            type="button"
            onClick={copy}
            title="Copy the install command to run in your terminal"
            className="ml-auto inline-flex items-center gap-1 rounded-lg border border-ink-200
                       bg-card px-2 py-1 text-[11px] font-semibold text-ink-500 hover:border-accent"
          >
            {copied ? <BadgeCheck size={12} className="text-emerald-600" /> : <Lock size={12} />}
            {copied ? "Copied" : "Copy command"}
          </button>
        )}
      </div>

      {expanded ? (
        <div className="space-y-1">
          {group.packages.map((pkg) => (
            <div key={pkg.pip} className="flex items-center gap-2 text-[11px]">
              {pkg.installed
                ? <BadgeCheck size={11} className="text-emerald-600" />
                : <AlertCircle size={11} className="text-red-500" />}
              <code className="text-ink-700">{pkg.pip}</code>
              <span className="ml-auto tabular-nums text-ink-400">
                {pkg.installed ? (pkg.version ?? "installed") : "missing"}
              </span>
            </div>
          ))}
          <div className="flex items-center gap-1.5 pt-0.5 text-[10px] text-ink-400">
            <Terminal size={10} />
            <code className="truncate">{group.install_command}</code>
          </div>
        </div>
      ) : null}

      {install ? (
        <div>
          <pre
            ref={logRef}
            className="max-h-48 overflow-auto rounded-lg border border-ink-800/50
                       bg-[#0f172a] p-2.5 font-mono text-[11px] leading-relaxed text-slate-100"
          >
            {install.lines.join("\n") || "starting…"}
          </pre>
          {install.done !== null ? (
            <div className={cn(
              "mt-1.5 flex items-center gap-1.5 text-[11px] font-semibold",
              install.done === 0 ? "text-emerald-700" : "text-red-700",
            )}>
              {install.done === 0
                ? <><BadgeCheck size={12} /> Installed. You can launch now.</>
                : <><AlertCircle size={12} /> Install exited with code {install.done}. See the log.</>}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-[10px] text-ink-500">
          Installs into the platform&apos;s Python. This can take a few minutes
          (large packages); you&apos;ll see pip&apos;s output stream here.
        </p>
      )}
    </div>
  );
}

// Re-exported for any caller that still wants the type.
export type { EnvGroup };
