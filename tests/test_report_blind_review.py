import json
from pathlib import Path

import pytest

from evidenceloop.cli import main
from evidenceloop.report import blind_review

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "benchmarks/report_dev/v1"
OUT = ROOT / "reports/report-lab"


def sheet():
    rows, _, _, packet = blind_review.load(DATA)
    labels = [dict(key=blind_review.opaque(r["run_id"]), verdict="", reason="") for r in rows]
    labels[0].update(verdict="unknown", reason="测试回执：保留争议")
    return dict(schema="report-review/1", reviewer="scripted-check", packet_id=packet, labels=labels)


def test_review_commands_rebuild_both_public_artifacts(tmp_path, capsys):
    path = tmp_path / "blind.html"
    main(["report", "blind-review", "--out", str(path), "--dataset", str(DATA)])
    assert path.read_bytes() == (OUT / "blind-review.html").read_bytes()
    for r in blind_review.read_lines(DATA / "observations.jsonl"):
        assert r["run_id"] not in path.read_text()
    assert "review_reason" not in path.read_text() and "archived_model" not in path.read_text()
    main(["report", "sample-review", "--dataset", str(DATA)])
    assert json.loads(capsys.readouterr().out) == json.loads((OUT / "review-sampling-v1.json").read_text())


def test_scripted_return_keeps_disagreements_and_unreviewed_distinct(tmp_path, capsys):
    sample = sheet()
    path = tmp_path / "returned.json"
    path.write_text(json.dumps(sample))
    main(["report", "reconcile-review", "--submission", str(path), "--dataset", str(DATA)])
    result = json.loads(capsys.readouterr().out)
    assert (result["reviewed"], result["pending"], result["agreed"]) == (1, 13, 0)
    assert not result["identity_verified"]
    assert result["rows"][0]["returned"] == "unknown"


@pytest.mark.parametrize("bad", ["duplicate", "omission", "reason", "packet", "empty"])
def test_reject_invalid_return(bad):
    data = sheet()
    if bad == "duplicate":
        data["labels"][-1] = data["labels"][0]
    elif bad == "omission":
        data["labels"].pop()
    elif bad == "reason":
        data["labels"][0]["reason"] = " "
    elif bad == "packet":
        data["packet_id"] = "older-dataset"
    else:
        data["labels"][0].update(verdict="", reason="")
    with pytest.raises(ValueError):
        blind_review.reconcile(DATA, data)


def test_individually_issued_keys_hide_public_mapping_and_require_correct_return_map(tmp_path):
    import stat

    path = tmp_path / "coordinator.json"
    blind_review.issue_key(DATA, path)
    private = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        blind_review.issue_key(DATA, path)
    second = tmp_path / "second.json"
    blind_review.issue_key(DATA, second)
    other = json.loads(second.read_text())
    rows, _, _, dataset_id = blind_review.load(DATA)
    packet_id, tokens = blind_review.packet_keys(rows, dataset_id, private)
    assert set(tokens.values()).isdisjoint(other["tokens"].values())
    page = blind_review.render(DATA, private)
    assert not any(blind_review.opaque(r["run_id"]) in page for r in rows)
    response = sheet()
    response["packet_id"] = packet_id
    for r, label in zip(rows, response["labels"]):
        label["key"] = tokens[r["run_id"]]
    for incorrect in (None, other):
        with pytest.raises(ValueError, match="wrong review packet"):
            blind_review.reconcile(DATA, response, incorrect)
    result = blind_review.reconcile(DATA, response, private)
    assert (result["packet_mode"], result["pending"]) == ("private_mapping", 13)
