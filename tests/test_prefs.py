"""D16: preference pairs. Chosen is always a legal next step, rejected never is, and the source can be swapped."""
import json

import pytest

from evidenceloop.data import prefs
from evidenceloop.data.build import build_training_set
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.parser import parse_assistant_output
from evidenceloop.harness.scripted import CORRUPTIONS, ScriptedBackend, next_action


@pytest.fixture(scope="module")
def built():
    data = build_training_set("uniform", 7, 30)
    orders = {r["task_id"]: r["demo_order"] for r in data["records"]}
    return data, orders, prefs.build_pairs(data["tasks"], data["privates"], orders, prefs.ScriptedSource())


def _reply(message):
    """An assistant message as (text, calls), the form the loop builds it from."""
    return message.get("content") or "", [(c["function"]["name"], c["function"]["arguments"]) for c in message.get("tool_calls", [])]


def _legal_replies(prompt):
    """What the reference solver would say next, for either order."""
    out = []
    for order in prefs.ORDERS:
        parsed = parse_assistant_output(next_action(prompt, None, order))
        out.append((parsed.content, [(c["name"], c["arguments"]) for c in parsed.calls]))
    return out


def test_pairs_have_the_trl_conversational_format(built):
    pairs = built[2]["pairs"]
    assert pairs and built[2]["rejects"] == []
    for pair in pairs:
        row = prefs.to_trl(pair)
        assert set(row) == {"prompt", "chosen", "rejected", "tools"}
        assert [m["role"] for m in row["prompt"][:2]] == ["system", "user"] and row["prompt"][-1]["role"] in ("user", "tool")
        assert [m["role"] for m in row["chosen"]] == ["assistant"] and [m["role"] for m in row["rejected"]] == ["assistant"]
        assert row["chosen"] != row["rejected"]
        assert pair["turn"] == sum(1 for m in row["prompt"] if m["role"] == "assistant") + 1
    json.dumps([prefs.to_trl(p) for p in pairs])  # plain JSON all the way down


def test_chosen_is_a_legal_next_step_and_rejected_never_is(built):
    """The point of the fork rule: a step that is legal in the other order must not end up as rejected."""
    for pair in built[2]["pairs"]:
        legal = _legal_replies(pair["prompt"])
        assert _reply(pair["chosen"][0]) in legal, pair["pair_id"]
        assert _reply(pair["rejected"][0]) not in legal, pair["pair_id"]


def test_the_fork_is_at_the_mistake_not_at_the_first_difference_from_one_order(built):
    data, orders, out = built
    units = {t["task_id"]: t["knobs"]["units"] for t in data["tasks"]}
    seen = 0
    for pair in out["pairs"]:
        tid = pair["task_id"]
        rejected_tool = (pair["rejected"][0].get("tool_calls") or [{"function": {"name": None}}])[0]["function"]["name"]
        chosen_tool = (pair["chosen"][0].get("tool_calls") or [{"function": {"name": None}}])[0]["function"]["name"]
        done = [c["function"]["name"] for m in pair["prompt"] for c in m.get("tool_calls", [])]
        if "no_convert" in pair["labels"] and orders[tid] == "convert_first" and units[tid] != "all_V":
            # the filter was a legal step, so it is part of the prompt; the mistake is computing without converting
            assert (chosen_tool, rejected_tool) == ("convert_units", "compute_statistics") and "filter_rows" in done
            assert pair["reference_order"] == "filter_first"
            seen += 1
        if "skip_filter" in pair["labels"] and orders[tid] == "filter_first" and units[tid] != "all_V":
            assert (chosen_tool, rejected_tool) == ("filter_rows", "compute_statistics") and "convert_units" in done
            assert pair["reference_order"] == "convert_first"
            seen += 1
    assert seen >= 4


def test_only_trajectories_that_fail_the_gate_are_rejected(built):
    data, orders, out = built
    labels = {label for pair in out["pairs"] for label in pair["labels"]}
    # correct work with a fake note, correct extra statistics, and a second conversion the training domain never
    # needs are not mistakes here
    assert not labels & {"fake_notes", "all_stats", "partial_convert"}
    assert labels == set(CORRUPTIONS) - {"fake_notes", "all_stats", "partial_convert"}
    assert out["attempts"] == len(CORRUPTIONS) * len(data["tasks"]) and out["passed_gate"] >= 3 * len(data["tasks"])
    assert all(p["rejected_status"] == "ungrounded" or p["rejected_status"].startswith("failed:") for p in out["pairs"])
    single = [t for t in data["tasks"] if t["knobs"]["n_versions"] == 1]
    assert single and not any("old_version" in p["labels"] for p in out["pairs"] if p["task_id"] in {t["task_id"] for t in single})


def test_the_same_reply_at_the_same_point_is_one_pair(built):
    pairs = built[2]["pairs"]
    keys = [json.dumps([p["prompt"], p["chosen"], p["rejected"]], sort_keys=True, ensure_ascii=False) for p in pairs]
    assert len(set(keys)) == len(keys)
    both = [p for p in pairs if p["labels"][:2] == ["no_convert", "fake_notes_wrong"]]
    assert both and not any(p["labels"][0] == "fake_notes_wrong" for p in pairs)


def test_pairs_carry_no_private_field(built):
    data, _, out = built
    text = json.dumps(out["pairs"], ensure_ascii=False)
    assert "CANARY-" not in text and "error_paths" not in text and "dataset_rows" not in text
    assert {p["dedup_key"] for p in out["pairs"]} == {data["privates"][t["task_id"]]["dedup_key"] for t in data["tasks"]}


def test_selection_spreads_the_budget_over_the_tasks(built):
    pairs = built[2]["pairs"]
    tasks = list(dict.fromkeys(p["task_id"] for p in pairs))
    n = 4 * len(tasks) + 3
    chosen = prefs.select_pairs(pairs, n, seed=1)
    per_task = [sum(1 for p in chosen if p["task_id"] == tid) for tid in tasks]
    assert len(chosen) == n and per_task[:3] == [5, 5, 5] and set(per_task[3:]) == {4}
    assert [p["task_id"] for p in chosen] == sorted((p["task_id"] for p in chosen), key=tasks.index), "grouped by task"
    assert prefs.select_pairs(pairs, n, seed=1) == chosen and prefs.select_pairs(pairs, n, seed=2) != chosen
    assert prefs.select_pairs(pairs, len(pairs), seed=1) == pairs
    with pytest.raises(ValueError):
        prefs.select_pairs(pairs, len(pairs) + 1, seed=1)
    parts = prefs.composition(chosen)
    assert all(sum(part.values()) == n for part in parts.values())


def test_the_source_can_be_replaced_by_recorded_trajectories(built):
    data, orders, out = built
    traces = [trace for mode in CORRUPTIONS for order in prefs.ORDERS
              for trace in run_episodes([t for t in data["tasks"] if orders[t["task_id"]] == order],
                                        ScriptedBackend(corruption=mode, order=order))]
    recorded = prefs.build_pairs(data["tasks"], data["privates"], orders, prefs.RecordedSource(traces, label="replay"))
    strip = lambda pairs: [(p["prompt"], p["chosen"], p["rejected"], p["rejected_status"]) for p in pairs]  # noqa: E731
    assert strip(recorded["pairs"]) == strip(out["pairs"])
    assert recorded["source"] == {"source": "recorded", "label": "replay", "traces": len(traces)}
    assert {label for p in recorded["pairs"] for label in p["labels"]} == {"replay"}
    # a trajectory of some other task is ignored
    other = prefs.build_pairs(data["tasks"][:3], data["privates"], orders, prefs.RecordedSource(traces))
    assert {p["task_id"] for p in other["pairs"]} == {t["task_id"] for t in data["tasks"][:3]}
    with pytest.raises(ValueError):
        prefs.ScriptedSource(modes=("no_such_mode",))
