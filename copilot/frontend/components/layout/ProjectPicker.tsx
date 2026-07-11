"use client";
import * as React from "react";
import useSWR from "swr";
import { ChevronDown, FolderOpen, Plus, Check, Trash2, Sparkles } from "@/components/ui/icons";
import {
  api, getCurrentProjectId, setCurrentProjectId, type ProjectRow,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

type CreateMode = "existing" | "scaffold";

/**
 * Project switcher. Lives in the topbar. Lists every registered project,
 * lets the user switch (persists to localStorage so every API call carries
 * `project_id=...`), and opens an inline "+ New project" form.
 *
 * When the user switches we force a full reload: every SWR cache key was
 * scoped to the previous project, simpler than invalidating each one.
 *
 * Two ways to add a project:
 *   - "Existing folder"   → POST /api/projects (path must already be a
 *                            puffin project)
 *   - "Scaffold from template" → POST /api/projects/scaffold (copies
 *                            configs/, profiles/, contracts/, eval sets/,
 *                            empty data/raw/ + artifacts/ into a new path)
 */
export function ProjectPicker() {
  const { data, mutate } = useSWR("projects", () => api.listProjects(),
    { refreshInterval: 30_000 });
  const projects: ProjectRow[] = data?.projects ?? [];
  const [open, setOpen] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const [mode, setMode] = React.useState<CreateMode>("scaffold");
  const [name, setName] = React.useState("");
  const [path, setPath] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const rootRef = React.useRef<HTMLDivElement>(null);

  // Resolve the currently selected project. If none is stored, fall back
  // to the first project the backend reports (auto-seeded default).
  const storedId = typeof window !== "undefined" ? getCurrentProjectId() : null;
  const current = projects.find((p) => p.id === storedId) ?? projects[0];

  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const pick = (id: string) => {
    if (id === current?.id) { setOpen(false); return; }
    setCurrentProjectId(id);
    setOpen(false);
    // Hard reload so every SWR-cached panel re-fetches under the new project.
    window.location.reload();
  };

  const submit = async () => {
    setErr(null);
    if (!name.trim() || !path.trim()) {
      setErr("Both fields are required.");
      return;
    }
    setBusy(true);
    try {
      const body = { name: name.trim(), path: path.trim() };
      const resp = mode === "scaffold"
        ? await api.scaffoldProject(body)
        : await api.createProject(body);
      setCurrentProjectId(resp.project.id);
      await mutate();
      setCreating(false); setName(""); setPath("");
      window.location.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Remove this project from the picker? (files on disk are untouched)")) return;
    await api.deleteProject(id);
    if (storedId === id) setCurrentProjectId(null);
    await mutate();
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "h-8 w-full inline-flex items-center gap-2 rounded-lg border border-ink-200",
          "bg-card px-3 text-sm font-semibold text-ink hover:border-accent",
          "transition-colors justify-between",
        )}
      >
        <FolderOpen size={13} className="text-amber-500 shrink-0" />
        <span className="truncate flex-1 text-left">{current?.name ?? "Select project"}</span>
        <ChevronDown size={12} className="text-ink-500 shrink-0" />
      </button>

      {open ? (
        <div className="absolute z-50 mt-1 left-0 w-96 bg-card border border-ink-200
                        rounded-xl shadow-card overflow-hidden">
          <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider
                          text-ink-500 border-b border-ink-200 flex items-center
                          justify-between">
            <span>Project</span>
            <button
              onClick={() => setCreating(true)}
              className="text-amber-700 hover:text-amber-900 inline-flex items-center
                         gap-1 text-[10px] uppercase tracking-wider font-bold"
            >
              <Plus size={11} /> New
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto py-1">
            {projects.length === 0 ? (
              <div className="px-3 py-4 text-xs text-ink-500 text-center">
                No projects. Click <b>+ New</b> above.
              </div>
            ) : null}
            {projects.map((proj) => {
              const isActive = proj.id === (current?.id ?? "");
              return (
                <div
                  key={proj.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => pick(proj.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      pick(proj.id);
                    }
                  }}
                  className={cn(
                    "group w-full text-left px-3 py-2 hover:bg-ink-50",
                    "flex items-start gap-2 cursor-pointer",
                    "focus:outline-none focus:bg-ink-50",
                  )}
                >
                  <Check
                    size={14}
                    className={cn(
                      "mt-1 shrink-0",
                      isActive ? "text-amber-500" : "text-transparent",
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-ink truncate">
                      {proj.name}
                    </div>
                    <div className="text-[11px] text-ink-500 font-mono truncate">
                      {proj.path}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => remove(proj.id, e)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity
                               text-ink-400 hover:text-red-500 p-1"
                    aria-label="Remove project"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })}
          </div>

          {creating ? (
            <div className="border-t border-ink-200 p-3 space-y-2 bg-ink-50">
              <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
                Add a project
              </div>
              <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setMode("scaffold")}
                  className={cn(
                    "rounded-lg border px-2 py-1.5 text-left flex items-start gap-1.5",
                    mode === "scaffold"
                      ? "border-amber-400 bg-amber-100/40"
                      : "border-ink-200 bg-card hover:border-amber-300",
                  )}
                >
                  <Sparkles size={11} className="text-amber-600 mt-0.5 shrink-0" />
                  <div>
                    <div className="font-bold text-ink">Scaffold from template</div>
                    <div className="text-ink-500 text-[10px] leading-snug">
                      Copy configs, profiles, contracts, eval sets into an empty folder.
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setMode("existing")}
                  className={cn(
                    "rounded-lg border px-2 py-1.5 text-left flex items-start gap-1.5",
                    mode === "existing"
                      ? "border-amber-400 bg-amber-100/40"
                      : "border-ink-200 bg-card hover:border-amber-300",
                  )}
                >
                  <FolderOpen size={11} className="text-amber-600 mt-0.5 shrink-0" />
                  <div>
                    <div className="font-bold text-ink">Existing folder</div>
                    <div className="text-ink-500 text-[10px] leading-snug">
                      Already has configs/: just register the path.
                    </div>
                  </div>
                </button>
              </div>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Display name (e.g. customer-support-v2)"
                className="w-full rounded-lg border border-ink-200 px-2 py-1.5 text-sm
                           bg-card focus:outline-none focus:border-accent"
              />
              <div className="flex gap-1.5">
                <input
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  placeholder={mode === "scaffold"
                    ? "Absolute path for the new folder (must not exist or be empty)"
                    : "Absolute path to an existing puffin project"}
                  className="flex-1 rounded-lg border border-ink-200 px-2 py-1.5 text-sm
                             bg-card font-mono focus:outline-none focus:border-accent"
                />
                <button
                  type="button"
                  onClick={async () => {
                    setErr(null);
                    try {
                      const r = await api.pickFolder({
                        title: mode === "scaffold"
                          ? "Choose where to create the new project"
                          : "Choose the existing project folder",
                        initial: path || undefined,
                      });
                      if (r.path) setPath(r.path);
                    } catch (e) {
                      setErr(`Picker unavailable: ${(e as Error).message}`);
                    }
                  }}
                  className="px-2 py-1.5 rounded-lg border border-ink-200 bg-card
                             text-xs font-semibold text-ink-700 hover:border-amber-400
                             hover:text-amber-700 transition-colors flex items-center
                             gap-1 shrink-0"
                  title="Open folder picker"
                >
                  <FolderOpen size={12} />
                  Browse…
                </button>
              </div>
              {err ? (
                <div className="text-[11px] text-red-700">{err}</div>
              ) : null}
              <div className="flex gap-2 justify-end">
                <Button size="sm" variant="ghost"
                        onClick={() => { setCreating(false); setErr(null); }}>
                  Cancel
                </Button>
                <Button size="sm" variant="primary" onClick={submit} disabled={busy}>
                  {busy ? "Working…" : mode === "scaffold" ? "Scaffold" : "Add"}
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
