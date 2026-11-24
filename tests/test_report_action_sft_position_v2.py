import copy
import json

import pytest

from evidenceloop.report import action_sft_position as v1
from evidenceloop.report import action_sft_position_v2 as v2


def test_rotation_preserves_initial_action_and_all_other_user_content():
    old = v1.manifest()
    fresh = v2.manifest()
    assert len(fresh["matrix"]) == 72
    for before, after in zip(old["matrix"], fresh["matrix"], strict=True):
        canonical_code = next(c["initial"] for c in v1.cases() if c["case_id"] == after["case_id"])
        action = v1.menu_for("canonical")[canonical_code]
        assert v1.menu_for(after["menu_id"])[after["initial_code"]] == action == after["initial_action"]
        restored = after["messages"][1]["content"].replace(
            f"送审前动作 {after['initial_code']}。", f"送审前动作 {canonical_code}。")
        assert restored == before["messages"][1]["content"]
        assert after["messages"][0] == before["messages"][0]
        assert after["gold_action"] == before["gold_action"]
    archive = v1.read_json(v1.ROOT / "reports/report-lab/action-sft-position-v1/manifest.json")
    assert old == archive  # V1 still reproducible, never silently rewritten.


def records(frozen):
    return [{**{k: c[k] for k in ("case_id", "menu_id", "arm", "messages")},
             "answer": c["gold_code"], "attempt": 1} for c in frozen["matrix"]]


def test_missing_duplicate_changed_inputs_and_retries_are_rejected():
    frozen = v2.manifest()
    good = records(frozen)
    assert v2.score(good, frozen)["totals"]["base"]["semantic_action_correct"] == 36
    bad_input = copy.deepcopy(good)
    bad_input[0]["messages"][1]["content"] += "changed"
    retry = copy.deepcopy(good)
    retry[0]["attempt"] = 2
    for rows in (good[:-1], good[:-1] + [good[0]], retry, bad_input):
        with pytest.raises(ValueError):
            v2.score(rows, frozen)


def test_two_invalid_outputs_are_not_consistent_and_freeze_cannot_overwrite(tmp_path):
    frozen = v2.prepare(tmp_path / "first")
    rows = records(frozen)
    for row in rows:
        row["answer"] = ""
    result = v2.score(rows, frozen)
    assert all(t["menu_position_consistent"] == 0 for t in result["totals"].values())
    assert json.loads((tmp_path / "first/manifest.json").read_text()) == frozen
    with pytest.raises(FileExistsError):
        v2.prepare(tmp_path / "first")
