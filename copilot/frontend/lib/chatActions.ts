"use client";
import * as React from "react";

/**
 * Context that lets nested artifact cards (e.g. AskUserQuestionCard) send
 * a fresh user message into the current chat thread without prop-drilling.
 */
export interface ChatActions {
  send: (text: string) => void | Promise<void>;
  isStreaming: boolean;
}

const Ctx = React.createContext<ChatActions | null>(null);

export const ChatActionsProvider = Ctx.Provider;

export function useChatActions(): ChatActions {
  const v = React.useContext(Ctx);
  return v ?? { send: () => undefined, isStreaming: false };
}
