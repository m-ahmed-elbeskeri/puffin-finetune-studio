"use client";
import * as React from "react";
import { Sun, Moon } from "@/components/ui/icons";

/**
 * Flips the Blueprint palette between light and dark by toggling `.dark` on
 * <html> (see app/globals.css) and persisting the choice to localStorage.
 * The initial class is set by the pre-paint script in app/layout.tsx, so this
 * button only ever reflects and mutates an already-correct state — no flash.
 */
export function ThemeToggle() {
  const [dark, setDark] = React.useState(false);

  React.useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const el = document.documentElement;
    const next = !el.classList.contains("dark");
    el.classList.toggle("dark", next);
    try {
      localStorage.setItem("puffin-theme", next ? "dark" : "light");
    } catch {
      /* storage blocked (private mode) — the toggle still works this session */
    }
    setDark(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs
                 text-white/55 hover:bg-white/5 hover:text-white transition-colors"
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {dark ? <Sun size={14} /> : <Moon size={14} />}
      {dark ? "Light mode" : "Dark mode"}
    </button>
  );
}
