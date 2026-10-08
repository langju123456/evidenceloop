"""LoRA SFT for stage 3, written out by hand so every step can be checked.

1. Each exported sample ("history so far" -> "next assistant message") is rendered with the model's own
   chat template exactly as at inference: the prompt with the generation prompt, thinking off. The target
   is what follows the prompt in the rendered conversation, cut right after <|im_end|>.
2. Prompt and target are tokenized separately and concatenated, so the prompt tokens are the same ones the
   model sees at inference. Labels are -100 on the prompt: the loss counts only the target (the loss mask).
   Tool observations live in the prompt and are never supervised.
3. The target sits at the end of the sequence, so logits are computed only for those positions: a full
   vocabulary projection over a few-thousand-token history would not fit on a T4.
4. LoRA adapters are trained with AdamW, the base stays frozen; on a GPU in fp16 with a grad scaler.
   Each optimizer step averages the loss over the supervised tokens of its samples. A step whose
   gradients overflow is skipped by the scaler and marked in the log; a non-finite loss, or more than
   MAX_SKIPPED skipped steps, stops the run after writing the log so far (then train in fp32).
5. train_log.json records the data hash, every setting, the git commit, supervised and total token counts,
   the number of optimizer steps and the loss of each step (D10: budgets are checked in tokens, not
   characters), peak GPU memory, and fingerprints of the adapter and of the merged model (the same
   fingerprints that the evaluation backends put into every trace).
6. --merge-out folds the adapter into the base and saves it: that is how W is made (D11).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from evidenceloop.data.export import EOS, check_prefix_consistency
from evidenceloop.harness.backends import render_full, render_prompt, weights_fingerprint

TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
MAX_SKIPPED = 5
INIT_SCALE = 2.0**12  # torch's default 2**16 tends to overflow, and so skip, the first steps of a short run


@dataclass
class TrainConfig:
    base: str
    data: str
    out: str
    merge_out: str | None = None
    lr: float = 1e-4
    epochs: int = 2
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: list(TARGET_MODULES))
    grad_accum: int = 16
    warmup_steps: int = 5
    max_len: int = 8192
    max_steps: int = 0
    seed: int = 0
    gradient_checkpointing: bool = True
    fp32: bool = False


def _render(tokenizer: Any):
    def render(messages: list[dict[str, Any]], tools: list[dict[str, Any]], add_generation_prompt: bool) -> str:
        if add_generation_prompt:
            return render_prompt(tokenizer, messages, tools, enable_thinking=False)
        return render_full(tokenizer, messages, tools)
    return render


def build_example(tokenizer: Any, sample: dict[str, Any], max_len: int) -> tuple[dict[str, Any] | None, str | None]:
    """Token ids and labels for one sample, or (None, reason)."""
    render = _render(tokenizer)
    problems = check_prefix_consistency(render, sample)
    if problems:
        return None, "template: " + "; ".join(problems)
    prompt = render(sample["prompt"], sample["tools"], True)
    target = render(sample["prompt"] + sample["completion"], sample["tools"], False)[len(prompt):]
    target = target[: target.index(EOS) + len(EOS)]
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    target_ids = tokenizer(target, add_special_tokens=False)["input_ids"]
    if len(prompt_ids) + len(target_ids) > max_len:
        return None, "too_long"
    return {
        "input_ids": prompt_ids + target_ids,
        "labels": [-100] * len(prompt_ids) + target_ids,
        "n_prompt": len(prompt_ids),
        "n_supervised": len(target_ids),
    }, None


def plan_windows(n_examples: int, epochs: int, grad_accum: int, seed: int, max_steps: int = 0) -> list[list[int]]:
    """Which examples go into each optimizer step: a fresh shuffle per epoch, grad_accum samples per step."""
    order: list[int] = []
    for epoch in range(epochs):
        idx = list(range(n_examples))
        random.Random(f"{seed}:{epoch}").shuffle(idx)
        order += idx
    windows = [order[i:i + grad_accum] for i in range(0, len(order), grad_accum)]
    return windows[:max_steps] if max_steps else windows


def lr_factor(step: int, total: int, warmup: int) -> float:
    """Linear warm-up to the peak, then linear decay to zero at the last step (step counts from 0)."""
    warmup = min(warmup, max(total - 1, 0))
    if warmup and step < warmup:
        return (step + 1) / warmup
    remaining = max(total - warmup, 1)
    return max(0.0, 1 - (step - warmup) / remaining)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_state() -> dict[str, Any]:
    """The code version a run used: commit, and whether tracked files had uncommitted changes."""
    import subprocess

    here = os.path.dirname(os.path.abspath(__file__))
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True, text=True, timeout=10)
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=here,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}
    if commit.returncode != 0:
        return {"commit": None, "dirty": None}
    return {"commit": commit.stdout.strip(), "dirty": bool(status.stdout.strip())}


def example_loss(causal_lm: Any, example: dict[str, Any], device: str, use_fp16: bool = False) -> Any:
    """Summed cross-entropy over the target tokens of one example (a 0-dim tensor). Equal to the library's
    loss with labels (which averages) times n_supervised; tests/test_train_smoke.py checks that."""
    import torch

    n_prompt, n_sup = example["n_prompt"], example["n_supervised"]
    ids = torch.tensor([example["input_ids"]], device=device)
    target = torch.tensor(example["input_ids"][n_prompt:], device=device)
    with torch.autocast(device_type=device, dtype=torch.float16, enabled=use_fp16):
        hidden = causal_lm.model(input_ids=ids, use_cache=False).last_hidden_state
        # position t predicts token t+1: the target tokens are predicted from n_prompt-1 onward
        logits = causal_lm.lm_head(hidden[0, n_prompt - 1: n_prompt - 1 + n_sup])
    return torch.nn.functional.cross_entropy(logits.float(), target, reduction="sum")


def prepare(tokenizer: Any, samples: list[dict[str, Any]], max_len: int) -> tuple[list[dict[str, Any]], Counter]:
    examples, skipped = [], Counter()
    for sample in samples:
        example, reason = build_example(tokenizer, sample, max_len)
        if example is None:
            skipped[reason] += 1
        else:
            examples.append(example)
    broken = {r: n for r, n in skipped.items() if r != "too_long"}
    if broken:
        raise RuntimeError(f"模板检查没通过，不能训练：{broken}")
    return examples, skipped


def train(cfg: TrainConfig) -> dict[str, Any]:
    import peft
    import torch
    import transformers
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer

    from evidenceloop.harness.backends import load_causal_lm

    began = time.time()
    torch.manual_seed(cfg.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_fp16 = device == "cuda" and not cfg.fp32
    tokenizer = AutoTokenizer.from_pretrained(cfg.base)
    with open(cfg.data, encoding="utf-8") as fh:
        samples = [json.loads(line) for line in fh if line.strip()]
    examples, skipped = prepare(tokenizer, samples, cfg.max_len)
    if not examples:
        raise RuntimeError("没有可训练的样本")

    model = load_causal_lm(cfg.base, torch.float16 if use_fp16 else torch.float32).to(device)
    model.config.use_cache = False
    if cfg.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=cfg.rank, lora_alpha=cfg.alpha, lora_dropout=cfg.dropout,
                                             target_modules=cfg.target_modules, task_type="CAUSAL_LM"))
    for p in model.parameters():  # adapters in fp32 even when the frozen base is fp16
        if p.requires_grad:
            p.data = p.data.float()
    params = [p for p in model.parameters() if p.requires_grad]
    trainable = sum(p.numel() for p in params)
    total_params = sum(p.numel() for p in model.parameters())
    optimizer = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=0.0)
    try:
        scaler = torch.amp.GradScaler("cuda", init_scale=INIT_SCALE, enabled=use_fp16)
    except (AttributeError, TypeError):  # torch < 2.3
        scaler = torch.cuda.amp.GradScaler(init_scale=INIT_SCALE, enabled=use_fp16)
    causal_lm = model.get_base_model()
    windows = plan_windows(len(examples), cfg.epochs, cfg.grad_accum, cfg.seed, cfg.max_steps)
    os.makedirs(cfg.out, exist_ok=True)
    log_path = os.path.join(cfg.out, "train_log.json")
    data_sha256, base_fingerprint, git = _sha256_file(cfg.data), weights_fingerprint(cfg.base), git_state()
    steps: list[dict[str, Any]] = []

    def peak_gb() -> float | None:
        return round(torch.cuda.max_memory_allocated() / 2**30, 2) if device == "cuda" else None

    def write_log(**extra: Any) -> dict[str, Any]:
        """Written at the end, and also when a run stops early, so the steps up to that point are kept."""
        log = {
            "config": asdict(cfg),
            "data_sha256": data_sha256,
            "base_fingerprint": base_fingerprint,  # None for a hub name; W's fingerprint when B, C, D train on W
            "samples_in_file": len(samples),
            "examples": len(examples),
            "skipped": dict(skipped),
            "planned_steps": len(windows),
            "optimizer_steps": len(steps),
            "skipped_steps": sum(s["overflow_skipped"] for s in steps),
            "supervised_tokens_per_epoch": sum(e["n_supervised"] for e in examples),
            "total_tokens_per_epoch": sum(len(e["input_ids"]) for e in examples),
            # tokens behind updates that were applied; a step skipped by the grad scaler taught nothing
            "supervised_tokens_trained": sum(s["supervised_tokens"] for s in steps if not s["overflow_skipped"]),
            "max_sequence_length": max(len(e["input_ids"]) for e in examples),
            "trainable_parameters": trainable,
            "total_parameters": total_params,
            "device": device,
            "dtype": "float16" if use_fp16 else "float32",
            "grad_scaler_init": INIT_SCALE if use_fp16 else None,
            "versions": {"torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__},
            "git": git,
            "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "peak_memory_gb": peak_gb(),
            "seconds": round(time.time() - began, 1),
            "steps": steps,
            **extra,
        }
        with open(log_path, "w", encoding="utf-8") as fh:
            json.dump(log, fh, ensure_ascii=False, indent=2)
        return log

    def stop(message: str) -> None:
        write_log(aborted=message)
        raise RuntimeError(f"{message}（到这一步为止的记录在 {log_path}）")

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    model.train()
    for step, window in enumerate(windows):
        lr = cfg.lr * lr_factor(step, len(windows), cfg.warmup_steps)
        for group in optimizer.param_groups:
            group["lr"] = lr
        n_sup = sum(examples[i]["n_supervised"] for i in window)
        loss_sum = 0.0
        for i in window:
            loss = example_loss(causal_lm, examples[i], device, use_fp16)
            scaler.scale(loss / n_sup).backward()
            loss_sum += loss.item()
        if not math.isfinite(loss_sum):
            stop(f"第 {step + 1} 步的 loss 不是有限数（fp16 前向溢出）：加 --fp32 重新训练")
        scaler.unscale_(optimizer)
        grad_norm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
        scale = scaler.get_scale()
        scaler.step(optimizer)
        scaler.update()
        overflow = bool(use_fp16 and scaler.get_scale() < scale)  # inf/nan gradients: the scaler skipped this update
        optimizer.zero_grad(set_to_none=True)
        steps.append({"step": step + 1, "loss": loss_sum / n_sup, "lr": lr, "samples": len(window),
                      "supervised_tokens": n_sup, "grad_norm": grad_norm if math.isfinite(grad_norm) else None,
                      "overflow_skipped": overflow})
        memory = f"  显存峰值 {peak_gb()} GB" if device == "cuda" else ""
        print(f"step {step + 1}/{len(windows)}  loss {loss_sum / n_sup:.4f}  lr {lr:.2e}  tokens {n_sup}{memory}"
              + ("  梯度溢出，这一步跳过" if overflow else ""), flush=True)
        skipped_steps = sum(s["overflow_skipped"] for s in steps)
        if skipped_steps > MAX_SKIPPED:
            stop(f"已有 {skipped_steps} 步因梯度溢出被跳过（上限 {MAX_SKIPPED}）：加 --fp32 重新训练")

    adapter_dir = os.path.join(cfg.out, "adapter")
    model.save_pretrained(adapter_dir)
    log = write_log(adapter_dir=adapter_dir, adapter_fingerprint=weights_fingerprint(adapter_dir))

    if cfg.merge_out:
        del model, causal_lm, optimizer
        if device == "cuda":
            torch.cuda.empty_cache()
        merging = time.time()
        merge(cfg.base, adapter_dir, cfg.merge_out, torch.float16 if use_fp16 else torch.float32)
        log = write_log(adapter_dir=adapter_dir, adapter_fingerprint=log["adapter_fingerprint"], seconds=log["seconds"],
                        merged_to=cfg.merge_out, merge_seconds=round(time.time() - merging, 1),
                        merged_fingerprint=weights_fingerprint(cfg.merge_out))  # = model_fingerprint in W's traces
    return log


def merge(base: str, adapter_dir: str, out: str, dtype: Any) -> None:
    """Fold the adapter into the base weights and save a plain model (W, D11). Runs on the CPU."""
    from peft import PeftModel
    from transformers import AutoTokenizer

    from evidenceloop.harness.backends import load_causal_lm

    model = PeftModel.from_pretrained(load_causal_lm(base, dtype), adapter_dir).merge_and_unload()
    model.save_pretrained(out, safe_serialization=True)
    AutoTokenizer.from_pretrained(base).save_pretrained(out)


def supervised_tokens(tokenizer: Any, samples: list[dict[str, Any]], max_len: int = 1 << 30) -> int:
    examples, _ = prepare(tokenizer, samples, max_len)
    return sum(e["n_supervised"] for e in examples)


def steps_for(n_examples: int, epochs: int, grad_accum: int) -> int:
    return math.ceil(n_examples * epochs / grad_accum)
