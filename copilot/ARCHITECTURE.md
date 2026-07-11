# Architecture

## One-line summary

A typed Python tool registry that the Anthropic SDK calls via a streaming
tool-use loop, with a Next.js frontend that mirrors the tool result shapes as
React artifact cards.

## Request lifecycle: one chat turn

```
USER (frontend)
   │ POST /api/chat { thread_id, content: [{type:"text", text:"..."}] }
   ▼
copilot.backend.app.chat
   │
   ├─ ThreadStore.append_message(user)
   ├─ ThreadStore.to_anthropic_messages(thread_id) → history
   │
   └─ loop.run_loop(provider, model, system, history, ToolContext, …)
        │
        ├─ provider.stream_turn(...)
        │   │ Anthropic SDK Messages API (streaming)
        │   │ yields: text_delta / tool_use_end / turn_end
        │   ▼
        ├─ if stop_reason == "tool_use":
        │     for each tool_use block:
        │       registry.invoke(name, input, ToolContext)  ← validates args
        │     append a user-role tool_result message
        │     loop ← provider.stream_turn(...) again
        │
        └─ emit events: text / tool_call / tool_result / usage / done
              │
              ▼
        sse.to_sse(…)  → bytes
              │
              ▼
        StreamingResponse(media_type="text/event-stream")
              │
              ▼
USER (frontend, via iterateSse)
   ├─ text deltas → render into the active text block
   ├─ tool_call_start → render a "thinking" trace
   ├─ tool_call → fill in args
   ├─ tool_result → drop into <ArtifactRouter />
   ├─ done → mark turn complete; SWR re-fetches the thread
```

## Persistence

```
artifacts/
└─ copilot/
   └─ threads.sqlite3
      ├─ threads(id, title, model, created_at, updated_at, deleted)
      └─ messages(id, thread_id, idx, role, content_json, created_at)
```

`content_json` is the **full Anthropic-shaped content list** — text + tool_use
+ tool_result blocks. Replaying a conversation = `SELECT * FROM messages
WHERE thread_id ORDER BY idx`. The frontend uses `setFromStored()` in
`useChatStream` to recover the same in-memory ChatTurn shape.

Live training state and metrics still live in `artifacts/<adapter>/training_*.json` —
that's owned by `llmops.training._metrics_callback.TrainingMetricsCallback`,
not by the copilot. The copilot just reads them.

## Tool registry contract

A tool is a coroutine that takes a Pydantic args model and a `ToolContext`:

```python
class FooArgs(BaseModel):
    path: str
    n: int = 10

@tool("foo", description="…", args_model=FooArgs, dangerous=False)
async def foo(args: FooArgs, ctx: ToolContext) -> dict[str, Any]:
    return {"kind": "foo_result", "path": args.path, "rows": [...]}
```

- `args_model` produces the JSON schema fed to Claude.
- Return value MUST be JSON-serialisable and SHOULD carry a `kind` key — the
  frontend's `ArtifactRouter` dispatches on it.
- Raise `ToolError("...")` for user-visible failures; any other exception is
  caught, stringified, and returned as `{kind:"error", message:"…"}` — the
  loop never crashes from a misbehaving tool.
- `dangerous=True` tools are gated behind `enable_dangerous` on the
  ToolContext (env `PUFFIN_COPILOT_ENABLE_DANGEROUS`).

## Streaming protocol

The `/api/chat` SSE envelope:

| event | data |
|---|---|
| `text` | `{text}` — assistant text delta |
| `tool_call_start` | `{id, name}` — model began emitting tool_use |
| `tool_call` | `{id, name, input}` — completed tool call |
| `tool_result` | `{id, name, result}` — what `registry.invoke` returned |
| `usage` | `{input_tokens, output_tokens, cumulative_*}` |
| `assistant_message` | `{content}` — full content list for this provider turn |
| `done` | `{stop_reason}` — loop is finished |
| `error` | `{message}` — loop bailed |

`/api/live/training` SSE envelope:

| event | data |
|---|---|
| `training_state` | the `live_training` payload (only emitted on change) |
| `ping` | `{ts}` keep-alive |

## Frontend artifact router

`components/artifacts/ArtifactRouter.tsx` is a single switch over
`artifact.kind`. Every backend tool maps to exactly one React card:

```
project_status      → ProjectStatusCard
live_training       → LiveTrainingCard
run_history         → RunHistoryCard
run_detail          → RunDetailCard
dataset_audit       → DatasetAuditCard
dataset_preview     → DatasetPreviewCard
eval_result         → EvalResultCard
gate_result         → GateCard
deploy_push_result  → DeployPushCard
k8s_manifest        → K8sManifestCard
registry            → RegistryCard
server_health       → ServerHealthCard
serve_chat_result   → ServeChatCard
request_log         → RequestLogCard
config_*            → ConfigCard
train_started       → TrainStartedCard
…                   → GenericResultCard  (collapsible JSON, never breaks)
```

Add a new tool: write the Python handler, give the return dict a unique
`kind`, write a `<KindNameCard />` React component, and register it in the
switch. The TypeScript union in `lib/types.ts` keeps the dispatch type-safe.

## Why FastAPI + Next

- **Streaming.** Tool-use traces plus per-kind artifact components want a real
  React tree, not a re-rendered Python script.
- **Live updates without rerunning the script.** SSE + React lets the
  LiveTraining card update independently of whatever else the user is doing.
- **Routing.** Real URLs (`/runs/artifacts/adapter`) for sharing, not
  query-string hacks.
- **Backend reusable.** The FastAPI app is a clean HTTP surface for any
  client — CLI, dashboard, third-party integrations.
