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
