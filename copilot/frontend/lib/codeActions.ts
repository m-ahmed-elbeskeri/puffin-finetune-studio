"use client";
import * as React from "react";

/**
 * Optional per-surface actions on rendered code blocks.
 *
 * The AI side panel provides {label, languages, onAction} so python blocks
 * gain a "Save as pipeline script" button; the main chat provides nothing
 * and code blocks render as usual.
 */
export interface CodeActions {
  label: string;
  /** Languages the action applies to (lowercase). */
  languages: string[];
  onAction: (code: string) => void;
}

const Ctx = React.createContext<CodeActions | null>(null);

export const CodeActionsProvider = Ctx.Provider;

export function useCodeActions(): CodeActions | null {
  return React.useContext(Ctx);
}
