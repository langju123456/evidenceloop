import json

import pytest

from evidenceloop.report import revisions as rev


def test_blind_input_and_intermediate_turn_ablation():
    tasks = rev.read_json(rev.QUESTIONS)
    refs = rev.read_json(rev.REFERENCE)
    assert len(tasks) == len(refs) == 8
    for item in tasks:
        single = rev.messages(item, "last")
        history = rev.messages(item, "history")
        patch = rev.messages(item, "patch")
        assert history[1] == patch[1]
        assert (single == history) == (len(item["turns"]) == 1)
        if "value" in refs[item["case_id"]]:
            for arm in rev.ARMS:
                assert refs[item["case_id"]]["value"] not in json.dumps(rev.messages(item, arm))


def test_patch_executes_against_saved_form_and_checks_the_actual_denominator():
    case = rev.read_json(rev.QUESTIONS)[3]
    gold = rev.read_json(rev.REFERENCE)[case["case_id"]]
    decision = {"action":"compute", "changes":{"year":2025, "metric":"yoy_growth"}, "pages":[65]}
    raw = {"case_id":case["case_id"], "arm":"patch", "latency_ms":10, "run_id":"probe",
           "response":{"done":True, "message":{"content":json.dumps(decision)}}}
    cells = rev.read_json(rev.SOURCE)["cells"]
    correct = rev.evaluate(raw, case, gold, cells)
    assert correct["verdict"] == "pass" and correct["executed"]["receipt"]["denominator"] == "5431"
    decision["changes"].pop("year")
    raw["response"]["message"]["content"] = json.dumps(decision)
    wrong = rev.evaluate(raw, case, gold, cells)
    assert wrong["verdict"] == "fail" and not wrong["checks"]["year"]
    raw["error"] = "timeout"
    assert rev.evaluate(raw, case, gold, cells)["verdict"] == "unknown"


def test_hold_does_not_accept_a_hidden_calculation():
    with pytest.raises(ValueError, match="invalid hold"):
        rev.execute({"action":"hold", "reason":"user_paused", "value":12}, "history", {}, {})


def test_archived_actions_replay_to_the_checked_in_report():
    folder = rev.ROOT / "reports/report-lab"
    result = rev.read_json(folder / "oracle-revision-results-v1.json")
    logfile = folder / "oracle-revision-trials-v1.jsonl"
    records, model = rev.checked_archive(rev.QUESTIONS, logfile, rev.ARMS, rev.messages,
                                         split=rev.SPLIT, freeze=result["freeze_commit"])
    gold = rev.read_json(rev.REFERENCE)
    cases = {q["case_id"]: q for q in rev.read_json(rev.QUESTIONS)}
    cells = rev.read_json(rev.SOURCE)["cells"]
    assert model == rev.MODEL and len(records) == 24
    assert result["raw_sha256"] == rev.digest(logfile)
    assert [rev.evaluate(r, cases[r["case_id"]], gold[r["case_id"]], cells) for r in records] == result["rows"]
    for totals in result["summary"].values():
        assert totals["pass"] + totals["fail"] + totals["unknown"] == totals["n"] == 8
        assert totals["pass"] == totals["compute_pass"] + totals["hold_pass"]
