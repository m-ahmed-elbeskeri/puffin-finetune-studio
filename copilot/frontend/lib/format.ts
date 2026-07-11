/**
 * Human-readable formatters (mirror ui/components/training_runs.py).
 */

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "-";
  const s = Number(seconds);
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "-";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso.slice(0, 19);
  const delta = (Date.now() - dt.getTime()) / 1000;
  if (delta < 60) return `${Math.floor(delta)}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86_400) return `${Math.floor(delta / 3600)}h ago`;
  return dt.toLocaleString();
}

export function fmtParams(n: number | null | undefined): string {
  if (!n) return "-";
  if (n >= 1_000_000_000) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1e3).toFixed(0)}K`;
  return String(n);
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "-";
  if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`;
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

/**
 * Metric glossary: single source of truth for tooltip help, mirrors the
 * backend METRIC_GLOSSARY in ui/components/training_runs.py.
 */
export const METRIC_HELP: Record<string, string> = {
  loss: "Average training cross-entropy on this logging window. Lower = the model is fitting the training data better. Watch the curve, not the absolute number: it depends on tokenizer + sequence length.",
  eval_loss: "Cross-entropy on the held-out eval split. If eval_loss rises while train loss falls, you're overfitting.",
  learning_rate: "Current optimizer step size. Schedules ramp it down; warmup ramps it up. Flat zero at the end is normal.",
  grad_norm: "L2 norm of the gradient before clipping. Spikes >> max_grad_norm often signal instability: lower the LR or increase warmup.",
  epoch: "Fraction of the training set seen. 1.0 = one full pass.",
  step: "Optimizer update count (gradient_accumulation_steps batches each).",
  duration_s: "Wall-clock seconds from on_train_begin to on_train_end.",
  final_loss: "Last training loss observed before the run finished.",
  best_eval_loss: "Minimum eval_loss across all eval steps in this run.",
  trainable_params: "Parameters that received gradient updates. With LoRA this is tiny (<1% of total).",
  total_params: "Total parameters (frozen + trainable).",
  peak_vram_gb: "Maximum CUDA memory allocated across all GPUs during the run.",
  task_score: "Pass rate on the golden eval set (0–1). Higher = better. The gate needs ≥ min_task_score from configs/eval.yaml.",
  p50_latency_ms: "Median request latency in milliseconds: the typical request.",
  p95_latency_ms: "95th-percentile request latency: what 1-in-20 requests will feel.",
  p99_latency_ms: "99th-percentile request latency: the tail your angriest users experience.",
  refusal_rate: "Fraction of monitored samples where the model refused. >30% usually means over-cautious guardrails.",
  json_validity_rate: "Fraction of monitored responses that parsed as valid JSON.",
  length_ks_statistic: "Kolmogorov-Smirnov statistic comparing prod vs train prompt lengths. >0.2 ≈ drifting.",

  // --- Evaluation & gate ---
  "safety crit": "Critical safety failures (prompt injection, data leakage, jailbreaks). The gate blocks promotion if this isn't 0.",
  "safety high": "High-severity safety failures. Must be 0 to pass the promotion gate.",
  "regression failures": "Previously-fixed bugs and golden queries that broke again. Any failure blocks promotion.",
  "cost / 1k req": "Estimated serving cost per 1,000 requests, from token counts and configured prices.",
  gate: "The promotion gate: task, safety, regression, and latency thresholds from configs/eval.yaml. PASS is required before deploy.",

  // --- Deploy / registry ---
  alias: "A movable pointer (candidate → staging → production) to a registry version. Promotion moves the alias, not the files.",
  candidate: "Freshly-pushed model version awaiting human approval.",
  staging: "Pre-production alias: run integration checks against it.",
  production: "The alias serving live traffic. Rollback = point it back to the previous version.",
  registry: "Versioned store of pushed adapters under artifacts/_registry, with lineage and aliases.",

  // --- Monitoring ---
  drift: "Are production prompts still shaped like the training data? Length/embedding distribution shifts mean your model is seeing unfamiliar inputs.",
  quality: "LLM-judge scores on sampled production traffic against a fixed rubric.",
  quality_score: "Average LLM-judge score (0–1) on sampled production responses.",

  // --- Training ---
  "lora rank": "Adapter capacity (r). 8–16 for style, 32–64 for domain knowledge. Higher = more expressive, slower, overfits small data.",
  smoke: "A ~1-minute run with a tiny model on your real data: catches data/config/env problems before you pay for GPU time.",
  adapter: "The small set of LoRA weights training produces: merged with or loaded next to the frozen base model.",
};

export function metricHelp(key: string): string {
  if (METRIC_HELP[key]) return METRIC_HELP[key];
  for (const pre of ["eval_", "train_", "test_"]) {
    if (key.startsWith(pre) && METRIC_HELP[key.slice(pre.length)]) {
      return METRIC_HELP[key.slice(pre.length)];
    }
  }
  return "";
}
