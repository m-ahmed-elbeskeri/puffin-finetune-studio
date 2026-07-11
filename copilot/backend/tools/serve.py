"""Serving tools — health check + direct chat against the FastAPI serving app."""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool


class HealthArgs(BaseModel):
    url: str = Field(default="http://127.0.0.1:8089",
                     description="Serving app base URL.")


@tool(
    "serve_health",
    description=(
        "Check the FastAPI serving app's /ready endpoint. Returns backend, "
        "model_id, adapter status. Use to verify serving is up before serve_chat."
    ),
    args_model=HealthArgs,
)
async def serve_health(args: HealthArgs, ctx: ToolContext) -> dict[str, Any]:
    url = args.url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{url}/ready")
    except (httpx.HTTPError, OSError) as exc:
        return {"kind": "server_health", "up": False, "url": url,
                "error": f"{type(exc).__name__}: {exc}"}
    if r.status_code != 200:
        return {"kind": "server_health", "up": False, "url": url,
                "error": f"HTTP {r.status_code}"}
    payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return {"kind": "server_health", "up": True, "url": url,
            "backend": payload.get("backend", "?"),
            "model_id": payload.get("model_id", "?"),
            "adapter_loaded": bool(payload.get("adapter_loaded", False)),
            "payload": payload}


class ChatArgs(BaseModel):
    prompt: str
    url: str = Field(default="http://127.0.0.1:8089")
    system: str | None = Field(
        default="You are a helpful assistant.",
        description="System prompt prepended to the conversation.",
    )
    model: str = Field(default="puffin-playground")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=256, ge=1, le=8192)
    require_json: bool = False


@tool(
    "serve_chat",
    description=(
        "Send one chat completion request to the serving app's "
        "/v1/chat/completions endpoint. Returns the response text + metadata "
        "(latency, request_id, backend used). Use to sanity-check a deployed model."
    ),
    args_model=ChatArgs,
)
async def serve_chat(args: ChatArgs, ctx: ToolContext) -> dict[str, Any]:
    url = args.url.rstrip("/")
    msgs = []
    if args.system:
        msgs.append({"role": "system", "content": args.system})
    msgs.append({"role": "user", "content": args.prompt})
    payload: dict[str, Any] = {
        "model": args.model, "messages": msgs,
        "temperature": float(args.temperature),
        "max_tokens": int(args.max_tokens),
    }
    if args.require_json:
        payload["response_format"] = {"type": "json_object"}

    rid = f"req_{uuid.uuid4().hex[:24]}"
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{url}/v1/chat/completions", json=payload,
                headers={"x-request-id": rid},
            )
    except (httpx.HTTPError, OSError) as exc:
        raise ToolError(f"serving request failed: {exc}") from exc
    wall_ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        raise ToolError(f"HTTP {r.status_code}: {r.text[:500]}")
    body = r.json()
    return {
        "kind": "serve_chat_result",
        "text": body["choices"][0]["message"]["content"],
        "latency_ms": round(wall_ms, 1),
        "usage": body.get("usage", {}),
        "metadata": body.get("puffin_metadata", {}),
        "request_id": rid,
        "model": args.model,
    }
