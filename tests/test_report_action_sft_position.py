from evidenceloop.report import action_sft_position as position


def test_action_parser_rejects_empty_or_multiple_choices():
    for value in (None, "", " ", "AB", "ABCDEF", "A or B", "A."):
        assert position.normalize_answer(value) is None
    assert position.normalize_answer(" b ") == "B"


def test_frozen_matrix_has_nine_allow_pause_pairs_and_72_first_answers():
    position.check_cases()
    frozen = position.manifest()
    assert frozen["expected_first_responses"] == 72
    assert len(frozen["matrix"]) == 72
    assert frozen["matrix"][0]["gold_code"] != next(r for r in frozen["matrix"]
                                                   if r["case_id"] == frozen["matrix"][0]["case_id"] and r["menu_id"] == "rotated")["gold_code"]


def test_score_separates_semantics_position_tool_intercept_and_paired_changes():
    frozen = position.manifest()
    records = []
    for task in frozen["matrix"]:
        answer = task["gold_code"]
        if task["arm"] == "lora" and task["case_id"] == "apple-25-growth-pause" and task["menu_id"] == "rotated":
            answer = position.code_for(task["menu_id"], "fy25_growth")
        records.append({"case_id": task["case_id"], "menu_id": task["menu_id"], "arm": task["arm"], "attempt": 1, "answer": answer})
    scored = position.score(records, frozen)
    assert scored["n"] == 72
    assert scored["totals"]["base"]["semantic_action_correct"] == 36
    assert scored["totals"]["lora"]["semantic_action_correct"] == 35
    assert scored["totals"]["lora"]["final_misreport"] == 1
    assert scored["totals"]["lora"]["menu_position_consistent"] == 34
    assert scored["paired"]["lost"] == ["apple-25-growth-pause/rotated"]
    assert scored["manual_review"]["submitted"] == 0


def test_legacy_failure_export_is_real_archive_and_unreviewed():
    exported = position.legacy_failures()
    # All three D22 evaluation splits are retained: 6 dev, 17 holdout, 6 regression failures.
    assert exported["n"] == 29
    assert exported["manual_review"]["submitted"] == 0
    assert all(row["independent_reviewer"] is None for row in exported["rows"])
    assert any(row["tool_intercepted"] for row in exported["rows"])
    assert "尚无独立专家复核" in position.render_legacy_review(exported)
