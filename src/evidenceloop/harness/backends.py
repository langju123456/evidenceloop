"""Real model backends.

MLXBackend runs on the Mac (development and smoke runs). VLLMBackend runs on Kaggle (official
numbers for the leaderboard and stage 3). HFBackend is the Kaggle fallback when vLLM cannot run on the
GPU; which one stage 3 uses is fixed before the first formal run (D11, D12). All are kept thin: render
with the model's own chat template, generate greedily, return raw text. The strict parser in parser.py
does everything else, identically for all of them.

Rule: every comparison inside one experiment must use one backend. Record describe() with each trace.
"""

from __future__ import annotations

import hashlib
import os
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


def render_full(tokenizer: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
    """The whole conversation, no generation prompt. Training targets are cut from this (export.py)."""
    return tokenizer.apply_chat_template(
        _template_messages(messages), tools=tools, add_generation_prompt=False, enable_thinking=False, tokenize=False
    )


def load_causal_lm(name: str, dtype: Any) -> Any:
    """transformers renamed torch_dtype to dtype; accept either version."""
    from transformers import AutoModelForCausalLM

    try:
        return AutoModelForCausalLM.from_pretrained(name, dtype=dtype)
    except TypeError:
        return AutoModelForCausalLM.from_pretrained(name, torch_dtype=dtype)


def _template_hash(tokenizer: Any) -> str:
    template = getattr(tokenizer, "chat_template", "") or ""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]


def weights_fingerprint(path: str | None) -> str | None:
    """Content hash of a local model or adapter directory (weights, configs, tokenizer files); None for a hub
    name. A W retrained into the same directory gets a new fingerprint, so its traces cannot be mixed with
    the old W's (the fingerprint is part of describe(), hence of inference_config_hash)."""
    if not path or not os.path.isdir(path):
        return None
    digest = hashlib.sha256()
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if not (os.path.isfile(full) and name.endswith((".safetensors", ".bin", ".json", ".model", ".txt", ".jinja"))):
            continue
        digest.update(name.encode("utf-8") + b"\0")
        with open(full, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest()[:16]


def _local_path(path: str | None) -> str | None:
    """A local directory as one spelling (runs/W25/merged/ and runs/W25/merged resume the same run)."""
    return os.path.normpath(path) if path and os.path.isdir(path) else path


def _fingerprints(model: str, adapter: str | None) -> dict[str, str]:
    """Only present when there is something local to fingerprint, so hub-name runs keep their old hashes."""
    out = {}
    model_fp, adapter_fp = weights_fingerprint(model), weights_fingerprint(adapter)
    if model_fp:
        out["model_fingerprint"] = model_fp
    if adapter_fp:
        out["adapter_fingerprint"] = adapter_fp
    return out


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
        self._fingerprints = _fingerprints(model, lora_path)

    def generate_batch(self, batch: list[list[dict[str, Any]]], tools: list[dict[str, Any]]) -> list[str]:
        prompts = [render_prompt(self.tokenizer, messages, tools, enable_thinking=self.thinking) for messages in batch]
        results = self.llm.generate(prompts, self.params, lora_request=self._lora, use_tqdm=False)
        return [r.outputs[0].text for r in results]

    def describe(self) -> dict[str, Any]:
        return {"backend": "vllm", "vllm_version": self._version, "model": _local_path(self.model_name),
                "lora": _local_path(self.lora_path),
                "dtype": self.dtype, "tensor_parallel_size": self._tp, "max_tokens": self.max_tokens,
                "enable_thinking": self.thinking, "chat_template": _template_hash(self.tokenizer),
                "sampling": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "seed": 0} if self.thinking
                else {"temperature": 0.0},
                "execution_mode": "real_model", **self._fingerprints}


class HFBackend:
    """Kaggle fallback: plain transformers generate. Greedy, thinking off, left-padded micro-batches sorted
    by prompt length. Decoding drops special tokens like vLLM does (<|im_end|> goes, <tool_call> stays,
    because Qwen3 does not mark it special). A LoRA adapter is merged in before generating.

    A micro-batch that runs out of GPU memory is split in half and retried, down to one prompt. A prompt
    that does not fit even alone gets no output (None): only its episode ends as infra_error, the others go
    on. gen_batch is part of describe(), because in fp16 which prompts share a batch can change a greedy
    output; D12 fixes one value for all of stage 3."""

    def __init__(self, model: str, adapter_path: str | None = None, max_tokens: int = 512, gen_batch: int = 8):
        import torch
        import transformers
        from transformers import AutoTokenizer

        self.model_name, self.adapter_path, self.max_tokens, self.gen_batch = model, adapter_path, max_tokens, gen_batch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        net = load_causal_lm(model, self.dtype)
        revision = getattr(net.config, "_commit_hash", None)  # the hub snapshot, for a model loaded by name
        if adapter_path:
            from peft import PeftModel

            net = PeftModel.from_pretrained(net, adapter_path).merge_and_unload()
        self.model = net.to(self.device).eval()
        self._torch = torch
        self._oom = getattr(torch.cuda, "OutOfMemoryError", ())
        self._version = transformers.__version__
        self._fingerprints = _fingerprints(model, adapter_path)
        if revision and "model_fingerprint" not in self._fingerprints:
            self._fingerprints["model_revision"] = revision
        self.oom_splits = self.oom_failures = self.max_prompt_tokens = 0

    def _generate(self, prompts: list[str]) -> list[str]:
        enc = self.tokenizer(prompts, return_tensors="pt", padding=True, add_special_tokens=False)
        input_ids, attention_mask = enc["input_ids"].to(self.device), enc["attention_mask"].to(self.device)
        self.max_prompt_tokens = max(self.max_prompt_tokens, int(input_ids.shape[1]))
        with self._torch.inference_mode():
            out = self.model.generate(input_ids=input_ids, attention_mask=attention_mask, max_new_tokens=self.max_tokens,
                                      do_sample=False, temperature=None, top_p=None, top_k=None,
                                      pad_token_id=self.tokenizer.pad_token_id)
        return self.tokenizer.batch_decode(out[:, input_ids.shape[1]:], skip_special_tokens=True)

    def _generate_fitting(self, prompts: list[str]) -> list[str | None]:
        try:
            return self._generate(prompts)
        except self._oom:
            pass
        # outside the except block the failed call's tensors are already released
        self._torch.cuda.empty_cache()
        if len(prompts) == 1:
            self.oom_failures += 1
            return [None]
        self.oom_splits += 1
        half = len(prompts) // 2
        return self._generate_fitting(prompts[:half]) + self._generate_fitting(prompts[half:])

    def generate_batch(self, batch: list[list[dict[str, Any]]], tools: list[dict[str, Any]]) -> list[str | None]:
        prompts = [render_prompt(self.tokenizer, messages, tools, enable_thinking=False) for messages in batch]
        order = sorted(range(len(prompts)), key=lambda i: len(prompts[i]))
        outputs: list[str | None] = [""] * len(prompts)
        for start in range(0, len(order), self.gen_batch):
            idx = order[start:start + self.gen_batch]
            for i, text in zip(idx, self._generate_fitting([prompts[i] for i in idx])):
                outputs[i] = text
        return outputs

    def status(self) -> str:
        """For the progress line: the longest prompt so far, peak GPU memory, splits and failures."""
        parts = [f"最长输入 {self.max_prompt_tokens} token"]
        if self.device == "cuda":
            parts.append(f"显存峰值 {self._torch.cuda.max_memory_allocated() / 2**30:.1f} GB")
        if self.oom_splits:
            parts.append(f"显存不够拆小 {self.oom_splits} 次")
        if self.oom_failures:
            parts.append(f"单条也放不下 {self.oom_failures} 次")
        return "，".join(parts)

    def describe(self) -> dict[str, Any]:
        return {"backend": "hf", "transformers_version": self._version, "model": _local_path(self.model_name),
                "adapter": _local_path(self.adapter_path), "dtype": str(self.dtype).replace("torch.", ""),
                "gen_batch": self.gen_batch,
                "max_tokens": self.max_tokens, "enable_thinking": False, "sampling": {"temperature": 0.0},
                "chat_template": _template_hash(self.tokenizer), "execution_mode": "real_model", **self._fingerprints}

