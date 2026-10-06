"""SFT export.

Single-decision expansion: every assistant message becomes one sample, "history so far -> this
message". Only the completion is supervised, and the history is rendered exactly as at inference.

Formats:
  trl : {"prompt": [...], "completion": [...], "tools": [...]}  (Kaggle, TRL SFTTrainer)
  mlx : {"messages": [...], "tools": [...]}                     (Mac, mlx_lm.lora --mask-prompt)

check_prefix_consistency() must pass with the real tokenizer before any training run. Use
scripts/check_template.py on the machine that trains.
"""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Callable
from typing import Any

from evidenceloop.common import GENERATOR_VERSION, VERIFIER_VERSION, canonical_json, content_hash

EOS = "<|im_end|>"
Render = Callable[[list[dict[str, Any]], list[dict[str, Any]], bool], str]


def expand(record: dict[str, Any]) -> list[dict[str, Any]]:
    messages, samples = record["messages"], []
    for i, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        samples.append({
            "sample_id": f"{record['task_id']}#{i}",
            "task_id": record["task_id"],
            "policy": record["policy"],
            "bucket": record["bucket"],
            "source_failure_ids": record["source_failure_ids"],
            "verification_status": record["verification_status"],
            "prompt": copy.deepcopy(messages[:i]),
            "completion": [copy.deepcopy(message)],
            "tools": record["tools"],
        })
    return samples


def to_format(sample: dict[str, Any], fmt: str) -> dict[str, Any]:
    if fmt == "trl":
        return {"prompt": sample["prompt"], "completion": sample["completion"], "tools": sample["tools"]}
    if fmt == "mlx":
        return {"messages": sample["prompt"] + sample["completion"], "tools": sample["tools"]}
    raise ValueError(fmt)


def check_prefix_consistency(render: Render, sample: dict[str, Any]) -> list[str]:
    """Problems found; empty means the loss mask will land exactly on the completion."""
    problems = []
    prompt_text = render(sample["prompt"], sample["tools"], True)
    full_text = render(sample["prompt"] + sample["completion"], sample["tools"], False)
    if not full_text.startswith(prompt_text):
        problems.append("rendered prompt is not a prefix of the rendered conversation")
        return problems
    target = full_text[len(prompt_text):]
    if EOS not in target:
        problems.append(f"supervised span does not contain {EOS}")
    for message in sample["prompt"]:
        if message["role"] == "tool" and message["content"] and message["content"] in target:
            problems.append("a tool observation falls inside the supervised span")
    return problems


def supervised_size(sample: dict[str, Any], count: Callable[[str], int] = len) -> int:
    return count(canonical_json(sample["completion"]))


def match_budgets(sets: dict[str, list[dict[str, Any]]], seed: int, tolerance: float = 0.05) -> dict[str, Any]:
    """Equal sample counts across groups; report whether supervised size is within tolerance."""
    n = min(len(samples) for samples in sets.values())
    matched = {}
    for name, samples in sets.items():
        rng = random.Random(f"budget:{name}:{seed}")
        keep = sorted(rng.sample(range(len(samples)), n))
        matched[name] = [samples[i] for i in keep]
    sizes = {name: sum(supervised_size(s) for s in samples) for name, samples in matched.items()}
    low, high = min(sizes.values()), max(sizes.values())
    return {"samples": matched, "n_per_group": n, "supervised_chars": sizes,
            "within_tolerance": high <= low * (1 + tolerance)}


def build_manifest(dataset_id: str, built: dict[str, Any], samples: list[dict[str, Any]], fmt: str) -> dict[str, Any]:
    exported = [to_format(s, fmt) for s in samples]
    return {
        "dataset_id": dataset_id,
        "format": fmt,
        "policy": built["policy"],
        "seed": built["seed"],
        "content_sha256": content_hash(exported),
        "n_tasks": len({s["task_id"] for s in samples}),
        "n_samples": len(samples),
        "supervised_chars": sum(supervised_size(s) for s in samples),
        "total_chars": sum(len(canonical_json(e)) for e in exported),
        "corrupted_trajectories": built.get("corrupted", 0),
        "reject_counts": built["reject_counts"],
        "weights_sha256": content_hash(built["weights"]),
        "generator_version": GENERATOR_VERSION,
        "verifier_version": VERIFIER_VERSION,
    }


def write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
