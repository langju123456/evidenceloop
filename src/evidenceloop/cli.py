"""el: the EvidenceLoop command line.

  el tasks build  --split calibration --n 60 --out data/tasks
  el run          --tasks data/tasks/calibration.public.jsonl --backend mlx --model Qwen/Qwen3-0.6B --out runs/calib_mlx
  el eval         --traces runs/calib_mlx/traces.jsonl --private data/tasks/calibration.private.jsonl --out runs/calib_mlx/evals.jsonl
  el report baseline --evals runs/calib_mlx/evals.jsonl --names base --out reports/baseline.md
  el data build   --policy targeted --seed 1 --n 200 --evals runs/mining/evals.jsonl --out data/sft/C1
  el export sft   --records data/sft/B1/records.jsonl data/sft/C1/records.jsonl data/sft/D1/records.jsonl \
                  --names B1 C1 D1 --format trl --seed 1 --out data/sft/export_seed1

`run` never opens a private file: the model side of the pipeline cannot see answers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from evidenceloop.data.export import build_manifest, expand, match_budgets, to_format, write_jsonl


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _append_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def cmd_tasks_build(args: argparse.Namespace) -> None:
    from evidenceloop.tasks.generator import generate_split

    os.makedirs(args.out, exist_ok=True)
    target = os.path.join(args.out, f"{args.split}.public.jsonl")
    if os.path.exists(target) and not args.force:
        print(f"{target} 已存在，跳过（已有轨迹依赖这些题目；确实要重新生成请加 --force，或换一个 --out 目录）")
        return
    publics, privates, rejects = generate_split(args.split, args.n)
    write_jsonl(os.path.join(args.out, f"{args.split}.public.jsonl"), publics)
    write_jsonl(os.path.join(args.out, f"{args.split}.private.jsonl"), privates)
    write_jsonl(os.path.join(args.out, f"{args.split}.rejects.jsonl"), rejects)
    print(f"{args.split}: {len(publics)} tasks, {len(rejects)} rejected")


def _backend(args: argparse.Namespace):
    if args.backend == "scripted":
        from evidenceloop.harness.scripted import ScriptedBackend
        return ScriptedBackend(corruption=args.corruption, order=args.order)
    if args.backend == "mlx":
        from evidenceloop.harness.backends import MLXBackend
        return MLXBackend(args.model, adapter_path=args.adapter, max_tokens=args.max_tokens, thinking=args.thinking)
    from evidenceloop.harness.backends import VLLMBackend
    return VLLMBackend(args.model, lora_path=args.adapter, dtype=args.dtype, max_tokens=args.max_tokens,
                       tensor_parallel_size=args.tp, thinking=args.thinking)


def cmd_run(args: argparse.Namespace) -> None:
    from evidenceloop.harness.loop import run_episodes

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "traces.jsonl")
    existing = _read_jsonl(out_path)
    done = {t["task_id"] for t in existing}
    tasks = [t for t in _read_jsonl(args.tasks) if t["task_id"] not in done]
    if args.limit:
        tasks = tasks[: max(0, args.limit - len(done))]
    print(f"{len(done)} already done, {len(tasks)} to run")
    backend = _backend(args)
    from evidenceloop.common import ENV_VERSION, content_hash
    config_hash = content_hash({"backend": backend.describe(), "max_turns": args.max_turns})
    stale = [t for t in existing if t.get("env_version") != ENV_VERSION or t.get("inference_config_hash") != config_hash]
    if stale:
        sys.exit(f"{args.out} 里有 {len(stale)} 条轨迹来自不同的环境版本或模型配置，不能接着跑。请换一个 --out 目录。")
    began = time.time()
    for start in range(0, len(tasks), args.batch_size):
        batch = tasks[start:start + args.batch_size]
        traces = run_episodes(batch, backend, max_turns=args.max_turns, attempt_seed=args.attempt_seed)
        _append_jsonl(out_path, traces)  # every batch is durable: an interrupted run resumes here
        done_now = start + len(batch)
        elapsed = time.time() - began
        eta = elapsed / done_now * (len(tasks) - done_now)
        print(f"  {done_now}/{len(tasks)}  已用 {elapsed / 60:.1f} 分钟，预计还要 {eta / 60:.1f} 分钟", flush=True)


def cmd_eval(args: argparse.Namespace) -> None:
    from evidenceloop.verify.verifier import evaluate

    privates = {p["task_id"]: p for p in _read_jsonl(args.private)}
    traces = _read_jsonl(args.traces)
    known = [t for t in traces if t["task_id"] in privates]
    if len(known) < len(traces):
        print(f"skipped {len(traces) - len(known)} traces whose tasks are not in {args.private} (older task set?)")
    results = [evaluate(t, privates[t["task_id"]]) for t in known]
    write_jsonl(args.out, results)
    print(f"{sum(r['task_success'] for r in results)}/{len(results)} succeeded")


def cmd_report(args: argparse.Namespace) -> None:
    from evidenceloop.report.baseline import render_markdown

    names = args.names or [os.path.basename(os.path.dirname(p)) for p in args.evals]
    runs = {name: _read_jsonl(path) for name, path in zip(names, args.evals)}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(args.title, runs))
    print(f"wrote {args.out}")


def cmd_data_build(args: argparse.Namespace) -> None:
    from evidenceloop.data.build import build_training_set

    evals = _read_jsonl(args.evals) if args.evals else None
    if args.policy != "uniform" and not evals:
        sys.exit("targeted and unfiltered need --evals from train_mining")
    built = build_training_set(args.policy, args.seed, args.n, evals)
    os.makedirs(args.out, exist_ok=True)
    write_jsonl(os.path.join(args.out, "records.jsonl"), built["records"])
    write_jsonl(os.path.join(args.out, "rejects.jsonl"), built["rejects"])
    with open(os.path.join(args.out, "build.json"), "w", encoding="utf-8") as fh:
        json.dump({k: built[k] for k in ("policy", "seed", "weights", "reject_counts", "corrupted")}, fh, ensure_ascii=False, indent=2)
    print(f"{args.policy}: {len(built['records'])} trajectories, rejects {built['reject_counts']}, corrupted {built['corrupted']}")


def cmd_export(args: argparse.Namespace) -> None:
    names = args.names or [os.path.basename(os.path.dirname(p)) for p in args.records]
    built_meta, sets = {}, {}
    for name, path in zip(names, args.records):
        records = _read_jsonl(path)
        meta_path = os.path.join(os.path.dirname(path), "build.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
        built_meta[name] = {"policy": records[0]["policy"], "seed": meta.get("seed"), "weights": meta.get("weights", {}),
                            "reject_counts": meta.get("reject_counts", {}), "corrupted": meta.get("corrupted", 0)}
        sets[name] = [s for r in records for s in expand(r)]
    matched = match_budgets(sets, args.seed) if len(sets) > 1 else {"samples": sets, "within_tolerance": True,
                                                                       "n_per_group": len(next(iter(sets.values())))}
    os.makedirs(args.out, exist_ok=True)
    for name, samples in matched["samples"].items():
        write_jsonl(os.path.join(args.out, f"{name}.{args.format}.jsonl"), [to_format(s, args.format) for s in samples])
        manifest = build_manifest(name, built_meta[name], samples, args.format)
        with open(os.path.join(args.out, f"{name}.manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"{matched['n_per_group']} samples per group; supervised size within 5%: {matched['within_tolerance']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="el")
    sub = parser.add_subparsers(dest="command", required=True)

    tasks = sub.add_parser("tasks").add_subparsers(dest="action", required=True).add_parser("build")
    tasks.add_argument("--split", required=True,
                       choices=["calibration", "train_mining", "validation", "test_id", "test_ood"])
    tasks.add_argument("--n", type=int, required=True)
    tasks.add_argument("--out", default="data/tasks")
    tasks.add_argument("--force", action="store_true")
    tasks.set_defaults(func=cmd_tasks_build)

    run = sub.add_parser("run")
    run.add_argument("--tasks", required=True)
    run.add_argument("--backend", required=True, choices=["scripted", "mlx", "vllm"])
    run.add_argument("--model")
    run.add_argument("--adapter")
    run.add_argument("--corruption")
    run.add_argument("--order", default="filter_first", choices=["filter_first", "convert_first"])
    run.add_argument("--out", required=True)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--batch-size", type=int, default=64)
    run.add_argument("--max-turns", type=int, default=12)
    run.add_argument("--max-tokens", type=int, default=512)
    run.add_argument("--attempt-seed", type=int, default=0)
    run.add_argument("--dtype", default="half")
    run.add_argument("--tp", type=int, default=1)
    run.add_argument("--thinking", action="store_true", help="Qwen3 thinking mode (sampled, larger token budget)")
    run.set_defaults(func=cmd_run)

    ev = sub.add_parser("eval")
    ev.add_argument("--traces", required=True)
    ev.add_argument("--private", required=True)
    ev.add_argument("--out", required=True)
    ev.set_defaults(func=cmd_eval)

    report = sub.add_parser("report").add_subparsers(dest="action", required=True).add_parser("baseline")
    report.add_argument("--evals", nargs="+", required=True)
    report.add_argument("--names", nargs="+")
    report.add_argument("--title", default="EvidenceLoop 基线报告")
    report.add_argument("--out", required=True)
    report.set_defaults(func=cmd_report)

    data = sub.add_parser("data").add_subparsers(dest="action", required=True).add_parser("build")
    data.add_argument("--policy", required=True, choices=["uniform", "targeted", "unfiltered"])
    data.add_argument("--seed", type=int, required=True)
    data.add_argument("--n", type=int, required=True)
    data.add_argument("--evals")
    data.add_argument("--out", required=True)
    data.set_defaults(func=cmd_data_build)

    export = sub.add_parser("export").add_subparsers(dest="action", required=True).add_parser("sft")
    export.add_argument("--records", nargs="+", required=True)
    export.add_argument("--names", nargs="+")
    export.add_argument("--format", required=True, choices=["trl", "mlx"])
    export.add_argument("--seed", type=int, default=0)
    export.add_argument("--out", required=True)
    export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
