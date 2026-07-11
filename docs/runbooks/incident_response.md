# Runbook — Incident response

## Severity definitions

| Sev | Examples                                                                   | Page |
| --- | -------------------------------------------------------------------------- | ---- |
| 1   | Production down, sensitive PII leaking, jailbreak in prod                  | yes  |
| 2   | Quality regression affecting >10% of users; sustained latency breach       | yes  |
| 3   | Quality regression on a single feature; non-PII safety regression          | no   |
| 4   | Cosmetic / docs / non-prod tooling                                         | no   |

## First 5 minutes

1. **Acknowledge the page.** Confirm in the alert channel.
2. **Stop the bleeding.** If the issue is in a single model version,
   follow [rollback.md](rollback.md). If it's a serving infra issue, scale or
   restart, not rollback.
3. **Open an incident channel.** Pin: failing model version, alert link,
   first observed time.
4. **Capture evidence.** Tail the request logs (`artifacts/serving/requests.jsonl`
   or cloud equivalent) and grab the first 50 affected requests by
   request_id. Do NOT screenshot prompts/outputs into the incident channel
   if PII is involved — link to the log entries instead.

## During

- Comms cadence: every 15 minutes for sev1/2.
- Use the request_id from logs to reproduce in the eval harness:

```bash
echo '{"id":"incident-XYZ","prompt":"...","system":"...","criteria":{"forbid_refusal":true}}' \
    >> eval_sets/regression.jsonl
PUFFIN_EVAL_BACKEND=transformers \
  PUFFIN_MODEL_ID=<failing model> \
  python -m llmops.evaluation.regression_eval --config configs/eval.yaml
```

## After (within 48h)

1. Write a post-mortem in `docs/runbooks/incidents/INC-YYYY-MM-DD.md`.
2. Required fields:
   - Title
   - Severity
   - Timeline (alerts, decisions, comms)
   - Customer impact
   - Root cause
   - Detection latency (what we wish would have caught it)
   - Mitigation
   - Action items (owners + due dates)
3. Open a PR adding the failing case(s) to `eval_sets/regression.jsonl`.
4. Update the gate thresholds in `configs/eval.yaml` if the bar should rise.
5. Schedule a post-mortem review.

## What never to do

- Disable a gate threshold to ship a fix.
- Edit a regression case to make it pass.
- Delete request log entries, even on PII concerns — instead, redact in place
  using the structured logger fields (`PUFFIN_REDACT_LOGS=true`) and re-run.
- Push directly to `production` alias without the staging → canary path,
  except in the rollback procedure documented in `rollback.md`.
