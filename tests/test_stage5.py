"""D16: the harder test split and how it is frozen, the stage-5 pairs built from C's own tasks, the difficulty
check, and the stage-5 comparisons."""
import dataclasses
import json
import os
import shutil

import pytest

from evidenceloop.cli import main
from evidenceloop.data import stage4, stage5
from evidenceloop.data.export import jsonl_sha256
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import ScriptedBackend
from evidenceloop.report.compare import STAGE4, STAGE5, render
from evidenceloop.tasks.generator import HARD_SPLITS, RULE_SEQUENCES, TRAIN_TEMPLATES, generate_split
from evidenceloop.train.dpo import DPOConfig
from evidenceloop.verify.verifier import evaluate

ROOT = os.path.join(os.path.dirname(__file__), "..")
REPORT_W25 = os.path.join(ROOT, "reports", "warmup_check_W25.md")


def _config(name):
    with open(os.path.join(ROOT, "configs", name), encoding="utf-8") as fh:
        return json.load(fh)


def _lines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def hard():
    return {split: generate_split(split, stage5.HARD_SIZES[split]) for split in HARD_SPLITS}


def test_the_hard_splits_are_the_frozen_ones_and_the_official_splits_did_not_move(hard):
    record = _config("frozen_hard.json")
    for split, (publics, privates, _) in hard.items():
        assert jsonl_sha256(publics) == record["splits"][split]["public_sha256"], split
        assert jsonl_sha256(privates) == record["splits"][split]["private_sha256"], split
    for split, info in _config("frozen.json")["splits"].items():  # adding two splits to the generator changed none
        publics, privates, _ = generate_split(split, info["n"])
        assert (jsonl_sha256(publics), jsonl_sha256(privates)) == (info["public_sha256"], info["private_sha256"]), split


def test_hard_tasks_use_only_what_training_has_at_its_hard_end(hard):
    publics, privates, rejects = hard["test_hard"]
    assert stage5.hard_problems("test_hard", publics, privates) == []
    by_id = {p["task_id"]: p for p in privates}
    for task in publics:
        knobs = task["knobs"]
        assert knobs["template"] in TRAIN_TEMPLATES and knobs["schema"] in ("S1", "S2"), "nothing held out for test_ood"
        assert knobs["units"] in ("all_mV", "mixed") and knobs["error"] == "transient"
        assert knobs["n_versions"] in (4, 5) and knobs["distractors"] in (3, 4), "beyond the training range"
        assert task["split"] == "test_hard" and "|v4-5|transient|" in task["bucket"]
        assert "提示：" not in task["prompt"], "the latest version is never given away"
        assert 1 <= task["prompt"].count("上次分析用的是") <= 2
        assert by_id[task["task_id"]]["required"]["protocol_version"] == f"v{knobs['n_versions']}"
    assert stage5.reference_turns(publics) == {"9": 150}, "longer than any test_id task, three turns inside the limit"
    # with four versions, rule type R2 ends on an exclusion list no training-domain protocol version has
    trained_lists = {tuple(v) for seq in RULE_SEQUENCES.values() for v in seq[:3]}
    unseen = [t for t in publics if tuple(by_id[t["task_id"]]["protocol_rules"][f"v{t['knobs']['n_versions']}"]["exclude_flags"])
              not in trained_lists]
    assert unseen and all(t["knobs"]["rule_type"] == "R2" and t["knobs"]["n_versions"] == 4 for t in unseen)
    assert 0.15 < len(unseen) / len(publics) < 0.35


def test_known_mistakes_fail_on_hard_tasks_too(hard):
    publics, privates, _ = hard["calib_hard"]
    by_id = {p["task_id"]: p for p in privates}
    for corruption in ("no_convert", "skip_filter", "old_version", "wrong_cite", "guess_version", "keep_only_ok", "publish"):
        for trace in run_episodes(publics, ScriptedBackend(corruption=corruption)):
            assert not evaluate(trace, by_id[trace["task_id"]])["task_success"], (corruption, trace["task_id"])


def test_hard_problems_and_overlaps_are_caught(hard):
    publics, privates, _ = hard["calib_hard"]
    assert any("要求 50 道" in p for p in stage5.hard_problems("calib_hard", publics[:-1], privates[:-1]))
    easy = generate_split("validation", 1)
    swapped = [dict(easy[0][0], split="calib_hard")] + publics[1:], [easy[1][0]] + privates[1:]
    assert any("超出了 D16 的范围" in p for p in stage5.hard_problems("calib_hard", *swapped))
    broken = [dict(privates[0], reference={k: "0" for k in privates[0]["reference"]})] + privates[1:]
    assert any("参考解法" in p for p in stage5.hard_problems("calib_hard", publics, broken))
    keys = {"test_hard": {"a", "b"}, "calib_hard": {"c"}, "test_id": {"d"}, "trained": {"e"}}
    assert stage5.key_overlaps(keys, HARD_SPLITS) == []
    assert len(stage5.key_overlaps(dict(keys, calib_hard={"a"}), HARD_SPLITS)) == 1
    assert len(stage5.key_overlaps(dict(keys, trained={"c", "b"}), HARD_SPLITS)) == 2


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    """A small frozen set, a warm-up, stage 4 at 8 tasks for two seeds, and the hard splits frozen next to them."""
    d = tmp_path_factory.mktemp("stage5")
    main(["tasks", "build", "--split", "calibration", "--n", "2", "--out", str(d / "tasks")])
    (d / "calibration.md").write_text("# 校准报告\n", encoding="utf-8")
    main(["freeze", "--tasks-dir", str(d / "tasks"), "--base", "Qwen/Qwen3-1.7B", "--calibration", str(d / "calibration.md"),
          "--sizes", "train_mining=6", "validation=4", "test_id=5", "test_ood=4", "--out", str(d / "frozen.json")])
    main(["warmup", "build", "--tasks-dir", str(d / "tasks"), "--doses", "3", "--out", str(d / "warmup"),
          "--record", str(d / "warmup.json")])
    main(["stage4", "build", "--mining-report", REPORT_W25, "--tasks-dir", str(d / "tasks"), "--warmup-records",
          str(d / "warmup" / "dose3.records.jsonl"), "--seeds", "1", "2", "--n", "8", "--out", str(d / "s4"),
          "--record", str(d / "stage4.json")])
    trained = [str(d / "warmup" / "dose3.records.jsonl")]
    trained += [str(d / "s4" / f"{a}{s}" / "records.jsonl") for s in (1, 2) for a in "BCD"]
    freeze = ["stage5", "freeze", "--tasks-dir", str(d / "tasks"), "--exclude-records", *trained,
              "--record", str(d / "frozen_hard.json")]
    main(freeze)
    return {"dir": d, "trained": trained, "freeze": freeze}


def _build_args(workdir, out, record, source="--mining-report"):
    d = workdir["dir"]
    return ["stage5", "build", source, REPORT_W25, "--tasks-dir", str(d / "tasks"), "--warmup-records",
            str(d / "warmup" / "dose3.records.jsonl"), "--stage4-record", str(d / "stage4.json"), "--hard-record",
            str(d / "frozen_hard.json"), "--seeds", "1", "2", "--n", "8", "--out", str(out), "--record", str(record)]


def test_freeze_records_checks_and_never_overwrites(workdir, tmp_path, hard):
    d = workdir["dir"]
    record = json.loads((d / "frozen_hard.json").read_text(encoding="utf-8"))
    assert record["decision"] == "D16" and set(record["splits"]) == set(HARD_SPLITS)
    assert record["splits"]["test_hard"]["public_sha256"] == _config("frozen_hard.json")["splits"]["test_hard"]["public_sha256"]
    assert record["splits"]["test_hard"]["reference_turns"] == {"9": 150}
    assert set(record["dedup_keys_checked_against"]) == {"train_mining", "validation", "test_id", "test_ood", *workdir["trained"]}
    main(workdir["freeze"])  # a second run only checks
    assert json.loads((d / "frozen_hard.json").read_text(encoding="utf-8")) == record

    tasks = tmp_path / "tasks"
    shutil.copytree(d / "tasks", tasks)
    own = ["stage5", "freeze", "--tasks-dir", str(tasks), "--exclude-records", *workdir["trained"]]  # the copy's own files
    planted = tmp_path / "planted.records.jsonl"  # a trained task with the content of a hard one
    planted.write_text(json.dumps({"dedup_key": hard["test_hard"][1][0]["dedup_key"], "messages": []}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        main([*own, str(planted), "--record", str(tmp_path / "a.json")])
    assert "内容重复" in str(stopped.value) and not (tmp_path / "a.json").exists()
    path = tasks / "calib_hard.public.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    shutil.copy(d / "frozen_hard.json", tmp_path / "b.json")
    with pytest.raises(SystemExit):  # a changed file no longer matches the record, and the record stays
        main([*own, "--record", str(tmp_path / "b.json")])
    assert json.loads((tmp_path / "b.json").read_text(encoding="utf-8")) == record


def test_stage5_build_makes_the_pairs_from_cs_own_tasks(workdir, tmp_path):
    d, out, record_path = workdir["dir"], tmp_path / "s5", tmp_path / "stage5.json"
    args = _build_args(workdir, out, record_path)
    main(args)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    stage4_record = json.loads((d / "stage4.json").read_text(encoding="utf-8"))
    assert record["decision"] == "D16" and record["seeds"] == [1, 2] and record["training"] == stage5.D16_TRAINING
    assert set(record["excluded_from"]) == {"train_mining", "validation", "test_id", "test_ood", "test_hard", "calib_hard", "warmup"}
    assert record["eval_files"]["eval.public.jsonl"]["tasks"] == 150 + 5
    frozen = set()
    for split in ("train_mining", "validation", "test_id", "test_ood", "test_hard", "calib_hard"):
        frozen |= {p["dedup_key"] for p in _lines(d / "tasks" / f"{split}.private.jsonl")}
    warm = {r["dedup_key"] for r in _lines(d / "warmup" / "dose3.records.jsonl")}
    for seed in ("1", "2"):
        info, expected = record["per_seed"][seed], stage4_record["per_seed"][seed]
        assert info["c_trl_sha256"] == expected["trl_sha256"][f"C{seed}"] and info["c_samples"] == expected["samples_per_arm"]
        assert info["pairs"] == expected["samples_per_arm"] // 2 and info["sequences"] == 2 * info["pairs"]
        assert info["optimizer_steps"] == -(-info["pairs"] // 8) and info["tasks_with_pairs"] == 8
        rows, pairs = _lines(out / f"prefs_s{seed}.trl.jsonl"), _lines(out / f"prefs_s{seed}.records.jsonl")
        assert len(rows) == len(pairs) == info["pairs"]
        assert all(set(row) == {"prompt", "chosen", "rejected", "tools"} for row in rows)
        assert jsonl_sha256(rows) == info["trl_sha256"]
        c_tasks = [r["task_id"] for r in _lines(d / "s4" / f"C{seed}" / "records.jsonl")]
        assert list(dict.fromkeys(p["task_id"] for p in pairs)) == c_tasks, "the same tasks as C, in C's order"
        assert not {p["dedup_key"] for p in pairs} & (frozen | warm)
        assert sum(info["composition"]["by_label"].values()) == info["pairs"]
    assert _lines(out / "prefs_s1.trl.jsonl") != _lines(out / "prefs_s2.trl.jsonl")

    main(args)  # a second run (the Kaggle run) checks against the record and leaves it alone
    assert json.loads(record_path.read_text(encoding="utf-8")) == record
    evals = tmp_path / "w25.jsonl"  # the real evals give what the report's table gives
    evals.write_text("\n".join(json.dumps(e) for e in stage4.evals_from_check_report(REPORT_W25)), encoding="utf-8")
    real = _build_args(workdir, out, record_path, source="--evals")
    real[3] = str(evals)
    main(real)

    tampered = dict(stage4_record, per_seed={**stage4_record["per_seed"], "1": {
        **stage4_record["per_seed"]["1"], "trl_sha256": {**stage4_record["per_seed"]["1"]["trl_sha256"], "C1": "0" * 64}}})
    (tmp_path / "other4.json").write_text(json.dumps(tampered), encoding="utf-8")
    other = _build_args(workdir, tmp_path / "s5b", tmp_path / "other5.json")
    other[other.index("--stage4-record") + 1] = str(tmp_path / "other4.json")
    with pytest.raises(SystemExit) as stopped:  # these would not be the tasks C1 was trained on
        main(other)
    assert "对不上" in str(stopped.value) and not (tmp_path / "other5.json").exists()


def test_the_recorded_stage5_data_matches_stage4_and_d16():
    record, stage4_record = _config("stage5.json"), _config("stage4.json")
    assert record["seeds"] == [1, 2, 3] and record["n_tasks"] == 100
    assert {s: record["per_seed"][s]["pairs"] for s in "123"} == {"1": 407, "2": 409, "3": 407}
    for seed in "123":
        info, expected = record["per_seed"][seed], stage4_record["per_seed"][seed]
        assert info["c_trl_sha256"] == expected["trl_sha256"][f"C{seed}"]
        assert info["pairs"] == expected["samples_per_arm"] // 2 and info["optimizer_steps"] == expected["optimizer_steps"]
        assert info["candidate_pairs"] >= info["pairs"] and info["tasks_with_pairs"] == 100
        assert set(info["pairs_per_task"]) == {"4", "5"}
    hard_record = _config("frozen_hard.json")
    assert {s: v["public_sha256"] for s, v in record["hard_splits"].items()} == \
           {s: v["public_sha256"] for s, v in hard_record["splits"].items()}
    assert record["excluded_from"]["test_hard"] == 150 and record["excluded_from"]["calib_hard"] == 50


def test_the_training_settings_are_cs_plus_beta_and_eight_pairs_a_step():
    defaults = dataclasses.asdict(DPOConfig(base="b", data="d", out="o"))
    assert {k: defaults[k] for k in stage5.D16_TRAINING} == stage5.D16_TRAINING
    changed = {k for k in stage5.D16_TRAINING if stage4.D12_TRAINING.get(k) != stage5.D16_TRAINING[k]}
    assert changed == {"grad_accum", "beta"} and stage5.D16_TRAINING["grad_accum"] * 2 == stage4.STEP_SAMPLES


def test_training_problems():
    cfg = dict(stage5.D16_TRAINING, seed=2)
    log = {"loss": "dpo", "config": cfg, "data_sha256": "d", "base_fingerprint": "w", "adapter_fingerprint": "a", "skipped": {}}
    assert stage5.training_problems(log, "d", "w", 2, "a") == []
    assert stage5.training_problems(log, "other", "w", 2, "a")
    assert stage5.training_problems(log, "d", "not-w", 2, "a"), "CP must start from W with C merged in, P from W"
    assert stage5.training_problems(log, "d", "w", 3, "a")
    assert stage5.training_problems(log, "d", "w", 2, "changed")
    assert stage5.training_problems(dict(log, aborted="loss"), "d", "w", 2, "a")
    assert stage5.training_problems(dict(log, skipped={"too_long": 1}), "d", "w", 2, "a")
    assert stage5.training_problems(dict(log, config=dict(cfg, beta=0.5)), "d", "w", 2, "a")
    assert stage5.training_problems(dict(log, config=dict(cfg, grad_accum=16)), "d", "w", 2, "a")
    sft = {k: v for k, v in log.items() if k != "loss"}
    assert stage5.training_problems(sft, "d", "w", 2, "a"), "an SFT log is not a DPO run"


def _evals(name, wins, n=50, split="calib_hard", infra=0):
    buckets = ("F2|mixed|v4-5|transient|sci", "F1|all_mV|v4-5|transient|plain")
    return [{"task_id": f"t{i}", "split": split, "bucket": buckets[i % 2],
             "inference_config_hash": name, "task_success": i < wins,
             "termination": "infra_error" if i < infra else "final_answer"} for i in range(n)]


def test_the_gate_stops_at_the_ceiling_and_at_the_floor(tmp_path):
    ok = stage5.gate({1: _evals("c1", 40), 2: _evals("c2", 30), 3: _evals("c3", 35)})
    assert ok["passed"] and ok["rate"] == pytest.approx(105 / 150) and ok["successes"] == {1: 40, 2: 30, 3: 35}
    assert stage5.gate({s: _evals(f"c{s}", 45) for s in (1, 2, 3)})["passed"], "exactly 90% still passes"
    top = stage5.gate({1: _evals("c1", 50), 2: _evals("c2", 50), 3: _evals("c3", 36)})
    assert not top["passed"] and "到顶" in top["reasons"][0]
    floor = stage5.gate({s: _evals(f"c{s}", 9) for s in (1, 2, 3)})
    assert not floor["passed"] and "太难" in floor["reasons"][0]
    for broken in ({1: _evals("c1", 40), 2: _evals("c2", 30)},  # a seed missing
                   {1: _evals("c1", 40), 2: _evals("c2", 30), 3: None},
                   {1: _evals("c1", 40), 2: _evals("c2", 30), 3: _evals("c3", 30)[:-1]},
                   {1: _evals("c1", 40), 2: _evals("c2", 30), 3: _evals("c3", 30, infra=2)},
                   {1: _evals("c1", 40), 2: _evals("c2", 30), 3: _evals("c3", 30, split="test_hard")}):
        with pytest.raises(ValueError):
            stage5.gate(broken)

    rows = []
    for seed, wins in ((1, 50), (2, 49), (3, 50)):
        path = tmp_path / f"c{seed}.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in _evals(f"c{seed}", wins)), encoding="utf-8")
        rows += ["--row", f"C:{seed}={path}"]
    with pytest.raises(SystemExit) as stopped:
        main(["stage5", "gate", *rows, "--out", str(tmp_path / "gate.md")])
    assert stopped.value.code == 3, "its own exit code: the run was fine, the split is not usable"
    text = (tmp_path / "gate.md").read_text(encoding="utf-8")
    assert "不通过" in text and "149/150" in text and "| C2 | 49/50 |" in text
    (tmp_path / "c2.jsonl").write_text("\n".join(json.dumps(e) for e in _evals("c2", 20)), encoding="utf-8")
    main(["stage5", "gate", *rows, "--out", str(tmp_path / "gate.md")])
    assert "- 结论：通过" in (tmp_path / "gate.md").read_text(encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        main(["stage5", "gate", *rows[:4]])
    assert stopped.value.code != 3 and "C3" in str(stopped.value)


def test_stage5_comparisons_follow_d16(tmp_path):
    hard = lambda name, wins: _evals(name, wins, n=20, split="test_hard")  # noqa: E731
    rows = {"W": {None: hard("w", 6)}, "C": {s: hard(f"c{s}", 10) for s in (1, 2, 3)},
            "P": {1: hard("p1", 9), 2: hard("p2", 10), 3: hard("p3", 11)},
            "CP": {1: hard("cp1", 15), 2: hard("cp2", 16), 3: None}}
    text = render("test_hard", rows, 20, resamples=500, design=STAGE5)
    assert text.startswith("# 阶段五：test_hard 上的对比（D16）")
    assert "| H4（主假设） | CP − C |" in text and "| H5 | P − C |" in text and "| H6 | CP − P |" in text
    h4 = next(line for line in text.splitlines() if line.startswith("| H4"))
    assert "| 1, 2 |" in h4 and h4.rstrip().endswith("| X 更好 |"), "CP3 is missing: seeds 1 and 2, both won"
    h5 = next(line for line in text.splitlines() if line.startswith("| H5"))
    assert h5.rstrip().endswith("| 分不出 |")
    assert "- CP3：没有结果文件" in text and "H1" not in text and "ICL" not in text
    assert text.index("| W |") < text.index("| C |") < text.index("| P |") < text.index("| CP |")
    other = render("test_id", {k: {s: [dict(e, split="test_id") for e in v] if v else v for s, v in r.items()}
                               for k, r in rows.items()}, 20, resamples=500, design=STAGE5)
    assert "只作描述" in other
    assert STAGE4.primary_split == "test_id" and "H1" in render("test_id", {"B": {}, "C": {}}, 20, resamples=10)

    paths = []
    for arm, runs in rows.items():
        for seed, evals in runs.items():
            if evals is None:
                continue
            path = tmp_path / f"{arm}{seed or ''}.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in evals), encoding="utf-8")
            paths += ["--row", f"{arm}:{seed}={path}" if seed else f"{arm}={path}"]
    main(["stage5", "compare", "--split", "test_hard", *paths, "--row", f"CP:3={tmp_path / 'missing.jsonl'}",
          "--expected-n", "20", "--resamples", "500", "--out", str(tmp_path / "cmp.md")])
    assert (tmp_path / "cmp.md").read_text(encoding="utf-8") == text
