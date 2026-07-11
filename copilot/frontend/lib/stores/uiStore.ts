"use client";
import { create } from "zustand";

/**
 * Cross-page UI state: currently the AI side panel.
 *
 * Any component can `openDrawer("prompt")` and the drawer sends it into
 * the side-panel conversation as soon as it's ready (thread ensured).
 */
interface UiStore {
  drawerOpen: boolean;
  pendingPrompt: string | null;
  openDrawer: (prompt?: string) => void;
  closeDrawer: () => void;
  toggleDrawer: () => void;
  consumePendingPrompt: () => string | null;
}

export const useUiStore = create<UiStore>()((set, get) => ({
  drawerOpen: false,
  pendingPrompt: null,

  openDrawer(prompt) {
    set({ drawerOpen: true, ...(prompt ? { pendingPrompt: prompt } : {}) });
  },

  closeDrawer() {
    set({ drawerOpen: false });
  },

  toggleDrawer() {
    set((s) => ({ drawerOpen: !s.drawerOpen }));
  },

  consumePendingPrompt() {
    const p = get().pendingPrompt;
    if (p) set({ pendingPrompt: null });
    return p;
  },
}));
