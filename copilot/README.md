# Puffin Studio

**The web studio for the Puffin LLM fine-tuning platform: a dashboard plus an AI copilot.**

A native React/Next.js app for the whole fine-tuning lifecycle (data, train,
evals, deploy, monitor) as pages you click through, with a built-in **copilot**
chat. Pick your AI backend for the chat - the Anthropic/OpenAI APIs or any local
agent CLI (Claude Code, Codex, Gemini, Qwen, OpenCode, Cursor, Copilot). The
copilot has direct tool-use access to the entire `llmops.*` codebase: it can read
your data, run training, evaluate, deploy, and watch monitoring, all by calling
typed Python functions you've defined as tools.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Next.js 15 (React 19, Tailwind, Recharts) - /chat, /runs, /monitor… │
└─────────────────────────┬────────────────────────────────────────────┘
                          │  fetch / SSE (POST /api/chat)
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI - multi-turn tool-use loop, provider-agnostic               │
│  ├─ providers: Anthropic API / OpenAI API / Claude Code / Codex /    │
│  │             Gemini CLI / Qwen / OpenCode / Cursor / Copilot CLI   │
│  ├─ 24 typed tools (pydantic args, JSON-schema'd to the model)       │
│  ├─ SQLite thread persistence (conversation history)                 │
│  └─ Live training tail (SSE) - frontend subscribes once              │
└─────────────────────────┬────────────────────────────────────────────┘
                          │  in-process imports
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  llmops.* - data / training / eval / deploy / serve / monitor        │
└──────────────────────────────────────────────────────────────────────┘
```

## Quick start

```powershell
# 1. Install backend extras (adds the `finetune-copilot` command)
pip install -e ".[copilot]"

# 2. (Optional) set your Anthropic API key so chat works
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# 3. Open the app - one command, from anywhere
finetune-copilot
```

`finetune-copilot` starts the backend and the web UI, waits until both are
serving, and opens your browser. Press Ctrl+C to stop both. It installs the
frontend's npm dependencies for you the first time.

Useful variants:

```powershell
finetune-copilot doctor      # check Node, deps, ports, and API key
finetune-copilot --no-browser --backend-port 8900   # override ports; don't auto-open
finetune-copilot build       # produce a static UI bundle (out/)
finetune-copilot --prod      # serve that bundle from one port, no Node at runtime
```

No `ANTHROPIC_API_KEY`? The dashboard still works, and the copilot also runs
entirely on your local agent CLIs - anything already installed and authed shows
up in the model picker.

<details><summary>Manual / hot-reload dev launch</summary>

```powershell
cd copilot/frontend && npm install && cd ../..   # .npmrc handles peer deps
$env:PUFFIN_COPILOT_ENABLE_DANGEROUS = "1"        # optional: unlock destructive tools
./copilot/scripts/dev.ps1                         # backend :8765 + frontend :3000
```

On macOS/Linux/WSL use `./copilot/scripts/dev.sh` instead.
</details>

## Ask AI anywhere

The AI can do everything the UI can. Every page has one-click AI actions
(audit data, run the pipeline, run evals + gate, push/promote, diagnose
drift), and **Ctrl/Cmd+K** opens a global command bar with page-aware
suggestions - type anything and it lands in Chat where the model executes
it with tools. The `train_studio_recipes` / `train_studio_launch` tools give
the AI the same recipe + knob powers as the /train page.

## Model providers

The chat backend is provider-agnostic. Each thread picks a `vendor:model`
string; the picker (`GET /api/models`) shows what's actually wired:

| Vendor | Backing | Needs | Puffin tools |
|---|---|---|---|
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY` | native tool-use |
| `openai` | OpenAI chat completions (`gpt-5`, `gpt-5-codex`) | `OPENAI_API_KEY` | function-calling |
| `claude-code` | local Claude Code CLI (agent SDK) | `claude` on PATH | mounted via MCP + CLI's own Bash/Read/Edit |
| `codex-cli` | local `codex exec --json` | `codex` on PATH | CLI's own tools |
| `gemini-cli` | local Gemini CLI, `--output-format stream-json` | `gemini` on PATH | CLI's own tools |
| `qwen-code` | local Qwen Code CLI (headless) | `qwen` on PATH | CLI's own tools |
| `opencode` | local `opencode run` | `opencode` on PATH | CLI's own tools |
| `cursor-agent` | local Cursor agent CLI (print mode) | `cursor-agent` on PATH | CLI's own tools |
| `copilot-cli` | local GitHub Copilot CLI (prompt mode) | `copilot` on PATH | CLI's own tools |

The last five run through one generic, spec-driven adapter
(`copilot/backend/providers/agent_cli.py`). Adding the next agent CLI is a
catalog entry (binary, headless flags, prompt delivery, output parser) -
not a new provider class. CLIs are auto-detected at startup; only installed
ones are wired.

`GET /api/clis` is the doctor: for every known CLI it reports installed /
path / version / wired, plus an install hint (`?refresh=1` re-probes after
you install one).

Local CLIs run with conservative flags by default (read-only sandboxes,
default approval modes). Setting `PUFFIN_COPILOT_ENABLE_DANGEROUS=1` opts
into each CLI's autonomous mode (`--approval-mode yolo`, `--force`,
`--allow-all-tools`, …).

## Pages

| Route          | What |
|----------------|---|
| `/`            | **Chat** - thread list + streaming chat with full tool access |
| `/dashboard`   | Project state at a glance, hardware, KPI tiles, quick links |
| `/train`       | **Train Studio** - recipes (beginner→advanced) or a full knob editor; smoke-first launch, YAML preview, live run card |
| `/runs`        | Training history table + drilldown (loss curve, LR schedule) + live card |
| `/monitor`     | Request log + Quality + Drift tabs |
| `/deploy`      | Local registry + serving health |
| `/playground`  | Direct chat against the serving FastAPI app (bypasses the LLM) |
| `/data`        | Pipeline state + common-ask quick links |
| `/evaluate`    | Latest metrics + per-criterion tiles |
| `/settings`    | Configs + profiles + API-key entry |
| `/docs`        | Live tool catalog (every tool, its schema, dangerous-or-safe) |

## Train Studio

`/train` makes fine-tuning approachable at every experience level without
hiding the deep end:

- **Recipes** - curated presets with plain-English guidance: Smoke test,
  Style & format tune (beginner), Domain adaptation (intermediate),
  QLoRA on one GPU, Full fine-tune, DPO alignment (advanced). Each shows
  what it changes and warns when your hardware won't fit.
- **Custom** - a knob editor over the full training surface (38 settings:
  LoRA/DoRA, quantization, optimizers, schedules, Liger/torch.compile,
  loss variants, DPO beta …). Nothing is hidden behind experience levels -
  every field has plain-English help text, changes are diffed against your
  base config with per-field reset, and there's a YAML preview.
- **Smoke-first** - the primary button is always the ~1-minute smoke test;
  full training needs a second confirming click.

Launches materialize `configs/train_studio.yaml` from your base config +
overrides (the commented `configs/train.yaml` is never touched) and start
the run through the same `train_start` tool the chat uses - so the live
loss curve, run history, and the dangerous-tool gate all behave
identically. Backend surface: `GET /api/train/studio`,
`POST /api/train/preview`, `POST /api/train/launch`,
`POST /api/train/cancel`; catalog lives in
`copilot/backend/training_studio.py` (recipes and knobs are data - add a
new preset by appending to `RECIPES`).

## Tests

```powershell
# Backend (38 tests)
pytest tests/copilot

# Frontend (23 tests)
cd copilot/frontend && npm test
```

## Production build

```powershell
cd copilot/frontend && npm run build
# Outputs static assets to copilot/frontend/.next

# Then point the backend at them so a single uvicorn serves both:
$env:PUFFIN_COPILOT_FRONTEND_DIST = "copilot/frontend/.next/server/app"
python -m copilot.backend.main
```

## Configuration

All settings come from environment variables. See `copilot/backend/settings.py`
for defaults.

| Var | Default | What |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | Wires the `anthropic` vendor. Optional if a local agent CLI is installed. |
| `OPENAI_API_KEY` | - | Wires the `openai` vendor (`gpt-5`, `gpt-5-codex`). |
| `PUFFIN_COPILOT_MODEL` | `claude-sonnet-4-6` | Default model for new threads. |
| `PUFFIN_COPILOT_MAX_TOKENS` | `8192` | Per-turn token cap. |
| `PUFFIN_COPILOT_MAX_TOOL_ITERS` | `10` | Loop safety bound. |
| `PUFFIN_COPILOT_HOST` / `PORT` | `127.0.0.1` / `8765` | Bind. |
| `PUFFIN_COPILOT_DB` | `artifacts/copilot/threads.sqlite3` | Thread store. |
| `PUFFIN_COPILOT_API_KEY` | - | If set, every request needs `Authorization: Bearer …`. |
| `PUFFIN_COPILOT_CORS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated origins. |
| `PUFFIN_COPILOT_ENABLE_DANGEROUS` | `false` | Gate on `train_start`, `config_edit`, `deploy_*`, etc. |
| `PUFFIN_COPILOT_FRONTEND_DIST` | - | Static-mount the frontend at `/`. |

## See also

- `copilot/ARCHITECTURE.md` - data flow, request lifecycle, persistence model.
- `copilot/TOOLS.md` - every tool, when Claude should call it, the return shape.
- `copilot/DEPLOYMENT.md` - single-binary deploy, reverse-proxy + TLS notes.
