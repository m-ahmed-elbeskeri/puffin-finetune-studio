"use client";
import * as React from "react";
import useSWR from "swr";
import { AlertCircle, ArrowRight, Check, CheckCircle2, ChevronDown, ChevronRight, Clock, EyeOff, FileCode2, FilePlus2, Filter, GripVertical, Layers, LayoutTemplate, ListOrdered, Loader2, Lock, Pencil, Play, PlayCircle, Plus, Shuffle, Sparkles, Trash2, Wand2, X } from "@/components/ui/icons";
import {
  api, type TransformChainResult, type TransformRunResult,
  type TransformScript,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtRelative } from "@/lib/format";
import { buildTransformPrompt, TRANSFORM_TEMPLATE } from "@/lib/aiContext";
import {
  CATEGORY_META, templatesByCategory, type TemplateCategory,
  type TransformTemplate,
} from "@/lib/transformTemplates";
import { useUiStore } from "@/lib/stores/uiStore";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

interface DataFile {
  path: string; name: string; kind: string;
  size_bytes: number; mtime: string; line_count: number;
  schema_hint: string;
}

const CATEGORY_ICON: Record<TemplateCategory, typeof EyeOff> = {
  redact: EyeOff,
  dedupe: Layers,
  filter: Filter,
  clean: Wand2,
  map: Shuffle,
};

type EditorState = { name: string; content: string; isNew: boolean } | null;

export function TransformsPanel({
  raw, processed, dangerousEnabled, onFilesChanged,
}: {
  raw: DataFile[];
  processed: DataFile[];
  dangerousEnabled: boolean | undefined;
  onFilesChanged: () => void;
}) {
  const { data, mutate } = useSWR("data:transforms", () => api.listTransforms());
  const scripts = data?.transforms ?? [];
  const locked = dangerousEnabled === false;

  const [editor, setEditor] = React.useState<EditorState>(null);
  const [pickTemplate, setPickTemplate] = React.useState(false);
  const [aiOpen, setAiOpen] = React.useState(false);

  const openBlank = () => setEditor({
    name: "my_script.py", content: TRANSFORM_TEMPLATE, isNew: true,
  });
  const openTemplate = (t: TransformTemplate) => {
    setPickTemplate(false);
    setEditor({ name: t.suggestedName, content: t.code, isNew: true });
  };

  return (
    <Card>
      <CardHeader className="flex items-center gap-3 text-sm font-bold">
        <FileCode2 size={14} className="text-amber-600" />
        Custom scripts
        <span className="font-normal text-[11px] text-ink-500">
          small Python steps that clean up your raw data before the pipeline runs
        </span>
        {locked ? (
          <span
            className="ml-auto inline-flex items-center gap-1 rounded-full border
                       border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px]
                       font-bold text-amber-800"
            title="Set PUFFIN_COPILOT_ENABLE_DANGEROUS=1 and restart the backend to run scripts. Writing and editing them works right now."
          >
            <Lock size={9} /> running is locked
          </span>
        ) : null}
      </CardHeader>
      <CardBody className="space-y-4">
        {/* Teaching intro */}
        <p className="rounded-lg bg-ink-50 px-3 py-2 text-[11px] leading-relaxed text-ink-600">
          A script reads your data one record at a time and writes a cleaned-up
          copy. Each one does a single job (redact private info, drop junk, fix
          the format), and you can stack several so they run one after another.
          The result lands back in <code>data/raw/</code>, ready for the pipeline
          to pick up. Nothing runs until you press a run button, so it is safe to
          experiment.
        </p>

        {/* The ordered pipeline of scripts */}
        {scripts.length > 0 ? (
          <ScriptPipeline
            scripts={scripts}
            raw={raw}
            processed={processed}
            locked={locked}
            onReordered={() => void mutate()}
            onEdit={async (name) => {
              const r = await api.readTransform(name);
              setEditor({ name: r.name, content: r.content, isNew: false });
            }}
            onChanged={() => { void mutate(); onFilesChanged(); }}
          />
        ) : null}

        {/* Add a script */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-bold text-ink">
            <Plus size={13} className="text-amber-600" />
            {scripts.length > 0 ? "Add another script" : "Add your first script"}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <AddOption
              icon={LayoutTemplate}
              title="From a template"
              blurb="Pick a ready-made script and tweak it. The fastest start."
              accent
              onClick={() => setPickTemplate(true)}
            />
            <AddOption
              icon={Sparkles}
              title="With AI"
              blurb="Describe what you need in plain words and let AI write it."
              onClick={() => setAiOpen((v) => !v)}
              active={aiOpen}
            />
            <AddOption
              icon={FilePlus2}
              title="Blank script"
              blurb="Start from an empty skeleton and write it yourself."
              onClick={openBlank}
            />
          </div>
          {aiOpen ? (
            <AiGenerateBox raw={raw} onClose={() => setAiOpen(false)} />
          ) : null}
        </div>
      </CardBody>

      {pickTemplate ? (
        <TemplatePickerModal
          onPick={openTemplate}
          onClose={() => setPickTemplate(false)}
        />
      ) : null}
      {editor ? (
        <ScriptEditorModal
          initialName={editor.name}
          initialContent={editor.content}
          isNew={editor.isNew}
          onClose={() => setEditor(null)}
          onSaved={() => void mutate()}
        />
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Add-a-script option button                                          */
/* ------------------------------------------------------------------ */

function AddOption({
  icon: Icon, title, blurb, onClick, accent, active,
}: {
  icon: typeof Plus;
  title: string;
  blurb: string;
  onClick: () => void;
  accent?: boolean;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-start gap-2.5 rounded-xl border p-3 text-left transition-all",
        "hover:border-accent hover:shadow-glow",
        active ? "border-accent bg-amber-50/60"
          : accent ? "border-amber-200 bg-amber-50/40" : "border-ink-200 bg-card",
      )}
    >
      <span className={cn(
        "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
        accent || active ? "bg-amber-100 text-amber-700" : "bg-ink-100 text-ink-500",
      )}>
        <Icon size={14} />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-bold text-ink">{title}</span>
        <span className="block text-[11px] leading-snug text-ink-500">{blurb}</span>
      </span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* AI generate box                                                     */
/* ------------------------------------------------------------------ */

function AiGenerateBox({
  raw, onClose,
}: {
  raw: DataFile[];
  onClose: () => void;
}) {
  const openDrawer = useUiStore((s) => s.openDrawer);
  const [goal, setGoal] = React.useState("");
  const [goalFile, setGoalFile] = React.useState(raw[0]?.path ?? "");

  const generate = () => {
    if (!goal.trim()) return;
    const file = raw.find((f) => f.path === goalFile) ?? raw[0] ?? null;
    openDrawer(buildTransformPrompt({
      goal: goal.trim(),
      file: file ? { path: file.path, schema_hint: file.schema_hint } : null,
    }));
    setGoal("");
    onClose();
  };

  return (
    <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50/40 p-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          autoFocus
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && goal.trim()) generate(); }}
          placeholder='Describe the script, for example: "drop any record where the assistant reply is empty"'
          className="min-w-0 flex-1 rounded-lg border border-ink-200 bg-card px-3
                     py-1.5 text-sm focus:border-accent focus:outline-none"
        />
        {raw.length > 0 ? (
          <select
            value={goalFile}
            onChange={(e) => setGoalFile(e.target.value)}
            aria-label="File it should run on"
            className="rounded-lg border border-ink-200 bg-card px-2 py-1.5 text-xs
                       focus:border-accent focus:outline-none"
          >
            {raw.map((f) => (
              <option key={f.path} value={f.path}>{f.name}</option>
            ))}
          </select>
        ) : null}
        <Button variant="primary" size="sm" onClick={generate} disabled={!goal.trim()}>
          <Sparkles size={12} /> Write it
        </Button>
      </div>
      <p className="text-[10px] leading-relaxed text-ink-500">
        AI writes the script in the side panel so you can read it first. When it
        looks right, press <b>Save as pipeline script</b> on the code block and it
        joins your list here.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Reorderable script pipeline + chain runner                          */
/* ------------------------------------------------------------------ */

function ScriptPipeline({
  scripts, raw, processed, locked, onReordered, onEdit, onChanged,
}: {
  scripts: TransformScript[];
  raw: DataFile[];
  processed: DataFile[];
  locked: boolean;
  onReordered: () => void;
  onEdit: (name: string) => void | Promise<void>;
  onChanged: () => void;
}) {
  // Local order so drag/arrow moves feel instant; server confirms after.
  const [items, setItems] = React.useState<TransformScript[]>(scripts);
  const sig = scripts.map((s) => s.name).join("|");
  React.useEffect(() => { setItems(scripts); }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  const [dragIdx, setDragIdx] = React.useState<number | null>(null);
  const [overIdx, setOverIdx] = React.useState<number | null>(null);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [deleteArm, setDeleteArm] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!deleteArm) return;
    const t = window.setTimeout(() => setDeleteArm(null), 3_500);
    return () => window.clearTimeout(t);
  }, [deleteArm]);

  const persist = async (next: TransformScript[]) => {
    setItems(next);
    try {
      await api.saveTransformOrder(next.map((s) => s.name));
      onReordered();
    } catch { /* order is cosmetic; ignore save failure */ }
  };

  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length || from === to) return;
    const next = items.slice();
    const [m] = next.splice(from, 1);
    next.splice(to, 0, m);
    void persist(next);
  };

  const removeScript = async (name: string) => {
    setDeleteArm(null);
    await api.deleteTransform(name);
    onChanged();
  };

  const multiple = items.length > 1;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-bold text-ink">
        <ListOrdered size={13} className="text-amber-600" />
        Your scripts
        <span className="font-normal text-[10px] text-ink-500">
          {multiple
            ? "they run top to bottom; drag the handle or use the arrows to change the order"
            : "add more below to build a cleanup sequence"}
        </span>
      </div>

      <div className="space-y-1.5">
        {items.map((s, i) => (
          <div
            key={s.name}
            draggable={!locked}
            onDragStart={() => setDragIdx(i)}
            onDragEnter={() => setOverIdx(i)}
            onDragOver={(e) => e.preventDefault()}
            onDragEnd={() => {
              if (dragIdx !== null && overIdx !== null) move(dragIdx, overIdx);
              setDragIdx(null); setOverIdx(null);
            }}
            className={cn(
              "rounded-lg border bg-card transition-colors",
              dragIdx === i ? "opacity-50" : "",
              overIdx === i && dragIdx !== null && dragIdx !== i
                ? "border-accent" : "border-ink-200",
            )}
          >
            <div className="flex items-center gap-2 px-2 py-2">
              {/* Drag handle + order controls */}
              <div className="flex shrink-0 items-center">
                <span
                  className={cn(
                    "cursor-grab text-ink-300 active:cursor-grabbing",
                    "hidden sm:block",
                  )}
                  title="Drag to reorder"
                  aria-hidden="true"
                >
                  <GripVertical size={14} />
                </span>
                <span className="flex flex-col">
                  <button
                    type="button"
                    onClick={() => move(i, i - 1)}
                    disabled={i === 0}
                    aria-label="Move up"
                    className="text-ink-300 hover:text-ink disabled:opacity-30"
                  >
                    <ChevronDown size={12} className="rotate-180" />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(i, i + 1)}
                    disabled={i === items.length - 1}
                    aria-label="Move down"
                    className="text-ink-300 hover:text-ink disabled:opacity-30"
                  >
                    <ChevronDown size={12} />
                  </button>
                </span>
              </div>

              <span className="flex h-5 w-5 shrink-0 items-center justify-center
                               rounded-full bg-ink-100 text-[10px] font-bold text-ink-500">
                {i + 1}
              </span>

              <button
                type="button"
                onClick={() => setExpanded((e) => (e === s.name ? null : s.name))}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                <FileCode2 size={13} className="shrink-0 text-amber-600" />
                <code className="shrink-0 text-xs font-bold text-ink">{s.name}</code>
                <span className="truncate text-[11px] text-ink-500">
                  {s.description || "no description yet"}
                </span>
              </button>

              <span className="hidden items-center gap-1 text-[10px] text-ink-400 md:inline-flex">
                <Clock size={9} /> {fmtRelative(s.mtime)}
              </span>

              {deleteArm === s.name ? (
                <span className="inline-flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => void removeScript(s.name)}
                    aria-label="Confirm delete"
                    className="rounded bg-red-600 p-1 text-white hover:bg-red-700"
                  >
                    <Check size={11} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteArm(null)}
                    aria-label="Cancel delete"
                    className="rounded border border-ink-200 p-1 text-ink-500 hover:bg-ink-50"
                  >
                    <X size={11} />
                  </button>
                </span>
              ) : (
                <span className="inline-flex items-center gap-0.5">
                  <button
                    type="button"
                    onClick={() => setExpanded((e) => (e === s.name ? null : s.name))}
                    title="Run this one on a file"
                    aria-label={`Run ${s.name}`}
                    className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-amber-700"
                  >
                    <Play size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => void onEdit(s.name)}
                    title="View and edit the code"
                    aria-label={`Edit ${s.name}`}
                    className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink"
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteArm(s.name)}
                    title="Delete this script"
                    aria-label={`Delete ${s.name}`}
                    className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-red-600"
                  >
                    <Trash2 size={12} />
                  </button>
                </span>
              )}
            </div>

            {expanded === s.name ? (
              <SingleRun
                name={s.name}
                raw={raw}
                processed={processed}
                locked={locked}
                onRan={onChanged}
              />
            ) : null}
          </div>
        ))}
      </div>

      {/* Run the whole sequence */}
      <ChainRunner
        count={items.length}
        raw={raw}
        processed={processed}
        locked={locked}
        onRan={onChanged}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Run one script                                                      */
/* ------------------------------------------------------------------ */

function fileStem(path: string): string {
  return (path.split("/").pop() ?? path).replace(/\.jsonl$/i, "");
}

function SingleRun({
  name, raw, processed, locked, onRan,
}: {
  name: string;
  raw: DataFile[];
  processed: DataFile[];
  locked: boolean;
  onRan: () => void;
}) {
  const inputs = [...raw, ...processed];
  const [input, setInput] = React.useState(inputs[0]?.path ?? "");
  const [output, setOutput] = React.useState("");
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<TransformRunResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  const auto = input ? `data/raw/${fileStem(input)}__${name.replace(/\.py$/, "")}.jsonl` : "";

  const run = async () => {
    if (!input || running) return;
    setRunning(true); setErr(null); setResult(null);
    try {
      const r = await api.runTransform(name, {
        input, ...(output.trim() ? { output: output.trim() } : {}),
      });
      setResult(r);
      if (r.ok) onRan();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-2 border-t border-ink-100 bg-ink-50/50 px-3 py-2.5">
      <p className="text-[10px] text-ink-500">
        Try this one script on a single file. It reads the input and writes a new
        output file, leaving the original untouched.
      </p>
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <label className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
          Read
        </label>
        <select
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-ink-200 bg-card px-2 py-1.5
                     font-mono text-xs focus:border-accent focus:outline-none"
        >
          {inputs.length === 0 ? <option value="">no files yet</option> : null}
          {inputs.map((f) => (
            <option key={f.path} value={f.path}>
              {f.path} ({f.line_count.toLocaleString()} records)
            </option>
          ))}
        </select>
        <label className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
          Write
        </label>
        <input
          value={output}
          onChange={(e) => setOutput(e.target.value)}
          placeholder={auto}
          className="min-w-0 flex-1 rounded-lg border border-ink-200 bg-card px-2 py-1.5
                     font-mono text-xs focus:border-accent focus:outline-none"
        />
        <Button
          variant="primary" size="sm"
          onClick={run}
          disabled={running || !input || locked}
          title={locked ? "Running is locked" : "Run this script"}
        >
          {running ? <Loader2 size={12} className="animate-spin" />
            : locked ? <Lock size={12} /> : <Play size={12} />}
          Run
        </Button>
      </div>
      {err ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {err}
        </div>
      ) : null}
      {result ? <RunOutcome result={result} /> : null}
    </div>
  );
}

function RunOutcome({ result }: { result: TransformRunResult }) {
  return (
    <div className={cn(
      "space-y-1.5 rounded-lg border p-2.5 text-xs",
      result.ok ? "border-emerald-200 bg-emerald-50/60" : "border-red-200 bg-red-50/60",
    )}>
      <div className="flex flex-wrap items-center gap-2">
        {result.ok ? <CheckCircle2 size={13} className="text-emerald-600" />
          : <AlertCircle size={13} className="text-red-600" />}
        <span className={cn("font-bold", result.ok ? "text-emerald-800" : "text-red-800")}>
          {result.ok ? `Wrote ${result.output_lines.toLocaleString()} records`
            : result.timed_out ? "Timed out" : `Failed (exit ${result.exit_code})`}
        </span>
        <code className="text-[11px] text-ink-500">{result.output}</code>
        <span className="ml-auto tabular-nums text-[10px] text-ink-400">{result.duration_s}s</span>
      </div>
      {result.stdout_tail ? (
        <pre className="max-h-40 overflow-auto rounded border border-ink-200 bg-card p-2
                        font-mono text-[11px]">
          {result.stdout_tail}
        </pre>
      ) : null}
      {result.ok ? (
        <div className="text-[10px] text-ink-500">
          The new file is in your raw files above. Audit it, then build your splits.
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Chain runner                                                        */
/* ------------------------------------------------------------------ */

function ChainRunner({
  count, raw, processed, locked, onRan,
}: {
  count: number;
  raw: DataFile[];
  processed: DataFile[];
  locked: boolean;
  onRan: () => void;
}) {
  const inputs = [...raw, ...processed];
  const [input, setInput] = React.useState(inputs[0]?.path ?? "");
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<TransformChainResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!input && inputs[0]) setInput(inputs[0].path);
  }, [inputs, input]);

  if (count < 2) return null;

  const run = async () => {
    if (!input || running) return;
    setRunning(true); setErr(null); setResult(null);
    try {
      const r = await api.runTransformChain({ input });
      setResult(r);
      if (r.all_ok) onRan();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50/40 p-3">
      <div className="flex items-center gap-1.5 text-xs font-bold text-ink">
        <PlayCircle size={13} className="text-amber-600" />
        Run all {count} in order
        <span className="font-normal text-[10px] text-ink-500">
          feeds one file through every script, top to bottom, in a single pass
        </span>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <label className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
          Start from
        </label>
        <select
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-ink-200 bg-card px-2 py-1.5
                     font-mono text-xs focus:border-accent focus:outline-none"
        >
          {inputs.length === 0 ? <option value="">no files yet</option> : null}
          {inputs.map((f) => (
            <option key={f.path} value={f.path}>
              {f.path} ({f.line_count.toLocaleString()} records)
            </option>
          ))}
        </select>
        <Button
          variant="primary" size="sm"
          onClick={run}
          disabled={running || !input || locked}
          title={locked ? "Running is locked" : "Run the whole sequence"}
        >
          {running ? <Loader2 size={12} className="animate-spin" />
            : locked ? <Lock size={12} /> : <PlayCircle size={12} />}
          Run all
        </Button>
      </div>
      {err ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {err}
        </div>
      ) : null}
      {result ? <ChainOutcome result={result} /> : null}
    </div>
  );
}

function ChainOutcome({ result }: { result: TransformChainResult }) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {result.steps.map((s, i) => (
          <React.Fragment key={`${s.script}-${i}`}>
            {i > 0 ? <ArrowRight size={11} className="text-ink-300" /> : null}
            <span
              title={s.stdout_tail}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold",
                s.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-red-200 bg-red-50 text-red-700",
              )}
            >
              {s.ok ? <CheckCircle2 size={10} /> : <AlertCircle size={10} />}
              {s.script.replace(/\.py$/, "")}
              <span className="tabular-nums text-ink-400">
                {s.input_lines}&rarr;{s.output_lines}
              </span>
            </span>
          </React.Fragment>
        ))}
      </div>
      <div className={cn(
        "rounded-lg border px-3 py-2 text-xs",
        result.all_ok ? "border-emerald-200 bg-emerald-50 text-emerald-800"
          : "border-red-200 bg-red-50 text-red-800",
      )}>
        {result.all_ok ? (
          <span className="font-semibold">
            Done. Wrote {result.output_lines.toLocaleString()} records to{" "}
            <code>{result.output}</code>. It is in your raw files, ready for the pipeline.
          </span>
        ) : (
          <span className="font-semibold">
            Stopped at a failing step. Hover the red step above for its output; the
            final file was not written.
          </span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Template picker modal                                               */
/* ------------------------------------------------------------------ */

function TemplatePickerModal({
  onPick, onClose,
}: {
  onPick: (t: TransformTemplate) => void;
  onClose: () => void;
}) {
  const groups = React.useMemo(() => templatesByCategory(), []);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden
                   rounded-2xl border border-ink-200 bg-card shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
          <LayoutTemplate size={15} className="text-amber-600" />
          <span className="text-sm font-bold text-ink">Pick a template</span>
          <span className="text-[11px] text-ink-400">
            each opens in the editor so you can adjust it before saving
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
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
          {groups.map((g) => {
            const Icon = CATEGORY_ICON[g.category];
            const meta = CATEGORY_META[g.category];
            return (
              <div key={g.category} className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <Icon size={12} className="text-amber-600" />
                  <span className="text-xs font-bold text-ink">{meta.label}</span>
                  <span className="text-[11px] text-ink-400">{meta.blurb}</span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {g.items.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => onPick(t)}
                      className="group flex items-start gap-2 rounded-lg border border-ink-200
                                 bg-card px-3 py-2.5 text-left transition-all
                                 hover:border-accent hover:shadow-glow"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[13px] font-bold text-ink">{t.label}</span>
                          <code className="rounded bg-ink-100 px-1 text-[9px] text-ink-500">
                            {t.suggestedName}
                          </code>
                        </div>
                        <p className="mt-0.5 text-[11px] leading-snug text-ink-500">
                          {t.description}
                        </p>
                      </div>
                      <Plus size={14} className="mt-0.5 shrink-0 text-ink-300
                                                 transition-colors group-hover:text-amber-600" />
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Script editor modal                                                 */
/* ------------------------------------------------------------------ */

const NAME_RE = /^[A-Za-z0-9_\-]+\.py$/;

function ScriptEditorModal({
  initialName, initialContent, isNew, onClose, onSaved,
}: {
  initialName: string;
  initialContent: string;
  isNew: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState(initialName);
  const [content, setContent] = React.useState(initialContent);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<string | null>(null);
  const [warnings, setWarnings] = React.useState<string[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const valid = NAME_RE.test(name);

  const save = async () => {
    if (!valid || busy || !content.trim()) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api.saveTransform(name, content);
      setMsg(`Saved to data/transforms/${r.name}${r.backup ? ` (previous version kept as ${r.backup})` : ""}.`);
      setWarnings(r.warnings);
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden
                   rounded-2xl border border-ink-200 bg-card shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
          <FileCode2 size={14} className="text-amber-600" />
          {isNew ? (
            <input
              value={name}
              onChange={(e) => setName(e.target.value.trim())}
              aria-label="Script filename"
              className={cn(
                "rounded-lg border px-2 py-1 font-mono text-sm font-bold focus:outline-none",
                valid ? "border-ink-200 focus:border-accent" : "border-red-300",
              )}
            />
          ) : (
            <code className="text-sm font-bold text-ink">{name}</code>
          )}
          <span className="hidden text-[10px] text-ink-400 md:inline">
            it runs as: python {valid ? name : "your_script.py"} --input file.jsonl --output out.jsonl
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close editor"
            className="ml-auto rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          spellCheck={false}
          aria-label="Script content"
          className="min-h-[380px] flex-1 resize-none bg-[#0f172a] p-4 font-mono
                     text-[12px] leading-relaxed text-slate-100 focus:outline-none"
        />
        <div className="flex items-center gap-2 border-t border-ink-200 px-4 py-2.5">
          <div className="min-w-0 flex-1 space-y-0.5 text-[11px]">
            {msg ? (
              <div className="flex items-center gap-1.5 text-emerald-700">
                <CheckCircle2 size={12} /> {msg}
              </div>
            ) : null}
            {warnings.map((w) => (
              <div key={w} className="flex items-start gap-1.5 text-amber-700">
                <AlertCircle size={12} className="mt-0.5 shrink-0" /> {w}
              </div>
            ))}
            {err ? (
              <div className="flex items-start gap-1.5 text-red-700">
                <AlertCircle size={12} className="mt-0.5 shrink-0" /> {err}
              </div>
            ) : !msg && !warnings.length ? (
              <span className="text-ink-400">
                Adjust the constants near the top to fit your data, then save.
              </span>
            ) : null}
          </div>
          <Button variant="secondary" size="sm" onClick={onClose}>Close</Button>
          <Button
            variant="primary" size="sm"
            onClick={save}
            disabled={!valid || busy || !content.trim()}
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : null}
            Save script
          </Button>
        </div>
      </div>
    </div>
  );
}
