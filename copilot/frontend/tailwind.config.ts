import type { Config } from "tailwindcss";

/**
 * Blueprint theme, light + dark.
 *
 * Every colour token resolves to a CSS variable (an "R G B" triplet) so the
 * whole palette can flip between light and dark by swapping the variables on
 * `<html class="dark">` — see app/globals.css. The `<alpha-value>` shim keeps
 * Tailwind's `/opacity` modifiers working (e.g. `bg-card/70`, `bg-accent/20`).
 *
 * The neutral `ink` scale INVERTS between modes: ink-50 is the page ground
 * (lightest in light mode, darkest in dark mode) and `ink` DEFAULT is the
 * primary text (darkest, then lightest). Anything that must stay light on a
 * permanently-dark surface (the sidebar, code panes) uses literal `white`/
 * `slate` or fixed hexes, never the invertible `ink` scale.
 */
const v = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Neutral system (inverts light/dark).
        ink: {
          DEFAULT: v("--ink"),
          900: v("--ink-900"),
          800: v("--ink-800"),
          700: v("--ink-700"),
          600: v("--ink-600"),
          500: v("--ink-500"),
          400: v("--ink-400"),
          300: v("--ink-300"),
          200: v("--ink-200"),
          100: v("--ink-100"),
          50: v("--ink-50"),
        },
        // Card / raised surface (replaces the old literal `bg-white`).
        card: { DEFAULT: v("--card"), muted: v("--card-muted") },
        // Accent = drafting orange-red. `amber` is an alias of the same scale
        // so the app's existing amber-* classes all become the accent.
        accent: {
          DEFAULT: v("--acc-500"),
          400: v("--acc-400"),
          600: v("--acc-600"),
          900: v("--acc-900"),
        },
        amber: {
          DEFAULT: v("--acc-500"),
          50: v("--acc-50"), 100: v("--acc-100"), 200: v("--acc-200"),
          300: v("--acc-300"), 400: v("--acc-400"), 500: v("--acc-500"),
          600: v("--acc-600"), 700: v("--acc-700"), 800: v("--acc-800"),
          900: v("--acc-900"),
        },
        // Semantic OK (emerald alias).
        emerald: {
          DEFAULT: v("--ok-500"),
          50: v("--ok-50"), 200: v("--ok-200"), 300: v("--ok-300"),
          400: v("--ok-400"), 500: v("--ok-500"), 600: v("--ok-600"),
          700: v("--ok-700"), 800: v("--ok-800"),
        },
        // Semantic FAIL (red alias).
        red: {
          DEFAULT: v("--fail-600"),
          50: v("--fail-50"), 200: v("--fail-200"), 300: v("--fail-300"),
          400: v("--fail-400"), 500: v("--fail-500"), 600: v("--fail-600"),
          700: v("--fail-700"), 800: v("--fail-800"), 900: v("--fail-900"),
        },
        teal: { DEFAULT: v("--teal") },
        ok: { DEFAULT: v("--ok-500") },
        fail: { DEFAULT: v("--fail-600") },
        warn: { DEFAULT: v("--warn") },
        // Riso second ink — exposed on its own for the two-ink motifs.
        coral: { DEFAULT: v("--coral") },
        sidebar: { DEFAULT: v("--sidebar"), muted: v("--sidebar-muted") },
      },
      fontFamily: {
        // next/font registers obfuscated family names and exposes them via
        // CSS vars — reference the vars or the loaded fonts never apply.
        sans: [
          "var(--font-sans)", "Inter", "ui-sans-serif", "system-ui",
          "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial",
          "sans-serif",
        ],
        mono: [
          "var(--font-mono)", "JetBrains Mono", "ui-monospace", "SF Mono",
          "Menlo", "Consolas", "monospace",
        ],
        // Riso display face: condensed, set in caps for headings + tab labels.
        display: [
          "var(--font-display)", "Oswald", "Archivo Narrow", "Arial Narrow",
          "Segoe UI Semibold", "system-ui", "sans-serif",
        ],
      },
      // Blueprint reads as a drafting board: hard, squared corners. Every box
      // radius collapses to 0; `full` is kept only for genuine circles (status
      // dots, step numbers, avatars).
      borderRadius: {
        none: "0px", sm: "0px", DEFAULT: "0px", md: "0px", lg: "0px",
        xl: "0px", "2xl": "0px", "3xl": "0px", full: "9999px",
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow) / 0.05), 0 4px 14px -6px rgb(var(--shadow) / 0.14)",
        glow: "0 6px 22px -10px rgb(var(--acc-500) / 0.5)",
        // Hard offset "print" shadows for the Riso motifs.
        riso: "4px 4px 0 rgb(var(--acc-500))",
        "riso-coral": "4px 4px 0 rgb(var(--coral))",
        "riso-lg": "7px 7px 0 rgb(var(--acc-500))",
      },
      backgroundImage: {
        // Faint schematic dot-grid for page grounds.
        grid: "radial-gradient(rgb(var(--grid) / 0.7) 1px, transparent 1px)",
      },
      keyframes: {
        pulseDot: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        fadeInUp: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        pulseDot: "pulseDot 1.4s ease-in-out infinite",
        fadeInUp: "fadeInUp 0.18s ease-out both",
        fadeIn: "fadeIn 0.15s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
