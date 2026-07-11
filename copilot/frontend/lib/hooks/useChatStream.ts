"use client";
import { useCallback } from "react";
import {
  useChatStore, type ChatBlock, type ChatTurn, type SendOptions,
} from "@/lib/stores/chatStore";
import type { StoredMessage } from "@/lib/types";

export type { ChatBlock, ChatTurn, SendOptions };

interface UsageState {
  cumulative_input: number;
  cumulative_output: number;
}

export interface UseChatStream {
  turns: ChatTurn[];
  isStreaming: boolean;
  usage: UsageState;
  startedAt: number | null;
  send: (text: string, opts?: SendOptions) => Promise<void>;
  abort: () => void;
  setFromStored: (msgs: StoredMessage[]) => void;
}

/**
 * Per-thread chat handle backed by the global chatStore.
 *
 * The store owns the SSE connection, the AbortController, and the
 * accumulated turns. This hook is just a thin selector + action binder
 * so components that already used the old useChatStream API don't have
 * to change. State survives unmount → the user can navigate to /runs
 * or /monitor while a chat is streaming and come back to it intact.
 */
export function useChatStream(threadId: string | null): UseChatStream {
  const thread = useChatStore((state) =>
    threadId ? state.threads[threadId] : undefined,
  );
  const sendAction = useChatStore((state) => state.send);
  const abortAction = useChatStore((state) => state.abort);
  const setFromStoredAction = useChatStore((state) => state.setFromStored);

  const send = useCallback(
    async (text: string, opts?: SendOptions) => {
      if (!threadId) return;
      await sendAction(threadId, text, opts);
    },
    [threadId, sendAction],
  );

  const abort = useCallback(() => {
    if (!threadId) return;
    abortAction(threadId);
  }, [threadId, abortAction]);

  const setFromStored = useCallback(
    (msgs: StoredMessage[]) => {
      if (!threadId) return;
      setFromStoredAction(threadId, msgs);
    },
    [threadId, setFromStoredAction],
  );

  return {
    turns: thread?.turns ?? [],
    isStreaming: thread?.isStreaming ?? false,
    usage: thread?.usage ?? { cumulative_input: 0, cumulative_output: 0 },
    startedAt: thread?.startedAt ?? null,
    send,
    abort,
    setFromStored,
  };
}
