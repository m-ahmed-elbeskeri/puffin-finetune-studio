<div align="center">

# 🐧 puffin-finetune-studio

**The golden-path platform for fine-tuning open LLMs, and shipping them safely.**

Config-driven SFT / LoRA / DPO with reproducible lineage, hard eval gates, a model
registry, production monitoring, cloud-portable serving, and an AI copilot you open
with a single command.

[![CI](https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio/actions/workflows/llmops-ci.yml/badge.svg)](https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio/actions/workflows/llmops-ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[Quickstart](#-quickstart) · [Why](#-why-puffin) · [Architecture](#-architecture) · [The Copilot](#-the-copilot) · [Docs](#-documentation) · [Contributing](#-contributing)

</div>

---

## ✨ TL;DR

```bash
pip install -e ".[copilot]"
finetune-copilot          # opens the dashboard in your browser
```

That one command starts the backend and the web UI, waits for both, and lands you on a
point-and-click fine-tuning studio. Prefer the terminal? The `puffin` CLI runs the same
golden path (data → train → evaluate → gate → serve) with no code changes for ~80% of
projects, just YAML.

> **The reusable contract:** a new project is a new config plus a new dataset plus new evals.
> Not a new platform every time.

---

## 🧭 Why puffin?

Most teams rebuild the same fragile scaffolding for every fine-tune: a training script here,
an eval notebook there, a serving app that quietly drifts out of sync with training. puffin
turns that into one opinionated, tested platform.

| Problem you hit every time | What puffin gives you |
| --- | --- |
| Training/serving skew (the #1 silent failure) | Training and serving import the **same** prompt builder, chat template, tokenizer, and schemas from `src/llmops/features/`. |
| "Which data/model/seed produced this?" | Every run records git SHA, config hash, dataset version, base-model revision, seed, and package versions. |
| A bad model reaches production | A **hard promotion gate** on task / safety / regression / latency thresholds that exits non-zero on failure. |
| Locked into one cloud | Provider adapters for `local`, `gcp`, `aws`, `azure`, `kubernetes`, selected in config. |
| Fine-tuning is expert-only | The **Copilot** makes it point-and-click (or chat), with plain-English recipes from smoke test to QLoRA to DPO. |
| No visibility in production | JSON structured logs with PII redaction, Prometheus metrics, a drift monitor, and an LLM-judge quality monitor. |

---

## 🚀 Quickstart

### Prerequisites

- Python **3.11+**
- Node.js **18.18+** (only for the Copilot web UI)
- ~1 GB free disk for the smoke model; no GPU required for the smoke path

### Option A: the Copilot (point-and-click)

```bash
pip install -e ".[copilot]"

# optional: set a key to unlock chat (the dashboard works without it)
export ANTHROPIC_API_KEY="sk-ant-..."     # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."

finetune-copilot                          # backend + web UI, opens your browser
```

`finetune-copilot` installs the frontend's npm deps on first run, starts everything, and
opens the dashboard. `finetune-copilot doctor` checks your environment; `finetune-copilot
--prod` serves a prebuilt UI from a single port with no Node.js at runtime. See
[copilot/README.md](copilot/README.md) for the full tour.

No `ANTHROPIC_API_KEY`? The Copilot also drives any local agent CLI you already have
installed and authed (Claude Code, Codex, Gemini, Qwen, OpenCode, Cursor, GitHub Copilot).

### Option B: the CLI golden path

```bash
# Linux / macOS
cp .env.example .env
make setup           # install dev + train extras
make test-fast
make data-validate
make train-smoke     # tiny CPU smoke train (SmolLM2-135M by default, < 1 min)
make evaluate
make gate            # exits non-zero if thresholds are missed
make serve           # FastAPI on :8080
```

```powershell
# Windows PowerShell: same targets via make.ps1
copy .env.example .env
.\make.ps1 setup
.\make.ps1 train-smoke
.\make.ps1 gate
.\make.ps1 serve
```

The template ships with **no training data**. Drop your JSONL into `data/raw/`, list it under
`sources:` in `configs/data.yaml`, and the pipeline plus smoke train run end-to-end on a
laptop CPU. A 20-row reference dataset lives at `tests/fixtures/example.jsonl`.

---

## 🏗 Architecture

The whole platform is driven by YAML configs. Training and serving share one feature layer so
they can never drift apart, the single most common fine-tuning failure.

```text
┌──────────────────────────────────────────────────────────┐
│                       Configs (YAML)                     │
│   data.yaml │ train.yaml │ eval.yaml │ deploy.yaml       │
│        observability.yaml  +  profiles/<provider>.yaml   │
└─────────────────┬─────────────────────┬──────────────────┘
                  ▼                     ▼
        ┌──────────────────┐  ┌──────────────────┐
        │  Data pipeline   │  │ Features (shared │
        │  ingest→validate │  │ prompt/chat/     │
        │  →redact→dedupe  │  │ tokenizer/RAG/   │
        │  →split→card     │  │ schemas)         │
        └────────┬─────────┘  └────────┬─────────┘
                 ▼                     │
        ┌──────────────────┐           │
        │    Training      │ ◀─────────┘
        │  SFT / LoRA / DPO│
        │  (TRL + PEFT)    │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │   Evaluation     │
        │  task / safety / │
        │  regression /    │
        │  latency  → gate │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │  Model registry  │  MLflow by default; Vertex / SageMaker / AzureML adapters
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │   Serving        │ ◀─── shared features ─┐
        │  FastAPI +       │                       │
        │  Transformers /  │                       │
        │  vLLM            │                       │
        └────────┬─────────┘                       │
                 ▼                                 │
        ┌──────────────────┐                       │
        │   Monitoring     │                       │
        │  logs / metrics  │                       │
        │  / drift / judge │ ──── feedback loop ───┘
        └──────────────────┘
```

---

## 🤖 The Copilot

`copilot/` is an optional Next.js + FastAPI dashboard that gives the whole `llmops.*`
codebase a friendly face and an AI chat with tool-use access to it.

- **One command to open it:** `finetune-copilot` (backend + UI + browser, clean Ctrl+C teardown).
- **Train Studio** (`/train`): curated recipes (smoke → style tune → domain adaptation → QLoRA →
  full fine-tune → DPO) with a Beginner/Intermediate/Advanced knob editor, YAML preview, and a
  smoke-first launch flow.
- **Provider-agnostic:** chat through the Anthropic or OpenAI APIs, or through any local agent
  CLI you already have. Installed CLIs are auto-detected in the model picker.
- **Every page has AI actions:** audit data, run the pipeline, run evals + gate, push/promote,
  diagnose drift. `Ctrl/Cmd+K` opens a page-aware command bar.

<div align="center"><em>Full page list, provider matrix, and tool catalogue in <a href="copilot/README.md">copilot/README.md</a>.</em></div>

---

## 📦 Dataset format

<details>
<summary><strong>SFT (chat-style)</strong></summary>

```json
{
  "id": "ticket-00001",
  "source": "support-zendesk-2024-q4",
  "messages": [
    {"role": "system",    "content": "You are a helpful customer support agent."},
    {"role": "user",      "content": "How do I reset my password?"},
    {"role": "assistant", "content": "Click 'Forgot password' on the sign-in page..."}
  ],
  "quality_score": 0.92,
  "license": "internal",
  "contains_pii": false
}
```
</details>

<details>
<summary><strong>Preference (DPO)</strong></summary>

```json
{
  "prompt": "Explain transformers to a 5-year-old.",
  "chosen": "Imagine a robot that pays attention to what's important...",
  "rejected": "Transformers are a deep learning architecture introduced in...",
  "reason": "chosen is age-appropriate"
}
```
</details>

JSON Schemas live in [`data_contracts/`](data_contracts/). Records that fail validation are
blocked before training.

---

## 🎯 Fine-tuning methods

| Situation | Method | Module |
| --- | --- | --- |
| Domain-specific response format / style | SFT | `llmops.training.train_sft_lora` |
| Efficient domain adaptation | LoRA / QLoRA | `llmops.training.train_sft_lora` + lora |
| Preference alignment (chosen / rejected) | DPO | `llmops.training.train_dpo` |
| Need a single deployable file | Adapter merge | `llmops.training.merge_adapter` |
| Push to registry (MLflow / Vertex / SageMaker) | Push | `llmops.training.push_model` |

Default recommendation: **SFT + LoRA**. Switch by editing `configs/train.yaml`, no code change.

---

## 🛡 Evaluation gates

The promotion gate runs four eval layers and fails the build if thresholds are missed:

- **Task** exact match, F1, ROUGE-L, JSON validity, tool-call correctness, custom rubric.
- **Safety** prompt injection, jailbreak, data leakage, toxicity, memorization. OWASP-LLM-aligned.
- **Regression** a golden set of previously-fixed bugs and high-value queries.
- **Latency / cost** p50 / p95 / p99 latency, tokens/sec, cost per 1k requests.

```yaml
# configs/eval.yaml
gates:
  min_task_score: 0.85
  min_improvement_over_baseline: 0.05
  max_safety_failures_critical: 0
  max_regression_failures: 0
  min_json_validity: 0.995
  max_p95_latency_ms: 2500
```

`make gate` (or the Copilot's one-click gate) exits non-zero on failure.

---

## ☁️ Deployment

| Profile | Compute | Serving | Registry |
| --- | --- | --- | --- |
| `local` | local Python | FastAPI + Transformers | MLflow (file://) |
| `kubernetes_vllm` | GKE / EKS / AKS | vLLM | MLflow (PVC / S3) |
| `gcp_vertex` | Vertex AI Custom Job | Vertex Endpoint | Vertex Model Registry |
| `aws_sagemaker` | SageMaker Training | SageMaker Endpoint | SageMaker Model Registry |
| `azure_ml` | Azure ML Job | Azure ML Online Endpoint | Azure ML Registry |

Pick a profile in `configs/deploy.yaml` (`platform.provider`); the rest of the code is unchanged.

---

## 📁 Repository layout

```text
puffin-finetune-studio/
├── configs/            YAML configs (data, train, eval, deploy, observability)
├── profiles/           Provider profiles (local, gcp_vertex, aws_sagemaker, ...)
├── data_contracts/     JSON schemas for SFT / preference data
├── eval_sets/          Golden, safety, regression, latency JSONL
├── src/llmops/
│   ├── common/         Config, logging, tracking, versioning
│   ├── data/           Ingest, validate, redact, dedupe, split, card
│   ├── features/       SHARED with serving: chat template, prompt builder, schemas
│   ├── training/       SFT/LoRA, DPO, merge, push
│   ├── evaluation/     Task / safety / regression / latency / gate
│   ├── serving/        FastAPI + OpenAI-compatible + guardrails
│   ├── monitoring/     Logs, quality, drift
│   ├── providers/      local | gcp | aws | azure | kubernetes
│   └── cli.py          `puffin` entry point
├── copilot/            Next.js + FastAPI dashboard (optional, install with [copilot])
│   ├── frontend/       Next.js 15 / React 19 / Tailwind / Recharts
│   └── backend/        FastAPI tool-use loop + the finetune-copilot launcher
├── infra/              Dockerfiles + per-cloud Terraform
├── pipelines/          DVC + GitHub Actions + Vertex + Argo
├── tests/              unit / data_quality / evaluation / serving / security
└── pyproject.toml
```

---

## 📚 Documentation

| Topic | Link |
| --- | --- |
| Copilot tour, provider matrix, tool catalogue | [copilot/README.md](copilot/README.md) |
| Architecture deep-dive | [docs/architecture.md](docs/architecture.md) |
| Dataset format | [docs/dataset_format.md](docs/dataset_format.md) |
| Runbooks (rollback, on-call, incidents) | [docs/runbooks/](docs/runbooks/) |
| Security checklist | [docs/security_checklist.md](docs/security_checklist.md) |

---

## 🤝 Contributing

Contributions are very welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup, coding standards (ruff + mypy + pytest), and PR checklist, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations.

```bash
make setup && make lint && make test-fast   # green before you push
```

Good first issues are labelled [`good first issue`](https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio/labels/good%20first%20issue).

## 🔒 Security

Found a vulnerability? Please **do not** open a public issue. See [SECURITY.md](SECURITY.md)
for private disclosure.

## 🗺 Roadmap

See [open issues](https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio/issues) and the
[Discussions](https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio/discussions) board.
Near-term: GRPO/KTO recipe polish, hosted demo, one-click cloud submit from the Copilot.

## 📄 License

[Apache 2.0](LICENSE). Use it, fork it, ship it.

## 🙏 Acknowledgements

Built on the shoulders of [Transformers](https://github.com/huggingface/transformers),
[TRL](https://github.com/huggingface/trl), [PEFT](https://github.com/huggingface/peft),
[FastAPI](https://github.com/tiangolo/fastapi), [Next.js](https://github.com/vercel/next.js),
and [MLflow](https://github.com/mlflow/mlflow).

<div align="center">

If puffin saves you a weekend, consider leaving a ⭐. It genuinely helps.

</div>
