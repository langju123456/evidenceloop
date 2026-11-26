"""Agreement between the human labels, the judge model and the existing program rule on one split.

- human vs judge, and human vs every program rater in key.jsonl (the verifier's keyword rule for replies;
  the scorer and the development labels for annual answers): raw agreement, Cohen's kappa, the confusion
  matrix (rows = human), and a 95% percentile interval for kappa from a bootstrap that resamples clusters
  (task_id or case_id) with a fixed seed. With fewer than MIN_CLUSTERS clusters no interval is given.
- judge vs each program rater: who matches the human label on the same items; exact two-sided McNemar test
  on the discordant items and a cluster-bootstrap interval for the accuracy difference.
- retest: the labeller against their own first round on the relabelled subset.

A judge row that is invalid or failed in transport keeps its place as the category `invalid`, so it counts
as a disagreement. Items the human left unlabelled are counted as pending and left out. Before the judge has
run, a protected split only reports the retest: comparing its labels with the program rule early would leak
the test side into prompt tuning. Pure Python, no numpy.
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from evidenceloop.judge import items as judge_items
from evidenceloop.judge import labels as judge_labels
from evidenceloop.judge import rubric as rubrics
from evidenceloop.judge import run as judge_run
from evidenceloop.report.annual import digest

BOOTSTRAP = 10_000
MIN_CLUSTERS = 10
INVALID = "invalid"
Pair = tuple[str, str]


def cohen_kappa(pairs: list[Pair]) -> tuple[float, float | None]:
    """Raw agreement and kappa; kappa is None when both raters used one and the same single label."""
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[c] * right[c] for c in left) / n ** 2
    return observed, None if expected == 1 else (observed - expected) / (1 - expected)


def confusion(pairs: list[Pair], rows: tuple[str, ...], cols: tuple[str, ...]) -> dict[str, dict[str, int]]:
    counts = Counter(pairs)
    return {r: {c: counts[r, c] for c in cols} for r in rows}


def cluster_interval(groups: dict[str, list[Any]], statistic: Callable[[list[Any]], float | None],
                     resamples: int = BOOTSTRAP, seed: int = 0) -> dict[str, Any] | None:
    """95% percentile interval of a statistic when whole clusters are resampled with replacement."""
    names = sorted(groups)
    if len(names) < MIN_CLUSTERS:
        return None
    rng = random.Random(seed)
    values, undefined = [], 0
    for _ in range(resamples):
        value = statistic([row for _ in names for row in groups[names[rng.randrange(len(names))]]])
        if value is None:
            undefined += 1
        else:
            values.append(value)
    if not values:
        return None
    values.sort()
    return {"low": values[int(0.025 * len(values))], "high": values[int(0.975 * len(values)) - 1],
            "clusters": len(names), "resamples": resamples, "undefined": undefined}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def compare(left: dict[str, str], right: dict[str, str], clusters: dict[str, str], rows: tuple[str, ...],
            cols: tuple[str, ...], resamples: int = BOOTSTRAP) -> dict[str, Any] | None:
    """Two raters on the items both labelled; `left` is the reference (the human)."""
    ids = sorted(set(left) & set(right))
    if not ids:
        return None
    groups: dict[str, list[Pair]] = defaultdict(list)
    for item_id in ids:
        groups[clusters[item_id]].append((left[item_id], right[item_id]))
    pairs = [pair for name in sorted(groups) for pair in groups[name]]
    observed, kappa = cohen_kappa(pairs)
    return {"n": len(pairs), "clusters": len(groups), "agreement": observed, "kappa": kappa,
            "kappa_interval": cluster_interval(groups, lambda sample: cohen_kappa(sample)[1], resamples),
            "matrix": confusion(pairs, rows, cols)}


def paired_accuracy(human: dict[str, str], judge: dict[str, str], other: dict[str, str], clusters: dict[str, str],
                    resamples: int = BOOTSTRAP) -> dict[str, Any] | None:
    """Judge vs another rater on who matches the human label, item by item."""
    ids = sorted(set(human) & set(judge) & set(other))
    if not ids:
        return None
    groups: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for item_id in ids:
        groups[clusters[item_id]].append((judge[item_id] == human[item_id], other[item_id] == human[item_id]))
    rows = [row for name in sorted(groups) for row in groups[name]]
    counts = Counter(rows)
    b, c = counts[True, False], counts[False, True]
    n = len(rows)
    return {"n": n, "both_right": counts[True, True], "judge_only_right": b, "other_only_right": c,
            "both_wrong": counts[False, False], "judge_accuracy": (counts[True, True] + b) / n,
            "other_accuracy": (counts[True, True] + c) / n, "mcnemar_exact_p": mcnemar_exact(b, c),
            "difference_interval": cluster_interval(
                groups, lambda sample: sum(j - o for j, o in sample) / len(sample), resamples)}


def summarize(dataset: dict[str, Any], split: str, labels_path: Path, judge_path: Path | None = None,
              retest_path: Path | None = None, resamples: int = BOOTSTRAP, root: Path = rubrics.ROOT) -> dict[str, Any]:
    spec = rubrics.RUBRICS[dataset["rubric"]]
    allowed = tuple(spec["labels"])
    key = dataset["key"]
    shown = [item["item_id"] for item in judge_items.split_items(dataset, split)]
    clusters = {item_id: key[item_id]["cluster"] for item_id in shown}
    human_doc = judge_labels.load_labels(labels_path, dataset, split)
    reasons = {row["item_id"]: row["reason"] for row in human_doc["labels"]}
    human = {row["item_id"]: row["label"] for row in human_doc["labels"]}
    result: dict[str, Any] = {
        "schema_version": 1, "rubric": dataset["rubric"], "split": split, "n_items": len(shown),
        "labelled": len(human), "pending": len(shown) - len(human), "reviewer": human_doc["reviewer"],
        "rubric_sha256_on_form": human_doc.get("rubric_sha256"), "human_labels": dict(Counter(human.values())),
        "inputs_sha256": {"labels": digest(labels_path), "key": dataset["manifest"]["files"]["key.jsonl"]},
        "judge": None, "human_vs_judge": None, "human_vs_program": {}, "judge_vs_program": {}, "retest": None,
        "disagreements": [],
    }

    archive = marker = None
    if judge_path is not None:
        archive = judge_run.checked_archive(dataset, split, judge_path, root)
        marker = archive["marker"]
        if marker and marker["labels_sha256"] != digest(labels_path):
            raise ValueError("人工标注和裁判运行前登记的那一份不一样")
        parsed = {item_id: judge_run.parse(row, allowed) for item_id, row in archive["rows"].items()}
        judge = {item_id: content["verdict"] if state == "ok" else INVALID for item_id, (state, content) in parsed.items()}
        cols = allowed + ((INVALID,) if INVALID in judge.values() else ())
        result["inputs_sha256"]["judge"] = digest(judge_path)
        judged_with = {row["rubric_sha256"] for row in archive["rows"].values()}
        result["judge"] = {"model": archive["model"], "prompt_version": archive["prompt_version"],
                           "freeze_commit": archive["freeze_commit"], "n": len(judge), "missing": len(archive["missing"]),
                           "same_rubric_text_as_labels": judged_with == {human_doc.get("rubric_sha256")},
                           "states": dict(Counter(state for state, _ in parsed.values())),
                           "labels": dict(Counter(judge.values()))}
        result["human_vs_judge"] = compare(human, judge, clusters, allowed, cols, resamples)

    if archive is not None or not judge_run.protected(split):
        for name in sorted({name for item_id in shown for name in key[item_id]["raters"]}):
            program = {item_id: key[item_id]["raters"][name] for item_id in shown if name in key[item_id]["raters"]}
            result["human_vs_program"][name] = compare(human, program, clusters, allowed, allowed, resamples)
            if archive is not None:
                result["judge_vs_program"][name] = paired_accuracy(human, judge, program, clusters, resamples)
    if archive is not None:
        for item_id in shown:
            if item_id in human and item_id in judge and human[item_id] != judge[item_id]:
                content = parsed[item_id][1] or {}
                result["disagreements"].append({"item_id": item_id, "human": human[item_id], "judge": judge[item_id],
                                                "program": key[item_id]["raters"], "human_note": reasons[item_id],
                                                "judge_reason": content.get("reason")})

    if retest_path is not None:
        if split != "test":
            raise ValueError("重标子集取自测试集，--retest-labels 只和 --split test 一起用")
        if marker and marker.get("retest_labels_sha256") not in (None, digest(retest_path)):
            raise ValueError("重标标注和裁判运行前登记的那一份不一样")
        again_doc = judge_labels.load_labels(retest_path, dataset, "retest")
        again = {row["item_id"]: row["label"] for row in again_doc["labels"]}
        result["inputs_sha256"]["retest_labels"] = digest(retest_path)
        result["retest"] = compare(human, again, clusters, allowed, allowed, resamples)
    return result


def command(args) -> None:
    try:
        dataset = judge_items.load_dataset(Path(args.dataset))
        result = summarize(dataset, args.split, Path(args.labels), Path(args.judge) if args.judge else None,
                           Path(args.retest_labels) if args.retest_labels else None, args.resamples)
    except (ValueError, FileNotFoundError) as err:
        sys.exit(f"不能统计：{err}")
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
