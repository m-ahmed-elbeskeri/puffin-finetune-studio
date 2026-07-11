# Deployment

## Single-binary deploy (recommended)

Build the frontend statically and serve it from the FastAPI app so one
process answers everything.

```bash
# 1. Build the frontend
cd copilot/frontend
npm install --legacy-peer-deps
npm run build
cd ../..

# 2. Point the backend at the build output
export PUFFIN_COPILOT_FRONTEND_DIST=$PWD/copilot/frontend/.next/server/app
export ANTHROPIC_API_KEY=sk-ant-...
export PUFFIN_COPILOT_HOST=0.0.0.0
export PUFFIN_COPILOT_PORT=80
export PUFFIN_COPILOT_API_KEY=$(openssl rand -hex 32)    # any client must send this as Bearer

# 3. Run
python -m copilot.backend.main
```

Everything (chat, dashboard pages, API, SSE) is served from `:80`.

## With a reverse proxy

```nginx
# nginx — TLS termination + buffering tweaks for SSE
server {
    listen 443 ssl http2;
    server_name copilot.example.com;
    ssl_certificate     /etc/ssl/.../fullchain.pem;
    ssl_certificate_key /etc/ssl/.../privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For $remote_addr;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # SSE needs these:
        proxy_buffering           off;
        proxy_cache               off;
        proxy_read_timeout        24h;
        proxy_send_timeout        24h;
    }
}
```

Set `PUFFIN_COPILOT_CORS=https://copilot.example.com` so the browser allows
cross-origin requests from your hostname only.

## Auth model

If `PUFFIN_COPILOT_API_KEY` is set:

- Every `/api/*` and SSE request must carry `Authorization: Bearer <key>`.
- The frontend reads the key from `localStorage["puffin_copilot_api_key"]`
  (settable from `/settings`).
- `GET /healthz` is intentionally unauthenticated for load balancers.

There is no user model in v1 — one key, one workspace, one repo. Don't expose
the copilot to the public internet without TLS + an opaque API key.

## Containerised

```dockerfile
# Multi-stage: build frontend, then bake into the python image.
FROM node:22-alpine AS fe
WORKDIR /app/frontend
COPY copilot/frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY copilot/frontend ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY copilot/ ./copilot/
COPY ui/ ./ui/
RUN pip install --no-cache-dir -e ".[copilot,serve,eval,mlflow]"
COPY --from=fe /app/frontend/.next /app/copilot/frontend/.next

ENV PUFFIN_COPILOT_HOST=0.0.0.0
ENV PUFFIN_COPILOT_PORT=8000
ENV PUFFIN_COPILOT_FRONTEND_DIST=/app/copilot/frontend/.next/server/app
EXPOSE 8000

CMD ["python", "-m", "copilot.backend.main"]
```

## Health checks

| Endpoint | Use |
|---|---|
| `GET /healthz` | Liveness — no auth. Returns `{ok, version, provider_configured, tools[]}`. |
| `GET /api/state` | Readiness — needs auth. Returns 200 only if the repo is mounted and tools register. |

## Operational notes

- **Anthropic costs.** Every chat turn calls the Messages API; tool-use loops
  may consume several turns per user input. The `usage` SSE event surfaces
  cumulative input/output tokens — the frontend doesn't enforce a cap.
  Add a token budget per thread by intercepting in `loop.run_loop`.
- **Process management.** `train_start` spawns long-lived subprocesses. They
  outlive the request that started them. To survive a server restart, those
  PIDs are orphaned — `train_status` will continue to read their sidecar
  JSON files, but `train_cancel` may fail.
- **Concurrent threads.** Each `/api/chat` runs in its own asyncio task and
  uses its own SQLite connection. SQLite WAL mode is enabled. For dozens of
  concurrent users on the same DB, swap `aiosqlite` for Postgres in
  `ThreadStore` — the schema is portable.
- **Logs.** Structured JSON via `python-json-logger`. Set
  `PUFFIN_COPILOT_LOG_LEVEL=DEBUG` for tool-call traces.
