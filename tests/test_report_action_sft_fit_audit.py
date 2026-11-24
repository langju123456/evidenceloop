import pytest

from evidenceloop.report import action_sft as d22
from evidenceloop.report import action_sft_fit_audit as audit
from evidenceloop.report import action_sft_fit_probe as d26


def _raw(cell, arm, freeze):
    target = d22.CODES.index(cell["gold_code"])
    scores = [-2.0] * 6
    scores[target] = 5.0
    choice = cell["gold_code"]
    return {**cell, "arm": arm, "attempt": 1, "freeze": d22.sha(audit.SOURCE_FREEZE),
            "base_sha256": d22.BASE_SHA, "adapter_sha256": d26._adapter_sha(arm), "input_tokens": 4,
            "scores": scores, "choice": choice, "choice_action": "fy25_growth",
            "restricted_correct": True, "target_margin_vs_other_actions": 7.0}


def test_audit_redecodes_rotated_semantics_and_preserves_score_derived_fit_count(monkeypatch):
    freeze = {"matrix": d26.matrix()}
    rows = [_raw(cell, arm, freeze) for cell in d26.matrix() for arm in d26.ARMS]
    corrected, result = audit.audit_payload(rows, freeze)
    rotated = next(row for row in corrected if row["menu_id"] == "rotated" and row["choice"] == "A")
    assert rotated["choice_action"] == "missing_evidence"
    assert result["derived_restricted_correct_by_arm"] == {"base": 64, "d22_lora": 64, "d25_lora": 64}
    assert len(result["stale_choice_action_rows"]) > 0


def test_audit_rejects_margin_or_correctness_that_disagrees_with_raw_logits():
    freeze = {"matrix": d26.matrix()}
    rows = [_raw(cell, arm, freeze) for cell in d26.matrix() for arm in d26.ARMS]
    rows[0]["target_margin_vs_other_actions"] = 0.0
    with pytest.raises(ValueError, match="margin"):
        audit.audit_payload(rows, freeze)
    rows[0]["target_margin_vs_other_actions"] = 7.0
    rows[0]["restricted_correct"] = False
    with pytest.raises(ValueError, match="correctness"):
        audit.audit_payload(rows, freeze)
