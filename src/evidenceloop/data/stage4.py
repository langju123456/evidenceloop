"""D14, stage 4: B, C and D trained from W25, and the in-context baseline W+ICL.

build_stage4(): for each seed, B (uniform), C (targeted) and D (unfiltered) are built exactly as `el data build`
builds them, with the warm-up's exclusions (the four frozen splits and every warm-up task), then aligned to one
sample count per seed exactly as `el export sft` aligns them. set_problems() refuses anything that departs from
D14: the task count, D's share of wrong demos (exactly 25%), C and D sharing their tasks, equal sample counts,
supervised size within 5%.

C's and D's sampling depends on W's train_mining run only through the pooled failure rate of each of the six
groups (selection.py), and only C's lineage field (source_failure_ids) names W's failed tasks; the exported
files carry no lineage. So the per-group table in reports/warmup_check_W25.md (D13) fixes the exported data
completely: evals_from_check_report() turns that table into stand-in evals for a CPU dry run, and the hashes
recorded in configs/stage4.json must then match what the real W25 evals give on Kaggle.

icl_tasks(): W+ICL is C's evidence put into the context instead of the weights. Every task of a seed gets the
same text in its system prompt: the first verified demo of C_s whose dataset and protocol ids appear in no
evaluation task, written out the way the model sees tool calls. The system prompt is the only thing changed,
so the message layout, the harness and the frozen verifier are untouched.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from evidenceloop.common import ENV_VERSION, GENERATOR_VERSION, VERIFIER_VERSION, content_hash
from evidenceloop.harness.parser import format_tool_call

from .build import D_CORRUPTION_RATIO, build_training_set
from .export import expand, match_budgets
from .selection import GROUPS, TRAIN_BUCKETS, group_of
from .warmup import check_warmup

SEEDS = (1, 2, 3)  # the build seeds kept free for B, C and D in D11 (warmup.py); also export and training seeds
N_TASKS = 100  # D14: the largest D11 dose, and the only one at which D's 25% is a whole number of tasks
ARMS = {"B": "uniform", "C": "targeted", "D": "unfiltered"}
ICL_K = 1  # demos in the context: one keeps a 12-turn episode inside the 8192-token window (D14)
EVAL_SPLITS = ("validation", "test_id", "test_ood")
STEP_SAMPLES = 16  # samples per optimizer step (D12)
# D12's training settings (train_lora.py defaults) plus one epoch, as for W; the seed is the replicate seed
D12_TRAINING = {"lr": 1e-4, "epochs": 1, "rank": 16, "alpha": 32, "dropout": 0.05, "grad_accum": STEP_SAMPLES,
                "warmup_steps": 5, "max_len": 8192, "max_steps": 0, "fp32": False, "gradient_checkpointing": True,
                "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]}
_RESOURCE_ID = re.compile(r"(?:ds|pr)_[a-z]+_\d+")
_TABLE_ROW = re.compile(r"^\| (\w+)｜(F\d) \| (\d+)/(\d+) \|")

ICL_HEADER = ("下面是一道同类任务的完整做法，已经通过验证，供参考。它用的是另一份数据和另一条规则："
              "里面的资源 ID、版本号、表句柄和数值都只属于那道题，不能用在当前任务里。")


def evals_from_check_report(path: str) -> list[dict[str, Any]]:
    """Stand-in train_mining evals with the per-group successes of a warm-up check report (no GPU needed).
    Failures carry no schema_error, as W25's do not (reports/stage3_train_mining.md), so C's weights are W25's."""
    config = None
    rows = []
    bucket_of_group = {}
    for bucket in TRAIN_BUCKETS:
        bucket_of_group.setdefault(group_of(bucket), bucket)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("- 模型配置："):
                config = line.split("：", 1)[1].strip()
            match = _TABLE_ROW.match(line)
            if not match:
                continue
            units, family, success, n = match.group(1), match.group(2), int(match.group(3)), int(match.group(4))
            group = f"{units}|{family}"
            for i in range(n):
                ok = i < success
                rows.append({"task_id": f"standin:{group}:{i}", "split": "train_mining", "bucket": bucket_of_group[group],
                             "inference_config_hash": config, "termination": "final_answer", "task_success": ok,
                             "failure": None if ok else {"primary": "unknown"}})
    if {group_of(r["bucket"]) for r in rows} != set(GROUPS):
        raise ValueError(f"{path} 里没有完整的六组表")
    return rows


def mining_summary(evals: list[dict[str, Any]]) -> dict[str, Any]:
    """What C and D take from W's train_mining run. W must have passed the D11 check (D13)."""
    result = check_warmup(evals)  # raises ValueError on an incomplete or mixed run
    if not result["passed"]:
        raise ValueError("这份 train_mining 结果没有通过 D11 的达标检查，不是 D13 定下的 W")
    return {"success": result["successes"], "n": result["n"], "shift": round(result["shift"], 6),
            "groups": {g: {"success": row["success"], "n": row["n"]} for g, row in result["groups"].items()}}


def set_problems(built: dict[str, dict[str, Any]], n_tasks: int, ratio: float = D_CORRUPTION_RATIO) -> list[str]:
    """What is wrong with one seed's three built sets; empty when they are what D14 asks for."""
    problems = []
    for arm, data in built.items():
        if len(data["records"]) != n_tasks:
            problems.append(f"{arm} 有 {len(data['records'])} 道题，要求 {n_tasks} 道（被拒：{data['reject_counts']}）")
    wrong = n_tasks * ratio
    if wrong != int(wrong):
        problems.append(f"{n_tasks} 道题的 {ratio:.0%} 不是整数道，D 组的错误示范比例会偏离")
    elif built["D"]["corrupted"] != int(wrong):
        problems.append(f"D 有 {built['D']['corrupted']} 道错误示范，要求 {int(wrong)} 道")
    if built["B"]["corrupted"] or built["C"]["corrupted"]:
        problems.append("B、C 里不能有错误示范")
    if not all(r["verified"] for arm in ("B", "C") for r in built[arm]["records"]):
        problems.append("B、C 的示范必须都通过验证门")
    if [r["task_id"] for r in built["C"]["records"]] != [r["task_id"] for r in built["D"]["records"]]:
        problems.append("C 和 D 必须是同一串题")
    return problems


def build_seed(seed: int, n_tasks: int, evals: list[dict[str, Any]], exclude: set[str]) -> dict[str, Any]:
    built = {arm: build_training_set(policy, seed, n_tasks, evals, exclude_keys=exclude) for arm, policy in ARMS.items()}
    problems = set_problems(built, n_tasks)
    if problems:
        raise ValueError("；".join(problems))
    sets = {f"{arm}{seed}": [s for r in built[arm]["records"] for s in expand(r)] for arm in ARMS}
    matched = match_budgets(sets, seed)  # the same call el export sft makes for these three names and this seed
    if len({len(v) for v in matched["samples"].values()}) != 1:
        raise ValueError("对齐后三组的样本数不一样")
    if not matched["within_tolerance"]:
        raise ValueError(f"三组监督部分的大小相差超过 5%：{matched['supervised_chars']}")
    return {"built": built, "matched": matched, "built_samples": {name: len(v) for name, v in sets.items()}}


def resource_ids(record_or_task: dict[str, Any]) -> set[str]:
    if "resources" in record_or_task:
        res = record_or_task["resources"]
        return set(res["datasets"]) | set(res["protocols"]) | set(_RESOURCE_ID.findall(record_or_task["prompt"]))
    return set(_RESOURCE_ID.findall(json.dumps(record_or_task["messages"], ensure_ascii=False)))


def pick_demos(records: list[dict[str, Any]], eval_tasks: list[dict[str, Any]], k: int = ICL_K) -> list[dict[str, Any]]:
    """The first k verified demos, in build order, that share no dataset or protocol id with any evaluation task:
    a shared id would let a copied version pass the provenance check."""
    taken = set().union(*(resource_ids(t) for t in eval_tasks))
    demos = [r for r in records if r["verified"] and not r["corruption"] and not resource_ids(r) & taken][:k]
    if len(demos) < k:
        raise ValueError(f"只找到 {len(demos)} 条和考题没有共同资源 ID 的示范，要 {k} 条")
    return demos


def render_demo(record: dict[str, Any]) -> str:
    """One demo as text: the task, each tool call as the model writes it, each tool result, the final reply."""
    messages = record["messages"]
    lines = ["【示范任务】", messages[1]["content"], "【示范过程】"]
    for message in messages[2:]:
        if message["role"] == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                lines.append(format_tool_call(call["function"]["name"], call["function"]["arguments"]))
        elif message["role"] == "assistant":
            lines += ["【示范的最终回复】", message["content"]]
        elif message["role"] == "tool":
            lines.append("<tool_response>\n" + message["content"] + "\n</tool_response>")
    lines.append("【示范结束】")
    return "\n".join(lines)


def icl_tasks(tasks: list[dict[str, Any]], demos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same tasks (same task_id, so the frozen private files still score them), with the demos appended to the
    system prompt. Everything else, the user prompt included, is unchanged."""
    block = "\n\n".join([ICL_HEADER] + [render_demo(d) for d in demos])
    if "CANARY-" in block:
        raise ValueError("示范里出现了 canary")
    out = []
    for task in tasks:
        new = copy.deepcopy(task)
        new["system_prompt"] = task["system_prompt"] + "\n\n" + block
        new["icl"] = {"decision": "D14", "demo_task_ids": [d["task_id"] for d in demos], "context_sha256": content_hash(block)}
        out.append(new)
    return out


def stage4_record(mining: dict[str, Any], seeds: dict[int, dict[str, Any]], excluded: dict[str, int],
                  files: dict[str, dict[str, Any]], icl: dict[int, dict[str, Any]], n_tasks: int) -> dict[str, Any]:
    per_seed = {}
    for seed, result in seeds.items():
        matched = result["matched"]
        samples = matched["n_per_group"]
        per_seed[str(seed)] = {
            "arms": {arm: {"tasks": len(result["built"][arm]["records"]), "corrupted": result["built"][arm]["corrupted"],
                           "samples_built": result["built_samples"][f"{arm}{seed}"],
                           "reject_counts": result["built"][arm]["reject_counts"]} for arm in ARMS},
            "samples_per_arm": samples,
            "optimizer_steps": -(-samples // STEP_SAMPLES),
            "supervised_chars": matched["supervised_chars"],
            "trl_sha256": {name: files[f"export_s{seed}/{name}.trl.jsonl"]["sha256"] for name in matched["samples"]},
            "icl": icl[seed],
        }
    return {
        "decision": "D14",
        "generator_version": GENERATOR_VERSION,
        "env_version": ENV_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "start": "W25（D13）",
        "n_tasks": n_tasks,
        "seeds": sorted(seeds),
        "corruption_ratio": D_CORRUPTION_RATIO,
        "icl_k": ICL_K,
        "mining": mining,
        "excluded_from": excluded,
        "per_seed": per_seed,
        "eval_files": {name: info for name, info in files.items() if not name.startswith("export_")},
        "reproducibility": "data/ 不进版本库；el stage4 build 由生成器、参考解法和 W25 在 train_mining 上的分组结果确定性生成，"
                           "重新运行后哈希应与这里一致。",
    }


def record_diffs(old: dict[str, Any], new: dict[str, Any], prefix: str = "") -> list[str]:
    """Paths at which two records differ."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            out += record_diffs(old.get(key), new.get(key), f"{prefix}{key}.")
        return out
    return [] if old == new else [prefix.rstrip(".")]


def training_problems(log: dict[str, Any], data_sha256: str, base_fingerprint: str | None, seed: int,
                      adapter_fingerprint: str | None) -> list[str]:
    """Whether a finished training run is the D14 run for this data (used to skip it when the script resumes)."""
    problems = []
    if log.get("aborted"):
        problems.append(f"训练中途停下：{log['aborted']}")
    if not log.get("adapter_fingerprint") or log.get("adapter_fingerprint") != adapter_fingerprint:
        problems.append("adapter 和训练日志对不上")
    if log.get("data_sha256") != data_sha256:
        problems.append("训练数据不是这一份")
    if base_fingerprint and log.get("base_fingerprint") != base_fingerprint:
        problems.append("不是在 W25 上训的")
    cfg = log.get("config", {})
    wanted = dict(D12_TRAINING, seed=seed)
    wrong = {k: cfg.get(k) for k, v in wanted.items() if cfg.get(k) != v}
    if wrong:
        problems.append(f"训练设置和 D12、D14 不一样：{wrong}")
    return problems
