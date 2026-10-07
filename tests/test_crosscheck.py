"""Acceptance: on 30 smoke tasks the oracle and the reference solver (working through the tools) agree."""
from decimal import Decimal

import pytest

from evidenceloop.common import within_tolerance
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import ScriptedBackend
from evidenceloop.verify.verifier import evaluate


@pytest.mark.parametrize("order", ["filter_first", "convert_first"])
def test_reference_solver_matches_oracle(calibration, order):
    pubs, privs, _ = calibration
    traces = run_episodes(pubs, ScriptedBackend(order=order))
    for trace in traces:
        private = privs[trace["task_id"]]
        result = evaluate(trace, private)
        assert result["task_success"], (trace["task_id"], result)
        draft = next(r for rid, r in trace["final_snapshot"]["reports"].items() if rid not in trace["init_snapshot"]["reports"])
        for item in draft["report"]["results"]:
            assert within_tolerance(Decimal(str(item["value"])), Decimal(private["reference"][item["statistic"]]))


def test_ood_reference_solver_succeeds_within_budget(ood_pool):
    pubs, privs, _ = ood_pool
    traces = run_episodes(pubs, ScriptedBackend())
    assert all(evaluate(t, privs[t["task_id"]])["task_success"] for t in traces)
    assert max(t["turns"] for t in traces) <= 12


def test_four_significant_digits_are_accepted_and_one_percent_errors_are_not(calibration):
    """The protocol allows 4 significant digits, so the verifier must accept them; real mistakes stay out."""
    import copy

    pubs, privs, _ = calibration
    for trace in run_episodes(pubs[:10], ScriptedBackend()):
        private = privs[trace["task_id"]]
        for fmt, should_pass in ((".4g", True), ("1pct", False)):
            altered = copy.deepcopy(trace)
            draft = next(r for rid, r in altered["final_snapshot"]["reports"].items()
                         if rid not in altered["init_snapshot"]["reports"])
            for item in draft["report"]["results"]:
                exact = Decimal(private["reference"][item["statistic"]])
                item["value"] = format(exact, ".4g") if fmt == ".4g" else str(exact * Decimal("1.01"))
            assert evaluate(altered, private)["checks"]["numeric_pass"] is should_pass, (fmt, trace["task_id"])


def test_short_tier_is_short_and_its_hint_counts_as_context(validation_pool):
    from evidenceloop.verify.grounding import ungrounded_arguments

    pubs, privs = validation_pool
    short = [p for p in pubs if p["knobs"]["units"] == "all_V"]
    assert short, "about a third of train-domain tasks should be short"
    for p in short:
        latest = privs[p["task_id"]]["required"]["protocol_version"]
        assert f"最新版本是 {latest}" in p["prompt"]
        assert p["env_config"]["error_injection"] is None
    for trace in run_episodes(short, ScriptedBackend()):
        result = evaluate(trace, privs[trace["task_id"]])
        assert result["task_success"] and ungrounded_arguments(trace["messages"]) == []
        assert sum(1 for e in trace["events"] if e["kind"] == "tool_call") <= 7
    # reading the hinted version straight away, without list_versions, is not a guess
    for p in short:
        required = privs[p["task_id"]]["required"]
        call = {"function": {"name": "read_protocol",
                             "arguments": {"protocol_id": required["protocol_id"], "version": required["protocol_version"]}}}
        messages = [{"role": "system", "content": p["system_prompt"]}, {"role": "user", "content": p["prompt"]},
                    {"role": "assistant", "content": "", "tool_calls": [call]}]
        assert ungrounded_arguments(messages) == []


def test_no_short_tier_in_ood(ood_pool):
    assert all(p["knobs"]["units"] != "all_V" for p in ood_pool[0])
