/**
 * Global chat-stream store.
 *
 * State lives outside React so users can navigate away from /chat while a
 * stream is in flight: the SSE connection, AbortController, and
 * accumulated turns all live in the store. ChatThread re-subscribes on
 * mount and sees the latest state without a network round-trip.
 *
 * One bucket per thread id, keyed by thread id. We never delete buckets;
 * memory cost is negligible (one open conversation per id) and keeping
 * them lets the user toggle between threads instantly.
 */
"use client";
import { create } from "zustand";

import { api } from "@/lib/api";
import { iterateSse } from "@/lib/sseClient";
import { revalidateData } from "@/lib/revalidate";
import type {
  AnthropicContentBlock, Artifact, StoredMessage, StreamEvent,
} from "@/lib/types";

// Tools and result kinds that change project state. When the AI runs one of
// these, we instantly refresh every data/dashboard panel (no manual reload).
const MUTATING_TOOLS = new Set([
  "data_pipeline_run", "dataset_import_hf", "config_edit",
  "deploy_push", "deploy_promote", "train_start", "train_studio_launch",
  "train_cancel", "eval_run", "gate_apply",
]);
const MUTATING_KINDS = new Set([
  "data_pipeline_result", "config_edit_result", "dataset_import_result",
  "deploy_push_result", "deploy_promote_result", "train_started",
  "train_cancel_result", "eval_result", "gate_result",
]);

function revalidateAfterTool(name: unknown, result: unknown): void {
  const kind = (result as { kind?: string } | undefined)?.kind;
  const mutates =
    (typeof name === "string" && MUTATING_TOOLS.has(name)) ||
    (typeof kind === "string" && MUTATING_KINDS.has(kind));
  if (mutates) revalidateData();
}


export interface ChatBlock {
  type: "text" | "tool";
  text?: string;
  streaming?: boolean;
  toolId?: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  toolResult?: Artifact;
  toolStarted?: boolean;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  blocks: ChatBlock[];
  createdAt: string;
  status?: "streaming" | "done" | "error";
  stopReason?: string;
  // Persisted message idx on the backend: present once the turn has been
  // reconciled with the server snapshot. Powers rewind (regenerate / edit).
  storedIdx?: number;
}

interface UsageState {
  cumulative_input: number;
  cumulative_output: number;
}

export interface SendOptions {
  // Rewind the server-side history to just before this message idx first.
  // Used by regenerate (resend last user text) and edit-and-resend.
  truncateFromIdx?: number;
  // Extra system-prompt context for this turn (e.g. which page the AI side
  // panel is assisting on). Appended server-side to the platform prompt.
  systemExtra?: string;
}

interface ThreadState {
  turns: ChatTurn[];
  isStreaming: boolean;
  usage: UsageState;
  abortCtrl: AbortController | null;
  // Generation counter so old in-flight streams that started before a
  // refresh can be ignored if a newer one supersedes them.
  generation: number;
  // Wall-clock ms when the in-flight stream started (for the elapsed timer).
  startedAt: number | null;
}

const emptyThread = (): ThreadState => ({
  turns: [],
  isStreaming: false,
  usage: { cumulative_input: 0, cumulative_output: 0 },
  abortCtrl: null,
  generation: 0,
  startedAt: null,
});

interface ChatStore {
  threads: Record<string, ThreadState>;

  getThread: (threadId: string) => ThreadState;
  isAnyStreaming: () => boolean;
  streamingThreadIds: () => string[];

  setFromStored: (threadId: string, msgs: StoredMessage[]) => void;
  send: (threadId: string, text: string, opts?: SendOptions) => Promise<void>;
  abort: (threadId: string) => void;

  // Internal helpers: exposed only so the hook layer can debounce
  // setFromStored calls without re-implementing the diff logic.
  _patchThread: (
    threadId: string,
    patch: Partial<ThreadState> | ((s: ThreadState) => Partial<ThreadState>),
  ) => void;
}


/**
 * Walk persisted messages, pair tool_use ↔ tool_result blocks, and emit
 * the render-ready ChatTurn array. Used both by `setFromStored` and by
 * unit tests.
 */
function buildTurnsFromStored(msgs: StoredMessage[]): ChatTurn[] {
  const t: ChatTurn[] = [];
  const toolResultsByUseId = new Map<string, AnthropicContentBlock>();
  for (const m of msgs) {
    if (m.role === "user") {
      for (const b of m.content) {
        if (b.type === "tool_result") {
          toolResultsByUseId.set(b.tool_use_id, b);
        }
      }
    }
  }
  for (const m of msgs) {
    if (m.role === "user") {
      const textBlocks = m.content.filter((b) => b.type === "text");
      if (textBlocks.length === 0) continue;
      t.push({
        id: m.id, role: "user", createdAt: m.created_at, status: "done",
        storedIdx: m.idx,
        blocks: textBlocks.map((b) => ({
          type: "text", text: (b as { text: string }).text,
        })),
      });
    } else {
      const blocks: ChatBlock[] = [];
      for (const b of m.content) {
        if (b.type === "text") {
          blocks.push({ type: "text", text: b.text });
        } else if (b.type === "tool_use") {
          const result = toolResultsByUseId.get(b.id);
          let parsed: Artifact | undefined;
          if (result && result.type === "tool_result") {
            try {
              parsed = JSON.parse(result.content) as Artifact;
            } catch {
              parsed = { kind: "error", message: result.content };
            }
          }
          blocks.push({
            type: "tool", toolId: b.id, toolName: b.name,
            toolInput: b.input, toolResult: parsed, toolStarted: true,
          });
        }
      }
      t.push({
        id: m.id, role: "assistant", createdAt: m.created_at,
        status: "done", storedIdx: m.idx, blocks,
      });
    }
  }
  return t;
}

function friendlyChatError(message: string): string {
  const clean = message.replace(/\s+/g, " ").trim();
  if (/No providers configured/i.test(clean)) {
    return (
      "No AI provider is configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
      + "or configure a local Claude/Codex CLI provider, then restart the backend."
    );
  }
  if (/\(401\b|Bad or missing bearer token/i.test(clean)) {
    return (
      "The copilot API key is missing or invalid. Add the key in Settings and "
      + "try again."
    );
  }
  if (/\(404\b|thread not found/i.test(clean)) {
    return (
      "This conversation no longer exists for the selected project. Start a new chat."
    );
  }
  if (/Failed to fetch|NetworkError|fetch failed/i.test(clean)) {
    return (
      "The backend is not reachable. Make sure the Puffin Copilot backend is "
      + "running on port 8765 and try again."
    );
  }
  // A bare 50x with no detail body is the proxy answering for a dead
  // backend (real provider failures carry a detail message).
  if (/failed \(50\d[^)]*\)\s*$/i.test(clean)) {
    return (
      "The backend is not responding. Make sure the Puffin Copilot backend is "
      + "running on port 8765 (copilot/scripts/dev.ps1) and try again."
    );
  }
  return clean || "The chat stream stopped unexpectedly.";
}

function finalizeAssistantTurn(
  turn: ChatTurn,
  status: "done" | "error",
  options: { message?: string; stopReason?: string } = {},
): ChatTurn {
  const blocks: ChatBlock[] = turn.blocks.map((b) => ({ ...b, streaming: false }));
  if (options.message) {
    blocks.push({ type: "text", text: options.message });
  }
  if (blocks.length === 0 && status === "done") {
    blocks.push({ type: "text", text: "Stopped." });
  }
  return {
    ...turn,
    blocks,
    status,
    stopReason: options.stopReason ?? turn.stopReason,
  };
}

function finalizeLastAssistantTurn(
  turns: ChatTurn[],
  status: "done" | "error",
  options: { message?: string; stopReason?: string } = {},
): ChatTurn[] {
  const idx = [...turns].reverse().findIndex((t) => t.role === "assistant");
  if (idx === -1) return turns;
  const actual = turns.length - 1 - idx;
  const out = turns.slice();
  out[actual] = finalizeAssistantTurn(out[actual], status, options);
  return out;
}


export const useChatStore = create<ChatStore>()((set, get) => ({
  threads: {},

  getThread(threadId) {
    return get().threads[threadId] ?? emptyThread();
  },

  isAnyStreaming() {
    return Object.values(get().threads).some((t) => t.isStreaming);
  },

  streamingThreadIds() {
    return Object.entries(get().threads)
      .filter(([, t]) => t.isStreaming)
      .map(([id]) => id);
  },

  _patchThread(threadId, patch) {
    set((state) => {
      const current = state.threads[threadId] ?? emptyThread();
      const next = typeof patch === "function" ? patch(current) : patch;
      return {
        threads: {
          ...state.threads,
          [threadId]: { ...current, ...next },
        },
      };
    });
  },

  setFromStored(threadId, msgs) {
    const turns = buildTurnsFromStored(msgs);
    set((state) => {
      const current = state.threads[threadId] ?? emptyThread();
      // If a stream is currently in flight we must NOT clobber its
      // in-progress turns; the server snapshot may be older than the
      // optimistic local state. The stream's `done` handler will persist
      // and another refetch will reconcile.
      if (current.isStreaming) return state;
      const hasLocalTail = current.turns.some((t) => t.id.startsWith("local_"));
      if (hasLocalTail && turns.length < current.turns.length) return state;
      return {
        threads: {
          ...state.threads,
          [threadId]: { ...current, turns },
        },
      };
    });
  },

  abort(threadId) {
    const t = get().threads[threadId];
    if (!t) return;
    if (!t.isStreaming && !t.abortCtrl) return;
    t.abortCtrl?.abort();
    set((state) => ({
      threads: {
        ...state.threads,
        [threadId]: {
          ...(state.threads[threadId] ?? emptyThread()),
          turns: finalizeLastAssistantTurn(
            state.threads[threadId]?.turns ?? [],
            "done",
          ),
          isStreaming: false,
          abortCtrl: null,
          startedAt: null,
        },
      },
    }));
  },

  async send(threadId, text, opts) {
    if (!threadId || !text.trim()) return;
    // Abort any prior stream on the same thread before starting a new one.
    get().abort(threadId);

    const truncateFromIdx = opts?.truncateFromIdx;
    if (truncateFromIdx != null) {
      // Rewind the server history BEFORE any optimistic UI so a failure
      // leaves the conversation exactly as it was.
      try {
        await api.truncateThread(threadId, truncateFromIdx);
      } catch (exc) {
        get()._patchThread(threadId, (current) => ({
          turns: [...current.turns, {
            id: `local_${Date.now()}_err`,
            role: "assistant" as const,
            createdAt: new Date().toISOString(),
            status: "error" as const,
            blocks: [{
              type: "text" as const,
              text: friendlyChatError((exc as Error).message),
            }],
          }],
        }));
        return;
      }
    }

    const ctrl = new AbortController();
    const userTurnId = `local_${Date.now()}_u`;
    const asstTurnId = `local_${Date.now()}_a`;
    const userTurn: ChatTurn = {
      id: userTurnId, role: "user",
      blocks: [{ type: "text", text }],
      createdAt: new Date().toISOString(),
      status: "done",
    };
    const asstTurn: ChatTurn = {
      id: asstTurnId, role: "assistant", blocks: [],
      createdAt: new Date().toISOString(),
      status: "streaming",
    };

    // Bump generation so we can detect being superseded.
    const generation = (get().threads[threadId]?.generation ?? 0) + 1;
    get()._patchThread(threadId, (current) => {
      // After a rewind, drop the local turns that were just truncated
      // server-side so the optimistic view matches the new history.
      let base = current.turns;
      if (truncateFromIdx != null) {
        const cut = base.findIndex(
          (t) => t.storedIdx != null && t.storedIdx >= truncateFromIdx,
        );
        if (cut !== -1) base = base.slice(0, cut);
      }
      return {
        turns: [...base, userTurn, asstTurn],
        isStreaming: true,
        abortCtrl: ctrl,
        generation,
        startedAt: Date.now(),
      };
    });

    // updateLast clones the asstTurn into the store so React picks up
    // the change. asstTurn itself is mutated locally as events arrive;
    // every store update produces a fresh array reference at the turn
    // index so component re-renders fire.
    const flush = (snapshot: ChatTurn) => {
      get()._patchThread(threadId, (current) => {
        const idx = current.turns.findIndex((t) => t.id === snapshot.id);
        if (idx === -1) return current;
        const out = current.turns.slice();
        out[idx] = { ...snapshot, blocks: snapshot.blocks.map((b) => ({ ...b })) };
        return { turns: out };
      });
    };

    let curText: ChatBlock | null = null;
    const toolBlocks = new Map<string, ChatBlock>();
    let cumIn = 0;
    let cumOut = 0;

    try {
      const resp = await api.chatStream(
        {
          thread_id: threadId,
          content: [{ type: "text", text }],
          ...(opts?.systemExtra ? { system_extra: opts.systemExtra } : {}),
        },
        { signal: ctrl.signal },
      );

      for await (const evt of iterateSse(resp) as AsyncGenerator<StreamEvent>) {
        // If a newer send superseded us, drop events from this stale stream.
        if (get().threads[threadId]?.generation !== generation) break;

        if (evt.event === "text") {
          if (!curText) {
            curText = { type: "text", text: "", streaming: true };
            asstTurn.blocks.push(curText);
          }
          curText.text = (curText.text ?? "") + evt.data.text;
          flush(asstTurn);
        } else if (evt.event === "tool_call_start") {
          if (curText) { curText.streaming = false; curText = null; }
          const block: ChatBlock = {
            type: "tool", toolId: evt.data.id, toolName: evt.data.name,
            toolStarted: true,
          };
          toolBlocks.set(evt.data.id, block);
          asstTurn.blocks.push(block);
          flush(asstTurn);
        } else if (evt.event === "tool_call") {
          const b = toolBlocks.get(evt.data.id);
          if (b) b.toolInput = evt.data.input;
          flush(asstTurn);
        } else if (evt.event === "tool_result") {
          const b = toolBlocks.get(evt.data.id);
          if (b) b.toolResult = evt.data.result;
          flush(asstTurn);
          // AI changed something (imported data, ran the pipeline, edited a
          // config, etc.), so refresh every panel instantly.
          revalidateAfterTool(evt.data.name, evt.data.result);
        } else if (evt.event === "usage") {
          cumIn = evt.data.cumulative_input;
          cumOut = evt.data.cumulative_output;
          get()._patchThread(threadId, {
            usage: { cumulative_input: cumIn, cumulative_output: cumOut },
          });
        } else if (evt.event === "assistant_message") {
          if (curText) { curText.streaming = false; curText = null; }
        } else if (evt.event === "done") {
          asstTurn.status = "done";
          asstTurn.stopReason = evt.data.stop_reason;
          if (curText) { curText.streaming = false; }
          flush(asstTurn);
        } else if (evt.event === "error") {
          asstTurn.status = "error";
          if (curText) { curText.streaming = false; curText = null; }
          asstTurn.blocks.push({
            type: "text", text: friendlyChatError(evt.data.message),
          });
          flush(asstTurn);
        }
      }
    } catch (exc) {
      if ((exc as Error).name === "AbortError") {
        const final = finalizeAssistantTurn(asstTurn, "done");
        asstTurn.blocks = final.blocks;
        asstTurn.status = final.status;
        flush(asstTurn);
      } else {
        asstTurn.status = "error";
        if (curText) { curText.streaming = false; curText = null; }
        asstTurn.blocks.push({
          type: "text",
          text: friendlyChatError((exc as Error).message),
        });
        flush(asstTurn);
      }
    } finally {
      // Only clear isStreaming if WE are still the active generation;
      // otherwise a newer send already took over.
      if (get().threads[threadId]?.generation === generation) {
        if (asstTurn.status === "streaming") {
          const final = finalizeAssistantTurn(asstTurn, "done");
          asstTurn.blocks = final.blocks;
          asstTurn.status = final.status;
          asstTurn.stopReason = final.stopReason;
          flush(asstTurn);
        }
        get()._patchThread(threadId, {
          isStreaming: false, abortCtrl: null, startedAt: null,
        });
      }
    }
  },
}));
