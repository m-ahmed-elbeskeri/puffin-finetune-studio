"use client";
import * as React from "react";
import useSWR from "swr";
import { AlertCircle, ArrowRight, BadgeCheck, ChevronDown, ChevronRight, Database, Download, FileText, Loader2, Lock, Play, RotateCcw, Scissors, Settings2, Shuffle, Sparkles, X } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { revalidateData } from "@/lib/revalidate";
import { cn } from "@/lib/cn";
import type { DataPipelineResultPayload } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { LockedNote } from "@/components/ui/LockedNote";
import { useUiStore } from "@/lib/stores/uiStore";

interface DataFile {
  path: string; name: string; kind: string;
  size_bytes: number; mtime: string; line_count: number;
  schema_hint: string;
}

// The pipeline's core stages. Redaction + dedupe are NOT here: they're
// editable script templates the user runs on raw data first.
const STAGES = [
  { key: "ingest", label: "Ingest", icon: Download,
    help: "Collect every source JSONL from data/raw/ into one interim file." },
  { key: "validate", label: "Validate", icon: BadgeCheck,
    help: "Check records against the schema contract; reject malformed rows and forbidden licenses." },
  { key: "split", label: "Split", icon: Scissors,
    help: "Deterministic train / eval / test split into data/processed/, using the ratios you set." },
  { key: "build_dataset_card", label: "Card", icon: FileText,
    help: "Write dataset_cards/generated.md documenting sources, counts, and processing." },
] as const;

type StageState = "idle" | "running" | "ok" | "fail" | "skipped";

export function PipelineRunner({
  raw, processed, dangerousEnabled, onDone,
}: {
  raw: DataFile[];
  processed: DataFile[];
  dangerousEnabled: boolean | undefined;
  onDone: () => void;
}) {
  const openDrawer = useUiStore((s) => s.openDrawer);
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<DataPipelineResultPayload | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [showConfig, setShowConfig] = React.useState(false);

  const rawRecords = raw.reduce((s, f) => s + f.line_count, 0);
  const split = (name: string) =>
    processed.find((f) => f.name === `${name}.jsonl`)?.line_count;
  const train = split("train");
  const ready = (train ?? 0) > 0;
  const locked = dangerousEnabled === false;

  const run = async () => {
    setRunning(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api.runDataPipeline();
      if (r.kind === "error") {
        setErr(r.message);
      } else {
        setResult(r);
        if (!r.all_ok) setErr("Pipeline stopped at a failing stage: open its log below.");
      }
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const stageState = (key: string): StageState => {
    if (running) return "running";
    if (!result) return "idle";
    const s = result.stages.find((x) => x.stage === key);
    if (!s) return "skipped";
    return s.ok ? "ok" : "fail";
  };

  return (
    <Card>
      <CardBody className="space-y-4">
        {/* Stage rail */}
        <div className="flex flex-wrap items-center gap-1">
          {STAGES.map((s, i) => {
            const st = stageState(s.key);
            const Icon = s.icon;
            return (
              <React.Fragment key={s.key}>
                {i > 0 ? (
                  <div className={cn(
                    "h-px w-3 shrink-0 sm:w-5",
                    st === "ok" ? "bg-emerald-300" : "bg-ink-200",
                  )} />
                ) : null}
                <div
                  title={s.help}
                  className={cn(
                    "flex items-center gap-1.5 rounded-lg border px-2 py-1.5",
                    "text-[11px] font-semibold transition-colors",
                    st === "ok" && "border-emerald-200 bg-emerald-50 text-emerald-700",
                    st === "fail" && "border-red-200 bg-red-50 text-red-700",
                    st === "running" && "border-amber-200 bg-amber-50 text-amber-800",
                    st === "skipped" && "border-ink-100 bg-ink-50 text-ink-300",
                    st === "idle" && "border-ink-200 bg-card text-ink-500",
                  )}
                >
                  {st === "running"
                    ? <Loader2 size={11} className="animate-spin" />
                    : <Icon size={11} />}
                  <span className="hidden sm:inline">{s.label}</span>
                </div>
              </React.Fragment>
            );
          })}
          <span className="ml-1 hidden text-[10px] text-ink-400 lg:inline">
            need redaction or dedup? run a script template first
          </span>
        </div>

        {/* Split ratio controls */}
        <SplitControls />

        {/* Input → Build → Output: the transformation this step performs. */}
        <div className="rounded-xl border border-ink-200 bg-card/50 p-3 sm:p-4">
          <div className="flex flex-col items-stretch gap-3 lg:flex-row lg:items-center">
            {/* Raw input */}
            <div className={cn(
              "flex-1 rounded-lg border px-4 py-3 transition-colors",
              raw.length ? "border-ink-200 bg-card"
                : "border-dashed border-amber-300 bg-amber-50/40",
            )}>
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-400">
                <Database size={11} /> Raw input
              </div>
              <div className="mt-1 text-base font-extrabold tabular-nums text-ink">
                {raw.length
                  ? `${raw.length} file${raw.length === 1 ? "" : "s"} · ${rawRecords.toLocaleString()} records`
                  : "no data yet"}
              </div>
              <div className="text-[10px] text-ink-400">
                {raw.length ? "in data/raw/" : "add some above to begin"}
              </div>
            </div>

            {/* Connector + the action that transforms input into output */}
            <div className="flex shrink-0 items-center justify-center gap-2">
              <ArrowRight size={18} className="hidden shrink-0 text-ink-300 lg:block" />
              <Button
                variant="primary"
                disabled={running || raw.length === 0 || locked}
                onClick={run}
                title={locked
                  ? "Locked: set PUFFIN_COPILOT_ENABLE_DANGEROUS=1 and restart the backend"
                  : "Rebuild data/processed/ from data/raw/ using configs/data.yaml"}
              >
                {running
                  ? <Loader2 size={14} className="animate-spin" />
                  : locked ? <Lock size={14} /> : <Play size={14} />}
                {running ? "Building…" : "Build splits"}
              </Button>
              <ArrowRight size={18} className="hidden shrink-0 text-ink-300 lg:block" />
            </div>

            {/* Training splits output */}
            <div className={cn(
              "flex-1 rounded-lg border px-4 py-3 transition-colors",
              ready ? "border-emerald-300 bg-emerald-50/60"
                : "border-dashed border-ink-200 bg-ink-50/50",
            )}>
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-400">
                {ready
                  ? <BadgeCheck size={11} className="text-emerald-600" />
                  : <Scissors size={11} />} Training splits
              </div>
              {ready ? (
                <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-base font-extrabold tabular-nums text-ink">
                  <span>train <span className="text-emerald-700">{train?.toLocaleString()}</span></span>
                  <span className="text-ink-300">·</span>
                  <span>eval <span className="text-emerald-700">{split("eval")?.toLocaleString() ?? 0}</span></span>
                  <span className="text-ink-300">·</span>
                  <span>test <span className="text-emerald-700">{split("test")?.toLocaleString() ?? 0}</span></span>
                </div>
              ) : (
                <div className="mt-1 text-base font-extrabold text-ink-400">not built yet</div>
              )}
              <div className="text-[10px] text-ink-400">
                {ready ? "in data/processed/" : "output of the pipeline"}
              </div>
            </div>
          </div>

          {/* Secondary: config + AI, quietly under the flow. */}
          <div className="mt-3 flex items-center justify-end gap-1.5 border-t border-ink-100 pt-2.5">
            <button
              type="button"
              onClick={() => setShowConfig(true)}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px]
                         font-semibold text-ink-500 transition-colors hover:text-ink"
            >
              <Settings2 size={12} /> configs/data.yaml
            </button>
            <button
              type="button"
              onClick={() => openDrawer(
                "Read configs/data.yaml and explain what each setting does for MY "
                + "data specifically: validation, split, and leakage checks. "
                + "Base it on an audit of my raw files.")}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px]
                         font-semibold text-ink-500 transition-colors hover:text-ink"
            >
              <Sparkles size={12} className="text-coral" /> Explain with Copilot
            </button>
          </div>
        </div>

        {locked ? <LockedNote action="Building splits" /> : null}

        {err ? (
          <div className="flex items-start gap-1.5 text-xs text-red-700">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            <span>{err}</span>
          </div>
        ) : null}

        {result ? (
          <div className="space-y-1.5">
            {result.all_ok ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border
                              border-emerald-200 bg-emerald-50 px-3 py-2 text-xs
                              text-emerald-800">
                <BadgeCheck size={14} className="shrink-0" />
                <span className="min-w-0 flex-1 font-semibold">
                  Splits rebuilt and dataset card written.
                </span>
                <button
                  type="button"
                  onClick={() => openDrawer(
                    "The data pipeline just finished. Audit data/processed/train.jsonl "
                    + "and eval.jsonl, check the split sizes are sane, and flag "
                    + "anything I should fix before training.")}
                  className="inline-flex items-center gap-1 rounded-md border
                             border-emerald-300 bg-card px-2 py-1 font-semibold
                             text-emerald-700 hover:bg-emerald-100"
                >
                  <Sparkles size={11} /> Sanity-check with AI
                </button>
              </div>
            ) : null}
            {result.stages.map((s) => (
              <StageLog
                key={s.stage}
                label={STAGES.find((x) => x.key === s.stage)?.label ?? s.stage}
                ok={s.ok}
                exitCode={s.exit_code}
                tail={s.stdout_tail}
              />
            ))}
          </div>
        ) : null}
      </CardBody>

      {showConfig ? (
        <ConfigModal path="configs/data.yaml" onClose={() => setShowConfig(false)} />
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Split ratio controls                                                */
/* ------------------------------------------------------------------ */

function SplitControls() {
  const { data, mutate } = useSWR("data:split", () => api.getSplit());
  const [pct, setPct] = React.useState<{ train: number; eval: number; test: number } | null>(null);
  const [seed, setSeed] = React.useState(42);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  // Seed local editable state from the server once.
  React.useEffect(() => {
    if (!data) return;
    setPct({
      train: Math.round(data.train * 100),
      eval: Math.round(data.eval * 100),
      test: Math.round(data.test * 100),
    });
    setSeed(data.seed);
  }, [data]);

  if (!pct) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-ink-200 bg-ink-50/60 px-3 py-2 text-xs text-ink-400">
        <Loader2 size={12} className="animate-spin" /> Loading split…
      </div>
    );
  }

  const sum = pct.train + pct.eval + pct.test;
  const sumOk = sum === 100;
  const dirty = data
    ? Math.round(data.train * 100) !== pct.train
      || Math.round(data.eval * 100) !== pct.eval
      || Math.round(data.test * 100) !== pct.test
      || data.seed !== seed
    : true;

  const setPart = (key: "train" | "eval" | "test", v: number) => {
    setSaved(false);
    setErr(null);
    setPct((p) => (p ? { ...p, [key]: Math.max(0, Math.min(100, v)) } : p));
  };

  const save = async () => {
    if (!sumOk || saving) return;
    setSaving(true);
    setErr(null);
    try {
      await api.saveSplit({
        train: pct.train / 100, eval: pct.eval / 100,
        test: pct.test / 100, seed,
      });
      setSaved(true);
      void mutate();
      revalidateData();  // split feeds the fingerprint/lineage + inspect cards
      window.setTimeout(() => setSaved(false), 2_000);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    if (!data) return;
    setPct({
      train: Math.round(data.train * 100),
      eval: Math.round(data.eval * 100),
      test: Math.round(data.test * 100),
    });
    setSeed(data.seed);
    setErr(null);
  };

  const bar = (color: string, value: number) => (
    <div className={cn("h-full", color)} style={{ width: `${value}%` }} />
  );

  return (
    <div className="space-y-2 rounded-xl border border-ink-200 bg-card p-3">
      <div className="flex items-center gap-2">
        <Scissors size={13} className="text-ink-400" />
        <span className="text-xs font-bold text-ink">Split ratios</span>
        <span className="text-[10px] text-ink-400">how records divide into train / eval / test</span>
        <span className={cn(
          "ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold tabular-nums",
          sumOk ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700",
        )}>
          {sum}%{sumOk ? "" : ": must total 100%"}
        </span>
      </div>

      {/* Proportion bar */}
      <div className="flex h-2 overflow-hidden rounded-full bg-ink-100">
        {bar("bg-amber-500", pct.train)}
        {bar("bg-teal", pct.eval)}
        {bar("bg-ink-400", pct.test)}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(["train", "eval", "test"] as const).map((k) => (
          <label key={k} className="flex flex-col gap-0.5">
            <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-ink-500">
              <span className={cn(
                "h-2 w-2 rounded-full",
                k === "train" ? "bg-amber-500" : k === "eval" ? "bg-teal" : "bg-ink-400",
              )} />
              {k}
            </span>
            <div className="flex items-center rounded-lg border border-ink-200 bg-card
                            focus-within:border-accent">
              <input
                type="number"
                min={0}
                max={100}
                value={pct[k]}
                onChange={(e) => setPart(k, Math.round(Number(e.target.value) || 0))}
                className="w-full bg-transparent px-2 py-1.5 text-sm tabular-nums
                           focus:outline-none"
              />
              <span className="pr-2 text-xs text-ink-400">%</span>
            </div>
          </label>
        ))}
        <label className="flex flex-col gap-0.5">
          <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-ink-500">
            <Shuffle size={9} /> seed
          </span>
          <input
            type="number"
            min={0}
            value={seed}
            onChange={(e) => { setSaved(false); setSeed(Math.max(0, Math.round(Number(e.target.value) || 0))); }}
            className="rounded-lg border border-ink-200 bg-card px-2 py-1.5 text-sm
                       tabular-nums focus:border-accent focus:outline-none"
          />
        </label>
      </div>

      <div className="flex items-center gap-2">
        {err ? (
          <span className="flex items-center gap-1 text-[11px] text-red-700">
            <AlertCircle size={11} /> {err}
          </span>
        ) : saved ? (
          <span className="flex items-center gap-1 text-[11px] text-emerald-700">
            <BadgeCheck size={11} /> Saved to configs/data.yaml
          </span>
        ) : (
          <span className="text-[10px] text-ink-400">
            Applies on the next <b>Build splits</b> run.
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {dirty ? (
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px]
                         font-semibold text-ink-400 hover:text-ink"
            >
              <RotateCcw size={11} /> Reset
            </button>
          ) : null}
          <Button
            variant={dirty && sumOk ? "primary" : "secondary"}
            size="sm"
            onClick={save}
            disabled={!sumOk || !dirty || saving}
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : null}
            Save split
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function StageLog({
  label, ok, exitCode, tail,
}: {
  label: string; ok: boolean; exitCode: number; tail: string;
}) {
  const [open, setOpen] = React.useState(!ok);
  return (
    <div className={cn(
      "rounded-lg border text-xs",
      ok ? "border-ink-200 bg-card" : "border-red-200 bg-red-50/40",
    )}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className={cn("font-semibold", ok ? "text-ink-700" : "text-red-700")}>
          {label}
        </span>
        <span className="text-ink-400">exit {exitCode}</span>
        <span className={cn(
          "ml-auto rounded px-1.5 py-px text-[10px] font-bold",
          ok ? "bg-emerald-50 text-emerald-700" : "bg-red-100 text-red-700",
        )}>
          {ok ? "OK" : "FAILED"}
        </span>
      </button>
      {open && tail ? (
        <pre className="max-h-56 overflow-auto border-t border-ink-100 bg-ink-50 p-2
                        font-mono text-[11px] leading-relaxed">
          {tail}
        </pre>
      ) : null}
    </div>
  );
}

function ConfigModal({ path, onClose }: { path: string; onClose: () => void }) {
  const { data, error } = useSWR(`config:${path}`, () => api.config(path));
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden
                   rounded-2xl border border-ink-200 bg-card shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
          <Settings2 size={14} className="text-ink-400" />
          <code className="text-sm font-bold text-ink">{path}</code>
          <span className="text-[10px] text-ink-400">
            drives every pipeline stage
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {error ? (
            <div className="text-xs text-red-700">{String(error)}</div>
          ) : !data ? (
            <div className="flex items-center gap-2 text-xs text-ink-500">
              <Loader2 size={12} className="animate-spin" /> Loading…
            </div>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-ink-800">
              {data.text}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
