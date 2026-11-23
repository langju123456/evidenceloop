"""A one-decision diagnostic, followed by actual bounded Decimal tool execution."""

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from evidenceloop.report.annual import digest, read_json
from evidenceloop.report.evidence_trials import checked_archive, run_paired

ARMS = ("direct", "cells", "metric_tool")
PROMPTS = "benchmarks/report_dev/calculation-arms-v1.json"
REVIEW = "benchmarks/report_dev/calculation-review-v1.json"
SCHEMAS = {
    "direct": '直接给最终百分数。JSON 字段为 value（不含百分号的数字）、pages（页码整数列表）。',
    "cells": '选择原表操作数，工具执行 100 × 分子 / 分母。JSON 字段 numerator 和 denominator 各为一到两个格 ID 的列表；单格取原值，两格按顺序相减。pages 为页码整数列表。只允许给格 ID。',
    "metric_tool": '选择计算函数及参数。JSON 字段 metric（yoy_growth 同比增速，或 share_of_change 增量贡献），series（Services 或 Total），year（目标财年整数），pages（页码整数列表）。增量贡献以所选业务增量除以总收入增量。',
}


def messages(item, arm):
    cells = item["cells"]
    lines = ["第 26 页，Products and Services Performance，单位百万美元。"]
    for prefix, title in (("S", "Services"), ("T", "Total net sales")):
        lines.append(title + " | " + " | ".join(
            f"FY20{y} [{prefix}{y}] {cells[prefix + y]}" for y in ("25", "24", "23")))
    return [{"role":"system", "content":"只用给定证据，只输出一个 JSON 对象。" + SCHEMAS[arm]},
            {"role":"user", "content":item["question"] + "\n" + "\n".join(lines)}]


def calculate(arm, decision, cells):
    """The allowed actions read only the presented table. No reference answers enter."""
    if not isinstance(decision, dict):
        raise ValueError("expected JSON object")
    if arm == "direct":
        text = str(decision["value"])
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
            raise ValueError("expected a plain percentage number")
        return {"tool":None, "value":str(Decimal(text))}
    if arm == "cells":
        def operand(ids):
            if not isinstance(ids, list) or len(ids) not in (1, 2) or not all(isinstance(k,str) and k in cells for k in ids):
                raise ValueError("unknown or missing cell")
            values = [Decimal(cells[k]) for k in ids]
            return values[0] if len(values) == 1 else values[0] - values[1]
        num = operand(decision["numerator"])
        den = operand(decision["denominator"])
    elif arm == "metric_tool":
        year = decision["year"]
        if type(year) is not int or year not in (2025, 2024):
            raise ValueError("available comparisons start in 2024")
        prefix = {"Services":"S","Total":"T"}[decision["series"]]
        y, prior = str(year)[-2:], str(year - 1)[-2:]
        num = Decimal(cells[prefix+y]) - Decimal(cells[prefix+prior])
        if decision["metric"] == "yoy_growth":
            den = Decimal(cells[prefix+prior])
        elif decision["metric"] == "share_of_change":
            den = Decimal(cells["T"+y]) - Decimal(cells["T"+prior])
        else:
            raise ValueError("unrecognized metric")
    else:
        raise ValueError("unrecognized tool")
    if not den:
        raise ValueError("zero denominator")
    value = (100 * num / den).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    return {"tool":arm, "arguments":decision, "numerator":str(num), "denominator":str(den), "value":str(value)}


def run_command(args):
    run_paired(args, ARMS, messages)


def summarize(prompts, review, log):
    tasks = {i["case_id"]:i for i in read_json(prompts)}
    expected = read_json(review)
    if set(expected) != set(tasks):
        raise ValueError("tasks do not match review")
    rows = []
    records, config = checked_archive(prompts, log, ARMS, messages)
    for r in records:
        cid, arm = r["case_id"], r["arm"]
        resp = r.get("response", {})
        receipt, decision, reason, verdict = None, None, None, "unknown"
        if "error" in r:
            reason = r["error"]
        else:
            try:
                if not resp.get("done"):
                    raise ValueError("incomplete model output")
                decision = json.loads(resp["message"]["content"])
                receipt = calculate(arm, decision, tasks[cid]["cells"])
                citations = decision.get("pages")
                supported = (isinstance(citations,list) and all(type(p) is int for p in citations)
                             and set(citations) == {26})
                verdict = "pass" if Decimal(receipt["value"]) == Decimal(expected[cid]) and supported else "fail"
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                reason, verdict = str(exc), "fail"
        rows.append({"case_id":cid, "arm":arm, "run_id":r["run_id"], "decision":decision, "receipt":receipt,
                     "expected":expected[cid], "verdict":verdict, "error":reason, "model_ms":r["latency_ms"],
                     "input_tokens":resp.get("prompt_eval_count"), "output_tokens":resp.get("eval_count")})
    base = {r["case_id"]:r["verdict"] for r in rows if r["arm"]=="direct"}
    summaries = {}
    for arm in ARMS:
        group = [r for r in rows if r["arm"] == arm]
        summaries[arm] = {"n":len(group),"pass":sum(r["verdict"]=="pass" for r in group),
                          "fixed":[r["case_id"] for r in group if base[r["case_id"]]!="pass" and r["verdict"]=="pass"],
                          "lost":[r["case_id"] for r in group if base[r["case_id"]]=="pass" and r["verdict"]!="pass"]}
    return {"model":list(config),"split":"public_dev","raw_sha256":digest(log),"gold_sha256":digest(review),
            "summaries":summaries,"rows":rows}


def summary_command(args):
    print(json.dumps(summarize(Path(args.prompts), Path(args.review), Path(args.log)),ensure_ascii=False,indent=2))
