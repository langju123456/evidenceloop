from decimal import Decimal, ROUND_HALF_UP

import pytest

from evidenceloop.report import calculation, issuer_holdout as hold
from evidenceloop.report.annual import read_json


def test_frozen_case_matrix_and_reference_from_reported_amounts():
    prompts = read_json(hold.ROOT / hold.DATA / "questions.json")
    gold = read_json(hold.ROOT / hold.DATA / "references.json")
    assert len(prompts) == len(gold) == 8
    for row in prompts:
        cid = row["case_id"]
        issuer, year, metric = cid.split(".")
        assert issuer == row["document"] and issuer in {"cisco", "dell"}
        current = year[-2:]
        prior = str(int(year) - 1)[-2:]
        c = {k: Decimal(v) for k, v in row["cells"].items()}
        ds = c["S"+current] - c["S"+prior]
        dt = c["T"+current] - c["T"+prior]
        ratio = ds / (dt if metric == "contribution" else c["S"+prior])
        assert (100 * ratio).quantize(Decimal(".01"), rounding=ROUND_HALF_UP) == Decimal(gold[cid])
        for arm in calculation.ARMS:
            prompt = calculation.messages(row, arm)[1]["content"]
            assert gold[cid] not in prompt and "Apple" not in prompt
            assert f'第 {row["page"]} 页' in prompt


def test_old_apple_input_still_matches_immutable_archive():
    root = hold.ROOT
    result = calculation.summarize(root / calculation.PROMPTS, root / calculation.REVIEW,
                                   root / "reports/report-lab/calculation-trials-v1.jsonl")
    assert result == read_json(root / "reports/report-lab/calculation-results-v1.json")


def test_freeze_refuses_short_sha():
    with pytest.raises(ValueError, match="full preregistration"):
        hold.check_freeze("6a1adcd")


def test_observable_wrong_year_and_missing_citation_remain_separate():
    row = {"case_id": "cisco.2024.contribution", "arm": "metric_tool", "expected": "-21.72", "verdict": "fail",
           "receipt": {"value": "17.4"}, "decision": {"year": 2025, "series": "Services",
                                                    "metric": "share_of_change", "pages": [26]}}
    assert hold.diagnose(row, {"page": 57}) == ["citation_does_not_locate_table", "wrong_fiscal_year"]
