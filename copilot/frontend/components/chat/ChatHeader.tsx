"use client";
import * as React from "react";
import { Check, FileDown, FileJson, MoreHorizontal, Pencil, Trash2, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import type { ThreadSummary } from "@/lib/types";
import { ModelPicker } from "./ModelPicker";

function fmtCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function ChatHeader({
  thread,
  usage,
  isStreaming,
  onRename,
  onChangeModel,
  onDelete,
  onExportMarkdown,
  onExportJson,
}: {
  thread: ThreadSummary | undefined;
  usage: { cumulative_input: number; cumulative_output: number };
  isStreaming: boolean;
  onRename: (title: string) => void;
  onChangeModel: (model: string) => void;
  onDelete: () => void;
  onExportMarkdown: () => void;
  onExportJson: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!menuOpen) {
      setConfirmDelete(false);
      return;
    }
    const onDoc = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  const startEdit = () => {
    if (!thread) return;
    setDraft(thread.title);
    setEditing(true);
    window.setTimeout(() => inputRef.current?.select(), 0);
  };

  const commitEdit = () => {
    const title = draft.trim();
    setEditing(false);
    if (title && thread && title !== thread.title) onRename(title);
  };

  const totalTokens = usage.cumulative_input + usage.cumulative_output;

  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b border-ink-200
                    bg-card/85 px-4 backdrop-blur">
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitEdit();
              if (e.key === "Escape") setEditing(false);
            }}
            aria-label="Conversation title"
            className="w-full max-w-md rounded-md border border-accent bg-card
                       px-2 py-1 text-sm font-semibold focus:outline-none"
          />
        ) : (
          <>
            <button
              type="button"
              onDoubleClick={startEdit}
              onClick={startEdit}
              title="Rename conversation"
              className="truncate rounded-md px-1.5 py-1 text-sm font-semibold
                         text-ink transition-colors hover:bg-ink-100"
            >
              {thread?.title ?? "…"}
            </button>
            <Pencil
              size={11}
              className="shrink-0 text-ink-300"
              aria-hidden="true"
            />
          </>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {isStreaming ? (
          <span className="hidden items-center gap-1.5 rounded-full bg-amber-50
                           px-2.5 py-1 text-[10px] font-bold text-amber-800 md:inline-flex">
            <span className="h-1.5 w-1.5 animate-pulseDot rounded-full bg-amber-500" />
            STREAMING
          </span>
        ) : null}
        {totalTokens > 0 ? (
          <span
            className="hidden rounded-full border border-ink-200 bg-ink-50 px-2.5
                       py-1 text-[10px] font-semibold tabular-nums text-ink-500 lg:inline"
            title={`Session usage: input: ${usage.cumulative_input.toLocaleString()} tokens, output: ${usage.cumulative_output.toLocaleString()} tokens`}
          >
            {fmtCompact(usage.cumulative_input)} in · {fmtCompact(usage.cumulative_output)} out
          </span>
        ) : null}

        {thread ? (
          <ModelPicker
            compact
            value={thread.model}
            onChange={onChangeModel}
          />
        ) : null}

        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Conversation actions"
            aria-expanded={menuOpen}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg
                       border border-ink-200 bg-card text-ink-500 transition-colors
                       hover:border-accent hover:text-ink"
          >
            <MoreHorizontal size={15} />
          </button>
          {menuOpen ? (
            <div className="absolute right-0 z-40 mt-1 w-56 overflow-hidden rounded-xl
                            border border-ink-200 bg-card py-1 shadow-card animate-fadeInUp">
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onExportMarkdown(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm
                           text-ink-700 hover:bg-ink-50"
              >
                <FileDown size={14} className="text-ink-400" />
                Export as Markdown
              </button>
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onExportJson(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm
                           text-ink-700 hover:bg-ink-50"
              >
                <FileJson size={14} className="text-ink-400" />
                Export as JSON
              </button>
              <div className="my-1 border-t border-ink-100" />
              {confirmDelete ? (
                <div className="flex items-center gap-1 px-3 py-1.5">
                  <span className="text-xs font-semibold text-red-700">Delete forever?</span>
                  <button
                    type="button"
                    onClick={() => { setMenuOpen(false); onDelete(); }}
                    aria-label="Confirm delete"
                    className="ml-auto rounded-md bg-red-600 p-1.5 text-white hover:bg-red-700"
                  >
                    <Check size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    aria-label="Cancel delete"
                    className="rounded-md border border-ink-200 p-1.5 text-ink-500 hover:bg-ink-50"
                  >
                    <X size={12} />
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className={cn(
                    "flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm",
                    "text-red-600 hover:bg-red-50",
                  )}
                >
                  <Trash2 size={14} />
                  Delete conversation
                </button>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
