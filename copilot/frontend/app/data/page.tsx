"use client";
import * as React from "react";
import useSWR from "swr";
import { Check, ChevronDown, ChevronRight, Database, Upload, ClipboardPaste, Cloud, Trash2, FileText, FlaskConical, Loader2, AlertCircle, CheckCircle2, Plus, Sparkles, Table2, X } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { revalidateData } from "@/lib/revalidate";
import type {
  DatasetAuditPayload, DatasetPreviewPayload,
} from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Tip } from "@/components/ui/Tip";
import { DatasetAuditCard } from "@/components/artifacts/DatasetAuditCard";
import { TransformsPanel } from "@/components/data/TransformsPanel";
import { PipelineRunner } from "@/components/data/PipelineRunner";
import { InspectPanel } from "@/components/data/InspectPanel";
import { RecordsEditor } from "@/components/data/RecordsEditor";
import { useUiStore } from "@/lib/stores/uiStore";
import { StepWizard, WizardSection, type WizardStepDef } from "@/components/layout/StepWizard";
import { cn } from "@/lib/cn";


function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function fmtRelativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  const dt = Date.now() - t;
  const m = Math.floor(dt / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Which training methods each detected format can feed. Mirrors the backend
// FORMAT_META (data_inspect.py) so the browser and audit agree.
type Tone = "ok" | "info" | "muted" | "warn";
interface FormatMeta { label: string; tone: Tone; methods: string[]; help: string }

const FORMATS: Record<string, FormatMeta> = {
  messages: {
    label: "chat messages", tone: "ok", methods: ["sft"],
    help: "Chat records with a messages[] list of {role, content}. Ready for SFT.",
  },
  prompt_completion: {
    label: "prompt + completion", tone: "info", methods: ["sft"],
    help: "Prompt→answer pairs (prompt/completion, instruction/response, …). Mapped onto the chat template for SFT.",
  },
  preference: {
    label: "preference pairs", tone: "info", methods: ["dpo", "reward"],
    help: "prompt + chosen + rejected. Feeds DPO and reward-model training.",
  },
  kto: {
    label: "labeled (KTO)", tone: "info", methods: ["kto"],
    help: "prompt + completion + a boolean label (good/bad). Feeds KTO from unpaired thumbs-up / thumbs-down feedback.",
  },
  prompt_only: {
    label: "prompts only", tone: "info", methods: ["grpo", "rloo"],
    help: "Prompts with no target answer (optionally a reward). Feeds online RL — GRPO / RLOO.",
  },
  // legacy alias kept for older listings
  instruction: {
    label: "instruction", tone: "info", methods: ["sft"],
    help: "Instruction/response records. Trainable via SFT; mapped onto the chat template.",
  },
  empty: { label: "empty", tone: "muted", methods: [], help: "File has no records." },
  unknown: {
    label: "unrecognized", tone: "warn", methods: [],
    help: "Rows don't match any known training schema. Preview the file or reshape it with a transform script first.",
  },
  invalid: {
    label: "invalid JSON", tone: "warn", methods: [],
    help: "Rows failed to parse as JSON. Fix or re-export this file.",
  },
};

const METHOD_LABEL: Record<string, string> = {
  sft: "SFT", dpo: "DPO", kto: "KTO", reward: "Reward", grpo: "GRPO", rloo: "RLOO",
};

function fmtMeta(hint: string): FormatMeta {
  return FORMATS[hint] ?? FORMATS.unknown;
}


type Tab = "upload" | "paste" | "huggingface";

export default function DataPage() {
  const { data, mutate } = useSWR("data:files",
    () => api.listDataFiles(), { refreshInterval: 5_000 });
  const { data: caps } = useSWR("capabilities", () => api.capabilities());
  const { data: tfData } = useSWR("data:transforms", () => api.listTransforms());
  const files = data?.files ?? [];
  const raw = files.filter((f) => f.kind === "raw");
  const processed = files.filter((f) => f.kind === "processed");

  const [addOpen, setAddOpen] = React.useState(false);

  // Any change (manual edit or the AI's tools) refreshes every panel at once,
  // so the file list, inspect cards, split, and eval sets stay in lockstep.
  const refreshAll = React.useCallback(() => {
    void mutate();
    revalidateData();
  }, [mutate]);

  const hasRaw = raw.length > 0;
  const hasScripts = (tfData?.transforms.length ?? 0) > 0;
  const ready = processed.some(
    (f) => f.name === "train.jsonl" && f.line_count > 0);

  const steps: WizardStepDef[] = [
    { id: "add-data", label: "Add data",
      status: hasRaw ? "done" : "current" },
    { id: "reshape", label: "Reshape", status: hasScripts ? "done" : "optional" },
    { id: "splits", label: "Build splits",
      status: ready ? "done" : hasRaw ? "current" : "pending" },
    { id: "inspect", label: "Inspect", status: ready ? "current" : "pending" },
  ];

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-ink">Data</h1>
          <p className="text-sm text-ink-500 mt-1">
            Your data workspace: add sources, reshape with scripts, build splits,
            and inspect. Head to <b>Train</b> when it&apos;s ready; author eval
            sets on <b>Evaluate</b>.
          </p>
        </div>
      </div>

      <StepWizard steps={steps}>
      {/* ----- Step 1: add data ------------------------------------- */}
      <WizardSection
        id="add-data"
        n={1}
        title="Add your data"
        status={hasRaw ? "done" : "current"}
        hint="Your source files live here. Add more any time by uploading, pasting, or importing from Hugging Face, then preview, audit, or edit the records."
      >
        <FormatGuide />
        <Card className={cn(!hasRaw && "ring-1 ring-amber-300")}>
          <CardHeader className="flex items-center gap-3 text-sm font-bold">
            <Database size={14} className="text-amber-600" />
            Your data
            <span className="font-normal text-[11px] text-ink-500">
              {raw.length
                ? `${raw.length} file${raw.length === 1 ? "" : "s"} in data/raw/`
                : "nothing yet"}
            </span>
            <Button
              variant="primary" size="sm" className="ml-auto"
              onClick={() => setAddOpen(true)}
            >
              <Plus size={13} /> Add data
            </Button>
          </CardHeader>
          <CardBody className="p-0">
            {hasRaw ? (
              <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="bg-ink-50 text-[10px] uppercase tracking-wider text-ink-500">
                  <tr>
                    <th className="px-4 py-2 text-left font-bold">File</th>
                    <th className="px-4 py-2 text-left font-bold">Schema</th>
                    <th className="px-4 py-2 text-right font-bold">Records</th>
                    <th className="px-4 py-2 text-right font-bold">Size</th>
                    <th className="px-4 py-2 text-right font-bold">Modified</th>
                    <th className="px-4 py-2 text-right font-bold w-40">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {raw.map((f) => (
                    <FileRow key={f.path} file={f} onDone={refreshAll} canDelete />
                  ))}
                </tbody>
              </table>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
                <Database size={26} className="text-ink-300" />
                <div className="text-sm font-semibold text-ink">No data in this project</div>
                <p className="max-w-sm text-xs text-ink-500">
                  Add your first JSONL file to get started. You can upload a file,
                  paste records, or import a dataset from Hugging Face.
                </p>
                <Button variant="primary" size="md" onClick={() => setAddOpen(true)}>
                  <Plus size={14} /> Add data
                </Button>
              </div>
            )}
          </CardBody>
        </Card>
      </WizardSection>

      {addOpen ? (
        <AddDataModal onClose={() => setAddOpen(false)} onDone={refreshAll} />
      ) : null}

      {/* ----- Step 2: custom scripts (optional) ---------------------- */}
      <WizardSection
        id="reshape"
        n={2}
        title="Reshape with custom scripts"
        status={hasScripts ? "done" : "optional"}
        hint="Optional. AI-generated (or hand-written) Python transforms that clean, filter, or re-map raw files before the pipeline. Skip if your data is already in shape."
      >
        <TransformsPanel
          raw={raw}
          processed={processed}
          dangerousEnabled={caps?.dangerous_enabled}
          onFilesChanged={refreshAll}
        />
      </WizardSection>

      {/* ----- Step 3: build splits ---------------------------------- */}
      <WizardSection
        id="splits"
        n={3}
        title="Build training splits"
        status={ready ? "done" : hasRaw ? "current" : "pending"}
        hint="Set your train / eval / test ratios, then run the pipeline (ingest → validate → split → dataset card). Works for every format: chat, preference pairs, KTO, and prompt-only. Every run leaves a per-stage log."
      >
        <PipelineRunner
          raw={raw}
          processed={processed}
          dangerousEnabled={caps?.dangerous_enabled}
          onDone={refreshAll}
        />
        {processed.length > 0 ? (
          <FileGroup title="Processed" sub="data/processed/: what training actually consumes"
                     files={processed} onDone={refreshAll} />
        ) : null}
      </WizardSection>

      {/* ----- Step 4: inspect -------------------------------------- */}
      <WizardSection
        id="inspect"
        n={4}
        title="Inspect and trust your data"
        status={ready ? "current" : "pending"}
        hint="Before you spend GPU time: check the token budget, see what the model actually trains on, and catch split leakage. This is where a bad dataset gets caught."
      >
        <InspectPanel raw={raw} processed={processed} />
      </WizardSection>
      </StepWizard>
    </div>
  );
}


/* ============================================================== */
/* Add-data modal                                                  */
/* ============================================================== */

const ADD_TABS: Array<{ id: Tab; label: string; icon: typeof Upload; blurb: string }> = [
  { id: "upload", label: "Upload files", icon: Upload,
    blurb: "Drop or browse for .jsonl files from your computer." },
  { id: "paste", label: "Paste JSONL", icon: ClipboardPaste,
    blurb: "Paste records straight in, one JSON object per line." },
  { id: "huggingface", label: "Hugging Face", icon: Cloud,
    blurb: "Import a public dataset and map it to the chat format." },
];

function AddDataModal({
  onClose, onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [tab, setTab] = React.useState<Tab>("upload");
  const active = ADD_TABS.find((t) => t.id === tab) ?? ADD_TABS[0];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-xl flex-col overflow-hidden
                   rounded-2xl border border-ink-200 bg-card shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
          <Database size={15} className="text-amber-600" />
          <span className="text-sm font-bold text-ink">Add data</span>
          <span className="text-[11px] text-ink-400">everything lands in data/raw/</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>

        {/* source tabs */}
        <div className="flex gap-1 border-b border-ink-200 px-3 pt-2">
          {ADD_TABS.map((t) => (
            <TabBtn key={t.id} active={tab === t.id} onClick={() => setTab(t.id)}>
              <t.icon size={12} /> {t.label}
            </TabBtn>
          ))}
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-4">
          <p className="text-[11px] text-ink-500">{active.blurb}</p>
          {tab === "upload" ? <UploadTab onDone={onDone} /> : null}
          {tab === "paste" ? <PasteTab onDone={onDone} /> : null}
          {tab === "huggingface" ? <HuggingFaceTab onDone={onDone} /> : null}
        </div>

        <div className="flex justify-end border-t border-ink-200 px-4 py-2.5">
          <Button variant="secondary" size="sm" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================== */
/* Tabs                                                            */
/* ============================================================== */

function TabBtn({
  active, onClick, children,
}: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold",
        "rounded-t-lg -mb-px border-b-2 transition-colors",
        active
          ? "border-amber-500 text-amber-700"
          : "border-transparent text-ink-500 hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}


function UploadTab({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const [drag, setDrag] = React.useState(false);
  const [result, setResult] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const upload = async (files: FileList | File[]) => {
    setErr(null);
    setResult(null);
    const arr = Array.from(files);
    if (!arr.length) return;
    setBusy(true);
    try {
      const r = await api.uploadDataFiles(arr);
      const ok = r.imported.length;
      const totalRecs = r.imported.reduce((s, f) => s + f.valid_records, 0);
      const badRecs = r.imported.reduce((s, f) => s + f.invalid_records, 0);
      setResult(
        `Uploaded ${ok} file${ok === 1 ? "" : "s"} (${totalRecs} valid records` +
        (badRecs ? `, ${badRecs} invalid` : "") + ").",
      );
      if (r.skipped.length) {
        setErr(`Skipped ${r.skipped.length}: ${r.skipped.map(s => s.reason).join("; ")}`);
      }
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault(); setDrag(false);
          upload(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "rounded-xl border-2 border-dashed p-8 text-center cursor-pointer",
          "transition-colors text-sm",
          drag
            ? "border-amber-500 bg-amber-50"
            : "border-ink-200 hover:border-amber-400 bg-card",
        )}
      >
        <Upload size={20} className="mx-auto mb-2 text-ink-400" />
        <div className="font-semibold text-ink">
          Drop .jsonl files here or click to browse
        </div>
        <div className="text-[11px] text-ink-500 mt-1">
          Files go to <code>data/raw/</code>. Multiple files OK.
        </div>
        <input
          ref={inputRef} type="file" accept=".jsonl" multiple
          className="hidden"
          onChange={(e) => e.target.files && upload(e.target.files)}
        />
      </div>
      <StatusLine busy={busy} ok={result} err={err} />
    </div>
  );
}


function PasteTab({ onDone }: { onDone: () => void }) {
  const [filename, setFilename] = React.useState("");
  const [content, setContent] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    setResult(null);
    let name = filename.trim();
    if (!name) name = `pasted-${Date.now()}.jsonl`;
    if (!name.endsWith(".jsonl")) name += ".jsonl";
    setBusy(true);
    try {
      const r = await api.pasteDataFile({ filename: name, content });
      setResult(
        `Saved ${r.path} (${r.valid_records} records` +
        (r.invalid_records ? `, ${r.invalid_records} invalid` : "") + ").",
      );
      setContent("");
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <input
        value={filename}
        onChange={(e) => setFilename(e.target.value)}
        placeholder="Filename (e.g. my-tickets.jsonl)"
        className="w-full rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                   font-mono bg-card focus:outline-none focus:border-accent"
      />
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder='{"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}'
        rows={8}
        className="w-full rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                   font-mono bg-card focus:outline-none focus:border-accent"
      />
      <div className="flex justify-end">
        <Button variant="primary" size="sm"
                onClick={submit} disabled={busy || !content.trim()}>
          {busy ? <Loader2 size={12} className="animate-spin" /> : null}
          Save to data/raw/
        </Button>
      </div>
      <StatusLine busy={busy} ok={result} err={err} />
    </div>
  );
}


function HuggingFaceTab({ onDone }: { onDone: () => void }) {
  const [name, setName] = React.useState("");
  const [split, setSplit] = React.useState("train");
  const [subset, setSubset] = React.useState("");
  const [maxRecords, setMaxRecords] = React.useState(1000);
  const [filename, setFilename] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<string | null>(null);
  const [samples, setSamples] = React.useState<string[]>([]);
  const [err, setErr] = React.useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    setResult(null);
    setSamples([]);
    if (!name.trim()) { setErr("Dataset name required"); return; }
    setBusy(true);
    try {
      const r = await api.importHuggingFace({
        name: name.trim(),
        split: split.trim() || "train",
        subset: subset.trim() || undefined,
        max_records: maxRecords,
        output_filename: filename.trim() || undefined,
      });
      setResult(r.message);
      setSamples(r.samples);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Dataset (e.g. HuggingFaceH4/no_robots)"
          className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                     font-mono bg-card focus:outline-none focus:border-accent"
        />
        <input
          value={split}
          onChange={(e) => setSplit(e.target.value)}
          placeholder="Split (default: train)"
          className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                     font-mono bg-card focus:outline-none focus:border-accent"
        />
        <input
          value={subset}
          onChange={(e) => setSubset(e.target.value)}
          placeholder="Subset / config (optional)"
          className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                     font-mono bg-card focus:outline-none focus:border-accent"
        />
        <input
          value={maxRecords}
          onChange={(e) => setMaxRecords(Math.max(1, Number(e.target.value) || 1))}
          type="number" min={1} max={200000}
          placeholder="Max records"
          className="rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                     font-mono bg-card focus:outline-none focus:border-accent"
        />
        <input
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          placeholder="Output filename (optional, .jsonl)"
          className="md:col-span-2 rounded-lg border border-ink-200 px-3 py-1.5 text-sm
                     font-mono bg-card focus:outline-none focus:border-accent"
        />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-ink-500">
          Streams + heuristic-maps to chat schema. Rows that don't fit are skipped.
        </span>
        <Button variant="primary" size="sm"
                onClick={submit} disabled={busy || !name.trim()}>
          {busy ? <Loader2 size={12} className="animate-spin" /> : null}
          Import
        </Button>
      </div>
      <StatusLine busy={busy} ok={result} err={err} />
      {samples.length > 0 ? (
        <div className="space-y-1 text-[11px] font-mono bg-ink-50 rounded-lg p-2">
          <div className="text-ink-500 font-bold uppercase tracking-wider text-[10px]">
            First {samples.length} records
          </div>
          {samples.map((s, i) => (
            <div key={i} className="truncate text-ink-700">{s}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}


/* ============================================================== */
/* File browser                                                    */
/* ============================================================== */

function FileGroup({
  title, sub, files, onDone, canDelete,
}: {
  title: string; sub: string;
  files: Array<{
    path: string; name: string; kind: string;
    size_bytes: number; mtime: string; line_count: number;
    schema_hint: string;
  }>;
  onDone: () => void;
  canDelete?: boolean;
}) {
  if (files.length === 0) {
    return (
      <Card>
        <CardHeader className="flex items-center justify-between text-sm">
          <div>
            <span className="font-bold text-ink">{title}</span>
            <span className="text-ink-500 ml-2 text-[11px]">{sub}</span>
          </div>
          <Badge tone="muted">empty</Badge>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="flex items-center justify-between text-sm">
        <div>
          <span className="font-bold text-ink">{title}</span>
          <span className="text-ink-500 ml-2 text-[11px]">{sub}</span>
        </div>
        <Badge tone="muted">{files.length} file{files.length === 1 ? "" : "s"}</Badge>
      </CardHeader>
      <CardBody className="p-0">
        <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-ink-50 text-[10px] uppercase tracking-wider text-ink-500">
            <tr>
              <th className="text-left px-4 py-2 font-bold">File</th>
              <th className="text-left px-4 py-2 font-bold">Schema</th>
              <th className="text-right px-4 py-2 font-bold">Records</th>
              <th className="text-right px-4 py-2 font-bold">Size</th>
              <th className="text-right px-4 py-2 font-bold">Modified</th>
              <th className="text-right px-4 py-2 font-bold w-32">Actions</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <FileRow key={f.path} file={f} onDone={onDone} canDelete={!!canDelete} />
            ))}
          </tbody>
        </table>
        </div>
      </CardBody>
    </Card>
  );
}

type Expanded =
  | { kind: "audit"; data?: DatasetAuditPayload; error?: string }
  | { kind: "preview"; data?: DatasetPreviewPayload; error?: string }
  | null;

function FileRow({
  file, onDone, canDelete,
}: {
  file: {
    path: string; name: string; kind: string;
    size_bytes: number; mtime: string; line_count: number;
    schema_hint: string;
  };
  onDone: () => void;
  canDelete: boolean;
}) {
  const openDrawer = useUiStore((s) => s.openDrawer);
  const [deleting, setDeleting] = React.useState(false);
  const [deleteArmed, setDeleteArmed] = React.useState(false);
  const [deleteErr, setDeleteErr] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<Expanded>(null);
  const [loading, setLoading] = React.useState<"audit" | "preview" | null>(null);
  const [editingRows, setEditingRows] = React.useState(false);

  React.useEffect(() => {
    if (!deleteArmed) return;
    const t = window.setTimeout(() => setDeleteArmed(false), 3_500);
    return () => window.clearTimeout(t);
  }, [deleteArmed]);

  const onDelete = async () => {
    setDeleteArmed(false);
    setDeleting(true);
    setDeleteErr(null);
    try {
      await api.deleteDataFile(file.path);
      onDone();
    } catch (e) {
      setDeleteErr((e as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  const askTransform = () => {
    openDrawer(
      `Look at \`${file.path}\` (schema hint: ${file.schema_hint}, `
      + `${file.line_count.toLocaleString()} records). Preview a few records, `
      + "then propose the 2–3 most useful transform scripts for this file "
      + "(cleaning, filtering, schema mapping). Write the best one as a "
      + "complete python script following the transform contract.",
    );
  };

  const toggle = async (kind: "audit" | "preview") => {
    if (expanded?.kind === kind) {
      setExpanded(null);
      return;
    }
    setLoading(kind);
    try {
      if (kind === "audit") {
        setExpanded({ kind, data: await api.auditDataFile(file.path) });
      } else {
        setExpanded({ kind, data: await api.previewDataFile(file.path, 5) });
      }
    } catch (e) {
      setExpanded({ kind, error: (e as Error).message });
    } finally {
      setLoading(null);
    }
  };

  const actionBtn = (kind: "audit" | "preview", label: string, tip: string) => (
    <button
      onClick={() => toggle(kind)}
      className={cn(
        "inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded border",
        expanded?.kind === kind
          ? "border-amber-400 text-amber-700 bg-amber-50"
          : "border-ink-200 hover:border-amber-400 hover:text-amber-700",
      )}
      title={tip}
    >
      {loading === kind
        ? <Loader2 size={11} className="animate-spin" />
        : expanded?.kind === kind
          ? <ChevronDown size={11} />
          : <ChevronRight size={11} />}
      {label}
    </button>
  );

  return (
    <>
    <tr className="border-t border-ink-100 hover:bg-ink-50/50">
      <td className="px-4 py-2 font-mono text-[12px]">
        <div className="flex items-center gap-2">
          <FileText size={12} className="text-ink-400 shrink-0" />
          <span className="text-ink truncate">{file.name}</span>
        </div>
        <div className="text-[10px] text-ink-400 font-sans">{file.path}</div>
      </td>
      <td className="px-4 py-2">
        {(() => {
          const meta = fmtMeta(file.schema_hint);
          return (
            <div className="space-y-1">
              <Tip text={meta.help}>
                <Badge tone={meta.tone}>{meta.label}</Badge>
              </Tip>
              {meta.methods.length ? (
                <div className="flex flex-wrap gap-1">
                  <span className="text-[9px] uppercase tracking-wide text-ink-400">trains</span>
                  {meta.methods.map((m) => (
                    <span key={m}
                      className="rounded bg-emerald-50 px-1.5 py-px text-[9px] font-bold
                                 text-emerald-700 border border-emerald-200">
                      {METHOD_LABEL[m] ?? m}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })()}
      </td>
      <td className="px-4 py-2 text-right font-mono text-[12px]">
        {file.line_count.toLocaleString()}
      </td>
      <td className="px-4 py-2 text-right font-mono text-[12px] text-ink-500">
        {fmtBytes(file.size_bytes)}
      </td>
      <td className="px-4 py-2 text-right text-[11px] text-ink-500">
        {fmtRelativeTime(file.mtime)}
      </td>
      <td className="px-4 py-2 text-right">
        <div className="inline-flex flex-nowrap items-center justify-end gap-1">
          {actionBtn("preview", "Preview", "Show the first 5 records inline")}
          {actionBtn("audit", "Audit", "Schema, lengths, PII signals, warnings: inline")}
          <button
            onClick={() => setEditingRows(true)}
            className="inline-flex items-center gap-1 rounded border border-ink-200 px-2 py-1
                       text-[11px] hover:border-accent hover:text-accent"
            title="View, add, edit, and delete individual records"
          >
            <Table2 size={11} /> Edit
          </button>
          {file.kind === "raw" ? (
            <button
              onClick={askTransform}
              className="inline-flex items-center gap-1 rounded border border-ink-200 px-2 py-1
                         text-[11px] hover:border-accent hover:text-accent"
              title="Ask the Copilot to write a cleanup / reshape script for this file"
            >
              <Sparkles size={11} className="text-coral" /> Reshape
            </button>
          ) : null}
          {canDelete ? (
            <span className="ml-1 border-l border-ink-200 pl-1.5">
            {deleteArmed ? (
              <span className="inline-flex gap-1">
                <button
                  onClick={onDelete}
                  className="inline-flex items-center gap-1 rounded bg-red-600 px-2 py-1
                             text-[11px] font-semibold text-white hover:bg-red-700"
                  title="Confirm delete: cannot be undone"
                >
                  <Check size={11} /> Delete?
                </button>
                <button
                  onClick={() => setDeleteArmed(false)}
                  className="rounded border border-ink-200 px-2 py-1 text-[11px] hover:bg-ink-50"
                  title="Cancel"
                  aria-label="Cancel delete"
                >
                  <X size={11} />
                </button>
              </span>
            ) : (
              <button
                onClick={() => setDeleteArmed(true)}
                disabled={deleting}
                className="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px]
                           text-ink-400 hover:bg-red-50 hover:text-red-700
                           disabled:opacity-50"
                title="Delete file"
              >
                {deleting
                  ? <Loader2 size={11} className="animate-spin" />
                  : <Trash2 size={11} />} Delete
              </button>
            )}
            </span>
          ) : null}
        </div>
        {deleteErr ? (
          <div className="mt-1 text-right text-[10px] text-red-600">{deleteErr}</div>
        ) : null}
      </td>
    </tr>
    {expanded ? (
      <tr className="border-t border-ink-100 bg-ink-50/40">
        <td colSpan={6} className="px-4 py-3">
          {expanded.error ? (
            <div className="flex items-start gap-1.5 text-xs text-red-700">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              {expanded.error}
            </div>
          ) : expanded.kind === "audit" && expanded.data ? (
            <DatasetAuditCard data={expanded.data} />
          ) : expanded.kind === "preview" && expanded.data ? (
            <RecordsView records={expanded.data.records} />
          ) : null}
        </td>
      </tr>
    ) : null}
    {editingRows ? (
      <RecordsEditor
        path={file.path}
        schemaHint={file.schema_hint}
        onClose={() => setEditingRows(false)}
        onChanged={onDone}
      />
    ) : null}
    </>
  );
}


/* ============================================================== */
/* Wizard chrome                                                   */
/* ============================================================== */

// A compact reference of every dataset shape the studio can train on, so you
// know what to bring for each method. Mirrors FORMATS / the backend FORMAT_META.
const GUIDE_ORDER = ["messages", "prompt_completion", "preference", "kto", "prompt_only"] as const;

function FormatGuide() {
  const [open, setOpen] = React.useState(false);
  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm font-bold text-ink"
      >
        {open ? <ChevronDown size={14} className="text-ink-400" />
              : <ChevronRight size={14} className="text-ink-400" />}
        Supported data formats
        <span className="font-normal text-[11px] text-ink-500">
          what to bring for each training method
        </span>
      </button>
      {open ? (
        <div className="border-t border-ink-100 px-4 py-3">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ink-200 text-left text-[10px] uppercase tracking-wider text-ink-400">
                  <th className="py-1.5 pr-3 font-bold">Format</th>
                  <th className="py-1.5 pr-3 font-bold">Required fields</th>
                  <th className="py-1.5 font-bold">Trains</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {GUIDE_ORDER.map((id) => {
                  const m = FORMATS[id];
                  return (
                    <tr key={id}>
                      <td className="py-1.5 pr-3">
                        <Badge tone={m.tone}>{m.label}</Badge>
                      </td>
                      <td className="py-1.5 pr-3 text-ink-600">{m.help}</td>
                      <td className="py-1.5">
                        <div className="flex flex-wrap gap-1">
                          {m.methods.map((mm) => (
                            <span key={mm}
                              className="rounded bg-emerald-50 px-1.5 py-px text-[9px] font-bold
                                         text-emerald-700 border border-emerald-200">
                              {METHOD_LABEL[mm] ?? mm}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-500">
            Bring any of these as JSONL (one record per line). The file browser
            labels each file&apos;s format and which methods it can feed.
          </p>
        </div>
      ) : null}
    </Card>
  );
}

/* ============================================================== */
/* Shared types                                                    */
/* ============================================================== */

interface DataFile {
  path: string; name: string; kind: string;
  size_bytes: number; mtime: string; line_count: number;
  schema_hint: string;
}

/* ============================================================== */
/* Record preview (schema-aware)                                   */
/* ============================================================== */

function RecordsView({ records }: { records: Record<string, unknown>[] }) {
  if (!records.length) {
    return <div className="text-xs text-ink-500">File is empty.</div>;
  }
  return (
    <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
      {records.map((r, i) => <RecordView key={i} rec={r} index={i} />)}
    </div>
  );
}

const ROLE_STYLE: Record<string, string> = {
  system: "bg-ink-100 border-ink-200 text-ink-700",
  user: "bg-card border-ink-200 text-ink",
  assistant: "bg-amber-50 border-amber-200 text-ink",
  tool: "bg-cyan-50 border-cyan-200 text-ink-700",
};

function RecordView({
  rec, index,
}: {
  rec: Record<string, unknown>;
  index: number;
}) {
  const msgs = rec.messages;
  if (Array.isArray(msgs) && msgs.every(
    (m) => m && typeof m === "object" && "role" in m,
  )) {
    return (
      <div className="bg-card border border-ink-200 rounded-lg p-3 space-y-1.5">
        <div className="text-[10px] font-bold uppercase tracking-wider text-ink-400">
          Record {index + 1}
        </div>
        {(msgs as Array<{ role: string; content: unknown }>).map((m, j) => (
          <div
            key={j}
            className={cn(
              "rounded-lg border px-2.5 py-1.5 text-[12px] leading-relaxed",
              ROLE_STYLE[m.role] ?? "bg-card border-ink-200",
            )}
          >
            <span className="text-[9px] font-bold uppercase tracking-wider text-ink-400 mr-2">
              {m.role}
            </span>
            <span className="whitespace-pre-wrap break-words">{String(m.content ?? "")}</span>
          </div>
        ))}
      </div>
    );
  }

  if (typeof rec.prompt === "string" && (rec.chosen != null || rec.rejected != null)) {
    return (
      <div className="bg-card border border-ink-200 rounded-lg p-3 space-y-1.5">
        <div className="text-[10px] font-bold uppercase tracking-wider text-ink-400">
          Record {index + 1} · preference pair
        </div>
        <div className="rounded-lg border border-ink-200 bg-ink-50 px-2.5 py-1.5 text-[12px]">
          <span className="text-[9px] font-bold uppercase tracking-wider text-ink-400 mr-2">prompt</span>
          <span className="whitespace-pre-wrap break-words">{rec.prompt}</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[12px]">
            <span className="text-[9px] font-bold uppercase tracking-wider text-emerald-600 mr-2">chosen</span>
            <span className="whitespace-pre-wrap break-words">{String(rec.chosen ?? "")}</span>
          </div>
          <div className="rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-[12px]">
            <span className="text-[9px] font-bold uppercase tracking-wider text-red-600 mr-2">rejected</span>
            <span className="whitespace-pre-wrap break-words">{String(rec.rejected ?? "")}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <pre className="bg-ink-50 border border-ink-200 rounded-lg p-3 text-[11px] overflow-x-auto">
      {JSON.stringify(rec, null, 2)}
    </pre>
  );
}

function StatusLine({
  busy, ok, err,
}: {
  busy: boolean; ok: string | null; err: string | null;
}) {
  if (busy) {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-ink-500">
        <Loader2 size={11} className="animate-spin" />
        Working…
      </div>
    );
  }
  if (err) {
    return (
      <div className="flex items-start gap-1.5 text-[11px] text-red-700">
        <AlertCircle size={11} className="mt-0.5 shrink-0" />
        <span>{err}</span>
      </div>
    );
  }
  if (ok) {
    return (
      <div className="flex items-start gap-1.5 text-[11px] text-emerald-700">
        <CheckCircle2 size={11} className="mt-0.5 shrink-0" />
        <span>{ok}</span>
      </div>
    );
  }
  return null;
}
