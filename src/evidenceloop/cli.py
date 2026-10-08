"""el: the EvidenceLoop command line.

  el tasks build  --split calibration --n 60 --out data/tasks
  el run          --tasks data/tasks/calibration.public.jsonl --backend mlx --model Qwen/Qwen3-0.6B --out runs/calib_mlx
  el eval         --traces runs/calib_mlx/traces.jsonl --private data/tasks/calibration.private.jsonl --out runs/calib_mlx/evals.jsonl
  el report baseline --evals runs/calib_mlx/evals.jsonl --names base --out reports/baseline.md
  el freeze       --tasks-dir data/tasks/gen-0.2.0 --base Qwen/Qwen3-1.7B --calibration reports/calibration_x.md
  el data build   --policy targeted --seed 1 --n 200 --evals runs/mining/evals.jsonl --out data/sft/C1
  el export sft   --records data/sft/B1/records.jsonl data/sft/C1/records.jsonl data/sft/D1/records.jsonl \
                  --names B1 C1 D1 --format trl --seed 1 --out data/sft/export_seed1
  el frozen verify --tasks-dir data/tasks/gen-0.2.1
  el warmup build --tasks-dir data/tasks/gen-0.2.1 --out data/warmup
  el warmup check --evals runs/W25_train_mining/evals.jsonl --out reports/warmup_check_W25.md

`run` never opens a private file: the model side of the pipeline cannot see answers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from evidenceloop.data.export import build_manifest, expand, match_budgets, supervised_size, to_format, write_jsonl


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _require(*paths: str) -> None:
    """Inputs must exist: a missing file would otherwise read as empty and give an empty result."""
    missing = [path for path in paths if not os.path.exists(path)]
    if missing:
        sys.exit(f"找不到 {', '.join(missing)}")


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


FREEZE_SIZES = {"train_mining": 200, "validation": 50, "test_id": 150, "test_ood": 150}


def _sha256_file(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cmd_freeze(args: argparse.Namespace) -> None:
    """Build the official splits once (never overwritten), check them, and record what was frozen."""
    from datetime import date

    from evidenceloop.common import ENV_VERSION, GENERATOR_VERSION, VERIFIER_VERSION
    from evidenceloop.tasks.generator import OOD_TEMPLATES, generate_split

    sizes = dict(FREEZE_SIZES)
    for item in args.sizes or []:
        split, _, n = item.partition("=")
        if split not in sizes or not n.isdigit():
            sys.exit(f"--sizes 的写法是 split=数量，split 取 {', '.join(sizes)}")
        sizes[split] = int(n)
    missing = [path for path in args.calibration if not os.path.exists(path)]
    if missing:
        sys.exit(f"找不到校准报告 {', '.join(missing)}：冻结要写明是根据哪几份校准定的")
    os.makedirs(args.tasks_dir, exist_ok=True)

    record: dict[str, Any] = {"splits": {}}
    keys: dict[str, set[str]] = {}
    has_calibration = os.path.exists(os.path.join(args.tasks_dir, "calibration.public.jsonl"))
    for split in (("calibration",) if has_calibration else ()) + tuple(sizes):
        public = os.path.join(args.tasks_dir, f"{split}.public.jsonl")
        private = os.path.join(args.tasks_dir, f"{split}.private.jsonl")
        if split != "calibration" and not os.path.exists(public):
            publics, privates, rejects = generate_split(split, sizes[split])
            write_jsonl(public, publics)
            write_jsonl(private, privates)
            write_jsonl(os.path.join(args.tasks_dir, f"{split}.rejects.jsonl"), rejects)
        pubs, privs = _read_jsonl(public), _read_jsonl(private)
        if not pubs:
            sys.exit(f"{public} 不存在或为空")
        if split != "calibration" and len(pubs) != sizes[split]:
            sys.exit(f"{public} 里有 {len(pubs)} 道题，要求 {sizes[split]} 道；已有的划分不会被覆盖，请换一个目录")
        if {p["generator_version"] for p in pubs} != {GENERATOR_VERSION}:
            sys.exit(f"{public} 不是用当前生成器 {GENERATOR_VERSION} 生成的")
        templates = {p["knobs"]["template"] for p in pubs}
        if (split == "test_ood") != bool(templates & set(OOD_TEMPLATES)) or (split == "test_ood" and not templates <= set(OOD_TEMPLATES)):
            sys.exit(f"{split} 的提示模板没有按 OOD 规则隔离：{sorted(templates)}")
        keys[split] = {p["dedup_key"] for p in privs}
        record["splits"][split] = {
            "n": len(pubs),
            "short_tier": sum(1 for p in pubs if p["knobs"]["units"] == "all_V"),
            "public_sha256": _sha256_file(public),
            "private_sha256": _sha256_file(private),
        }
    names = list(keys)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = keys[a] & keys[b]
            if shared:
                sys.exit(f"{a} 和 {b} 有 {len(shared)} 道题内容重复，不能冻结")

    record = {
        "frozen_at": date.today().isoformat(),
        "base_model": args.base,
        "generator_version": GENERATOR_VERSION,
        "env_version": ENV_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "calibration_reports": args.calibration,
        "note": args.note or "",
        "tasks_dir": args.tasks_dir,
        "checks": {"no_duplicates_across_splits": True, "ood_templates_isolated": True},
        "reproducibility": "data/ 不进版本库；题目由生成器确定性生成，重新生成后哈希应与这里一致。test_id 与 test_ood 在阶段三之前保持密封。",
        **record,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    for split, info in record["splits"].items():
        print(f"{split:13s} {info['n']:4d} 道（简单档 {info['short_tier']}）  {info['public_sha256'][:12]}")
    print(f"已冻结：基座 {args.base}，{GENERATOR_VERSION} / {ENV_VERSION} / {VERIFIER_VERSION} → {args.out}")


def cmd_frozen_verify(args: argparse.Namespace) -> None:
    """Regenerate any missing frozen split files and check them against configs/frozen.json (on Kaggle,
    or any fresh clone: data/ is not in the repo). Existing files are never overwritten."""
    from evidenceloop.common import GENERATOR_VERSION
    from evidenceloop.tasks.generator import generate_split

    with open(args.record, encoding="utf-8") as fh:
        record = json.load(fh)
    if record["generator_version"] != GENERATOR_VERSION:
        sys.exit(f"冻结记录是 {record['generator_version']}，当前生成器是 {GENERATOR_VERSION}，不能核对")
    tasks_dir = args.tasks_dir or record["tasks_dir"]
    os.makedirs(tasks_dir, exist_ok=True)
    bad = []
    for split, info in record["splits"].items():
        public = os.path.join(tasks_dir, f"{split}.public.jsonl")
        private = os.path.join(tasks_dir, f"{split}.private.jsonl")
        if not os.path.exists(public):
            publics, privates, rejects = generate_split(split, info["n"])
            write_jsonl(public, publics)
            write_jsonl(private, privates)
            write_jsonl(os.path.join(tasks_dir, f"{split}.rejects.jsonl"), rejects)
        same = _sha256_file(public) == info["public_sha256"] and _sha256_file(private) == info["private_sha256"]
        print(f"{split:13s} {'一致' if same else '不一致'}")
        if not same:
            bad.append(split)
    if bad:
        sys.exit(f"{', '.join(bad)} 和冻结记录对不上，不能继续")
    print(f"四个划分都和 {args.record} 一致")


def cmd_warmup_build(args: argparse.Namespace) -> None:
    """D11: build the warm-up doses once, record seeds and hashes; on a second machine, check them."""
    from evidenceloop.common import ENV_VERSION, GENERATOR_VERSION, VERIFIER_VERSION
    from evidenceloop.data.warmup import build_warmup

    result = build_warmup(args.tasks_dir, args.seed, tuple(args.doses))
    built = result["built"]
    os.makedirs(args.out, exist_ok=True)
    doses = {}
    for dose, records in result["doses"].items():
        samples = [s for r in records for s in expand(r)]
        write_jsonl(os.path.join(args.out, f"dose{dose}.records.jsonl"), records)
        trl_path = os.path.join(args.out, f"dose{dose}.trl.jsonl")
        write_jsonl(trl_path, [to_format(s, "trl") for s in samples])
        doses[str(dose)] = {"tasks": len(records), "samples": len(samples),
                            "supervised_chars": sum(supervised_size(s) for s in samples),
                            "trl_sha256": _sha256_file(trl_path)}
    write_jsonl(os.path.join(args.out, "rejects.jsonl"), built["rejects"])
    record = {
        "decision": "D11",
        "generator_version": GENERATOR_VERSION,
        "env_version": ENV_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "policy": "uniform",
        "seed": args.seed,
        "doses": doses,
        "nested": "小档是大档的前缀：同一串题的前 N 道",
        "frozen_tasks_dir": args.tasks_dir,
        "frozen_splits_checked": result["frozen_splits"],
        "excluded_frozen_duplicates": result["excluded_frozen_duplicates"],
        "templates": result["templates"],
        "reject_counts": built["reject_counts"],
        "reproducibility": "data/ 不进版本库；预热数据由生成器和参考解法确定性生成，重新运行 el warmup build 后哈希应与这里一致。",
    }
    for dose, info in doses.items():
        print(f"dose {dose:>3s}: {info['tasks']} 道题，{info['samples']} 条样本，{info['trl_sha256'][:12]}")
    print(f"和冻结划分重复而剔除的题：{result['excluded_frozen_duplicates']}")
    if os.path.exists(args.record):
        with open(args.record, encoding="utf-8") as fh:
            old = json.load(fh)
        diffs = [d for d in old["doses"] if doses.get(d, {}).get("trl_sha256") != old["doses"][d]["trl_sha256"]]
        diffs += [k for k in ("seed", "generator_version", "env_version", "verifier_version") if old.get(k) != record[k]]
        if diffs:
            sys.exit(f"和 {args.record} 对不上：{', '.join(diffs)}（记录不会被覆盖）")
        print(f"和 {args.record} 一致")
        return
    os.makedirs(os.path.dirname(args.record) or ".", exist_ok=True)
    with open(args.record, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"记录写入 {args.record}")


def cmd_warmup_check(args: argparse.Namespace) -> None:
    from evidenceloop.data.warmup import check_warmup, render_check

    _require(args.evals)
    try:
        result = check_warmup(_read_jsonl(args.evals), expected_n=args.expected_n)
    except ValueError as err:
        sys.exit(f"不能做达标检查：{err}")
    text = render_check(result, args.title)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)


def _backend(args: argparse.Namespace):
    if args.backend == "scripted":
        from evidenceloop.harness.scripted import ScriptedBackend
        return ScriptedBackend(corruption=args.corruption, order=args.order)
    if args.backend == "mlx":
        from evidenceloop.harness.backends import MLXBackend
        return MLXBackend(args.model, adapter_path=args.adapter, max_tokens=args.max_tokens, thinking=args.thinking)
    if args.backend == "hf":
        if args.thinking:
            sys.exit("hf 后端只跑不开 thinking 的贪心解码")
        from evidenceloop.harness.backends import HFBackend
        return HFBackend(args.model, adapter_path=args.adapter, max_tokens=args.max_tokens, gen_batch=args.gen_batch)
    from evidenceloop.harness.backends import VLLMBackend
    return VLLMBackend(args.model, lora_path=args.adapter, dtype=args.dtype, max_tokens=args.max_tokens,
                       tensor_parallel_size=args.tp, thinking=args.thinking)


def cmd_run(args: argparse.Namespace) -> None:
    """Resumable: tasks already in traces.jsonl are skipped, except infra_error ones (the backend crashed,
    e.g. out of memory), which are run again; the old file is kept as a backup first."""
    from evidenceloop.harness.loop import run_episodes

    _require(args.tasks)
    if args.adapter and args.backend == "hf" and not os.path.exists(os.path.join(args.adapter, "adapter_config.json")):
        sys.exit(f"{args.adapter} 里没有 adapter_config.json：训练没有跑完，或者 --adapter 路径写错了")
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "traces.jsonl")
    existing = _read_jsonl(out_path)
    kept = [t for t in existing if t.get("termination") != "infra_error"]
    redo = len(existing) - len(kept)
    done = {t["task_id"] for t in kept}
    tasks = [t for t in _read_jsonl(args.tasks) if t["task_id"] not in done]
    if args.limit:
        tasks = tasks[: max(0, args.limit - len(done))]
    print(f"{len(done)} already done, {len(tasks)} to run" + (f"（其中 {redo} 道上次是运行故障，重跑）" if redo else ""))
    backend = _backend(args)
    from evidenceloop.common import ENV_VERSION, content_hash
    config_hash = content_hash({"backend": backend.describe(), "max_turns": args.max_turns})
    stale = [t for t in kept if t.get("env_version") != ENV_VERSION or t.get("inference_config_hash") != config_hash]
    if stale:
        sys.exit(f"{args.out} 里有 {len(stale)} 条轨迹来自不同的环境版本或模型配置（换了模型、权重或设置），"
                 "不能接着跑。请换一个 --out 目录。")
    if redo:
        import shutil

        backup = f"{out_path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copyfile(out_path, backup)
        write_jsonl(out_path + ".tmp", kept)
        os.replace(out_path + ".tmp", out_path)  # atomic: an interruption leaves either the old file or the new one
        print(f"原文件备份在 {backup}")
    began = time.time()
    failed = 0
    for start in range(0, len(tasks), args.batch_size):
        batch = tasks[start:start + args.batch_size]
        traces = run_episodes(batch, backend, max_turns=args.max_turns, attempt_seed=args.attempt_seed)
        _append_jsonl(out_path, traces)  # every batch is durable: an interrupted run resumes here
        failed += sum(1 for t in traces if t["termination"] == "infra_error")
        done_now = start + len(batch)
        elapsed = time.time() - began
        eta = elapsed / done_now * (len(tasks) - done_now)
        note = backend.status() if hasattr(backend, "status") else ""
        print(f"  {done_now}/{len(tasks)}  已用 {elapsed / 60:.1f} 分钟，预计还要 {eta / 60:.1f} 分钟"
              + (f"  {note}" if note else "") + (f"  运行故障 {failed} 道" if failed else ""), flush=True)
    if failed:
        print(f"有 {failed} 道是运行故障（infra_error）。再运行同一条命令，只重跑这些题。")


def cmd_eval(args: argparse.Namespace) -> None:
    from evidenceloop.verify.verifier import evaluate

    _require(args.traces, args.private)
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

    _require(*args.evals)
    names = args.names or [os.path.basename(os.path.dirname(p)) for p in args.evals]
    runs = {name: _read_jsonl(path) for name, path in zip(names, args.evals)}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(args.title, runs))
    print(f"wrote {args.out}")


def cmd_data_build(args: argparse.Namespace) -> None:
    """Stage 3 builds pass --exclude-tasks-dir (the frozen splits) and --exclude-records (the warm-up data),
    so no training task repeats an evaluation task or a task W was already trained on."""
    from evidenceloop.data.build import build_training_set
    from evidenceloop.data.warmup import frozen_dedup_keys

    if args.evals:
        _require(args.evals)
    evals = _read_jsonl(args.evals) if args.evals else None
    if args.policy != "uniform" and not evals:
        sys.exit("targeted and unfiltered need --evals from train_mining")
    exclude: set[str] = set()
    sources: dict[str, int] = {}
    if args.exclude_tasks_dir:
        try:
            frozen = frozen_dedup_keys(args.exclude_tasks_dir)
        except FileNotFoundError as err:
            sys.exit(str(err))
        for split, keys in frozen.items():
            exclude |= keys
            sources[split] = len(keys)
    for path in args.exclude_records or []:
        if not os.path.exists(path):
            sys.exit(f"找不到 {path}")
        keys = {r["dedup_key"] for r in _read_jsonl(path) if r.get("dedup_key")}
        if not keys:
            sys.exit(f"{path} 里没有 dedup_key（用当前版本的 el warmup build / el data build 重新生成）")
        exclude |= keys
        sources[path] = len(keys)
    built = build_training_set(args.policy, args.seed, args.n, evals, exclude_keys=exclude or None)
    os.makedirs(args.out, exist_ok=True)
    write_jsonl(os.path.join(args.out, "records.jsonl"), built["records"])
    write_jsonl(os.path.join(args.out, "rejects.jsonl"), built["rejects"])
    meta = {k: built[k] for k in ("policy", "seed", "weights", "reject_counts", "corrupted")}
    meta["excluded_from"] = sources
    with open(os.path.join(args.out, "build.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f"{args.policy}: {len(built['records'])} trajectories, rejects {built['reject_counts']}, corrupted {built['corrupted']}")


def cmd_export(args: argparse.Namespace) -> None:
    _require(*args.records)
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
    run.add_argument("--backend", required=True, choices=["scripted", "mlx", "vllm", "hf"])
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
    run.add_argument("--gen-batch", type=int, default=8, help="hf backend: prompts per generate call")
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

    freeze = sub.add_parser("freeze")
    freeze.add_argument("--tasks-dir", required=True)
    freeze.add_argument("--base", required=True, help="the base model chosen from calibration")
    freeze.add_argument("--calibration", nargs="+", required=True, help="the calibration reports the choice was based on")
    freeze.add_argument("--note", help="anything a reader of the frozen record must know")
    freeze.add_argument("--sizes", nargs="*", help="override split sizes, e.g. train_mining=200 test_id=150")
    freeze.add_argument("--out", default="configs/frozen.json")
    freeze.set_defaults(func=cmd_freeze)

    data = sub.add_parser("data").add_subparsers(dest="action", required=True).add_parser("build")
    data.add_argument("--policy", required=True, choices=["uniform", "targeted", "unfiltered"])
    data.add_argument("--seed", type=int, required=True)
    data.add_argument("--n", type=int, required=True)
    data.add_argument("--evals")
    data.add_argument("--exclude-tasks-dir", help="drop tasks whose content matches a frozen split in this directory")
    data.add_argument("--exclude-records", nargs="+", help="drop tasks already in these records files (the warm-up data)")
    data.add_argument("--out", required=True)
    data.set_defaults(func=cmd_data_build)

    frozen = sub.add_parser("frozen").add_subparsers(dest="action", required=True).add_parser("verify")
    frozen.add_argument("--record", default="configs/frozen.json")
    frozen.add_argument("--tasks-dir", help="defaults to the tasks_dir in the record")
    frozen.set_defaults(func=cmd_frozen_verify)

    warmup = sub.add_parser("warmup").add_subparsers(dest="action", required=True)
    wbuild = warmup.add_parser("build")
    wbuild.add_argument("--tasks-dir", required=True, help="the frozen splits, used for the duplicate check")
    wbuild.add_argument("--seed", type=int, default=900)
    wbuild.add_argument("--doses", type=int, nargs="+", default=[25, 50, 100])
    wbuild.add_argument("--out", default="data/warmup")
    wbuild.add_argument("--record", default="configs/warmup.json")
    wbuild.set_defaults(func=cmd_warmup_build)
    wcheck = warmup.add_parser("check")
    wcheck.add_argument("--evals", required=True, help="W's evals on all 200 train_mining tasks")
    wcheck.add_argument("--expected-n", type=int, default=FREEZE_SIZES["train_mining"])
    wcheck.add_argument("--title", default="预热达标检查（D11）")
    wcheck.add_argument("--out")
    wcheck.set_defaults(func=cmd_warmup_check)

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
