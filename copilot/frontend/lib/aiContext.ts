"use client";
/**
 * Section-specialised context for the AI side panel.
 *
 * Each page gets (a) a short system-prompt addendum sent with every drawer
 * message so the model knows where the user is standing, and (b) tailored
 * suggestion chips. The data section also owns the transform-script
 * contract used by "generate a custom pipeline script".
 */

export interface SectionContext {
  /** Human label shown as a chip in the drawer header. */
  label: string;
  /** Appended to the platform system prompt (server caps at 4000 chars). */
  systemExtra: string;
  /** Suggestion chips shown when the panel is idle. */
  suggestions: string[];
}

/** Contract every custom transform script follows: shown to the AI and
 * used as the blank-script template in the editor. */
export const TRANSFORM_CONTRACT = `Transform scripts live in data/transforms/*.py and are run as:
  python data/transforms/<name>.py --input <in.jsonl> --output <out.jsonl>
They read JSONL records line-by-line, write JSONL, print a summary line
(e.g. "kept=120 dropped=3 bad_json=1"), and exit 0 on success. Standard
library only: no third-party imports. The first docstring line is shown
as the script's description in the UI.`;

export const TRANSFORM_TEMPLATE = `"""Describe what this transform does (this line is shown in the UI)."""
import argparse
import json


def transform(record: dict) -> dict | None:
    """Return the modified record, or None to drop it."""
    # your logic here
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    kept = dropped = bad = 0
    with open(args.input, "r", encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            out = transform(rec)
            if out is None:
                dropped += 1
                continue
            fout.write(json.dumps(out, ensure_ascii=False) + "\\n")
            kept += 1
    print(f"kept={kept} dropped={dropped} bad_json={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
`;

/** Build the drawer prompt that asks the AI to write a transform script. */
export function buildTransformPrompt(opts: {
  goal: string;
  file?: { path: string; schema_hint: string } | null;
}): string {
  const fileLine = opts.file
    ? `It will run on \`${opts.file.path}\` (detected schema: ${opts.file.schema_hint}). Preview the file first if the schema matters.`
    : "Ask me which file it should run on if that matters.";
  return [
    `Write a custom pipeline transform script that does the following: ${opts.goal}`,
    "",
    fileLine,
    "",
    TRANSFORM_CONTRACT,
    "",
    "Reply with a single complete ```python code block (I'll save it as a "
    + "script from here), then a one-paragraph explanation of the approach "
    + "and any edge cases.",
  ].join("\n");
}

const DATA_CONTEXT: SectionContext = {
  label: "Data specialist",
  systemExtra: [
    "The user is on the **Data page**. You are their DATA specialist right now.",
    "Stay strictly on data work: adding and cleaning data, editing records,",
    "reshaping with scripts, building splits, inspecting quality, and authoring",
    "eval sets. If the user asks about training, deployment, or monitoring,",
    "answer briefly and point them to that page rather than going deep here.",
    "",
    "What you can do for data (use the tools, do not just describe):",
    "- SEE the data: dataset_list shows every file across data/raw, data/interim,",
    "  data/processed, and eval_sets. dataset_preview shows records;",
    "  dataset_audit gives schema, length, and PII signals.",
    "- ADD data: uploads and pastes land in data/raw/; dataset_import_hf pulls",
    "  from Hugging Face.",
    "- EDIT records: the user can add, edit, and delete individual rows from the",
    "  file browser (the table icon). Files live under data/ and eval_sets/.",
    "- RESHAPE: custom Python scripts in data/transforms/*.py clean or remap raw",
    "  files; they can be reordered and run as a chain.",
    "- BUILD SPLITS: the pipeline runs ingest, validate, split, and dataset card.",
    "  Redaction and dedupe are now editable script templates, not fixed stages.",
    "  Split ratios and seed live in configs/data.yaml (default 70/15/15).",
    "- INSPECT: token budget (real tokenizer), the chat template plus loss mask,",
    "  train/eval/test leakage, response quality, and a dataset fingerprint.",
    "- EVAL SETS: golden, safety, regression, and latency cases in eval_sets/;",
    "  golden and regression must come from the user's own domain.",
    TRANSFORM_CONTRACT,
    "When asked to write a transform script, reply with ONE complete",
    "```python block following that contract: the UI offers a save button",
    "on python blocks. Prefer dataset_audit / dataset_preview to look at the",
    "real data before writing code.",
  ].join("\n"),
  suggestions: [
    "Show me every data file I have and how many records each holds",
    "Audit my raw data and list exactly what to fix before training",
    "Write a script that drops records with an empty assistant reply",
    "Check my splits for train/eval leakage",
    "Draft 10 golden eval cases from my domain",
  ],
};

const SECTIONS: Array<{ prefix: string; ctx: SectionContext }> = [
  { prefix: "/data", ctx: DATA_CONTEXT },
  {
    prefix: "/train",
    ctx: {
      label: "Training",
      systemExtra: [
        "The user is on the Train Studio page. You are their TRAINING",
        "specialist. Stay on training: choosing a recipe, tuning knobs,",
        "smoke-testing, launching, and reading live progress.",
        "",
        "How training works here:",
        "- Recipes (train_studio_recipes) are curated presets grouped by",
        "  category: Get started (smoke, style), Efficient LoRA (domain-adapt),",
        "  Big models (QLoRA on one GPU), Maximum capacity (full fine-tune),",
        "  Preference alignment (DPO). Prefer train_studio_launch with a recipe",
        "  and/or dotted knob overrides over hand-editing YAML.",
        "- ALWAYS smoke-test first on a new dataset or config (smoke=true): CPU,",
        "  tiny model, 2 steps, ~1 min. Only do a full run after smoke passes.",
        "- The knob surface has an 'essentials' set (base model, quantization,",
        "  LoRA rank/alpha, epochs, learning rate, batch size) plus everything",
        "  else. Explain tradeoffs in plain terms (rank = capacity; alpha scales",
        "  the update; lr too high = instability; QLoRA-nf4 fits big models on",
        "  one GPU; DPO beta = how far from the reference).",
        "- Live state: train_status shows the stage (loading vs training step",
        "  X/Y), elapsed time, loss, and learning rate. A run whose process died",
        "  shows as failed with the log path.",
        "- Training needs the trl/peft/accelerate packages. If a launch fails",
        "  because they're missing, tell the user to install them from the Train",
        "  page's Environment panel (or `pip install -e \".[train]\"`).",
        "- Cloud training: SageMaker, Vertex, and Azure ML submit scripts live in",
        "  infra/cloud/; they take the materialized configs/train_studio.yaml.",
        "  The Environment panel installs each provider's SDK.",
        "Surface time and cost before anything expensive. Keep replies compact.",
      ].join("\n"),
      suggestions: [
        "Recommend a recipe for my dataset and explain why",
        "Smoke-test now and watch it live",
        "What do LoRA rank, alpha, and learning rate trade off?",
        "Is my environment ready to train? What's missing?",
      ],
    },
  },
  {
    prefix: "/runs",
    ctx: {
      label: "Runs",
      systemExtra:
        "The user is browsing training run history. Focus on comparing runs, "
        + "diagnosing loss curves, and picking the best adapter.",
      suggestions: [
        "Compare my recent runs and pick the best",
        "Why did my last run's loss plateau?",
      ],
    },
  },
  {
    prefix: "/evaluate",
    ctx: {
      label: "Evaluation",
      systemExtra:
        "The user is on the Evaluate page. Focus on eval modules (task, "
        + "safety, regression, latency), the promotion gate thresholds in "
        + "configs/eval.yaml, and interpreting metrics.json.",
      suggestions: [
        "Run all evals, then apply the gate and explain the verdict",
        "Walk me through my latest eval metrics",
      ],
    },
  },
  {
    prefix: "/deploy",
    ctx: {
      label: "Deploy",
      systemExtra:
        "The user is on the Deploy page. Focus on the registry under "
        + "artifacts/_registry, aliases (candidate → staging → production), "
        + "and gate-before-deploy discipline.",
      suggestions: [
        "Push the latest passing adapter and promote to staging",
        "What's currently on each alias?",
      ],
    },
  },
  {
    prefix: "/monitor",
    ctx: {
      label: "Monitoring",
      systemExtra:
        "The user is on the Monitor page. Focus on the serving request log, "
        + "quality judge reports, and drift metrics.",
      suggestions: [
        "Diagnose drift and quality on recent traffic",
        "Show the last 25 requests and flag anything odd",
      ],
    },
  },
  {
    prefix: "/playground",
    ctx: {
      label: "Playground",
      systemExtra:
        "The user is on the Playground page chatting with their deployed "
        + "model on :8089. Focus on serve_health / serve_chat sanity checks.",
      suggestions: ["Sanity-check my deployed model with 3 tricky prompts"],
    },
  },
];

const DEFAULT_CONTEXT: SectionContext = {
  label: "Project",
  systemExtra:
    "The user has the AI side panel open on the dashboard. Keep answers "
    + "compact: the panel is narrow. Prefer running tools over guessing.",
  suggestions: [
    "What's the state of this project? What should I do next?",
    "Take me from raw data to a deployed model, step by step",
  ],
};

export function sectionContext(pathname: string | null): SectionContext {
  const path = pathname ?? "/";
  for (const { prefix, ctx } of SECTIONS) {
    if (path.startsWith(prefix)) return ctx;
  }
  return DEFAULT_CONTEXT;
}
