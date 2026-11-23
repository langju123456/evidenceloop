from evidenceloop.report import action_sft as sft


def test_group_isolation_and_inputs_never_contain_gold_field():
    sft.check_data()
    sources = sft.read_json(sft.DATA / "sources.json")
    for split in ("train", *sft.EVAL):
        for task in sft.examples(split):
            source = sources[task["document"]]
            modified = dict(task, gold="different")
            assert sft.messages(task, source, "base") == sft.messages(modified, source, "lora")
            assert sft.messages(task, source, "coached")[1] == sft.messages(task, source, "base")[1]


def test_frozen_financial_references_and_missing_year():
    refs = sft.read_json(sft.DATA / "finance-reference.json")
    sources = sft.read_json(sft.DATA / "sources.json")
    for doc, codes in refs.items():
        for code, value in codes.items():
            assert sft.execute(code, sources[doc])["value"] == value
    assert sft.execute("C", sources["tencent"])["action"] == "invalid_calculation"
    assert sft.execute("D", sources["moutai"])["action"] == "invalid_calculation"
    assert sft.execute("E", {}) != sft.execute("F", {})


def test_trained_archive_replays_including_refusals_and_returned_wrong_year():
    folder = sft.ROOT / "reports/report-lab/action-sft-v1"
    report = sft.read_json(folder / "results.json")
    replay = sft.summarize(folder, sft.read_json(sft.DATA / "sources.json"), report["freeze"])
    assert replay == report
    attempts = [r for r in replay["rows"] if r["arm"] == "lora" and r["split"] == "holdout"]
    assert len(attempts) == 18 and not replay["gate_passed"]
    pair = {r["case_id"]: r for r in attempts if r["case_id"] in {"moutai-05", "moutai-09"}}
    assert pair["moutai-05"]["passed"] and not pair["moutai-09"]["passed"]
    assert pair["moutai-05"]["receipt"] == pair["moutai-09"]["receipt"]
    assert pair["moutai-09"]["receipt"]["value"] == "10.86"
