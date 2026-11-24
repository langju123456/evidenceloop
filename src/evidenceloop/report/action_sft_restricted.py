"""D27: one frozen D25-equivalent candidate with restricted A--F CE.

Only the loss changes: the next-token distribution is restricted to the six
legal action letters before cross entropy.  Data, prompts, 64-step schedule,
seed, LoRA placement/configuration, optimizer, and the original canonical D22
adoption gate remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from evidenceloop.report import action_sft as d22
from evidenceloop.report import action_sft_fit_audit as d26audit
from evidenceloop.report import action_sft_menu_aug as d25

ROOT = d22.ROOT
PROTOCOL = ROOT / "docs/report-lab/20-restricted-action-sft-freeze.md"
FREEZE_FILES = [Path(__file__), PROTOCOL, Path(d22.__file__), Path(d25.__file__), Path(d26audit.__file__),
                d22.DATA / "train.json", d22.DATA / "dev.json", d22.DATA / "holdout.json",
                d22.DATA / "regression.json", d22.DATA / "sources.json", d22.DATA / "finance-reference.json",
                d22.DATA / "model.json", ROOT / "src/evidenceloop/report/calculation.py",
                ROOT / "src/evidenceloop/report/annual.py"]


def action_tokens(tokenizer: Any) -> list[int]:
    encoded = [tokenizer.encode(code, add_special_tokens=False) for code in d22.CODES]
    if encoded != [[32 + index] for index in range(6)]:
        raise ValueError("unexpected action-letter token mapping")
    return [single[0] for single in encoded]


def plan() -> list[dict[str, Any]]:
    return d25.training_plan()


def check_protocol() -> None:
    d25.check_data()
    rows = plan()
    if len(rows) != 64 or any(row["target_code"] not in d22.CODES for row in rows):
        raise ValueError("D27 must retain D25's exact 64-step plan")
    if {row["menu_id"] for row in rows} != set(d25.MENU_IDS):
        raise ValueError("D27 menu presentations changed")


def digest(path: Path) -> str:
    return d22.sha(path)


def freeze_payload() -> dict[str, Any]:
    check_protocol()
    return {
        "schema": "action-sft-restricted/1",
        "repository_head_at_freeze": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "files": {str(path.relative_to(ROOT)): digest(path) for path in FREEZE_FILES},
        "base_sha256": d22.BASE_SHA, "runtime": d22.read_json(d22.DATA / "model.json")["runtime"],
        "config": d22.CONFIG, "seed": d22.SEED, "updates": 64,
        "menu_schedule": "menu[(case_index + epoch - 1) % 2]", "plan": plan(),
        "only_changed_variable": "restricted cross_entropy(logits[A:F], target_action_index), replacing full-vocabulary CE",
        "train_fit_requirement": "candidate terminal train fit must equal 64/64 on the 32x2 D25 presentations",
        "adoption_requirement": "original D22 canonical 96-row gate must pass AND terminal train fit must equal 64/64",
        "evaluation_scope": {"holdout": "exposed-reuse regression set; not fresh holdout",
                             "regression": "exposed Oracle regression set"},
    }


def freeze(folder: Path) -> Path:
    if folder.exists():
        raise FileExistsError("refusing to overwrite a frozen or experimental directory")
    folder.mkdir(parents=True)
    path = folder / "freeze.json"
    d22.write(path, freeze_payload())
    return path


def verify_freeze(path: Path) -> dict[str, Any]:
    saved = d22.read_json(path)
    expected = freeze_payload()
    for key in ("schema", "files", "base_sha256", "runtime", "config", "seed", "updates",
                "menu_schedule", "plan", "only_changed_variable", "train_fit_requirement",
                "adoption_requirement", "evaluation_scope"):
        if saved.get(key) != expected[key]:
            raise ValueError(f"changed after D27 freeze: {key}")
    return saved


def _check_base(base: Path) -> None:
    d25._check_base(base)


def train(base: Path, folder: Path, freeze_file: Path) -> None:
    frozen = verify_freeze(freeze_file)
    marker = folder / "training-started.json"
    if marker.exists() or (folder / "training.json").exists() or (folder / "adapter").exists():
        raise FileExistsError("D27 training already exists; never overwrite or silently retry")
    d22.write(marker, {"freeze": digest(freeze_file), "base_sha256": d22.BASE_SHA,
                       "planned_updates": 64, "steps_file": "training-steps.jsonl",
                       "loss": "restricted_action_cross_entropy"})
    steps: list[dict[str, Any]] = []
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
        if sum(weight.size for weight in params.values()) != 81920:
            raise ValueError("unexpected trainable parameter count")
        allowed = action_tokens(tokenizer)
        encoded = []
        for row in frozen["plan"]:
            task = tasks[row["case_index"]]
            prompt = d25.messages(task, sources[task["document"]], row["menu_id"])
            ids = tokenizer.apply_chat_template(prompt, tokenize=True, add_generation_prompt=True,
                                               enable_thinking=False, return_dict=False)
            if not 0 < len(ids) <= 512:
                raise ValueError("input outside preregistered budget")
            target_index = d22.CODES.index(row["target_code"])
            encoded.append((row, mx.array([ids]), mx.array([target_index]), target_index))

        allowed_tensor = mx.array(allowed)

        def loss_fn(net, inputs, target_index):
            full_logits = net(inputs)[:, -1, :].astype(mx.float32)
            return nn.losses.cross_entropy(full_logits[:, allowed_tensor], target_index).mean()

        gradient = nn.value_and_grad(model, loss_fn)
        optimizer = optim.Adam(learning_rate=0.0002)
        started = time.monotonic()
        with (folder / "training-steps.jsonl").open("x", encoding="utf-8") as stream:
            for row, inputs, target_index, action_index in encoded:
                loss, grads = gradient(model, inputs, target_index)
                optimizer.update(model, grads)
                mx.eval(model.trainable_parameters(), optimizer.state, loss)
                value = float(loss.item())
                if not math.isfinite(value):
                    raise ValueError("non-finite training loss")
                record = {**row, "target_token": allowed[action_index], "target_action_index": action_index,
                          "loss": value, "input_tokens": inputs.size}
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
        d22.write(folder / "training.json", {"freeze": digest(freeze_file), "base_sha256": d22.BASE_SHA,
                  "steps": steps, "seed": d22.SEED, "trainable_parameters": sum(weight.size for weight in weights.values()),
                  "largest_abs_B": delta_max, "seconds": round(time.monotonic() - started, 3),
                  "peak_memory_bytes": mx.get_peak_memory(), "adapter_sha256": digest(adapter / "adapters.safetensors"),
                  "runtime": d22.runtime(), "loss": "restricted_action_cross_entropy"})
    except BaseException as error:
        failure = folder / "training-failure.json"
        if not failure.exists():
            d22.write(failure, {"freeze": digest(freeze_file), "error_type": type(error).__name__,
                                "error": str(error), "completed_updates": len(steps)})
        raise


def verify_training_receipt(folder: Path, freeze_file: Path) -> dict[str, Any]:
    frozen = verify_freeze(freeze_file)
    marker = d22.read_json(folder / "training-started.json")
    if marker != {"freeze": digest(freeze_file), "base_sha256": d22.BASE_SHA, "planned_updates": 64,
                  "steps_file": "training-steps.jsonl", "loss": "restricted_action_cross_entropy"}:
        raise ValueError("invalid D27 training-started marker")
    if (folder / "training-failure.json").exists():
        raise ValueError("D27 training recorded a failure; do not collect or score it")
    steps = [json.loads(line) for line in (folder / "training-steps.jsonl").read_text(encoding="utf-8").splitlines()]
    training = d22.read_json(folder / "training.json")
    if training.get("runtime") != frozen["runtime"] or training.get("trainable_parameters") != 81920:
        raise ValueError("D27 runtime or trainable parameter count changed")
    delta = training.get("largest_abs_B")
    if not isinstance(delta, (int, float)) or not math.isfinite(delta) or delta <= 0:
        raise ValueError("D27 adapter update receipt is invalid")
    if training.get("freeze") != digest(freeze_file) or training.get("base_sha256") != d22.BASE_SHA or training.get("loss") != "restricted_action_cross_entropy":
        raise ValueError("D27 training summary mismatch")
    if training.get("steps") != steps or training.get("seed") != d22.SEED or len(steps) != 64:
        raise ValueError("D27 step receipt mismatch")
    for actual, expected in zip(steps, frozen["plan"], strict=True):
        if {key: actual.get(key) for key in expected} != expected:
            raise ValueError("D27 receipt deviates from frozen menu plan")
        index = d22.CODES.index(expected["target_code"])
        if actual.get("target_action_index") != index or actual.get("target_token") != 32 + index:
            raise ValueError("D27 receipt target mismatch")
        if not isinstance(actual.get("input_tokens"), int) or not 0 < actual["input_tokens"] <= 512:
            raise ValueError("D27 receipt invalid input length")
        if not isinstance(actual.get("loss"), (int, float)) or not math.isfinite(actual["loss"]):
            raise ValueError("D27 receipt non-finite loss")
    adapter = folder / "adapter"
    if d22.read_json(adapter / "adapter_config.json") != d22.CONFIG or training.get("adapter_sha256") != digest(adapter / "adapters.safetensors"):
        raise ValueError("D27 adapter receipt mismatch")
    return training


def collect_train_fit(base: Path, folder: Path, freeze_file: Path) -> Path:
    """Archive the candidate's 64 terminal training-presentation first answers."""
    frozen = verify_freeze(freeze_file)
    verify_training_receipt(folder, freeze_file)
    output = folder / "training-fit.jsonl"
    if output.exists():
        raise FileExistsError("D27 training fit output already exists; never overwrite")
    _check_base(base)
    import mlx.core as mx
    from mlx_lm import load

    sources = d22.read_json(d22.DATA / "sources.json")
    tasks = {task["case_id"]: task for task in d22.examples("train")}
    adapter = folder / "adapter"
    model, tokenizer = load(str(base), adapter_path=str(adapter))
    model.eval()
    allowed = action_tokens(tokenizer)
    try:
        with output.open("x", encoding="utf-8") as stream:
            for row in frozen["plan"]:
                task = tasks[row["case_id"]]
                prompt = d25.messages(task, sources[task["document"]], row["menu_id"])
                ids = tokenizer.apply_chat_template(prompt, tokenize=True, add_generation_prompt=True,
                                                   enable_thinking=False, return_dict=False)
                if not 0 < len(ids) <= 512:
                    raise ValueError("input outside preregistered budget")
                logits = model(mx.array([ids]))[0, -1].astype(mx.float32)
                scores = logits[mx.array(allowed)].tolist()
                choice = d22.CODES[max(range(6), key=scores.__getitem__)]
                stream.write(json.dumps({"case_id": row["case_id"], "menu_id": row["menu_id"], "attempt": 1,
                    "freeze": digest(freeze_file), "base_sha256": d22.BASE_SHA,
                    "adapter_sha256": digest(adapter / "adapters.safetensors"), "gold_action": row["gold_action"],
                    "gold_code": row["target_code"], "choice": choice,
                    "choice_action": d26audit.action_for(row["menu_id"], choice), "scores": scores,
                    "restricted_correct": choice == row["target_code"], "input_tokens": len(ids)},
                    ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
    finally:
        del model, tokenizer
        mx.clear_cache()
    return output


def summarize_train_fit(folder: Path, freeze_file: Path) -> dict[str, Any]:
    frozen = verify_freeze(freeze_file)
    expected = {(row["case_id"], row["menu_id"]): row for row in frozen["plan"]}
    seen = set()
    correct = 0
    adapter_sha = digest(folder / "adapter/adapters.safetensors")
    for line in (folder / "training-fit.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row.get("case_id"), row.get("menu_id"))
        expected_row = expected.get(key)
        if expected_row is None or key in seen:
            raise ValueError("unexpected or duplicate D27 train-fit row")
        seen.add(key)
        scores = row.get("scores")
        if (row.get("attempt") != 1 or row.get("freeze") != digest(freeze_file) or
                row.get("base_sha256") != d22.BASE_SHA or row.get("adapter_sha256") != adapter_sha or
                not isinstance(row.get("input_tokens"), int) or not 0 < row["input_tokens"] <= 512 or
                not isinstance(scores, list) or len(scores) != 6 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in scores)):
            raise ValueError("invalid D27 train-fit receipt")
        choice = d22.CODES[max(range(6), key=scores.__getitem__)]
        if row.get("choice") != choice or row.get("choice_action") != d26audit.action_for(key[1], choice):
            raise ValueError("D27 train-fit action decoding mismatch")
        derived = choice == expected_row["target_code"]
        if row.get("gold_action") != expected_row["gold_action"] or row.get("gold_code") != expected_row["target_code"] or row.get("restricted_correct") is not derived:
            raise ValueError("D27 train-fit gold or correctness mismatch")
        correct += int(derived)
    if set(seen) != set(expected) or len(seen) != 64:
        raise ValueError("D27 train-fit matrix incomplete")
    return {"n": 64, "restricted_correct": correct, "passed": correct == 64,
            "predictions_sha256": digest(folder / "training-fit.jsonl")}


def collect(base: Path, folder: Path, freeze_file: Path) -> None:
    """Run unchanged D22 canonical collection after the restricted train receipt."""
    verify_training_receipt(folder, freeze_file)
    _check_base(base)
    d22.collect(base, folder, d22.read_json(d22.DATA / "sources.json"), digest(freeze_file))
    collect_train_fit(base, folder, freeze_file)


def score(folder: Path, freeze_file: Path) -> dict[str, Any]:
    verify_training_receipt(folder, freeze_file)
    original = d22.summarize(folder, d22.read_json(d22.DATA / "sources.json"), digest(freeze_file))
    train_fit = summarize_train_fit(folder, freeze_file)
    return {"schema": "action-sft-restricted-results/1", **original, "terminal_train_fit": train_fit,
            "gate_passed": original["gate_passed"] and train_fit["passed"],
            "original_canonical_gate_passed": original["gate_passed"],
            "evaluation_scope": d22.read_json(freeze_file)["evaluation_scope"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "freeze", "train", "collect", "score"))
    parser.add_argument("--base", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.action == "check":
        check_protocol()
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
        result = args.out / "results.json"
        if result.exists():
            raise FileExistsError("D27 results already exist; never overwrite")
        d22.write(result, score(args.out, args.freeze))
        print(result)


if __name__ == "__main__":
    main()
