/**
 * Shared TypeScript types: mirror the Pydantic shapes the backend tools
 * return. Kept in one file so the artifact router stays type-safe.
 */

// ============================================================================
// Project / hardware
// ============================================================================
export type StepStatus = "done" | "current" | "pending" | "fail";

export interface PipelineStep {
  key: "data" | "train" | "evaluate" | "deploy" | "monitor";
  label: string;
  status: StepStatus;
  sub: string;
}

export interface GpuInfo {
  available: boolean;
  name?: string;
  vram_total_gb?: number;
  vram_used_gb?: number;
  driver?: string;
}

export interface Hardware {
  platform: string;
  python: string;
  cpu_count: number;
  ram_gb: number;
  disk_free_gb: number;
  gpu: GpuInfo;
}

export interface ProjectStatus {
  kind: "project_status";
  repo_root: string;
  steps: PipelineStep[];
  next_action: string;
  registry_models: string[];
  hardware: Hardware;
  demo_data?: boolean;
}

// ============================================================================
// Training
// ============================================================================
export interface TrainingRun {
  adapter_dir: string;
  status: "completed" | "running" | "starting" | "stalled" | "failed" | "unknown";
  method: string;
  run_name: string;
  smoke_test: boolean;
  base_model: string;
  peft_method: string;
  start_ts: string;
  end_ts: string | null;
  duration_s: number | null;
  elapsed_s?: number | null;
  stage?: string;
  total_steps: number | null;
  current_step: number | null;
  current_epoch: number | null;
  total_epochs: number | null;
  current_loss: number | null;
  current_lr: number | null;
  final_loss: number | null;
  best_eval_loss: number | null;
  trainable_params: number | null;
  total_params: number | null;
  peak_vram_gb: number | null;
  pid: number | null;
  error: string | null;
  metrics?: TrainingMetricRow[];
}

export interface TrainingMetricRow {
  ts?: string;
  step: number;
  loss?: number;
  eval_loss?: number;
  learning_rate?: number;
  grad_norm?: number;
  epoch?: number;
  [k: string]: number | string | undefined;
}

export interface LiveTrainingPayload {
  kind: "live_training";
  active: boolean;
  run?: TrainingRun;
  message?: string;
}

export interface RunHistoryPayload {
  kind: "run_history";
  runs: TrainingRun[];
}

export interface RunDetailPayload {
  kind: "run_detail";
  run: TrainingRun;
}

// ============================================================================
// Data
// ============================================================================
export interface DatasetAuditPayload {
  kind: "dataset_audit";
  path: string;
  total_records: number;
  sampled?: number;
  schema?: "messages" | "prompt_completion" | "unknown";
  char_length?: {
    p50: number; p90: number; p99: number; max: number; mean: number;
  };
  sources?: Record<string, number>;
  licenses?: Record<string, number>;
  pii?: { email: number; phone: number; ssn: number };
  warnings: string[];
}

export interface DatasetPreviewPayload {
  kind: "dataset_preview";
  path: string;
  records: Record<string, unknown>[];
}

export interface DataPipelineResultPayload {
  kind: "data_pipeline_result";
  all_ok: boolean;
  stages: Array<{
    stage: string;
    exit_code: number;
    ok: boolean;
    stdout_tail: string;
  }>;
}

// ============================================================================
// Evaluation / gate
// ============================================================================
export interface EvalResultPayload {
  kind: "eval_result";
  all_ok: boolean;
  modules: Array<{
    module: string;
    exit_code: number;
    ok: boolean;
    stdout_tail: string;
  }>;
  metrics_summary: Record<string, number | null | undefined>;
}

export interface GateResultPayload {
  kind: "gate_result";
  passed: boolean;
  failures: string[];
  passes: string[];
  criteria: string[];
  exit_code: number;
  stdout_tail: string;
}

export interface EvalMetricsPayload {
  kind: "eval_metrics";
  present: boolean;
  metrics?: Record<string, unknown>;
}

// ============================================================================
// Deploy / registry
// ============================================================================
export interface DeployPushResultPayload {
  kind: "deploy_push_result";
  uri: string;
  alias_set: boolean;
  alias: string;
  name: string;
  warning?: string;
}

export interface DeployPromoteResultPayload {
  kind: "deploy_promote_result";
  name: string;
  version: string;
  alias: string;
  message: string;
}

export interface K8sManifestPayload {
  kind: "k8s_manifest";
  yaml: string;
  lines: number;
  bytes: number;
  args: Record<string, unknown>;
}

export interface RegistryPayload {
  kind: "registry";
  models: Array<{
    name: string;
    versions: Array<{
      version: string;
      registered_at: string;
      metrics: Record<string, unknown>;
      tags: Record<string, unknown>;
    }>;
    aliases: Record<string, string>;
  }>;
}

// ============================================================================
// Serving / monitor
// ============================================================================
export interface ServerHealthPayload {
  kind: "server_health";
  up: boolean;
  url: string;
  backend?: string;
  model_id?: string;
  adapter_loaded?: boolean;
  error?: string;
}

export interface ServeChatResultPayload {
  kind: "serve_chat_result";
  text: string;
  latency_ms: number;
  usage: Record<string, number>;
  metadata: Record<string, unknown>;
  request_id: string;
  model: string;
}

export interface RequestLogPayload {
  kind: "request_log";
  present: boolean;
  total: number;
  recent?: Record<string, unknown>[];
  summary?: {
    avg_latency_ms: number;
    total_output_chars: number;
    by_model_version: Record<string, number>;
  };
}

export interface QualityReportPayload {
  kind: "quality_report";
  present: boolean;
  report?: Record<string, unknown>;
  error?: string;
}

export interface DriftReportPayload {
  kind: "drift_report";
  present: boolean;
  report?: Record<string, unknown>;
  error?: string;
}

// ============================================================================
// Configs
// ============================================================================
export interface ConfigListPayload {
  kind: "config_list";
  files: Array<{ path: string; bytes: number }>;
}

export interface ConfigReadPayload {
  kind: "config_read";
  path: string;
  text: string;
  parsed: Record<string, unknown>;
  bytes: number;
}

export interface ConfigEditResultPayload {
  kind: "config_edit_result";
  path: string;
  backup: string;
  old_bytes: number;
  new_bytes: number;
  old_text: string;
  new_text: string;
}

export interface TrainStartedPayload {
  kind: "train_started";
  method: "sft" | "dpo";
  smoke: boolean;
  pid: number;
  adapter_dir: string;
  log_path: string;
  command: string;
  message: string;
}

export interface TrainCancelResultPayload {
  kind: "train_cancel_result";
  pid: number;
  killed: boolean;
  message: string;
}

export interface ErrorPayload {
  kind: "error";
  tool?: string;
  message: string;
}

export interface CodexCommandResultPayload {
  kind: "codex_command_result";
  command: string;
  status: string;
  exit_code: number | null;
  ok: boolean;
  output: string;
}

// ============================================================================
// Interactive: ask_user_question card
// ============================================================================
export interface AskUserQuestionPayload {
  kind: "ask_user_question";
  question: string;
  header: string;
  options: Array<{ label: string; description?: string }>;
  multi_select: boolean;
  awaiting_user_input: true;
}

// ============================================================================
// Unified artifact union
// ============================================================================
export type Artifact =
  | ProjectStatus
  | LiveTrainingPayload
  | RunHistoryPayload
  | RunDetailPayload
  | DatasetAuditPayload
  | DatasetPreviewPayload
  | DataPipelineResultPayload
  | EvalResultPayload
  | GateResultPayload
  | EvalMetricsPayload
  | DeployPushResultPayload
  | DeployPromoteResultPayload
  | K8sManifestPayload
  | RegistryPayload
  | ServerHealthPayload
  | ServeChatResultPayload
  | RequestLogPayload
  | QualityReportPayload
  | DriftReportPayload
  | ConfigListPayload
  | ConfigReadPayload
  | ConfigEditResultPayload
  | TrainStartedPayload
  | TrainCancelResultPayload
  | AskUserQuestionPayload
  | CodexCommandResultPayload
  | ErrorPayload;

// ============================================================================
// Threads / messages
// ============================================================================
export interface ThreadSummary {
  id: string;
  title: string;
  model: string;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export type AnthropicContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean };

export interface StoredMessage {
  id: string;
  thread_id: string;
  idx: number;
  role: "user" | "assistant";
  content: AnthropicContentBlock[];
  created_at: string;
}

// ============================================================================
// Streaming events (mirrors copilot.backend.loop)
// ============================================================================
export type StreamEvent =
  | { event: "text"; data: { text: string } }
  | { event: "tool_call_start"; data: { id: string; name: string } }
  | { event: "tool_call"; data: { id: string; name: string; input: Record<string, unknown> } }
  | { event: "tool_result"; data: { id: string; name: string; result: Artifact } }
  | { event: "usage"; data: { input_tokens: number; output_tokens: number;
                              cumulative_input: number; cumulative_output: number } }
  | { event: "assistant_message"; data: { content: AnthropicContentBlock[] } }
  | { event: "done"; data: { stop_reason: string } }
  | { event: "error"; data: { message: string } };
