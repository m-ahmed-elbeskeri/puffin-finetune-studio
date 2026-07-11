"use client";
import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowRight, Check, Copy, Loader2, Pencil, RefreshCw, RotateCcw } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { fmtRelative } from "@/lib/format";
import { ToolCallTrace } from "./ToolCallTrace";
import { CodeBlock } from "./CodeBlock";
import { PuffinMark } from "./PuffinMark";
import { ArtifactRouter } from "@/components/artifacts/ArtifactRouter";
import type { ChatTurn } from "@/lib/hooks/useChatStream";

/** Pull code text + language out of react-markdown's <pre> children. */
function extractCode(
  children: React.ReactNode,
): { code: string; language: string } | null {
  if (!React.isValidElement(children)) return null;
  const props = children.props as {
    className?: string; children?: React.ReactNode;
  };
  const language = /language-(\w+)/.exec(props.className || "")?.[1] ?? "";
  const raw = props.children;
  const code = typeof raw === "string"
    ? raw
    : Array.isArray(raw) ? raw.map(String).join("") : "";
  return { code: String(code).replace(/\n$/, ""), language };
}

const MARKDOWN_COMPONENTS = {
  pre({ children }: { children?: React.ReactNode }) {
    const extracted = extractCode(children);
    if (extracted) {
      return <CodeBlock language={extracted.language} code={extracted.code} />;
    }
    return <pre>{children}</pre>;
  },
};

function turnText(turn: ChatTurn): string {
  return turn.blocks
    .filter((b) => b.type === "text")
    .map((b) => b.text ?? "")
    .join("\n\n")
    .trim();
}

function CopyButton({
  text, label, className,
}: {
  text: string; label: string; className?: string;
}) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_400);
    } catch { /* clipboard unavailable */ }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px]",
        "text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink",
        className,
      )}
      aria-label={label}
      title={label}
    >
      {copied
        ? <Check size={12} className="text-emerald-500" />
        : <Copy size={12} />}
    </button>
  );
}

export interface MessageBubbleProps {
  turn: ChatTurn;
  isLast: boolean;
  /** Thread-level streaming flag: hides history-rewriting actions mid-flight. */
  busy: boolean;
  onRetry?: () => void;
  onRegenerate?: () => void;
  onContinue?: () => void;
  onEdit?: (turn: ChatTurn) => void;
}

export const MessageBubble = React.memo(function MessageBubble({
  turn, isLast, busy, onRetry, onRegenerate, onContinue, onEdit,
}: MessageBubbleProps) {
  const isUser = turn.role === "user";
  const isStreaming = turn.status === "streaming";
  const text = React.useMemo(() => turnText(turn), [turn]);
  const timestamp = fmtRelative(turn.createdAt);
  const absoluteTime = new Date(turn.createdAt).toLocaleString();

  // ------------------------------------------------------------- user turn
  if (isUser) {
    const canEdit = !busy && turn.storedIdx != null && Boolean(onEdit);
    return (
      <div className="group flex w-full items-end justify-end gap-1 animate-fadeInUp">
        <div
          className="mb-1 flex items-center gap-0.5 opacity-0 transition-opacity
                     group-hover:opacity-100 group-focus-within:opacity-100"
        >
          {canEdit ? (
            <button
              type="button"
              onClick={() => onEdit?.(turn)}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px]
                         text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink"
              aria-label="Edit and resend"
              title="Edit and resend (rewinds the conversation here)"
            >
              <Pencil size={12} />
            </button>
          ) : null}
          <CopyButton text={text} label="Copy message" />
        </div>
        <div
          title={absoluteTime}
          className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md
                     bg-ink px-4 py-2.5 text-sm text-ink-50 shadow-card"
        >
          {text}
        </div>
      </div>
    );
  }

  // -------------------------------------------------------- assistant turn
  const showThinking = isStreaming && turn.blocks.length === 0;
  const truncated = turn.status === "done" && turn.stopReason === "max_tokens";

  return (
    <div className="group flex w-full gap-3 animate-fadeInUp" title={absoluteTime}>
      <div className="mt-0.5 h-7 w-7 shrink-0 overflow-hidden rounded-lg shadow-card">
        <PuffinMark size={28} />
      </div>
      <div className="min-w-0 flex-1">
        {showThinking ? (
          <div className="flex items-center gap-2 py-1.5 text-xs text-ink-500">
            <Loader2 size={13} className="animate-spin text-amber-600" />
            <span>Thinking</span>
            <span className="flex gap-0.5">
              <span className="h-1 w-1 animate-pulseDot rounded-full bg-amber-400" />
              <span className="h-1 w-1 animate-pulseDot rounded-full bg-amber-400"
                    style={{ animationDelay: "150ms" }} />
              <span className="h-1 w-1 animate-pulseDot rounded-full bg-amber-400"
                    style={{ animationDelay: "300ms" }} />
            </span>
          </div>
        ) : null}

        {turn.blocks.map((b, idx) => {
          if (b.type === "text") {
            return (
              <div
                key={idx}
                className={cn(
                  "prose-puffin text-sm text-ink-800",
                  b.streaming && "cursor-blink",
                )}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={MARKDOWN_COMPONENTS}
                >
                  {b.text ?? ""}
                </ReactMarkdown>
              </div>
            );
          }
          return (
            <div key={idx} className="my-2 space-y-2">
              <ToolCallTrace
                name={b.toolName ?? "tool"}
                input={b.toolInput}
                result={b.toolResult}
                pending={!b.toolResult}
              />
              {b.toolResult ? <ArtifactRouter artifact={b.toolResult} /> : null}
            </div>
          );
        })}

        {truncated && onContinue ? (
          <div className="mt-2 flex items-center gap-2 rounded-lg border border-amber-200
                          bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <span>Response hit the max-token limit.</span>
            <button
              type="button"
              onClick={onContinue}
              disabled={busy}
              className="ml-auto inline-flex items-center gap-1 rounded-md border
                         border-amber-300 bg-card px-2 py-1 font-semibold
                         text-amber-800 transition-colors hover:bg-amber-100
                         disabled:opacity-50"
            >
              Continue <ArrowRight size={11} />
            </button>
          </div>
        ) : null}

        {turn.status === "error" ? (
          <div className="mt-2 flex items-center gap-2 rounded-lg border border-red-200
                          bg-red-50 px-3 py-2">
            <div className="text-xs font-semibold text-red-700">
              Conversation stopped.
            </div>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                disabled={busy}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border
                           border-red-200 bg-card px-2 py-1 text-xs font-semibold
                           text-red-700 transition-colors hover:bg-red-100
                           disabled:opacity-50"
              >
                <RotateCcw size={12} />
                Retry
              </button>
            ) : null}
          </div>
        ) : null}

        {!isStreaming && (text || turn.blocks.length > 0) ? (
          <div
            className="mt-1 flex h-6 items-center gap-0.5 opacity-0
                       transition-opacity group-hover:opacity-100
                       group-focus-within:opacity-100"
          >
            {text ? <CopyButton text={text} label="Copy response" /> : null}
            {isLast && onRegenerate && !busy ? (
              <button
                type="button"
                onClick={onRegenerate}
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-1
                           text-[11px] text-ink-400 transition-colors
                           hover:bg-ink-100 hover:text-ink"
                aria-label="Regenerate response"
                title="Regenerate response"
              >
                <RefreshCw size={12} />
              </button>
            ) : null}
            <span className="ml-1 select-none text-[10px] text-ink-300">
              {timestamp}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
});
