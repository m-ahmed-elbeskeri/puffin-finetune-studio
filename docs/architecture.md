# Architecture

## Three pipelines, one shared core

```text
                ┌─────────────────────────┐
                │ src/llmops/features/    │  ← imported by BOTH training and serving
                │ - chat_template (v1)    │     (THE anti-skew defense)
                │ - prompt_builder        │
                │ - schemas (pydantic)    │
                │ - rag_context           │
                │ - tokenization          │
                └────────────┬────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
 Training pipeline    Inference pipeline   RAG ingestion (optional)
 (data → SFT/LoRA →   (HTTP req → guardrails (docs → chunk → embed →
  evaluate → gate →    → backend.generate →    vector store)
  registry)            postprocess → log)
```

The single most important architectural rule: **prompts, chat templates,
tokenizer settings, and request/response schemas live in `src/llmops/features/`
and are imported by both the training data pipeline and the serving inference
pipeline**. There is exactly one definition. Forking that code is the #1 cause
of fine-tuning quality regressions in production.

## Provider plane

Every cloud-touching capability is fronted by a Protocol in
`src/llmops/providers/base.py`:

- `StorageBackend` — bytes and files.
- `ModelRegistry` — versioned model artifacts with aliases.
- `PipelineBackend` — container-based pipeline orchestration.
- `DeploymentBackend` — inference deployment + rollback.

Implementations live in `src/llmops/providers/{local,gcp,aws,azure,kubernetes}.py`
and `mlflow_registry.py`. Cloud SDKs are imported lazily — the package is
import-safe with no cloud extras installed.

The `factory.py` module reads `profiles/<provider>.yaml` and dispatches to the
right adapter at runtime.

## Data flow at a glance

```text
data/raw/*.jsonl
   │
   │  ingest      (normalize: prompt/response → messages, defaults)
   ▼
data/interim/all.jsonl
   │
   │  validate    (jsonschema + pydantic + license filter + max chars)
   │  redact_pii  (regex + Luhn + deny terms)
   ▼
data/interim/redacted.jsonl
   │
   │  dedupe      (MinHash LSH; falls back to exact hash)
   ▼
data/interim/deduped.jsonl
   │
   │  split       (deterministic stratified by source + leakage check)
   ▼
data/processed/{train,eval,test}.jsonl
   │
   │  build_dataset_card    (dataset card with stats + lineage)
   ▼
dataset_cards/generated.md
```

## Training flow

```text
train.yaml + processed/train.jsonl + features/ (shared)
   │
   │  load_text_dataset  (uses build_training_text)
   ▼
HF Dataset                ── tracker (MLflow): params + lineage tags
   │
   │  SFTTrainer (TRL) + PEFT LoRA
   ▼
artifacts/adapter (or model)  + lineage.json
   │
   │  evaluation/{task,safety,regression,latency}_eval
   ▼
artifacts/eval/metrics.json
   │
   │  evaluation/gate
   ▼
PASS → push_model → registry (alias=candidate)
       human approval → alias=staging → canary → production
```

## Serving flow

```text
HTTP POST /v1/chat/completions
   │
   │  pydantic validation (ChatCompletionRequest)
   ▼
inference_pipeline.run_chat_completion
   │
   ├── check_input  (guardrails)
   ├── backend.generate  (echo | transformers | vllm)
   ├── strip_code_fences if response_format=json_object
   ├── truncate_at_stop
   └── check_output (guardrails)
   │
   │  Prometheus metrics + RequestLogger (JSONL)
   ▼
ChatCompletionResponse  (OpenAI-compatible)
```

## Eval gate is the contract

The gate (`src/llmops/evaluation/gate.py`) is the single source of truth for
"is this model good enough to ship?" It reads `artifacts/eval/metrics.json` and
fails the build if any threshold in `configs/eval.yaml::gates` is missed.

CI calls `make gate`. Promotion scripts call `make gate`. Pipelines call
`make gate`. There is no other way to ship a model.

## Anti-skew checklist

- ✅ `build_messages` (`features/prompt_builder.py`) is the only place messages
  are composed — used by both training and serving.
- ✅ `apply_chat_template` (`features/chat_template.py`) is versioned and the
  string template is also pinned onto the live HF tokenizer in both pipelines.
- ✅ Schemas (`features/schemas.py`) are pydantic — same validation in
  training, eval, and serving.
- ✅ `format_rag_context` is a pure function — RAG ingestion and serving
  produce byte-identical context blocks.
- ✅ `TokenizerWrapper` pins `pad_token`, `chat_template`, and `revision` so
  every entrypoint loads the tokenizer the same way.
- ✅ Tests in `tests/unit/test_features.py::test_anti_skew_training_and_serving_match`
  fail loudly if anyone forks the prompt logic.

## What lives where

| Concern                  | Module                                  |
| ------------------------ | --------------------------------------- |
| Config loading + lineage | `llmops.common.config / .versioning`    |
| Tracking                 | `llmops.common.tracking`                |
| Storage abstraction      | `llmops.common.storage` + `providers/`  |
| Shared anti-skew code    | `llmops.features`                       |
| Data pipeline            | `llmops.data`                           |
| Training                 | `llmops.training`                       |
| Evaluation + gate        | `llmops.evaluation`                     |
| Serving                  | `llmops.serving`                        |
| Monitoring               | `llmops.monitoring`                     |
| Cloud adapters           | `llmops.providers`                      |
