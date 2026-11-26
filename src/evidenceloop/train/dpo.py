"""LoRA DPO for stage 5 (D16), on the same hand-written loop as train/sft.py.

1. A pair {prompt, chosen, rejected, tools} becomes two examples that share their prompt tokens: the prompt
   followed by the chosen reply, and by the rejected reply. Each is built exactly like an SFT example
   (sft.build_example): rendered with the model's own chat template as at inference, the reply cut right
   after <|im_end|>.
2. log pi(reply | prompt) is the sum of the token log-probabilities over the reply only, the positions the
   SFT loss mask covers: it is minus sft.example_loss(). The history and the tool observations never count.
3. The reference model is the model the new adapter sits on. Its two log-probabilities per pair are computed
   once, before the first step, with the adapter disabled, and are not computed again.
4. loss = -log sigmoid(beta * [(log pi(chosen) - log ref(chosen)) - (log pi(rejected) - log ref(rejected))]),
   averaged over the pairs of an optimizer step. A fresh adapter changes nothing yet, so step 1 starts at ln 2.
5. The rest is train/sft.py's: the adapter setup, AdamW, the schedule, fp16 with a grad scaler, stopping on a
   non-finite loss or too many skipped steps. train_log.json has the same fields, plus beta, the reference
   log-probabilities, and per step the mean log-probabilities of both sides and how many pairs moved toward
   the chosen reply relative to the reference.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from evidenceloop.harness.backends import check_no_old_torchao, weights_fingerprint
from evidenceloop.train.sft import (INIT_SCALE, MAX_SKIPPED, TARGET_MODULES, _sha256_file, build_example, example_loss,
                                    git_state, grad_scaler, lora_model, lr_factor, plan_windows)

SIDES = ("chosen", "rejected")


@dataclass
class DPOConfig:
    base: str
    data: str
    out: str
    beta: float = 0.1
    lr: float = 1e-4
    epochs: int = 1
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: list(TARGET_MODULES))
    grad_accum: int = 8  # pairs per optimizer step: 16 sequences, as many as SFT's 16 samples
    warmup_steps: int = 5
    max_len: int = 8192
    max_steps: int = 0
    seed: int = 0
    gradient_checkpointing: bool = True
    fp32: bool = False


def build_pair(tokenizer: Any, pair: dict[str, Any], max_len: int) -> tuple[dict[str, Any] | None, str | None]:
    """The two examples of one pair ({"chosen": ..., "rejected": ...}), or (None, reason)."""
    examples = {}
    for side in SIDES:
        sample = {"prompt": pair["prompt"], "completion": pair[side], "tools": pair["tools"]}
        example, reason = build_example(tokenizer, sample, max_len)
        if example is None:
            return None, reason
        examples[side] = example
    chosen, rejected = examples["chosen"], examples["rejected"]
    if chosen["input_ids"][:chosen["n_prompt"]] != rejected["input_ids"][:rejected["n_prompt"]]:
        return None, "template: chosen and rejected do not share the prompt tokens"
    return examples, None


def prepare_pairs(tokenizer: Any, pairs: list[dict[str, Any]], max_len: int) -> tuple[list[dict[str, Any]], Counter]:
    examples, skipped = [], Counter()
    for pair in pairs:
        example, reason = build_pair(tokenizer, pair, max_len)
        if example is None:
            skipped[reason] += 1
        else:
            examples.append(example)
    broken = {r: n for r, n in skipped.items() if r != "too_long"}
    if broken:
        raise RuntimeError(f"模板检查没通过，不能训练：{broken}")
    return examples, skipped


def dpo_loss(policy_chosen: Any, policy_rejected: Any, ref_chosen: Any, ref_rejected: Any, beta: float) -> Any:
    """The DPO loss of one pair. The four arguments are log-probabilities of whole replies (sums over tokens)."""
    import torch

    margin = (policy_chosen - ref_chosen) - (policy_rejected - ref_rejected)
    return -torch.nn.functional.logsigmoid(beta * margin)


def pair_logps(causal_lm: Any, example: dict[str, Any], device: str, use_fp16: bool = False) -> tuple[Any, Any]:
    """(log pi(chosen | prompt), log pi(rejected | prompt)) as 0-dim tensors, summed over the reply tokens only."""
    chosen, rejected = (-example_loss(causal_lm, example[side], device, use_fp16) for side in SIDES)
    return chosen, rejected


def reference_logps(model: Any, examples: list[dict[str, Any]], device: str,
                    use_fp16: bool = False) -> list[tuple[float, float]]:
    """The reference model's (chosen, rejected) log-probabilities for every pair: the peft model with its adapter
    disabled, which is the base the adapter sits on. No gradients; done once."""
    import torch

    causal_lm = model.get_base_model()
    was_training = model.training
    model.eval()
    out = []
    with torch.no_grad(), model.disable_adapter():
        for example in examples:
            chosen, rejected = pair_logps(causal_lm, example, device, use_fp16)
            out.append((chosen.item(), rejected.item()))
    model.train(was_training)
    return out


def train(cfg: DPOConfig) -> dict[str, Any]:
    check_no_old_torchao()
    import peft
    import torch
    import transformers
    from transformers import AutoTokenizer

    began = time.time()
    torch.manual_seed(cfg.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_fp16 = device == "cuda" and not cfg.fp32
    tokenizer = AutoTokenizer.from_pretrained(cfg.base)
    with open(cfg.data, encoding="utf-8") as fh:
        pairs = [json.loads(line) for line in fh if line.strip()]
    examples, skipped = prepare_pairs(tokenizer, pairs, cfg.max_len)
    if not examples:
        raise RuntimeError("没有可训练的偏好对")

    model = lora_model(cfg, device, use_fp16)
    params = [p for p in model.parameters() if p.requires_grad]
    trainable = sum(p.numel() for p in params)
    total_params = sum(p.numel() for p in model.parameters())
    optimizer = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=0.0)
    scaler = grad_scaler(use_fp16)
    causal_lm = model.get_base_model()
    windows = plan_windows(len(examples), cfg.epochs, cfg.grad_accum, cfg.seed, cfg.max_steps)
    os.makedirs(cfg.out, exist_ok=True)
    log_path = os.path.join(cfg.out, "train_log.json")
    data_sha256, base_fingerprint, git = _sha256_file(cfg.data), weights_fingerprint(cfg.base), git_state()
    steps: list[dict[str, Any]] = []
    reference: dict[str, Any] = {}

    def peak_gb() -> float | None:
        return round(torch.cuda.max_memory_allocated() / 2**30, 2) if device == "cuda" else None

    def write_log(**extra: Any) -> dict[str, Any]:
        """Written at the end, and also when a run stops early, so the steps up to that point are kept."""
        log = {
            "loss": "dpo",
            "config": asdict(cfg),
            "data_sha256": data_sha256,
            "base_fingerprint": base_fingerprint,  # the reference model: W for P, W with C merged in for CP (D16)
            "pairs_in_file": len(pairs),
            "pairs": len(examples),
            "skipped": dict(skipped),
            "planned_steps": len(windows),
            "optimizer_steps": len(steps),
            "skipped_steps": sum(s["overflow_skipped"] for s in steps),
            "sequences_per_epoch": 2 * len(examples),
            "supervised_tokens_per_epoch": sum(e[side]["n_supervised"] for e in examples for side in SIDES),
            "total_tokens_per_epoch": sum(len(e[side]["input_ids"]) for e in examples for side in SIDES),
            "max_sequence_length": max(len(e[side]["input_ids"]) for e in examples for side in SIDES),
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
            "reference": reference,
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
    ref_began = time.time()
    ref = reference_logps(model, examples, device, use_fp16)
    if not all(math.isfinite(v) for pair in ref for v in pair):
        stop("reference 的对数概率不是有限数（fp16 前向溢出）：加 --fp32 重新训练")
    reference.update({
        "model": "the base with the adapter disabled",
        "seconds": round(time.time() - ref_began, 1),
        "mean_logp_chosen": sum(c for c, _ in ref) / len(ref),
        "mean_logp_rejected": sum(r for _, r in ref) / len(ref),
        # pairs the reference already ranks the right way round; DPO has little to teach on those (D16)
        "chosen_more_likely": sum(1 for c, r in ref if c > r),
        "logps": [[round(c, 4), round(r, 4)] for c, r in ref],
    })
    print(f"reference：{len(ref)} 对，chosen 平均 {reference['mean_logp_chosen']:.2f}，rejected 平均 "
          f"{reference['mean_logp_rejected']:.2f}，其中 {reference['chosen_more_likely']} 对 chosen 的概率本来就更高，"
          f"用时 {reference['seconds']} 秒", flush=True)

    model.train()
    for step, window in enumerate(windows):
        lr = cfg.lr * lr_factor(step, len(windows), cfg.warmup_steps)
        for group in optimizer.param_groups:
            group["lr"] = lr
        loss_sum = chosen_sum = rejected_sum = 0.0
        improved = 0
        for i in window:
            chosen, rejected = pair_logps(causal_lm, examples[i], device, use_fp16)
            loss = dpo_loss(chosen, rejected, ref[i][0], ref[i][1], cfg.beta)
            scaler.scale(loss / len(window)).backward()
            loss_sum += loss.item()
            chosen_sum += chosen.item()
            rejected_sum += rejected.item()
            improved += int(chosen.item() - ref[i][0] > rejected.item() - ref[i][1])
        if not math.isfinite(loss_sum):
            stop(f"第 {step + 1} 步的 loss 不是有限数（fp16 前向溢出）：加 --fp32 重新训练")
        scaler.unscale_(optimizer)
        grad_norm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
        scale = scaler.get_scale()
        scaler.step(optimizer)
        scaler.update()
        overflow = bool(use_fp16 and scaler.get_scale() < scale)  # inf/nan gradients: the scaler skipped this update
        optimizer.zero_grad(set_to_none=True)
        n = len(window)
        steps.append({"step": step + 1, "loss": loss_sum / n, "lr": lr, "pairs": n,
                      "supervised_tokens": sum(examples[i][side]["n_supervised"] for i in window for side in SIDES),
                      "logp_chosen": chosen_sum / n, "logp_rejected": rejected_sum / n, "improved": improved,
                      "grad_norm": grad_norm if math.isfinite(grad_norm) else None, "overflow_skipped": overflow})
        memory = f"  显存峰值 {peak_gb()} GB" if device == "cuda" else ""
        print(f"step {step + 1}/{len(windows)}  loss {loss_sum / n:.4f}  lr {lr:.2e}  logp chosen {chosen_sum / n:.2f} "
              f"rejected {rejected_sum / n:.2f}  比 reference 更偏向 chosen 的 {improved}/{n}{memory}"
              + ("  梯度溢出，这一步跳过" if overflow else ""), flush=True)
        skipped_steps = sum(s["overflow_skipped"] for s in steps)
        if skipped_steps > MAX_SKIPPED:
            stop(f"已有 {skipped_steps} 步因梯度溢出被跳过（上限 {MAX_SKIPPED}）：加 --fp32 重新训练")

    adapter_dir = os.path.join(cfg.out, "adapter")
    model.save_pretrained(adapter_dir)
    return write_log(adapter_dir=adapter_dir, adapter_fingerprint=weights_fingerprint(adapter_dir))
