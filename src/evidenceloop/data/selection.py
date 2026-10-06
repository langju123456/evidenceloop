"""Where to sample new training tasks from.

B (uniform): every train-domain bucket equally, no model information.
C and D (targeted): weight = max(failure rate, FLOOR), normalised, no bucket above CAP.
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
]


def knobs_for_bucket(bucket: str, rng: random.Random) -> dict[str, Any]:
    family, units, versions, error, number_format = bucket.split("|")
    return {
        "family": family,
        "units": units,
        "n_versions": 1 if versions == "v1" else rng.choice([2, 3]),
        "error": None if error == "noerr" else error,
        "number_format": number_format,
    }


def failure_stats(evals: list[dict[str, Any]]) -> dict[str, Any]:
    per_bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "fail": 0, "fail_non_schema": 0, "task_ids": []})
    total_fail = schema_fail = 0
    for ev in evals:
        primary = (ev.get("failure") or {}).get("primary")
        if primary == "infra_error":
            continue
        row = per_bucket[ev["bucket"]]
        row["n"] += 1
        if not ev["task_success"]:
            row["fail"] += 1
            row["task_ids"].append(ev["task_id"])
            total_fail += 1
            if primary == "schema_error":
                schema_fail += 1
            else:
                row["fail_non_schema"] += 1
    schema_dominant = total_fail > 0 and schema_fail / total_fail > 0.5
    return {"buckets": dict(per_bucket), "total_failures": total_fail, "schema_failures": schema_fail,
            "schema_dominant": schema_dominant}


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
        row = stats["buckets"].get(bucket)
        rate = row[key] / row["n"] if row and row["n"] else 0.0
        raw[bucket] = max(rate, FLOOR)
    total = sum(raw.values())
    return _cap({b: w / total for b, w in raw.items()}, CAP)
