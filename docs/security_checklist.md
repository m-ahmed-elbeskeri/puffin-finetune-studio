# Security & privacy checklist

Walk through this before promoting a model to staging.

## Data

- [ ] No PII in raw data unless contractually permitted; otherwise PII redacted
      by `llmops.data.redact_pii`.
- [ ] No forbidden licenses present (`forbidden_licenses` in `configs/data.yaml`).
- [ ] Train/test leakage check has run and passed (`split.leakage_max == 0`).
- [ ] Dataset card complete and approved.
- [ ] Memorization eval below the configured threshold.

## Model

- [ ] Base model and revision are pinned.
- [ ] Training config hash recorded in lineage.
- [ ] Adapter or merged weights are stored in versioned, encrypted storage.
- [ ] Model card complete with rollback target.

## Serving

- [ ] Input guardrails configured (`max_input_chars`, `max_messages`, banned patterns).
- [ ] Output guardrails configured (`banned_output_patterns`, max length).
- [ ] OpenAI-compatible request validation enforced (pydantic schema).
- [ ] HTTPS termination at the load balancer / ingress.
- [ ] Request logging defaults to NOT logging prompts/outputs
      (`observability.log_prompts: false`, `observability.log_outputs: false`).
- [ ] Production env has `PUFFIN_REDACT_LOGS=true`.
- [ ] User identifiers are hashed in logs (`PUFFIN_USER_HASH_SALT` set, distinct per env).
- [ ] No secrets baked into Docker images; secrets pulled from cloud secret manager.

## Evaluation

- [ ] OWASP-LLM safety eval set covers: prompt injection, jailbreak, PII leakage,
      toxicity, training-data memorization, unsafe tool use, overclaim domains.
- [ ] Promotion gate enforces `max_safety_failures_critical: 0` and
      `max_safety_failures_high: 0`.
- [ ] Regression set updated after every incident.

## Cloud

- [ ] Service accounts use least-privilege IAM (`infra/terraform/.../iam`).
- [ ] Storage buckets are private + versioned + encrypted at rest.
- [ ] Container registry images are immutable / pinned by digest in deployment manifests.
- [ ] Network egress restricted (VPC Service Controls / private subnets / NetworkPolicy).
- [ ] Audit logging enabled for the project / account.

## Operational

- [ ] Rollback target identified and warm.
- [ ] On-call runbook reviewed.
- [ ] Alert routing tested (paged the rotation in dry-run).
- [ ] Quality monitor and drift monitor scheduled.
- [ ] Disaster-recovery: model artifacts + dataset versions are in cross-region
      backups.

## NIST AI RMF / OWASP-LLM mapping

| Concern                             | Where it's enforced                                |
| ----------------------------------- | -------------------------------------------------- |
| LLM01 Prompt injection              | `eval_sets/safety.jsonl::prompt_injection`         |
| LLM02 Insecure output handling      | `serving/guardrails.py::check_output`              |
| LLM03 Training data poisoning       | `data/validate.py` + `dedupe.py` + dataset card    |
| LLM04 Model DoS                     | guardrails (max input chars / messages) + autoscaling |
| LLM05 Supply chain vulnerabilities  | pinned base model revision, signed images, Renovate |
| LLM06 Sensitive information disclosure | `redact_pii.py`, no log of prompts by default   |
| LLM07 Insecure plugin design        | tool-call guardrails in safety eval set            |
| LLM08 Excessive agency              | `unsafe_tool_use` safety category                  |
| LLM09 Overreliance                  | `overclaim_medical_legal_financial` safety category |
| LLM10 Model theft                   | private registry, signed model artifacts           |
