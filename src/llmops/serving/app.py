"""FastAPI serving app — OpenAI-compatible chat completions + ops endpoints.

Endpoints:
  GET  /health                      → liveness
  GET  /ready                       → readiness (model loaded)
  GET  /model/version               → backend + model_version
  GET  /metrics                     → Prometheus
  POST /v1/chat/completions         → OpenAI-compatible chat
  POST /v1/feedback                 → user feedback capture (thumbs / rubric)

Run:
    python -m llmops.serving.app --config configs/deploy.yaml
or
    uvicorn llmops.serving.app:create_app --factory --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from llmops.common.config import load_yaml
from llmops.common.errors import GuardrailError
from llmops.common.logging import configure_logging, get_logger
from llmops.monitoring.metrics import (
    REGISTRY,
    inference_counter,
    inference_errors,
    inference_latency,
    inference_tokens,
    render_prometheus,
)
from llmops.monitoring.request_log import RequestLogger
from llmops.serving.backends import build_backend
from llmops.serving.guardrails import GuardrailConfig
from llmops.serving.inference_pipeline import (
    coerce_request,
    run_chat_completion,
)

log = get_logger(__name__)

_STATE: dict[str, Any] = {}


def _make_lifespan(cfg: dict[str, Any]):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        log.info("loading backend %s", cfg.get("server", {}).get("backend", "echo"))
        backend = build_backend(cfg)
        guardrails = GuardrailConfig.from_dict(cfg.get("guardrails"))
        request_logger = RequestLogger(
            log_path=cfg.get("observability", {}).get("request_log_path"),
            log_inputs=cfg.get("observability", {}).get("log_prompts", False),
            log_outputs=cfg.get("observability", {}).get("log_outputs", False),
        )
        _STATE.update(
            {
                "backend": backend,
                "guardrails": guardrails,
                "request_logger": request_logger,
                "config": cfg,
            }
        )
        log.info(
            "ready: backend=%s model=%s version=%s",
            backend.name,
            backend.model_id,
            backend.model_version,
        )
        try:
            yield
        finally:
            log.info("shutting down")
            _STATE.clear()

    return lifespan


def create_app(config_path: str | None = None) -> FastAPI:
    configure_logging()
    config_path = config_path or os.environ.get("PUFFIN_DEPLOY_CONFIG", "configs/deploy.yaml")
    cfg = load_yaml(config_path)

    app = FastAPI(
        title="puffin-finetune-studio serving",
        version="0.1.0",
        lifespan=_make_lifespan(cfg),
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        backend = _STATE.get("backend")
        if backend is None:
            raise HTTPException(status_code=503, detail="backend not loaded")
        return {"status": "ready", "backend": backend.name, "model_id": backend.model_id}

    @app.get("/model/version")
    async def model_version() -> dict[str, Any]:
        backend = _STATE.get("backend")
        if backend is None:
            raise HTTPException(status_code=503, detail="backend not loaded")
        return {
            "backend": backend.name,
            "model_id": backend.model_id,
            "model_version": backend.model_version,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return PlainTextResponse(content=render_prometheus(REGISTRY), media_type="text/plain")

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        backend = _STATE.get("backend")
        guardrails = _STATE.get("guardrails")
        request_logger: RequestLogger | None = _STATE.get("request_logger")
        if backend is None or guardrails is None:
            raise HTTPException(status_code=503, detail="backend not loaded")

        try:
            payload = await request.json()
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

        try:
            req = coerce_request(payload)
        except Exception as exc:  # pydantic ValidationError + others
            inference_errors.labels(reason="validation").inc()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        request_id = request.headers.get("x-request-id")
        try:
            result = run_chat_completion(
                req,
                backend=backend,
                guardrails=guardrails,
                request_id=request_id,
            )
        except GuardrailError as exc:
            inference_errors.labels(reason="guardrail").inc()
            if request_logger:
                request_logger.log_error(
                    request_id=request_id or "n/a",
                    error_type="guardrail",
                    error_message=str(exc),
                )
            raise HTTPException(status_code=400, detail=f"guardrail: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            inference_errors.labels(reason="internal").inc()
            log.exception("inference error")
            raise HTTPException(status_code=500, detail="internal error") from exc

        inference_counter.labels(model=backend.model_id, backend=backend.name).inc()
        inference_latency.labels(model=backend.model_id).observe(result.latency_ms / 1000.0)
        inference_tokens.labels(model=backend.model_id, kind="prompt").inc(result.input_tokens)
        inference_tokens.labels(model=backend.model_id, kind="completion").inc(result.output_tokens)

        if request_logger:
            request_logger.log_request(
                request_id=result.request_id,
                user=req.user,
                model=req.model,
                model_version=backend.model_version,
                backend=backend.name,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                input_messages=[m.model_dump() for m in req.messages],
                output_text=result.response.choices[0].message.content,
            )

        return JSONResponse(content=result.response.model_dump(mode="json"))

    @app.post("/v1/feedback")
    async def feedback(request: Request) -> dict[str, str]:
        request_logger: RequestLogger | None = _STATE.get("request_logger")
        try:
            payload = await request.json()
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

        rid = payload.get("request_id")
        score = payload.get("score")
        comment = payload.get("comment")
        if not rid:
            raise HTTPException(status_code=400, detail="request_id is required")
        if request_logger:
            request_logger.log_feedback(request_id=rid, score=score, comment=comment)
        return {"status": "ok"}

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run puffin serving app.")
    parser.add_argument("--config", default="configs/deploy.yaml")
    parser.add_argument("--host", default=os.environ.get("PUFFIN_SERVE_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PUFFIN_SERVE_PORT", "8080"))
    )
    args = parser.parse_args(argv)

    import uvicorn

    os.environ["PUFFIN_DEPLOY_CONFIG"] = args.config
    uvicorn.run(
        "llmops.serving.app:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
