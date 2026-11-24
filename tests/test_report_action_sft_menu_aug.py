import json

import pytest

from evidenceloop.report import action_sft as d22
from evidenceloop.report import action_sft_menu_aug as d25


def test_menu_plan_is_fixed_balanced_and_semantically_invariant():
    d25.check_data()
    plan = d25.training_plan()
    assert len(plan) == 64
    assert [row["case_index"] for row in plan[:32]] != [row["case_index"] for row in plan[32:]]
    grouped = {}
    for row in plan:
        grouped.setdefault(row["case_id"], []).append(row)
        assert d25.ACTION_BY_CODE[d22.examples("train")[row["case_index"]]["gold"]] == row["gold_action"]
        assert d25.code_for(row["menu_id"], row["gold_action"]) == row["target_code"]
    assert len(grouped) == 32
    assert all({row["menu_id"] for row in rows} == {"canonical", "rotated"} for rows in grouped.values())
    assert {row["menu_id"] for row in plan[:32]} == {"canonical", "rotated"}
    assert [sum(row["menu_id"] == menu for row in plan if row["epoch"] == epoch)
            for epoch in (1, 2) for menu in ("canonical", "rotated")] == [16, 16, 16, 16]


def test_canonical_is_byte_for_byte_d22_and_rotated_only_reencodes_options_initial():
    sources = d22.read_json(d22.DATA / "sources.json")
    for task in d22.examples("train"):
        before = d22.messages(task, sources[task["document"]], "base")
        assert d25.messages(task, sources[task["document"]], "canonical") == before
        rotated = d25.messages(task, sources[task["document"]], "rotated")
        assert rotated[1]["content"].replace(
            f"送审前动作 {d25.code_for('rotated', d25.ACTION_BY_CODE[task['initial']])}。",
            f"送审前动作 {task['initial']}。",
        ) == before[1]["content"]
        assert "分析师：" in rotated[1]["content"] and d25.ACTION_BY_CODE[task["gold"]] in d25.ACTION_TEXT


def test_freeze_is_content_checked_and_never_overwritten(tmp_path):
    folder = tmp_path / "d25"
    frozen = d25.freeze(folder)
    assert d25.verify_freeze(frozen)["updates"] == 64
    with pytest.raises(FileExistsError):
        d25.freeze(folder)
    payload = json.loads(frozen.read_text())
    payload["updates"] = 65
    frozen.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="updates"):
        d25.verify_freeze(frozen)


def test_score_delegates_to_original_gate_and_labels_exposed_sets(monkeypatch, tmp_path):
    freeze = d25.freeze(tmp_path / "d25")
    seen = {}

    def fake(folder, sources, value):
        seen.update(folder=folder, sources=sources, value=value)
        return {"gate_passed": False, "summary": {}}

    monkeypatch.setattr(d22, "summarize", fake)
    monkeypatch.setattr(d25, "verify_training_receipt", lambda folder, path: seen.update(receipt=(folder, path)))
    result = d25.score(tmp_path / "d25", freeze)
    assert result["gate_passed"] is False
    assert result["evaluation_scope"]["holdout"].startswith("exposed-reuse")
    assert seen["value"] == d22.sha(freeze)
    assert seen["receipt"] == (tmp_path / "d25", freeze)


def test_failed_training_is_evidenced_and_cannot_silently_retry(monkeypatch, tmp_path):
    folder = tmp_path / "d25"
    freeze = d25.freeze(folder)

    def fail_before_model(_):
        raise RuntimeError("simulated base validation failure")

    monkeypatch.setattr(d25, "_check_base", fail_before_model)
    with pytest.raises(RuntimeError, match="simulated"):
        d25.train(tmp_path / "base", folder, freeze)
    marker = json.loads((folder / "training-started.json").read_text())
    failure = json.loads((folder / "training-failure.json").read_text())
    assert marker["freeze"] == d22.sha(freeze)
    assert failure["error_type"] == "RuntimeError" and failure["completed_updates"] == 0
    with pytest.raises(FileExistsError, match="never overwrite"):
        d25.train(tmp_path / "base", folder, freeze)


def receipt(folder, freeze):
    plan = d25.training_plan()
    rows = [{**row, "target_token": 32 + d22.CODES.index(row["target_code"]),
             "input_tokens": 12, "loss": 1.25} for row in plan]
    d22.write(folder / "training-started.json", {"freeze": d22.sha(freeze), "base_sha256": d22.BASE_SHA,
                                                   "planned_updates": 64, "steps_file": "training-steps.jsonl"})
    (folder / "training-steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    adapter = folder / "adapter"
    adapter.mkdir()
    (adapter / "adapters.safetensors").write_bytes(b"synthetic adapter")
    d22.write(adapter / "adapter_config.json", d22.CONFIG)
    d22.write(folder / "training.json", {"freeze": d22.sha(freeze), "base_sha256": d22.BASE_SHA,
                                           "seed": d22.SEED, "steps": rows,
                                           "adapter_sha256": d22.sha(adapter / "adapters.safetensors")})
    return rows


def test_training_receipt_requires_exact_plan_log_summary_and_adapter(tmp_path):
    folder = tmp_path / "d25"
    freeze = d25.freeze(folder)
    rows = receipt(folder, freeze)
    assert d25.verify_training_receipt(folder, freeze)["steps"] == rows
    for case in ("missing", "menu", "summary"):
        broken = tmp_path / case
        copied_freeze = d25.freeze(broken)
        copied_rows = receipt(broken, copied_freeze)
        if case == "missing":
            (broken / "training-steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in copied_rows[:-1]))
        elif case == "menu":
            copied_rows[0]["menu_id"] = "rotated"
            (broken / "training-steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in copied_rows))
            summary = d22.read_json(broken / "training.json")
            summary["steps"] = copied_rows
            (broken / "training.json").write_text(json.dumps(summary))
        else:
            summary = d22.read_json(broken / "training.json")
            summary["seed"] = 999
            (broken / "training.json").write_text(json.dumps(summary))
        with pytest.raises(ValueError):
            d25.verify_training_receipt(broken, copied_freeze)
