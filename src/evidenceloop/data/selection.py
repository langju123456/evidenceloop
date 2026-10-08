"""Where to sample new training tasks from.

B (uniform): every train-domain bucket equally, no model information.
C and D (targeted): every bucket takes the pooled failure rate of its group (unit tier x family, six
groups, D11); weight = max(rate, FLOOR), normalised, no bucket above CAP. Pooling keeps the weights from
being noise: train_mining has about 5 tasks per bucket but about 30 per group. When every group fails
at the same rate, C's weights are exactly B's.
infra_error never counts as a failure. If schema_error is more than half of all failures, only
non-format failures count, so format problems (fixed by any SFT) do not swamp the signal.
"""

from __future__ import annotations

import itertools
import random
from collections import defaultdict
from typing import Any

FLOOR = 0.05
CAP = 0.30

TRAIN_BUCKETS = [
    "|".join(parts)
    for parts in itertools.product(("F1", "F2"), ("all_mV", "mixed"), ("v1", "v2-3"), ("noerr", "transient"), ("plain", "sci"))
] + [
    "|".join(parts)  # the short tier
    for parts in itertools.product(("F1", "F2"), ("all_V",), ("v1", "v2-3"), ("noerr",), ("plain", "sci"))
]


GROUPS = [f"{units}|{family}" for units in ("all_V", "all_mV", "mixed") for family in ("F1", "F2")]


def group_of(bucket: str) -> str:
    """The D11 group of a bucket: unit tier x family, e.g. "mixed|F2"."""
    family, units = bucket.split("|")[:2]
    return f"{units}|{family}"


def knobs_for_bucket(bucket: str, rng: random.Random) -> dict[str, Any]:
    family, units, versions, error, number_format = bucket.split("|")
    return {
        "family": family,
        "units": units,
        "n_versions": 1 if versions == "v1" else rng.choice([2, 3]),
        "error": None if error == "noerr" else error,
        "number_format": number_format,
    }


def is_infra_error(ev: dict[str, Any]) -> bool:
    """The run itself broke (the backend crashed), so the result says nothing about the model. Judged by
    how the episode ended: an earlier unrecovered error can be the primary diagnosis of such an episode."""
    return ev.get("termination") == "infra_error" or (ev.get("failure") or {}).get("primary") == "infra_error"


def failure_stats(evals: list[dict[str, Any]]) -> dict[str, Any]:
    def new_row() -> dict[str, Any]:
        return {"n": 0, "fail": 0, "fail_non_schema": 0, "task_ids": []}

    per_bucket: dict[str, dict[str, Any]] = defaultdict(new_row)
    per_group: dict[str, dict[str, Any]] = defaultdict(new_row)
    total_fail = schema_fail = 0
    for ev in evals:
        if is_infra_error(ev):
            continue
        primary = (ev.get("failure") or {}).get("primary")
        rows = (per_bucket[ev["bucket"]], per_group[group_of(ev["bucket"])])
        for row in rows:
            row["n"] += 1
        if not ev["task_success"]:
            for row in rows:
                row["fail"] += 1
                row["task_ids"].append(ev["task_id"])
                if primary != "schema_error":
                    row["fail_non_schema"] += 1
            total_fail += 1
            if primary == "schema_error":
                schema_fail += 1
    schema_dominant = total_fail > 0 and schema_fail / total_fail > 0.5
    return {"buckets": dict(per_bucket), "groups": dict(per_group), "total_failures": total_fail,
            "schema_failures": schema_fail, "schema_dominant": schema_dominant}


def _cap(weights: dict[str, float], cap: float) -> dict[str, float]:
    weights = dict(weights)
    for _ in range(len(weights)):
        over = {k for k, w in weights.items() if w > cap + 1e-12}
        if not over:
            break
        excess = sum(weights[k] - cap for k in over)
        for k in over:
            weights[k] = cap
        rest = {k: w for k, w in weights.items() if k not in over and w < cap}
        total_rest = sum(rest.values())
        for k, w in rest.items():
            weights[k] = w + excess * (w / total_rest)
    return weights


def selection_weights(policy: str, evals: list[dict[str, Any]] | None = None,
                      buckets: list[str] = TRAIN_BUCKETS) -> dict[str, float]:
    if policy == "uniform":
        return {b: 1 / len(buckets) for b in buckets}
    if policy not in ("targeted", "unfiltered"):
        raise ValueError(policy)
    stats = failure_stats(evals or [])
    key = "fail_non_schema" if stats["schema_dominant"] else "fail"
    raw = {}
    for bucket in buckets:
        row = stats["groups"].get(group_of(bucket))
        rate = row[key] / row["n"] if row and row["n"] else 0.0
        raw[bucket] = max(rate, FLOOR)
    total = sum(raw.values())
    return _cap({b: w / total for b, w in raw.items()}, CAP)


def group_weights(weights: dict[str, float]) -> dict[str, float]:
    totals = {g: 0.0 for g in GROUPS}
    for bucket, weight in weights.items():
        totals[group_of(bucket)] += weight
    return totals


def allocation_shift(a: dict[str, float], b: dict[str, float]) -> float:
    """Share of the budget that moves between two allocations: half the summed absolute difference
    (total variation distance). 0 means the same allocation; D11 requires at least 0.10 for C vs B."""
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)
