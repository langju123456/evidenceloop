import json
from pathlib import Path

import pytest

from evidenceloop.report.annual import compare, extract_claim, read_json, read_lines, score


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "benchmarks/report_dev/v1"


def test_checked_in_comparison_is_reproducible():
    results = compare(DATA)
    assert results == read_json(ROOT / "reports/report-lab/scoring-v1.json")
    indexed = {r["run_id"]: r for r in results["rows"]}
    real_error = indexed["e1df2a4553e44125befe1d3fe973d529"]
    assert real_error["scores"]["cited"] == "pass"
    assert real_error["scores"]["grounded"] == "fail"
    assert indexed["annual-unread"]["scores"]["grounded"] == "unknown"
    assert indexed["annual-wrong-unread"]["checks"]["page_support"] == "unknown"
    assert indexed["annual-wrong-unread"]["scores"]["grounded"] == "fail"
    assert indexed["quarter-header-missing"]["scores"]["grounded"] == "unknown"


def test_normalize_units_and_abstain_on_multiple_amounts():
    case = read_json(DATA / "cases.json")["catl.annual"]
    sources = read_json(DATA / "sources.json")
    row = read_lines(DATA / "observations.jsonl")[0]
    row.update(answer="1,332.19982 亿元。", citations=[{"doc":"catl", "page":11}])
    assert score(case, row, sources)["scores"]["grounded"] == "pass"
    assert extract_claim("1332 亿元或 500 千元") is None


def test_reviewer_cannot_silently_drop_an_observation(tmp_path):
    for file in DATA.iterdir():
        if file.is_file():
            (tmp_path / file.name).write_bytes(file.read_bytes())
    gold = read_json(tmp_path / "review.json")
    gold.pop("annual-unread")
    (tmp_path / "review.json").write_text(json.dumps(gold))
    with pytest.raises(ValueError, match="one-to-one"):
        compare(tmp_path)
