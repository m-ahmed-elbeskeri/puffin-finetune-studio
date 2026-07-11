# Model card — `<MODEL NAME>` v`<VERSION>`

> Fill in every section before promoting to staging. Empty sections are blockers.

## Identity

- **Model name:** `<MODEL_NAME>`
- **Version:** `<SEMVER or REGISTRY VERSION>`
- **Base model:** `<HF id @ revision>`
- **Method:** SFT | LoRA | QLoRA | DPO | full fine-tune
- **Adapter merged into base?** yes / no
- **Owner:** `<team / oncall handle>`
- **Created at (UTC):** `<ISO 8601>`

## Lineage

- **Training run ID:** `<MLflow / Vertex / SageMaker run id>`
- **Git SHA:** `<git sha at training>`
- **Config hash:** `<sha256 of train.yaml>`
- **Dataset version:** `<dataset card version>`
- **Chat template version:** `v1`
- **Random seed:** `<int>`
- **Container image digest:** `<image@sha256:…>`

## Intended use

- **Use cases (in scope):**
  - …
- **Out-of-scope uses:**
  - …
- **Users:** internal | partners | end-users
- **Locales / languages:** en, …

## Training data

- **Sources:** `<sources, with counts>`
- **Total examples:** `<n>`
- **Filters applied:** schema, PII redaction, license filter, near-dup removal
- **PII rate after redaction:** `<%>`
- **License:** `<license>`

## Evaluation results

| Eval                       | Score   | Threshold | Pass |
| -------------------------- | ------- | --------- | ---- |
| Task score                 | …       | ≥ 0.85    | …    |
| JSON validity              | …       | ≥ 0.99    | …    |
| Improvement vs. baseline   | …       | ≥ +5%     | …    |
| Safety failures (critical) | …       | 0         | …    |
| Safety failures (high)     | …       | 0         | …    |
| Regression failures        | …       | 0         | …    |
| p95 latency (ms)           | …       | ≤ 2 500   | …    |
| Cost / 1k requests (USD)   | …       | ≤ 5.00    | …    |

Full per-case results: `artifacts/eval/metrics.json`.

## Safety considerations

- **OWASP-LLM categories tested:** prompt_injection, jailbreak, pii_leakage, toxicity,
  training_data_memorization, unsafe_tool_use, overclaim_medical_legal_financial.
- **Memorization probe result:** …
- **Known failure modes:** …
- **Mitigations:** input + output guardrails, refusal patterns, RAG grounding for
  facts that may be stale.

## Deployment

- **Profile:** local | gcp_vertex | aws_sagemaker | azure_ml | kubernetes_vllm
- **Serving backend:** transformers | vllm
- **Min / max replicas:** … / …
- **Quantization:** none | 4bit | 8bit
- **Rollback target:** `<previous version + alias>`

## Monitoring

- **Dashboards:** `<URLs>`
- **Alerts wired up:** p95 latency, error rate, refusal-rate drift
- **Quality monitor schedule:** every 6h
- **Drift monitor schedule:** daily

## Approvals

- [ ] Author sign-off
- [ ] Reviewer sign-off (eng)
- [ ] Reviewer sign-off (safety / policy)
- [ ] Rollback target confirmed
- [ ] Runbook reviewed
