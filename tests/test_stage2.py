import json

import pytest

from evidenceloop.data.build import build_training_set
from evidenceloop.data.export import EOS, build_manifest, check_prefix_consistency, expand, match_budgets, to_format
from evidenceloop.data.selection import CAP, FLOOR, TRAIN_BUCKETS, selection_weights
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import ScriptedBackend
from evidenceloop.tasks.generator import generate_split
from evidenceloop.verify.grounding import ungrounded_arguments
from evidenceloop.verify.verifier import evaluate


@pytest.fixture(scope="module")
def mining_evals():
    """A stand-in base model that fails every mixed-unit task."""
    pubs, privs, _ = generate_split("train_mining", 80)
    privs = {p["task_id"]: p for p in privs}
    mixed = [p for p in pubs if p["knobs"]["units"] == "mixed"]
    rest = [p for p in pubs if p["knobs"]["units"] != "mixed"]
    traces = run_episodes(mixed, ScriptedBackend(corruption="no_convert")) + run_episodes(rest, ScriptedBackend())
    return [evaluate(t, privs[t["task_id"]]) for t in traces]


@pytest.fixture(scope="module")
def built(mining_evals):
    return {pol: build_training_set(pol, seed=3, n_tasks=40, evals=mining_evals)
            for pol in ("uniform", "targeted", "unfiltered")}


def test_weights(mining_evals):
    uniform = selection_weights("uniform")
    assert len(set(uniform.values())) == 1 and abs(sum(uniform.values()) - 1) < 1e-9
    targeted = selection_weights("targeted", mining_evals)
    assert abs(sum(targeted.values()) - 1) < 1e-9
    assert max(targeted.values()) <= CAP + 1e-9
    assert min(targeted.values()) > 0
    mixed = sum(w for b, w in targeted.items() if "|mixed|" in b)
    assert mixed > 0.5, "failures were all in mixed-unit buckets"


def test_schema_dominated_failures_are_discounted():
    evals = [{"task_id": f"t{i}", "bucket": TRAIN_BUCKETS[i % 2], "task_success": False,
              "failure": {"primary": "schema_error" if i % 2 == 0 else "unit_error"}} for i in range(4)]
    evals += [{"task_id": "t9", "bucket": TRAIN_BUCKETS[0], "task_success": False, "failure": {"primary": "schema_error"}}]
    weights = selection_weights("targeted", evals)
    assert weights[TRAIN_BUCKETS[1]] > weights[TRAIN_BUCKETS[0]]


def test_c_and_d_share_tasks_and_differ_only_in_the_gate(built):
    c, d = built["targeted"], built["unfiltered"]
    assert [r["task_id"] for r in c["records"]] == [r["task_id"] for r in d["records"]]
    assert d["corrupted"] == round(len(d["records"]) * 0.25)
    assert c["corrupted"] == 0 and all(r["verified"] for r in c["records"])
    assert all(r["corruption"] is None for r in built["uniform"]["records"])


def test_gated_demos_are_verified_and_grounded(built):
    for policy in ("uniform", "targeted"):
        for record in built[policy]["records"]:
            assert record["verified"]
            assert ungrounded_arguments(record["messages"]) == []


def test_lineage_points_back_to_failures(built, mining_evals):
    failed = {e["task_id"] for e in mining_evals if not e["task_success"]}
    linked = [r for r in built["targeted"]["records"] if r["source_failure_ids"]]
    assert linked and all(set(r["source_failure_ids"]) <= failed for r in linked)
    assert all(not r["source_failure_ids"] for r in built["uniform"]["records"])


def test_expansion_supervises_only_assistant_turns(built):
    record = built["targeted"]["records"][0]
    samples = expand(record)
    assert len(samples) == sum(1 for m in record["messages"] if m["role"] == "assistant")
    for sample in samples:
        assert [m["role"] for m in sample["completion"]] == ["assistant"]
        assert sample["prompt"][-1]["role"] in ("user", "tool")
    assert set(to_format(samples[0], "trl")) == {"prompt", "completion", "tools"}
    assert set(to_format(samples[0], "mlx")) == {"messages", "tools"}


def _qwen_like(messages, tools, add_generation_prompt, buggy=False):
    """A small stand-in for the Qwen3 template, thinking disabled. The real one is checked by scripts/check_template.py."""
    out = "<|im_start|>system\n" + messages[0]["content"] + "\n# Tools\n" + json.dumps(tools, ensure_ascii=False) + EOS + "\n"
    last = len(messages) - 1
    for i, m in enumerate(messages[1:], start=1):
        if m["role"] == "user":
            out += "<|im_start|>user\n" + m["content"] + EOS + "\n"
        elif m["role"] == "tool":
            out += "<|im_start|>user\n<tool_response>\n" + m["content"] + "\n</tool_response>" + EOS + "\n"
        else:
            think = "<think>\n\n</think>\n\n" if (i == last and not buggy) else ""
            calls = "".join("<tool_call>\n" + json.dumps({"name": c["function"]["name"], "arguments": c["function"]["arguments"]},
                                                         ensure_ascii=False) + "\n</tool_call>" for c in m.get("tool_calls", []))
            out += "<|im_start|>assistant\n" + think + (m.get("content") or "") + calls + EOS + "\n"
    if add_generation_prompt:
        out += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    return out


def test_prefix_consistency_check_passes_and_catches_a_bad_template(built):
    samples = [s for r in built["targeted"]["records"][:5] for s in expand(r)]
    assert all(check_prefix_consistency(_qwen_like, s) == [] for s in samples)
    buggy = lambda m, t, g: _qwen_like(m, t, g, buggy=True)  # noqa: E731
    assert any(check_prefix_consistency(buggy, s) for s in samples)


def test_budget_matching_and_manifest_hash(built):
    sets = {p: [s for r in b["records"] for s in expand(r)] for p, b in built.items()}
    matched = match_budgets(sets, seed=3)
    assert len({len(v) for v in matched["samples"].values()}) == 1
    first = build_manifest("ds_C", built["targeted"], matched["samples"]["targeted"], "trl")
    again = build_manifest("ds_C", built["targeted"], matched["samples"]["targeted"], "trl")
    assert first["content_sha256"] == again["content_sha256"]
    assert first["n_samples"] == matched["n_per_group"]


def test_canary_never_reaches_exports(built):
    exported = json.dumps([to_format(s, "trl") for r in built["targeted"]["records"] for s in expand(r)], ensure_ascii=False)
    assert "CANARY-" not in exported
