"""D14's comparisons and verdicts, computed from eval records only (nothing typed by hand).

For a comparison X vs Y on one split: every row must be one complete run (all tasks of the split, each once, one
inference configuration, no infra_error); a row that is not is reported as missing and left out. A seed counts
when both X and Y are complete on it (a single-run row such as W serves every seed). Per task, the difference is
the mean over the counted seeds of X's success minus Y's; the effect is its mean over tasks, in percentage
points, with a 95% interval from a paired bootstrap over tasks (BOOTSTRAP resamples, fixed seed).

Verdict (D14): "X 更好" when the interval lies above 0 and X beat Y on every counted seed; "X 更差" when the
interval lies below 0 and X lost on every counted seed; otherwise "分不出". Fewer than MIN_SEEDS counted seeds:
no verdict.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from evidenceloop.data.selection import is_infra_error

COMPARISONS = (
    ("H1（主假设）", "C", "B", "按失败定向选题 vs 均匀选题"),
    ("H2", "C", "D", "示范全部过验证门 vs 混入 25% 不经验证的错误示范"),
    ("H3", "C", "ICL", "C 的证据写进参数 vs 放进上下文"),
    ("相对 W", "B", "W", "B 相对起点 W 的提升"),
    ("相对 W", "C", "W", "C 相对起点 W 的提升"),
    ("相对 W", "D", "W", "D 相对起点 W 的提升"),
    ("相对 W", "ICL", "W", "上下文示范相对 W 的提升"),
)
ARM_ORDER = ("A", "W", "B", "C", "D", "ICL")
MIN_SEEDS = 2
BOOTSTRAP = 10_000
PRIMARY_SPLIT = "test_id"


def run_problems(evals: list[dict[str, Any]], split: str, expected_n: int) -> list[str]:
    if not evals:
        return ["没有评测结果"]
    problems = []
    splits = sorted({str(e.get("split")) for e in evals})
    if splits != [split]:
        problems.append(f"结果要全部来自 {split}，现在有 {', '.join(splits)}")
    ids = [e["task_id"] for e in evals]
    if len(set(ids)) < len(ids):
        problems.append(f"有 {len(ids) - len(set(ids))} 条重复")
    if len(set(ids)) != expected_n:
        problems.append(f"要 {expected_n} 道题，现在是 {len(set(ids))} 道")
    if len({e.get("inference_config_hash") for e in evals}) != 1:
        problems.append("结果来自不止一种模型配置")
    infra = sum(1 for e in evals if is_infra_error(e))
    if infra:
        problems.append(f"有 {infra} 道运行故障")
    return problems


def _success(evals: list[dict[str, Any]]) -> dict[str, int]:
    return {e["task_id"]: int(bool(e["task_success"])) for e in evals}


def bootstrap_interval(diffs: list[float], resamples: int = BOOTSTRAP, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def compare_arms(x: dict[Any, dict[str, int]], y: dict[Any, dict[str, int]], resamples: int = BOOTSTRAP) -> dict[str, Any]:
    """x, y: seed (None for a single run) -> {task_id: 0/1}, complete runs only."""
    if None in y:
        seeds = sorted(x)
        pairs = {s: (x[s], y[None]) for s in seeds}
    else:
        seeds = sorted(set(x) & set(y))
        pairs = {s: (x[s], y[s]) for s in seeds}
    out: dict[str, Any] = {"seeds": seeds}
    if len(seeds) < MIN_SEEDS:
        out["verdict"] = f"不判定：两边都完整的种子只有 {len(seeds)} 个，至少要 {MIN_SEEDS} 个"
        return out
    tasks = sorted(next(iter(pairs.values()))[0])
    for xs, ys in pairs.values():
        if sorted(xs) != tasks or sorted(ys) != tasks:
            raise ValueError("两边考的不是同一批题")
    per_seed = {s: 100 * (sum(xs.values()) - sum(ys.values())) / len(tasks) for s, (xs, ys) in pairs.items()}
    diffs = [100 * sum(xs[t] - ys[t] for xs, ys in pairs.values()) / len(pairs) for t in tasks]
    effect = sum(diffs) / len(diffs)
    low, high = bootstrap_interval(diffs, resamples)
    if low > 0 and all(d > 0 for d in per_seed.values()):
        verdict = "X 更好"
    elif high < 0 and all(d < 0 for d in per_seed.values()):
        verdict = "X 更差"
    else:
        verdict = "分不出"
    out.update(per_seed=per_seed, effect=effect, interval=(low, high), verdict=verdict, n_tasks=len(tasks))
    return out


def load_rows(rows: dict[str, dict[Any, list[dict[str, Any]] | None]], split: str,
              expected_n: int) -> tuple[dict[str, dict[Any, dict[str, int]]], dict[str, str]]:
    """Complete runs as success maps, and why each other row was left out."""
    usable: dict[str, dict[Any, dict[str, int]]] = defaultdict(dict)
    missing = {}
    for arm, runs in rows.items():
        for seed, evals in runs.items():
            name = arm if seed is None else f"{arm}{seed}"
            if evals is None:
                missing[name] = "没有结果文件（没跑，或没跑成）"
                continue
            problems = run_problems(evals, split, expected_n)
            if problems:
                missing[name] = "；".join(problems)
            else:
                usable[arm][seed] = _success(evals)
    return dict(usable), missing


def _group(bucket: str) -> str:
    family, units = bucket.split("|")[:2]
    return f"{units}｜{family}"


def render(split: str, rows: dict[str, dict[Any, list[dict[str, Any]] | None]], expected_n: int,
           title: str | None = None, resamples: int = BOOTSTRAP) -> str:
    usable, missing = load_rows(rows, split, expected_n)
    primary = split == PRIMARY_SPLIT
    lines = [f"# {title or f'阶段四：{split} 上的对比（D14）'}", ""]
    lines.append("- 主指标是 test_id 上的 task_success；只有 test_id 上 H1 的结论回答主问题。"
                 + ("" if primary else f"本表是 {split}，只作描述，不下结论。"))
    lines.append(f"- 判定（D14）：按题配对，差值取各种子的平均；95% 区间来自对题目的 {resamples} 次自助重抽（种子 0）。"
                 "区间在 0 以上且每个种子都赢，记为“X 更好”；区间在 0 以下且每个种子都输，记为“X 更差”；"
                 f"其余“分不出”；两边都完整的种子少于 {MIN_SEEDS} 个不判定。")
    lines.append("- W = W25（D13）；B、C、D 都是从 W 出发新训的 LoRA，数字是种子。")
    lines.append("")

    seeds = sorted({s for runs in rows.values() for s in runs if s is not None})
    lines += ["## 成功数", "", "| 行 | " + " | ".join(f"种子 {s}" for s in seeds) + " | 单次 / 平均 |",
              "| --- |" + " --- |" * (len(seeds) + 1)]
    for arm in [a for a in ARM_ORDER if a in rows] + [a for a in rows if a not in ARM_ORDER]:
        runs = rows[arm]
        cells = []
        for s in seeds:
            if s not in runs:
                cells.append("")
            else:
                cells.append(f"{sum(usable[arm][s].values())}/{expected_n}" if s in usable.get(arm, {}) else "没有")
        done = list(usable.get(arm, {}).values())
        mean = sum(sum(m.values()) for m in done) / len(done) if done else None
        if mean is None:
            cells.append("没有")
        else:
            count = f"{mean:.0f}" if None in runs else f"{mean:.1f}"
            cells.append(f"{count}/{expected_n}（{mean / expected_n:.1%}）")
        lines.append(f"| {arm} | " + " | ".join(cells) + " |")

    lines += ["", "## 对比", "", "| 编号 | X − Y | 含义 | 用到的种子 | 各种子的差（百分点） | 平均差（百分点） | 95% 区间 | 结论 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for label, x, y, meaning in COMPARISONS:
        if x not in rows or y not in rows:
            continue
        xs, ys = usable.get(x, {}), usable.get(y, {})
        if not xs or not ys:
            lines.append(f"| {label} | {x} − {y} | {meaning} | — | — | — | — | 不判定：有一边没有完整结果 |")
            continue
        result = compare_arms(xs, ys, resamples)
        if "effect" not in result:
            lines.append(f"| {label} | {x} − {y} | {meaning} | {', '.join(map(str, result['seeds'])) or '—'} | — | — | — | {result['verdict']} |")
            continue
        per_seed = ", ".join(f"{d:+.1f}" for d in result["per_seed"].values())
        low, high = result["interval"]
        verdict = result["verdict"] if primary else f"（{result['verdict']}，只作描述）"
        lines.append(f"| {label} | {x} − {y} | {meaning} | {', '.join(map(str, result['seeds']))} | {per_seed} | "
                     f"{result['effect']:+.1f} | [{low:+.1f}, {high:+.1f}] | {verdict} |")

    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    buckets = {}
    for runs in rows.values():
        for evals in runs.values():
            for e in evals or []:
                buckets[e["task_id"]] = e["bucket"]
    for arm, runs in usable.items():
        for success in runs.values():
            for task, ok in success.items():
                groups[_group(buckets[task])][arm].append(ok)
    arms = [a for a in ARM_ORDER if a in usable] + [a for a in usable if a not in ARM_ORDER]
    if groups:
        lines += ["", "## 按组（单位档｜题型）的成功率，各种子合并", "", "| 组 | 题数 | " + " | ".join(arms) + " |",
                  "| --- | --- |" + " --- |" * len(arms)]
        for g in sorted(groups):
            n = len({t for t, b in buckets.items() if _group(b) == g})
            cells = [f"{sum(v) / len(v):.0%}" if (v := groups[g].get(a)) else "—" for a in arms]
            lines.append(f"| {g} | {n} | " + " | ".join(cells) + " |")
    if missing:
        lines += ["", "## 没有算进来的行", ""] + [f"- {name}：{why}" for name, why in sorted(missing.items())]
    return "\n".join(lines) + "\n"
