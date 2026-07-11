"use client";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";
import { useRouter } from "next/navigation";
import { Activity, AlertTriangle, Database, Flame, FlaskConical, LineChart, Loader2, Rocket, Wrench } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { Composer, JumpToLatest, type EditingState } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { ChatHeader } from "./ChatHeader";
import { ModelPicker } from "./ModelPicker";
import { PuffinMark } from "./PuffinMark";
import {
  useChatStream, type ChatTurn, type SendOptions,
} from "@/lib/hooks/useChatStream";
import { ChatActionsProvider } from "@/lib/chatActions";
import { consumeAIPrompt } from "@/lib/askAI";
import type { StoredMessage, ThreadSummary } from "@/lib/types";

const STARTERS: Array<{
  icon: typeof Activity; title: string; text: string;
}> = [
  { icon: Activity, title: "Project pulse",
    text: "What's the state of this project? What should I do next?" },
  { icon: Database, title: "Audit my data",
    text: "Audit data/raw/example.jsonl and tell me if it's ready to train." },
  { icon: Flame, title: "Smoke train",
    text: "Run a smoke train and watch progress live." },
  { icon: FlaskConical, title: "Evals + gate",
    text: "Run all evals on the latest adapter, then apply the gate." },
  { icon: Rocket, title: "Ship it",
    text: "Push the latest passing adapter to the registry and promote it to staging." },
  { icon: LineChart, title: "Watch production",
    text: "Show recent serving traffic, quality, and drift: anything odd?" },
];

function textOf(turn: ChatTurn): string {
  return turn.blocks
    .filter((b) => b.type === "text")
    .map((b) => b.text ?? "")
    .join("\n\n")
    .trim();
}

/** Derive a thread title from the first message (first line, clamped). */
function titleFrom(text: string): string {
  const line = text.split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  const clean = line.replace(/[#*`>_~]/g, "").trim();
  return clean.length > 60 ? `${clean.slice(0, 57)}…` : clean || "New conversation";
}

function download(filename: string, mime: string, content: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function exportSlug(thread: ThreadSummary): string {
  const base = thread.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 40) || "conversation";
  return `${base}-${thread.id.slice(-6)}`;
}

function buildMarkdown(thread: ThreadSummary, messages: StoredMessage[]): string {
  const lines: string[] = [
    `# ${thread.title}`,
    "",
    `_Model: ${thread.model} · Exported ${new Date().toLocaleString()}_`,
    "",
  ];
  for (const m of messages) {
    const text = m.content
      .filter((b) => b.type === "text")
      .map((b) => (b as { text: string }).text)
      .join("\n\n")
      .trim();
    const toolUses = m.content.filter((b) => b.type === "tool_use") as Array<{
      name: string; input: Record<string, unknown>;
    }>;
    // Skip tool_result round-trip messages: the tool call line covers them.
    if (m.role === "user" && !text) continue;
    if (!text && toolUses.length === 0) continue;
    lines.push(`## ${m.role === "user" ? "You" : "Puffin Copilot"}`, "");
    if (text) lines.push(text, "");
    for (const t of toolUses) {
      lines.push(`> 🔧 \`${t.name}(${JSON.stringify(t.input ?? {})})\``, "");
    }
  }
  return lines.join("\n");
}

function useElapsedSeconds(startedAt: number | null): number | null {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (startedAt == null) return;
    setNow(Date.now());
    const iv = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(iv);
  }, [startedAt]);
  if (startedAt == null) return null;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

export function ChatThread({ threadId }: { threadId: string }) {
  const router = useRouter();
  const { data, mutate } = useSWR(
    threadId ? `thread:${threadId}` : null,
    () => api.getThread(threadId),
  );
  const { data: modelsData } = useSWR("models", () => api.models());
  const chat = useChatStream(threadId);
  const messages = data?.messages;
  const thread = data?.thread;
  const loadedKey = React.useRef<string | null>(null);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const stickToBottomRef = React.useRef(true);
  const [showJump, setShowJump] = React.useState(false);
  const [editing, setEditing] = React.useState<EditingState | null>(null);
  const elapsed = useElapsedSeconds(chat.startedAt);

  // Replay persisted history when the thread loads.
  React.useEffect(() => {
    if (!messages) return;
    const key = `${threadId}:${messages.length}`;
    if (loadedKey.current === key) return;
    loadedKey.current = key;
    chat.setFromStored(messages);
  }, [messages, threadId, chat]);

  // Reset edit state when switching threads.
  React.useEffect(() => { setEditing(null); }, [threadId]);

  const scrollToBottom = React.useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  const handleScroll = React.useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distance < 140;
    setShowJump(distance > 320);
  }, []);

  // Auto-scroll only while the reader is already near the bottom. Instant
  // during streaming (smooth scrolling fights the delta rate), smooth after.
  React.useEffect(() => {
    if (stickToBottomRef.current) {
      requestAnimationFrame(() =>
        scrollToBottom(chat.isStreaming ? "auto" : "smooth"));
    }
  }, [chat.turns, chat.isStreaming, scrollToBottom]);

  // --- Send pipeline -----------------------------------------------------
  const maybeAutoTitle = React.useCallback((text: string) => {
    const t = data?.thread;
    if (!t || t.title !== "New conversation") return;
    if (chat.turns.some((x) => x.role === "user")) return;
    void api.updateThread(threadId, { title: titleFrom(text) })
      .then(() => {
        void globalMutate("threads");
        void mutate();
      })
      .catch(() => { /* cosmetic: never block the send */ });
  }, [data?.thread, chat.turns, threadId, mutate]);

  const send = React.useCallback(async (text: string, opts?: SendOptions) => {
    stickToBottomRef.current = true;
    maybeAutoTitle(text);
    await chat.send(text, opts);
    // After the stream ends, refresh the server view so the persisted
    // message ids/timestamps replace the optimistic locals on next nav.
    void mutate();
  }, [chat.send, maybeAutoTitle, mutate]);
  const sendRef = React.useRef(send);
  sendRef.current = send;
  const sendPlain = React.useCallback(
    (text: string) => sendRef.current(text), []);

  const handleComposerSend = React.useCallback((text: string) => {
    const editIdx = editing?.idx;
    setEditing(null);
    void sendRef.current(
      text,
      editIdx != null ? { truncateFromIdx: editIdx } : undefined,
    );
  }, [editing]);

  const turnsRef = React.useRef(chat.turns);
  turnsRef.current = chat.turns;

  const handleEdit = React.useCallback((turn: ChatTurn) => {
    if (turn.storedIdx == null) return;
    setEditing({ idx: turn.storedIdx, text: textOf(turn) });
  }, []);

  const handleRecallLast = React.useCallback(() => {
    const turns = turnsRef.current;
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const t = turns[i];
      if (t.role === "user" && t.storedIdx != null) {
        setEditing({ idx: t.storedIdx, text: textOf(t) });
        return;
      }
    }
  }, []);

  const handleRegenerate = React.useCallback(() => {
    const turns = turnsRef.current;
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const t = turns[i];
      if (t.role === "user" && t.storedIdx != null) {
        const text = textOf(t);
        if (text) void sendRef.current(text, { truncateFromIdx: t.storedIdx });
        return;
      }
    }
  }, []);

  const handleContinue = React.useCallback(() => {
    void sendRef.current("Continue.");
  }, []);

  const handleCancelEdit = React.useCallback(() => setEditing(null), []);

  // Ask-AI-anywhere handoff: a page queued a prompt and navigated here -
  // fire it once the persisted history has been replayed (so the stored
  // replay can't clobber the streaming turn).
  const pendingConsumed = React.useRef(false);
  React.useEffect(() => {
    if (pendingConsumed.current || !messages) return;
    pendingConsumed.current = true;
    const pending = consumeAIPrompt();
    if (pending) void sendRef.current(pending);
  }, [messages]);

  // --- Header actions ------------------------------------------------------
  const handleRename = React.useCallback((title: string) => {
    void api.updateThread(threadId, { title }).then(() => {
      void mutate();
      void globalMutate("threads");
    });
  }, [threadId, mutate]);

  const handleChangeModel = React.useCallback((model: string) => {
    void api.updateThread(threadId, { model }).then(() => {
      void mutate();
      void globalMutate("threads");
    });
  }, [threadId, mutate]);

  const handleDelete = React.useCallback(() => {
    void api.deleteThread(threadId).then(() => {
      void globalMutate("threads");
      router.push("/");
    });
  }, [threadId, router]);

  const handleExportMarkdown = React.useCallback(() => {
    if (!thread || !messages) return;
    download(`${exportSlug(thread)}.md`, "text/markdown",
      buildMarkdown(thread, messages));
  }, [thread, messages]);

  const handleExportJson = React.useCallback(() => {
    if (!thread || !messages) return;
    download(`${exportSlug(thread)}.json`, "application/json",
      JSON.stringify({ thread, messages }, null, 2));
  }, [thread, messages]);

  // --- Derived view state --------------------------------------------------
  const isEmpty = Boolean(data) && chat.turns.length === 0;

  const currentTool = React.useMemo(() => {
    if (!chat.isStreaming) return null;
    const last = chat.turns[chat.turns.length - 1];
    if (!last || last.role !== "assistant") return null;
    const lastBlock = [...last.blocks].reverse().find(
      (b) => b.type === "tool" && !b.toolResult);
    return lastBlock?.toolName ?? null;
  }, [chat.turns, chat.isStreaming]);

  const retryTextFor = React.useCallback((turnIndex: number): string | null => {
    for (let i = turnIndex - 1; i >= 0; i -= 1) {
      const candidate = chat.turns[i];
      if (candidate.role !== "user") continue;
      const text = textOf(candidate);
      return text || null;
    }
    return null;
  }, [chat.turns]);

  const threadModel = thread
    ? modelsData?.models.find((m) => m.id === thread.model)
    : undefined;
  const modelUnavailable = Boolean(
    thread && modelsData && (!threadModel || !threadModel.available));

  return (
    <ChatActionsProvider value={{ send: sendPlain, isStreaming: chat.isStreaming }}>
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <ChatHeader
        thread={thread}
        usage={chat.usage}
        isStreaming={chat.isStreaming}
        onRename={handleRename}
        onChangeModel={handleChangeModel}
        onDelete={handleDelete}
        onExportMarkdown={handleExportMarkdown}
        onExportJson={handleExportJson}
      />

      <div className="relative min-h-0 flex-1">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto px-4 py-6"
        >
          <div className="mx-auto max-w-4xl space-y-5">
            {!data ? (
              <div className="space-y-4 pt-4" aria-hidden="true">
                <div className="h-8 w-2/5 animate-pulse rounded-lg bg-ink-100" />
                <div className="h-24 animate-pulse rounded-2xl bg-ink-100" />
                <div className="ml-auto h-12 w-1/2 animate-pulse rounded-2xl bg-ink-100" />
                <div className="h-24 animate-pulse rounded-2xl bg-ink-100" />
              </div>
            ) : isEmpty ? (
              <div className="space-y-6 py-10 text-center">
                <div className="inline-flex h-14 w-14 items-center justify-center
                                overflow-hidden rounded-2xl shadow-glow">
                  <PuffinMark size={56} />
                </div>
                <div className="space-y-2">
                  <h1 className="text-3xl font-extrabold tracking-tight text-ink">
                    Fine-tune any open LLM. End-to-end.
                  </h1>
                  <p className="mx-auto max-w-xl text-ink-500">
                    Talk to the platform. I can read your data, run training,
                    evaluate, deploy, and inspect monitoring from this chat.
                  </p>
                </div>

                {modelUnavailable && thread ? (
                  <div className="mx-auto flex max-w-xl flex-col items-center gap-3
                                  rounded-xl border border-amber-200 bg-amber-50 p-4
                                  text-sm text-amber-900 sm:flex-row sm:text-left">
                    <AlertTriangle size={18} className="shrink-0 text-amber-600" />
                    <div className="min-w-0 flex-1">
                      <b>{threadModel?.label ?? thread.model}</b> isn&apos;t usable on
                      this machine
                      {threadModel?.requires ? (
                        <> (needs <code className="font-mono text-xs">{threadModel.requires}</code>)</>
                      ) : null}
                      . Pick an available model:
                    </div>
                    <ModelPicker compact value={thread.model} onChange={handleChangeModel} />
                  </div>
                ) : null}

                <div className="mx-auto grid max-w-2xl grid-cols-1 gap-3 pt-2 md:grid-cols-2">
                  {STARTERS.map((s) => {
                    const Icon = s.icon;
                    return (
                      <button
                        key={s.title}
                        onClick={() => sendPlain(s.text)}
                        disabled={chat.isStreaming}
                        className="group flex items-start gap-3 rounded-xl border
                                   border-ink-200 bg-card p-4 text-left shadow-card
                                   transition-all hover:border-accent hover:shadow-glow
                                   disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center
                                         justify-center rounded-lg bg-amber-100
                                         text-amber-700 transition-colors
                                         group-hover:bg-amber-200">
                          <Icon size={15} />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-sm font-bold text-ink">
                            {s.title}
                          </span>
                          <span className="block text-xs leading-snug text-ink-500">
                            {s.text}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>

                <div className="flex flex-wrap items-center justify-center gap-x-4
                                gap-y-1 pt-2 text-[10px] text-ink-400">
                  <span><span className="kbd">/</span> focus composer</span>
                  <span><span className="kbd">Ctrl+Shift+O</span> new chat</span>
                  <span><span className="kbd">Ctrl+K</span> ask AI anywhere</span>
                  <span><span className="kbd">↑</span> edit last message</span>
                </div>
              </div>
            ) : (
              chat.turns.map((t, idx) => {
                const retryText = t.status === "error" ? retryTextFor(idx) : null;
                const isLast = idx === chat.turns.length - 1;
                return (
                  <MessageBubble
                    key={t.id}
                    turn={t}
                    isLast={isLast}
                    busy={chat.isStreaming}
                    onRetry={retryText ? () => sendPlain(retryText) : undefined}
                    onRegenerate={
                      t.role === "assistant" && isLast ? handleRegenerate : undefined
                    }
                    onContinue={
                      t.role === "assistant" && isLast ? handleContinue : undefined
                    }
                    onEdit={t.role === "user" ? handleEdit : undefined}
                  />
                );
              })
            )}
          </div>
        </div>

        {showJump ? (
          <div className="pointer-events-none absolute bottom-4 left-1/2 z-10
                          -translate-x-1/2">
            <JumpToLatest onClick={() => {
              stickToBottomRef.current = true;
              scrollToBottom("smooth");
            }} />
          </div>
        ) : null}
      </div>

      {/* Screen-reader stream status (visual strip below). */}
      <div className="sr-only" role="status" aria-live="polite">
        {chat.isStreaming ? "Assistant is responding" : ""}
      </div>

      {chat.isStreaming ? (
        <div className="flex items-center gap-2 border-t border-ink-200 bg-amber-50/60
                        px-4 py-2 text-xs text-ink-700">
          {currentTool ? (
            <>
              <Wrench size={12} className="text-amber-600" />
              <span>
                Running <code className="font-mono font-bold">{currentTool}</code>…
              </span>
            </>
          ) : (
            <>
              <Loader2 size={12} className="animate-spin text-amber-600" />
              <span>Thinking…</span>
            </>
          )}
          {elapsed != null && elapsed >= 3 ? (
            <span className="tabular-nums text-ink-400">{elapsed}s</span>
          ) : null}
          <span className="ml-auto tabular-nums text-ink-400">
            in {chat.usage.cumulative_input.toLocaleString()} ·
            out {chat.usage.cumulative_output.toLocaleString()} tok
          </span>
        </div>
      ) : null}

      <Composer
        threadId={threadId}
        isStreaming={chat.isStreaming}
        editing={editing}
        onSend={handleComposerSend}
        onAbort={chat.abort}
        onCancelEdit={handleCancelEdit}
        onRecallLast={handleRecallLast}
        disabled={!threadId}
      />
    </div>
    </ChatActionsProvider>
  );
}
