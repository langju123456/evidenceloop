"""D25: train one LoRA candidate with menu-code augmentation only.

The original D22 evaluator remains the authority for collection and the
adoption gate.  This module changes only the two presentations seen by the
training rows, then records enough provenance to reproduce that fact.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import time
from pathlib import Path
from typing import Any

from evidenceloop.report import action_sft as d22

ROOT = d22.ROOT
PROTOCOL = ROOT / "docs/report-lab/16-menu-augmented-sft-freeze.md"
MENU_IDS = ("canonical", "rotated")
ACTION_BY_CODE = {
    "A": "fy25_growth", "B": "fy25_contribution", "C": "fy24_growth",
    "D": "fy24_contribution", "E": "user_pause", "F": "missing_evidence",
}
ROTATED_ACTIONS = (
    "missing_evidence", "fy24_contribution", "user_pause", "fy25_growth",
    "fy24_growth", "fy25_contribution",
)
ACTION_TEXT = {
    "fy25_growth": "FY2025同比", "fy25_contribution": "FY2025贡献",
    "fy24_growth": "FY2024同比", "fy24_contribution": "FY2024贡献",
    "user_pause": "按用户要求暂停", "missing_evidence": "表中缺少计算所需年度",
}
FREEZE_FILES = [
    Path(__file__), PROTOCOL, d22.DATA / "train.json", d22.DATA / "dev.json",
    d22.DATA / "holdout.json", d22.DATA / "regression.json", d22.DATA / "sources.json",
    d22.DATA / "finance-reference.json", d22.DATA / "model.json", Path(d22.__file__),
    ROOT / "src/evidenceloop/report/calculation.py", ROOT / "src/evidenceloop/report/annual.py",
]


def code_for(menu_id: str, action: str) -> str:
    actions = tuple(ACTION_BY_CODE.values()) if menu_id == "canonical" else ROTATED_ACTIONS
    if action not in actions:
        raise ValueError("unknown menu or action")
    return chr(65 + actions.index(action))


def options(menu_id: str) -> str:
    actions = tuple(ACTION_BY_CODE.values()) if menu_id == "canonical" else ROTATED_ACTIONS
    return "，".join(f"{chr(65 + index)}={ACTION_TEXT[action]}" for index, action in enumerate(actions)) + "。"


def messages(task: dict[str, Any], source: dict[str, Any], menu_id: str) -> list[dict[str, str]]:
    if menu_id == "canonical":
        return d22.messages(task, source, "base")
    initial_action = ACTION_BY_CODE[task["initial"]]
    initial_code = code_for(menu_id, initial_action)
    system = "请从六个工具动作中选一个执行，只输出一个英文字母。" + options(menu_id)
    cells = source["cells"]
    table = [f"FY20{year}: {cells['S' + year]} / {cells['T' + year]}"
             for year in ("25", "24", "23") if "S" + year in cells]
    user = (f"{source['name']}。每行依次为{source['segment']}与总收入，单位{source['unit']}。\n"
            + "\n".join(table) + f"\n送审前动作 {initial_code}。\n"
            + "\n".join(f"分析师：{turn}" for turn in task["turns"]))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def training_plan() -> list[dict[str, Any]]:
    """Return the fixed 64-step order without importing MLX or model weights."""
    cases = d22.examples("train")
    rng = random.Random(d22.SEED)
    plan = []
    for epoch in (1, 2):
        order = list(range(len(cases)))
        rng.shuffle(order)
        for index in order:
            task = cases[index]
            menu_id = MENU_IDS[(index + epoch - 1) % len(MENU_IDS)]
            action = ACTION_BY_CODE[task["gold"]]
            plan.append({"epoch": epoch, "case_index": index, "case_id": task["case_id"],
                         "menu_id": menu_id, "gold_action": action,
                         "target_code": code_for(menu_id, action)})
    return plan


def check_data() -> None:
    d22.check_data()
    plan = training_plan()
    if len(plan) != 64:
        raise ValueError("D25 must retain exactly 64 gradient updates")
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in plan:
        by_case.setdefault(row["case_id"], []).append(row)
    if len(by_case) != 32 or any({r["menu_id"] for r in rows} != set(MENU_IDS) for rows in by_case.values()):
        raise ValueError("each original training delegation must see each menu exactly once")
    train_docs = {task["document"] for task in d22.examples("train")}
    eval_docs = {task["document"] for split in d22.EVAL for task in d22.examples(split)}
    if train_docs != {"dell", "cisco"} or train_docs & eval_docs:
        raise ValueError("training and evaluation documents must remain isolated")


def digest(path: Path) -> str:
    return d22.sha(path)


def freeze_payload() -> dict[str, Any]:
    check_data()
    return {
        "schema": "action-sft-menu-augmented/1",
        "repository_head_at_freeze": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "files": {str(path.relative_to(ROOT)): digest(path) for path in FREEZE_FILES},
        "base_sha256": d22.BASE_SHA,
        "config": d22.CONFIG,
        "seed": d22.SEED,
        "updates": 64,
        "menu_schedule": "menu[(case_index + epoch - 1) % 2]",
        "menus": list(MENU_IDS),
        "evaluation_scope": {
            "dev": "Apple development set",
            "holdout": "Tencent and Moutai exposed-reuse regression set; not fresh holdout",
            "regression": "Oracle exposed regression set",
        },
    }


def freeze(folder: Path) -> Path:
    if folder.exists():
        raise FileExistsError("refusing to overwrite a frozen or experimental directory")
    folder.mkdir(parents=True)
    path = folder / "freeze.json"
    d22.write(path, freeze_payload())
    return path


def verify_freeze(path: Path) -> dict[str, Any]:
    frozen = d22.read_json(path)
    expected = freeze_payload()
    for key in ("schema", "files", "base_sha256", "config", "seed", "updates", "menu_schedule", "menus", "evaluation_scope"):
        if frozen.get(key) != expected[key]:
            raise ValueError(f"changed after D25 freeze: {key}")
    return frozen


def _check_base(base: Path) -> None:
    if not base.is_dir() or digest(base / d22.WEIGHTS) != d22.BASE_SHA:
        raise ValueError("wrong base snapshot")
    profile = d22.read_json(d22.DATA / "model.json")
    for name, expected in profile["files"].items():
        if digest(base / name) != expected:
            raise ValueError(f"mismatched model file {name}")
    if d22.runtime() != profile["runtime"]:
        raise ValueError("training or inference runtime differs from freeze")


def train(base: Path, folder: Path, freeze_file: Path) -> None:
    """Create one final adapter.  No early stopping or candidate selection."""
    verify_freeze(freeze_file)
    marker = folder / "training-started.json"
    steps_file = folder / "training-steps.jsonl"
    failure = folder / "training-failure.json"
    if marker.exists() or (folder / "training.json").exists() or (folder / "adapter").exists():
        raise FileExistsError("D25 training already exists; never overwrite or silently retry")
    d22.write(marker, {"freeze": digest(freeze_file), "base_sha256": d22.BASE_SHA,
                       "planned_updates": 64, "steps_file": steps_file.name})
    steps = []
    try:
        _check_base(base)
        import mlx.core as mx
        import mlx.optimizers as optim
        from mlx import nn
        from mlx.utils import tree_flatten
        from mlx_lm import load
        from mlx_lm.tuner.utils import linear_to_lora_layers

        sources = d22.read_json(d22.DATA / "sources.json")
        tasks = d22.examples("train")
        model, tokenizer = load(str(base))
        model.freeze()
        mx.random.seed(d22.SEED)
        linear_to_lora_layers(model, d22.CONFIG["num_layers"], d22.CONFIG["lora_parameters"])
        model.train()
        params = dict(tree_flatten(model.trainable_parameters()))
        if len(params) != 16 or any(name.rsplit(".", 1)[-1] not in ("lora_a", "lora_b") for name in params):
            raise ValueError("unexpected trainable weights")
        token_ids = {code: tokenizer.encode(code, add_special_tokens=False) for code in d22.CODES}
        if token_ids != {code: [32 + index] for index, code in enumerate(d22.CODES)}:
            raise ValueError("unexpected action-letter token mapping")
        optimizer = optim.Adam(learning_rate=0.0002)
        encoded = []
        for row in training_plan():
            task = tasks[row["case_index"]]
            prompt = messages(task, sources[task["document"]], row["menu_id"])
            ids = tokenizer.apply_chat_template(prompt, tokenize=True, add_generation_prompt=True,
                                                enable_thinking=False, return_dict=False)
            if not 0 < len(ids) <= 512:
                raise ValueError("input outside preregistered budget")
            target_ids = token_ids[row["target_code"]]
            encoded.append((row, mx.array([ids]), mx.array(target_ids), target_ids[0]))

        def loss_fn(net, inputs, target):
            return nn.losses.cross_entropy(net(inputs)[:, -1, :].astype(mx.float32), target).mean()

        gradient = nn.value_and_grad(model, loss_fn)
        started = time.monotonic()
        with steps_file.open("x", encoding="utf-8") as stream:
            for row, inputs, target, target_token in encoded:
                loss, grads = gradient(model, inputs, target)
                optimizer.update(model, grads)
                mx.eval(model.trainable_parameters(), optimizer.state, loss)
                value = loss.item()
                if not math.isfinite(value):
                    raise ValueError("non-finite training loss")
                record = {**row, "target_token": target_token, "loss": value, "input_tokens": inputs.size}
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                steps.append(record)
        adapter = folder / "adapter"
        adapter.mkdir()
        weights = dict(tree_flatten(model.trainable_parameters()))
        delta_max = max(float(mx.max(mx.abs(weight)).item()) for name, weight in weights.items() if name.endswith("lora_b"))
        if not delta_max > 0:
            raise ValueError("LoRA B matrices did not update")
        mx.save_safetensors(str(adapter / "adapters.safetensors"), weights)
        d22.write(adapter / "adapter_config.json", d22.CONFIG)
        d22.write(folder / "training.json", {
            "freeze": digest(freeze_file), "base_sha256": d22.BASE_SHA, "steps": steps, "seed": d22.SEED,
            "trainable_parameters": sum(weight.size for weight in weights.values()), "largest_abs_B": delta_max,
            "seconds": round(time.monotonic() - started, 3), "peak_memory_bytes": mx.get_peak_memory(),
            "adapter_sha256": digest(adapter / "adapters.safetensors"), "runtime": d22.runtime(),
            "training_scope": "Dell/Cisco only; each original case saw canonical and rotated menu once",
        })
    except BaseException as error:
        if not failure.exists():
            d22.write(failure, {"freeze": digest(freeze_file), "error_type": type(error).__name__,
                                "error": str(error), "completed_updates": len(steps),
                                "steps_file": steps_file.name})
        raise


def verify_training_receipt(folder: Path, freeze_file: Path) -> dict[str, Any]:
    """Require the persisted D25 plan and adapter receipt before evaluation."""
    freeze_digest = digest(freeze_file)
    marker = d22.read_json(folder / "training-started.json")
    if marker != {"freeze": freeze_digest, "base_sha256": d22.BASE_SHA,
                  "planned_updates": 64, "steps_file": "training-steps.jsonl"}:
        raise ValueError("invalid D25 training-started marker")
    if (folder / "training-failure.json").exists():
        raise ValueError("D25 training recorded a failure; do not collect or score it")
    steps_path = folder / "training-steps.jsonl"
    logged = [json.loads(line) for line in steps_path.read_text(encoding="utf-8").splitlines()]
    training = d22.read_json(folder / "training.json")
    if training.get("freeze") != freeze_digest or training.get("base_sha256") != d22.BASE_SHA:
        raise ValueError("training summary does not match D25 freeze or base")
    if training.get("seed") != d22.SEED or training.get("steps") != logged:
        raise ValueError("training summary and append-only step log disagree")
    plan = training_plan()
    if len(logged) != 64 or len(logged) != len(plan):
        raise ValueError("D25 receipt does not contain exactly 64 updates")
    for actual, expected in zip(logged, plan, strict=True):
        if {key: actual.get(key) for key in expected} != expected:
            raise ValueError("D25 receipt deviates from frozen menu plan")
        expected_token = 32 + d22.CODES.index(expected["target_code"])
        if actual.get("target_token") != expected_token:
            raise ValueError("D25 receipt has an unexpected target token")
        if not isinstance(actual.get("input_tokens"), int) or not 0 < actual["input_tokens"] <= 512:
            raise ValueError("D25 receipt has an invalid input length")
        if not isinstance(actual.get("loss"), (int, float)) or not math.isfinite(actual["loss"]):
            raise ValueError("D25 receipt has a non-finite loss")
    adapter = folder / "adapter"
    if d22.read_json(adapter / "adapter_config.json") != d22.CONFIG:
        raise ValueError("D25 adapter configuration mismatch")
    if training.get("adapter_sha256") != digest(adapter / "adapters.safetensors"):
        raise ValueError("D25 adapter fingerprint mismatch")
    return training


def collect(base: Path, folder: Path, freeze_file: Path) -> None:
    verify_freeze(freeze_file)
    verify_training_receipt(folder, freeze_file)
    _check_base(base)
    # D22's collector reloads this adapter from disk and evaluates the unchanged canonical evaluator inputs.
    d22.collect(base, folder, d22.read_json(d22.DATA / "sources.json"), digest(freeze_file))


def score(folder: Path, freeze_file: Path) -> dict[str, Any]:
    verify_freeze(freeze_file)
    verify_training_receipt(folder, freeze_file)
    result = d22.summarize(folder, d22.read_json(d22.DATA / "sources.json"), digest(freeze_file))
    return {**result, "schema": "action-sft-menu-augmented-results/1", "evaluation_scope": {
        "holdout": "exposed-reuse regression set; do not call fresh holdout",
        "regression": "exposed Oracle regression set",
    }}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "freeze", "train", "collect", "score"))
    parser.add_argument("--base", type=Path)
    parser.add_argument("--out", type=Path, required=False)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.action == "check":
        check_data()
        return
    if args.action == "freeze":
        if args.out is None:
            parser.error("freeze requires --out")
        print(freeze(args.out))
        return
    if args.out is None or args.freeze is None:
        parser.error(f"{args.action} requires --out and --freeze")
    if args.action == "train":
        if args.base is None:
            parser.error("train requires --base")
        train(args.base, args.out, args.freeze)
    elif args.action == "collect":
        if args.base is None:
            parser.error("collect requires --base")
        collect(args.base, args.out, args.freeze)
    else:
        output = args.out / "results.json"
        if output.exists():
            raise FileExistsError("D25 results already exist; never overwrite")
        d22.write(output, score(args.out, args.freeze))
        print(output)


if __name__ == "__main__":
    main()
