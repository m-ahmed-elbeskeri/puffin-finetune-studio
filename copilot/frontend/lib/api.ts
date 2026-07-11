/**
 * Backend API client: typed wrapper over fetch.
 *
 * In dev, next.config.js proxies /api/* → FastAPI, so the browser sees a
 * same-origin app. In prod, NEXT_PUBLIC_BACKEND can override the base URL.
 */
import type {
  ConfigListPayload, ConfigReadPayload, EvalMetricsPayload,
  LiveTrainingPayload, ProjectStatus, QualityReportPayload, RegistryPayload,
  RequestLogPayload, RunDetailPayload, RunHistoryPayload, ServeChatResultPayload,
  ServerHealthPayload,
  StoredMessage, ThreadSummary, DriftReportPayload, AnthropicContentBlock,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_BACKEND || "";
// Streaming goes same-origin through the Next rewrite proxy too (verified
// unbuffered). NEXT_PUBLIC_STREAM_BACKEND stays as an escape hatch for
// deployments where the proxy can't stream.
const STREAM_BASE = (
  process.env.NEXT_PUBLIC_STREAM_BACKEND
  || process.env.NEXT_PUBLIC_BACKEND
  || ""
);
const PROJECT_KEY = "puffin_copilot_project_id";

function authHeader(): HeadersInit {
  if (typeof window === "undefined") return {};
  const key = window.localStorage.getItem("puffin_copilot_api_key");
  return key ? { Authorization: `Bearer ${key}` } : {};
}

/** Current project id (kept in localStorage so it survives reload). */
export function getCurrentProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(PROJECT_KEY);
}

export function setCurrentProjectId(id: string | null): void {
  if (typeof window === "undefined") return;
  if (id) window.localStorage.setItem(PROJECT_KEY, id);
  else window.localStorage.removeItem(PROJECT_KEY);
}

/** Append `project_id=...` to a URL when a project is selected. */
function p(url: string): string {
  const pid = getCurrentProjectId();
  if (!pid) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}project_id=${encodeURIComponent(pid)}`;
}

export interface ProjectRow {
  id: string; name: string; path: string; created_at: string;
}

// --- Training Studio shapes (GET /api/train/studio) ---------------------
export type StudioMethod = "sft" | "dpo" | "kto" | "reward" | "grpo" | "rloo";

export interface StudioRecipe {
  id: string; label: string; category: string; method: StudioMethod;
  icon: string; tagline: string; description: string;
  overrides: Record<string, unknown>;
  force_smoke?: boolean; needs_gpu: boolean; est_time: string;
  custom?: boolean;
}

export interface CloudField {
  key: string; label: string;
  placeholder?: string; default?: string; help?: string;
}
export interface CloudTarget {
  id: string; label: string; kind: "local" | "cloud"; env_group: string;
  blurb: string; needs?: string; submit?: string; docs?: string;
  fields?: CloudField[];
}

export interface StudioKnob {
  path: string; label: string; group: string; essential: boolean;
  type: "text" | "int" | "float" | "bool" | "select";
  options?: string[]; min?: number; max?: number; step?: number;
  methods: StudioMethod[]; help: string;
  /** Short "ideal value" guidance shown under the control. */
  recommended?: string;
  /** For selects: each option mapped to a one-line explanation. */
  option_help?: Record<string, string>;
}

export interface StudioCatalog {
  recipes: StudioRecipe[];
  recipe_categories: string[];
  cloud_targets: CloudTarget[];
  knobs: StudioKnob[];
  group_order: string[];
  current: Record<StudioMethod, Record<string, unknown>>;
  base_config: Record<StudioMethod, string>;
  studio_config: Record<StudioMethod, string>;
  gpu: {
    available: boolean; name?: string;
    vram_total_gb?: number; vram_used_gb?: number;
  };
  dangerous_enabled: boolean;
}

export interface TrainLaunchResult {
  launch: {
    kind: string; message?: string; pid?: number;
    adapter_dir?: string; log_path?: string;
  };
  config_path: string;
  yaml: string;
}

async function jsonFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
      ...(init?.headers ?? {}),
    },
  });
  if (!r.ok) {
    throw await responseError(r, "Request");
  }
  return (await r.json()) as T;
}

async function responseError(r: Response, label: string): Promise<Error> {
  const text = await r.text().catch(() => "");
  let detail = text.trim();
  if (detail) {
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown };
      const value = parsed.detail ?? parsed;
      detail = typeof value === "string" ? value : JSON.stringify(value);
    } catch {
      // Keep the raw response body.
    }
  }
  return new Error(
    `${label} failed (${r.status} ${r.statusText || "HTTP error"})${
      detail ? `: ${detail}` : ""
    }`,
  );
}

export interface TransformScript {
  name: string;
  size_bytes: number;
  mtime: string;
  description: string;
}

export interface TransformRunResult {
  kind: "transform_run_result";
  script: string;
  input: string;
  output: string;
  exit_code: number;
  ok: boolean;
  timed_out: boolean;
  stdout_tail: string;
  output_exists: boolean;
  output_lines: number;
  duration_s: number;
}

export interface TransformChainStep {
  script: string;
  input_lines: number;
  exit_code: number;
  ok: boolean;
  timed_out: boolean;
  stdout_tail: string;
  output_exists: boolean;
  output_lines: number;
  duration_s: number;
}

export interface TransformChainResult {
  kind: "transform_chain_result";
  steps: TransformChainStep[];
  all_ok: boolean;
  input: string;
  output: string;
  output_exists: boolean;
  output_lines: number;
}

export interface DataRecord {
  index: number;
  valid: boolean;
  data?: unknown;
  raw?: string;
  error?: string;
}
export interface RecordPage {
  kind: "record_page";
  path: string; total: number; offset: number; limit: number;
  records: DataRecord[];
}

export interface TokenReport {
  kind: "token_report";
  path: string; tokenizer: string; exact: boolean;
  max_seq_length: number; total_records: number; sampled: number;
  tokens: { p50: number; p90: number; p99: number; max: number; mean: number };
  over_max_seq: number; over_max_seq_pct: number;
  est_tokens_per_epoch: number; est_cost_per_epoch_usd: number;
  warnings: string[];
}

export interface TemplateSegment { role: string; content: string; trained: boolean }
export interface TemplatePreview {
  kind: "template_preview";
  path: string; index: number; tokenizer: string | null;
  rendered: string | null; token_count: number | null;
  segments: TemplateSegment[]; trained_fraction: number; note: string;
}

export interface DataQualityReport {
  kind: "data_quality_report";
  path: string; schema: string; total_records: number; sampled: number;
  warnings: string[];
  empty_assistant?: number; short_assistant?: number; no_assistant?: number;
  bad_alternation?: number; refusals?: number; refusal_rate?: number;
  single_turn?: number; multi_turn?: number; with_system?: number;
  distinct_system_prompts?: number;
  identical_pairs?: number; empty_side?: number; chosen_longer?: number;
  chosen_longer_frac?: number; mean_chosen_chars?: number; mean_rejected_chars?: number;
}

export interface LeakagePair {
  a: string; b: string; exact_overlap: number; prompt_overlap: number;
}
export interface DataLeakageReport {
  kind: "data_leakage_report";
  present: boolean; clean?: boolean; message?: string;
  pairs: LeakagePair[];
  examples?: Array<{ kind: string; text: string }>;
  capped?: number; warnings: string[];
}

export interface DatasetFingerprint {
  kind: "dataset_fingerprint";
  dataset_hash: string; built: boolean;
  splits: Record<string, { records: number; sha256: string; bytes: number }>;
  lineage: {
    sources: string[]; transforms: string[];
    split: Record<string, number>;
  };
}

export interface EnvPackage {
  import: string; pip: string; installed: boolean; version: string | null;
}
export interface EnvGroup {
  id: string; label: string; purpose: string;
  packages: EnvPackage[];
  installed_count: number; total: number; ready: boolean;
  install_command: string;
}
export interface EnvironmentReport {
  kind: "environment";
  python: string; executable: string;
  groups: EnvGroup[];
}

// --- Pre-launch readiness + resource estimate ---------------------------
export interface TrainingLogPayload {
  kind: "training_log";
  adapter_dir: string;
  present: boolean;
  log_path?: string | null;
  total_lines?: number;
  lines: string[];
  message?: string;
}

export interface PreflightCheck {
  id: string; label: string;
  status: "ok" | "warn" | "fail";
  detail: string;
}
export interface TrainPreflight {
  kind: "train_preflight";
  ok: boolean;
  checks: PreflightCheck[];
}

export interface RunConfigPayload {
  kind: "run_config";
  adapter_dir: string;
  present: boolean;
  config_path?: string;
  yaml?: string;
  meta?: {
    launched_at?: string; method?: string; smoke_test?: boolean;
    config_source?: string; dataset_hash?: string | null;
    dataset_splits?: Record<string, { records: number; sha256: string; bytes: number }>;
    command?: string;
  };
  message?: string;
}

export interface TrainEstimate {
  kind: "train_estimate";
  known: boolean;
  base_model?: string;
  params_b?: number;
  quantization?: string;
  lora?: boolean;
  batch?: number;
  seq_len?: number;
  vram_gb?: number;
  gpu_vram_gb?: number | null;
  fits?: boolean | null;
  method_note?: string;
  time_note?: string;
  note?: string;
  warnings?: string[];
}

// --- Evaluation studio --------------------------------------------------
export interface EvalRunResult {
  kind: "eval_result";
  modules: Array<{ module: string; exit_code: number; ok: boolean; stdout_tail: string }>;
  all_ok: boolean;
  metrics_summary: Record<string, number | null>;
}
export interface GateResult {
  kind: "gate_result";
  passed: boolean;
  failures: string[];
  passes?: string[];
  exit_code?: number;
  stdout_tail?: string;
}
export interface EvalConfig {
  kind: "eval_config";
  gates: Record<string, number>;
  settings: {
    backend?: string; model_id?: string;
    adapter_path?: string; max_new_tokens?: number;
  };
}
export type ToolErrorResult = { kind: "error"; message: string };

export interface GateReportRead {
  kind: "gate_report";
  present: boolean;
  passed?: boolean;
  failures?: string[];
}

// --- Deploy studio ------------------------------------------------------
export interface DeployConfig {
  kind: "deploy_config"; name: string; default_alias: string;
}
export interface DeployPushResult {
  kind: "deploy_push_result";
  uri?: string; alias_set?: boolean; alias?: string; name?: string; warning?: string;
}
export interface DeployPromoteResult {
  kind: "deploy_promote_result";
  name?: string; version?: string; alias?: string; message?: string;
}

// --- Serving control ----------------------------------------------------
export interface ServingStatus {
  kind: "serving_status";
  running: boolean;
  pid?: number;
  port: number;
  backend?: string;
  url: string;
  config?: string;
  started_at?: string;
  log_path?: string;
  message?: string;
}
export interface ServingStopResult {
  kind: "serving_stop"; stopped: boolean; message: string;
}
export interface ServingLogPayload {
  kind: "serving_log"; present: boolean;
  log_path?: string; total_lines?: number; lines: string[]; message?: string;
}
export interface K8sManifest {
  kind: "k8s_manifest"; yaml: string; lines: number; bytes: number;
  args: Record<string, unknown>;
}
export interface DeployTarget {
  id: string; label: string; cli: string; cli_installed: boolean;
  cloud: boolean; dir?: string | null; dir_exists: boolean;
}
export interface DeployTargetsPayload {
  kind: "deploy_targets"; targets: DeployTarget[];
}
export interface DeployStatus {
  kind: "deploy_status"; running: boolean; pid?: number; target?: string;
  label?: string; cloud?: boolean; command?: string; started_at?: string;
  log_path?: string; message?: string;
}
export interface DeployLogPayload {
  kind: "deploy_log"; present: boolean; log_path?: string;
  total_lines?: number; lines: string[]; message?: string;
}

export interface ProjectBrief {
  kind: "project_brief";
  fields: Record<string, string>;
  labels: Record<string, string>;
  present: boolean;
}

export const api = {
  // --- Liveness ---------------------------------------------------------
  healthz: () => jsonFetch<Record<string, unknown>>("/healthz"),
  getBrief: () => jsonFetch<ProjectBrief>(p("/api/brief")),
  saveBrief: (fields: Record<string, string>) =>
    jsonFetch<ProjectBrief>(p("/api/brief"), {
      method: "PUT", body: JSON.stringify({ fields }),
    }),
  capabilities: () =>
    jsonFetch<{ dangerous_enabled: boolean }>("/api/capabilities"),

  // --- Environment doctor ----------------------------------------------
  environment: () => jsonFetch<EnvironmentReport>("/api/environment"),
  installEnvironment: async (
    group: string, init?: { signal?: AbortSignal },
  ): Promise<Response> => {
    const r = await fetch(`${BASE}${p("/api/environment/install")}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json", Accept: "text/event-stream",
        ...authHeader(),
      },
      body: JSON.stringify({ group }),
      signal: init?.signal,
    });
    if (!r.ok || !r.body) throw await responseError(r, "Install");
    return r;
  },

  // --- Record-level editing (view / add / edit / delete rows) ----------
  readRecords: (path: string, offset = 0, limit = 25) =>
    jsonFetch<RecordPage>(p(
      `/api/data/records?path=${encodeURIComponent(path)}&offset=${offset}&limit=${limit}`)),
  addRecord: (path: string, record: unknown) =>
    jsonFetch<{ ok: boolean; total: number; index: number }>(
      p(`/api/data/records?path=${encodeURIComponent(path)}`),
      { method: "POST", body: JSON.stringify({ record }) }),
  updateRecord: (path: string, index: number, record: unknown) =>
    jsonFetch<{ ok: boolean; total: number; index: number }>(
      p(`/api/data/records?path=${encodeURIComponent(path)}&index=${index}`),
      { method: "PUT", body: JSON.stringify({ record }) }),
  deleteRecord: (path: string, index: number) =>
    jsonFetch<{ ok: boolean; total: number }>(
      p(`/api/data/records?path=${encodeURIComponent(path)}&index=${index}`),
      { method: "DELETE" }),

  // --- Data inspection (read-only) -------------------------------------
  inspectTokens: (path: string) =>
    jsonFetch<TokenReport>(p(`/api/data/inspect/tokens?path=${encodeURIComponent(path)}`)),
  inspectTemplate: (path: string, index = 0) =>
    jsonFetch<TemplatePreview>(
      p(`/api/data/inspect/template?path=${encodeURIComponent(path)}&index=${index}`)),
  inspectQuality: (path: string) =>
    jsonFetch<DataQualityReport>(p(`/api/data/inspect/quality?path=${encodeURIComponent(path)}`)),
  inspectLeakage: () =>
    jsonFetch<DataLeakageReport>(p("/api/data/inspect/leakage")),
  inspectFingerprint: () =>
    jsonFetch<DatasetFingerprint>(p("/api/data/inspect/fingerprint")),

  // --- Dashboard data (project_id auto-appended by p()) ----------------
  state: () => jsonFetch<{ status: ProjectStatus; training: LiveTrainingPayload }>(
    p("/api/state")),
  runs: (includeMetrics = false) =>
    jsonFetch<RunHistoryPayload>(
      p(`/api/runs${includeMetrics ? "?include_metrics=true" : ""}`)),
  run: (adapterDir: string) =>
    jsonFetch<RunDetailPayload>(p(`/api/runs/${encodeURIComponent(adapterDir)}`)),
  registry: () => jsonFetch<RegistryPayload>(p("/api/registry")),
  configs: () => jsonFetch<ConfigListPayload>(p("/api/configs")),
  config: (path: string) =>
    jsonFetch<ConfigReadPayload>(p(`/api/configs/${encodeURIComponent(path)}`)),
  servingHealth: (url = "http://127.0.0.1:8089") =>
    jsonFetch<ServerHealthPayload>(
      p(`/api/serving/health?url=${encodeURIComponent(url)}`)),
  servingStatus: () => jsonFetch<ServingStatus>(p("/api/serving/status")),
  servingStart: (body: { backend?: string; port?: number } = {}) =>
    jsonFetch<ServingStatus>(p("/api/serving/start"), {
      method: "POST", body: JSON.stringify(body),
    }),
  servingStop: () =>
    jsonFetch<ServingStopResult>(p("/api/serving/stop"), {
      method: "POST", body: JSON.stringify({}),
    }),
  /** One chat completion, proxied through the backend (avoids browser CORS to :8089).
   *  Pass `messages` for a multi-turn conversation, or `prompt`+`system` for one turn. */
  serveChat: (body: {
    prompt?: string; url?: string; system?: string;
    messages?: Array<{ role: string; content: string }>;
    temperature?: number; max_tokens?: number; require_json?: boolean;
  }) =>
    jsonFetch<ServeChatResultPayload | ToolErrorResult>(p("/api/serving/chat"), {
      method: "POST", body: JSON.stringify(body),
    }),
  servingLog: (tail = 400) =>
    jsonFetch<ServingLogPayload>(p(`/api/serving/log?tail=${tail}`)),
  deployK8s: (body: {
    environment?: string; replicas?: number; gpu?: boolean;
    namespace?: string; model_ref?: string; serving_image?: string;
  }) =>
    jsonFetch<K8sManifest | ToolErrorResult>(p("/api/deploy/k8s"), {
      method: "POST", body: JSON.stringify(body),
    }),
  deployTargets: () => jsonFetch<DeployTargetsPayload>(p("/api/deploy/targets")),
  deployStatus: () => jsonFetch<DeployStatus>(p("/api/deploy/status")),
  deployLog: (tail = 400) =>
    jsonFetch<DeployLogPayload>(p(`/api/deploy/log?tail=${tail}`)),
  deployRun: (target: string, settings: Record<string, unknown>) =>
    jsonFetch<DeployStatus | ToolErrorResult>(p("/api/deploy/run"), {
      method: "POST", body: JSON.stringify({ target, settings }),
    }),
  deployCancel: () =>
    jsonFetch<{ kind: string; cancelled: boolean; message: string }>(
      p("/api/deploy/cancel"), { method: "POST", body: JSON.stringify({}) }),
  monitorRequests: (n = 25) =>
    jsonFetch<RequestLogPayload>(p(`/api/monitor/requests?n=${n}`)),
  monitorQuality: () => jsonFetch<QualityReportPayload>(p("/api/monitor/quality")),
  monitorDrift: () => jsonFetch<DriftReportPayload>(p("/api/monitor/drift")),
  evalMetrics: () => jsonFetch<EvalMetricsPayload>(p("/api/eval/metrics")),
  evalConfig: () => jsonFetch<EvalConfig>(p("/api/eval/config")),
  updateEvalGates: (gates: Record<string, number>) =>
    jsonFetch<EvalConfig>(p("/api/eval/config"), {
      method: "PUT", body: JSON.stringify({ gates }),
    }),
  evalRun: (body: { modules?: string[]; backend?: string } = {}) =>
    jsonFetch<EvalRunResult | ToolErrorResult>(p("/api/eval/run"), {
      method: "POST", body: JSON.stringify(body),
    }),
  evalGate: () =>
    jsonFetch<GateResult | ToolErrorResult>(p("/api/eval/gate"), {
      method: "POST", body: JSON.stringify({}),
    }),
  evalGateReport: () => jsonFetch<GateReportRead>(p("/api/eval/gate")),

  // --- Deploy studio ---------------------------------------------------
  deployConfig: () => jsonFetch<DeployConfig>(p("/api/deploy/config")),
  deployPush: (body: { name?: string; alias?: string; adapter_dir?: string }) =>
    jsonFetch<DeployPushResult | ToolErrorResult>(p("/api/deploy/push"), {
      method: "POST", body: JSON.stringify(body),
    }),
  deployPromote: (body: { name: string; version: string; alias: string }) =>
    jsonFetch<DeployPromoteResult | ToolErrorResult>(p("/api/deploy/promote"), {
      method: "POST", body: JSON.stringify(body),
    }),

  // --- Projects --------------------------------------------------------
  listProjects: () =>
    jsonFetch<{ projects: ProjectRow[] }>("/api/projects"),
  createProject: (body: { name: string; path: string }) =>
    jsonFetch<{ project: ProjectRow }>("/api/projects", {
      method: "POST", body: JSON.stringify(body),
    }),
  scaffoldProject: (body: { name: string; path: string }) =>
    jsonFetch<{
      project: ProjectRow;
      scaffold: {
        target_path: string;
        files_copied: string[];
        dirs_created: string[];
        skipped: string[];
      };
    }>("/api/projects/scaffold", {
      method: "POST", body: JSON.stringify(body),
    }),
  deleteProject: (id: string) =>
    jsonFetch<{ deleted: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  pickFolder: (body: { title?: string; initial?: string } = {}) =>
    jsonFetch<{ path: string | null }>("/api/picker/folder", {
      method: "POST", body: JSON.stringify(body),
    }),

  // --- Data files (scoped to current project) --------------------------
  listDataFiles: () =>
    jsonFetch<{
      kind: "dataset_list";
      files: Array<{
        path: string; name: string;
        kind: "raw" | "interim" | "processed" | "eval";
        size_bytes: number; mtime: string; line_count: number;
        schema_hint: string;
      }>;
    }>(p("/api/data/files")),
  uploadDataFiles: async (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    const r = await fetch(`${BASE}${p("/api/data/upload")}`, {
      method: "POST", headers: authHeader(), body: form,
    });
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      throw new Error(`HTTP ${r.status}: ${text}`);
    }
    return (await r.json()) as {
      imported: Array<{
        path: string; size_bytes: number;
        valid_records: number; invalid_records: number;
      }>;
      skipped: Array<{ filename: string; reason: string }>;
    };
  },
  pasteDataFile: (body: { filename: string; content: string }) =>
    jsonFetch<{
      path: string; size_bytes: number;
      valid_records: number; invalid_records: number;
    }>(p("/api/data/paste"), {
      method: "POST", body: JSON.stringify(body),
    }),
  deleteDataFile: (path: string) => {
    const base = p("/api/data/files");
    const sep = base.includes("?") ? "&" : "?";
    return jsonFetch<{ deleted: boolean; path: string }>(
      `${base}${sep}path=${encodeURIComponent(path)}`,
      { method: "DELETE" },
    );
  },
  auditDataFile: (path: string) =>
    jsonFetch<import("./types").DatasetAuditPayload>(
      (() => {
        const base = p("/api/data/audit");
        const sep = base.includes("?") ? "&" : "?";
        return `${base}${sep}path=${encodeURIComponent(path)}`;
      })()),
  previewDataFile: (path: string, n = 5) =>
    jsonFetch<import("./types").DatasetPreviewPayload>(
      (() => {
        const base = p("/api/data/preview");
        const sep = base.includes("?") ? "&" : "?";
        return `${base}${sep}path=${encodeURIComponent(path)}&n=${n}`;
      })()),
  runDataPipeline: (opts?: { redact_pii?: boolean; dedupe?: boolean }) =>
    jsonFetch<import("./types").DataPipelineResultPayload
      | { kind: "error"; message: string }>(
      p("/api/data/pipeline"), {
        method: "POST", body: JSON.stringify(opts ?? {}),
      }),

  // --- Split ratios (configs/data.yaml) --------------------------------
  getSplit: () =>
    jsonFetch<{ train: number; eval: number; test: number; seed: number }>(
      p("/api/data/split")),
  saveSplit: (body: { train: number; eval: number; test: number; seed: number }) =>
    jsonFetch<{ train: number; eval: number; test: number; seed: number }>(
      p("/api/data/split"), { method: "PUT", body: JSON.stringify(body) }),

  // --- Eval sets (author / append / clear) -----------------------------
  writeEvalSet: (
    name: string,
    body: { content: string; mode?: "replace" | "append" },
  ) =>
    jsonFetch<{
      name: string; mode: string; added: number; total: number;
      backup: string | null; cleared: boolean;
    }>(p(`/api/data/eval/${encodeURIComponent(name)}`), {
      method: "PUT", body: JSON.stringify(body),
    }),
  // --- Custom pipeline transform scripts (data/transforms/*.py) --------
  listTransforms: () =>
    jsonFetch<{ transforms: TransformScript[] }>(p("/api/data/transforms")),
  readTransform: (name: string) =>
    jsonFetch<{ name: string; content: string }>(
      p(`/api/data/transforms/${encodeURIComponent(name)}`)),
  saveTransform: (name: string, content: string) =>
    jsonFetch<{
      name: string; size_bytes: number; backup: string | null;
      warnings: string[]; description: string;
    }>(p(`/api/data/transforms/${encodeURIComponent(name)}`), {
      method: "PUT", body: JSON.stringify({ content }),
    }),
  deleteTransform: (name: string) =>
    jsonFetch<{ deleted: boolean; name: string }>(
      p(`/api/data/transforms/${encodeURIComponent(name)}`),
      { method: "DELETE" }),
  runTransform: (name: string, body: { input: string; output?: string }) =>
    jsonFetch<TransformRunResult>(
      p(`/api/data/transforms/${encodeURIComponent(name)}/run`), {
        method: "POST", body: JSON.stringify(body),
      }),
  saveTransformOrder: (order: string[]) =>
    jsonFetch<{ order: string[] }>(p("/api/data/transforms-order"), {
      method: "PUT", body: JSON.stringify({ order }),
    }),
  runTransformChain: (body: { input: string; output?: string; steps?: string[] }) =>
    jsonFetch<TransformChainResult>(p("/api/data/transforms-run-chain"), {
      method: "POST", body: JSON.stringify(body),
    }),

  importHuggingFace: (body: {
    name: string; split?: string; max_records?: number;
    subset?: string; output_filename?: string;
  }) =>
    jsonFetch<{
      kind: "dataset_import_result";
      path: string; name: string; split: string; subset: string | null;
      kept: number; skipped: number; samples: string[]; message: string;
    }>(p("/api/data/import_hf"), {
      method: "POST", body: JSON.stringify(body),
    }),

  // --- Training Studio (/train page) -----------------------------------
  trainStudio: () => jsonFetch<StudioCatalog>(p("/api/train/studio")),
  trainPreview: (body: {
    method: StudioMethod; recipe?: string | null;
    overrides?: Record<string, unknown>;
  }) =>
    jsonFetch<{ config_path: string; yaml: string }>(p("/api/train/preview"), {
      method: "POST", body: JSON.stringify(body),
    }),
  trainLaunch: (body: {
    method: StudioMethod; smoke: boolean; recipe?: string | null;
    overrides?: Record<string, unknown>;
  }) =>
    jsonFetch<TrainLaunchResult>(p("/api/train/launch"), {
      method: "POST", body: JSON.stringify(body),
    }),
  trainCancel: (pid: number) =>
    jsonFetch<{ kind: string; killed: boolean; message: string }>(
      p("/api/train/cancel"), {
        method: "POST", body: JSON.stringify({ pid }),
      }),
  trainMaterialize: (body: {
    method: StudioMethod; recipe?: string | null;
    overrides?: Record<string, unknown>;
  }) =>
    jsonFetch<{ config_path: string; yaml: string }>(
      p("/api/train/materialize"), {
        method: "POST", body: JSON.stringify(body),
      }),
  saveRecipe: (body: {
    name: string; method: StudioMethod;
    overrides: Record<string, unknown>; description?: string;
  }) =>
    jsonFetch<{ recipe: StudioRecipe }>(p("/api/train/recipes"), {
      method: "POST", body: JSON.stringify(body),
    }),
  deleteRecipe: (id: string) =>
    jsonFetch<{ deleted: boolean }>(
      p(`/api/train/recipes/${encodeURIComponent(id)}`), { method: "DELETE" }),
  trainLog: (adapterDir: string, tail = 300) =>
    jsonFetch<TrainingLogPayload>(p(
      `/api/train/log?adapter_dir=${encodeURIComponent(adapterDir)}&tail=${tail}`)),
  trainRunConfig: (adapterDir: string) =>
    jsonFetch<RunConfigPayload>(p(
      `/api/train/run-config?adapter_dir=${encodeURIComponent(adapterDir)}`)),
  trainPreflight: (body: {
    method: StudioMethod; recipe?: string | null;
    overrides?: Record<string, unknown>; local?: boolean;
  }) =>
    jsonFetch<TrainPreflight>(p("/api/train/preflight"), {
      method: "POST", body: JSON.stringify(body),
    }),
  trainEstimate: (body: {
    method: StudioMethod; recipe?: string | null;
    overrides?: Record<string, unknown>;
  }) =>
    jsonFetch<TrainEstimate>(p("/api/train/estimate"), {
      method: "POST", body: JSON.stringify(body),
    }),

  // --- Provider catalog (frontend model picker) ----------------------
  models: () => jsonFetch<{
    default: string;
    models: Array<{
      id: string; label: string; vendor: string;
      requires: string; description: string; available: boolean;
    }>;
  }>("/api/models"),

  // --- Threads (scoped by current project_id via p()) ------------------
  listThreads: () =>
    jsonFetch<{ threads: ThreadSummary[] }>(p("/api/threads")),
  createThread: (body: { title?: string; model?: string } = {}) =>
    jsonFetch<{ thread: ThreadSummary }>(p("/api/threads"), {
      method: "POST", body: JSON.stringify(body),
    }),
  getThread: (id: string) =>
    jsonFetch<{ thread: ThreadSummary; messages: StoredMessage[] }>(
      p(`/api/threads/${id}`)),
  updateThread: (id: string, body: { title?: string; model?: string }) =>
    jsonFetch<{ thread: ThreadSummary }>(p(`/api/threads/${id}`), {
      method: "PATCH", body: JSON.stringify(body),
    }),
  deleteThread: (id: string) =>
    jsonFetch<{ deleted: boolean }>(p(`/api/threads/${id}`), { method: "DELETE" }),
  /** Rewind a conversation: drop stored messages with idx >= fromIdx. */
  truncateThread: (id: string, fromIdx: number) =>
    jsonFetch<{ deleted: number; thread_id: string }>(
      p(`/api/threads/${id}/truncate`), {
        method: "POST", body: JSON.stringify({ from_idx: fromIdx }),
      }),

  // --- Streaming chat --------------------------------------------------
  chatStream: async (
    body: {
      thread_id: string;
      content: AnthropicContentBlock[];
      system_extra?: string;
    },
    init?: { signal?: AbortSignal },
  ): Promise<Response> => {
    const r = await fetch(`${STREAM_BASE}${p("/api/chat")}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json", Accept: "text/event-stream",
        ...authHeader(),
      },
      body: JSON.stringify(body),
      signal: init?.signal,
    });
    if (!r.ok || !r.body) {
      throw await responseError(r, "AI chat");
    }
    return r;
  },

  // --- Live training subscription URL --------------------------------
  liveTrainingURL: (interval = 2.0): string =>
    `${STREAM_BASE}/api/live/training?interval=${interval}`,
};
