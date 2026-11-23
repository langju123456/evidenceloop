import json
from pathlib import Path

import pytest

from evidenceloop.report.evidence_trials import DATASET, parse_response, summarize


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports/report-lab/evidence-trials-v1.jsonl"
DATA = ROOT / "benchmarks/report_dev/v1"


def test_transport_and_abstention_remain_separate():
    assert parse_response({"error":"timeout"}) == ("infra_error", None)
    row = {"response":{"done":True, "message":{"content":'{"status":"unknown"}'}}}
    assert parse_response(row)[0] == "abstained"
    row["response"]["message"]["content"] = '{"status":"answered","value":36.8,"unit":"%","pages":[true]}'
    assert parse_response(row)[0] == "invalid"


def test_rescore_complete_and_refuse_changed_prompt(tmp_path):
    actual = summarize(ROOT / DATASET, RAW, DATA)
    assert actual == json.loads((ROOT / "reports/report-lab/evidence-results-v1.json").read_text())
    records = RAW.read_text().splitlines()
    path = tmp_path / "replies.jsonl"
    path.write_text("\n".join(records[:-1]))
    with pytest.raises(ValueError, match="incomplete"):
        summarize(ROOT / DATASET, path, DATA)
    first = json.loads(records[0])
    first["request"]["messages"][1]["content"] += " extra prompt"
    path.write_text("\n".join([json.dumps(first), *records[1:]]))
    with pytest.raises(ValueError, match="changed experiment"):
        summarize(ROOT / DATASET, path, DATA)
