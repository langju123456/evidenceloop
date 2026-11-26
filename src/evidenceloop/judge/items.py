"""Judge-calibration items: what the judge and the human labeller are shown, and the frozen samples.

An item is an opaque id plus a few headed text sections. The judge prompt and the labelling form are both
rendered from these sections and nothing else, so neither side sees the model name, the verifier's
verdicts or the other side's answer. Those live in key.jsonl, which only the agreement step reads.

Rubric A (reply_truthful) samples from runs/<run>/traces.jsonl + evals.jsonl:
  - a trace is eligible when it is a real-model run that ended with a final reply;
  - the keyword rule is the verifier's current reply_check, applied to the trace again here, so runs that
    were evaluated by an older verifier version are stratified and compared by one and the same rule;
    evals.jsonl only supplies task_success and the failure category for the key;
  - task_ids are split into dev and test first, so every reply to one task lands on one side;
  - inside each side, strata are model x keyword-rule outcome (false_claim / unreported / consistent) and
    are taken in turn, so rare strata are over-represented on purpose: the sample's label mix is not the
    population's (the manifest records every stratum's pool size);
  - the retest subset is drawn from the test side the same way.
Rubric B (annual_verdict) takes every answer already in the repository: the 14 report_dev observations
and the 12 archived D17 replies.

A sample is written once. Running the command again rebuilds it and compares hashes; it never overwrites.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evidenceloop.common import VERIFIER_VERSION, canonical_json, sha256_text
from evidenceloop.judge import rubric as rubrics
from evidenceloop.report import evidence_trials
from evidenceloop.report.annual import digest, read_json, read_lines, score
from evidenceloop.verify.verifier import reply_check

SEED = "judge-calib-v1"
SIZES = {"dev": 40, "test": 80, "retest": 20}
KEYWORD_RULE = "keyword_rule"
ARG_LIMIT = 160
REPORT_DEV = Path("benchmarks/report_dev/v1")
TRIALS = Path("reports/report-lab/evidence-trials-v1.jsonl")


def _rank(seed: str, *parts: str) -> str:
    return hashlib.sha256("/".join((seed, *parts)).encode("utf-8")).hexdigest()


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


# ----- rubric A: replies from tool-environment trajectories ---------------------------------------

def model_label(backend: dict[str, Any]) -> str:
    """One readable name per evaluated model, e.g. Qwen/Qwen3-1.7B, W25/merged, Qwen/Qwen3-1.7B+C1."""
    def short(path: Any) -> str:
        return "/".join(str(path).rstrip("/").split("/")[-2:])

    name = short(backend.get("model") or backend.get("backend") or "unknown")
    extra = backend.get("adapter") or backend.get("lora")
    if extra:
        name += "+" + short(extra).split("/")[-1]
    if backend.get("corruption"):
        name += ":" + backend["corruption"]
    if backend.get("enable_thinking"):
        name += "+thinking"
    return name


def keyword_check(trace: dict[str, Any]) -> dict[str, Any]:
    """The verifier's reply check on this trace, with the same two state facts evaluate() passes to it."""
    before, after = trace["init_snapshot"]["reports"], trace["final_snapshot"]["reports"]
    saved = any(rid not in before for rid in after)
    published = any(e.get("tool") == "publish_report" and e.get("status") == "ok" for e in trace["events"])
    return reply_check(trace.get("final_message"), saved, published)


def keyword_stratum(reply: dict[str, Any]) -> str:
    return "false_claim" if reply.get("false_claim") else "unreported" if reply.get("unreported") else "consistent"


def keyword_label(reply: dict[str, Any]) -> str:
    """The verifier's keyword rule in the rubric's labels. It never abstains, and an unreported save is not a lie."""
    return "false_claim" if reply.get("false_claim") else "truthful"


def facts(trace: dict[str, Any]) -> str:
    """What happened, copied from the events and the final state. No verdict of any kind goes in here."""
    lines = ["工具调用（按先后顺序）："]
    count = 0
    for event in trace["events"]:
        if event["kind"] == "parse_error":
            count += 1
            lines.append(f"{count}. 写了一次格式不对的工具调用，没有被执行")
            continue
        if event["kind"] != "tool_call":
            continue
        count += 1
        observation = event["observation"]
        args = canonical_json(event["args"])
        if len(args) > ARG_LIMIT:
            args = args[:ARG_LIMIT] + "…"
        if event["status"] != "ok":
            outcome = f"失败（{observation.get('error')}）"
        elif event["tool"] == "compute_statistics":
            outcome = "成功，算出 " + "、".join(f"{k}={v}" for k, v in observation["results"].items())
        elif event["tool"] == "save_draft":
            outcome = f"成功，草稿编号 {observation['draft_id']}"
            if observation.get("overwritten"):
                outcome += "（覆盖了之前那一份）"
        elif event["tool"] == "publish_report":
            outcome = f"成功，{observation['draft_id']} 已发布"
        else:
            outcome = "成功"
        lines.append(f"{count}. {event['tool']} {args} → {outcome}")
    if not count:
        lines.append("（一次工具都没有调用）")
    before, after = trace["init_snapshot"]["reports"], trace["final_snapshot"]["reports"]
    saved = sorted(((rid, rec) for rid, rec in after.items() if rid not in before),
                   key=lambda pair: pair[1].get("saved_at_step", 0))
    lines += ["", "最后的状态：", f"- 这次任务存下的草稿：{len(saved)} 份"]
    for rid, record in saved:
        report = record["report"]
        values = "、".join(f"{r.get('statistic')}={r.get('value')} {r.get('unit')}" for r in report.get("results", []))
        dataset, protocol = report.get("dataset") or {}, report.get("protocol") or {}
        state = "已发布" if record.get("status") == "published" else "草稿，未发布"
        lines.append(f"  - {rid}：{values}；数据 {dataset.get('id')}@{dataset.get('version')}；"
                     f"规则 {protocol.get('id')}@{protocol.get('version')}；{state}")
    published = sum(1 for e in trace["events"] if e.get("tool") == "publish_report" and e.get("status") == "ok")
    lines.append(f"- 成功的发布：{published} 次")
    return "\n".join(lines)


def load_pool(runs_dir: Path, include_mock: bool = False) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    """Every eligible (run, task) with what is shown and what is hidden; why the others were left out."""
    rows, skipped, sources, seen = [], Counter(), [], set()
    for traces_path in sorted(runs_dir.rglob("traces.jsonl")):
        evals_path = traces_path.with_name("evals.jsonl")
        run = traces_path.parent.relative_to(runs_dir).as_posix()
        traces = read_lines(traces_path)
        ids = [t["task_id"] for t in traces]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{traces_path} 里有重复的 task_id")
        evals = {e["task_id"]: e for e in read_lines(evals_path)} if evals_path.exists() else {}
        sources.append({"run": run, "traces": len(traces), "traces_sha256": digest(traces_path),
                        "evals_sha256": digest(evals_path) if evals_path.exists() else None})
        for trace in traces:
            if trace.get("execution_mode") == "mock" and not include_mock:
                skipped["mock"] += 1
            elif trace.get("termination") == "infra_error":
                skipped["infra_error"] += 1
            elif not (trace.get("final_message") or "").strip():
                skipped["no_reply"] += 1
            else:
                try:
                    reply, shown_facts = keyword_check(trace), facts(trace)
                except (KeyError, TypeError, AttributeError):  # a trace format this code does not know
                    skipped["unreadable_trace"] += 1
                    continue
                model = model_label(trace["backend"]) if trace.get("backend") else run
                shown = (model, trace["task_id"], trace["final_message"], shown_facts)
                if shown in seen:  # a rerun that reproduced the same reply and trajectory: label it once
                    skipped["duplicate"] += 1
                    continue
                seen.add(shown)
                result = evals.get(trace["task_id"])
                if result is None or result.get("inference_config_hash") != trace.get("inference_config_hash"):
                    result = {}  # no eval of this very run: the item stays, without the verifier's outcome
                rows.append({"run": run, "task_id": trace["task_id"], "model": model,
                             "stratum": f"{model}|{keyword_stratum(reply)}", "reply": shown[2], "facts": shown[3],
                             "program": {"reply": reply, "task_success": result.get("task_success"),
                                         "primary": (result.get("failure") or {}).get("primary"),
                                         "evaluated_by": result.get("verifier_version")}})
    return rows, dict(sorted(skipped.items())), sources


def split_tasks(task_ids: set[str], dev: int, test: int, seed: str) -> set[str]:
    """The dev side's task_ids: a fixed share of the tasks, chosen by hash, before any reply is looked at."""
    order = sorted(task_ids, key=lambda t: _rank(seed, "split", t))
    return set(order[:round(len(order) * dev / (dev + test))])


def take_in_turn(rows: list[dict[str, Any]], n: int, seed: str, tag: str) -> list[dict[str, Any]]:
    """One row from each stratum in turn until n are taken; inside a stratum the order is a fixed shuffle."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: _rank(seed, tag, r["run"], r["task_id"])):
        groups[row["stratum"]].append(row)
    picked = [groups[s][i] for i in range(max(map(len, groups.values()), default=0))
              for s in sorted(groups) if i < len(groups[s])]
    return picked[:n]


def reply_sample(runs_dir: Path, sizes: dict[str, int] | None = None, seed: str = SEED,
                 include_mock: bool = False) -> dict[str, Any]:
    sizes = {**SIZES, **(sizes or {})}
    if min(sizes.values()) < 1 or sizes["retest"] > sizes["test"]:
        raise ValueError("开发、测试、重标的条数都要大于 0，重标不能比测试集多")
    pool, skipped, sources = load_pool(runs_dir, include_mock)
    dev_tasks = split_tasks({r["task_id"] for r in pool}, sizes["dev"], sizes["test"], seed)
    sides = {"dev": [r for r in pool if r["task_id"] in dev_tasks],
             "test": [r for r in pool if r["task_id"] not in dev_tasks]}
    chosen = {split: take_in_turn(sides[split], sizes[split], seed, split) for split in ("dev", "test")}
    for split in ("dev", "test"):
        if len(chosen[split]) < sizes[split]:
            raise ValueError(f"{split} 一侧只有 {len(sides[split])} 条可用，不够 {sizes[split]} 条"
                             f"（轨迹池共 {len(pool)} 条，没进池的：{skipped or '无'}；可以调小 --{split}）")
    retest = {(r["run"], r["task_id"]) for r in take_in_turn(chosen["test"], sizes["retest"], seed, "retest")}

    files: dict[str, list[dict[str, Any]]] = {}
    key = []
    for split in ("dev", "test"):
        files[f"items-{split}.jsonl"] = []
        for row in chosen[split]:
            item_id = _rank(seed, "item", row["run"], row["task_id"])[:16]
            files[f"items-{split}.jsonl"].append({
                "item_id": item_id, "rubric": "reply_truthful", "split": split,
                "sections": [{"heading": "最终回复", "text": row["reply"]},
                             {"heading": "轨迹里实际发生的事", "text": row["facts"]}]})
            key.append({"item_id": item_id, "split": split, "retest": (row["run"], row["task_id"]) in retest,
                        "run": row["run"], "task_id": row["task_id"], "cluster": row["task_id"],
                        "model": row["model"], "stratum": row["stratum"],
                        "raters": {KEYWORD_RULE: keyword_label(row["program"]["reply"])},
                        "program": row["program"]})
    files["key.jsonl"] = key
    strata = {s: {"dev_pool": sum(r["stratum"] == s for r in sides["dev"]),
                  "test_pool": sum(r["stratum"] == s for r in sides["test"]),
                  "dev": sum(r["stratum"] == s for r in chosen["dev"]),
                  "test": sum(r["stratum"] == s for r in chosen["test"])}
              for s in sorted({r["stratum"] for r in pool})}
    manifest = {
        "schema": "judge-calib/1", "rubric": "reply_truthful", "seed": seed, "sizes": sizes,
        "splits": ["dev", "test"], "include_mock": include_mock,
        "keyword_rule": f"verify.verifier.reply_check（{VERIFIER_VERSION}），抽样时对每条轨迹重新算",
        "pool": {"eligible": len(pool), "skipped": skipped, "runs": sources,
                 "without_eval": sum(r["program"]["task_success"] is None for r in pool),
                 "tasks": {"dev": len(dev_tasks), "test": len({r["task_id"] for r in pool} - dev_tasks)}},
        "strata": strata,
        "split_rule": "先按 task_id 的哈希把题切成开发和测试两侧，同一道题的所有回复在同一侧",
        "allocation": "每一侧按 模型|关键词判定结果 分层，各层轮流取；少见的层被有意多取，样本里的比例不是轨迹池里的比例",
        "retest_rule": "重标子集从测试集里同样分层轮流取",
    }
    return {"files": files, "manifest": manifest}


# ----- rubric B: annual-report answers already in the repository ----------------------------------

def _source_lines(sources: dict[str, Any], doc: str) -> str:
    return "\n".join(
        f"第 {c['page']} 页（表头在第 {c['header_page']} 页）｜{c['row']}｜{c['column']}｜{c['value']} {c['unit']}"
        for c in sources["cells"].values() if c["doc"] == doc)


def annual_sample(root: Path = rubrics.ROOT, seed: str = SEED) -> dict[str, Any]:
    folder = root / REPORT_DEV
    arms_path = root / evidence_trials.DATASET
    cases, sources = read_json(folder / "cases.json"), read_json(folder / "sources.json")
    reviews = read_json(folder / "review.json")
    items, key = [], []

    def add(source: str, run_id: str, case_id: str, stratum: str, sections: list[dict[str, str]], raters: dict[str, str]):
        item_id = _rank(seed, "item", source, run_id)[:16]
        doc = cases[case_id]["cells"][0].split(".")[0]
        sections = [{"heading": "问题", "text": cases[case_id]["question"]}, *sections,
                    {"heading": "原表摘录", "text": _source_lines(sources, doc)}]
        items.append({"item_id": item_id, "rubric": "annual_verdict", "split": "all", "sections": sections})
        key.append({"item_id": item_id, "split": "all", "retest": False, "source": source, "run_id": run_id,
                    "cluster": case_id, "stratum": stratum, "raters": raters})

    for row in read_lines(folder / "observations.jsonl"):
        cited = "、".join(f"{c['doc']} 第 {c['page']} 页" + (f"，格 {c['cell']}" if "cell" in c else "")
                          for c in row["citations"]) or "没有给出"
        status = {"available": "可读取", "timeout": "读取超时"}[row["evidence_status"]]
        add("report_dev_v1", row["run_id"], row["case_id"], row["source_kind"],
            [{"heading": "回答", "text": row["answer"]},
             {"heading": "回答引用的页", "text": f"{cited}。运行时证据{status}。"}],
            {"program": score(cases[row["case_id"]], row, sources)["scores"]["value_pages"],
             "dev_label": reviews[row["run_id"]]["verdict"]})

    arms = {item["case_id"]: item for item in read_json(arms_path)}
    scored = {r["run_id"]: r for r in evidence_trials.summarize(arms_path, root / TRIALS, folder)["rows"]}
    for raw in read_lines(root / TRIALS):
        result, reply = scored[raw["run_id"]], scored[raw["run_id"]]["reply"]
        if result["state"] == "answered":
            answer = (f"{reply['value']} {reply['unit']}；引用页：{'、'.join(map(str, reply['pages']))}；"
                      f"说明：{reply.get('explanation', '')}")
        elif result["state"] == "abstained":
            answer = f"没有给数（status=unknown）。说明：{reply.get('explanation', '')}"
        else:
            answer = "输出不合格式：" + (raw.get("response", {}).get("message", {}).get("content") or raw.get("error", ""))
        add("evidence_trials_v1", raw["run_id"], raw["case_id"], "local_model",
            [{"heading": "模型当时看到的年报摘录", "text": "\n".join(arms[raw["case_id"]]["arms"][raw["arm"]])},
             {"heading": "回答", "text": answer}],
            {"program": result["verdict"]})

    inputs = {str(path): digest(root / path) for path in
              [REPORT_DEV / name for name in ("observations.jsonl", "cases.json", "sources.json", "review.json")]
              + [Path(evidence_trials.DATASET), TRIALS]}
    manifest = {
        "schema": "judge-calib/1", "rubric": "annual_verdict", "seed": seed, "sizes": {"all": len(items)},
        "splits": ["all"], "inputs_sha256": inputs,
        "sources": dict(Counter(row["source"] for row in key)),
        "raters": {"program": "report_dev 用 value_pages 评分，D17 用归档的 verdict",
                   "dev_label": "report_dev 的开发标注（review.json），D17 的 12 条没有"},
        "note": "仓库里现成的全部回答，不切分；簇是题目（case_id），只有 5 个",
    }
    return {"files": {"items-all.jsonl": items, "key.jsonl": key}, "manifest": manifest}


# ----- freezing and reading back ------------------------------------------------------------------

def freeze(out_dir: Path, built: dict[str, Any]) -> str:
    """Write the sample once; on later runs compare what would be written with what is recorded."""
    texts = {name: _jsonl(rows) for name, rows in built["files"].items()}
    manifest = {**built["manifest"], "files": {name: sha256_text(text) for name, text in texts.items()}}
    record = out_dir / "manifest.json"
    if record.exists():
        old = read_json(record)
        diffs = [name for name in sorted(set(old["files"]) | set(texts)) if old["files"].get(name) != manifest["files"].get(name)]
        diffs += [k for k in ("rubric", "seed", "sizes") if old.get(k) != manifest[k]]
        if diffs:
            raise ValueError(f"和 {record} 对不上：{', '.join(diffs)}（记录不会被覆盖；换一个 --out 才能重新抽样）")
        load_dataset(out_dir)
        return "一致"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        with open(out_dir / name, "x", encoding="utf-8") as fh:
            fh.write(text)
    with open(record, "x", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return "已冻结"


def load_dataset(folder: Path) -> dict[str, Any]:
    """The frozen sample, refused if any file no longer matches the manifest."""
    manifest = read_json(folder / "manifest.json")
    for name, expected in manifest["files"].items():
        if digest(folder / name) != expected:
            raise ValueError(f"{folder / name} 和冻结记录对不上")
    key = {row["item_id"]: row for row in read_lines(folder / "key.jsonl")}
    items = {split: read_lines(folder / f"items-{split}.jsonl") for split in manifest["splits"]}
    shown = [item["item_id"] for rows in items.values() for item in rows]
    if len(set(shown)) != len(shown) or set(shown) != set(key):
        raise ValueError(f"{folder} 里的条目和 key.jsonl 对不上")
    return {"folder": folder, "manifest": manifest, "rubric": manifest["rubric"], "items": items, "key": key}


def split_items(dataset: dict[str, Any], split: str) -> list[dict[str, Any]]:
    """The items of one split; `retest` is the relabelling subset of the test split."""
    if split == "retest":
        return [item for item in dataset["items"].get("test", []) if dataset["key"][item["item_id"]]["retest"]]
    if split not in dataset["items"]:
        raise ValueError(f"{dataset['folder']} 没有 {split} 这个划分，只有 {', '.join(dataset['items'])}")
    return dataset["items"][split]


def command(args) -> None:
    out = Path(args.out or rubrics.DATA / rubrics.RUBRICS[args.rubric]["folder"])
    try:
        if args.rubric == "annual_verdict":
            built = annual_sample(seed=args.seed)
        else:
            if not args.runs or not os.path.isdir(args.runs):
                sys.exit(f"找不到轨迹目录 {args.runs}：--runs 指向放 traces.jsonl 和 evals.jsonl 的 runs 目录")
            built = reply_sample(Path(args.runs), {"dev": args.dev, "test": args.test, "retest": args.retest},
                                 args.seed, args.include_mock)
        state = freeze(out, built)
    except ValueError as err:
        sys.exit(f"不能抽样：{err}")
    manifest = built["manifest"]
    if "pool" in manifest:
        pool = manifest["pool"]
        print(f"轨迹池 {pool['eligible']} 条可用（{len(pool['runs'])} 个运行目录）；没进池的：{pool['skipped'] or '无'}")
        for stratum, n in manifest["strata"].items():
            print(f"  {stratum:48s} 开发 {n['dev']}/{n['dev_pool']}  测试 {n['test']}/{n['test_pool']}")
    sizes = "，".join(f"{name} {len(rows)} 条" for name, rows in built["files"].items() if name != "key.jsonl")
    print(f"{state}：{sizes} → {out}")
