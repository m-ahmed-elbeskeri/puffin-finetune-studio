"use client";
/**
 * Settings: the YAML config + profile browser and the backend API key. Configs
 * are edited through the copilot (so it validates + backs up), so this view is
 * read + copy + "ask the AI to change it".
 */
import * as React from "react";
import useSWR from "swr";
import { Check, ChevronRight, Copy, FileCode2, KeyRound, Sparkles } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { useUiStore } from "@/lib/stores/uiStore";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

export default function SettingsPage() {
  const { data: list } = useSWR("configs", () => api.configs());
  const [picked, setPicked] = React.useState<string | null>(null);
  // config_read only accepts forward-slash paths; the list gives Windows ones.
  const norm = picked ? picked.replace(/\\/g, "/") : null;
  const { data: cfg } = useSWR(norm ? `cfg:${norm}` : null, () => api.config(norm!));
  const openDrawer = useUiStore((s) => s.openDrawer);

  const [apiKey, setApiKey] = React.useState("");
  const [savedKey, setSavedKey] = React.useState(false);
  React.useEffect(() => {
    setApiKey(window.localStorage.getItem("puffin_copilot_api_key") ?? "");
  }, []);
  React.useEffect(() => {
    if (!picked && list?.files.length) setPicked(list.files[0].path);
  }, [picked, list]);

  const saveKey = () => {
    window.localStorage.setItem("puffin_copilot_api_key", apiKey);
    setSavedKey(true);
    window.setTimeout(() => setSavedKey(false), 2_500);
  };

  const files = list?.files ?? [];
  const configs = files.filter((f) => f.path.replace(/\\/g, "/").startsWith("configs/"));
  const profiles = files.filter((f) => f.path.replace(/\\/g, "/").startsWith("profiles/"));
  const other = files.filter((f) => !configs.includes(f) && !profiles.includes(f));

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold text-ink">Settings</h1>
        <p className="text-sm text-ink-500 mt-1">
          Config files and profiles. Edits go through the copilot so it validates
          and keeps a backup before writing.
        </p>
      </div>

      {/* Collapsed by default so the file editor owns the page. */}
      <details className="group rounded-xl border border-ink-200 bg-card shadow-card">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm font-bold">
          <KeyRound size={14} className="text-amber-600" /> Backend API key
          <span className="ml-auto text-[11px] font-normal text-ink-400">
            {apiKey ? "set" : "optional"}
          </span>
          <ChevronRight size={14} className="text-ink-400 transition-transform group-open:rotate-90" />
        </summary>
        <div className="space-y-2 border-t border-ink-100 px-4 py-3">
          <p className="text-xs text-ink-500">
            Only needed if the backend was started with <code>PUFFIN_COPILOT_API_KEY</code> set.
            Stored in this browser&apos;s localStorage.
          </p>
          <div className="flex gap-2">
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
              className="flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm font-mono focus:border-accent focus:outline-none"
              placeholder="leave blank if the backend has no auth" />
            <Button onClick={saveKey} variant="primary">
              {savedKey ? <><Check size={14} /> Saved</> : "Save"}
            </Button>
          </div>
          {savedKey ? <p className="text-[11px] text-emerald-700">Saved. Reload to apply.</p> : null}
        </div>
      </details>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[16rem_1fr]">
        {/* File list */}
        <Card className="h-fit">
          <CardHeader className="text-sm font-bold">Files</CardHeader>
          <CardBody className="space-y-3">
            <FileGroup label="Configs" files={configs} picked={picked} onPick={setPicked} />
            <FileGroup label="Profiles" files={profiles} picked={picked} onPick={setPicked} />
            {other.length ? <FileGroup label="Other" files={other} picked={picked} onPick={setPicked} /> : null}
          </CardBody>
        </Card>

        {/* Viewer */}
        <Card>
          <CardHeader className="flex flex-wrap items-center gap-2 text-sm font-bold">
            <FileCode2 size={14} className="text-amber-600" />
            <code className="text-[13px]">{norm ?? "no file selected"}</code>
            <div className="ml-auto flex items-center gap-2">
              {picked ? (
                <Button size="sm" variant="secondary"
                  onClick={() => openDrawer(`Open ${norm}, explain what it controls, and help me change it. Apply edits with config_edit (it validates and backs up).`)}>
                  <Sparkles size={13} className="text-coral" /> Edit with Copilot
                </Button>
              ) : null}
              {cfg ? <CopyBtn text={cfg.text} /> : null}
              <span className="rounded border border-ink-200 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink-400">
                read-only here
              </span>
            </div>
          </CardHeader>
          <CardBody>
            {cfg ? (
              <div className="relative">
                <pre className="max-h-[64vh] overflow-auto rounded-lg bg-sidebar p-3 font-mono text-[11px] leading-relaxed text-white/90">
                  {cfg.text}
                </pre>
                {/* Fade hint that the panel scrolls beyond the fold. */}
                <div className="pointer-events-none absolute inset-x-1 bottom-1 h-8 rounded-b-lg
                                bg-gradient-to-t from-sidebar to-transparent" />
              </div>
            ) : (
              <div className="py-10 text-center text-sm text-ink-400">Pick a file to view it.</div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function FileGroup({
  label, files, picked, onPick,
}: {
  label: string;
  files: Array<{ path: string; bytes: number }>;
  picked: string | null;
  onPick: (p: string) => void;
}) {
  if (files.length === 0) return null;
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-bold uppercase tracking-wider text-ink-400">{label}</div>
      {files.map((f) => {
        const name = f.path.replace(/\\/g, "/").split("/").pop();
        return (
          <button key={f.path} type="button" onClick={() => onPick(f.path)}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors",
              picked === f.path
                ? "bg-accent/15 font-semibold text-ink shadow-[inset_3px_0_0_rgb(var(--acc-500))]"
                : "text-ink-600 hover:bg-ink-50",
            )}>
            <span className="min-w-0 flex-1 truncate font-mono">{name}</span>
            <span className="shrink-0 text-[10px] text-ink-400">{(f.bytes / 1024).toFixed(1)}k</span>
          </button>
        );
      })}
    </div>
  );
}

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <button type="button"
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1_400); }
        catch { /* clipboard unavailable */ }
      }}
      className="inline-flex items-center gap-1 rounded-lg border border-ink-200 px-2 py-1 text-[11px] font-semibold text-ink-500 hover:border-accent hover:text-ink">
      {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />} Copy
    </button>
  );
}
