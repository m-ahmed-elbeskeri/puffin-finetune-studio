# Runbook — On-call basics

## Daily check (15 minutes)

1. **Dashboards** — green across:
   - p50 / p95 / p99 latency
   - error rate
   - refusal rate (should be stable; spike = drift)
   - safety classifier counter
   - GPU utilization & queue depth (if vLLM)
2. **Recent deploys** — `puffin info` shows the live model_version on each env.
3. **Open alerts** — any silenced alerts? Re-open if mitigation no longer holds.
4. **Quality monitor digest** — `artifacts/monitoring/quality.json`:
   - mean LLM-judge score should be ≥ training-time baseline.
   - new failure cluster? Open a ticket.

## Common alerts → action

| Alert                        | First response                                                  |
| ---------------------------- | --------------------------------------------------------------- |
| `high_p95_latency`           | Check serving CPU/GPU saturation; scale replicas; check vLLM logs for OOM. |
| `error_rate_spike`           | Tail request log; group by `error_type`; if guardrail-driven, capture pattern. |
| `refusal_rate_drift`         | Sample 10 affected requests; were they actually unsafe? If not → quality regression → rollback path. |
| `gate_failure_in_ci`         | Don't bypass. Reach out to owner; help triage. |
| `dataset_validation_failure` | Bad upstream data — block the dataset version, ping owner. |

## Escalation

- Sev1/2: page model owner via PagerDuty rotation `puffin-llm-prod`.
- Sev3/4: ticket in `LLM-PROD` project.
- After-hours infra: page `mlplat-oncall`.

## Tools you'll need

- `kubectl` (for K8s + vLLM)
- `gcloud` / `aws` / `az` CLI for the relevant cloud
- Grafana / cloud-native dashboards
- MLflow UI (for lineage + registry)
- The Python repo checked out locally so you can run the eval harness against
  any reproducer prompt.

## Recovery time targets

| Severity | MTTA | MTTR |
| -------- | ---- | ---- |
| 1        | 5 m  | 60 m |
| 2        | 15 m | 4 h  |
| 3        | 1 h  | 1 d  |
