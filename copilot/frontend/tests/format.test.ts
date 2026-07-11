import { describe, expect, it } from "vitest";
import { fmtDuration, fmtParams, fmtRelative, metricHelp } from "@/lib/format";

describe("fmtDuration", () => {
  it("returns dash for null", () => {
    expect(fmtDuration(null)).toBe("-");
  });
  it("formats seconds", () => {
    expect(fmtDuration(45)).toBe("45.0s");
  });
  it("formats minutes", () => {
    expect(fmtDuration(125)).toBe("2m 5s");
  });
  it("formats hours", () => {
    expect(fmtDuration(3725)).toBe("1h 2m");
  });
});

describe("fmtParams", () => {
  it("formats millions", () => {
    expect(fmtParams(135_000_000)).toBe("135.0M");
  });
  it("formats billions", () => {
    expect(fmtParams(7_500_000_000)).toBe("7.50B");
  });
  it("formats small numbers as K", () => {
    expect(fmtParams(540_672)).toBe("541K");
  });
});

describe("fmtRelative", () => {
  it("returns dash for empty", () => {
    expect(fmtRelative("")).toBe("-");
  });
  it("returns Ns ago for recent", () => {
    const recent = new Date(Date.now() - 5_000).toISOString();
    expect(fmtRelative(recent)).toMatch(/\d+s ago/);
  });
});

describe("metricHelp", () => {
  it("knows about loss", () => {
    expect(metricHelp("loss")).toContain("cross-entropy");
  });
  it("strips eval_ prefix", () => {
    expect(metricHelp("eval_grad_norm")).toContain("L2 norm");
  });
  it("returns empty string for unknown keys", () => {
    expect(metricHelp("nonsense_xyz")).toBe("");
  });
});
