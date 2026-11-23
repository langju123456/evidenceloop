from decimal import Decimal

import pytest

from evidenceloop.report.calculation import calculate


CELLS = {"S25":"109158", "S24":"96169", "T25":"416161", "T24":"391035"}


def test_cell_and_business_tools_preserve_explicit_denominator():
    selected = calculate("cells", {"numerator":["S25","S24"],"denominator":["T25","T24"]}, CELLS)
    named = calculate("metric_tool", {"metric":"share_of_change","series":"Services","year":2025}, CELLS)
    assert (named["numerator"], named["denominator"], named["value"]) == ("12989","25126","51.70")
    assert selected["value"] == named["value"]
    growth = calculate("metric_tool", {"metric":"yoy_growth","series":"Services","year":2025}, CELLS)
    assert Decimal(growth["value"]) == Decimal("13.51")


def test_calculator_refuses_bad_operands_and_zero_denominator():
    with pytest.raises(ValueError, match="cell"):
        calculate("cells", {"numerator":["not-in-table"],"denominator":["S24"]}, CELLS)
    with pytest.raises(ValueError, match="zero denominator"):
        calculate("cells", {"numerator":["S25","S24"],"denominator":["T25","T25"]}, CELLS)


def test_stored_tool_receipts_replay_exactly():
    import json
    from pathlib import Path
    from evidenceloop.report import calculation

    root = Path(__file__).resolve().parents[1]
    logs = root / "reports/report-lab"
    result = calculation.summarize(root / calculation.PROMPTS, root / calculation.REVIEW,
                                   logs / "calculation-trials-v1.jsonl")
    assert result == json.loads((logs / "calculation-results-v1.json").read_text())
    assert result["summaries"]["cells"]["lost"] == ["apple.2025.growth"]


@pytest.mark.parametrize("tamper", ["run_id","model","missing_response"])
def test_calculation_refuses_altered_archive(tmp_path, tamper):
    import json
    from pathlib import Path
    from evidenceloop.report import calculation

    root = Path(__file__).resolve().parents[1]
    lines = (root / "reports/report-lab/calculation-trials-v1.jsonl").read_text().splitlines()
    row = json.loads(lines[0])
    if tamper == "run_id":
        row["run_id"] = "wrong-attempt"
    elif tamper == "model":
        row["response"]["model"] = "other-model"
    else:
        del row["response"]
    lines[0] = json.dumps(row)
    archive = tmp_path / "edited.jsonl"
    archive.write_text("\n".join(lines))
    with pytest.raises(ValueError, match="changed experiment"):
        calculation.summarize(root / calculation.PROMPTS, root / calculation.REVIEW, archive)
