"""Preference pairs for DPO (D16).

A pair is one decision: the conversation so far (prompt), the reply a verified reference trajectory gives there
(chosen) and the reply a failed trajectory gives there (rejected). The exported row is
{"prompt": [...], "chosen": [assistant message], "rejected": [assistant message], "tools": [...]}, the
conversational format TRL's DPOTrainer reads.

Where the failed trajectories come from is a replaceable source: anything with attempts(tasks, orders) that
yields (label, trace) for the given tasks. ScriptedSource (plan A) runs the scripted corruptions of
harness/scripted.py. RecordedSource takes trajectories that already exist, such as a model's own runs.

Gate: the same one the SFT demos pass (data/build.py). A reference trajectory must pass the verifier and
have no ungrounded argument; a trajectory only counts as failed when it does not pass that gate.

Fork: the failed trajectory is compared with the reference trajectory of each legal order (filter first,
convert first) and the one sharing the longest prefix is used. That prefix is the prompt, and the next
assistant message of each side is chosen and rejected. Comparing with one order only is wrong: skipping
the conversion on a convert-first task first differs at filter_rows, which is the legal next step of the
other order; the mistake is the compute_statistics after it.

This holds for scripted corruptions, which follow the reference until the mistake. A model's trajectory
can leave the reference earlier with a harmless step, so the fork rule has to be re-checked before
RecordedSource is used for training data (D16).
"""

from __future__ import annotations

import copy
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any, Protocol

from evidenceloop.common import canonical_json
from evidenceloop.env.tools import tool_schemas
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import CORRUPTIONS, ScriptedBackend
from evidenceloop.verify.grounding import ungrounded_arguments
from evidenceloop.verify.verifier import evaluate

ORDERS = ("filter_first", "convert_first")


class Source(Protocol):
    def describe(self) -> dict[str, Any]: ...

    def attempts(self, tasks: list[dict[str, Any]], orders: dict[str, str]) -> Iterable[tuple[str, dict[str, Any]]]:
        """(label, trace) for trajectories on these tasks; the ones that pass the gate are ignored."""
        ...


class ScriptedSource:
    """Plan A: every scripted corruption on every task, in the order the task's demo used."""

    def __init__(self, modes: tuple[str, ...] = CORRUPTIONS):
        unknown = [m for m in modes if m not in CORRUPTIONS]
        if unknown:
            raise ValueError(unknown)
        self.modes = tuple(modes)

    def describe(self) -> dict[str, Any]:
        return {"source": "scripted", "modes": list(self.modes)}

    def attempts(self, tasks: list[dict[str, Any]], orders: dict[str, str]) -> Iterable[tuple[str, dict[str, Any]]]:
        for mode in self.modes:
            for order in ORDERS:
                group = [t for t in tasks if orders[t["task_id"]] == order]
                for trace in run_episodes(group, ScriptedBackend(corruption=mode, order=order)):
                    yield mode, trace


class RecordedSource:
    """Trajectories that already exist (el run's traces.jsonl), e.g. a model's own runs on the same tasks."""

    def __init__(self, traces: list[dict[str, Any]], label: str = "recorded"):
        self.traces, self.label = traces, label

    def describe(self) -> dict[str, Any]:
        return {"source": "recorded", "label": self.label, "traces": len(self.traces)}

    def attempts(self, tasks: list[dict[str, Any]], orders: dict[str, str]) -> Iterable[tuple[str, dict[str, Any]]]:
        wanted = {t["task_id"] for t in tasks}
        for trace in self.traces:
            if trace["task_id"] in wanted:
                yield self.label, trace


def gate(trace: dict[str, Any], private: dict[str, Any]) -> str:
    """Whether a trajectory passes the gate the SFT demos pass: "passed", or the reason it does not."""
    result = evaluate(trace, private)
    if not result["task_success"]:
        return f"failed:{result['failure']['primary']}"
    if ungrounded_arguments(trace["messages"]):
        return "ungrounded"
    return "passed"


def common_prefix(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def fork(references: list[dict[str, Any]], wrong: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
    """The reference sharing the longest prefix with the wrong trajectory (the first one on a tie) and the
    index of the first message that differs; None when that message is not an assistant message on both sides."""
    best = max(references, key=lambda ref: common_prefix(ref["messages"], wrong["messages"]))
    index = common_prefix(best["messages"], wrong["messages"])
    for messages in (best["messages"], wrong["messages"]):
        if index >= len(messages) or messages[index]["role"] != "assistant":
            return None
    return best, index


def build_pairs(tasks: list[dict[str, Any]], privates: dict[str, dict[str, Any]], orders: dict[str, str],
                source: Source) -> dict[str, Any]:
    """Every distinct pair the source gives on these tasks, grouped by task in task order."""
    references: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejects = []
    for order in ORDERS:
        for trace in run_episodes(tasks, ScriptedBackend(order=order)):
            tid = trace["task_id"]
            status = gate(trace, privates[tid])
            if status != "passed":
                rejects.append({"task_id": tid, "reason": f"reference:{status}", "order": order})
            elif all(trace["messages"] != ref["messages"] for ref in references[tid]):  # the short tier has one order
                trace["order"] = order
                references[tid].append(trace)
    for tid, refs in references.items():  # on a tie the fork goes to the order the task's demo used
        refs.sort(key=lambda ref: ref["order"] != orders[tid])

    tools = tool_schemas()
    by_task: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    buckets = {t["task_id"]: t["bucket"] for t in tasks}
    attempts = passed = 0
    for label, trace in source.attempts(tasks, orders):
        tid = trace["task_id"]
        attempts += 1
        if not references[tid]:
            rejects.append({"task_id": tid, "reason": "no_verified_reference", "label": label})
            continue
        status = gate(trace, privates[tid])
        if status == "passed":  # not a mistake on this task: nothing to reject
            passed += 1
            continue
        found = fork(references[tid], trace)
        if found is None:
            rejects.append({"task_id": tid, "reason": "no_fork", "label": label})
            continue
        reference, index = found
        prompt, chosen, rejected = trace["messages"][:index], reference["messages"][index], trace["messages"][index]
        key = canonical_json([prompt, chosen, rejected])
        if key in by_task[tid]:  # two mistakes that are the same reply at the same point
            by_task[tid][key]["labels"].append(label)
            continue
        by_task[tid][key] = {
            "pair_id": f"{tid}#{index}:{label}",
            "task_id": tid,
            "dedup_key": privates[tid]["dedup_key"],
            "bucket": buckets[tid],
            "labels": [label],
            "rejected_status": status,
            "reference_order": reference["order"],
            "fork_index": index,
            "turn": sum(1 for m in prompt if m["role"] == "assistant") + 1,
            "prompt": copy.deepcopy(prompt),
            "chosen": [copy.deepcopy(chosen)],
            "rejected": [copy.deepcopy(rejected)],
            "tools": tools,
        }
    pairs = [pair for task in tasks for pair in by_task[task["task_id"]].values()]
    return {
        "source": source.describe(),
        "pairs": pairs,
        "rejects": rejects,
        "attempts": attempts,
        "passed_gate": passed,
        "reject_counts": dict(Counter(r["reason"] for r in rejects)),
    }


def select_pairs(pairs: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """n pairs, spread over the tasks: each task's pairs in a fixed random order, then one pair per task per round
    (tasks in the order given) until n are taken. Returned grouped by task, in the order they came in."""
    if len(pairs) < n:
        raise ValueError(f"只有 {len(pairs)} 对候选，不够 {n} 对")
    by_task: dict[str, list[int]] = defaultdict(list)
    for i, pair in enumerate(pairs):
        by_task[pair["task_id"]].append(i)
    for tid, indices in by_task.items():
        random.Random(f"prefs:{seed}:{tid}").shuffle(indices)
    taken: list[int] = []
    for round_ in range(max(len(v) for v in by_task.values())):
        for indices in by_task.values():
            if round_ < len(indices) and len(taken) < n:
                taken.append(indices[round_])
    return [pairs[i] for i in sorted(taken)]


def to_trl(pair: dict[str, Any]) -> dict[str, Any]:
    return {"prompt": pair["prompt"], "chosen": pair["chosen"], "rejected": pair["rejected"], "tools": pair["tools"]}


def composition(pairs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """What the pairs are made of: by the first corruption that gave each pair, by why the rejected trajectory
    failed, and by the assistant turn the pair sits at."""
    return {
        "by_label": dict(sorted(Counter(p["labels"][0] for p in pairs).items())),
        "by_rejected_status": dict(sorted(Counter(p["rejected_status"] for p in pairs).items())),
        "by_turn": {str(k): v for k, v in sorted(Counter(p["turn"] for p in pairs).items())},
    }
