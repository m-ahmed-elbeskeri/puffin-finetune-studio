/**
 * Smoke render tests for the artifact router + key cards.
 *
 * We're not testing visual fidelity (that's the screenshot loop) — we're
 * proving every kind a tool can return actually has a card that mounts.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArtifactRouter } from "@/components/artifacts/ArtifactRouter";
import type {
  Artifact, GateResultPayload, LiveTrainingPayload, ProjectStatus, RunHistoryPayload,
} from "@/lib/types";

const projectStatus: ProjectStatus = {
  kind: "project_status",
  repo_root: "/repo/puffin",
  next_action: "Run a smoke train.",
  registry_models: [],
  steps: [
    { key: "data", label: "Data", status: "done", sub: "splits ready" },
    { key: "train", label: "Train", status: "current", sub: "ready" },
    { key: "evaluate", label: "Evaluate", status: "pending", sub: "needs adapter" },
    { key: "deploy", label: "Deploy", status: "pending", sub: "needs gate" },
    { key: "monitor", label: "Monitor", status: "pending", sub: "needs deploy" },
  ],
  hardware: {
    platform: "windows", python: "3.13.3", cpu_count: 8, ram_gb: 16,
    disk_free_gb: 100,
    gpu: { available: true, name: "RTX 3050 Ti", vram_total_gb: 4 },
  },
};

const livePayload: LiveTrainingPayload = {
  kind: "live_training", active: true,
  run: {
    adapter_dir: "artifacts/adapter",
    status: "running", method: "sft", run_name: "puffin-test",
    smoke_test: true, base_model: "test/SmolLM2", peft_method: "lora",
    start_ts: new Date().toISOString(), end_ts: null,
    duration_s: 10, total_steps: 24, current_step: 7,
    current_epoch: 0.5, total_epochs: 1.0,
    current_loss: 0.8, current_lr: 1.5e-4,
    final_loss: null, best_eval_loss: null,
    trainable_params: 1024, total_params: 1_000_000,
    peak_vram_gb: 0.5, pid: 1234, error: null,
    metrics: [
      { step: 1, loss: 1.1 }, { step: 2, loss: 0.95 }, { step: 3, loss: 0.85 },
    ],
  },
};

const gatePass: GateResultPayload = {
  kind: "gate_result", passed: true, failures: [],
  passes: ["task_score >= 0.7", "safety_failures_critical == 0"],
  criteria: [], exit_code: 0, stdout_tail: "",
};

const gateFail: GateResultPayload = {
  ...gatePass, passed: false,
  failures: ["task_score < 0.7"], passes: [],
};

const runHistory: RunHistoryPayload = {
  kind: "run_history",
  runs: [livePayload.run!],
};

describe("ArtifactRouter", () => {
  it("renders project_status with next action", () => {
    render(<ArtifactRouter artifact={projectStatus} />);
    expect(screen.getByText(/next action/i)).toBeInTheDocument();
    expect(screen.getByText("Run a smoke train.")).toBeInTheDocument();
  });

  it("renders a running live_training card with progress", () => {
    render(<ArtifactRouter artifact={livePayload} />);
    expect(screen.getByText(/puffin-test/i)).toBeInTheDocument();
    expect(screen.getByText(/Running/i)).toBeInTheDocument();
    // 7/24 should appear in the progress label.
    expect(screen.getByText(/Step 7 \/ 24/)).toBeInTheDocument();
  });

  it("renders gate PASS prominently", () => {
    render(<ArtifactRouter artifact={gatePass} />);
    expect(screen.getByText(/PASS/)).toBeInTheDocument();
  });

  it("renders gate FAIL with failure list", () => {
    render(<ArtifactRouter artifact={gateFail} />);
    expect(screen.getByText(/FAIL/)).toBeInTheDocument();
    expect(screen.getByText("task_score < 0.7")).toBeInTheDocument();
  });

  it("renders run history as a table with one row", () => {
    render(<ArtifactRouter artifact={runHistory} />);
    expect(screen.getByText(/Training runs/)).toBeInTheDocument();
    expect(screen.getByText("puffin-test")).toBeInTheDocument();
  });

  it("renders Codex command results with command output", () => {
    render(<ArtifactRouter artifact={{
      kind: "codex_command_result",
      command: "powershell -Command Get-Location",
      status: "completed",
      exit_code: 0,
      ok: true,
      output: "C:\\repo\\puffin",
    }} />);
    expect(screen.getByText(/Codex command/i)).toBeInTheDocument();
    expect(screen.getByText(/completed \/ exit 0/i)).toBeInTheDocument();
    expect(screen.getByText("C:\\repo\\puffin")).toBeInTheDocument();
  });

  it("falls back to GenericResultCard for unknown kinds", () => {
    const weird = { kind: "totally_new_kind", value: 42 } as unknown as Artifact;
    render(<ArtifactRouter artifact={weird} />);
    expect(screen.getByText(/Result/i)).toBeInTheDocument();
  });

  it("renders the error card", () => {
    render(<ArtifactRouter artifact={{ kind: "error", message: "boom" }} />);
    expect(screen.getByText(/Tool error|failed/i)).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});
