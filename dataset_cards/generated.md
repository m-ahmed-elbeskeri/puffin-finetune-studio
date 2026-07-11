# Dataset card — puffin-project

- **Version:** `f4959df947583d05`
- **Generated:** 2026-07-03T22:00:44.759588+00:00
- **Splits:** train / eval / test

## Description

Project-specific dataset. List one or more JSONL files in `sources` —
each path is relative to the project root and must satisfy the schema
in `data_contracts/<schema_filename>`. The data pipeline ingests every
source, applies redaction + dedupe, then splits into train/eval/test.


## Counts

| Split | Records | PII | PII rate | Median chars | p95 chars |
|-------|--------:|----:|---------:|-------------:|----------:|
| train | 342 | 0 | 0.0 | 165 | 178 |
| eval | 74 | 0 | 0.0 | 164 | 177 |
| test | 73 | 0 | 0.0 | 164 | 176 |

## Sources

| Source | Records |
|--------|--------:|
| `insults` | 489 |

## Licenses

| License | Records |
|---------|--------:|
| `unknown` | 489 |

## Lineage

```json
{
  "config": "C:\\Users\\A\\Documents\\puffin-finetune-studio\\configs\\data.yaml",
  "version": "f4959df947583d05",
  "train_path": "data/processed/train.jsonl",
  "eval_path": "data/processed/eval.jsonl",
  "test_path": "data/processed/test.jsonl",
  "splits": {
    "train": 342,
    "eval": 74,
    "test": 73
  }
}
```

## Pre-training checks

- [x] Schema validation
- [x] PII redaction
- [x] Near-duplicate removal
- [x] Train/test leakage check
