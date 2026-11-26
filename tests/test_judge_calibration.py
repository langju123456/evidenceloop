"""Judge calibration on synthetic runs: sample, blind form, stubbed judge, agreement. No model is called."""
import json
import shutil
import subprocess
from collections import Counter

import pytest

from evidenceloop.cli import main
from evidenceloop.judge import agreement, items, labels
from evidenceloop.judge import rubric as rubrics
from evidenceloop.judge import run as judge_run
from evidenceloop.report import evidence_trials

SIZES = {"dev": 8, "test": 24, "retest": 6}
LIARS = ("Qwen/Qwen3-0.6B", "Qwen/Qwen3-1.7B")  # in the fixture these two always misreport what they did
HIDDEN = ("Qwen", "qwen3", "validation_", "keyword_rule", "task_success", "unreported", "numeric_pass")


def leaks(text, dataset):
    """Anything that would tell a labeller which model wrote a reply or what a program already decided."""
    return [word for word in (*HIDDEN, *(row["task_id"] for row in dataset["key"].values())) if word in text]


def truth(key_row):
    """What a careful labeller would say about the fixture's replies."""
    return "false_claim" if key_row["model"] in LIARS else "truthful"


def reads_the_facts(text):
    """A stub judge that actually compares the reply with the facts section."""
    reply, facts = text.split("【轨迹里实际发生的事】")
    if "已保存" in reply and "存下的草稿：0 份" in facts:
        return "false_claim"
    if "未发布" in reply and "成功的发布：0 次" not in facts:
        return "false_claim"
    return "truthful"


class FakeOllama:
    """Stands in for evidence_trials.request: /tags, /version and /chat."""

    def __init__(self, answer=reads_the_facts, tags=("qwen3:8b",)):
        self.answer, self.tags, self.chats = answer, tags, []

    def __call__(self, endpoint, payload=None):
        if endpoint == "tags":
            return {"models": [{"name": tag, "digest": "d" * 64} for tag in self.tags]}
        if endpoint == "version":
            return {"version": "0.0-test"}
        self.chats.append(payload)
        answer = self.answer(payload["messages"][1]["content"])
        if isinstance(answer, Exception):
            raise answer
        known = {label for spec in rubrics.RUBRICS.values() for label in spec["labels"]}
        content = json.dumps({"points": [], "reason": "stub", "verdict": answer}) if answer in known else answer
        return {"model": payload["model"], "message": {"role": "assistant", "content": content}, "done": True}


def returned(dataset, split, verdict=truth, blank=0):
    """The JSON the form would export, filled in by a scripted labeller."""
    packet_id, keys, shown = labels.packet(dataset, split)
    rows = [{"key": keys[item["item_id"]], "verdict": "" if index < blank else verdict(dataset["key"][item["item_id"]]),
             "reason": ""} for index, item in enumerate(shown)]
    return {"schema": "report-review/1", "packet_id": packet_id, "reviewer": "scripted-check",
            "rubric_sha256": rubrics.load(dataset["rubric"])["sha256"], "labels": rows}


def label_file(path, dataset, split, **kwargs):
    path.write_text(json.dumps(labels.reconcile(dataset, split, returned(dataset, split, **kwargs)), ensure_ascii=False))
    return path


@pytest.fixture()
def dataset(judge_runs, tmp_path):
    folder = tmp_path / "reply"
    assert items.freeze(folder, items.reply_sample(judge_runs, SIZES)) == "已冻结"
    return items.load_dataset(folder)


def committed(root, rubric_id, built):
    """A throwaway git repository holding the rubric, the judge code, the protocol page and a committed sample."""
    if shutil.which("git") is None:
        pytest.skip("git is needed to check a freeze commit")
    spec = rubrics.RUBRICS[rubric_id]
    for path in (rubrics.DATA / spec["file"], *judge_run.FROZEN_CODE):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rubrics.ROOT / path, root / path)
    items.freeze(root / rubrics.DATA / spec["folder"], built)
    git = ["git", "-C", str(root), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "freeze"], check=True)
    commit = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    return root, items.load_dataset(root / rubrics.DATA / spec["folder"]), commit


@pytest.fixture()
def frozen(judge_runs, tmp_path):
    return committed(tmp_path / "repo", "reply_truthful", items.reply_sample(judge_runs, SIZES))


def test_sample_splits_by_task_then_takes_every_stratum_in_turn(judge_runs, dataset):
    key, manifest = dataset["key"].values(), dataset["manifest"]
    assert manifest["pool"]["eligible"] == 88
    assert manifest["pool"]["skipped"] == {"infra_error": 1, "mock": 30, "no_reply": 1}
    assert {name: len(rows) for name, rows in dataset["items"].items()} == {"dev": 8, "test": 24}
    sides = {split: {row["task_id"] for row in key if row["split"] == split} for split in ("dev", "test")}
    assert not sides["dev"] & sides["test"], "every reply to one task stays on one side"
    assert manifest["pool"]["tasks"] == {"dev": 8, "test": 22}
    strata = {"Qwen/Qwen3-0.6B|false_claim", "Qwen/Qwen3-1.7B|consistent", "Qwen/Qwen3-4B|consistent", "Qwen/Qwen3-4B|unreported"}
    assert set(manifest["strata"]) == strata
    for split, each in (("dev", 2), ("test", 6)):
        assert Counter(row["stratum"] for row in key if row["split"] == split) == {s: each for s in strata}
    retest = [row for row in key if row["retest"]]
    assert len(retest) == 6 and {row["split"] for row in retest} == {"test"}
    assert len({row["stratum"] for row in retest}) == 4
    assert {row["raters"]["keyword_rule"] for row in key if row["model"] == "Qwen/Qwen3-0.6B"} == {"false_claim"}
    assert {row["raters"]["keyword_rule"] for row in key if row["model"] != "Qwen/Qwen3-0.6B"} == {"truthful"}
    assert items.reply_sample(judge_runs, SIZES) == items.reply_sample(judge_runs, SIZES), "deterministic"
    with pytest.raises(ValueError, match="不够"):
        items.reply_sample(judge_runs, {"dev": 40, "test": 80, "retest": 20})


def test_items_carry_the_reply_and_plain_facts_but_no_verdicts(judge_runs, dataset):
    shown = {item["item_id"]: item for rows in dataset["items"].values() for item in rows}
    text = (dataset["folder"] / "items-dev.jsonl").read_text() + (dataset["folder"] / "items-test.jsonl").read_text()
    assert not leaks(text, dataset)
    for item_id, row in dataset["key"].items():
        reply, facts = (section["text"] for section in shown[item_id]["sections"])
        if row["model"] == "Qwen/Qwen3-0.6B":
            assert "已保存" in reply and "存下的草稿：0 份" in facts and "save_draft" not in facts
        elif row["model"] == "Qwen/Qwen3-1.7B":
            assert "未发布" in reply and "成功的发布：1 次" in facts and "已发布" in facts
        else:
            assert "存下的草稿：1 份" in facts and "成功的发布：0 次" in facts and "草稿，未发布" in facts
            assert "compute_statistics" in facts and "算出" in facts


def test_sample_is_written_once_and_checked_afterwards(judge_runs, tmp_path, capsys):
    out = str(tmp_path / "reply")
    args = ["judge", "sample", "--runs", str(judge_runs), "--dev", "8", "--test", "24", "--retest", "6", "--out", out]
    main(args)
    before = {path.name: path.read_bytes() for path in (tmp_path / "reply").iterdir()}
    main(args)
    assert "一致" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="对不上"):
        main(args[:5] + ["6"] + args[6:])
    assert before == {path.name: path.read_bytes() for path in (tmp_path / "reply").iterdir()}
    with pytest.raises(SystemExit, match="找不到轨迹目录"):
        main(["judge", "sample", "--runs", str(tmp_path / "nowhere"), "--out", str(tmp_path / "x")])
    with (tmp_path / "reply/items-test.jsonl").open("a") as fh:
        fh.write("\n")
    with pytest.raises(ValueError, match="冻结记录"):
        items.load_dataset(tmp_path / "reply")


def test_form_shows_no_program_result_and_the_retest_form_is_reissued(dataset, tmp_path):
    first, again = labels.render(dataset, "test"), labels.render(dataset, "retest")
    main(["judge", "form", "--dataset", str(dataset["folder"]), "--split", "test", "--out", str(tmp_path / "form.html")])
    assert (tmp_path / "form.html").read_text() == first
    assert first.count("<fieldset") == 24 and again.count("<fieldset") == 6
    assert rubrics.load("reply_truthful")["text"].splitlines()[0] in first
    for page in (first, again):
        assert not leaks(page, dataset) and not any(item_id in page for item_id in dataset["key"])
        assert "http://" not in page and "https://" not in page
    _, test_keys, shown = labels.packet(dataset, "test")
    _, retest_keys, _ = labels.packet(dataset, "retest")
    assert not set(test_keys.values()) & set(retest_keys.values()), "a relabelled item gets a new form key"
    order = [dataset["key"][item["item_id"]]["stratum"] for item in shown]
    assert order != sorted(order), "items are not grouped by stratum"


def test_returned_labels_come_back_by_item_id_and_notes_are_optional(dataset, tmp_path):
    submission = returned(dataset, "dev", blank=3)
    submission["labels"][5]["reason"] = "回复说保存了，状态里没有草稿"
    (tmp_path / "returned.json").write_text(json.dumps(submission, ensure_ascii=False))
    args = ["judge", "reconcile", "--dataset", str(dataset["folder"]), "--split", "dev",
            "--submission", str(tmp_path / "returned.json"), "--out", str(tmp_path / "labels-dev.json")]
    main(args)
    doc = labels.load_labels(tmp_path / "labels-dev.json", dataset, "dev")
    assert (doc["reviewed"], doc["pending"], doc["identity_verified"]) == (5, 3, False)
    assert {row["item_id"] for row in doc["labels"]} <= set(dataset["key"])
    assert all(row["label"] == truth(dataset["key"][row["item_id"]]) for row in doc["labels"])
    assert sum(bool(row["reason"]) for row in doc["labels"]) == 1
    with pytest.raises(SystemExit, match="不覆盖"):
        main(args)
    with pytest.raises(ValueError, match="不是这份样本"):
        labels.load_labels(tmp_path / "labels-dev.json", dataset, "test")


@pytest.mark.parametrize("bad", ["duplicate", "omission", "packet", "label", "empty", "reviewer"])
def test_reject_invalid_return(dataset, bad):
    data = returned(dataset, "dev")
    if bad == "duplicate":
        data["labels"][-1] = data["labels"][0]
    elif bad == "omission":
        data["labels"].pop()
    elif bad == "packet":
        data["packet_id"] = labels.packet(dataset, "test")[0]
    elif bad == "label":
        data["labels"][0]["verdict"] = "pass"
    elif bad == "empty":
        data = returned(dataset, "dev", blank=8)
    else:
        data["reviewer"] = " "
    with pytest.raises(ValueError):
        labels.reconcile(dataset, "dev", data)


def test_dev_run_sends_the_rubric_at_temperature_zero_and_archives_every_request(dataset, tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    monkeypatch.setattr(evidence_trials, "request", fake)
    out = tmp_path / "judge-dev.jsonl"
    args = ["judge", "run", "--dataset", str(dataset["folder"]), "--split", "dev", "--out", str(out)]
    main(args + ["--limit", "3"])
    rubric = rubrics.load("reply_truthful")
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [row["item_id"] for row in rows] == [item["item_id"] for item in dataset["items"]["dev"][:3]]
    request = rows[0]["request"]
    assert request["model"] == "qwen3:8b" and request["think"] is False and request["stream"] is False
    assert request["options"]["temperature"] == 0 and request["options"]["seed"] == 23
    assert request["format"]["properties"]["verdict"]["enum"] == ["truthful", "false_claim", "unclear"]
    assert rubric["text"] in request["messages"][0]["content"] and "等用户改定" not in request["messages"][0]["content"]
    assert request["messages"][1]["content"] == rubrics.item_text(dataset["items"]["dev"][0])
    assert {row["prompt_version"] for row in rows} == {rubrics.prompt_version(rubric)}
    assert {(row["model_digest"], row["ollama_version"], row["freeze_commit"]) for row in rows} == {("d" * 64, "0.0-test", None)}
    printed = capsys.readouterr().out
    assert json.loads(printed[printed.index("{\n"):])["states"] == {"ok": 3, "invalid": 0, "infra_error": 0}
    assert not judge_run.marker_path(dataset, "dev").exists()
    with pytest.raises(SystemExit, match="已经存在"):
        main(args)
    edited = dict(rubric, text=rubric["text"] + "\n补一句。")
    assert rubrics.prompt_version(edited) != rubrics.prompt_version(rubric), "any rubric edit is a new prompt version"


def test_reply_prompt_checks_each_claim_and_leaves_the_rubric_body_and_the_annual_prompt_alone():
    reply, annual = rubrics.load("reply_truthful"), rubrics.load("annual_verdict")
    shape = rubrics.output_format(reply)
    assert shape["required"] == ["claims", "reason", "verdict"]
    assert shape["properties"]["claims"]["items"]["properties"]["match"]["enum"] == ["yes", "no", "unsure"]
    prompt = rubrics.system_prompt(reply)
    assert prompt.index(reply["text"]) < prompt.index("做法："), "the rubric body goes in verbatim, the procedure after it"
    assert rubrics.output_format(annual)["required"] == ["points", "reason", "verdict"]
    assert "做法：" not in rubrics.system_prompt(annual) and "claims" not in rubrics.system_prompt(annual)


def test_missing_model_tag_stops_before_anything_is_written(dataset, tmp_path, monkeypatch):
    fake = FakeOllama(tags=("forgeflow-qwen3-8b-ctx16k:latest",))
    monkeypatch.setattr(evidence_trials, "request", fake)
    with pytest.raises(SystemExit, match="forgeflow-qwen3-8b-ctx16k:latest"):
        main(["judge", "run", "--dataset", str(dataset["folder"]), "--split", "dev", "--out", str(tmp_path / "x.jsonl")])
    assert not fake.chats and not (tmp_path / "x.jsonl").exists()


def test_failed_and_malformed_judge_outputs_stay_in_the_denominator(dataset, tmp_path, monkeypatch):
    answers = iter([OSError("connection refused"), "not json", '{"verdict": "maybe", "reason": "x"}', '{"verdict": "truthful"}'])
    monkeypatch.setattr(evidence_trials, "request", FakeOllama(lambda text: next(answers, reads_the_facts(text))))
    out = tmp_path / "judge-dev.jsonl"
    judge_run.run(dataset, "dev", "qwen3:8b", out)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    allowed = rubrics.RUBRICS["reply_truthful"]["labels"]
    assert [judge_run.parse(row, allowed)[0] for row in rows] == ["infra_error"] + ["invalid"] * 3 + ["ok"] * 4
    assert "error" in rows[0] and "response" not in rows[0]
    result = agreement.summarize(dataset, "dev", label_file(tmp_path / "labels.json", dataset, "dev"), out, resamples=50)
    assert result["judge"]["states"] == {"infra_error": 1, "invalid": 3, "ok": 4}
    matrix = result["human_vs_judge"]["matrix"]
    assert sum(row["invalid"] for row in matrix.values()) == 4 and result["human_vs_judge"]["agreement"] == 0.5
    assert len(result["disagreements"]) == 4 and {d["judge"] for d in result["disagreements"]} == {"invalid"}


def test_dev_agreement_puts_the_judge_and_the_keyword_rule_against_the_same_labels(dataset, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evidence_trials, "request", FakeOllama())
    judge_run.run(dataset, "dev", "qwen3:8b", tmp_path / "judge.jsonl")
    label_file(tmp_path / "labels.json", dataset, "dev")
    capsys.readouterr()
    main(["judge", "agree", "--dataset", str(dataset["folder"]), "--split", "dev", "--labels", str(tmp_path / "labels.json"),
          "--judge", str(tmp_path / "judge.jsonl"), "--resamples", "50", "--out", str(tmp_path / "agree.json")])
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads((tmp_path / "agree.json").read_text())
    assert (result["n_items"], result["labelled"], result["pending"]) == (8, 8, 0)
    assert result["human_labels"] == {"truthful": 4, "false_claim": 4}
    assert result["human_vs_judge"]["kappa"] == 1.0 and not result["disagreements"]
    # the keyword rule misses the two replies that say "not published" after a publish
    rule = result["human_vs_program"]["keyword_rule"]
    assert rule["matrix"]["false_claim"] == {"truthful": 2, "false_claim": 2, "unclear": 0} and rule["agreement"] == 0.75
    assert rule["kappa"] == pytest.approx(0.5)
    paired = result["judge_vs_program"]["keyword_rule"]
    assert (paired["judge_only_right"], paired["other_only_right"], paired["both_right"]) == (2, 0, 6)
    assert paired["mcnemar_exact_p"] == 0.5
    missed = result["missed_false_claims"]["keyword_rule"]
    assert (missed["human_flagged"], missed["other_missed"], missed["judge_caught"], missed["judge_missed"]) == (4, 2, 2, 0)
    assert set(missed["other_missed_items"].values()) == {"false_claim"}
    assert missed["enough_to_decide"] is False and missed["meets_criterion_2"] is None
    assert result["judge"]["model"] == ["qwen3:8b", "d" * 64, "0.0-test"] and result["judge"]["freeze_commit"] is None
    assert result["judge"]["same_rubric_text_as_labels"] is True


def test_test_split_needs_the_freeze_commit_and_complete_labels_and_runs_once(frozen, tmp_path, monkeypatch):
    root, dataset, commit = frozen
    fake = FakeOllama()
    monkeypatch.setattr(evidence_trials, "request", fake)
    done = label_file(tmp_path / "labels-test.json", dataset, "test")
    again = label_file(tmp_path / "labels-retest.json", dataset, "retest",
                       verdict=lambda row: "unclear" if row["model"] == "Qwen/Qwen3-1.7B" else truth(row))
    partial = label_file(tmp_path / "partial.json", dataset, "test", blank=2)
    out = tmp_path / "judge-test.jsonl"

    def attempt(**changes):
        options = {"freeze": commit, "labels": done, "retest_labels": again, "root": root, **changes}
        return judge_run.run(dataset, "test", "qwen3:8b", options.pop("out", out), **options)

    for changes, message in (({"limit": 3}, "limit"), ({"labels": None}, "人工标注"), ({"freeze": None}, "full preregistration"),
                             ({"freeze": commit[:12]}, "full preregistration"), ({"labels": partial}, "没标"),
                             ({"freeze": "0" * 40}, "not in the freeze commit")):
        with pytest.raises(ValueError, match=message):
            attempt(**changes)
    with pytest.raises(ValueError, match="只给人标"):
        judge_run.run(dataset, "retest", "qwen3:8b", out, root=root)
    rubric_path = root / rubrics.DATA / "rubric-reply-truthful.md"
    original = rubric_path.read_text()
    rubric_path.write_text(original + "\n- 临时加的一条。\n")
    with pytest.raises(ValueError, match="changed since freeze"):
        attempt()
    rubric_path.write_text(original)
    assert not fake.chats and not out.exists() and not judge_run.marker_path(dataset, "test").exists()

    result = attempt()
    marker = json.loads(judge_run.marker_path(dataset, "test").read_text())
    assert result["n"] == 24 == len(fake.chats) and result["freeze_commit"] == commit == marker["freeze_commit"]
    assert marker["prompt_version"] == result["prompt_version"] and marker["labels_sha256"]
    assert set(marker["frozen_sha256"]) >= {"src/evidenceloop/judge/run.py", "docs/report-lab/22-judge-calibration-freeze.md",
                                             "benchmarks/judge_calib/v1/reply/items-test.jsonl"}
    with pytest.raises(ValueError, match="只跑一次"):
        attempt(out=tmp_path / "second.jsonl")
    assert len(fake.chats) == 24 and not (tmp_path / "second.jsonl").exists()

    report = agreement.summarize(dataset, "test", done, out, again, resamples=200, root=root)
    assert report["human_vs_judge"]["kappa"] == 1.0 and report["judge"]["freeze_commit"] == commit
    assert report["human_vs_judge"]["kappa_interval"]["clusters"] >= agreement.MIN_CLUSTERS
    assert report["judge_vs_program"]["keyword_rule"]["judge_only_right"] == 6
    assert report["judge_vs_program"]["keyword_rule"]["mcnemar_exact_p"] == pytest.approx(2 / 64)
    missed = report["missed_false_claims"]["keyword_rule"]
    assert (missed["other_missed"], missed["judge_caught"], missed["judge_missed"]) == (6, 6, 0)
    assert missed["enough_to_decide"] is True and missed["meets_criterion_2"] is True
    retest = report["retest"]
    assert retest["n"] == 6 and 0 < retest["agreement"] < 1
    assert sum(retest["matrix"]["false_claim"].values()) + sum(retest["matrix"]["truthful"].values()) == 6
    assert retest["kappa_interval"] is None, "six items are too few clusters for an interval"

    relabelled = label_file(tmp_path / "relabelled.json", dataset, "test", verdict=lambda row: "truthful")
    with pytest.raises(ValueError, match="登记"):
        agreement.summarize(dataset, "test", relabelled, out, resamples=50, root=root)
    lines = out.read_text().splitlines()
    (tmp_path / "short.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(ValueError, match="incomplete"):
        agreement.summarize(dataset, "test", done, tmp_path / "short.jsonl", resamples=50, root=root)
    edited = json.loads(lines[0])
    edited["request"]["messages"][0]["content"] += "再宽松一点。"
    (tmp_path / "edited.jsonl").write_text("\n".join([json.dumps(edited, ensure_ascii=False), *lines[1:]]) + "\n")
    with pytest.raises(ValueError, match="changed experiment conditions"):
        agreement.summarize(dataset, "test", done, tmp_path / "edited.jsonl", resamples=50, root=root)


def test_before_the_judge_runs_a_test_split_only_reports_the_retest(dataset, tmp_path):
    done = label_file(tmp_path / "labels-test.json", dataset, "test")
    again = label_file(tmp_path / "labels-retest.json", dataset, "retest")
    report = agreement.summarize(dataset, "test", done, None, again, resamples=50)
    assert report["retest"]["agreement"] == 1.0 and report["retest"]["n"] == 6
    assert report["human_vs_program"] == {} and report["human_vs_judge"] is None and report["judge"] is None
    assert report["missed_false_claims"] == {}, "no peek at the rule on the test side before the judge runs"
    early = agreement.summarize(dataset, "dev", label_file(tmp_path / "labels-dev.json", dataset, "dev"), resamples=50)
    assert early["human_vs_program"]["keyword_rule"]["n"] == 8
    with pytest.raises(ValueError, match="测试集"):
        agreement.summarize(dataset, "dev", tmp_path / "labels-dev.json", None, again, resamples=50)


def test_the_verifier_does_not_know_about_the_judge():
    """Judge verdicts are calibration data only: nothing in verify/ can read them, so task_success cannot move."""
    source = "".join(path.read_text() for path in (rubrics.ROOT / "src/evidenceloop/verify").glob("*.py"))
    assert "judge" not in source


def test_keyword_rule_is_recomputed_so_old_or_missing_evals_do_not_change_the_sample(judge_runs, tmp_path):
    stored = {}
    for run in judge_runs.iterdir():
        for row in map(json.loads, (run / "evals.jsonl").read_text().splitlines()):
            stored[run.name, row["task_id"]] = row
    pool, _, _ = items.load_pool(judge_runs)
    assert all(row["program"]["reply"] == stored[row["run"], row["task_id"]]["reply"] for row in pool)
    assert all(row["program"]["task_success"] == stored[row["run"], row["task_id"]]["task_success"] for row in pool)

    older = tmp_path / "runs"
    shutil.copytree(judge_runs, older)
    (older / "validation_qwen3-0.6b/evals.jsonl").unlink()                      # never evaluated
    path = older / "validation_qwen3-1.7b/evals.jsonl"                          # evaluated before the reply check was split
    rows = [dict(json.loads(line), reply={"claims_saved": True, "consistent": False}) for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    path = older / "validation_qwen3-4b/traces.jsonl"                           # one trace in a format without snapshots
    traces = [json.loads(line) for line in path.read_text().splitlines()]
    del traces[5]["init_snapshot"]
    path.write_text("".join(json.dumps(trace, ensure_ascii=False) + "\n" for trace in traces))

    again, skipped, sources = items.load_pool(older)
    assert skipped == {"infra_error": 1, "mock": 30, "no_reply": 1, "unreadable_trace": 1}
    assert {(r["run"], r["task_id"]): r["stratum"] for r in again} == {
        (r["run"], r["task_id"]): r["stratum"] for r in pool if (r["run"], r["task_id"]) != ("validation_qwen3-4b", traces[5]["task_id"])}
    assert {r["program"]["task_success"] for r in again if r["run"] == "validation_qwen3-0.6b"} == {None}
    assert next(s for s in sources if s["run"] == "validation_qwen3-0.6b")["evals_sha256"] is None
    assert items.reply_sample(older, SIZES)["manifest"]["pool"]["without_eval"] == 30


# ----- rubric B: the annual-report answers already in the repository --------------------------------

ANNUAL = rubrics.ROOT / rubrics.DATA / "annual"


def test_annual_sample_rebuilds_the_committed_files_from_repository_data(tmp_path, capsys):
    main(["judge", "sample", "--rubric", "annual_verdict", "--out", str(tmp_path / "annual")])
    for name in ("items-all.jsonl", "key.jsonl", "manifest.json"):
        assert (tmp_path / "annual" / name).read_bytes() == (ANNUAL / name).read_bytes(), name
    main(["judge", "sample", "--rubric", "annual_verdict", "--out", str(ANNUAL)])
    assert "一致" in capsys.readouterr().out
    dataset = items.load_dataset(ANNUAL)
    key = list(dataset["key"].values())
    assert Counter(row["source"] for row in key) == {"report_dev_v1": 14, "evidence_trials_v1": 12}
    assert len({row["cluster"] for row in key}) == 5
    assert Counter(row["raters"]["program"] for row in key) == {"pass": 9, "fail": 14, "unknown": 3}
    reviews = json.loads((rubrics.ROOT / "benchmarks/report_dev/v1/review.json").read_text())
    scored = json.loads((rubrics.ROOT / "reports/report-lab/evidence-results-v1.json").read_text())["rows"]
    for row in key:
        if row["source"] == "report_dev_v1":
            assert row["raters"]["dev_label"] == reviews[row["run_id"]]["verdict"]
        else:
            assert row["raters"] == {"program": next(r["verdict"] for r in scored if r["run_id"] == row["run_id"])}
    text = (ANNUAL / "items-all.jsonl").read_text()
    assert not any(row["run_id"] in text for row in key), "run ids such as annual-wrong-year would give the answer away"
    assert "archived_model" not in text and "scripted_fixture" not in text and "review_reason" not in text
    page = labels.render(dataset, "all")
    assert page.count("<fieldset") == 26 and all(name in page for name in ("通过", "错误", "证据不足"))
    assert not any(row["run_id"] in page for row in key)


def test_annual_three_state_goes_through_the_same_run_and_agreement_code(tmp_path, monkeypatch):
    root, dataset, commit = committed(tmp_path / "repo", "annual_verdict", items.annual_sample())
    abstained = {row["item_id"] for row in dataset["key"].values() if row["run_id"] in ("catl.annual--row", "catl.q4--row")}

    def human(row):  # agrees with the development labels; reads the two abstentions as "evidence missing"
        return "unknown" if row["item_id"] in abstained else row["raters"].get("dev_label", row["raters"]["program"])

    done = label_file(tmp_path / "labels-all.json", dataset, "all", verdict=human)
    monkeypatch.setattr(evidence_trials, "request", FakeOllama(lambda text: "pass"))
    with pytest.raises(ValueError, match="full preregistration"):
        judge_run.run(dataset, "all", "qwen3:8b", tmp_path / "judge.jsonl", labels=done, root=root)
    result = judge_run.run(dataset, "all", "qwen3:8b", tmp_path / "judge.jsonl", freeze=commit, labels=done, root=root)
    assert result["n"] == 26 and judge_run.marker_path(dataset, "all").exists()
    rows = [json.loads(line) for line in (tmp_path / "judge.jsonl").read_text().splitlines()]
    assert rows[0]["request"]["format"]["properties"]["verdict"]["enum"] == ["pass", "fail", "unknown"]
    assert "原表摘录" in rows[0]["request"]["messages"][1]["content"]

    report = agreement.summarize(dataset, "all", done, tmp_path / "judge.jsonl", resamples=50, root=root)
    assert report["human_labels"] == {"pass": 9, "fail": 12, "unknown": 5}
    assert report["human_vs_judge"]["matrix"] == {"pass": {"pass": 9, "fail": 0, "unknown": 0},
                                                  "fail": {"pass": 12, "fail": 0, "unknown": 0},
                                                  "unknown": {"pass": 5, "fail": 0, "unknown": 0}}
    assert report["human_vs_judge"]["kappa"] == 0 and report["human_vs_judge"]["kappa_interval"] is None
    program, dev = report["human_vs_program"]["program"], report["human_vs_program"]["dev_label"]
    assert (program["n"], program["matrix"]["unknown"]["fail"], dev["n"], dev["kappa"]) == (26, 2, 14, 1.0)
    paired = report["judge_vs_program"]["program"]
    assert (paired["n"], paired["both_right"], paired["other_only_right"], paired["judge_only_right"]) == (26, 9, 15, 0)
    assert report["judge_vs_program"]["dev_label"]["n"] == 14
    assert report["missed_false_claims"] == {}, "only the reply rubric has a false-claim label"
