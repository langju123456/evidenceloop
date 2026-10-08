"""End to end through the command line, including resuming an interrupted run."""
import json
import os

from evidenceloop.cli import main


def _lines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_pipeline_end_to_end(tmp_path):
    d = str(tmp_path)
    main(["tasks", "build", "--split", "train_mining", "--n", "30", "--out", f"{d}/tasks"])
    tasks = f"{d}/tasks/train_mining.public.jsonl"
    private = f"{d}/tasks/train_mining.private.jsonl"
    assert "CANARY-" not in open(tasks, encoding="utf-8").read()

    # an interrupted run: 10 tasks, then resume to 30
    main(["run", "--tasks", tasks, "--backend", "scripted", "--corruption", "no_convert", "--out", f"{d}/runs/mining",
          "--limit", "10", "--batch-size", "4"])
    assert len(_lines(f"{d}/runs/mining/traces.jsonl")) == 10
    main(["run", "--tasks", tasks, "--backend", "scripted", "--corruption", "no_convert", "--out", f"{d}/runs/mining"])
    traces = _lines(f"{d}/runs/mining/traces.jsonl")
    assert len(traces) == 30 and len({t["task_id"] for t in traces}) == 30

    main(["eval", "--traces", f"{d}/runs/mining/traces.jsonl", "--private", private, "--out", f"{d}/runs/mining/evals.jsonl"])
    main(["report", "baseline", "--evals", f"{d}/runs/mining/evals.jsonl", "--names", "scripted-no-convert",
          "--out", f"{d}/reports/baseline.md"])
    report = open(f"{d}/reports/baseline.md", encoding="utf-8").read()
    assert "unit_error" in report and "mock" in report
    assert "最终回复虚报" in report and "报告里有工具没算出过的数" in report and "ver-" in report

    for policy, name in (("uniform", "B1"), ("targeted", "C1"), ("unfiltered", "D1")):
        main(["data", "build", "--policy", policy, "--seed", "1", "--n", "20", "--evals", f"{d}/runs/mining/evals.jsonl",
              "--out", f"{d}/sft/{name}"])
    main(["export", "sft", "--records", f"{d}/sft/B1/records.jsonl", f"{d}/sft/C1/records.jsonl", f"{d}/sft/D1/records.jsonl",
          "--names", "B1", "C1", "D1", "--format", "trl", "--seed", "1", "--out", f"{d}/export"])
    sizes = {name: len(_lines(f"{d}/export/{name}.trl.jsonl")) for name in ("B1", "C1", "D1")}
    assert len(set(sizes.values())) == 1
    manifest = json.load(open(f"{d}/export/D1.manifest.json", encoding="utf-8"))
    assert manifest["corrupted_trajectories"] == 5 and manifest["policy"] == "unfiltered"
    assert os.path.exists(f"{d}/export/C1.manifest.json")


def test_run_refuses_to_mix_configs_in_one_directory(tmp_path):
    import pytest
    d = str(tmp_path)
    main(["tasks", "build", "--split", "calibration", "--n", "4", "--out", f"{d}/tasks"])
    tasks = f"{d}/tasks/calibration.public.jsonl"
    main(["run", "--tasks", tasks, "--backend", "scripted", "--out", f"{d}/runs/a", "--limit", "2"])
    with pytest.raises(SystemExit):
        main(["run", "--tasks", tasks, "--backend", "scripted", "--corruption", "skip_filter", "--out", f"{d}/runs/a"])
    main(["run", "--tasks", tasks, "--backend", "scripted", "--out", f"{d}/runs/a"])  # same config resumes fine
    assert len(_lines(f"{d}/runs/a/traces.jsonl")) == 4


def test_infra_errors_are_run_again_and_the_old_file_is_kept(tmp_path):
    d = str(tmp_path)
    main(["tasks", "build", "--split", "calibration", "--n", "4", "--out", f"{d}/tasks"])
    tasks = f"{d}/tasks/calibration.public.jsonl"
    main(["run", "--tasks", tasks, "--backend", "scripted", "--out", f"{d}/runs/a"])
    path = f"{d}/runs/a/traces.jsonl"
    traces = _lines(path)
    crashed = dict(traces[1], termination="infra_error", raw_outputs=[], messages=traces[1]["messages"][:2],
                   events=[{"turn": 1, "kind": "infra_error", "detail": "OutOfMemoryError()"}])
    with open(path, "w", encoding="utf-8") as fh:
        for t in (traces[0], crashed, traces[2], traces[3]):
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    main(["run", "--tasks", tasks, "--backend", "scripted", "--out", f"{d}/runs/a"])
    after = _lines(path)
    assert sorted(t["task_id"] for t in after) == sorted(t["task_id"] for t in traces)
    assert all(t["termination"] != "infra_error" for t in after)
    rerun = next(t for t in after if t["task_id"] == traces[1]["task_id"])
    assert rerun["raw_outputs"] == traces[1]["raw_outputs"]
    backups = [name for name in os.listdir(f"{d}/runs/a") if name.endswith(".bak")]
    assert len(backups) == 1
    assert [t["termination"] for t in _lines(f"{d}/runs/a/{backups[0]}")].count("infra_error") == 1


def test_a_prompt_the_backend_cannot_run_ends_only_its_own_episode():
    from evidenceloop.harness.loop import run_episodes
    from evidenceloop.harness.scripted import ScriptedBackend
    from evidenceloop.tasks.generator import generate_split

    tasks = generate_split("validation", 3)[0]
    scripted = ScriptedBackend()

    class OneDoesNotFit:  # like HFBackend when a single prompt runs out of GPU memory
        def generate_batch(self, batch, tools):
            outputs = scripted.generate_batch(batch, tools)
            return [None if messages[1]["content"] == tasks[1]["prompt"] else out for messages, out in zip(batch, outputs)]

        def describe(self):
            return {"backend": "test", "execution_mode": "mock"}

    traces = run_episodes(tasks, OneDoesNotFit())
    assert [t["termination"] for t in traces] == ["final_answer", "infra_error", "final_answer"]
    assert traces[1]["events"][-1]["kind"] == "infra_error"
    assert traces[0]["messages"] == run_episodes(tasks[:1], scripted)[0]["messages"], "the others are untouched"


def test_missing_inputs_stop_with_an_error_instead_of_giving_empty_results(tmp_path):
    import pytest

    d = str(tmp_path)
    for args in (["eval", "--traces", f"{d}/no.jsonl", "--private", f"{d}/no.jsonl", "--out", f"{d}/e.jsonl"],
                 ["report", "baseline", "--evals", f"{d}/no.jsonl", "--out", f"{d}/r.md"],
                 ["data", "build", "--policy", "targeted", "--seed", "1", "--n", "2", "--evals", f"{d}/no.jsonl",
                  "--out", f"{d}/C1"],
                 ["export", "sft", "--records", f"{d}/no.jsonl", "--format", "trl", "--out", f"{d}/x"],
                 ["run", "--tasks", f"{d}/no.jsonl", "--backend", "scripted", "--out", f"{d}/runs"]):
        with pytest.raises(SystemExit):
            main(args)
    assert not os.path.exists(f"{d}/r.md") and not os.path.exists(f"{d}/e.jsonl")


def test_task_build_never_overwrites_silently(tmp_path):
    d = str(tmp_path)
    main(["tasks", "build", "--split", "calibration", "--n", "3", "--out", f"{d}/tasks"])
    first = open(f"{d}/tasks/calibration.public.jsonl", encoding="utf-8").read()
    main(["tasks", "build", "--split", "calibration", "--n", "5", "--out", f"{d}/tasks"])
    assert open(f"{d}/tasks/calibration.public.jsonl", encoding="utf-8").read() == first
    main(["tasks", "build", "--split", "calibration", "--n", "5", "--out", f"{d}/tasks", "--force"])
    assert len(_lines(f"{d}/tasks/calibration.public.jsonl")) == 5


def test_gitignore_only_excludes_root_level_outputs():
    """A bare 'data/' pattern once hid the whole src/evidenceloop/data package from git."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    patterns = [line.strip() for line in (root / ".gitignore").read_text().splitlines() if line.strip()]
    for name in ("data/", "runs/", ".venv/", "reports/"):
        assert name not in patterns, f"{name} must be anchored as /{name} or not ignored"
    assert (root / "src/evidenceloop/data/build.py").exists()


def test_freeze_builds_checks_and_records_the_splits(tmp_path):
    d = str(tmp_path)
    tasks = f"{d}/tasks"
    main(["tasks", "build", "--split", "calibration", "--n", "6", "--out", tasks])
    open(f"{d}/calibration.md", "w").write("# 校准报告\n")
    args = ["freeze", "--tasks-dir", tasks, "--base", "Qwen/Qwen3-1.7B", "--calibration", f"{d}/calibration.md",
            "--sizes", "train_mining=8", "validation=4", "test_id=4", "test_ood=4", "--out", f"{d}/configs/frozen.json"]
    main(args)
    first = json.load(open(f"{d}/configs/frozen.json", encoding="utf-8"))
    assert first["base_model"] == "Qwen/Qwen3-1.7B" and first["checks"]["no_duplicates_across_splits"]
    assert first["calibration_reports"] == [f"{d}/calibration.md"]
    assert {s: v["n"] for s, v in first["splits"].items()} == {"calibration": 6, "train_mining": 8, "validation": 4,
                                                                 "test_id": 4, "test_ood": 4}
    main(args)  # running it again changes nothing: splits are never regenerated
    assert json.load(open(f"{d}/configs/frozen.json", encoding="utf-8"))["splits"] == first["splits"]


def test_freeze_refuses_a_split_of_the_wrong_size(tmp_path):
    import pytest

    d = str(tmp_path)
    tasks = f"{d}/tasks"
    main(["tasks", "build", "--split", "calibration", "--n", "3", "--out", tasks])
    main(["tasks", "build", "--split", "validation", "--n", "3", "--out", tasks])
    open(f"{d}/calibration.md", "w").write("# 校准报告\n")
    with pytest.raises(SystemExit):
        main(["freeze", "--tasks-dir", tasks, "--base", "x", "--calibration", f"{d}/calibration.md",
              "--sizes", "train_mining=3", "validation=5", "test_id=3", "test_ood=3", "--out", f"{d}/frozen.json"])
