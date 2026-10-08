"""D11 warm-up: the data that turns the base model into W, and the check that W is a usable start.

build_warmup(): B's uniform sampler with its own build seed, verified demos only. Every task is checked
against the four frozen splits by dedup key, and only the training templates are allowed. The doses are
prefixes of one task list, so a smaller dose is always contained in a larger one.

check_warmup(): on W's train_mining evals, both conditions must hold:
  (1) overall success between 20% and 80%, so there are failures to mine and successes to learn from;
  (2) C's allocation differs from B's by at least 0.10 (total variation distance), so the C-vs-B
      comparison is not run on two copies of the same data. "Half the groups between 20% and 80%" was
      rejected: six groups at 50% each satisfy it, yet C's weights would then be uniform again.
The input is checked first: all of train_mining, each task once, one inference configuration, and no
infra_error (those are re-run with el run before checking), so a partial or mixed run cannot pass.
"""

from __future__ import annotations

import json
import os
from typing import Any

from evidenceloop.tasks.generator import TRAIN_TEMPLATES

from .build import build_training_set
from .selection import GROUPS, allocation_shift, group_of, group_weights, is_infra_error, selection_weights

DOSES = (10, 25, 50, 100)  # 10 is D12's fallback below 25; the larger doses are unchanged
WARMUP_SEED = 900  # B, C and D use small build seeds (1, 2, 3); 900 keeps the warm-up tasks apart
FROZEN_SPLITS = ("train_mining", "validation", "test_id", "test_ood")
TRAIN_MINING_N = 200
SUCCESS_RANGE = (0.20, 0.80)
MIN_SHIFT = 0.10


def frozen_dedup_keys(tasks_dir: str, splits: tuple[str, ...] = FROZEN_SPLITS) -> dict[str, set[str]]:
    keys = {}
    for split in splits:
        path = os.path.join(tasks_dir, f"{split}.private.jsonl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} 不存在：查重需要四个冻结划分都在（先运行 el frozen verify）")
        with open(path, encoding="utf-8") as fh:
            keys[split] = {json.loads(line)["dedup_key"] for line in fh if line.strip()}
    return keys


def build_warmup(tasks_dir: str, seed: int = WARMUP_SEED, doses: tuple[int, ...] = DOSES) -> dict[str, Any]:
    doses = tuple(sorted(doses))
    frozen = frozen_dedup_keys(tasks_dir)
    exclude = set().union(*frozen.values())
    built = build_training_set("uniform", seed, doses[-1], exclude_keys=exclude)
    records = built["records"]
    if len(records) < doses[-1]:
        raise RuntimeError(f"只有 {len(records)} 条示范通过验证，不够最大一档 {doses[-1]} 道")
    templates = {r["recipe_id"].split("-")[0] for r in records}
    if not templates <= set(TRAIN_TEMPLATES):
        raise RuntimeError(f"预热数据用到了训练以外的模板：{sorted(templates - set(TRAIN_TEMPLATES))}")
    return {
        "built": built,
        "doses": {d: records[:d] for d in doses},
        "frozen_splits": {split: len(keys) for split, keys in frozen.items()},
        "excluded_frozen_duplicates": built["reject_counts"].get("excluded", 0),
        "templates": sorted(templates),
    }


def check_inputs(evals: list[dict[str, Any]], expected_n: int = TRAIN_MINING_N) -> list[str]:
    """What is wrong with the evals as input to the check; empty when they are W's full train_mining run."""
    if not evals:
        return ["没有评测结果"]
    problems = []
    splits = sorted({str(e.get("split")) for e in evals})
    if splits != ["train_mining"]:
        problems.append(f"结果要全部来自 train_mining，现在有 {', '.join(splits)}")
    ids = [e["task_id"] for e in evals]
    if len(set(ids)) < len(ids):
        problems.append(f"有 {len(ids) - len(set(ids))} 条结果是重复的题")
    if len(set(ids)) != expected_n:
        problems.append(f"要全部 {expected_n} 道题的结果，现在是 {len(set(ids))} 道")
    hashes = {e.get("inference_config_hash") for e in evals}
    if len(hashes) != 1:
        problems.append(f"结果来自 {len(hashes)} 种模型配置，只能有一种")
    infra = sum(1 for e in evals if is_infra_error(e))
    if infra:
        problems.append(f"有 {infra} 道是运行故障（infra_error）：先用同一条 el run 重跑，再 el eval")
    return problems


def check_warmup(evals: list[dict[str, Any]], expected_n: int = TRAIN_MINING_N,
                 success_range: tuple[float, float] = SUCCESS_RANGE, min_shift: float = MIN_SHIFT) -> dict[str, Any]:
    problems = check_inputs(evals, expected_n)
    if problems:
        raise ValueError("；".join(problems))
    n = len(evals)
    successes = sum(1 for e in evals if e["task_success"])
    rate = successes / n
    groups = {g: {"n": 0, "success": 0} for g in GROUPS}
    for e in evals:
        row = groups[group_of(e["bucket"])]
        row["n"] += 1
        row["success"] += int(bool(e["task_success"]))
    targeted, uniform = selection_weights("targeted", evals), selection_weights("uniform")
    shift = allocation_shift(targeted, uniform)
    reasons = []
    low, high = success_range
    if not low <= rate <= high:
        reasons.append(f"总成功率 {rate:.1%} 不在 {low:.0%}–{high:.0%} 之间")
    if shift < min_shift:
        reasons.append(f"C 和 B 的分配只差 {shift:.3f}，不到 {min_shift:.2f}")
    return {
        "n": n,
        "successes": successes,
        "success_rate": rate,
        "groups": groups,
        "targeted_group_weights": group_weights(targeted),
        "uniform_group_weights": group_weights(uniform),
        "shift": shift,
        "passed": not reasons,
        "reasons": reasons,
        "inference_config_hash": evals[0].get("inference_config_hash"),
        "thresholds": {"success_range": list(success_range), "min_shift": min_shift},
    }


def render_check(result: dict[str, Any], title: str = "预热达标检查（D11）") -> str:
    lines = [f"# {title}", ""]
    verdict = "达标" if result["passed"] else "不达标：" + "；".join(result["reasons"])
    low, high = result["thresholds"]["success_range"]
    lines += [f"- 结论：{verdict}",
              f"- 总成功率：{result['successes']}/{result['n']}（{result['success_rate']:.1%}），要求 {low:.0%}–{high:.0%}",
              f"- C 和 B 的分配之差：{result['shift']:.3f}，要求不小于 {result['thresholds']['min_shift']:.2f}",
              f"- 模型配置：{result['inference_config_hash']}"]
    lines += ["", "| 组（单位档｜题型） | 成功 | C 的题量占比 | B 的题量占比 |", "| --- | --- | --- | --- |"]
    for g in GROUPS:
        row = result["groups"][g]
        lines.append(f"| {g.replace('|', '｜')} | {row['success']}/{row['n']} | {result['targeted_group_weights'][g]:.1%} | "
                     f"{result['uniform_group_weights'][g]:.1%} |")
    return "\n".join(lines) + "\n"
