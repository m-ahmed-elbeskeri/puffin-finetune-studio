"""Generator abstraction for eval — a Protocol with two backends.

- `TransformersGenerator`: real generation using HF Transformers (CPU or GPU).
- `EchoGenerator`: deterministic canned responses keyed by prompt substrings,
  used in CI / unit tests where loading a real model is undesirable.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from llmops.features.chat_template import (
    DEFAULT_CHAT_TEMPLATE_VERSION,
    apply_chat_template,
    get_chat_template,
)
from llmops.features.schemas import Message


@dataclass
class GenerationResult:
    text: str
    latency_ms: float
    input_tokens: int
    output_tokens: int


class Generator(Protocol):
    backend: str
    model_id: str

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.0,
    ) -> GenerationResult: ...


@dataclass
class EchoGenerator:
    """Test-friendly generator. Returns first matching response from `rules`.

    Each rule is (regex, response_text). The first regex that matches
    (case-insensitive) the rendered prompt wins. Fallback returns
    `default_response` ("OK" by default).
    """

    rules: list[tuple[str, str]] = field(default_factory=list)
    default_response: str = "OK"
    backend: str = "echo"
    model_id: str = "echo"
    fixed_latency_ms: float = 1.0

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.0,
    ) -> GenerationResult:
        rendered = apply_chat_template(list(messages), add_generation_prompt=True)
        for pattern, response in self.rules:
            if re.search(pattern, rendered, flags=re.IGNORECASE):
                return GenerationResult(
                    text=response,
                    latency_ms=self.fixed_latency_ms,
                    input_tokens=len(rendered) // 4,
                    output_tokens=len(response) // 4,
                )
        return GenerationResult(
            text=self.default_response,
            latency_ms=self.fixed_latency_ms,
            input_tokens=len(rendered) // 4,
            output_tokens=len(self.default_response) // 4,
        )


@dataclass
class TransformersGenerator:
    """Real generator using transformers + (optional) PEFT adapter."""

    model_id: str
    adapter_path: str | None = None
    chat_template_version: str = DEFAULT_CHAT_TEMPLATE_VERSION
    device: str | None = None
    backend: str = "transformers"
    _model: Any = None
    _tokenizer: Any = None

    def __post_init__(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.chat_template = get_chat_template(self.chat_template_version)

        model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            torch_dtype=torch.bfloat16 if device == "cuda" else "auto",
        ).to(device)

        if self.adapter_path and Path(self.adapter_path).exists():
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, self.adapter_path)

        model.eval()
        self._model = model
        self._tokenizer = tokenizer
        self.device = device

    def generate(
        self,
        messages: Sequence[Message] | Sequence[dict[str, str]],
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.0,
    ) -> GenerationResult:
        import torch

        msg_dicts = [m.model_dump() if isinstance(m, Message) else dict(m) for m in messages]
        prompt = self._tokenizer.apply_chat_template(
            msg_dicts, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self.device)
        input_tokens = int(inputs["input_ids"].shape[1])

        gen_kwargs = dict(
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0.0,
            pad_token_id=self._tokenizer.pad_token_id,
        )
        if temperature > 0.0:
            gen_kwargs["temperature"] = float(temperature)

        t0 = time.perf_counter()
        with torch.no_grad():
            out = self._model.generate(**inputs, **gen_kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        gen_ids = out[0, input_tokens:]
        text = self._tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
        return GenerationResult(
            text=text,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=int(gen_ids.shape[0]),
        )


def build_generator(eval_cfg: dict[str, Any]) -> Generator:
    """Construct a generator from `configs/eval.yaml::eval` block."""
    backend = eval_cfg.get("backend", "transformers")
    if backend == "echo":
        rules = [(r["pattern"], r["response"]) for r in eval_cfg.get("echo_rules", [])]
        return EchoGenerator(
            rules=rules,
            default_response=eval_cfg.get("echo_default", "OK"),
        )
    return TransformersGenerator(
        model_id=eval_cfg["model_id"],
        adapter_path=eval_cfg.get("adapter_path"),
        chat_template_version=eval_cfg.get("chat_template_version", DEFAULT_CHAT_TEMPLATE_VERSION),
        device=eval_cfg.get("device"),
    )
