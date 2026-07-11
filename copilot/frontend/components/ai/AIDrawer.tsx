"use client";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";
import { usePathname } from "next/navigation";
import { AlertCircle, CheckCircle2, Loader2, Plus, Send, Sparkles, Square, Wrench, X } from "@/components/ui/icons";
import { api, getCurrentProjectId } from "@/lib/api";
import { cn } from "@/lib/cn";
import { sectionContext } from "@/lib/aiContext";
import { useUiStore } from "@/lib/stores/uiStore";
import { useChatStream } from "@/lib/hooks/useChatStream";
import { CodeActionsProvider, type CodeActions } from "@/lib/codeActions";
import { ChatActionsProvider } from "@/lib/chatActions";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { PuffinMark } from "@/components/chat/PuffinMark";

const threadKey = () =>
  `puffin_drawer_thread_${getCurrentProjectId() ?? "default"}`;

/** Pick a model that can actually answer on this machine. */
async function resolveModel(): Promise<string | undefined> {
  try {
    const { models, default: def } = await api.models();
    const byId = new Map(models.map((m) => [m.id, m]));
    if (byId.get(def)?.available) return def;
    return models.find((m) => m.available)?.id ?? def;
  } catch {
    return undefined;
  }
}

export function AIDrawer() {
  const open = useUiStore((s) => s.drawerOpen);
  const close = useUiStore((s) => s.closeDrawer);
  const toggle = useUiStore((s) => s.toggleDrawer);
  const consumePendingPrompt = useUiStore((s) => s.consumePendingPrompt);
  const pendingPrompt = useUiStore((s) => s.pendingPrompt);

  const pathname = usePathname();
  const section = sectionContext(pathname);

  const [threadId, setThreadId] = React.useState<string | null>(null);
  const [ensuring, setEnsuring] = React.useState(false);
  const [ensureError, setEnsureError] = React.useState<string | null>(null);
  const chat = useChatStream(threadId);

  // Ctrl/Cmd+K toggles the panel from anywhere.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  // Ensure the side-panel conversation exists (per project, persisted).
  const ensureThread = React.useCallback(async () => {
    if (ensuring) return;
    setEnsuring(true);
    setEnsureError(null);
    try {
      const key = threadKey();
      const stored = window.localStorage.getItem(key);
      if (stored) {
        try {
          await api.getThread(stored);
          setThreadId(stored);
          return;
        } catch {
          window.localStorage.removeItem(key);
        }
      }
      const model = await resolveModel();
      const { thread } = await api.createThread({
        title: "AI side panel",
        ...(model ? { model } : {}),
      });
      window.localStorage.setItem(key, thread.id);
      setThreadId(thread.id);
      void globalMutate("threads");
    } catch (exc) {
      setEnsureError((exc as Error).message);
    } finally {
      setEnsuring(false);
    }
  }, [ensuring]);

  React.useEffect(() => {
    if (open && !threadId) void ensureThread();
  }, [open, threadId, ensureThread]);

  // Replay persisted panel history once the thread resolves.
  const { data: threadData } = useSWR(
    open && threadId ? `thread:${threadId}` : null,
    () => api.getThread(threadId as string),
  );
  const replayedFor = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!threadData || !threadId) return;
    const key = `${threadId}:${threadData.messages.length}`;
    if (replayedFor.current === key) return;
    replayedFor.current = key;
    chat.setFromStored(threadData.messages);
  }, [threadData, threadId, chat]);

  const send = React.useCallback((text: string) => {
    const t = text.trim();
    if (!t) return;
    void chat.send(t, { systemExtra: section.systemExtra });
  }, [chat, section.systemExtra]);
  const sendRef = React.useRef(send);
  sendRef.current = send;

  // Interactive artifact cards (e.g. ask_user_question) submit through this.
  const chatActions = React.useMemo(
    () => ({ send, isStreaming: chat.isStreaming }),
    [send, chat.isStreaming]);

  // Fire a queued prompt (from AskAIButton anywhere) once we're ready.
  React.useEffect(() => {
    if (!open || !threadId || chat.isStreaming || !pendingPrompt) return;
    const p = consumePendingPrompt();
    if (p) sendRef.current(p);
  }, [open, threadId, chat.isStreaming, pendingPrompt, consumePendingPrompt]);

  const newConversation = React.useCallback(async () => {
    const model = await resolveModel();
    const { thread } = await api.createThread({
      title: "AI side panel",
      ...(model ? { model } : {}),
    });
    window.localStorage.setItem(threadKey(), thread.id);
    replayedFor.current = null;
    setThreadId(thread.id);
    void globalMutate("threads");
  }, []);

  // --- Save-as-script (data section) ------------------------------------
  const [saveCode, setSaveCode] = React.useState<string | null>(null);
  const codeActions = React.useMemo<CodeActions | null>(() => {
    if (!pathname?.startsWith("/data")) return null;
    return {
      label: "Save as pipeline script",
      languages: ["python", "py"],
      onAction: (code) => setSaveCode(code),
    };
  }, [pathname]);

  // --- Scroll handling ---------------------------------------------------
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const stickRef = React.useRef(true);
  React.useEffect(() => {
    if (!stickRef.current) return;
    const el = scrollRef.current;
    if (el) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  }, [chat.turns]);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const currentTool = React.useMemo(() => {
    if (!chat.isStreaming) return null;
    const last = chat.turns[chat.turns.length - 1];
    if (!last || last.role !== "assistant") return null;
    const block = [...last.blocks].reverse().find(
      (b) => b.type === "tool" && !b.toolResult);
    return block?.toolName ?? null;
  }, [chat.turns, chat.isStreaming]);

  const retryTextFor = React.useCallback((idx: number): string | null => {
    for (let i = idx - 1; i >= 0; i -= 1) {
      const t = chat.turns[i];
      if (t.role !== "user") continue;
      const text = t.blocks.filter((b) => b.type === "text")
        .map((b) => b.text ?? "").join("\n\n").trim();
      return text || null;
    }
    return null;
  }, [chat.turns]);

  const isEmpty = chat.turns.length === 0;

  return (
    <>
    {/* On mobile the panel overlays the page; tap the backdrop to close. */}
    {open ? (
      <div className="lg:hidden fixed inset-0 z-40 bg-black/50"
        onClick={close} aria-hidden />
    ) : null}
    <aside
      role="complementary"
      aria-label="Copilot"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          if (chat.isStreaming) chat.abort();
          else close();
        }
      }}
      className={cn(
        "z-30 flex-col overflow-hidden border-l border-ink-200 bg-card",
        "lg:sticky lg:top-0 lg:flex lg:h-screen lg:shrink-0 lg:transition-[width] lg:duration-200 lg:ease-out",
        open
          ? "fixed inset-y-0 right-0 z-50 flex h-screen w-full max-w-md shadow-card lg:w-[24rem] lg:max-w-[95vw] lg:shadow-none"
          : "hidden lg:flex lg:w-14",
      )}
    >
      {!open ? (
        <button
          type="button"
          onClick={toggle}
          title="Copilot (Ctrl+K)"
          aria-label="Open Copilot"
          className="group flex h-full w-full flex-col items-center gap-3 py-4
                     text-ink-500 transition-colors hover:bg-ink-50 hover:text-ink"
        >
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg
                           bg-amber-50 text-accent-600 transition-colors group-hover:bg-amber-100">
            <Sparkles size={18} />
          </span>
          <span className="text-[11px] font-bold uppercase tracking-widest [writing-mode:vertical-rl]">
            Copilot
          </span>
          <span className="kbd mt-auto">Ctrl K</span>
        </button>
      ) : (
      <>
      {/* Header */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-ink-200 px-3">
        <span className="inline-flex h-7 w-7 items-center justify-center overflow-hidden rounded-lg">
          <PuffinMark size={28} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold leading-tight text-ink">Copilot</div>
          <div className="flex items-center gap-1 text-[10px] leading-tight text-ink-400">
            <Sparkles size={9} className="text-coral" />
            tuned for: {section.label}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void newConversation()}
          title="New side-panel conversation"
          aria-label="New side-panel conversation"
          className="rounded-lg p-1.5 text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink"
        >
          <Plus size={15} />
        </button>
        <button
          type="button"
          onClick={close}
          title="Close (Esc)"
          aria-label="Close AI side panel"
          className="rounded-lg p-1.5 text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink"
        >
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 space-y-4 overflow-y-auto px-3 py-4"
      >
        {ensureError ? (
          <div className="flex items-start gap-2 rounded-lg border border-red-200
                          bg-red-50 p-3 text-xs text-red-700">
            <AlertCircle size={13} className="mt-0.5 shrink-0" />
            <div>
              Couldn&apos;t start the assistant: {ensureError}
              <button
                type="button"
                onClick={() => void ensureThread()}
                className="mt-1 block font-semibold underline"
              >
                Try again
              </button>
            </div>
          </div>
        ) : null}

        {isEmpty && !ensureError ? (
          <div className="space-y-3 pt-2">
            <p className="text-xs text-ink-500">
              I can see this project (files, configs, runs) and act through
              tools. Specialised for <b>{section.label}</b> while you&apos;re here.
            </p>
            <div className="space-y-1.5">
              {section.suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  disabled={chat.isStreaming || !threadId}
                  className="w-full rounded-lg border border-ink-200 bg-card px-3 py-2
                             text-left text-xs text-ink-700 transition-all
                             hover:border-accent hover:shadow-glow disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <ChatActionsProvider value={chatActions}>
          <CodeActionsProvider value={codeActions}>
            {chat.turns.map((t, idx) => {
              const retryText = t.status === "error" ? retryTextFor(idx) : null;
              return (
                <MessageBubble
                  key={t.id}
                  turn={t}
                  isLast={idx === chat.turns.length - 1}
                  busy={chat.isStreaming}
                  onRetry={retryText ? () => send(retryText) : undefined}
                  onContinue={
                    t.role === "assistant" && idx === chat.turns.length - 1
                      ? () => send("Continue.")
                      : undefined
                  }
                />
              );
            })}
          </CodeActionsProvider>
        </ChatActionsProvider>
      </div>

      {/* Streaming strip */}
      {chat.isStreaming ? (
        <div className="flex items-center gap-2 border-t border-ink-200 bg-amber-50/60
                        px-3 py-1.5 text-[11px] text-ink-700">
          {currentTool ? (
            <>
              <Wrench size={11} className="text-amber-600" />
              <span>Running <code className="font-mono font-bold">{currentTool}</code>…</span>
            </>
          ) : (
            <>
              <Loader2 size={11} className="animate-spin text-amber-600" />
              <span>Thinking…</span>
            </>
          )}
        </div>
      ) : null}

      <DrawerComposer
        disabled={!threadId || Boolean(ensureError)}
        isStreaming={chat.isStreaming}
        placeholder={`Ask about ${section.label.toLowerCase()}…`}
        onSend={send}
        onAbort={chat.abort}
      />
      </>
      )}

      {saveCode !== null ? (
        <SaveScriptDialog
          code={saveCode}
          onClose={() => setSaveCode(null)}
        />
      ) : null}
    </aside>
    </>
  );
}

function DrawerComposer({
  disabled, isStreaming, placeholder, onSend, onAbort,
}: {
  disabled: boolean;
  isStreaming: boolean;
  placeholder: string;
  onSend: (text: string) => void;
  onAbort: () => void;
}) {
  const [value, setValue] = React.useState("");
  const taRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`;
  }, [value]);

  const submit = () => {
    const t = value.trim();
    if (!t || disabled || isStreaming) return;
    onSend(t);
    setValue("");
  };

  return (
    <div className="shrink-0 border-t border-ink-200 p-2.5">
      <div className="flex items-end gap-1.5 rounded-xl border border-ink-200 bg-card
                      p-1.5 transition-colors focus-within:border-accent">
        <textarea
          ref={taRef}
          value={value}
          rows={1}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey
                && !(e.nativeEvent as KeyboardEvent).isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          disabled={disabled}
          placeholder={placeholder}
          aria-label="Message the AI side panel"
          className="composer-input max-h-36 min-h-[34px] flex-1 resize-none
                     bg-transparent px-2 py-1.5 text-xs placeholder:text-ink-400
                     focus:outline-none disabled:opacity-50"
        />
        {isStreaming ? (
          <button
            type="button"
            onClick={onAbort}
            title="Stop (Esc)"
            aria-label="Stop generating"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center
                       rounded-lg bg-fail text-white hover:bg-red-700"
          >
            <Square size={12} />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!value.trim() || disabled}
            title="Send (Enter)"
            aria-label="Send"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center
                       rounded-lg bg-accent text-ink shadow-glow transition-colors
                       hover:bg-accent-400 disabled:opacity-40 disabled:shadow-none"
          >
            <Send size={13} />
          </button>
        )}
      </div>
    </div>
  );
}

const NAME_RE = /^[A-Za-z0-9_\-]+\.py$/;

function SaveScriptDialog({
  code, onClose,
}: {
  code: string;
  onClose: () => void;
}) {
  const [name, setName] = React.useState("my_transform.py");
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState<string | null>(null);
  const [warnings, setWarnings] = React.useState<string[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const valid = NAME_RE.test(name);

  const save = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.saveTransform(name, code);
      setDone(`Saved data/transforms/${r.name}`);
      setWarnings(r.warnings);
      void globalMutate("data:transforms");
    } catch (exc) {
      setErr((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-ink/30 p-4">
      <div className="w-full space-y-3 rounded-2xl border border-ink-200 bg-card p-4 shadow-card">
        <div className="text-sm font-bold text-ink">Save as pipeline script</div>
        {done ? (
          <div className="space-y-2">
            <div className="flex items-start gap-2 text-xs text-emerald-700">
              <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
              {done}: find it in the Custom scripts panel on the Data page.
            </div>
            {warnings.map((w) => (
              <div key={w} className="flex items-start gap-2 text-xs text-amber-700">
                <AlertCircle size={13} className="mt-0.5 shrink-0" />{w}
              </div>
            ))}
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="space-y-1">
              <input
                value={name}
                onChange={(e) => setName(e.target.value.trim())}
                aria-label="Script filename"
                className="w-full rounded-lg border border-ink-200 px-2.5 py-1.5
                           font-mono text-xs focus:border-accent focus:outline-none"
              />
              {!valid ? (
                <div className="text-[10px] text-amber-700">
                  Letters, digits, _ or -, ending in .py
                </div>
              ) : (
                <div className="text-[10px] text-ink-400">
                  Saved to <code>data/transforms/{name}</code>; run it from the Data page.
                </div>
              )}
            </div>
            {err ? (
              <div className="flex items-start gap-2 text-xs text-red-700">
                <AlertCircle size={13} className="mt-0.5 shrink-0" />{err}
              </div>
            ) : null}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-ink-200 px-3 py-1.5 text-xs
                           font-semibold text-ink-500 hover:bg-ink-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void save()}
                disabled={!valid || busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3
                           py-1.5 text-xs font-semibold text-ink shadow-glow
                           disabled:opacity-50"
              >
                {busy ? <Loader2 size={12} className="animate-spin" /> : null}
                Save script
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
