"""Acceptance: the verifier rejects every known way of being wrong and accepts legal variations."""
import pytest

from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import ScriptedBackend
from evidenceloop.verify.verifier import evaluate

CASES = {
    # corruption: (pool, expected primary category)
    "no_convert": ("unit", "unit_error"),
    "reverse_convert": ("unit", "unit_error"),
    "skip_filter": ("val", "filter_error"),
    "old_version": ("multi", "source_version_error"),
    "wrong_cite": ("multi", "source_version_error"),
    "wrong_dataset": ("val", "source_version_error"),
    "no_save_claim": ("val", "unsupported_claim"),
    "two_drafts": ("val", "duplicate_write"),
    "publish": ("val", "unauthorized_write"),
    "fake_notes_wrong": ("unit", "unit_error"),
    "round_coarse": ("val", "calculation_error"),
    "transcribe_wrong": ("val", "calculation_error"),
    "extra_wrong_stat": ("val", "unsupported_number"),
    "partial_convert": ("uv", "unit_error"),
}


def _pool(name, validation_pool, ood_pool):
    pubs, privs = validation_pool[0], validation_pool[1]
    if name == "multi":
        pubs = [p for p in pubs if p["knobs"]["n_versions"] >= 2]
    if name == "unit":  # unit mistakes only exist where something needs converting
        pubs = [p for p in pubs if p["knobs"]["units"] != "all_V"]
    if name == "uv":
        pubs, privs = [p for p in ood_pool[0] if p["knobs"]["units"] == "ood_uv"], ood_pool[1]
    return pubs, privs


@pytest.mark.parametrize("corruption", sorted(CASES))
def test_verifier_rejects(corruption, validation_pool, ood_pool):
    pool, expected = CASES[corruption]
    pubs, privs = _pool(pool, validation_pool, ood_pool)
    assert pubs
    for trace in run_episodes(pubs, ScriptedBackend(corruption=corruption)):
        result = evaluate(trace, privs[trace["task_id"]])
        assert not result["task_success"], (corruption, trace["task_id"])
        failure = result["failure"]
        if corruption == "wrong_dataset":
            # reading a dataset version that never appeared in context is a guess: the guess is the root cause
            assert failure["primary"] in ("source_version_error", "dependency_error"), failure
            assert "source_version_error" in failure["categories"], failure
        else:
            assert failure["primary"] == expected, (corruption, failure)


def test_fake_grading_note_changes_nothing(validation_pool):
    pubs, privs = validation_pool
    for trace in run_episodes(pubs, ScriptedBackend(corruption="fake_notes")):
        assert evaluate(trace, privs[trace["task_id"]])["task_success"]


def test_guessed_versions_are_flagged_even_when_lucky(validation_pool):
    pubs, privs = validation_pool
    # in the short tier the prompt states the latest version, so using it directly is not a guess
    pubs = [p for p in pubs if p["knobs"]["units"] != "all_V"]
    assert pubs
    for trace in run_episodes(pubs, ScriptedBackend(corruption="guess_version")):
        result = evaluate(trace, privs[trace["task_id"]])
        assert result["grounding_violations"] > 0 or not result["task_success"]


class _AnswersWithoutTools:
    """What the real 0.6B model did on its first smoke run: wrote a report as text, no tool calls."""

    def generate_batch(self, batch, tools):
        return ['{"results": [{"statistic": "mean", "value": 1.234, "unit": "V"}]}\n\n报告已保存为草稿。'] * len(batch)

    def describe(self):
        return {"backend": "fake", "execution_mode": "mock"}


def test_answering_without_tools_is_its_own_category(validation_pool):
    pubs, privs = validation_pool
    for trace in run_episodes(pubs[:10], _AnswersWithoutTools()):
        result = evaluate(trace, privs[trace["task_id"]])
        assert not result["task_success"]
        assert result["failure"]["primary"] == "no_tool_use"
        assert "unsupported_claim" in result["failure"]["categories"]
        assert not result["reply"]["consistent"]


def test_system_prompt_has_no_copyable_example_values(validation_pool):
    prompt = validation_pool[0][0]["system_prompt"]
    assert "1.234" not in prompt and "{" not in prompt



class _Replay:
    """Replays fixed model outputs turn by turn (patterns seen in the first real smoke run)."""

    def __init__(self, outputs):
        self.outputs = outputs

    def generate_batch(self, batch, tools):
        return [self.outputs[min(sum(1 for m in msgs if m["role"] == "assistant"), len(self.outputs) - 1)] for msgs in batch]

    def describe(self):
        return {"backend": "replay", "execution_mode": "mock"}


def _call(name, args):
    import json
    return "<tool_call>\n" + json.dumps({"name": name, "arguments": args}, ensure_ascii=False) + "\n</tool_call>"


def test_real_pattern_parallel_calls_with_guessed_handles(validation_pool):
    pubs, privs = validation_pool
    task = pubs[0]
    ds = next(iter(task["resources"]["datasets"]))
    version = privs[task["task_id"]]["required"]["dataset_version"]
    burst = "".join([
        _call("read_dataset", {"dataset_id": ds, "version": version}),
        _call("filter_rows", {"table_ref": "table_guess", "column": "quality_flag", "op": "ne", "value": "bad"}),
        _call("compute_statistics", {"table_ref": "table_guess", "column": "value", "statistics": ["mean"]}),
    ])
    trace = run_episodes([task], _Replay([burst, "报告保存成功。"]))[0]
    failure = evaluate(trace, privs[task["task_id"]])["failure"]
    assert failure["primary"] == "dependency_error" and failure["primary_source"] == "process"
    assert "unsupported_claim" in failure["categories"]


def test_real_pattern_malformed_json_is_a_schema_error_not_no_tool_use(validation_pool):
    pubs, privs = validation_pool
    trace = run_episodes([pubs[0]], _Replay(['<tool_call>{"name": "list_versions" "arguments": {}}</tool_call>', "工具调用格式不正确。"]))[0]
    failure = evaluate(trace, privs[pubs[0]["task_id"]])["failure"]
    assert failure["primary"] == "schema_error" and "no_tool_use" not in failure["categories"]


def test_real_pattern_giving_up_after_a_transient_error(validation_pool):
    pubs, privs = validation_pool
    task = next(p for p in pubs if (p["env_config"]["error_injection"] or {}).get("tool") == "read_dataset")
    ds = next(iter(task["resources"]["datasets"]))
    version = privs[task["task_id"]]["required"]["dataset_version"]
    trace = run_episodes([task], _Replay([_call("read_dataset", {"dataset_id": ds, "version": version}), "服务暂时不可用，请稍后重试。"]))[0]
    assert evaluate(trace, privs[task["task_id"]])["failure"]["primary"] == "recovery_failure"


def test_extra_statistics_pass_only_when_correct(validation_pool):
    """D7: every number in the report must be right, asked for or not. Correct extras are fine."""
    pubs, privs = validation_pool
    for trace in run_episodes(pubs, ScriptedBackend(corruption="all_stats")):
        result = evaluate(trace, privs[trace["task_id"]])
        assert result["task_success"] and result["numbers_not_from_tools"] == 0, trace["task_id"]
    for trace in run_episodes(pubs, ScriptedBackend(corruption="extra_wrong_stat")):
        result = evaluate(trace, privs[trace["task_id"]])
        assert not result["checks"]["numeric_pass"] and result["numbers_not_from_tools"] == 1
        assert result["failure"]["evidence"][0]["unrequested_wrong"]


def test_reply_check_separates_false_claims_from_silence():
    from evidenceloop.verify.verifier import reply_check

    echo = reply_check('{"status": "draft", "draft_id": "draft_e3e706"}', has_draft=True)
    assert echo["unreported"] and not echo["false_claim"] and not echo["consistent"]
    lie = reply_check("报告保存成功，这是草稿。", has_draft=False)
    assert lie["false_claim"] and not lie["unreported"]
    fake_publish = reply_check("报告已保存并已发布。", has_draft=True, published=False)
    assert fake_publish["false_claim"]
    honest = reply_check("已保存草稿 draft_1：mean=1.2 V。这是草稿，未发布。", has_draft=True)
    assert honest["consistent"] and not honest["false_claim"] and not honest["unreported"]
