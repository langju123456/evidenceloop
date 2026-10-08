"""Build one training set.

uniform (B)    : uniform bucket sampling, verified demos only
targeted (C)   : failure-weighted sampling, verified demos only
unfiltered (D) : the same tasks as C (same seed), but a fixed share of demos replaced by wrong
                 ones and no verification gate (the "controlled wrong-data" group, D10).

Every record keeps its lineage: which bucket it was drawn for and which train_mining failures
made that bucket's group heavy. exclude_keys holds the dedup keys of tasks that must not be trained on
(the frozen splits, the warm-up data); a matching task is dropped with reason "excluded".
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any

from evidenceloop.env.tools import tool_schemas
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import ScriptedBackend
from evidenceloop.tasks.generator import RejectedTask, generate_task
from evidenceloop.verify.grounding import ungrounded_arguments
from evidenceloop.verify.verifier import evaluate

from .selection import TRAIN_BUCKETS, failure_stats, group_of, knobs_for_bucket, selection_weights

D_CORRUPTION_RATIO = 0.25


def _corruptions_for(task: dict[str, Any]) -> list[str]:
    """Wrong-demo modes that really are wrong for this task. In the short tier every reading is
    already in V, so skipping the conversion changes nothing; skipping the filter (E1) does."""
    modes = ["skip_filter" if task["knobs"]["units"] == "all_V" else "no_convert", "no_save_claim"]
    if task["knobs"]["n_versions"] >= 2:
        modes.append("old_version")
    return modes


def build_training_set(policy: str, seed: int, n_tasks: int, evals: list[dict[str, Any]] | None = None,
                       corruption_ratio: float = D_CORRUPTION_RATIO,
                       exclude_keys: set[str] | None = None) -> dict[str, Any]:
    if policy not in ("uniform", "targeted", "unfiltered"):
        raise ValueError(policy)
    weights = selection_weights(policy, evals)
    stats = failure_stats(evals or [])
    sampling_policy = "uniform" if policy == "uniform" else "targeted"
    rng = random.Random(f"build:{sampling_policy}:{seed}")  # C and D share this stream, so they share tasks

    publics, privates, rejects = [], {}, []
    seen_keys: set[str] = set()
    index = 0
    while len(publics) < n_tasks:
        bucket = rng.choices(TRAIN_BUCKETS, weights=[weights[b] for b in TRAIN_BUCKETS])[0]
        overrides = knobs_for_bucket(bucket, rng)
        task_index = seed * 1_000_000 + index
        index += 1
        try:
            public, private = generate_task("synth", task_index, overrides)
        except RejectedTask as err:
            rejects.append({"task_index": task_index, "reason": "non_discriminative", "detail": err.reasons[-1]})
            continue
        if private["dedup_key"] in seen_keys:
            rejects.append({"task_id": public["task_id"], "reason": "duplicate"})
            continue
        if exclude_keys and private["dedup_key"] in exclude_keys:
            rejects.append({"task_id": public["task_id"], "reason": "excluded"})
            continue
        seen_keys.add(private["dedup_key"])
        public["selection"] = {"policy": sampling_policy, "bucket": bucket, "weight": round(weights[bucket], 6)}
        publics.append(public)
        privates[public["task_id"]] = private

    # Plan the demos: order for every task, corruption for D's share.
    plan_rng = random.Random(f"plan:{seed}")
    orders = {p["task_id"]: plan_rng.choice(["filter_first", "convert_first"]) for p in publics}
    corruption: dict[str, str | None] = {p["task_id"]: None for p in publics}
    if policy == "unfiltered":
        chosen = random.Random(f"corrupt:{seed}").sample(publics, round(len(publics) * corruption_ratio))
        for task in chosen:
            corruption[task["task_id"]] = random.Random(f"mode:{task['task_id']}").choice(_corruptions_for(task))

    groups: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for task in publics:
        groups[(orders[task["task_id"]], corruption[task["task_id"]])].append(task)
    traces = {}
    for (order, mode), tasks in groups.items():
        for trace in run_episodes(tasks, ScriptedBackend(corruption=mode, order=order)):
            traces[trace["task_id"]] = trace

    tools = tool_schemas()
    records = []
    for task in publics:
        tid = task["task_id"]
        trace = traces[tid]
        result = evaluate(trace, privates[tid])
        ungrounded = ungrounded_arguments(trace["messages"])
        gated = policy != "unfiltered"
        if gated and not result["task_success"]:
            rejects.append({"task_id": tid, "reason": f"verifier:{result['failure']['primary']}"})
            continue
        if gated and ungrounded:
            rejects.append({"task_id": tid, "reason": "ungrounded"})
            continue
        bucket = task["selection"]["bucket"]
        source_failures = stats["groups"].get(group_of(bucket), {}).get("task_ids", [])[:5] if sampling_policy == "targeted" else []
        records.append({
            "task_id": tid,
            "dedup_key": privates[tid]["dedup_key"],
            "policy": policy,
            "bucket": bucket,
            "recipe_id": task["recipe_id"],
            "selection_weight": task["selection"]["weight"],
            "source_failure_ids": source_failures,
            "demo_order": orders[tid],
            "corruption": corruption[tid],
            "verified": bool(result["task_success"]),
            "verification_status": "passed" if result["task_success"] else f"failed:{result['failure']['primary']}",
            "gated": gated,
            "messages": trace["messages"],
            "tools": tools,
        })
    return {
        "policy": policy,
        "seed": seed,
        "weights": weights,
        "records": records,
        "rejects": rejects,
        "reject_counts": dict(Counter(r["reason"] for r in rejects)),
        "corrupted": sum(1 for r in records if r["corruption"]),
    }
