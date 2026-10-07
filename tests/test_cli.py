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
