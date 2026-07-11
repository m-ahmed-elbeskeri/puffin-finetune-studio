"use client";
import * as React from "react";
import { ArrowUp, CircleSlash, Pencil, Send, Square, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

export interface EditingState {
  /** Stored message idx the edit rewinds to. */
  idx: number;
  text: string;
}

interface SlashCommand {
  cmd: string;
  label: string;
  text: string;
}

const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: "status", label: "Project status & next action",
    text: "What's the state of this project? What should I do next?" },
  { cmd: "audit", label: "Audit a dataset",
    text: "Audit data/raw/example.jsonl: is it ready to train?" },
  { cmd: "pipeline", label: "Run the data pipeline",
    text: "Run the data pipeline and build train/eval/test splits." },
  { cmd: "smoke", label: "Smoke train",
    text: "Run a smoke train and watch progress live." },
  { cmd: "train", label: "Full training run",
    text: "Launch a full SFT LoRA training run with the current config." },
  { cmd: "evals", label: "Run evals + gate",
    text: "Run all evals on the latest adapter, then apply the promotion gate." },
  { cmd: "deploy", label: "Push + promote",
    text: "Push the latest passing adapter to the registry and promote it to staging." },
  { cmd: "monitor", label: "Check serving health",
    text: "Show recent serving traffic, quality, and drift: anything odd?" },
  { cmd: "help", label: "What can you do?",
    text: "What can you do? List your tools grouped by pipeline stage." },
];

const draftKey = (threadId: string) => `puffin_draft_${threadId}`;

export function Composer({
  threadId,
  disabled,
  isStreaming,
  editing,
  onSend,
  onAbort,
  onCancelEdit,
  onRecallLast,
}: {
  threadId: string;
  disabled?: boolean;
  isStreaming: boolean;
  editing: EditingState | null;
  onSend: (text: string) => void;
  onAbort: () => void;
  onCancelEdit: () => void;
  /** ArrowUp in an empty composer: edit your last message. */
  onRecallLast?: () => void;
}) {
  const [value, setValue] = React.useState("");
  const [menuIdx, setMenuIdx] = React.useState(0);
  const taRef = React.useRef<HTMLTextAreaElement>(null);
  const editingRef = React.useRef(editing);
  editingRef.current = editing;

  // Load the per-thread draft on thread switch; focus for immediate typing.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    if (!editingRef.current) {
      setValue(window.sessionStorage.getItem(draftKey(threadId)) ?? "");
    }
    const t = window.setTimeout(() => taRef.current?.focus(), 30);
    return () => window.clearTimeout(t);
  }, [threadId]);

  // Entering edit mode replaces the input with the message being edited.
  React.useEffect(() => {
    if (!editing) return;
    setValue(editing.text);
    const ta = taRef.current;
    if (ta) {
      ta.focus();
      window.setTimeout(
        () => ta.setSelectionRange(ta.value.length, ta.value.length), 0);
    }
  }, [editing]);

  const updateValue = (next: string) => {
    setValue(next);
    setMenuIdx(0);
    if (!editingRef.current && typeof window !== "undefined") {
      if (next) window.sessionStorage.setItem(draftKey(threadId), next);
      else window.sessionStorage.removeItem(draftKey(threadId));
    }
  };

  // Auto-grow up to ~9 lines.
  React.useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`;
  }, [value]);

  // Global "/" focuses the composer from anywhere on the page.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                || t.tagName === "SELECT" || t.isContentEditable)) return;
      e.preventDefault();
      taRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- Slash-command menu ------------------------------------------------
  const slashQuery = value.startsWith("/") && !value.includes("\n")
    ? value.slice(1).toLowerCase()
    : null;
  const slashMatches = React.useMemo(() => {
    if (slashQuery === null) return [];
    return SLASH_COMMANDS.filter(
      (c) => c.cmd.startsWith(slashQuery)
        || c.label.toLowerCase().includes(slashQuery),
    );
  }, [slashQuery]);
  const menuOpen = slashMatches.length > 0;
  const clampedMenuIdx = Math.min(menuIdx, Math.max(slashMatches.length - 1, 0));

  const pickCommand = (c: SlashCommand) => {
    updateValue(c.text);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }
    });
  };

  const cancelEdit = () => {
    onCancelEdit();
    const draft = typeof window !== "undefined"
      ? window.sessionStorage.getItem(draftKey(threadId)) ?? ""
      : "";
    setValue(draft);
  };

  const submit = () => {
    const text = value.trim();
    if (!text || disabled || isStreaming) return;
    onSend(text);
    setValue("");
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(draftKey(threadId));
    }
    requestAnimationFrame(() => taRef.current?.focus());
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMenuIdx((i) => (i + 1) % slashMatches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMenuIdx((i) => (i - 1 + slashMatches.length) % slashMatches.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pickCommand(slashMatches[clampedMenuIdx]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        updateValue("");
        return;
      }
    }
    if (
      e.key === "Enter"
      && !e.shiftKey
      && !(e.nativeEvent as KeyboardEvent).isComposing
    ) {
      e.preventDefault();
      submit();
      return;
    }
    if (e.key === "ArrowUp" && value === "" && !isStreaming && onRecallLast) {
      e.preventDefault();
      onRecallLast();
      return;
    }
    if (e.key === "Escape") {
      if (editing) {
        e.preventDefault();
        cancelEdit();
      } else if (isStreaming) {
        e.preventDefault();
        onAbort();
      }
    }
  };

  const chars = value.length;
  const showCounter = chars > 500;

  return (
    <div className="sticky bottom-0 border-t border-ink-200 bg-card/95 px-4 pb-3 pt-3 backdrop-blur">
      <div className="relative mx-auto max-w-4xl">
        {/* Slash-command menu */}
        {menuOpen ? (
          <div
            role="listbox"
            aria-label="Quick commands"
            className="absolute bottom-full left-0 right-0 z-30 mb-2 overflow-hidden
                       rounded-xl border border-ink-200 bg-card shadow-card animate-fadeInUp"
          >
            <div className="border-b border-ink-100 px-3 py-1.5 text-[10px] font-bold
                            uppercase tracking-wider text-ink-400">
              Quick commands
            </div>
            <div className="max-h-72 overflow-y-auto py-1">
              {slashMatches.map((c, i) => (
                <button
                  key={c.cmd}
                  type="button"
                  role="option"
                  aria-selected={i === clampedMenuIdx}
                  onMouseEnter={() => setMenuIdx(i)}
                  onClick={() => pickCommand(c)}
                  className={cn(
                    "flex w-full items-baseline gap-3 px-3 py-2 text-left text-sm",
                    i === clampedMenuIdx ? "bg-amber-50" : "hover:bg-ink-50",
                  )}
                >
                  <code className="shrink-0 font-mono text-xs font-bold text-amber-700">
                    /{c.cmd}
                  </code>
                  <span className="min-w-0 flex-1 truncate font-medium text-ink-700">
                    {c.label}
                  </span>
                  <span className="hidden max-w-[45%] truncate text-xs text-ink-400 md:block">
                    {c.text}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {/* Edit-mode banner */}
        {editing ? (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-amber-200
                          bg-amber-50 px-3 py-1.5 text-xs text-amber-900 animate-fadeInUp">
            <Pencil size={12} className="shrink-0 text-amber-600" />
            <span className="min-w-0 truncate">
              Editing your message: sending rewinds the conversation from that point.
            </span>
            <button
              type="button"
              onClick={cancelEdit}
              className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md
                         px-1.5 py-0.5 font-semibold text-amber-800 hover:bg-amber-100"
            >
              <X size={11} /> Cancel
            </button>
          </div>
        ) : null}

        <div
          className={cn(
            "flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-card",
            "transition-colors focus-within:border-accent focus-within:shadow-glow",
            editing ? "border-amber-300" : "border-ink-200",
          )}
        >
          <textarea
            ref={taRef}
            value={value}
            rows={1}
            aria-label="Message Copilot"
            onChange={(e) => updateValue(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={disabled}
            placeholder={
              isStreaming
                ? "Streaming… press Esc to stop"
                : "Ask about data, training, evals, deployment: or type / for commands"
            }
            className="composer-input max-h-60 min-h-[40px] flex-1 resize-none
                       bg-transparent px-2 py-2 text-sm placeholder:text-ink-400
                       focus:outline-none disabled:opacity-50"
          />
          {isStreaming ? (
            <Button variant="danger" size="md" onClick={onAbort} title="Stop generating (Esc)">
              <Square size={13} /> Stop
            </Button>
          ) : (
            <Button
              variant="primary"
              size="md"
              onClick={submit}
              disabled={!value.trim() || disabled}
              title="Send (Enter)"
              aria-label="Send message"
            >
              {editing ? <Pencil size={14} /> : <Send size={14} />}
              {editing ? "Resend" : "Send"}
            </Button>
          )}
        </div>

        {/* Hint row */}
        <div className="mt-1.5 flex items-center gap-3 px-1 text-[10px] text-ink-400">
          <span className="hidden items-center gap-1 sm:inline-flex">
            <span className="kbd">Enter</span> send
          </span>
          <span className="hidden items-center gap-1 sm:inline-flex">
            <span className="kbd">Shift+Enter</span> newline
          </span>
          <span className="hidden items-center gap-1 sm:inline-flex">
            <span className="kbd">/</span> commands
          </span>
          <span className="hidden items-center gap-1 md:inline-flex">
            <span className="kbd">↑</span> edit last
          </span>
          {isStreaming ? (
            <span className="inline-flex items-center gap-1 text-amber-700">
              <CircleSlash size={10} />
              <span className="kbd">Esc</span> stop
            </span>
          ) : null}
          {showCounter ? (
            <span className="ml-auto tabular-nums">
              {chars.toLocaleString()} chars · ~{Math.ceil(chars / 4).toLocaleString()} tok
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** Floating jump-to-latest affordance used by the thread view. */
export function JumpToLatest({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Jump to latest message"
      className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full
                 border border-ink-200 bg-card px-3 py-1.5 text-xs font-semibold
                 text-ink-700 shadow-card transition-all hover:border-accent
                 hover:shadow-glow animate-fadeInUp"
    >
      <ArrowUp size={12} className="rotate-180" />
      Latest
    </button>
  );
}
