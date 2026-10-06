"""Real model backends.

MLXBackend runs on the Mac (development and smoke runs). VLLMBackend runs on Kaggle (official
numbers for the leaderboard and stage 3). Neither can run in a CPU-only sandbox, so both are kept
thin: render with the model's own chat template, generate greedily, return raw text. The strict
parser in parser.py does everything else, identically for both.

Rule: every comparison inside one experiment must use one backend. Record describe() with each trace.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _template_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for message in messages:
        item = {"role": message["role"], "content": message.get("content") or ""}
        if message.get("tool_calls"):
            item["tool_calls"] = message["tool_calls"]
        out.append(item)
    return out


def render_prompt(tokenizer: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                  enable_thinking: bool = False) -> str:
    return tokenizer.apply_chat_template(
        _template_messages(messages), tools=tools, add_generation_prompt=True, enable_thinking=enable_thinking,
        tokenize=False
    )


def _template_hash(tokenizer: Any) -> str:
    template = getattr(tokenizer, "chat_template", "") or ""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]


class MLXBackend:
    """Mac backend. Sequential. Thinking off: greedy. Thinking on: the model card's sampling (greedy is
    discouraged in thinking mode), fixed seed, larger token budget."""

    def __init__(self, model: str, adapter_path: str | None = None, max_tokens: int = 512, thinking: bool = False,
                 seed: int = 0):
        import mlx.core as mx
        import mlx_lm
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        mx.random.seed(seed)
        self.model_name, self.adapter_path, self.thinking, self.seed = model, adapter_path, thinking, seed
        self.max_tokens = max(max_tokens, 2048) if thinking else max_tokens
        self.model, self.tokenizer = load(model, adapter_path=adapter_path)
        self._generate = generate
        if thinking:
            try:
                self._sampler = make_sampler(temp=0.6, top_p=0.95, top_k=20)
            except TypeError:  # older mlx-lm without top_k
                self._sampler = make_sampler(temp=0.6, top_p=0.95)
        else:
            self._sampler = make_sampler(temp=0.0)
        self._version = getattr(mlx_lm, "__version__", "unknown")

    def generate_batch(self, batch: list[list[dict[str, Any]]], tools: list[dict[str, Any]]) -> list[str]:
        outputs = []
        for messages in batch:
            prompt = render_prompt(self.tokenizer, messages, tools, enable_thinking=self.thinking)
            outputs.append(self._generate(self.model, self.tokenizer, prompt=prompt, max_tokens=self.max_tokens,
                                          sampler=self._sampler, verbose=False))
        return outputs

    def describe(self) -> dict[str, Any]:
        return {"backend": "mlx", "mlx_lm_version": self._version, "model": self.model_name, "adapter": self.adapter_path,
                "max_tokens": self.max_tokens, "enable_thinking": self.thinking,
                "sampling": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "seed": self.seed} if self.thinking
                else {"temperature": 0.0},
                "chat_template": _template_hash(self.tokenizer), "execution_mode": "real_model"}


class VLLMBackend:
    """Kaggle backend. T4 has no bf16, so dtype defaults to half. Batches a whole turn at once."""

    def __init__(self, model: str, lora_path: str | None = None, dtype: str = "half", max_tokens: int = 512,
                 tensor_parallel_size: int = 1, max_model_len: int = 8192, thinking: bool = False):
        import vllm
        from vllm import LLM, SamplingParams

        self.model_name, self.lora_path, self.dtype, self.max_tokens = model, lora_path, dtype, max_tokens
        self.llm = LLM(model=model, dtype=dtype, tensor_parallel_size=tensor_parallel_size,
                       max_model_len=max_model_len, enable_lora=lora_path is not None, seed=0)
        self.tokenizer = self.llm.get_tokenizer()
        self.thinking = thinking
        if thinking:
            self.max_tokens = max(max_tokens, 2048)
            self.params = SamplingParams(temperature=0.6, top_p=0.95, top_k=20, max_tokens=self.max_tokens, seed=0)
        else:
            self.params = SamplingParams(temperature=0.0, max_tokens=max_tokens)
        self._lora = None
        if lora_path:
            from vllm.lora.request import LoRARequest
            self._lora = LoRARequest("adapter", 1, lora_path)
        self._version = vllm.__version__
        self._tp = tensor_parallel_size

    def generate_batch(self, batch: list[list[dict[str, Any]]], tools: list[dict[str, Any]]) -> list[str]:
        prompts = [render_prompt(self.tokenizer, messages, tools, enable_thinking=self.thinking) for messages in batch]
        results = self.llm.generate(prompts, self.params, lora_request=self._lora, use_tqdm=False)
        return [r.outputs[0].text for r in results]

    def describe(self) -> dict[str, Any]:
        return {"backend": "vllm", "vllm_version": self._version, "model": self.model_name, "lora": self.lora_path,
                "dtype": self.dtype, "tensor_parallel_size": self._tp, "max_tokens": self.max_tokens,
                "enable_thinking": self.thinking, "chat_template": _template_hash(self.tokenizer),
                "sampling": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "seed": 0} if self.thinking
                else {"temperature": 0.0},
                "execution_mode": "real_model"}
