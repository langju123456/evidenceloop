import json

import pytest

from evidenceloop.report import action_sft as d22
from evidenceloop.report import action_sft_fit_probe as d26


def test_matrix_is_fixed_complete_and_semantically_reencoded():
    d26.check_protocol()
    rows = d26.matrix()
    assert len(rows) == 64
    assert len({(row["case_id"], row["menu_id"]) for row in rows}) == 64
    assert {row["menu_id"] for row in rows} == {"canonical", "rotated"}
    assert all(row["gold_code"] in d22.CODES for row in rows)


def test_freeze_is_content_checked_and_never_overwritten(tmp_path):
    freeze = d26.freeze(tmp_path / "d26")
    assert d26.verify_freeze(freeze)["arms"] == list(d26.ARMS)
    with pytest.raises(FileExistsError):
        d26.freeze(tmp_path / "d26")
    payload = json.loads(freeze.read_text())
    payload["matrix"] = []
    freeze.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="matrix"):
        d26.verify_freeze(freeze)


def _row(cell, arm, freeze):
    target = d22.CODES.index(cell["gold_code"])
    scores = [-4.0] * 6
    scores[target] = 3.0
    task = next(value for value in d22.examples("train") if value["case_id"] == cell["case_id"])
    source = d22.read_json(d22.DATA / "sources.json")[task["document"]]
    return {**cell, "arm": arm, "attempt": 1, "freeze": d22.sha(freeze),
            "base_sha256": d22.BASE_SHA, "adapter_sha256": d26._adapter_sha(arm),
            "messages": d26.d25.messages(task, source, cell["menu_id"]), "input_tokens": 1,
            "scores": scores, "choice": cell["gold_code"],
            "choice_action": cell["gold_action"], "restricted_correct": True,
            "full_vocab_top": 32 + target, "target_full_vocab_nll": 0.01,
            "target_margin_vs_other_actions": 7.0, "seconds": 0.0}


def test_summarize_requires_full_unique_first_attempt_matrix_and_freezes_next_branch(tmp_path):
    folder = tmp_path / "d26"
    freeze = d26.freeze(folder)
    rows = [_row(cell, arm, freeze) for cell in d26.matrix() for arm in d26.ARMS]
    (folder / "predictions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = d26.summarize(folder, freeze)
    assert result["rows"] == 192
    assert result["d25_supervised_fit"]["restricted_correct"] == 64
    assert "1.7B" in result["d25_supervised_fit"]["next_candidate"]
    (folder / "predictions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows[:-1]))
    with pytest.raises(ValueError, match="incomplete"):
        d26.summarize(folder, freeze)
