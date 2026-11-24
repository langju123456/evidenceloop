"""D24: rotate menu codes while preserving the initial business action."""
from __future__ import annotations

import json
from pathlib import Path

from evidenceloop.report import action_sft_position as v1


def manifest():
    frozen = v1.manifest()
    frozen["schema"] = "action-sft-menu-position/2"
    frozen["protocol"] = {**frozen["protocol"], "protocol": "D24-menu-position-v2",
        "initial_action_invariant": True, "paired_invalid_answers_are_consistent": False}
    cases = {r["case_id"]: r for r in v1.cases()}
    for cell in frozen["matrix"]:
        old = cases[cell["case_id"]]["initial"]
        semantic = v1.menu_for("canonical")[old]
        code = v1.code_for(cell["menu_id"], semantic)
        text = cell["messages"][1]["content"]
        assert text.count(f"送审前动作 {old}。") == 1
        cell["messages"][1]["content"] = text.replace(f"送审前动作 {old}。", f"送审前动作 {code}。")
        cell.update(initial_action=semantic, initial_code=code)
    frozen["configuration_sha256"] = v1.digest_object({"protocol": frozen["protocol"], "matrix": frozen["matrix"]})
    return frozen


def prepare(out: Path):
    out.mkdir(parents=True, exist_ok=False)
    frozen = manifest()
    (out / "manifest.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n")
    return frozen


def score(records, frozen):
    if frozen != manifest():
        raise ValueError("D24 sources or input contract changed")
    expected = {(c["case_id"], c["menu_id"], c["arm"]): c["messages"] for c in frozen["matrix"]}
    for row in records:
        if row.get("messages") != expected.get((row.get("case_id"), row.get("menu_id"), row.get("arm"))):
            raise ValueError("recorded messages do not match frozen input")
    result = v1.score(records, frozen)
    result["schema"] = "action-sft-menu-position-results/2"
    # Two unparseable outputs must not count as stable semantic choices.
    for row in result["rows"]:
        if row["chosen_action"] is None:
            row["menu_position_consistent"] = False
    for arm in v1.ARMS:
        result["totals"][arm]["menu_position_consistent"] = sum(
            r["menu_position_consistent"] for r in result["rows"] if r["arm"] == arm)
    return result
