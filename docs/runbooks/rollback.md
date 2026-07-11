# Runbook — Model rollback

## When to use this

Any of:
- Quality alert firing for >5 minutes (refusal_rate_drift, hallucination spike).
- p95 latency alert above 3s for >5 minutes.
- Error-rate alert: 5xx > 2% for >5 minutes.
- Safety incident reported by a user, partner, or oncall.

## Pre-conditions

- A previous `production` model alias is still warm (this is policy — do not
  decommission the rollback target until the new model is 24h stable).
- The on-call has access to the model registry and deployment backend.

## Local profile

```bash
puffin-finetune-studio> python -m llmops.training.push_model \
    --model-dir artifacts/_registry/<model>/v<previous> \
    --name <model> --alias production
```

Or directly via the registry adapter:

```python
from llmops.providers.factory import get_registry
get_registry({"registry": {"backend": "local"}}).promote(
    name="customer-support-llm", version="3", alias="production",
)
```

## GCP / Vertex AI

```bash
gcloud ai endpoints predict --region=$GCP_REGION ...   # current sanity check
puffin promote --backend vertex_ai --name <model> --version <prev> --alias production
```

Or imperatively:

```python
from llmops.providers.gcp import VertexAIEndpointDeployment
VertexAIEndpointDeployment().rollback(environment="prod")
```

## AWS / SageMaker

```bash
aws sagemaker update-endpoint \
    --endpoint-name puffin-prod \
    --endpoint-config-name puffin-prod-config-<previous>
```

## Azure ML

```bash
az ml online-deployment update \
    --name default --endpoint-name puffin-prod \
    --model azureml:<model>:<previous-version>
```

## Kubernetes (vLLM)

```bash
kubectl -n puffin rollout undo deployment/puffin-prod
kubectl -n puffin rollout status deployment/puffin-prod
```

## Post-rollback

1. **Confirm traffic is on the previous version.** Check `/model/version` on the
   serving endpoint, then sample a /v1/chat/completions response.
2. **Open an incident** in `docs/runbooks/incidents/`. Include:
   - Failing model version
   - Time of detection
   - Rollback target
   - First 10 failing inputs (anonymized)
3. **Add the failing inputs to `eval_sets/regression.jsonl`.** This is the
   single most important step — the next training run cannot ship without
   passing these cases. Use the `incident: <ID>` field so the regression
   record is traceable to the source incident.
4. **Page the model owner** for root-cause analysis.
5. **Notify stakeholders** that the previous version is in production.

## Anti-pattern

Do NOT:
- Skip the gate to "rush a fix" — that bypasses every safety check.
- Promote the previous version to `archived` until the new version is healthy
  in prod for 24h.
- Edit `eval_sets/regression.jsonl` to make it pass — the failure is the point.
