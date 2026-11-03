"""D14: the stage-4 data (B, C, D from W25, aligned per seed), the W+ICL task files, and the verdict rule."""
import dataclasses
import json
import os
import random

import pytest

from evidenceloop.cli import main
from evidenceloop.data import stage4
from evidenceloop.data.build import build_training_set
from evidenceloop.data.selection import allocation_shift, selection_weights
from evidenceloop.harness.parser import format_tool_call
from evidenceloop.report.compare import compare_arms, render, run_problems
from evidenceloop.tasks.generator import SYSTEM_PROMPT, generate_split
from evidenceloop.train.sft import TARGET_MODULES, TrainConfig

REPORT_W25 = os.path.join(os.path.dirname(__file__), "..", "reports", "warmup_check_W25.md")


def _lines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def w25():
    return stage4.evals_from_check_report(REPORT_W25)


def test_the_check_report_gives_back_w25s_groups_and_shift(w25):
    mining = stage4.mining_summary(w25)
    assert mining["success"] == 131 and mining["n"] == 200
    assert round(mining["shift"], 3) == 0.159
    assert mining["groups"]["all_mV|F2"] == {"success": 14, "n": 36}
    assert len({e["inference_config_hash"] for e in w25}) == 1


def test_exported_data_depends_only_on_the_group_table(w25):
    """The real W25 evals have other task ids, another order and other failure categories; as long as the group
    table is the same and schema_error does not dominate, C's and D's data are the same."""
    other = [dict(e, task_id=f"t_{i:04d}", failure=None if e["task_success"] else {"primary": random.Random(i).choice(
        ["unit_error", "source_version_error", "filter_error", "unknown"])}) for i, e in enumerate(w25)]
    random.Random(7).shuffle(other)
    assert selection_weights("targeted", other) == selection_weights("targeted", w25)
    a = stage4.build_seed(1, 8, w25, set())["matched"]
    b = stage4.build_seed(1, 8, other, set())["matched"]
    dump = lambda m: {n: [(s["prompt"], s["completion"]) for s in v] for n, v in m["samples"].items()}  # noqa: E731
    assert dump(a) == dump(b)
    assert allocation_shift(selection_weights("targeted", w25), selection_weights("uniform")) >= 0.10


def test_set_problems_catch_every_departure_from_d14(w25):
    built = {arm: build_training_set(policy, 2, 8, w25) for arm, policy in stage4.ARMS.items()}
    assert stage4.set_problems(built, 8) == []
    assert any("要求 9 道" in p for p in stage4.set_problems(built, 9))
    assert any("不是整数" in p for p in stage4.set_problems(built, 8, ratio=0.3))
    swapped = dict(built, D=dict(built["D"], records=built["D"]["records"][::-1]))
    assert any("同一串题" in p for p in stage4.set_problems(swapped, 8))
    tainted = dict(built, B=dict(built["B"], corrupted=1))
    assert any("错误示范" in p for p in stage4.set_problems(tainted, 8))


def test_d14_task_count_gives_d_exactly_a_quarter_of_wrong_demos():
    assert stage4.N_TASKS * 0.25 == 25
    assert round(50 * 0.25) != 50 * 0.25, "at 50 tasks D would get 12 of 50 (24%)"


def test_the_training_settings_are_d12s_with_one_epoch():
    defaults = dataclasses.asdict(TrainConfig(base="b", data="d", out="o"))
    for key, value in stage4.D12_TRAINING.items():
        assert defaults[key] == value or key == "epochs", key
    assert stage4.D12_TRAINING["target_modules"] == TARGET_MODULES and stage4.D12_TRAINING["epochs"] == 1


def test_training_problems():
    cfg = dict(stage4.D12_TRAINING, seed=2)
    log = {"config": cfg, "data_sha256": "d", "base_fingerprint": "w", "adapter_fingerprint": "a"}
    assert stage4.training_problems(log, "d", "w", 2, "a") == []
    assert stage4.training_problems(log, "other", "w", 2, "a")
    assert stage4.training_problems(log, "d", "not-w", 2, "a")
    assert stage4.training_problems(log, "d", "w", 3, "a")
    assert stage4.training_problems(log, "d", "w", 2, "changed")
    assert stage4.training_problems(dict(log, aborted="loss"), "d", "w", 2, "a")
    assert stage4.training_problems(dict(log, config=dict(cfg, epochs=2)), "d", "w", 2, "a")


def test_icl_tasks_change_only_the_system_prompt_and_pick_a_demo_with_no_shared_ids(w25):
    records = build_training_set("targeted", 1, 6, w25)["records"]
    tasks = generate_split("validation", 5)[0]
    clash = dict(tasks[0], resources={"datasets": [], "protocols": sorted(stage4.resource_ids(records[0]))})
    demos = stage4.pick_demos(records, [clash] + tasks[1:])
    assert demos[0]["task_id"] != records[0]["task_id"], "the first demo shares an id with a task and is skipped"
    out = stage4.icl_tasks(tasks, demos)
    for before, after in zip(tasks, out):
        assert after["task_id"] == before["task_id"] and after["prompt"] == before["prompt"]
        assert after["system_prompt"].startswith(SYSTEM_PROMPT) and len(after["system_prompt"]) > len(SYSTEM_PROMPT)
        unchanged = lambda t: {k: v for k, v in t.items() if k not in ("system_prompt", "icl")}  # noqa: E731
        assert unchanged(after) == unchanged(before)
    block = out[0]["system_prompt"]
    for message in demos[0]["messages"]:
        for call in message.get("tool_calls", []):
            assert format_tool_call(call["function"]["name"], call["function"]["arguments"]) in block
    assert "CANARY-" not in block and len({t["system_prompt"] for t in out}) == 1, "one context for every task"
    with pytest.raises(ValueError):
        stage4.pick_demos(records[:1], [clash])


def test_the_verifier_scores_icl_tasks_exactly_like_the_plain_ones(w25):
    from evidenceloop.harness.loop import run_episodes
    from evidenceloop.harness.scripted import ScriptedBackend
    from evidenceloop.verify.verifier import evaluate

    publics, privates, _ = generate_split("validation", 6)
    privates = {p["task_id"]: p for p in privates}
    icl = stage4.icl_tasks(publics, stage4.pick_demos(build_training_set("targeted", 1, 4, w25)["records"], publics))
    keep = ("checks", "task_success", "failure", "grounding_violations", "numbers_not_from_tools", "reply")
    for corruption in (None, "no_convert", "guess_version"):
        plain = [evaluate(t, privates[t["task_id"]]) for t in run_episodes(publics, ScriptedBackend(corruption=corruption))]
        ctx = [evaluate(t, privates[t["task_id"]]) for t in run_episodes(icl, ScriptedBackend(corruption=corruption))]
        assert [{k: e[k] for k in keep} for e in plain] == [{k: e[k] for k in keep} for e in ctx], corruption


@pytest.fixture(scope="module")
def frozen_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("frozen4")
    main(["tasks", "build", "--split", "calibration", "--n", "2", "--out", str(d / "tasks")])
    (d / "calibration.md").write_text("# 校准报告\n", encoding="utf-8")
    main(["freeze", "--tasks-dir", str(d / "tasks"), "--base", "Qwen/Qwen3-1.7B", "--calibration", str(d / "calibration.md"),
          "--sizes", "train_mining=6", "validation=4", "test_id=5", "test_ood=4", "--out", str(d / "frozen.json")])
    main(["warmup", "build", "--tasks-dir", str(d / "tasks"), "--doses", "3", "--out", str(d / "warmup"),
          "--record", str(d / "warmup.json")])
    return d


def test_stage4_build_records_checks_and_equals_the_documented_commands(frozen_dir, tmp_path, w25):
    evals = tmp_path / "w25.jsonl"
    evals.write_text("\n".join(json.dumps(e) for e in w25), encoding="utf-8")
    warm = str(frozen_dir / "warmup" / "dose3.records.jsonl")
    record = tmp_path / "stage4.json"
    args = ["stage4", "build", "--evals", str(evals), "--tasks-dir", str(frozen_dir / "tasks"), "--warmup-records", warm,
            "--seeds", "1", "2", "--n", "8", "--out", str(tmp_path / "s4"), "--record", str(record)]
    main(args)
    first = json.loads(record.read_text(encoding="utf-8"))
    assert first["decision"] == "D14" and first["seeds"] == [1, 2] and first["n_tasks"] == 8
    assert first["excluded_from"]["warmup"] == 3 and first["eval_files"]["eval.public.jsonl"]["tasks"] == 13
    assert first["eval_files"]["test.public.jsonl"]["tasks"] == 9
    for seed in ("1", "2"):
        info = first["per_seed"][seed]
        assert info["arms"]["D"]["corrupted"] == 2 and info["arms"]["B"]["tasks"] == 8
        assert len(_lines(tmp_path / "s4" / f"icl{seed}.test_id.public.jsonl")) == 5
    keys = {r["dedup_key"] for r in _lines(warm)}
    for name in ("B1", "C1", "D1", "B2", "C2", "D2"):
        assert not keys & {r["dedup_key"] for r in _lines(tmp_path / "s4" / name / "records.jsonl")}

    # the same data through el data build + el export sft, as docs/kaggle_stage4.md writes them out
    for arm, policy in stage4.ARMS.items():
        main(["data", "build", "--policy", policy, "--seed", "2", "--n", "8", "--evals", str(evals),
              "--exclude-tasks-dir", str(frozen_dir / "tasks"), "--exclude-records", warm, "--out", str(tmp_path / f"{arm}2")])
    main(["export", "sft", "--records", *[str(tmp_path / f"{a}2" / "records.jsonl") for a in stage4.ARMS],
          "--names", "B2", "C2", "D2", "--format", "trl", "--seed", "2", "--out", str(tmp_path / "export_s2")])
    for name in ("B2", "C2", "D2"):
        assert (tmp_path / "export_s2" / f"{name}.trl.jsonl").read_bytes() == \
               (tmp_path / "s4" / "export_s2" / f"{name}.trl.jsonl").read_bytes()

    main(args)  # a second run (the Kaggle run) checks against the record and leaves it alone
    assert json.loads(record.read_text(encoding="utf-8")) == first
    report_args = [a if a != str(evals) else REPORT_W25 for a in args]
    main([*report_args[:2], "--mining-report", *report_args[3:]])  # the CPU dry run gives the same record
    tampered = json.loads(record.read_text(encoding="utf-8"))
    tampered["per_seed"]["1"]["trl_sha256"]["C1"] = "0" * 64
    record.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(args)


def test_stage4_build_refuses_a_w_that_is_not_d13s(frozen_dir, tmp_path, w25):
    warm = str(frozen_dir / "warmup" / "dose3.records.jsonl")
    for broken in (w25[:-1], [dict(e, task_success=True) for e in w25]):  # a task missing; a W that passes nothing
        evals = tmp_path / "bad.jsonl"
        evals.write_text("\n".join(json.dumps(e) for e in broken), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(["stage4", "build", "--evals", str(evals), "--tasks-dir", str(frozen_dir / "tasks"),
                  "--warmup-records", warm, "--n", "4", "--out", str(tmp_path / "s4"), "--record", str(tmp_path / "r.json")])
        assert not (tmp_path / "r.json").exists()


def _evals(name, wins, n=20, split="test_id", infra=0):
    return [{"task_id": f"t{i}", "split": split, "bucket": ("F1|all_mV|v1|noerr|plain" if i % 2 else "F2|mixed|v1|noerr|sci"),
             "inference_config_hash": name, "task_success": i in wins,
             "termination": "infra_error" if i < infra else "final_answer"} for i in range(n)]


def _maps(runs):
    return {s: {e["task_id"]: int(e["task_success"]) for e in ev} for s, ev in runs.items()}


def test_verdicts_follow_the_d14_rule():
    y = {s: _evals(f"y{s}", set(range(8))) for s in (1, 2, 3)}
    better = {s: _evals(f"x{s}", set(range(15))) for s in (1, 2, 3)}
    result = compare_arms(_maps(better), _maps(y), resamples=2000)
    assert result["verdict"] == "X 更好" and result["effect"] == pytest.approx(35.0) and result["interval"][0] > 0
    assert compare_arms(_maps(y), _maps(better), resamples=2000)["verdict"] == "X 更差"
    mixed = {1: _evals("a", set(range(12))), 2: _evals("b", set(range(12))), 3: _evals("c", set(range(7)))}
    assert compare_arms(_maps(mixed), _maps(y), resamples=2000)["verdict"] == "分不出", "one seed loses"
    assert compare_arms(_maps({1: better[1]}), _maps(y), resamples=2000)["verdict"].startswith("不判定")
    single = compare_arms(_maps(better), {None: _maps({0: y[1]})[0]}, resamples=2000)
    assert single["seeds"] == [1, 2, 3] and single["verdict"] == "X 更好", "a single W serves every seed"
    again = compare_arms(_maps(mixed), _maps(y), resamples=2000)
    assert again["interval"] == compare_arms(_maps(mixed), _maps(y), resamples=2000)["interval"], "fixed bootstrap seed"


def test_only_complete_runs_are_compared_and_the_rest_are_listed():
    assert run_problems(_evals("x", set()), "test_id", 20) == []
    assert run_problems(_evals("x", set())[:-1], "test_id", 20)
    assert run_problems(_evals("x", set(), infra=2), "test_id", 20)
    assert run_problems(_evals("x", set(), split="validation"), "test_id", 20)
    rows = {"W": {None: _evals("w", set(range(10)))},
            "B": {s: _evals(f"b{s}", set(range(10))) for s in (1, 2, 3)},
            "C": {1: _evals("c1", set(range(16))), 2: _evals("c2", set(range(16))), 3: None},
            "ICL": {1: _evals("i1", set(), infra=3), 2: None, 3: None}}
    text = render("test_id", rows, 20, resamples=500)
    assert "| H1（主假设） | C − B |" in text and "| 1, 2 |" in text, "C3 is missing, so H1 uses seeds 1 and 2"
    assert "- C3：没有结果文件" in text and "ICL1：有 3 道运行故障" in text
    assert "H3" in text and "不判定：有一边没有完整结果" in text
    assert "mixed｜F2" in text and "all_mV｜F1" in text
    other = render("test_ood", {k: {s: [dict(e, split="test_ood") for e in v] if v else v for s, v in r.items()}
                                for k, r in rows.items()}, 20, resamples=500)
    assert "只作描述" in other
    no_w = render("validation", {**rows, "W": {None: None}, "A": {None: None}}, 20, resamples=500)
    assert "| W |  |  |  | 没有 |" in no_w and "- W：没有结果文件" in no_w and "B − W" in no_w
