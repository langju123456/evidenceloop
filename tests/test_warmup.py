"""D11: pooled group weights, the warm-up data, the warm-up check, and the frozen-split check."""
import json
import shutil

import pytest

from evidenceloop.cli import main
from evidenceloop.data.build import build_training_set
from evidenceloop.data.selection import (CAP, GROUPS, TRAIN_BUCKETS, _cap, allocation_shift, failure_stats, group_of,
                                         group_weights, selection_weights)
from evidenceloop.data.warmup import build_warmup, check_inputs, check_warmup, frozen_dedup_keys
from evidenceloop.tasks.generator import TRAIN_TEMPLATES

BUCKET_OF_GROUP = {}
for _bucket in TRAIN_BUCKETS:
    BUCKET_OF_GROUP.setdefault(group_of(_bucket), _bucket)

SOME_RIGHT_SOME_WRONG = {"all_V|F1": 27, "all_V|F2": 24, "all_mV|F1": 15, "all_mV|F2": 9, "mixed|F1": 6, "mixed|F2": 3}


def _evals(successes: dict[str, int], n: int = 30) -> list[dict]:
    """n train_mining tasks per group (180 in all), the given number of them solved, one configuration."""
    rows = []
    for g in GROUPS:
        for i in range(n):
            ok = i < successes.get(g, 0)
            rows.append({"task_id": f"{g}-{i}", "split": "train_mining", "bucket": BUCKET_OF_GROUP[g],
                         "inference_config_hash": "cfg", "termination": "final_answer", "task_success": ok,
                         "failure": None if ok else {"primary": "filter_error"}})
    return rows


def test_six_groups_cover_every_train_bucket():
    assert len(GROUPS) == 6
    assert {group_of(b) for b in TRAIN_BUCKETS} == set(GROUPS)
    assert group_of("F2|mixed|v2-3|transient|sci") == "mixed|F2"


def test_equal_failure_rates_give_exactly_the_uniform_allocation():
    evals = _evals({g: 15 for g in GROUPS})
    targeted, uniform = selection_weights("targeted", evals), selection_weights("uniform")
    assert allocation_shift(targeted, uniform) < 1e-12


def test_weights_are_pooled_per_group():
    a, b = [x for x in TRAIN_BUCKETS if group_of(x) == "mixed|F1"][:2]
    evals = [{"task_id": "t1", "bucket": a, "task_success": False, "failure": {"primary": "unit_error"}},
             {"task_id": "t2", "bucket": b, "task_success": True, "failure": None}]
    weights = selection_weights("targeted", evals)
    assert weights[a] == weights[b], "two buckets of one group share the group's pooled rate"
    assert group_weights(weights)["mixed|F1"] > group_weights(selection_weights("uniform"))["mixed|F1"]


def test_cap_moves_the_excess_to_the_others_until_none_is_above_it():
    for weights in ({"a": 0.6, "b": 0.2, "c": 0.2}, {"a": 0.5, "b": 0.35, "c": 0.15}, {"a": 0.5, "b": 0.45, "c": 0.05}):
        capped = _cap(weights, 0.4)
        assert abs(sum(capped.values()) - 1) < 1e-12 and max(capped.values()) <= 0.4 + 1e-12
        assert capped["a"] >= capped["b"] >= capped["c"], "the order of the weights is kept"
    assert _cap({"a": 0.5, "b": 0.35, "c": 0.15}, 0.4) == pytest.approx({"a": 0.4, "b": 0.4, "c": 0.2})
    one_group_fails = _evals({g: 30 for g in GROUPS if g != "mixed|F2"})
    assert max(selection_weights("targeted", one_group_fails).values()) <= CAP + 1e-12


def test_allocation_shift():
    assert allocation_shift({"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.5}) == 0
    assert allocation_shift({"x": 1.0}, {"y": 1.0}) == 1.0
    assert abs(allocation_shift({"x": 0.7, "y": 0.3}, {"x": 0.5, "y": 0.5}) - 0.2) < 1e-12


def test_an_episode_ended_by_a_crash_is_not_a_failure_even_if_an_earlier_error_is_its_diagnosis():
    crashed = {"task_id": "x", "bucket": TRAIN_BUCKETS[0], "task_success": False, "termination": "infra_error",
               "failure": {"primary": "schema_error"}}
    stats = failure_stats(_evals(SOME_RIGHT_SOME_WRONG) + [crashed])
    assert stats["total_failures"] == failure_stats(_evals(SOME_RIGHT_SOME_WRONG))["total_failures"]


def test_check_rejects_a_model_that_fails_everything():
    result = check_warmup(_evals({}), expected_n=180)
    assert not result["passed"] and result["success_rate"] == 0
    assert result["shift"] < 1e-12


def test_check_rejects_the_all_groups_at_half_loophole():
    result = check_warmup(_evals({g: 15 for g in GROUPS}), expected_n=180)
    assert result["success_rate"] == 0.5
    assert not result["passed"] and any("分配" in r for r in result["reasons"])


def test_check_accepts_a_model_that_is_right_on_some_groups_and_wrong_on_others():
    result = check_warmup(_evals(SOME_RIGHT_SOME_WRONG), expected_n=180)
    assert 0.2 <= result["success_rate"] <= 0.8
    assert result["shift"] >= 0.10 and result["passed"]
    assert result["targeted_group_weights"]["mixed|F2"] > result["targeted_group_weights"]["all_V|F1"]


def test_check_refuses_anything_but_one_complete_train_mining_run():
    good = _evals(SOME_RIGHT_SOME_WRONG)
    assert check_inputs(good, 180) == []
    assert check_inputs([], 180)
    assert check_inputs(good[:-1], 180), "a task missing"
    assert check_inputs(good + [good[0]], 180), "a task twice"
    assert check_inputs([dict(good[0], split="validation")] + good[1:], 180), "another split"
    assert check_inputs([dict(good[0], inference_config_hash="other")] + good[1:], 180), "two configurations"
    crashed = dict(good[0], termination="infra_error", task_success=False, failure={"primary": "schema_error"})
    assert any("infra_error" in p for p in check_inputs([crashed] + good[1:], 180)), "a crash, whatever its diagnosis"
    with pytest.raises(ValueError):
        check_warmup(good[:-1], expected_n=180)
    assert check_inputs(good, 200), "the default is the full train_mining split"


@pytest.fixture(scope="module")
def frozen_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("frozen")
    main(["tasks", "build", "--split", "calibration", "--n", "3", "--out", str(d / "tasks")])
    (d / "calibration.md").write_text("# 校准报告\n", encoding="utf-8")
    main(["freeze", "--tasks-dir", str(d / "tasks"), "--base", "Qwen/Qwen3-1.7B", "--calibration",
          str(d / "calibration.md"), "--sizes", "train_mining=8", "validation=4", "test_id=4", "test_ood=4",
          "--out", str(d / "frozen.json")])
    return d


def test_warmup_doses_are_nested_verified_and_disjoint_from_the_frozen_splits(frozen_dir):
    result = build_warmup(str(frozen_dir / "tasks"), seed=900, doses=(3, 6))
    small, large = result["doses"][3], result["doses"][6]
    assert [r["task_id"] for r in small] == [r["task_id"] for r in large[:3]]
    assert all(r["verified"] and r["gated"] and r["policy"] == "uniform" for r in large)
    frozen = set().union(*frozen_dedup_keys(str(frozen_dir / "tasks")).values())
    assert not {r["dedup_key"] for r in large} & frozen
    assert {r["recipe_id"].split("-")[0] for r in large} <= set(TRAIN_TEMPLATES)


def test_a_warmup_task_planted_in_a_frozen_split_is_dropped(frozen_dir, tmp_path):
    tasks = tmp_path / "tasks"
    shutil.copytree(frozen_dir / "tasks", tasks)
    clean = build_warmup(str(tasks), seed=900, doses=(3,))
    planted = clean["doses"][3][0]
    with open(tasks / "test_ood.private.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"dedup_key": planted["dedup_key"]}) + "\n")
    again = build_warmup(str(tasks), seed=900, doses=(3,))
    assert planted["task_id"] not in [r["task_id"] for r in again["doses"][3]]
    assert again["excluded_frozen_duplicates"] == clean["excluded_frozen_duplicates"] + 1


def test_a_task_matching_a_frozen_split_is_dropped():
    first = build_training_set("uniform", 900, 2)["records"][0]
    again = build_training_set("uniform", 900, 2, exclude_keys={first["dedup_key"]})
    assert first["task_id"] not in [r["task_id"] for r in again["records"]]
    assert again["reject_counts"]["excluded"] == 1


def test_data_build_can_exclude_the_frozen_splits_and_the_warmup_data(frozen_dir, tmp_path):
    main(["warmup", "build", "--tasks-dir", str(frozen_dir / "tasks"), "--seed", "1", "--doses", "2",
          "--out", str(tmp_path / "warmup"), "--record", str(tmp_path / "warmup.json")])
    warm = [json.loads(line) for line in open(tmp_path / "warmup" / "dose2.records.jsonl", encoding="utf-8")]
    # seed 1 for both, so B1 would start with the same tasks as this warm-up set if nothing were excluded
    main(["data", "build", "--policy", "uniform", "--seed", "1", "--n", "3", "--out", str(tmp_path / "B1"),
          "--exclude-tasks-dir", str(frozen_dir / "tasks"), "--exclude-records", str(tmp_path / "warmup" / "dose2.records.jsonl")])
    b1 = [json.loads(line) for line in open(tmp_path / "B1" / "records.jsonl", encoding="utf-8")]
    assert not {r["dedup_key"] for r in b1} & {r["dedup_key"] for r in warm}
    meta = json.load(open(tmp_path / "B1" / "build.json", encoding="utf-8"))
    assert meta["reject_counts"]["excluded"] >= 2
    assert set(meta["excluded_from"]) == {"train_mining", "validation", "test_id", "test_ood",
                                          str(tmp_path / "warmup" / "dose2.records.jsonl")}
    with pytest.raises(SystemExit):
        main(["data", "build", "--policy", "uniform", "--seed", "1", "--n", "3", "--out", str(tmp_path / "B2"),
              "--exclude-records", str(tmp_path / "missing.jsonl")])


def test_c_and_d_honour_the_exclusions_and_still_share_their_tasks(frozen_dir, tmp_path):
    evals = tmp_path / "w_evals.jsonl"
    evals.write_text("\n".join(json.dumps(e) for e in _evals(SOME_RIGHT_SOME_WRONG)), encoding="utf-8")
    common = ["--seed", "1", "--n", "3", "--evals", str(evals)]
    main(["data", "build", "--policy", "targeted", *common, "--out", str(tmp_path / "C_plain")])
    taken = tmp_path / "C_plain" / "records.jsonl"  # stands in for data that must not be used again
    flags = ["--exclude-tasks-dir", str(frozen_dir / "tasks"), "--exclude-records", str(taken)]
    main(["data", "build", "--policy", "targeted", *common, *flags, "--out", str(tmp_path / "C1")])
    main(["data", "build", "--policy", "unfiltered", *common, *flags, "--out", str(tmp_path / "D1")])
    read = lambda name: [json.loads(line) for line in open(tmp_path / name / "records.jsonl", encoding="utf-8")]  # noqa: E731
    c1, d1, before = read("C1"), read("D1"), read("C_plain")
    assert not {r["dedup_key"] for r in c1 + d1} & {r["dedup_key"] for r in before}
    assert [r["task_id"] for r in c1] == [r["task_id"] for r in d1], "C and D still share their tasks"


def test_warmup_build_records_hashes_and_a_second_run_checks_them(frozen_dir, tmp_path):
    record = tmp_path / "warmup.json"
    args = ["warmup", "build", "--tasks-dir", str(frozen_dir / "tasks"), "--doses", "2", "4",
            "--out", str(tmp_path / "warmup"), "--record", str(record)]
    main(args)
    first = json.loads(record.read_text(encoding="utf-8"))
    assert first["decision"] == "D11" and first["seed"] == 900 and set(first["doses"]) == {"2", "4"}
    assert first["doses"]["4"]["tasks"] == 4 and first["doses"]["4"]["samples"] > first["doses"]["2"]["samples"]
    main(args)  # same data again: matches the record, nothing overwritten
    assert json.loads(record.read_text(encoding="utf-8")) == first
    tampered = dict(first, doses={**first["doses"], "2": {**first["doses"]["2"], "trl_sha256": "0" * 64}})
    record.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(args)


def test_frozen_verify_regenerates_missing_files_and_catches_changes(frozen_dir, tmp_path):
    record = json.loads((frozen_dir / "frozen.json").read_text(encoding="utf-8"))
    fresh = tmp_path / "fresh"
    main(["frozen", "verify", "--record", str(frozen_dir / "frozen.json"), "--tasks-dir", str(fresh)])
    for split, info in record["splits"].items():
        assert (fresh / f"{split}.public.jsonl").exists(), split
    path = fresh / "validation.public.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["frozen", "verify", "--record", str(frozen_dir / "frozen.json"), "--tasks-dir", str(fresh)])


def test_warmup_check_command_writes_a_report_or_refuses(tmp_path):
    evals = tmp_path / "evals.jsonl"
    rows = _evals({"all_V|F1": 27, "mixed|F2": 3})
    evals.write_text("\n".join(json.dumps(e) for e in rows), encoding="utf-8")
    out = tmp_path / "check.md"
    main(["warmup", "check", "--evals", str(evals), "--expected-n", "180", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "预热达标检查" in text and "mixed｜F2" in text and "- 结论：" in text
    with pytest.raises(SystemExit):
        main(["warmup", "check", "--evals", str(evals), "--out", str(out)])  # 180 of the 200 tasks
    with pytest.raises(SystemExit):
        main(["warmup", "check", "--evals", str(tmp_path / "missing.jsonl"), "--expected-n", "180"])
