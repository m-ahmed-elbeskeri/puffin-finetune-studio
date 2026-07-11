"use client";
import * as React from "react";

/**
 * Recharts takes plain colour strings, not Tailwind classes, so its strokes
 * and fills can't ride the CSS-variable theme the rest of the app uses. This
 * reads the resolved Blueprint tokens off <html> and re-reads them whenever the
 * `.dark` class flips, so charts stay on-palette and update live on toggle.
 */
export interface ChartColors {
  grid: string;
  axis: string;
  tick: string;
  accent: string;
  accentSoft: string;
  coral: string;
  ok: string;
  teal: string;
  /** A non-semantic categorical hue, distinct from accent/teal/coral, for a
   *  second data series that must not be confused with them (e.g. latency). */
  violet: string;
  neutral: string;
  tooltipBg: string;
  tooltipFg: string;
}

// Light-mode Riso values, used for SSR and the first paint before the effect runs.
const FALLBACK: ChartColors = {
  grid: "rgb(199 191 169 / 0.5)",
  axis: "rgb(163 154 131)",
  tick: "rgb(122 115 100)",
  accent: "rgb(43 52 214)",
  accentSoft: "rgb(43 52 214 / 0.18)",
  coral: "rgb(255 90 84)",
  ok: "rgb(47 125 82)",
  teal: "rgb(46 111 138)",
  violet: "rgb(124 92 214)",
  neutral: "rgb(199 191 169)",
  tooltipBg: "#1c1a16",
  tooltipFg: "#f1ede2",
};

function read(): ChartColors {
  if (typeof window === "undefined") return FALLBACK;
  const cs = getComputedStyle(document.documentElement);
  const c = (n: string) => {
    const v = cs.getPropertyValue(n).trim();
    return v ? `rgb(${v})` : "";
  };
  const ca = (n: string, a: number) => {
    const v = cs.getPropertyValue(n).trim();
    return v ? `rgb(${v} / ${a})` : "";
  };
  return {
    grid: ca("--ink-400", 0.28) || FALLBACK.grid,
    axis: c("--ink-400") || FALLBACK.axis,
    tick: c("--ink-500") || FALLBACK.tick,
    accent: c("--acc-500") || FALLBACK.accent,
    accentSoft: ca("--acc-500", 0.18) || FALLBACK.accentSoft,
    coral: c("--coral") || FALLBACK.coral,
    ok: c("--ok-500") || FALLBACK.ok,
    teal: c("--teal") || FALLBACK.teal,
    violet: FALLBACK.violet,
    neutral: c("--ink-300") || FALLBACK.neutral,
    tooltipBg: c("--ink") || FALLBACK.tooltipBg,
    tooltipFg: c("--ink-50") || FALLBACK.tooltipFg,
  };
}

export function useChartColors(): ChartColors {
  const [colors, setColors] = React.useState<ChartColors>(FALLBACK);
  React.useEffect(() => {
    setColors(read());
    const obs = new MutationObserver(() => setColors(read()));
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => obs.disconnect();
  }, []);
  return colors;
}
