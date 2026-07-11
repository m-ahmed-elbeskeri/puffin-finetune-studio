"use client";
import * as React from "react";
import { AlertCircle, Check, ChevronLeft, ChevronRight, Loader2, Pencil, Plus, Save, Table2, Trash2, X } from "@/components/ui/icons";
import { api, type DataRecord, type RecordPage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

const TEMPLATES: Record<string, unknown> = {
  messages: {
    messages: [
      { role: "system", content: "" },
      { role: "user", content: "" },
      { role: "assistant", content: "" },
    ],
  },
  preference: { prompt: "", chosen: "", rejected: "" },
  prompt_completion: { prompt: "", completion: "" },
  instruction: { instruction: "", response: "" },
};

const PAGE_SIZE = 20;

export function RecordsEditor({
  path, schemaHint, onClose, onChanged,
}: {
  path: string;
  schemaHint: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [offset, setOffset] = React.useState(0);
  const [page, setPage] = React.useState<RecordPage | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<number | "new" | null>(null);
  const [deleteArm, setDeleteArm] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async (off: number) => {
    setLoading(true); setError(null);
    try {
      setPage(await api.readRecords(path, off, PAGE_SIZE));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  React.useEffect(() => { void load(offset); }, [load, offset]);

  const refresh = async () => {
    await load(offset);
    onChanged();
  };

  const total = page?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);

  const saveNew = async (record: unknown) => {
    setBusy(true);
    try {
      await api.addRecord(path, record);
      setEditing(null);
      // jump to the last page so the new record is visible
      const newTotal = total + 1;
      setOffset(Math.max(0, Math.floor((newTotal - 1) / PAGE_SIZE) * PAGE_SIZE));
      await refresh();
    } finally { setBusy(false); }
  };

  const saveEdit = async (index: number, record: unknown) => {
    setBusy(true);
    try {
      await api.updateRecord(path, index, record);
      setEditing(null);
      await refresh();
    } finally { setBusy(false); }
  };

  const remove = async (index: number) => {
    setDeleteArm(null);
    setBusy(true);
    try {
      await api.deleteRecord(path, index);
      // if we deleted the last item on the last page, step back
      if (offset > 0 && offset >= total - 1) setOffset(Math.max(0, offset - PAGE_SIZE));
      await refresh();
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden
                   rounded-2xl border border-ink-200 bg-card shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
          <Table2 size={15} className="text-amber-600" />
          <span className="text-sm font-bold text-ink">Edit records</span>
          <code className="truncate text-[11px] text-ink-400">{path}</code>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>

        {/* toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 px-4 py-2">
          <Button
            variant="primary" size="sm"
            onClick={() => { setEditing("new"); }}
            disabled={editing === "new"}
          >
            <Plus size={12} /> Add record
          </Button>
          <span className="text-[11px] text-ink-500 tabular-nums">
            {loading ? "loading…" : `${from.toLocaleString()}-${to.toLocaleString()} of ${total.toLocaleString()}`}
          </span>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0 || loading}
              aria-label="Previous page"
              className="rounded-lg border border-ink-200 p-1.5 text-ink-500
                         hover:bg-ink-50 disabled:opacity-30"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              onClick={() => setOffset(to < total ? offset + PAGE_SIZE : offset)}
              disabled={to >= total || loading}
              aria-label="Next page"
              className="rounded-lg border border-ink-200 p-1.5 text-ink-500
                         hover:bg-ink-50 disabled:opacity-30"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>

        {/* body */}
        <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
          {editing === "new" ? (
            <RecordForm
              title="New record"
              initial={JSON.stringify(TEMPLATES[schemaHint] ?? {}, null, 2)}
              busy={busy}
              onSave={saveNew}
              onCancel={() => setEditing(null)}
            />
          ) : null}

          {error ? (
            <div className="flex items-start gap-1.5 rounded-lg border border-red-200
                            bg-red-50 px-3 py-2 text-xs text-red-700">
              <AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}
            </div>
          ) : null}

          {loading && !page ? (
            <div className="flex items-center gap-2 py-8 text-xs text-ink-500">
              <Loader2 size={14} className="animate-spin" /> Loading records…
            </div>
          ) : null}

          {page && total === 0 && editing !== "new" ? (
            <div className="py-8 text-center text-sm text-ink-500">
              This file is empty. Use <b>Add record</b> to create the first one.
            </div>
          ) : null}

          {page?.records.map((rec) => (
            editing === rec.index ? (
              <RecordForm
                key={rec.index}
                title={`Record #${rec.index}`}
                initial={rec.valid
                  ? JSON.stringify(rec.data, null, 2)
                  : rec.raw ?? ""}
                busy={busy}
                onSave={(obj) => saveEdit(rec.index, obj)}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <RecordCard
                key={rec.index}
                rec={rec}
                armed={deleteArm === rec.index}
                onEdit={() => setEditing(rec.index)}
                onArmDelete={() => setDeleteArm(rec.index)}
                onCancelDelete={() => setDeleteArm(null)}
                onDelete={() => remove(rec.index)}
              />
            )
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function RecordForm({
  title, initial, busy, onSave, onCancel,
}: {
  title: string;
  initial: string;
  busy: boolean;
  onSave: (record: unknown) => void;
  onCancel: () => void;
}) {
  const [text, setText] = React.useState(initial);
  const [err, setErr] = React.useState<string | null>(null);

  const save = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setErr(`Not valid JSON: ${(e as Error).message}`);
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setErr("A record must be a JSON object (in { curly braces }).");
      return;
    }
    setErr(null);
    onSave(parsed);
  };

  return (
    <div className="rounded-lg border border-accent bg-amber-50/30 p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] font-bold text-ink">{title}</span>
        <span className="text-[10px] text-ink-400">one JSON object</span>
      </div>
      <textarea
        value={text}
        onChange={(e) => { setText(e.target.value); setErr(null); }}
        spellCheck={false}
        rows={Math.min(16, Math.max(4, text.split("\n").length))}
        className="w-full resize-y rounded-lg border border-ink-200 bg-card p-2.5
                   font-mono text-[12px] leading-relaxed focus:border-accent focus:outline-none"
      />
      {err ? (
        <div className="mt-1 flex items-start gap-1.5 text-[11px] text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {err}
        </div>
      ) : null}
      <div className="mt-1.5 flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={save} disabled={busy}>
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          Save
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function RecordCard({
  rec, armed, onEdit, onArmDelete, onCancelDelete, onDelete,
}: {
  rec: DataRecord;
  armed: boolean;
  onEdit: () => void;
  onArmDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={cn(
      "group rounded-lg border bg-card",
      rec.valid ? "border-ink-200" : "border-red-200 bg-red-50/40",
    )}>
      <div className="flex items-center gap-2 px-2.5 py-1.5">
        <span className="flex h-5 min-w-[1.5rem] items-center justify-center rounded-full
                         bg-ink-100 px-1 text-[10px] font-bold text-ink-500">
          {rec.index}
        </span>
        {!rec.valid ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-bold text-red-700">
            <AlertCircle size={11} /> invalid JSON
          </span>
        ) : null}
        <div className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity
                        group-hover:opacity-100 focus-within:opacity-100">
          {armed ? (
            <>
              <button type="button" onClick={onDelete} aria-label="Confirm delete"
                className="rounded bg-red-600 p-1 text-white hover:bg-red-700">
                <Check size={11} />
              </button>
              <button type="button" onClick={onCancelDelete} aria-label="Cancel delete"
                className="rounded border border-ink-200 p-1 text-ink-500 hover:bg-ink-50">
                <X size={11} />
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={onEdit} aria-label="Edit record"
                className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink">
                <Pencil size={12} />
              </button>
              <button type="button" onClick={onArmDelete} aria-label="Delete record"
                className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-red-600">
                <Trash2 size={12} />
              </button>
            </>
          )}
        </div>
      </div>
      <div className="px-2.5 pb-2">
        {rec.valid ? <RecordPreview data={rec.data} /> : (
          <pre className="overflow-x-auto rounded bg-card/60 p-1.5 font-mono text-[11px] text-red-800">
            {rec.raw}
          </pre>
        )}
      </div>
    </div>
  );
}

const ROLE_STYLE: Record<string, string> = {
  system: "bg-ink-100 text-ink-600",
  user: "bg-card border border-ink-200 text-ink",
  assistant: "bg-amber-50 border border-amber-200 text-ink",
};

function RecordPreview({ data }: { data: unknown }) {
  const rec = (data ?? {}) as Record<string, unknown>;
  const msgs = rec.messages;
  if (Array.isArray(msgs)) {
    return (
      <div className="space-y-1">
        {(msgs as Array<{ role?: string; content?: unknown }>).map((m, i) => (
          <div key={i} className={cn("rounded px-2 py-1 text-[12px]", ROLE_STYLE[m.role ?? ""] ?? "bg-ink-50")}>
            <span className="mr-1.5 text-[9px] font-bold uppercase tracking-wider text-ink-400">
              {m.role}
            </span>
            <span className="whitespace-pre-wrap break-words">
              {String(m.content ?? "") || <span className="text-ink-300">(empty)</span>}
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (typeof rec.prompt === "string" && (rec.chosen != null || rec.rejected != null)) {
    return (
      <div className="space-y-1 text-[12px]">
        <div className="rounded border border-ink-200 bg-ink-50 px-2 py-1">
          <span className="mr-1.5 text-[9px] font-bold uppercase text-ink-400">prompt</span>
          <span className="whitespace-pre-wrap break-words">{rec.prompt}</span>
        </div>
        <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
          <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1">
            <span className="mr-1.5 text-[9px] font-bold uppercase text-emerald-600">chosen</span>
            <span className="whitespace-pre-wrap break-words">{String(rec.chosen ?? "")}</span>
          </div>
          <div className="rounded border border-red-200 bg-red-50 px-2 py-1">
            <span className="mr-1.5 text-[9px] font-bold uppercase text-red-600">rejected</span>
            <span className="whitespace-pre-wrap break-words">{String(rec.rejected ?? "")}</span>
          </div>
        </div>
      </div>
    );
  }
  return (
    <pre className="overflow-x-auto rounded bg-ink-50 p-1.5 font-mono text-[11px] text-ink-700">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
