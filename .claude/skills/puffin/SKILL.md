---
name: puffin
description: |
  Drive the Puffin LLM fine-tuning platform from inside this repo. Use whenever the user
  asks to fine-tune, train, evaluate, deploy, monitor, or chat with a model in this
  project — including phrases like "smoke train", "run evals", "apply gate", "push to
  registry", "promote to staging", "is training running", "what's the loss", "tail
  request log", "audit my data", "what's in train.jsonl". Also use for fix/inspect
  asks against any `configs/*.yaml` or `profiles/*.yaml`, and for any reference to
  the copilot backend or the FastAPI serving app.
---

# Puffin platform — operator reference for Claude Code

This repo is **puffin-finetune-studio**: a cloud-portable LLM fine-tuning template
(SFT/LoRA/DPO with eval gates, registry, monitoring, provider adapters). When the
user is in this folder and asks to do anything model-related, prefer Puffin's
in-repo tools over inventing flows.

## Pipeline (5 stages, in order)

| Stage | What | Code | Outputs |
|---|---|---|---|
| Data | ingest → validate → redact PII → dedupe → split → card | `llmops.data.*` | `data/processed/{train,eval,test}.jsonl` + `dataset_cards/generated.md` |
| Train | SFT+LoRA or DPO | `llmops.training.train_sft_lora`, `train_dpo` | `artifacts/adapter*/` |
| Evaluate | task / safety / regression / latency + gate | `llmops.evaluation.*` | `artifacts/eval/metrics.json` + `gate_report.json` |
| Deploy | push to registry, promote between aliases | `llmops.training.push_model` + `llmops.providers.*` | `artifacts/_registry/<name>/manifest.json` |
| Monitor | request log + quality + drift | `llmops.monitoring.*` | `artifacts/monitoring/{quality,drift}.json` |

The full reference path on the **Train** page is:

```bash
PYTHONUTF8=1 python -m llmops.training.train_sft_lora --config configs/train.yaml --smoke-test
```

**Always smoke first** for a new dataset/config. Smoke = `--smoke-test` flag → CPU,
SmolLM2-135M, 2 steps, ~30s. Real training only after smoke passes.

## Live training (read this when the user asks "how's training going?")

Training writes three sidecars next to the adapter dir:

- `training_state.json` — rewritten every step. `status` ∈ {running, completed, failed, stalled}.
  Fields: `pid`, `current_step`, `total_steps`, `current_epoch`, `current_loss`, `current_lr`.
- `training_metrics.jsonl` — one row per logging step (loss, learning_rate, grad_norm, epoch).
- `training_summary.json` — written at on_train_end (duration_s, final_loss, best_eval_loss,
  peak_vram_gb, trainable_params).

Always read the JSON files directly with `Read` rather than rerunning training to check.

## The dashboard

**Copilot** (`copilot/`): React/Next.js chat UI + FastAPI backend with **24 typed tools** plus
multi-provider chat: Anthropic API, OpenAI API, and local agent CLIs (Claude Code,
Codex, Gemini CLI, Qwen Code, OpenCode, Cursor Agent, GitHub Copilot CLI — the last
five via the generic spec-driven adapter in `copilot/backend/providers/agent_cli.py`;
add the next CLI as an `AGENT_CLI_CATALOG` entry, not a new provider class). Installed
CLIs are auto-detected; `GET /api/clis` is the doctor (installed / version / wired /
install hint). Run with `./copilot/scripts/dev.ps1` (Windows) or
`./copilot/scripts/dev.sh` — frontend on :3000, backend on :8765.

**Train Studio** (`/train` page): recipes + knob editor over the training config.
Catalog is data in `copilot/backend/training_studio.py` (RECIPES + KNOBS with
levels/help text); REST: `GET /api/train/studio`, `POST /api/train/preview|launch|cancel`.
Launches materialize `configs/train_studio.yaml` (or `train_dpo_studio.yaml`) from the
base config + dotted-path overrides — never edit the generated file, and don't add a
knob without help text + level + methods (tests enforce this). User overrides beat
recipe overrides; virtual selects (`model.quantization`, `lora.target_modules`) map
friendly names to config blocks.

## Tool catalogue mirrors the copilot

The copilot exposes 24 Python tools at `copilot/backend/tools/*.py`. From Claude Code you
have direct file access — call those modules directly via `Bash` rather than going through
the HTTP layer. Each tool's args are Pydantic-typed; the `kind` field on the return value
is what the frontend dispatches on.

Key tools to know:
- `project_status` → 5-step pipeline state + hardware + recommended next action.
- `dataset_audit` → schema detection + length percentiles + PII regex + warnings.
- `train_start(method, smoke)` → spawns subprocess; survives UI disconnect.
- `train_status` → reads sidecar JSON; never re-runs training to check.
- `eval_run` + `gate_apply` → run evals then apply thresholds from `configs/eval.yaml`.
- `deploy_push` + `deploy_promote` → local registry under `artifacts/_registry/`.
- `serve_chat` → one chat completion against the FastAPI serving app on :8089.
- `monitor_request_log`, `monitor_quality`, `monitor_drift` → read the JSONL/JSON sidecars.
- `config_read` + `config_edit` → YAML configs/profiles; edits write a `.bak` and validate first.

Full reference: `copilot/TOOLS.md`.

## Key invariants — do not violate

1. **Smoke before full** on every new config/dataset. The smoke path writes
   to `artifacts/adapter-smoke/`, the real path to `artifacts/adapter/`.
2. **Gate before deploy.** `deploy_push` should follow a PASS verdict from
   `gate_apply`. The dashboard's stepper enforces this visually; respect it.
3. **No bypass of `_metrics_callback`.** Both trainers wire it as
   `callbacks=[metrics_cb]`. If you fork a trainer, keep the callback or
   the Monitor page goes dark on that run.
4. **Configs live under `configs/` and `profiles/`** — and only those paths
   are writeable by the copilot's `config_edit` tool. Edits elsewhere go
   through `Edit` directly.
5. **Windows note:** always prefix Python invocations with `PYTHONUTF8=1`.
   TRL's jinja loader is cp1252-broken on Windows.

## Common asks and the right entry point

| User says… | First action |
|---|---|
| "What should I do next?" | `project_status` |
| "Is training running?" | `train_status` (reads JSON; don't re-launch) |
| "How's training going?" | `train_status`, then explain the loss trajectory |
| "Last run took how long?" | `train_history` and quote `duration_s` |
| "My data ready to train?" | `dataset_audit data/raw/<file>.jsonl` |
| "Run smoke train" | `train_start(method='sft', smoke=true)` |
| "Run all evals" | `eval_run` then `gate_apply` |
| "Push the adapter" | check `gate_apply` PASS first, then `deploy_push` |
| "Promote to production" | `deploy_promote(name, version, alias='production')` |
| "Chat with the model" | `serve_health` then `serve_chat` |
| "What's hitting serving?" | `monitor_request_log` |

## Don't reach for these by default

- **Don't** run the data pipeline if `data/processed/train.jsonl` already exists unless
  the user explicitly asked to rebuild.
- **Don't** start full training (`smoke=false`) without an explicit user "yes, full train".
- **Don't** edit `pyproject.toml`, `infra/`, or `src/llmops/training/_metrics_callback.py`
  without checking first — they're load-bearing.
