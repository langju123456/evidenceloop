"""Run the judge model over one frozen split through the local Ollama HTTP API.

One request per item: temperature 0, fixed seed, thinking off, output constrained to the rubric's JSON
schema. Every row keeps the full request, the raw response, the prompt version and the model digest; a
failed request is recorded as an error and stays in the denominator. The output file is never overwritten.

The dev split can be run as often as needed (the prompt is tuned there). Every other split is protected:
it needs the full SHA of the preregistration commit, the rubric, code, sample and protocol page must be
byte-identical to that commit, the human labels must already be reconciled and complete, and a start marker
written next to the sample makes a second run fail. The judge's verdicts never feed task_success.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evidenceloop.judge import items as judge_items
from evidenceloop.judge import labels as judge_labels
from evidenceloop.judge import rubric as rubrics
from evidenceloop.report import evidence_trials
from evidenceloop.report.annual import digest, read_json, read_lines

DEFAULT_MODEL = "qwen3:8b"
PROTOCOL = Path("docs/report-lab/22-judge-calibration-freeze.md")
FROZEN_CODE = tuple(Path("src/evidenceloop/judge") / name
                    for name in ("rubric.py", "items.py", "labels.py", "run.py", "agreement.py")) + (PROTOCOL,)


def protected(split: str) -> bool:
    return split != "dev"


def marker_path(dataset: dict[str, Any], split: str) -> Path:
    return dataset["folder"] / f"judge-{split}-started.json"


def payload(rubric: dict[str, Any], item: dict[str, Any], model: str) -> dict[str, Any]:
    return {"model": model, "stream": False, "think": False, "format": rubrics.output_format(rubric),
            "options": rubrics.OPTIONS, "messages": rubrics.messages(rubric, item)}


def frozen_paths(dataset: dict[str, Any], rubric: dict[str, Any], split: str, root: Path) -> list[Path]:
    try:
        folder = dataset["folder"].resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("要冻结的样本必须放在仓库里并已提交") from None
    return [rubric["path"], *FROZEN_CODE, *(folder / name for name in ("manifest.json", "key.jsonl", f"items-{split}.jsonl"))]


def check_freeze(commit: str, paths: list[Path], root: Path) -> dict[str, str]:
    """Every frozen file must be byte-identical to the preregistration commit."""
    if not re.fullmatch("[0-9a-f]{40}", commit or ""):
        raise ValueError("use the full preregistration commit SHA")
    fingerprints = {}
    for path in paths:
        try:
            raw = subprocess.check_output(["git", "-C", str(root), "show", f"{commit}:{path.as_posix()}"],
                                          stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            raise ValueError(f"not in the freeze commit: {path}") from None
        if raw != (root / path).read_bytes():
            raise ValueError(f"changed since freeze: {path}")
        fingerprints[path.as_posix()] = digest(root / path)
    return fingerprints


def run(dataset: dict[str, Any], split: str, model: str, out: Path, *, freeze: str | None = None, limit: int = 0,
        labels: Path | None = None, retest_labels: Path | None = None, root: Path = rubrics.ROOT) -> dict[str, Any]:
    rubric = rubrics.load(dataset["rubric"], root)
    if split == "retest":
        raise ValueError("重标子集只给人标，裁判跑的是它所在的测试集")
    if Path(out).exists():
        raise ValueError(f"{out} 已经存在；裁判输出不覆盖，换一个文件名")
    todo = judge_items.split_items(dataset, split)
    marker = None
    if protected(split):
        if limit:
            raise ValueError(f"{split} 只能整份跑一次，不能加 --limit")
        if not labels:
            raise ValueError(f"{split} 要先交回人工标注（--labels）：裁判跑过之后标注不能再改")
        fingerprints = check_freeze(freeze or "", frozen_paths(dataset, rubric, split, root), root)
        returned = [(labels, judge_labels.load_labels(labels, dataset, split))]
        if retest_labels:
            returned.append((retest_labels, judge_labels.load_labels(retest_labels, dataset, "retest")))
        for path, doc in returned:
            if doc["pending"]:
                raise ValueError(f"{path} 里还有没标的条目")
            if doc["rubric_sha256"] != rubric["sha256"]:
                raise ValueError(f"{path} 标注时看的评分标准和现在裁判要用的不是同一版")
        marker = {"schema": "judge-run-started/1", "rubric": rubric["id"], "split": split, "freeze_commit": freeze,
                  "frozen_sha256": fingerprints, "prompt_version": rubrics.prompt_version(rubric),
                  "labels_sha256": digest(labels), "out": Path(out).name}
        if retest_labels:
            marker["retest_labels_sha256"] = digest(retest_labels)
        if marker_path(dataset, split).exists():
            raise ValueError(f"{split} 只跑一次：{marker_path(dataset, split)} 已经存在")
    elif limit:
        todo = todo[:limit]

    installed = {m["name"]: m["digest"] for m in evidence_trials.request("tags")["models"]}
    if model not in installed:
        raise ValueError(f"本机 Ollama 里没有 {model}（已安装：{', '.join(sorted(installed)) or '无'}）；这里不下载权重")
    version = evidence_trials.request("version")["version"]
    states = {"ok": 0, "invalid": 0, "infra_error": 0}
    with open(out, "x", encoding="utf-8") as stream:
        if marker is not None:  # written only once everything needed for the run is in place
            marker.update(model=model, model_digest=installed[model], ollama_version=version,
                          started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            with open(marker_path(dataset, split), "x", encoding="utf-8") as fh:
                json.dump(marker, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        for index, item in enumerate(todo, 1):
            request = payload(rubric, item, model)
            row = {"schema_version": 1, "item_id": item["item_id"], "rubric": rubric["id"], "split": split,
                   "source_kind": "local_judge", "prompt_version": rubrics.prompt_version(rubric),
                   "rubric_sha256": rubric["sha256"], "model_digest": installed[model], "ollama_version": version,
                   "freeze_commit": freeze if protected(split) else None, "request": request}
            start = time.monotonic()
            try:
                row["response"] = evidence_trials.request("chat", request)
            except (OSError, ValueError) as exc:
                row["error"] = str(exc)
            row["latency_ms"] = round((time.monotonic() - start) * 1000)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            states[parse(row, rubric["labels"])[0]] += 1
            print(f"  {index}/{len(todo)}  {row['latency_ms']} ms", flush=True)
    return {"split": split, "n": len(todo), "model": model, "model_digest": installed[model],
            "ollama_version": version, "prompt_version": rubrics.prompt_version(rubric), "states": states,
            "freeze_commit": freeze if protected(split) else None, "out": str(out)}


def parse(row: dict[str, Any], labels: tuple[str, ...]) -> tuple[str, dict[str, Any] | None]:
    """ok with the parsed content; invalid when the output is not the fixed JSON; infra_error for transport."""
    if "error" in row:
        return "infra_error", None
    try:
        response = row["response"]
        content = json.loads(response["message"]["content"])
    except (KeyError, TypeError, ValueError):
        return "invalid", None
    if (not response.get("done") or not isinstance(content, dict) or content.get("verdict") not in labels
            or not isinstance(content.get("reason"), str)):
        return "invalid", content if isinstance(content, dict) else None
    return "ok", content


def checked_archive(dataset: dict[str, Any], split: str, path: Path, root: Path = rubrics.ROOT) -> dict[str, Any]:
    """A judge output file for this split: one row per item, one model, one prompt. A protected split must be
    complete, match its start marker, and carry exactly the requests the current rubric and sample produce."""
    rubric = rubrics.load(dataset["rubric"], root)
    shown = {item["item_id"]: item for item in judge_items.split_items(dataset, split)}
    rows = read_lines(path)
    seen: dict[str, dict[str, Any]] = {}
    configs, prompts, commits = set(), set(), set()
    for row in rows:
        if row["item_id"] not in shown or row["item_id"] in seen or row.get("split") != split:
            raise ValueError(f"unexpected or duplicate item: {row['item_id']}")
        if ("response" in row) == ("error" in row):
            raise ValueError(f"row needs exactly one of response and error: {row['item_id']}")
        seen[row["item_id"]] = row
        configs.add((row["request"]["model"], row["model_digest"], row["ollama_version"]))
        prompts.add(row["prompt_version"])
        commits.add(row.get("freeze_commit"))
        if protected(split) and row["request"] != payload(rubric, shown[row["item_id"]], row["request"]["model"]):
            raise ValueError(f"changed experiment conditions: {row['item_id']}")
    if not rows or len(configs) != 1 or len(prompts) != 1 or len(commits) != 1:
        raise ValueError("empty judge output, or more than one model, prompt or freeze commit in it")
    marker = None
    if protected(split):
        if set(seen) != set(shown):
            raise ValueError("incomplete judge output for a protected split")
        marker = read_json(marker_path(dataset, split))
        if (marker["freeze_commit"] != next(iter(commits)) or marker["prompt_version"] != next(iter(prompts))
                or (marker["model"], marker["model_digest"], marker["ollama_version"]) != next(iter(configs))):
            raise ValueError("judge output does not belong to the recorded run of this split")
    return {"rows": seen, "model": list(next(iter(configs))), "prompt_version": next(iter(prompts)),
            "freeze_commit": next(iter(commits)), "marker": marker, "missing": sorted(set(shown) - set(seen))}


def command(args) -> None:
    try:
        dataset = judge_items.load_dataset(Path(args.dataset))
        result = run(dataset, args.split, args.model, Path(args.out), freeze=args.freeze, limit=args.limit,
                     labels=Path(args.labels) if args.labels else None,
                     retest_labels=Path(args.retest_labels) if args.retest_labels else None)
    except (ValueError, OSError) as err:  # OSError: Ollama is not running, or a file is missing
        sys.exit(f"不能运行裁判：{err}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
