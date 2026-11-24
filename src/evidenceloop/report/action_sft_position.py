"""D22 follow-up: frozen menu-position diagnostic and offline failure-review packet.

The module deliberately prepares and scores records only.  It never imports an
inference backend: a separately authorized runner supplies one first response
per frozen (case, menu, arm) cell.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from evidenceloop.report.action_sft import BASE_SHA, execute, read_json, sha

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "benchmarks/report_sft/menu_position_v1"
SOURCES = ROOT / "benchmarks/report_sft/v1/sources.json"
ARCHIVE = ROOT / "reports/report-lab/action-sft-v1"
ARMS = ("base", "lora")
MENU = {
    "canonical": ("fy25_growth", "fy25_contribution", "fy24_growth", "fy24_contribution", "user_pause", "missing_evidence"),
    "rotated": ("missing_evidence", "fy24_contribution", "user_pause", "fy25_growth", "fy24_growth", "fy25_contribution"),
}
ACTION_TO_CODE = {"fy25_growth": "A", "fy25_contribution": "B", "fy24_growth": "C", "fy24_contribution": "D",
                  "user_pause": "E", "missing_evidence": "F"}
ACTION_TEXT = {"fy25_growth": "FY2025同比", "fy25_contribution": "FY2025贡献", "fy24_growth": "FY2024同比",
               "fy24_contribution": "FY2024贡献", "user_pause": "按用户要求暂停", "missing_evidence": "表中缺少计算所需年度"}


def digest_object(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cases() -> list[dict[str, Any]]:
    return read_json(DATA / "cases.json")


def protocol() -> dict[str, Any]:
    return read_json(DATA / "protocol.json")


def menu_for(menu_id: str) -> dict[str, str]:
    if menu_id not in MENU:
        raise ValueError("unknown menu")
    return {chr(65 + position): action for position, action in enumerate(MENU[menu_id])}


def code_for(menu_id: str, action: str) -> str:
    return next(code for code, name in menu_for(menu_id).items() if name == action)


def messages(case: dict[str, Any], source: dict[str, Any], menu_id: str) -> list[dict[str, str]]:
    menu = menu_for(menu_id)
    choices = "，".join(f"{code}={ACTION_TEXT[action]}" for code, action in menu.items())
    rows = [f"FY20{year}: {source['cells']['S' + year]} / {source['cells']['T' + year]}"
            for year in ("25", "24", "23") if "S" + year in source["cells"]]
    return [{"role": "system", "content": "从六个合法动作中选一个，只输出一个英文字母。菜单：" + choices},
            {"role": "user", "content": f"{source['name']}。每行依次为{source['segment']}与总收入，单位{source['unit']}。\n"
             + "\n".join(rows) + f"\n送审前动作 {case['initial']}。\n" + "\n".join(f"分析师：{turn}" for turn in case["turns"])}]


def check_cases() -> None:
    rows = cases()
    source_data = read_json(SOURCES)
    if len(rows) != 18 or len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("expected exactly 18 distinct frozen delegations")
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["document"] not in source_data or row["gold_action"] not in ACTION_TO_CODE:
            raise ValueError("invalid case source or action")
        pairs[row["pair_id"]].append(row)
    if len(pairs) != 9 or any(len(pair) != 2 for pair in pairs.values()):
        raise ValueError("expected nine allow/pause pairs")
    for pair in pairs.values():
        if {item["gold_action"] == "user_pause" for item in pair} != {True, False}:
            raise ValueError("each pair needs one permitted result and one required pause")
    for menu_id in MENU:
        if len(set(menu_for(menu_id).values())) != 6:
            raise ValueError("menu must contain each semantic action once")
    if protocol()["max_first_responses"] != len(rows) * len(MENU) * len(ARMS):
        raise ValueError("declared budget does not match frozen matrix")


def manifest() -> dict[str, Any]:
    check_cases()
    rows = cases()
    return {"schema": "action-sft-menu-position/1", "protocol": protocol(), "base_sha256": BASE_SHA,
            "archived_adapter_sha256": read_json(ARCHIVE / "results.json")["adapter_sha256"],
            "cases_sha256": sha(DATA / "cases.json"), "sources_sha256": sha(SOURCES),
            "configuration_sha256": digest_object({"menu": MENU, "arms": ARMS, "first_response_only": True}),
            "expected_first_responses": len(rows) * len(MENU) * len(ARMS),
            "matrix": [{"case_id": case["case_id"], "pair_id": case["pair_id"], "arm": arm, "menu_id": menu_id,
                        "gold_action": case["gold_action"], "gold_code": code_for(menu_id, case["gold_action"]),
                        "messages": messages(case, read_json(SOURCES)[case["document"]], menu_id)}
                       for case in rows for menu_id in MENU for arm in ARMS]}


def prepare(out: Path) -> dict[str, Any]:
    """Write the immutable inference input before a runner is allowed to start."""
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    value = manifest()
    (out / "manifest.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value[key] for key in ("schema", "expected_first_responses", "cases_sha256", "configuration_sha256")}


def normalize_answer(value: Any) -> str | None:
    value = str(value).strip().upper() if value is not None else ""
    return value if len(value) == 1 and value in "ABCDEF" else None


def score(records: list[dict[str, Any]], frozen: dict[str, Any]) -> dict[str, Any]:
    expected = {(r["case_id"], r["menu_id"], r["arm"]): r for r in frozen["matrix"]}
    if len(records) != len(expected):
        raise ValueError("incomplete or duplicate first-response matrix")
    scored = []
    seen = set()
    source_data = read_json(SOURCES)
    by_case = {case["case_id"]: case for case in cases()}
    for record in records:
        key = (record.get("case_id"), record.get("menu_id"), record.get("arm"))
        if key not in expected or key in seen or record.get("attempt") != 1:
            raise ValueError("unexpected, duplicate, or non-first response")
        seen.add(key)
        answer = normalize_answer(record.get("answer"))
        target = expected[key]
        action = menu_for(target["menu_id"]).get(answer) if answer else None
        case = by_case[target["case_id"]]
        receipt = execute(ACTION_TO_CODE[action], source_data[case["document"]]) if action else {"action": "unparseable"}
        semantic_correct = action == target["gold_action"]
        intercepted = receipt.get("action") == "invalid_calculation"
        final_misreport = receipt.get("action") == "compute" and not semantic_correct
        scored.append({"case_id": key[0], "pair_id": target["pair_id"], "arm": key[2], "menu_id": key[1],
                       "answer": answer, "chosen_action": action, "gold_action": target["gold_action"],
                       "semantic_action_correct": semantic_correct, "tool_intercepted": intercepted,
                       "final_misreport": final_misreport, "receipt": receipt, "manual_label": None})
    paired = defaultdict(list)
    for row in scored:
        paired[(row["case_id"], row["arm"])].append(row)
    for rows in paired.values():
        if len(rows) != 2:
            raise ValueError("each arm must answer both menu positions")
        semantic_same = rows[0]["chosen_action"] == rows[1]["chosen_action"]
        for row in rows:
            row["menu_position_consistent"] = semantic_same
    totals = {}
    for arm in ARMS:
        rows = [row for row in scored if row["arm"] == arm]
        totals[arm] = {"n": len(rows), "semantic_action_correct": sum(r["semantic_action_correct"] for r in rows),
                       "menu_position_consistent": sum(r["menu_position_consistent"] for r in rows),
                       "tool_intercepted": sum(r["tool_intercepted"] for r in rows),
                       "final_misreport": sum(r["final_misreport"] for r in rows)}
    base = {(r["case_id"], r["menu_id"]): r for r in scored if r["arm"] == "base"}
    adapter = {(r["case_id"], r["menu_id"]): r for r in scored if r["arm"] == "lora"}
    fixed = sorted(f"{cid}/{menu}" for (cid, menu), row in adapter.items() if row["semantic_action_correct"] and not base[cid, menu]["semantic_action_correct"])
    lost = sorted(f"{cid}/{menu}" for (cid, menu), row in adapter.items() if not row["semantic_action_correct"] and base[cid, menu]["semantic_action_correct"])
    return {"schema": "action-sft-menu-position-results/1", "manifest_configuration_sha256": frozen["configuration_sha256"],
            "n": len(scored), "totals": totals, "paired": {"fixed": fixed, "lost": lost},
            "manual_review": {"submitted": 0, "pass": 0, "fail": 0, "unknown": 0}, "rows": scored}


def legacy_failures() -> dict[str, Any]:
    """Export genuine D22 failures, without relabelling Codex's scoring as independent review."""
    report = read_json(ARCHIVE / "results.json")
    inputs = {r["case_id"]: r["messages"] for line in (ARCHIVE / "predictions.jsonl").read_text().splitlines()
              if (r := json.loads(line))["arm"] == "lora"}
    rows = [row for row in report["rows"] if row["arm"] == "lora" and not row["passed"]]
    exported = []
    for row in rows:
        receipt = row["receipt"]
        exported.append({"case_id": row["case_id"], "document": row["document"], "split": row["split"],
                         "gold_action": row["gold"], "chosen_action": row["choice"], "receipt": receipt,
                         "semantic_action_correct": False, "tool_intercepted": receipt.get("action") == "invalid_calculation",
                         "final_misreport": receipt.get("action") == "compute", "manual_label": None,
                         "independent_reviewer": None, "input_messages": inputs[row["case_id"]]})
    return {"schema": "action-sft-real-failure-export/1", "source_results_sha256": sha(ARCHIVE / "results.json"),
            "source_predictions_sha256": sha(ARCHIVE / "predictions.jsonl"), "n": len(exported),
            "manual_review": {"submitted": 0, "pass": 0, "fail": 0, "unknown": 0}, "rows": exported}


def render_legacy_review(export: dict[str, Any]) -> str:
    items = "".join(f"<section data-case='{escape(r['case_id'], quote=True)}'><h2>{escape(r['case_id'])}</h2>"
                    f"<pre>{escape(chr(10).join(m['role'] + ': ' + m['content'] for m in r['input_messages']))}</pre>"
                    f"<p>原策略选择：{escape(r['chosen_action'])}。工具回执："
                    f"<code>{escape(json.dumps(r['receipt'], ensure_ascii=False))}</code></p>"
                    "<label>你的判断 <select><option value=''>未评</option><option>pass</option><option>fail</option><option>unknown</option>"
                    "</select></label><label>依据 <textarea rows='2'></textarea></label></section>" for r in export["rows"])
    metadata = json.dumps({"source_results_sha256": export["source_results_sha256"],
                           "source_predictions_sha256": export["source_predictions_sha256"]}).replace("<", "\\u003c")
    return ("<!doctype html><meta charset='utf-8'><title>D22 失败离线复核</title><style>body{max-width:860px;margin:auto;font:16px/1.6 system-ui;padding:18px}"
            "section{border-top:1px solid #ccc;padding:10px 0}textarea{display:block;width:95%}pre{white-space:pre-wrap}code{overflow-wrap:anywhere}</style>"
            "<h1>D22 真实失败离线复核</h1><p>尚无独立专家复核。这是定向失败复核，样本不是随机盲抽。原输入表格、指令和回执如下；"
            "请自行核对，不能将机器标签当作人工结论。填写后导出 JSON 保存；刷新页面会清空未导出内容。</p>"
            "<label>复核者标识 <input id='reviewer' autocomplete='off'></label> <button id='export' type='button'>导出复核记录</button>"
            f"<p id='status' role='status'>尚未提交独立人工标注；共 {export['n']} 个失败样本。</p>" + items
            + "<script>const packet=" + metadata + ";document.getElementById('export').onclick=()=>{"
            "const reviewer=document.getElementById('reviewer').value.trim(),status=document.getElementById('status');"
            "const rows=[...document.querySelectorAll('section[data-case]')].map(s=>({case_id:s.dataset.case,"
            "label:s.querySelector('select').value||null,reason:s.querySelector('textarea').value.trim()}));"
            "const selected=rows.filter(r=>r.label);if(!reviewer||!selected.length||selected.some(r=>!r.reason)){"
            "status.textContent='请填写复核者，并为至少一条判断填写依据。';return;}"
            "const data={schema:'action-sft-human-triage/1',...packet,reviewer,created_at:new Date().toISOString(),rows};"
            "const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));"
            "const a=document.createElement('a');a.href=url;a.download='d22-human-triage.json';a.click();"
            "setTimeout(()=>URL.revokeObjectURL(url),1000);status.textContent='已导出 '+selected.length+' 条判断；尚未导入评分。';"
            "};</script>\n")
