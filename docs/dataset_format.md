# Dataset format

Records are stored as JSON Lines (one JSON object per line). Two record shapes
are supported, validated by JSON Schemas in `data_contracts/`.

## SFT (chat-style) — `data_contracts/sft_schema.json`

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
  "created_at": "2024-11-12T13:55:00Z",
  "metadata": {"queue": "billing"}
}
```

Fields:

| Field            | Type    | Required | Notes                                                     |
| ---------------- | ------- | -------- | --------------------------------------------------------- |
| `id`             | string  | yes      | Unique within the dataset version.                        |
| `source`         | string  | yes      | Logical source name (used by the stratified split).       |
| `messages`       | array   | yes      | At least 1; roles must be in {system, user, assistant, tool}. |
| `quality_score`  | float   | no       | 0..1; used by dedup to pick the best of a duplicate cluster. |
| `license`        | string  | no       | Any string; `forbidden_licenses` filters in `configs/data.yaml`. |
| `contains_pii`   | bool    | no       | Set to true after `redact_pii` if anything was redacted.  |
| `created_at`     | string  | no       | ISO-8601.                                                 |
| `metadata`       | object  | no       | String→string only.                                       |

### Lightweight ingest shorthand

`llmops.data.ingest` also accepts records with `prompt` / `response` (and
optional `system`) and converts them to the canonical `messages` shape:

```json
{"prompt": "How do I cancel?", "response": "Go to Account → Subscriptions...", "system": "You are a..."}
```

## Preference (DPO) — `data_contracts/preference_schema.json`

```json
{
  "id": "pref-00001",
  "prompt": "Explain transformers to a 5-year-old.",
  "chosen": "Imagine a robot that pays attention...",
  "rejected": "Transformers are a deep learning architecture...",
  "reason": "chosen is age-appropriate",
  "labeler_id": "labeler-04"
}
```

Trained by `llmops.training.train_dpo` against `configs/train_dpo.yaml`.

## Eval JSONL records

Eval sets in `eval_sets/` use a separate, simpler shape that is rendered into
the same canonical message structure at eval time:

```json
{
  "id": "golden-001",
  "prompt": "How do I reset my password?",
  "system": "You are a helpful agent.",
  "criteria": {
    "must_contain": ["password", "reset"],
    "forbid_refusal": true,
    "min_length": 20
  }
}
```

Supported `criteria` keys:
`must_contain`, `must_not_contain`, `require_json`, `require_refusal`,
`forbid_refusal`, `min_length`, `max_length`.

Safety records additionally carry `category` and `severity`
(`critical | high | medium | low`).

Regression records additionally carry `incident` (e.g. `INC-2026-04-12 — …`).

## Validation

Every record is validated by **both** `jsonschema` (against the JSON Schema)
and `pydantic` (`llmops.features.schemas.SFTExample` /
`PreferenceExample`). Both must pass — schema enforces wire format, pydantic
catches semantically invalid data the schema can't express.
