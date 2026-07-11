"""Inference backends.

All backends implement the same `Backend` Protocol so the routing layer is
backend-agnostic. Three implementations ship:

- `EchoBackend`: regex → canned response. Zero dependencies. Used for tests
  and as the default smoke serving backend.
- `TransformersBackend`: HF transformers + optional PEFT adapter.
- `VLLMBackend`: vLLM AsyncLLMEngine. Falls back to ImportError-raising stub
  on platforms (e.g. Windows) where vLLM is not installable.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from llmops.common.errors import ProviderNotAvailableError
from llmops.features.chat_template import (
    DEFAULT_CHAT_TEMPLATE_VERSION,
    apply_chat_template,
    get_chat_template,
)
from llmops.features.schemas import Message


@dataclass
class GenResult:
    text: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    finish_reason: str = "stop"


class Backend(Protocol):
    name: str
    model_id: str
    model_version: str

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: list[str] | None = None,
        seed: int | None = None,
    ) -> GenResult: ...


@dataclass
class EchoBackend:
    """Deterministic regex → canned response. Used in tests and smoke serving."""

    rules: list[tuple[str, str]] = field(default_factory=list)
    default_response: str = "OK"
    name: str = "echo"
    model_id: str = "echo"
    model_version: str = "0"

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: list[str] | None = None,
        seed: int | None = None,
    ) -> GenResult:
        rendered = apply_chat_template(list(messages), add_generation_prompt=True)
        response = self.default_response
        for pattern, resp in self.rules:
            if re.search(pattern, rendered, flags=re.IGNORECASE):
                response = resp
                break
        return GenResult(
            text=response,
            latency_ms=1.0,
            input_tokens=max(1, len(rendered) // 4),
            output_tokens=max(1, len(response) // 4),
            finish_reason="stop",
        )


@dataclass
class TransformersBackend:
    """HF transformers + optional PEFT adapter."""

    model_id: str
    adapter_path: str | None = None
    chat_template_version: str = DEFAULT_CHAT_TEMPLATE_VERSION
    device: str | None = None
    quantization: str | None = None  # "4bit" | "8bit" | None
    name: str = "transformers"
    model_version: str = "unknown"
    _model: Any = None
    _tokenizer: Any = None

    def __post_init__(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        tok = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        tok.chat_template = get_chat_template(self.chat_template_version)

        load_kwargs: dict[str, Any] = {
            "torch_dtype": torch.bfloat16 if device == "cuda" else "auto",
        }
        if self.quantization == "4bit":
            try:
                from transformers import BitsAndBytesConfig

                load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
            except ImportError:  # pragma: no cover
                pass
        elif self.quantization == "8bit":
            try:
                from transformers import BitsAndBytesConfig

                load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
            except ImportError:  # pragma: no cover
                pass

        model = AutoModelForCausalLM.from_pretrained(self.model_id, **load_kwargs)
        if self.adapter_path and Path(self.adapter_path).exists():
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, self.adapter_path)
        if "quantization_config" not in load_kwargs:
            model = model.to(device)
        model.eval()

        self._model = model
        self._tokenizer = tok
        self.device = device
        self.model_version = self.adapter_path or self.model_id

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: list[str] | None = None,
        seed: int | None = None,
    ) -> GenResult:
        import torch

        if seed is not None:
            torch.manual_seed(seed)

        msg_dicts = [m.model_dump() if isinstance(m, Message) else dict(m) for m in messages]
        prompt = self._tokenizer.apply_chat_template(
            msg_dicts, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self.device)
        input_tokens = int(inputs["input_ids"].shape[1])

        gen_kwargs: dict[str, Any] = dict(
            max_new_tokens=max_tokens,
            do_sample=temperature > 0.0,
            top_p=top_p,
            pad_token_id=self._tokenizer.pad_token_id,
        )
        if temperature > 0.0:
            gen_kwargs["temperature"] = float(temperature)

        t0 = time.perf_counter()
        with torch.no_grad():
            out = self._model.generate(**inputs, **gen_kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        gen_ids = out[0, input_tokens:]
        text = self._tokenizer.decode(gen_ids, skip_special_tokens=True)

        finish_reason = "length" if int(gen_ids.shape[0]) >= max_tokens else "stop"
        if stop:
            for s in stop:
                idx = text.find(s)
                if idx >= 0:
                    text = text[:idx]
                    finish_reason = "stop"
                    break

        return GenResult(
            text=text.strip(),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=int(gen_ids.shape[0]),
            finish_reason=finish_reason,
        )


@dataclass
class VLLMBackend:
    """vLLM offline-style sync wrapper. Optional dependency.

    For a production deployment, prefer running the dedicated `vllm serve`
    process behind this app — keep this backend for embedded use.
    """

    model_id: str
    chat_template_version: str = DEFAULT_CHAT_TEMPLATE_VERSION
    name: str = "vllm"
    model_version: str = "unknown"
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float = 0.9
    _llm: Any = None

    def __post_init__(self) -> None:
        try:
            from vllm import LLM  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderNotAvailableError(
                "vllm is not installed. Install puffin-finetune-studio[serve-vllm] (Linux only)."
            ) from exc
        self._llm = LLM(
            model=self.model_id,
            tensor_parallel_size=self.tensor_parallel_size,
            gpu_memory_utilization=self.gpu_memory_utilization,
        )
        self.model_version = self.model_id

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: list[str] | None = None,
        seed: int | None = None,
    ) -> GenResult:
        from vllm import SamplingParams  # type: ignore

        msg_list = [m.model_dump() if isinstance(m, Message) else dict(m) for m in messages]
        prompt = apply_chat_template(
            msg_list,
            version=self.chat_template_version,
            add_generation_prompt=True,
        )
        params = SamplingParams(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop or [],
            seed=seed,
        )
        t0 = time.perf_counter()
        out = self._llm.generate([prompt], params)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        completion = out[0].outputs[0]
        return GenResult(
            text=completion.text.strip(),
            latency_ms=latency_ms,
            input_tokens=len(out[0].prompt_token_ids),
            output_tokens=len(completion.token_ids),
            finish_reason=completion.finish_reason or "stop",
        )


def build_backend(deploy_cfg: dict[str, Any]) -> Backend:
    """Construct a backend from `configs/deploy.yaml::server`."""
    server = deploy_cfg.get("server", {})
    backend = server.get("backend", "echo")

    if backend == "echo":
        rules = [(r["pattern"], r["response"]) for r in server.get("echo_rules", [])]
        return EchoBackend(
            rules=rules,
            default_response=server.get("echo_default", "OK"),
        )
    if backend == "transformers":
        return TransformersBackend(
            model_id=server["model_id"],
            adapter_path=server.get("adapter_path"),
            chat_template_version=server.get(
                "chat_template_version", DEFAULT_CHAT_TEMPLATE_VERSION
            ),
            device=server.get("device"),
            quantization=server.get("quantization"),
        )
    if backend == "vllm":
        return VLLMBackend(
            model_id=server["model_id"],
            chat_template_version=server.get(
                "chat_template_version", DEFAULT_CHAT_TEMPLATE_VERSION
            ),
            tensor_parallel_size=int(server.get("tensor_parallel_size", 1)),
            gpu_memory_utilization=float(server.get("gpu_memory_utilization", 0.9)),
        )
    raise ValueError(f"Unknown backend: {backend!r}")
