"""Evaluate one decision on a saved analyst brief after one or two scripted amendments."""

import argparse
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from evidenceloop.report import calculation
from evidenceloop.report.annual import digest, read_json
from evidenceloop.report.evidence_trials import checked_archive, run_paired

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "benchmarks/report_revision/v1"
QUESTIONS = DATA / "questions.json"
REFERENCE = DATA / "reference.json"
SOURCE = DATA / "source.json"
ARMS = ("last", "history", "patch")
MODEL = ("forgeflow-qwen3-8b-ctx16k:latest", "7ef4ca800d20a0ceaca9c42647f7626e6174aa47a5b32cbbc70276561557eaa5", "0.32.1")
SPLIT = "oracle_revision_probe_v1"
FILES = (QUESTIONS, REFERENCE, SOURCE, Path(__file__).resolve(), ROOT / "docs/report-lab/09-revisions.md",
         *(ROOT / "src/evidenceloop/report" / f for f in ("calculation.py", "evidence_trials.py", "annual.py")))


def frozen(commit):
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("supply the full preregistration SHA")
    for path in FILES:
        rel = path.relative_to(ROOT).as_posix()
        raw = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"])
        if raw != path.read_bytes():
            raise ValueError(f"changed since freeze: {rel}")


def messages(item, arm):
    source = read_json(SOURCE)
    cells = source["cells"]
    lines = [
        f'{source["issuer"]} FY2025 {source["table"]}，印刷页 {source["printed_page"]}，单位百万美元。',
        "财年 | FY2025 | FY2024 | FY2023",
        "Services | " + " | ".join(cells[f"S{y}"] for y in (25, 24, 23)),
        "Total revenues | " + " | ".join(cells[f"T{y}"] for y in (25, 24, 23)),
        "送审前表单：" + json.dumps(item["initial"], ensure_ascii=False),
    ]
    turns = item["turns"][-1:] if arm == "last" else item["turns"]
    lines += ["分析师：" + t for t in turns]
    base = ("根据可见的送审前表单与分析师后续消息交出当前最终决定。只处理 Services 收入。"
            "yoy_growth 是服务收入同比，share_of_change 是服务收入净变动占公司总收入净变动。"
            "需要相邻两年的原表金额。百分数由程序计算。只输出一个 JSON 对象。"
            '如果用户叫停或证据缺期，只输出 {"action":"hold","reason":"user_paused 或 missing_evidence"}。')
    schema = ('如果可算，输出 {"action":"compute","changes":{...},"pages":[印刷页码]}。'
              'changes 只放相对送审前需要改变的 year（整数）或 metric（指标英文名），未变时可用空对象。'
              if arm == "patch" else
              '如果可算，输出 {"action":"compute","year":财年整数,"metric":"指标英文名","pages":[印刷页码]}。')
    return [{"role": "system", "content": base + schema}, {"role": "user", "content": "\n".join(lines)}]


def execute(decision, arm, initial, cells):
    if not isinstance(decision, dict):
        raise ValueError("invalid decision")
    action = decision.get("action")
    if action == "hold":
        if set(decision) != {"action", "reason"} or decision["reason"] not in ("user_paused", "missing_evidence"):
            raise ValueError("invalid hold")
        return dict(decision)
    if action != "compute":
        raise ValueError("unknown action")
    if arm == "patch":
        changes = decision.get("changes")
        if set(decision) != {"action", "changes", "pages"} or not isinstance(changes, dict) or set(changes) - {"metric", "year"}:
            raise ValueError("invalid changes object")
        state = {**initial, **changes}
    else:
        if set(decision) != {"action", "metric", "year", "pages"}:
            raise ValueError("invalid replacement object")
        state = {k: decision[k] for k in ("metric", "year")}
    pages = decision["pages"]
    if not isinstance(pages, list) or not all(type(p) is int for p in pages):
        raise ValueError("invalid citation")
    args = {**state, "series": "Services"}
    receipt = calculation.calculate("metric_tool", args, cells)
    return {"action": action, **state, "pages": pages, "receipt": receipt}


def evaluate(row, case, gold, cells):
    response = row.get("response", {})
    outcome = {"case_id": row["case_id"], "arm": row["arm"], "run_id": row["run_id"],
               "reference": gold, "decision": None, "executed": None, "checks": {},
               "latency_ms": row["latency_ms"], "input_tokens": response.get("prompt_eval_count"),
               "output_tokens": response.get("eval_count")}
    if "error" in row:
        return dict(outcome, verdict="unknown", error=row["error"])
    try:
        if not response.get("done") or response.get("done_reason") == "length":
            raise ValueError("incomplete response")
        decision = json.loads(response["message"]["content"])
        outcome["decision"] = decision
        actual = execute(decision, row["arm"], case["initial"], cells)
        outcome["executed"] = actual
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return dict(outcome, verdict="fail", error=str(exc))
    checks = {"action": actual["action"] == gold["action"]}
    if checks["action"] and actual["action"] == "hold":
        checks["reason"] = actual["reason"] == gold["reason"]
    elif checks["action"]:
        checks.update({k: actual[k] == gold[k] for k in ("metric", "year")})
        checks["citation"] = set(actual["pages"]) == {gold["page"]}
        checks.update({k: actual["receipt"][k] == gold[k] for k in ("numerator", "denominator", "value")})
    return dict(outcome, checks=checks, verdict="pass" if all(checks.values()) else "fail")


def score(commit, log):
    frozen(commit)
    records, model = checked_archive(QUESTIONS, log, ARMS, messages, split=SPLIT, freeze=commit)
    if model != MODEL:
        raise ValueError("unexpected inference stack")
    questions = {q["case_id"]: q for q in read_json(QUESTIONS)}
    gold = read_json(REFERENCE)
    if gold.keys() != questions.keys():
        raise ValueError("unmatched references")
    cells = read_json(SOURCE)["cells"]
    rows = [evaluate(r, questions[r["case_id"]], gold[r["case_id"]], cells) for r in records]
    baseline = {r["case_id"]: r["verdict"] for r in rows if r["arm"] == "history"}
    summary = {}
    for arm in ARMS:
        group = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            "n": len(group), **{v: sum(r["verdict"] == v for r in group) for v in ("pass", "fail", "unknown")},
            "compute_pass": sum(r["reference"]["action"] == "compute" and r["verdict"] == "pass" for r in group),
            "hold_pass": sum(r["reference"]["action"] == "hold" and r["verdict"] == "pass" for r in group),
            "fixed_vs_history": [r["case_id"] for r in group if baseline[r["case_id"]] == "fail" and r["verdict"] == "pass"],
            "lost_vs_history": [r["case_id"] for r in group if baseline[r["case_id"]] == "pass" and r["verdict"] != "pass"],
            "model_request_ms": sum(r["latency_ms"] for r in group),
            **{k: sum(r[k] for r in group) if all(type(r[k]) is int for r in group) else None
               for k in ("input_tokens", "output_tokens")},
        }
    patch = summary["patch"]
    gate = bool(patch["compute_pass"] >= 5 and patch["hold_pass"] == 2 and not patch["unknown"]
                and patch["fixed_vs_history"] and not patch["lost_vs_history"])
    return {"freeze_commit": commit, "raw_sha256": digest(log), "source_sha256": digest(SOURCE), "split": SPLIT,
            "model": list(model), "independent_human_reviews": 0, "patch_gate": gate, "summary": summary, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    run.add_argument("--out", required=True)
    rescore = sub.add_parser("score")
    rescore.add_argument("--log", required=True, type=Path)
    for cmd in (run, rescore):
        cmd.add_argument("--freeze", required=True)
    args = parser.parse_args()
    if args.action == "score":
        print(json.dumps(score(args.freeze, args.log), ensure_ascii=False, indent=2))
    else:
        frozen(args.freeze)
        run_paired(SimpleNamespace(model=MODEL[0], prompts=QUESTIONS, out=args.out), ARMS, messages,
                   split=SPLIT, freeze=args.freeze, required_model=MODEL)


if __name__ == "__main__":
    main()
