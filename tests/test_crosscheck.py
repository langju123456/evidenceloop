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
