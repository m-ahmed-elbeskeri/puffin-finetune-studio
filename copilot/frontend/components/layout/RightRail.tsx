"use client";
/**
 * Docks the AI side panel on the right of every page EXCEPT chat (the chat
 * page is already the assistant, so a second AI panel there is redundant).
 * The panel itself is collapsible: a thin "Ask AI" rail that expands to the
 * full conversation. Mounted persistently so Ctrl+K and queued prompts work.
 */
import * as React from "react";
import { AIDrawer } from "@/components/ai/AIDrawer";

// The AI lives here on every page (the dedicated chat page was removed).
export function RightRail() {
  return <AIDrawer />;
}
