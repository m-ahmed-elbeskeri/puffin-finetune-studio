# Tools reference

Every tool the copilot can call. The live, machine-readable version (with
exact JSON schemas) is available at `GET /api/tools` and rendered at `/docs`
in the frontend.

**Safety:** tools marked **dangerous** are state-mutating and gated behind
`PUFFIN_COPILOT_ENABLE_DANGEROUS=1`. Anything that writes to disk, starts a
process, or hits the Anthropic API is dangerous.

## Project

| Tool | Returns | Notes |
|---|---|---|
| `project_status` | `kind=project_status` | Pipeline state + hardware + registry count + a single recommended next action. **Always call first** in a new conversation. |

## Data

| Tool | Returns | Dangerous? |
|---|---|---|
| `dataset_audit` | `kind=dataset_audit` | Record count, schema detection, length percentiles, PII regex hits, warnings. |
| `dataset_preview` | `kind=dataset_preview` | First N records (≤20). |
| `data_pipeline_run` | `kind=data_pipeline_result` | **yes** — runs ingest → validate → redact → dedupe → split → card. |

## Training

| Tool | Returns | Dangerous? |
|---|---|---|
| `train_start` | `kind=train_started` | **yes** — spawns a subprocess. Use `smoke=true` first. |
| `train_status` | `kind=live_training` | Active run snapshot incl. metrics. |
| `train_history` | `kind=run_history` | All past runs (smoke + full + DPO). |
| `train_get_run` | `kind=run_detail` | One run with full metrics history. |
| `train_cancel` | `kind=train_cancel_result` | **yes** — SIGTERM by PID. |

## Evaluation

| Tool | Returns | Dangerous? |
|---|---|---|
| `eval_run` | `kind=eval_result` | **yes** — runs task/safety/regression/latency. |
| `gate_apply` | `kind=gate_result` | **yes** — applies thresholds, writes `gate_report.json`. |
| `eval_get_metrics` | `kind=eval_metrics` | Read-only fetch of the latest metrics.json. |

## Deploy

| Tool | Returns | Dangerous? |
|---|---|---|
| `deploy_push` | `kind=deploy_push_result` | **yes** — registers a new model version. |
| `deploy_promote` | `kind=deploy_promote_result` | **yes** — moves an alias pointer. |
| `deploy_render_k8s` | `kind=k8s_manifest` | Read-only YAML render. |

## Registry / serving / monitoring

| Tool | Returns | Notes |
|---|---|---|
| `registry_list` | `kind=registry` | Models + versions + aliases. |
| `serve_health` | `kind=server_health` | `/ready` probe. |
| `serve_chat` | `kind=serve_chat_result` | One chat completion. |
| `monitor_request_log` | `kind=request_log` | Tail + distributions. |
| `monitor_quality` | `kind=quality_report` | Latest quality monitor result. |
| `monitor_drift` | `kind=drift_report` | Latest drift monitor result. |

## Configs

| Tool | Returns | Dangerous? |
|---|---|---|
| `config_list` | `kind=config_list` | All `configs/*.yaml` + `profiles/*.yaml`. |
| `config_read` | `kind=config_read` | Text + parsed dict. |
| `config_edit` | `kind=config_edit_result` | **yes** — writes a `.bak` first, validates YAML before saving. Path must stay inside `configs/` or `profiles/`. |

## Authoring a new tool

```python
# copilot/backend/tools/my_thing.py
from pydantic import BaseModel, Field
from copilot.backend.tools.registry import ToolContext, tool


class MyArgs(BaseModel):
    n: int = Field(default=1, ge=1, le=100,
                   description="How many things to do.")


@tool(
    "my_thing",
    description="Do the thing. Use when the user asks for the thing.",
    args_model=MyArgs,
    dangerous=False,
)
async def my_thing(args: MyArgs, ctx: ToolContext) -> dict:
    return {"kind": "my_thing_result", "did": args.n}
```

Then:

1. Import the module in `copilot/backend/tools/__init__.py` so the decorator runs.
2. Add the TypeScript type to `copilot/frontend/lib/types.ts`.
3. Add a case to `copilot/frontend/components/artifacts/ArtifactRouter.tsx`.
4. Write `copilot/frontend/components/artifacts/MyThingCard.tsx`.
5. (Optional) add a backend test to `tests/copilot/`.

The frontend's `GenericResultCard` is always the fallback, so the chat keeps
working even before you ship the dedicated card.
