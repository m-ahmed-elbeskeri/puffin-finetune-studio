import "@testing-library/jest-dom/vitest";

// jsdom doesn't ship ResizeObserver — recharts' ResponsiveContainer needs it.
class ResizeObserverPolyfill {
  observe(): void { /* noop */ }
  unobserve(): void { /* noop */ }
  disconnect(): void { /* noop */ }
}
(globalThis as { ResizeObserver?: typeof ResizeObserverPolyfill }).ResizeObserver
  ??= ResizeObserverPolyfill;

