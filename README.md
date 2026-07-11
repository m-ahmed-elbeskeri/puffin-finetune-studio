# puffin-finetune-studio

A cloud-portable, opinionated, **golden-path** LLM fine-tuning template. SFT + LoRA out of the box, with eval gates, model registry, canary deployment, monitoring, and provider adapters for **local / GCP / AWS / Azure / Kubernetes**.

> **The reusable contract:** new project = new config + new dataset + new evals — *not* a new platform every time.

---

## 1. What this template gives you

- **Reproducible training** — config-driven SFT/LoRA/DPO with full lineage (git SHA, config hash, dataset version, base-model revision, seed, package versions).
- **Anti-skew shared code** — training and serving import the *same* prompt builder, chat template, tokenization, and schemas from `src/llmops/features/`.
- **Promotion gate** — task / safety / regression / latency thresholds enforced before any model is promoted.
- **Cloud-portable serving** — FastAPI + OpenAI-compatible router; Transformers backend by default, vLLM optional.
- **Provider adapters** — `local`, `gcp` (GCS / Vertex AI), `aws` (S3 / SageMaker), `azure` (Blob / Azure ML), `kubernetes` — selectable in config.
- **Production hygiene** — JSON structured logs (with PII redaction), Prometheus metrics, drift monitor, quality monitor (LLM-judge), runbooks.
- **Tests** — unit, data-quality, evaluation, serving, and security suites.

---

## 2. Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                       Configs (YAML)                     │
│   data.yaml │ train.yaml │ eval.yaml │ deploy.yaml       │
│        observability.yaml  +  profiles/<provider>.yaml   │
└─────────────────┬─────────────────────┬──────────────────┘
                  ↓                     ↓
        ┌──────────────────┐  ┌──────────────────┐
        │  Data pipeline   │  │ Features (shared │
        │  ingest→validate │  │ prompt/chat/     │
        │  →redact→dedupe  │  │ tokenizer/RAG/   │
        │  →split→card     │  │ schemas)         │
        └────────┬─────────┘  └────────┬─────────┘
                 ↓                     │
        ┌──────────────────┐           │
        │    Training      │ ←─────────┘
        │  SFT / LoRA / DPO│
        │  (TRL + PEFT)    │
        └────────┬─────────┘
                 ↓
        ┌──────────────────┐
        │   Evaluation     │
        │  task / safety / │
        │  regression /    │
        │  latency  →gate  │
        └────────┬─────────┘
                 ↓
        ┌──────────────────┐
        │  Model registry  │  (MLflow by default; Vertex / SageMaker / AzureML adapters)
        └────────┬─────────┘
                 ↓
        ┌──────────────────┐
        │   Serving        │ ←─── shared features ─┐
        │  FastAPI +       │                       │
        │  Transformers /  │                       │
        │  vLLM            │                       │
        └────────┬─────────┘                       │
                 ↓                                 │
        ┌──────────────────┐                       │
        │   Monitoring     │                       │
        │  logs / metrics  │                       │
        │  / drift / judge │ ──── feedback loop ───┘
        └──────────────────┘
```

The serving and training pipelines share `src/llmops/features/` to **prevent training/serving skew** — the single most common LLM fine-tuning failure.

---

## 3. Local quickstart

```powershell
# Windows PowerShell
copy .env.example .env
.\make.ps1 setup
.\make.ps1 lint
.\make.ps1 test-fast
.\make.ps1 data-validate
.\make.ps1 train-smoke   # tiny CPU smoke train
.\make.ps1 evaluate
.\make.ps1 gate
.\make.ps1 serve         # FastAPI on :8080
```

```bash
# Linux / macOS
cp .env.example .env
make setup
make lint
make test-fast
make data-validate
make train-smoke
make evaluate
make gate
make serve
```

The smoke path uses a tiny model (`HuggingFaceTB/SmolLM2-135M-Instruct` by default). The template ships with **no training data** — drop your JSONL into `data/raw/`, list it under `sources:` in `configs/data.yaml`, and the data pipeline + smoke train run end-to-end on a laptop CPU in under a minute. A 20-row reference dataset lives at `tests/fixtures/example.jsonl` if you need a shape example.

### 3a. Optional: launch the Copilot

```powershell
pip install -e ".[copilot]"
cd copilot/frontend; npm install --legacy-peer-deps; cd ../..
$env:ANTHROPIC_API_KEY = "sk-ant-..."
./copilot/scripts/dev.ps1
# frontend on http://localhost:3000, backend on http://localhost:8765
```

`./copilot/scripts/dev.sh` on macOS/Linux/WSL. The Copilot is a Next.js + FastAPI chat
dashboard with tool-use access to the whole `llmops.*` codebase. It is
provider-agnostic: chat through the Anthropic or OpenAI APIs, **or through any
local agent CLI you already have installed and authed** — Claude Code, Codex,
Gemini CLI, Qwen Code, OpenCode, Cursor Agent, GitHub Copilot CLI. Installed
CLIs are auto-detected and appear in the model picker (no API key needed);
`GET /api/clis` reports what's installed, at which version, with install hints.

The **Train Studio** page (`/train`) makes fine-tuning point-and-click at any
skill level: curated recipes (smoke test → style tune → domain adaptation →
QLoRA → full fine-tune → DPO) with plain-English guidance, plus a
progressive-disclosure knob editor over the entire training surface with a
Beginner/Intermediate/Advanced toggle, YAML preview, and a smoke-first launch
flow. See `copilot/README.md` for the provider matrix, page list, and tool
catalogue.

---

## 4. Dataset format

### SFT (chat-style)

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
  "contains_pii": false,
  "created_at": "2024-11-12T13:55:00Z"
}
```

### Preference (DPO)

```json
{
  "prompt": "Explain transformers to a 5-year-old.",
  "chosen": "Imagine a robot that pays attention to what's important...",
  "rejected": "Transformers are a deep learning architecture introduced in...",
  "reason": "chosen is age-appropriate",
  "labeler_id": "labeler-04"
}
```

JSON Schemas live in `data_contracts/`. Records that fail validation are blocked before training.

---

## 5. Fine-tuning methods

| Situation                                              | Method            | Module                                  |
| ------------------------------------------------------ | ----------------- | --------------------------------------- |
| Domain-specific response format / style                | SFT               | `llmops.training.train_sft_lora`        |
| Efficient domain adaptation                            | LoRA / QLoRA      | `llmops.training.train_sft_lora` + lora |
| Preference alignment (chosen / rejected)               | DPO               | `llmops.training.train_dpo`             |
| Need a single deployable file                          | Adapter merge     | `llmops.training.merge_adapter`         |
| Push to model registry (MLflow / Vertex / SageMaker)   | Push              | `llmops.training.push_model`            |

Default recommendation: **SFT + LoRA**. Switch by editing `configs/train.yaml` — no code change.

---

## 6. Evaluation gates

The promotion gate runs four eval layers and fails the build if thresholds are missed:

- **Task** — exact match, F1, ROUGE-L, JSON validity, tool-call correctness, custom rubric.
- **Safety** — prompt injection, jailbreak, sensitive-data leakage, toxicity, training-data memorization. OWASP-LLM-aligned.
- **Regression** — golden set of previously-fixed bugs and high-value queries.
- **Latency / cost** — p50 / p95 / p99 latency, tokens/sec, cost per 1k requests.

```yaml
# configs/eval.yaml — promotion criteria
gates:
  min_task_score: 0.85
  min_improvement_over_baseline: 0.05
  max_safety_failures_critical: 0
  max_safety_failures_high: 0
  max_regression_failures: 0
  min_json_validity: 0.995
  max_p95_latency_ms: 2500
  max_cost_per_1k_requests_usd: 5.00
```

`make gate` exits non-zero on failure.

---

## 7. Model promotion flow

```text
candidate → staging → production → archived
```

1. Training run completes → metrics + lineage logged → artifact saved.
2. `evaluate` runs four eval suites → metrics.json written.
3. `gate` checks thresholds → exits 0 (promote) or non-zero (block).
4. `push_model` registers the model in the configured registry with alias `candidate`.
5. Human approval (manual) → promote alias to `staging`.
6. Canary rollout (1 % → 10 % → 50 % → 100 %).
7. On regression, rollback flips alias back to previous `production`.

---

## 8. Deployment options

| Profile             | Compute              | Serving           | Registry                |
| ------------------- | -------------------- | ----------------- | ----------------------- |
| `local`             | local Python         | FastAPI + Transformers | MLflow (file://)   |
| `kubernetes_vllm`   | GKE / EKS / AKS / k8s | vLLM            | MLflow (PVC / S3)       |
| `gcp_vertex`        | Vertex AI Custom Job | Vertex Endpoint   | Vertex AI Model Registry |
| `aws_sagemaker`     | SageMaker Training   | SageMaker Endpoint | SageMaker Model Registry |
| `azure_ml`          | Azure ML Job         | Azure ML Online Endpoint | Azure ML Registry |

Pick a profile in `configs/deploy.yaml` (`platform.provider`) — the rest of the code does not change.

---

## 9. Observability

Every request is logged as a single JSON line containing:

```text
request_id │ user_hash │ prompt_template_version │ model_version │ dataset_lineage
latency_ms │ input_tokens │ output_tokens │ cost_usd │ safety_result │ feedback_id
```

Prometheus metrics are exposed at `GET /metrics`. The drift monitor compares production prompt-embedding distributions against the training distribution. The quality monitor periodically samples production traffic and runs an LLM judge on a fixed rubric.

---

## 10. Security & privacy checklist

- [ ] PII redaction enabled in the data pipeline (configurable allow-list in `configs/data.yaml`).
- [ ] No forbidden licenses in the corpus.
- [ ] Eval-set leakage check passes (no near-duplicate between train and test).
- [ ] Memorization eval below threshold.
- [ ] Secrets in env vars or cloud secret manager (never in repo).
- [ ] Log redaction enabled in production (`PUFFIN_REDACT_LOGS=true`).
- [ ] OWASP-LLM categories covered in `eval_sets/safety.jsonl`.
- [ ] Model card and dataset card are complete.
- [ ] Rollback target identified before promotion.

---

## 11. Cost controls

- Default to LoRA over full fine-tuning unless evals require otherwise.
- Set `max_p95_latency_ms` and `max_cost_per_1k_requests_usd` gates.
- Use serving autoscaling with a minimum-replica floor of `0` for staging, `1+` for prod.
- Quantize for inference when accuracy permits (`configs/deploy.yaml: server.quantization`).

---

## 12. Rollback procedure

1. Detect (PagerDuty alert or manual) → identify the bad model version.
2. `puffin promote --name <model> --version <prev> --alias production` (or via cloud console).
3. Drain traffic from current endpoint; previous endpoint is kept warm by policy.
4. Open an incident; capture post-mortem in `docs/runbooks/incidents/`.
5. Add the failing inputs to `eval_sets/regression.jsonl` so the next training run cannot ship without fixing them.

Full runbook: `docs/runbooks/rollback.md`.

---

## 13. How to start a new project from this template

```bash
git clone <this-repo> my-llm-project
cd my-llm-project
cp .env.example .env

# 1. Edit configs only (no code changes needed for ~80% of projects):
#    - configs/data.yaml      → point at your raw data
#    - configs/train.yaml     → pick base model + LoRA params
#    - configs/eval.yaml      → set thresholds
#    - configs/deploy.yaml    → pick profile (local/gcp_vertex/...)
#    - eval_sets/golden.jsonl → your golden test cases
#    - eval_sets/safety.jsonl → your safety test cases

# 2. Run the local loop until evals pass:
make data-build
make train-smoke
make evaluate
make gate

# 3. Submit to your cloud:
#    GitHub Actions runs lint → tests → smoke train → smoke eval on every PR.
#    Merging to main triggers full training + evaluation + registry push.
```

---

## Repository layout

```text
puffin-finetune-studio/
├── configs/                  # YAML configs (data, train, eval, deploy, observability)
├── profiles/                 # Provider profiles (local, gcp_vertex, aws_sagemaker, ...)
├── data_contracts/           # JSON schemas for SFT / preference data
├── eval_sets/                # Golden, safety, regression, latency JSONL
├── data/raw/                 # Your raw JSONL goes here (committed empty)
├── model_cards/              # Templates + generated cards
├── dataset_cards/            # Templates + generated cards
├── docs/                     # Runbooks, architecture notes
├── src/llmops/
│   ├── common/               # Config, logging, tracking, errors, versioning
│   ├── data/                 # Ingest, validate, redact, dedupe, split, card
│   ├── features/             # SHARED with serving — chat template, prompt builder, schemas
│   ├── training/             # SFT/LoRA, DPO, merge, push
│   ├── evaluation/           # Task / safety / regression / latency / gate
│   ├── serving/              # FastAPI + OpenAI-compatible + guardrails
│   ├── monitoring/           # Logs, quality, drift
│   ├── providers/            # local | gcp | aws | azure | kubernetes
│   └── cli.py                # `puffin` entry point
├── pipelines/                # DVC + GitHub Actions + Vertex + Argo
├── infra/
│   ├── docker/               # Dockerfile.train / .serve / .eval
│   └── terraform/            # Per-cloud modules
├── tests/                    # unit / data_quality / evaluation / serving / security
├── copilot/                  # Next.js + FastAPI chat dashboard (optional, install with [copilot])
│   ├── frontend/             # Next.js 15 / React 19 / Tailwind / Recharts
│   ├── backend/              # FastAPI + Anthropic SDK tool-use loop, 24 typed tools
│   └── scripts/              # dev.ps1 / dev.sh launchers
├── scripts/                  # Bootstrap, smoke, dataset version, promote
├── Makefile / make.ps1       # Linux + Windows targets
└── pyproject.toml
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
