"""FastAPI application for Puffin Studio.

Endpoints (all JSON unless noted):

  GET  /healthz                       — liveness
  GET  /api/state                     — project_status + active run (snapshot)
  GET  /api/runs                      — list training runs (same shape as the tool)
  GET  /api/runs/{adapter_dir:path}   — one run detail
  GET  /api/registry                  — list registry models
  GET  /api/configs                   — list configs/profiles
  GET  /api/configs/{path:path}       — read one
  GET  /api/serving/health            — proxy to serve_health tool

  GET  /api/threads                   — list threads
  POST /api/threads                   — create thread
  GET  /api/threads/{id}              — thread + messages
  PATCH /api/threads/{id}             — rename
  DELETE /api/threads/{id}            — soft delete

  POST /api/chat                      — stream a turn (SSE)
       body: {thread_id, content: [...]}
       returns: text/event-stream with the loop envelope

  GET  /api/live/training (SSE)       — push the current training_state every
                                        2s. One stream the frontend can
                                        subscribe to from any page.

  GET  /api/train/studio              — recipes + knob schema + current values
  POST /api/train/preview             — materialized YAML, no write/launch
  POST /api/train/launch              — materialize config + start training
  POST /api/train/cancel              — stop a training run by PID

  GET  /api/tools                     — list registered tools (introspection)
  GET  /api/models                    — model/vendor catalog for the picker
  GET  /api/clis                      — agent-CLI doctor: installed / version /
                                        wired for claude, codex, gemini, qwen,
                                        opencode, cursor-agent, copilot
"""
from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import yaml
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from copilot.backend.logging import get_logger, setup_logging
from copilot.backend.loop import DEFAULT_SYSTEM_PROMPT, run_loop
from copilot.backend.projects import ProjectStore
from copilot.backend.providers import (
    AGENT_CLI_CATALOG,
    AVAILABLE_MODELS,
    AgentCliProvider,
    AnthropicProvider,
    ClaudeCodeProvider,
    CodexCliProvider,
    OpenAICodexProvider,
    Provider,
    ProviderHandle,
    choose_provider,
    probe_cli_version,
)
from copilot.backend.settings import Settings, get_settings
from copilot.backend.sse import encode_sse, to_sse
from copilot.backend.threads import ThreadStore
from copilot.backend.tools import ToolContext, registry

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# App factory — tests construct their own with overrides
# ---------------------------------------------------------------------------
def _build_provider_handles(
    s: Settings,
    *,
    overrides: dict[str, Provider] | None = None,
) -> dict[str, ProviderHandle]:
    """Wire up every provider for which we have credentials/CLI."""
    handles: dict[str, ProviderHandle] = {}
    if overrides:
        for vendor, prov in overrides.items():
            handles[vendor] = ProviderHandle(
                vendor=vendor, provider=prov,
                default_model="default",
            )
        return handles

    # Anthropic
    if s.anthropic_api_key:
        try:
            handles["anthropic"] = ProviderHandle(
                vendor="anthropic",
                provider=AnthropicProvider(s.anthropic_api_key),
                default_model="claude-sonnet-4-6",
            )
        except Exception as exc:
            log.warning("anthropic provider not loaded: %s", exc)

    # Claude Code (best-effort — the CLI may not be installed)
    try:
        handles["claude-code"] = ProviderHandle(
            vendor="claude-code",
            provider=ClaudeCodeProvider(
                repo_root=str(s.repo_root),
                enable_dangerous=s.enable_dangerous_tools,
            ),
            default_model="default",
        )
    except Exception as exc:
        log.info("claude-code provider not loaded: %s", exc)

    # Codex CLI (only register if the `codex` binary is on PATH)
    if CodexCliProvider.is_available():
        try:
            handles["codex-cli"] = ProviderHandle(
                vendor="codex-cli",
                provider=CodexCliProvider(
                    repo_root=str(s.repo_root),
                    enable_dangerous=s.enable_dangerous_tools,
                ),
                default_model="default",
            )
        except Exception as exc:
            log.info("codex-cli provider not loaded: %s", exc)

    # Other agent CLIs (Gemini, Qwen, OpenCode, Cursor, Copilot) — one
    # generic adapter, registered only when the binary is on PATH.
    for spec in AGENT_CLI_CATALOG:
        if not AgentCliProvider.is_available(spec):
            continue
        try:
            handles[spec.vendor] = ProviderHandle(
                vendor=spec.vendor,
                provider=AgentCliProvider(
                    spec,
                    repo_root=str(s.repo_root),
                    enable_dangerous=s.enable_dangerous_tools,
                ),
                default_model="default",
            )
        except Exception as exc:
            log.info("%s provider not loaded: %s", spec.vendor, exc)

    # OpenAI / Codex
    import os
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        try:
            handles["openai"] = ProviderHandle(
                vendor="openai",
                provider=OpenAICodexProvider(
                    openai_key, default_model="gpt-5-codex",
                ),
                default_model="gpt-5-codex",
            )
        except Exception as exc:
            log.warning("openai provider not loaded: %s", exc)

    return handles


async def _none() -> None:
    """Placeholder awaitable so gather() keeps positions for missing CLIs."""
    return None


def create_app(
    *,
    settings: Settings | None = None,
    provider: Provider | None = None,
    provider_handles: dict[str, Provider] | None = None,
    thread_store: ThreadStore | None = None,
) -> FastAPI:
    s = settings or get_settings()
    setup_logging(s.log_level)

    store = thread_store or ThreadStore(s.db_path)
    project_store = ProjectStore(s.db_path)
    # Back-compat: `provider=` (old single-provider arg) still works — it
    # becomes the anthropic handle.
    overrides: dict[str, Provider] | None = None
    if provider_handles is not None:
        overrides = dict(provider_handles)
    elif provider is not None:
        overrides = {"anthropic": provider}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await store.initialize()
        default_project = await project_store.initialize(default_path=s.repo_root)
        # Legacy threads (pre-project_id schema) get claimed by the default
        # project so they don't leak into newly-scaffolded projects.
        backfilled = await store.backfill_project_id(default_project.id)
        if backfilled:
            log = get_logger("copilot.threads")
            log.info(
                "backfilled %d legacy threads to default project %s",
                backfilled, default_project.id,
            )
        app.state.thread_store = store
        app.state.project_store = project_store
        app.state.settings = s
        app.state.provider_handles = _build_provider_handles(s, overrides=overrides)
        # Legacy attr — kept so old code paths (and tests) don't break.
        first_handle = next(iter(app.state.provider_handles.values()), None)
        app.state.provider = first_handle.provider if first_handle else None
        yield

    # When we serve the built frontend from this same process (single-origin
    # prod), FastAPI's default /docs, /redoc and /openapi.json would both
    # collide with the app's own /docs page and expose the API schema on
    # whatever host we bind. Disable them in that mode.
    serving_frontend = bool(s.frontend_dist and s.frontend_dist.exists())
    app = FastAPI(
        title="Puffin Studio", version="0.1.0", lifespan=lifespan,
        docs_url=None if serving_frontend else "/docs",
        redoc_url=None if serving_frontend else "/redoc",
        openapi_url=None if serving_frontend else "/openapi.json",
    )

    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(s.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ----- Auth dependency ----------------------------------------------
    async def require_auth(request: Request) -> None:
        if not s.api_key:
            return
        header = request.headers.get("authorization", "")
        if header == f"Bearer {s.api_key}":
            return
        raise HTTPException(status_code=401, detail="Bad or missing bearer token.")

    # ----- Health -------------------------------------------------------
    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        handles: dict[str, ProviderHandle] = getattr(
            app.state, "provider_handles", {}) or {}
        return {
            "ok": True,
            "version": "0.1.0",
            "provider_configured": bool(handles),
            "providers": sorted(handles.keys()),
            "tools": [t.name for t in registry.all()],
            "repo_root": str(s.repo_root),
            "dangerous_enabled": s.enable_dangerous_tools,
        }

    # ----- Models catalog (frontend picker) ----------------------------
    @app.get("/api/models", dependencies=[Depends(require_auth)])
    async def list_models() -> dict[str, Any]:
        handles: dict[str, ProviderHandle] = getattr(
            app.state, "provider_handles", {}) or {}
        wired = set(handles.keys())
        return {
            "default": "anthropic:claude-sonnet-4-6",
            "models": [
                {**m, "available": m["vendor"] in wired}
                for m in AVAILABLE_MODELS
            ],
        }

    # ----- Agent CLI doctor ----------------------------------------------
    # Which local agent CLIs (claude, codex, gemini, …) are installed, where,
    # and at what version. Results are cached per process; ?refresh=1 re-probes
    # (e.g. right after the user installs a CLI).
    _KNOWN_CLIS: list[dict[str, str]] = [
        {
            "vendor": "claude-code", "binary": "claude",
            "label": "Claude Code",
            "install_hint": "npm i -g @anthropic-ai/claude-code",
        },
        {
            "vendor": "codex-cli", "binary": "codex",
            "label": "Codex CLI",
            "install_hint": "npm i -g @openai/codex",
        },
        *(
            {
                "vendor": spec.vendor, "binary": spec.binary,
                "label": spec.label, "install_hint": spec.install_hint,
            }
            for spec in AGENT_CLI_CATALOG
        ),
    ]

    @app.get("/api/clis", dependencies=[Depends(require_auth)])
    async def list_clis(refresh: bool = Query(default=False)) -> dict[str, Any]:
        cache: dict[str, Any] | None = getattr(app.state, "cli_doctor_cache", None)
        if cache is not None and not refresh:
            return cache
        handles: dict[str, ProviderHandle] = getattr(
            app.state, "provider_handles", {}) or {}
        paths = [shutil.which(entry["binary"]) for entry in _KNOWN_CLIS]
        versions = await asyncio.gather(*(
            probe_cli_version(p) if p else _none() for p in paths
        ))
        clis = [
            {
                **entry,
                "installed": path is not None,
                "path": path,
                "version": version,
                "wired": entry["vendor"] in handles,
            }
            for entry, path, version in zip(_KNOWN_CLIS, paths, versions)
        ]
        result = {"clis": clis}
        app.state.cli_doctor_cache = result
        return result

    # ----- Tool introspection -------------------------------------------
    @app.get("/api/tools", dependencies=[Depends(require_auth)])
    async def list_tools() -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "dangerous": t.dangerous,
                    "args_schema": t.args_model.model_json_schema(),
                }
                for t in registry.all()
            ],
        }

    # ----- Direct tool wrappers (dashboard pages call these) ------------
    async def _ctx(project_id: str | None = None) -> ToolContext:
        """Build a ToolContext for the requested project (defaults to the
        first project, which was seeded from settings.repo_root)."""
        from pathlib import Path
        repo = s.repo_root
        if project_id:
            proj = await project_store.get_project(project_id)
            if proj is not None:
                repo = Path(proj.path)
        else:
            projects = await project_store.list_projects()
            if projects:
                repo = Path(projects[0].path)
        return ToolContext(
            repo_root=repo,
            enable_dangerous=s.enable_dangerous_tools,
        )

    # ----- Projects -----------------------------------------------------
    @app.get("/api/projects", dependencies=[Depends(require_auth)])
    async def list_projects() -> dict[str, Any]:
        return {"projects": [p.to_dict() for p in await project_store.list_projects()]}

    @app.post("/api/projects", dependencies=[Depends(require_auth)])
    async def create_project(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        name = str(body.get("name") or "").strip()
        path = str(body.get("path") or "").strip()
        if not name or not path:
            raise HTTPException(400, "name and path required")
        try:
            p = await project_store.create_project(name=name, path=path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"project": p.to_dict()}

    @app.post("/api/projects/scaffold", dependencies=[Depends(require_auth)])
    async def scaffold_project_endpoint(
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        """Materialise a fresh project folder from the platform template
        (configs/, profiles/, data_contracts/, eval_sets/, dataset_cards/,
        model_cards/, .env.example, empty data/raw/ + artifacts/) and
        register it in the picker. The folder must not already exist or
        must be empty — we never overwrite."""
        import pathlib

        from copilot.backend.scaffold import scaffold_project

        name = str(body.get("name") or "").strip()
        path = str(body.get("path") or "").strip()
        if not name or not path:
            raise HTTPException(400, "name and path required")
        try:
            result = scaffold_project(
                template_root=s.repo_root,
                target_path=pathlib.Path(path),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"scaffold failed: {exc}") from exc

        try:
            p = await project_store.create_project(
                name=name, path=result.target_path,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"project": p.to_dict(), "scaffold": result.to_dict()}

    @app.delete("/api/projects/{pid}", dependencies=[Depends(require_auth)])
    async def delete_project(pid: str) -> dict[str, Any]:
        await project_store.delete_project(pid)
        return {"deleted": True, "id": pid}

    @app.post("/api/picker/folder", dependencies=[Depends(require_auth)])
    async def pick_folder_endpoint(
        body: dict[str, Any] = Body(default={}),
    ) -> dict[str, Any]:
        """Open a native OS folder-picker dialog on the user's desktop
        and return the chosen absolute path. Backend must be running as
        the same user as the browser (i.e. the standard local-dev case).
        Returns `{"path": null}` if the user cancelled."""
        from copilot.backend.picker import pick_folder

        title = str(body.get("title") or "Pick project folder")
        initial = body.get("initial")
        try:
            path = await pick_folder(
                title=title,
                initial=str(initial) if initial else None,
            )
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"path": path}

    # All read endpoints take an optional ?project_id=... so the dashboard
    # can render data for any project the user has registered.
    PQ = Query(default=None, alias="project_id")

    def _assert_thread_project(thr: Any, project_id: str | None) -> None:
        if project_id and getattr(thr, "project_id", None) != project_id:
            raise HTTPException(status_code=404, detail="thread not found")

    @app.get("/api/state", dependencies=[Depends(require_auth)])
    async def get_state(project_id: str | None = PQ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        result = await registry.invoke("project_status", {}, ctx)
        active = await registry.invoke("train_status", {}, ctx)
        return {"status": result, "training": active}

    @app.get("/api/brief", dependencies=[Depends(require_auth)])
    async def get_brief(project_id: str | None = PQ) -> dict[str, Any]:
        """The project design brief (goal / audience / data / success / ...)."""
        from copilot.backend import brief_ops
        ctx = await _ctx(project_id)
        return brief_ops.read_brief(ctx.repo_root)

    @app.put("/api/brief", dependencies=[Depends(require_auth)])
    async def put_brief(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        from copilot.backend import brief_ops
        ctx = await _ctx(project_id)
        return await asyncio.to_thread(
            brief_ops.write_brief, ctx.repo_root, body.get("fields") or {})

    @app.get("/api/runs", dependencies=[Depends(require_auth)])
    async def get_runs(
        include_metrics: bool = Query(default=False),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        return await registry.invoke(
            "train_history", {"include_metrics": include_metrics},
            await _ctx(project_id))

    @app.get("/api/runs/{adapter_dir:path}", dependencies=[Depends(require_auth)])
    async def get_run(
        adapter_dir: str = Path(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        return await registry.invoke(
            "train_get_run", {"adapter_dir": adapter_dir}, await _ctx(project_id))

    # ----- Training Studio (the /train page) -----------------------------
    @app.get("/api/train/studio", dependencies=[Depends(require_auth)])
    async def get_train_studio(project_id: str | None = PQ) -> dict[str, Any]:
        """Recipes + knob schema + current base-config values + hardware."""
        from copilot.backend.tools.project import _gpu_summary
        from copilot.backend.training_studio import studio_catalog

        ctx = await _ctx(project_id)
        catalog = studio_catalog(ctx.repo_root)
        catalog["gpu"] = _gpu_summary()
        catalog["dangerous_enabled"] = s.enable_dangerous_tools
        return catalog

    @app.post("/api/train/preview", dependencies=[Depends(require_auth)])
    async def post_train_preview(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Materialize the config WITHOUT writing or launching — the review
        step of the wizard."""
        from copilot.backend.training_studio import StudioError, materialize

        ctx = await _ctx(project_id)
        try:
            rel, text = materialize(
                ctx.repo_root,
                method=str(body.get("method") or "sft").lower(),
                recipe_id=body.get("recipe") or None,
                overrides=body.get("overrides") or {},
                write=False,
            )
        except StudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"config_path": rel, "yaml": text}

    @app.post("/api/train/launch", dependencies=[Depends(require_auth)])
    async def post_train_launch(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Materialize the studio config, then launch through the existing
        train_start tool — same process management, sidecar metrics, and
        dangerous-tool gate as a chat-launched run."""
        from copilot.backend.training_studio import StudioError, materialize

        ctx = await _ctx(project_id)
        method = str(body.get("method") or "sft").lower()
        smoke = bool(body.get("smoke", True))
        try:
            rel, text = materialize(
                ctx.repo_root,
                method=method,
                recipe_id=body.get("recipe") or None,
                overrides=body.get("overrides") or {},
            )
        except StudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        result = await registry.invoke(
            "train_start", {"method": method, "smoke": smoke, "config": rel},
            ctx)
        return {"launch": result, "config_path": rel, "yaml": text}

    @app.post("/api/train/cancel", dependencies=[Depends(require_auth)])
    async def post_train_cancel(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        pid = body.get("pid")
        if not isinstance(pid, int):
            raise HTTPException(400, "pid (int) required")
        return await registry.invoke(
            "train_cancel", {"pid": pid}, await _ctx(project_id))

    @app.get("/api/train/log", dependencies=[Depends(require_auth)])
    async def get_train_log(
        adapter_dir: str = Query(...),
        tail: int = Query(default=300, ge=1, le=2000),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Tail a run's training log so failures are visible in-app."""
        from copilot.backend.tools.train import read_training_log
        ctx = await _ctx(project_id)
        try:
            return read_training_log(ctx.repo_root, adapter_dir, tail=tail)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/train/run-config", dependencies=[Depends(require_auth)])
    async def get_train_run_config(
        adapter_dir: str = Query(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """The exact config + data fingerprint a past run used (reproducibility)."""
        from copilot.backend.tools.train import read_run_config
        ctx = await _ctx(project_id)
        try:
            return read_run_config(ctx.repo_root, adapter_dir)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/train/preflight", dependencies=[Depends(require_auth)])
    async def post_train_preflight(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        from copilot.backend import train_ops
        ctx = await _ctx(project_id)
        return await asyncio.to_thread(
            train_ops.preflight, ctx.repo_root,
            method=body.get("method", "sft"),
            recipe_id=body.get("recipe") or None,
            overrides=body.get("overrides") or {},
            local=bool(body.get("local", True)))

    @app.post("/api/train/estimate", dependencies=[Depends(require_auth)])
    async def post_train_estimate(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        from copilot.backend import train_ops
        ctx = await _ctx(project_id)
        status = await registry.invoke("project_status", {}, ctx)
        gpu = (status.get("hardware", {}) or {}).get("gpu", {})
        return await asyncio.to_thread(
            train_ops.estimate, ctx.repo_root,
            method=body.get("method", "sft"),
            recipe_id=body.get("recipe") or None,
            overrides=body.get("overrides") or {}, gpu=gpu)

    @app.post("/api/train/materialize", dependencies=[Depends(require_auth)])
    async def post_train_materialize(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Write the studio config (configs/train_studio.yaml) from a recipe +
        overrides WITHOUT launching. Used to prep a config for a cloud submit."""
        from copilot.backend.training_studio import StudioError, materialize
        ctx = await _ctx(project_id)
        try:
            rel, text = materialize(
                ctx.repo_root, method=body.get("method", "sft"),
                recipe_id=body.get("recipe") or None,
                overrides=body.get("overrides") or {}, write=True)
        except StudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"config_path": rel, "yaml": text}

    @app.post("/api/train/recipes", dependencies=[Depends(require_auth)])
    async def post_save_recipe(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Save the current settings as a named custom recipe."""
        from copilot.backend.training_studio import StudioError, save_custom_recipe
        ctx = await _ctx(project_id)
        try:
            recipe = save_custom_recipe(
                ctx.repo_root,
                name=str(body.get("name") or ""),
                method=str(body.get("method") or "sft"),
                overrides=body.get("overrides") or {},
                description=str(body.get("description") or ""))
        except StudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"recipe": recipe}

    @app.delete("/api/train/recipes/{recipe_id}",
                dependencies=[Depends(require_auth)])
    async def delete_recipe(
        recipe_id: str, project_id: str | None = PQ,
    ) -> dict[str, Any]:
        from copilot.backend.training_studio import delete_custom_recipe
        ctx = await _ctx(project_id)
        return {"deleted": delete_custom_recipe(ctx.repo_root, recipe_id)}

    @app.get("/api/registry", dependencies=[Depends(require_auth)])
    async def get_registry(project_id: str | None = PQ) -> dict[str, Any]:
        return await registry.invoke("registry_list", {}, await _ctx(project_id))

    @app.get("/api/deploy/config", dependencies=[Depends(require_auth)])
    async def get_deploy_config(project_id: str | None = PQ) -> dict[str, Any]:
        """Default model name + alias from configs/deploy.yaml for the push form."""
        ctx = await _ctx(project_id)
        p = ctx.repo_root / "configs" / "deploy.yaml"
        name, alias = "my-model", "staging"
        if p.exists():
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                model = raw.get("model", {}) if isinstance(raw, dict) else {}
                name = model.get("name") or name
                alias = model.get("alias") or alias
            except yaml.YAMLError:
                pass
        return {"kind": "deploy_config", "name": name, "default_alias": alias}

    @app.post("/api/deploy/push", dependencies=[Depends(require_auth)])
    async def post_deploy_push(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Push the adapter to the local registry (dangerous-gated)."""
        ctx = await _ctx(project_id)
        args: dict[str, Any] = {"name": body.get("name") or "my-model"}
        if body.get("alias"):
            args["alias"] = body["alias"]
        if body.get("adapter_dir"):
            args["adapter_dir"] = body["adapter_dir"]
        return await registry.invoke("deploy_push", args, ctx)

    @app.post("/api/deploy/promote", dependencies=[Depends(require_auth)])
    async def post_deploy_promote(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Move an alias pointer to a version (dangerous-gated)."""
        ctx = await _ctx(project_id)
        return await registry.invoke("deploy_promote", {
            "name": body.get("name") or "my-model",
            "version": str(body.get("version") or ""),
            "alias": body.get("alias") or "staging",
        }, ctx)

    @app.get("/api/configs", dependencies=[Depends(require_auth)])
    async def get_configs(project_id: str | None = PQ) -> dict[str, Any]:
        return await registry.invoke("config_list", {}, await _ctx(project_id))

    @app.get("/api/configs/{config_path:path}", dependencies=[Depends(require_auth)])
    async def get_config(
        config_path: str = Path(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        return await registry.invoke(
            "config_read", {"path": config_path}, await _ctx(project_id))

    @app.get("/api/serving/health", dependencies=[Depends(require_auth)])
    async def get_serving_health(
        url: str = Query(default="http://127.0.0.1:8089"),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        return await registry.invoke(
            "serve_health", {"url": url}, await _ctx(project_id))

    @app.get("/api/serving/status", dependencies=[Depends(require_auth)])
    async def get_serving_status(project_id: str | None = PQ) -> dict[str, Any]:
        """Whether the UI-managed serving process is running (pid/port/backend)."""
        from copilot.backend import serving_ops
        ctx = await _ctx(project_id)
        return serving_ops.read_state(ctx.repo_root)

    @app.post("/api/serving/start", dependencies=[Depends(require_auth)])
    async def post_serving_start(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Launch the serving app (spawns a subprocess; dangerous-gated)."""
        if not s.enable_dangerous_tools:
            raise HTTPException(
                403, "Serving is locked. Set PUFFIN_COPILOT_ENABLE_DANGEROUS=1 "
                "and restart the backend to serve from the UI.")
        from copilot.backend import serving_ops
        ctx = await _ctx(project_id)
        try:
            return await serving_ops.start(
                ctx.repo_root,
                backend=str(body.get("backend") or "transformers"),
                port=int(body.get("port") or serving_ops.DEFAULT_PORT))
        except serving_ops.ServingError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/serving/stop", dependencies=[Depends(require_auth)])
    async def post_serving_stop(project_id: str | None = PQ) -> dict[str, Any]:
        """Stop the UI-managed serving process (dangerous-gated)."""
        if not s.enable_dangerous_tools:
            raise HTTPException(403, "Serving control is locked.")
        from copilot.backend import serving_ops
        ctx = await _ctx(project_id)
        return await asyncio.to_thread(serving_ops.stop, ctx.repo_root)

    @app.get("/api/serving/log", dependencies=[Depends(require_auth)])
    async def get_serving_log(
        tail: int = Query(default=400, ge=1, le=2000),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Tail the serving process log (model-load progress + errors)."""
        from copilot.backend import serving_ops
        ctx = await _ctx(project_id)
        return serving_ops.read_log(ctx.repo_root, tail=tail)

    @app.post("/api/deploy/k8s", dependencies=[Depends(require_auth)])
    async def post_deploy_k8s(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Render the Kubernetes manifest (deployment + service + HPA)."""
        ctx = await _ctx(project_id)
        args = {k: body[k] for k in
                ("environment", "replicas", "gpu", "namespace",
                 "model_ref", "serving_image") if k in body}
        return await registry.invoke("deploy_render_k8s", args, ctx)

    @app.get("/api/deploy/targets", dependencies=[Depends(require_auth)])
    async def get_deploy_targets(project_id: str | None = PQ) -> dict[str, Any]:
        """Per-target readiness: which deploy CLIs are installed + infra present."""
        from copilot.backend import deploy_ops
        ctx = await _ctx(project_id)
        return deploy_ops.preflight(ctx.repo_root)

    @app.get("/api/deploy/status", dependencies=[Depends(require_auth)])
    async def get_deploy_status(project_id: str | None = PQ) -> dict[str, Any]:
        from copilot.backend import deploy_ops
        ctx = await _ctx(project_id)
        return deploy_ops.read_state(ctx.repo_root)

    @app.get("/api/deploy/log", dependencies=[Depends(require_auth)])
    async def get_deploy_log(
        tail: int = Query(default=400, ge=1, le=2000),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        from copilot.backend import deploy_ops
        ctx = await _ctx(project_id)
        return deploy_ops.read_log(ctx.repo_root, tail=tail)

    @app.post("/api/deploy/run", dependencies=[Depends(require_auth)])
    async def post_deploy_run(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Execute a deployment target (spawns the deploy command; dangerous-gated)."""
        if not s.enable_dangerous_tools:
            raise HTTPException(
                403, "Deploying is locked. Set PUFFIN_COPILOT_ENABLE_DANGEROUS=1 "
                "and restart the backend to deploy from the UI.")
        from copilot.backend import deploy_ops
        ctx = await _ctx(project_id)
        try:
            return await deploy_ops.run(
                ctx.repo_root, target=str(body.get("target") or ""),
                settings=body.get("settings") or {})
        except deploy_ops.DeployError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/deploy/cancel", dependencies=[Depends(require_auth)])
    async def post_deploy_cancel(project_id: str | None = PQ) -> dict[str, Any]:
        if not s.enable_dangerous_tools:
            raise HTTPException(403, "Deploy control is locked.")
        from copilot.backend import deploy_ops
        ctx = await _ctx(project_id)
        return await asyncio.to_thread(deploy_ops.cancel, ctx.repo_root)

    @app.post("/api/serving/chat", dependencies=[Depends(require_auth)])
    async def post_serving_chat(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Proxy a chat completion to the serving app (server-side, so the
        browser never hits :8089 directly and there's no CORS). Accepts either a
        single `prompt` (+ optional `system`) or a full `messages` array for a
        multi-turn conversation."""
        await _ctx(project_id)
        url = str(body.get("url") or "http://127.0.0.1:8089").rstrip("/")
        temperature = float(body.get("temperature", 0.7))
        max_tokens = int(body.get("max_tokens", 256))
        msgs = body.get("messages")
        if not (isinstance(msgs, list) and msgs):
            # Single-turn: build system + user.
            msgs = []
            if body.get("system"):
                msgs.append({"role": "system", "content": str(body["system"])})
            msgs.append({"role": "user", "content": str(body.get("prompt") or "")})

        import time
        import uuid

        import httpx
        payload: dict[str, Any] = {
            "model": "puffin-playground", "messages": msgs,
            "temperature": temperature, "max_tokens": max_tokens,
        }
        if body.get("require_json"):
            payload["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(
                    f"{url}/v1/chat/completions", json=payload,
                    headers={"x-request-id": f"req_{uuid.uuid4().hex[:24]}"})
        except (httpx.HTTPError, OSError) as exc:
            return {"kind": "error", "message": f"serving request failed: {exc}"}
        if r.status_code != 200:
            return {"kind": "error", "message": f"HTTP {r.status_code}: {r.text[:400]}"}
        data = r.json()
        meta = data.get("puffin_metadata", {}) or {}
        return {
            "kind": "serve_chat_result",
            "text": data["choices"][0]["message"]["content"],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "usage": data.get("usage", {}), "metadata": meta,
            "request_id": meta.get("request_id", "-"),
            "model": "puffin-playground",
        }

    @app.get("/api/monitor/requests", dependencies=[Depends(require_auth)])
    async def get_monitor_requests(
        n: int = Query(default=25, ge=1, le=500),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        return await registry.invoke(
            "monitor_request_log", {"n": n}, await _ctx(project_id))

    @app.get("/api/monitor/quality", dependencies=[Depends(require_auth)])
    async def get_monitor_quality(project_id: str | None = PQ) -> dict[str, Any]:
        return await registry.invoke("monitor_quality", {}, await _ctx(project_id))

    @app.get("/api/monitor/drift", dependencies=[Depends(require_auth)])
    async def get_monitor_drift(project_id: str | None = PQ) -> dict[str, Any]:
        return await registry.invoke("monitor_drift", {}, await _ctx(project_id))

    @app.get("/api/eval/metrics", dependencies=[Depends(require_auth)])
    async def get_eval_metrics(project_id: str | None = PQ) -> dict[str, Any]:
        return await registry.invoke("eval_get_metrics", {}, await _ctx(project_id))

    @app.post("/api/eval/run", dependencies=[Depends(require_auth)])
    async def post_eval_run(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Run eval modules against the latest adapter (dangerous-gated)."""
        args: dict[str, Any] = {}
        if body.get("modules"):
            args["modules"] = body["modules"]
        if body.get("backend"):
            args["backend"] = body["backend"]
        return await registry.invoke("eval_run", args, await _ctx(project_id))

    @app.post("/api/eval/gate", dependencies=[Depends(require_auth)])
    async def post_eval_gate(project_id: str | None = PQ) -> dict[str, Any]:
        """Apply the promotion gate to the latest metrics (dangerous-gated)."""
        return await registry.invoke("gate_apply", {}, await _ctx(project_id))

    @app.get("/api/eval/gate", dependencies=[Depends(require_auth)])
    async def get_eval_gate(project_id: str | None = PQ) -> dict[str, Any]:
        """Read the last gate report without re-running."""
        ctx = await _ctx(project_id)
        p = ctx.repo_root / "artifacts" / "eval" / "gate_report.json"
        if not p.exists():
            return {"kind": "gate_report", "present": False}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"kind": "gate_report", "present": False}
        return {"kind": "gate_report", "present": True, **data}

    @app.get("/api/eval/config", dependencies=[Depends(require_auth)])
    async def get_eval_config(project_id: str | None = PQ) -> dict[str, Any]:
        """Gate thresholds + eval settings, so the studio can explain the gate."""
        ctx = await _ctx(project_id)
        p = ctx.repo_root / "configs" / "eval.yaml"
        gates: dict[str, Any] = {}
        settings: dict[str, Any] = {}
        if p.exists():
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                ev = raw.get("eval", {}) if isinstance(raw, dict) else {}
                gates = raw.get("gates", {}) if isinstance(raw, dict) else {}
                settings = {k: ev.get(k) for k in
                            ("backend", "model_id", "adapter_path", "max_new_tokens")}
            except yaml.YAMLError:
                pass
        return {"kind": "eval_config", "gates": gates, "settings": settings}

    @app.put("/api/eval/config", dependencies=[Depends(require_auth)])
    async def put_eval_config(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Edit the promotion-gate thresholds (configs/eval.yaml gates block)."""
        from copilot.backend import eval_authoring
        ctx = await _ctx(project_id)
        try:
            gates = await asyncio.to_thread(
                eval_authoring.update_gates, ctx.repo_root, body.get("gates") or {})
        except eval_authoring.EvalAuthoringError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"kind": "eval_config", "gates": gates}

    # ----- Data upload / paste / delete --------------------------------
    @app.get("/api/data/files", dependencies=[Depends(require_auth)])
    async def list_data_files(project_id: str | None = PQ) -> dict[str, Any]:
        """Browser-facing listing of every dataset file under the project."""
        return await registry.invoke("dataset_list", {}, await _ctx(project_id))

    @app.get("/api/data/audit", dependencies=[Depends(require_auth)])
    async def audit_data_file(
        path: str = Query(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Inline dataset audit for the Data page (same payload the chat
        tool produces, rendered by the same card)."""
        return await registry.invoke(
            "dataset_audit", {"path": path}, await _ctx(project_id))

    @app.get("/api/data/preview", dependencies=[Depends(require_auth)])
    async def preview_data_file(
        path: str = Query(...),
        n: int = Query(default=5, ge=1, le=20),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        return await registry.invoke(
            "dataset_preview", {"path": path, "n": n}, await _ctx(project_id))

    @app.post("/api/data/pipeline", dependencies=[Depends(require_auth)])
    async def run_data_pipeline(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Run the core data pipeline: ingest → validate → split → dataset
        card. Redaction and dedupe are NOT built into this flow — they're
        editable script templates the user runs on raw data first (see
        data/transforms/). Advanced callers may still opt into the built-in
        stages by passing redact_pii=true / dedupe=true. Gated by the same
        dangerous-tools flag as every other state-mutating tool."""
        def _flag(key: str) -> bool:
            v = body.get(key, False)
            return bool(v) if isinstance(v, bool) else str(v).lower() == "true"

        stages = ["ingest", "validate"]
        if _flag("redact_pii"):
            stages.append("redact_pii")
        if _flag("dedupe"):
            stages.append("dedupe")
        stages += ["split", "build_dataset_card"]
        return await registry.invoke(
            "data_pipeline_run", {"stages": stages}, await _ctx(project_id))

    # ----- Record-level editing (view / add / edit / delete rows) -------
    from copilot.backend import data_records as _records

    @app.get("/api/data/records", dependencies=[Depends(require_auth)])
    async def get_records(
        path: str = Query(...),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=200),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _records.read_records(ctx.repo_root, path, offset=offset, limit=limit)
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {path}") from None
        except _records.RecordError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/data/records", dependencies=[Depends(require_auth)])
    async def add_record(
        path: str = Query(...),
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _records.append_record(ctx.repo_root, path, body.get("record"))
        except _records.RecordError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/data/records", dependencies=[Depends(require_auth)])
    async def edit_record(
        path: str = Query(...),
        index: int = Query(..., ge=0),
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _records.update_record(ctx.repo_root, path, index, body.get("record"))
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {path}") from None
        except _records.RecordError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/data/records", dependencies=[Depends(require_auth)])
    async def remove_record(
        path: str = Query(...),
        index: int = Query(..., ge=0),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _records.delete_record(ctx.repo_root, path, index)
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {path}") from None
        except _records.RecordError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ----- Data inspection (read-only analyses) -------------------------
    from copilot.backend import data_inspect as _inspect

    @app.get("/api/data/inspect/tokens", dependencies=[Depends(require_auth)])
    async def inspect_tokens(
        path: str = Query(...), project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return await asyncio.to_thread(_inspect.analyze_tokens, ctx.repo_root, path)
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {path}") from None
        except _inspect.InspectError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/data/inspect/template", dependencies=[Depends(require_auth)])
    async def inspect_template(
        path: str = Query(...),
        index: int = Query(default=0, ge=0),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return await asyncio.to_thread(
                _inspect.template_preview, ctx.repo_root, path, index=index)
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {path}") from None
        except _inspect.InspectError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/data/inspect/quality", dependencies=[Depends(require_auth)])
    async def inspect_quality(
        path: str = Query(...), project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return await asyncio.to_thread(
                _inspect.analyze_quality, ctx.repo_root, path)
        except FileNotFoundError:
            raise HTTPException(404, f"no such file: {path}") from None
        except _inspect.InspectError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/data/inspect/leakage", dependencies=[Depends(require_auth)])
    async def inspect_leakage(project_id: str | None = PQ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        return await asyncio.to_thread(_inspect.analyze_leakage, ctx.repo_root)

    @app.get("/api/data/inspect/fingerprint", dependencies=[Depends(require_auth)])
    async def inspect_fingerprint(project_id: str | None = PQ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        return await asyncio.to_thread(_inspect.dataset_fingerprint, ctx.repo_root)

    # ----- Split ratios (surgical edit of configs/data.yaml) ------------
    from copilot.backend import data_authoring as _authoring

    @app.get("/api/data/split", dependencies=[Depends(require_auth)])
    async def get_split(project_id: str | None = PQ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _authoring.read_split(ctx.repo_root)
        except _authoring.AuthoringError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/data/split", dependencies=[Depends(require_auth)])
    async def put_split(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _authoring.update_split(ctx.repo_root, body)
        except _authoring.AuthoringError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ----- Eval sets (author / append / clear cases) --------------------
    @app.put("/api/data/eval/{name}", dependencies=[Depends(require_auth)])
    async def put_eval_set(
        name: str,
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Replace (or append with mode='append') JSONL cases in an eval set.
        An empty replace clears the file — how the UI drops demo cases."""
        ctx = await _ctx(project_id)
        mode = str(body.get("mode") or "replace")
        try:
            return _authoring.write_eval_set(
                ctx.repo_root, name, str(body.get("content") or ""), mode=mode)
        except _authoring.AuthoringError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/data/upload", dependencies=[Depends(require_auth)])
    async def upload_data_files(
        files: list[UploadFile] = File(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Accept one or more JSONL uploads and drop them into
        <project>/data/raw/. Files must end in .jsonl and parse line-by-line.
        Records that fail to parse are counted; the file is still saved."""
        import pathlib as _pl

        ctx = await _ctx(project_id)
        raw_dir = _pl.Path(ctx.repo_root) / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for uf in files:
            name = _pl.Path(uf.filename or "").name  # strip any path
            if not name:
                skipped.append({"filename": str(uf.filename), "reason": "empty name"})
                continue
            if not name.lower().endswith(".jsonl"):
                skipped.append({"filename": name, "reason": "not .jsonl"})
                continue
            dst = (raw_dir / name).resolve()
            if not str(dst).startswith(str(raw_dir.resolve())):
                skipped.append({"filename": name, "reason": "path traversal"})
                continue
            blob = await uf.read()
            dst.write_bytes(blob)
            # Cheap line-by-line parse check.
            ok = 0
            bad = 0
            for line in blob.splitlines():
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                    ok += 1
                except json.JSONDecodeError:
                    bad += 1
            imported.append({
                "path": str(dst.relative_to(ctx.repo_root)).replace("\\", "/"),
                "size_bytes": len(blob),
                "valid_records": ok,
                "invalid_records": bad,
            })
        return {"imported": imported, "skipped": skipped}

    @app.post("/api/data/paste", dependencies=[Depends(require_auth)])
    async def paste_data_file(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Same as upload but takes a JSONL blob in the request body.
        Body: {filename: 'foo.jsonl', content: '<jsonl>'}"""
        import pathlib as _pl

        filename = str(body.get("filename") or "").strip()
        content = str(body.get("content") or "")
        if not filename or not filename.lower().endswith(".jsonl"):
            raise HTTPException(400, "filename ending in .jsonl required")
        if not content.strip():
            raise HTTPException(400, "content cannot be empty")

        ctx = await _ctx(project_id)
        raw_dir = _pl.Path(ctx.repo_root) / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        dst = (raw_dir / _pl.Path(filename).name).resolve()
        if not str(dst).startswith(str(raw_dir.resolve())):
            raise HTTPException(400, "path traversal blocked")
        dst.write_text(content, encoding="utf-8")
        ok = 0
        bad = 0
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
                ok += 1
            except json.JSONDecodeError:
                bad += 1
        return {
            "path": str(dst.relative_to(ctx.repo_root)).replace("\\", "/"),
            "size_bytes": dst.stat().st_size,
            "valid_records": ok,
            "invalid_records": bad,
        }

    @app.post("/api/data/import_hf", dependencies=[Depends(require_auth)])
    async def import_huggingface(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Wrapper over the dataset_import_hf tool so the /data page can
        kick off an import without going through chat."""
        ctx = await _ctx(project_id)
        result = await registry.invoke("dataset_import_hf", body, ctx)
        if result.get("kind") == "error":
            raise HTTPException(400, result.get("message") or "import failed")
        return result

    @app.delete("/api/data/files", dependencies=[Depends(require_auth)])
    async def delete_data_file(
        path: str = Query(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Delete a JSONL file under data/raw/. Refuses anything outside."""
        import pathlib as _pl

        ctx = await _ctx(project_id)
        raw_dir = (_pl.Path(ctx.repo_root) / "data" / "raw").resolve()
        target = (_pl.Path(ctx.repo_root) / path).resolve()
        if not str(target).startswith(str(raw_dir)):
            raise HTTPException(400, "only files under data/raw/ can be deleted")
        if not target.exists():
            raise HTTPException(404, "file not found")
        target.unlink()
        return {"deleted": True, "path": path}

    # ----- Custom pipeline transform scripts ----------------------------
    # Saved under <project>/data/transforms/. Saving/editing is plain file
    # management (ungated, path-jailed like upload/paste); *execution* is
    # gated by the same dangerous flag as the pipeline itself.
    from copilot.backend import transforms as _tf

    _ENABLE_HINT = (
        "Script execution is locked. Set PUFFIN_COPILOT_ENABLE_DANGEROUS=1 "
        "and restart the backend to unlock pipeline + transform runs."
    )

    @app.get("/api/capabilities", dependencies=[Depends(require_auth)])
    async def get_capabilities() -> dict[str, Any]:
        """Feature flags the frontend uses to render locked states upfront."""
        return {"dangerous_enabled": s.enable_dangerous_tools}

    # ----- Environment doctor (which deps are installed; install missing) --
    from copilot.backend import environment as _env

    @app.get("/api/environment", dependencies=[Depends(require_auth)])
    async def get_environment() -> dict[str, Any]:
        return await asyncio.to_thread(_env.check_environment)

    @app.post("/api/environment/install", dependencies=[Depends(require_auth)])
    async def install_environment(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> StreamingResponse:
        """Install a capability group's pip extra, streaming pip output as SSE."""
        if not s.enable_dangerous_tools:
            raise HTTPException(
                403,
                "Installing packages is locked. Set "
                "PUFFIN_COPILOT_ENABLE_DANGEROUS=1 and restart the backend, or "
                "run the shown command in your terminal.",
            )
        group = str(body.get("group") or "").strip()
        if not group:
            raise HTTPException(400, "group required")

        async def gen() -> AsyncIterator[bytes]:
            try:
                async for event, line in _env.stream_install(group):
                    yield encode_sse(event, {"line": line})
            except asyncio.CancelledError:
                return
            except Exception as exc:
                yield encode_sse("error", {"line": f"{type(exc).__name__}: {exc}"})

        return StreamingResponse(
            gen(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform",
                     "X-Accel-Buffering": "no"},
        )

    @app.get("/api/data/transforms", dependencies=[Depends(require_auth)])
    async def list_transform_scripts(project_id: str | None = PQ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        return {"transforms": _tf.list_transforms(ctx.repo_root)}

    @app.put("/api/data/transforms-order", dependencies=[Depends(require_auth)])
    async def save_transform_order(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Persist the order scripts run in (drag-to-reorder in the UI)."""
        ctx = await _ctx(project_id)
        order = body.get("order")
        if not isinstance(order, list):
            raise HTTPException(400, "order must be a list of script names")
        return {"order": _tf.write_order(ctx.repo_root, order)}

    @app.post("/api/data/transforms-run-chain",
              dependencies=[Depends(require_auth)])
    async def run_transform_chain(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Run several scripts in order, piping each output into the next."""
        ctx = await _ctx(project_id)
        if not ctx.enable_dangerous:
            raise HTTPException(403, _ENABLE_HINT)
        input_rel = str(body.get("input") or "").strip()
        if not input_rel:
            raise HTTPException(400, "input (repo-relative .jsonl path) required")
        steps = body.get("steps")
        if steps is None:
            steps = _tf.read_order(ctx.repo_root) or [
                t["name"] for t in _tf.list_transforms(ctx.repo_root)]
        if not isinstance(steps, list) or not steps:
            raise HTTPException(400, "no scripts to run")
        output_rel = str(body.get("output") or "").strip() or None
        try:
            return await _tf.run_chain(
                ctx.repo_root, [str(s) for s in steps], input_rel, output_rel)
        except FileNotFoundError as exc:
            raise HTTPException(404, f"not found: {exc}") from None
        except _tf.TransformError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/data/transforms/{name}", dependencies=[Depends(require_auth)])
    async def read_transform_script(
        name: str, project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _tf.read_transform(ctx.repo_root, name)
        except FileNotFoundError:
            raise HTTPException(404, f"no such script: {name}") from None
        except _tf.TransformError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/data/transforms/{name}", dependencies=[Depends(require_auth)])
    async def save_transform_script(
        name: str,
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            return _tf.save_transform(
                ctx.repo_root, name, str(body.get("content") or ""))
        except _tf.TransformError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/data/transforms/{name}", dependencies=[Depends(require_auth)])
    async def delete_transform_script(
        name: str, project_id: str | None = PQ,
    ) -> dict[str, Any]:
        ctx = await _ctx(project_id)
        try:
            _tf.delete_transform(ctx.repo_root, name)
        except FileNotFoundError:
            raise HTTPException(404, f"no such script: {name}") from None
        except _tf.TransformError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"deleted": True, "name": name}

    @app.post("/api/data/transforms/{name}/run",
              dependencies=[Depends(require_auth)])
    async def run_transform_script(
        name: str,
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Run a saved transform: python <script> --input <in> --output <out>."""
        ctx = await _ctx(project_id)
        if not ctx.enable_dangerous:
            raise HTTPException(403, _ENABLE_HINT)
        input_rel = str(body.get("input") or "").strip()
        if not input_rel:
            raise HTTPException(400, "input (repo-relative .jsonl path) required")
        output_rel = str(body.get("output") or "").strip() or None
        try:
            return await _tf.run_transform(
                ctx.repo_root, name, input_rel, output_rel)
        except FileNotFoundError as exc:
            raise HTTPException(404, f"not found: {exc}") from None
        except _tf.TransformError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ----- Threads ------------------------------------------------------
    @app.get("/api/threads", dependencies=[Depends(require_auth)])
    async def list_threads(
        limit: int = Query(default=100, ge=1, le=1000),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        rows = await store.list_threads(limit=limit, project_id=project_id)
        return {"threads": [t.to_dict() for t in rows]}

    @app.post("/api/threads", dependencies=[Depends(require_auth)])
    async def create_thread(
        body: dict[str, Any] = Body(default={}),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        title = (body.get("title") or "New conversation").strip() or "New conversation"
        model = body.get("model") or s.default_model
        # Body wins over query param so the explicit create_thread({project_id})
        # path still works for tests; fall back to ?project_id=... otherwise.
        pid = body.get("project_id") or project_id
        thr = await store.create_thread(
            title=title, model=model, project_id=pid,
        )
        return {"thread": thr.to_dict()}

    @app.get("/api/threads/{thread_id}", dependencies=[Depends(require_auth)])
    async def get_thread(
        thread_id: str,
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        thr = await store.get_thread(thread_id)
        if thr is None:
            raise HTTPException(status_code=404, detail="thread not found")
        _assert_thread_project(thr, project_id)
        msgs = await store.list_messages(thread_id)
        return {"thread": thr.to_dict(),
                "messages": [m.to_dict() for m in msgs]}

    @app.patch("/api/threads/{thread_id}", dependencies=[Depends(require_auth)])
    async def patch_thread(
        thread_id: str,
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        thr = await store.get_thread(thread_id)
        if thr is None:
            raise HTTPException(status_code=404, detail="thread not found")
        _assert_thread_project(thr, project_id)
        if "title" in body:
            title = str(body["title"]).strip()
            if not title:
                raise HTTPException(status_code=400,
                                    detail="title must be non-empty")
            await store.rename_thread(thread_id, title)
        if "model" in body:
            model = str(body["model"]).strip()
            if not model:
                raise HTTPException(status_code=400,
                                    detail="model must be non-empty")
            await store.set_model(thread_id, model)
        thr = await store.get_thread(thread_id)
        if thr is None:
            raise HTTPException(status_code=404, detail="thread not found")
        return {"thread": thr.to_dict()}

    @app.post("/api/threads/{thread_id}/truncate",
              dependencies=[Depends(require_auth)])
    async def truncate_thread(
        thread_id: str,
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        """Rewind a conversation: drop stored messages with idx >= from_idx.

        Regenerate = truncate at the last user message, then re-send it.
        Edit-and-resend = truncate at the edited message, then send new text.
        """
        thr = await store.get_thread(thread_id)
        if thr is None:
            raise HTTPException(status_code=404, detail="thread not found")
        _assert_thread_project(thr, project_id)
        from_idx = body.get("from_idx")
        if not isinstance(from_idx, int) or isinstance(from_idx, bool) or from_idx < 0:
            raise HTTPException(status_code=400,
                                detail="from_idx must be a non-negative integer")
        deleted = await store.truncate_messages(thread_id, from_idx)
        return {"deleted": deleted, "thread_id": thread_id}

    @app.delete("/api/threads/{thread_id}", dependencies=[Depends(require_auth)])
    async def delete_thread(
        thread_id: str,
        project_id: str | None = PQ,
    ) -> dict[str, Any]:
        thr = await store.get_thread(thread_id)
        if thr is None:
            raise HTTPException(status_code=404, detail="thread not found")
        _assert_thread_project(thr, project_id)
        await store.delete_thread(thread_id)
        return {"deleted": True, "thread_id": thread_id}

    # ----- Chat (SSE stream) --------------------------------------------
    @app.post("/api/chat", dependencies=[Depends(require_auth)])
    async def chat(
        body: dict[str, Any] = Body(...),
        project_id: str | None = PQ,
    ) -> StreamingResponse:
        thread_id = body.get("thread_id")
        content = body.get("content")
        if not thread_id or not isinstance(content, list) or not content:
            raise HTTPException(status_code=400,
                                detail="thread_id + non-empty content list required")
        thr = await store.get_thread(thread_id)
        if thr is None:
            raise HTTPException(status_code=404, detail="thread not found")
        _assert_thread_project(thr, project_id)

        handles = getattr(app.state, "provider_handles", {}) or {}
        if not handles:
            raise HTTPException(
                status_code=500,
                detail=(
                    "No providers configured. Set ANTHROPIC_API_KEY, "
                    "OPENAI_API_KEY, or install the claude CLI."
                ),
            )
        try:
            handle, resolved_model = choose_provider(thr.model, handles)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        prov = handle.provider

        # Optional per-surface specialization (e.g. the AI side panel tells
        # the model which page the user is on). Appended to — never replaces
        # — the platform system prompt.
        system_prompt = DEFAULT_SYSTEM_PROMPT
        system_extra = body.get("system_extra")
        if isinstance(system_extra, str) and system_extra.strip():
            system_prompt = (
                f"{DEFAULT_SYSTEM_PROMPT}\n\n"
                f"# Current workspace context\n{system_extra.strip()[:4000]}"
            )

        # Always give the model the project brief (goal, audience, data, ...) so
        # it works toward the same intent on every page.
        try:
            from copilot.backend import brief_ops
            _brief = brief_ops.brief_summary((await _ctx(thr.project_id)).repo_root)
            if _brief:
                system_prompt = f"{system_prompt}\n\n# {_brief[:2000]}"
        except Exception:
            pass

        # Persist the user message first.
        await store.append_message(thread_id, role="user", content=content)
        history = await store.to_anthropic_messages(thread_id)

        async def stream() -> AsyncIterator[bytes]:
            ctx = await _ctx(thr.project_id)
            # Snapshot the messages list so we can re-read after the loop.
            messages = list(history)
            try:
                async for chunk in to_sse(run_loop(
                    provider=prov, model=resolved_model,
                    system=system_prompt,
                    messages=messages, tool_ctx=ctx,
                    max_tokens=s.max_tokens,
                    max_iterations=s.max_tool_iterations,
                )):
                    yield chunk
            except asyncio.CancelledError:  # client disconnected
                return
            except Exception as exc:
                log.exception("chat stream failed")
                yield encode_sse("error", {"message": f"{type(exc).__name__}: {exc}"})
            finally:
                # Persist everything the loop produced beyond the user message.
                # `messages` was mutated in place; the new tail is what we keep.
                tail = messages[len(history):]
                for m in tail:
                    if isinstance(m, dict) and "role" in m and "content" in m:
                        await store.append_message(
                            thread_id, role=m["role"], content=m["content"],
                        )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ----- Live training tail (SSE) -------------------------------------
    @app.get("/api/live/training", dependencies=[Depends(require_auth)])
    async def live_training(interval: float = Query(default=2.0, ge=0.5, le=10.0)) -> StreamingResponse:
        """Push the active training_state snapshot every `interval` seconds.

        Frontend subscribes once and renders updates anywhere — the LiveTraining
        card, the Monitor page, the sidebar pulse indicator.
        """
        ctx = ToolContext(
            repo_root=s.repo_root,
            enable_dangerous=s.enable_dangerous_tools,
        )

        async def gen() -> AsyncIterator[bytes]:
            last_payload: str | None = None
            try:
                while True:
                    snap = await registry.invoke("train_status", {}, ctx)
                    payload = json.dumps(snap, default=str)
                    # Only emit when the payload actually changed (cheap dedupe
                    # so the EventSource doesn't fire on every tick).
                    if payload != last_payload:
                        last_payload = payload
                        yield encode_sse("training_state", snap)
                    yield encode_sse("ping", {"ts": __import__("time").time()})
                    await asyncio.sleep(float(interval))
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ----- Optional: serve the built frontend at / ---------------------
    if s.frontend_dist and s.frontend_dist.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount(
            "/", StaticFiles(directory=str(s.frontend_dist), html=True),
            name="frontend",
        )

    return app
