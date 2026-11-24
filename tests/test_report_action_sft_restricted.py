import json

import pytest

from evidenceloop.report import action_sft as d22
from evidenceloop.report import action_sft_restricted as d27


def test_plan_and_freeze_keep_d25_controls_and_name_only_loss_change(tmp_path):
    d27.check_protocol()
    payload = d27.freeze_payload()
    assert payload["updates"] == 64 and payload["config"] == d22.CONFIG
    assert len(payload["plan"]) == 64
    assert "restricted" in payload["only_changed_variable"]
    freeze = d27.freeze(tmp_path / "d27")
    assert d27.verify_freeze(freeze)["seed"] == d22.SEED
    with pytest.raises(FileExistsError):
        d27.freeze(tmp_path / "d27")


def _receipt(folder, freeze):
    payload = d22.read_json(freeze)
    rows = []
    for row in payload["plan"]:
        index = d22.CODES.index(row["target_code"])
        rows.append({**row, "target_token": 32 + index, "target_action_index": index,
                     "loss": 1.0, "input_tokens": 7})
    d22.write(folder / "training-started.json", {"freeze": d22.sha(freeze), "base_sha256": d22.BASE_SHA,
              "planned_updates": 64, "steps_file": "training-steps.jsonl", "loss": "restricted_action_cross_entropy"})
    (folder / "training-steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    adapter = folder / "adapter"
    adapter.mkdir()
    (adapter / "adapters.safetensors").write_bytes(b"synthetic adapter")
    d22.write(adapter / "adapter_config.json", d22.CONFIG)
    d22.write(folder / "training.json", {"freeze": d22.sha(freeze), "base_sha256": d22.BASE_SHA,
              "steps": rows, "seed": d22.SEED, "loss": "restricted_action_cross_entropy",
              "runtime": payload["runtime"], "trainable_parameters": 81920, "largest_abs_B": 0.1,
              "adapter_sha256": d22.sha(adapter / "adapters.safetensors")})
    return rows


@pytest.mark.parametrize("field,value", [("runtime", "wrong"), ("trainable_parameters", 1),
                                       ("largest_abs_B", 0), ("largest_abs_B", float("nan"))])
def test_receipt_rejects_changed_training_controls(tmp_path, field, value):
    folder = tmp_path / "d27"
    freeze = d27.freeze(folder)
    _receipt(folder, freeze)
    training = d22.read_json(folder / "training.json")
    training[field] = value
    (folder / "training.json").write_text(json.dumps(training))
    with pytest.raises(ValueError, match="runtime|update receipt"):
        d27.verify_training_receipt(folder, freeze)


def test_semantic_decoder_is_frozen(tmp_path, monkeypatch):
    freeze = d27.freeze(tmp_path / "d27")
    decoder = d27.Path(d27.d26audit.__file__)
    assert str(decoder.relative_to(d27.ROOT)) in d22.read_json(freeze)["files"]
    real_digest = d27.digest
    monkeypatch.setattr(d27, "digest", lambda path: "changed" if path == decoder else real_digest(path))
    with pytest.raises(ValueError, match="files"):
        d27.verify_freeze(freeze)


def test_receipt_requires_menu_specific_target_indices_and_disallows_silent_retry(tmp_path):
    folder = tmp_path / "d27"
    freeze = d27.freeze(folder)
    rows = _receipt(folder, freeze)
    assert d27.verify_training_receipt(folder, freeze)["steps"] == rows
    rows[0]["target_action_index"] = 5
    (folder / "training-steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    summary = d22.read_json(folder / "training.json")
    summary["steps"] = rows
    (folder / "training.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="target"):
        d27.verify_training_receipt(folder, freeze)


def test_train_fit_requires_raw_score_choice_and_correct_menu_semantics(tmp_path):
    folder = tmp_path / "d27"
    freeze = d27.freeze(folder)
    _receipt(folder, freeze)
    payload = d22.read_json(freeze)
    adapter_sha = d22.sha(folder / "adapter/adapters.safetensors")
    records = []
    for row in payload["plan"]:
        target = d22.CODES.index(row["target_code"])
        scores = [-1.0] * 6
        scores[target] = 2.0
        records.append({"case_id": row["case_id"], "menu_id": row["menu_id"], "attempt": 1,
            "freeze": d22.sha(freeze), "base_sha256": d22.BASE_SHA, "adapter_sha256": adapter_sha,
            "gold_action": row["gold_action"], "gold_code": row["target_code"], "choice": row["target_code"],
            "choice_action": __import__("evidenceloop.report.action_sft_fit_audit", fromlist=["action_for"]).action_for(row["menu_id"], row["target_code"]),
            "scores": scores, "restricted_correct": True, "input_tokens": 4})
    (folder / "training-fit.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    assert d27.summarize_train_fit(folder, freeze)["passed"] is True
    records[0]["choice_action"] = "fy25_growth"
    (folder / "training-fit.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    with pytest.raises(ValueError, match="decoding"):
        d27.summarize_train_fit(folder, freeze)
