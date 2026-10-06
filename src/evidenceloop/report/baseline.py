"""Baseline / leaderboard report. Every number comes from eval records, never typed by hand."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

CHECKS = ("numeric_pass", "unit_pass", "provenance_pass", "state_pass", "permission_pass")


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "0/0"


def summarize(evals: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(evals)
    failures = [e for e in evals if not e["task_success"]]
    numeric_failures = [e for e in failures if e["failure"] and not e["checks"]["numeric_pass"]]
    matched = [e for e in numeric_failures if e["failure"]["matched_error_paths"]]
    by_bucket: dict[str, list[bool]] = defaultdict(list)
    for e in evals:
        by_bucket[e["bucket"]].append(e["task_success"])
    return {
        "n": n,
        "success": sum(e["task_success"] for e in evals),
        "checks": {c: sum(e["checks"][c] for e in evals) for c in CHECKS},
        "primary": Counter(e["failure"]["primary"] for e in failures if e["failure"]),
        "numeric_failures": len(numeric_failures),
        "numeric_failures_matched": len(matched),
        "by_bucket": {b: (sum(v), len(v)) for b, v in sorted(by_bucket.items())},
        "grounding_violations": sum(1 for e in evals if e.get("grounding_violations")),
        "reply_inconsistent": sum(1 for e in evals if not e["reply"]["consistent"]),
        "mean_turns": sum(e["turns"] or 0 for e in evals) / n if n else 0,
        "modes": Counter(e.get("execution_mode") for e in evals),
    }


def render_markdown(title: str, runs: dict[str, list[dict[str, Any]]]) -> str:
    lines = [f"# {title}", ""]
    names = list(runs)
    summaries = {name: summarize(evals) for name, evals in runs.items()}
    lines += ["| 指标 | " + " | ".join(names) + " |", "| --- |" + " --- |" * len(names)]
    lines.append("| 成功数/总数 | " + " | ".join(_pct(s["success"], s["n"]) for s in summaries.values()) + " |")
    for check in CHECKS:
        lines.append(f"| {check} | " + " | ".join(_pct(s["checks"][check], s["n"]) for s in summaries.values()) + " |")
    lines.append("| 数值失败中可归因到错误路径 | " + " | ".join(
        _pct(s["numeric_failures_matched"], s["numeric_failures"]) for s in summaries.values()) + " |")
    lines.append("| 有未溯源参数的轨迹 | " + " | ".join(_pct(s["grounding_violations"], s["n"]) for s in summaries.values()) + " |")
    lines.append("| 回复与状态不一致 | " + " | ".join(_pct(s["reply_inconsistent"], s["n"]) for s in summaries.values()) + " |")
    lines.append("| 平均轮数 | " + " | ".join(f"{s['mean_turns']:.1f}" for s in summaries.values()) + " |")
    for name, s in summaries.items():
        lines += ["", f"## {name}：失败类别（主类别）", "", "| 类别 | 数量 |", "| --- | --- |"]
        lines += [f"| {cat} | {count} |" for cat, count in s["primary"].most_common()] or ["| （无失败） | 0 |"]
        lines += ["", f"## {name}：按难度分桶", "", "| 分桶 | 成功 |", "| --- | --- |"]
        lines += [f"| `{b}` | {_pct(ok, tot)} |" for b, (ok, tot) in s["by_bucket"].items()]
        if s["modes"].get("mock"):
            lines += ["", f"> 注意：{name} 含 {s['modes']['mock']} 条 mock 轨迹，只能用于工程测试，不能当模型能力。"]
    return "\n".join(lines) + "\n"
