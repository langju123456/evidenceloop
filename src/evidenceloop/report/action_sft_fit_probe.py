"""D26: frozen terminal train-fit probe for the D22/D25 adapters.

This is a diagnosis, not a new training candidate.  It reloads each arm once
and archives one constrained next-token decision for every training case and
menu.  Existing D22/D25 artifacts remain immutable.
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
from evidenceloop.report import action_sft_menu_aug as d25

ROOT = d22.ROOT
PROTOCOL = ROOT / "docs/report-lab/18-terminal-train-fit-probe.md"
ARMS = ("base", "d22_lora", "d25_lora")
MENUS = d25.MENU_IDS
D22_FOLDER = ROOT / "reports/report-lab/action-sft-v1"
D25_FOLDER = ROOT / "reports/report-lab/action-sft-menu-aug-v1"
FREEZE_FILES = [
    Path(__file__), PROTOCOL, Path(d22.__file__), Path(d25.__file__),
    d22.DATA / "train.json", d22.DATA / "sources.json", d22.DATA / "model.json",
    D22_FOLDER / "training.json", D22_FOLDER / "adapter/adapter_config.json",
    D22_FOLDER / "adapter/adapters.safetensors", D25_FOLDER / "freeze.json",
    D25_FOLDER / "training.json", D25_FOLDER / "adapter/adapter_config.json",
    D25_FOLDER / "adapter/adapters.safetensors",
]


def _digest(path: Path) -> str:
    return d22.sha(path)


def _adapter_sha(arm: str) -> str | None:
    if arm == "base":
        return None
    folder = D22_FOLDER if arm == "d22_lora" else D25_FOLDER
    return _digest(folder / "adapter/adapters.safetensors")


def _adapter_path(arm: str) -> Path | None:
    if arm == "base":
        return None
    return (D22_FOLDER if arm == "d22_lora" else D25_FOLDER) / "adapter"


def matrix() -> list[dict[str, Any]]:
    """Return a stable 32 x 2 x 3 schedule without loading MLX."""
    rows = []
    for task in d22.examples("train"):
        action = d25.ACTION_BY_CODE[task["gold"]]
        for menu_id in MENUS:
            rows.append({"case_id": task["case_id"], "menu_id": menu_id,
                         "gold_action": action, "gold_code": d25.code_for(menu_id, action)})
    if len(rows) != 64 or len({(r["case_id"], r["menu_id"]) for r in rows}) != 64:
        raise ValueError("expected the fixed 64-cell training matrix")
    return rows


def check_protocol() -> None:
    d25.check_data()
    if tuple(ARMS) != ("base", "d22_lora", "d25_lora") or tuple(MENUS) != ("canonical", "rotated"):
        raise ValueError("probe arms or menus changed")
    if len(matrix()) * len(ARMS) != 192:
        raise ValueError("probe must contain exactly 192 first responses")
    if d22.read_json(D22_FOLDER / "adapter/adapter_config.json") != d22.CONFIG:
        raise ValueError("D22 adapter config changed")
    d25.verify_training_receipt(D25_FOLDER, D25_FOLDER / "freeze.json")


def freeze_payload() -> dict[str, Any]:
    check_protocol()
    return {
        "schema": "action-sft-terminal-fit/1",
        "repository_head_at_freeze": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "files": {str(path.relative_to(ROOT)): _digest(path) for path in FREEZE_FILES},
        "base_sha256": d22.BASE_SHA,
        "runtime": d22.read_json(d22.DATA / "model.json")["runtime"],
        "matrix": matrix(),
        "arms": list(ARMS),
        "menus": list(MENUS),
        "attempt_policy": "one forward pass per (case_id, menu_id, arm); no retry or overwrite",
        "decision_rule": {
            "d25_supervised_cells": 64,
            "if_lt_64": "one fixed 0.6B D25-equivalent candidate with restricted A-F CE only",
            "if_eq_64": "one fixed cached 1.7B D25-equivalent candidate; no 4B fallback",
        },
        "scope": "Dell/Cisco training-fit diagnosis only; passing it is not a generalization claim.",
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
    current = freeze_payload()
    for key in ("schema", "files", "base_sha256", "runtime", "matrix", "arms", "menus", "attempt_policy", "decision_rule", "scope"):
        if saved.get(key) != current[key]:
            raise ValueError(f"changed after D26 freeze: {key}")
    return saved


def _check_base(base: Path) -> None:
    d25._check_base(base)


def _target_stats(mx: Any, logits: Any, token: int, action_tokens: list[int]) -> tuple[float, float]:
    target = float(logits[token].item())
    alternatives = [float(logits[value].item()) for value in action_tokens if value != token]
    nll = float((mx.logsumexp(logits) - logits[token]).item())
    return nll, target - max(alternatives)


def run(base: Path, folder: Path, freeze_file: Path) -> Path:
    """Reload each persisted arm and create exactly 192 append-only rows."""
    frozen = verify_freeze(freeze_file)
    if folder / "predictions.jsonl" in folder.iterdir() or (folder / "results.json").exists():
        raise FileExistsError("D26 probe output already exists; never overwrite or retry")
    _check_base(base)
    import mlx.core as mx
    from mlx_lm import load

    marker = folder / "probe-started.json"
    d22.write(marker, {"freeze": _digest(freeze_file), "planned_rows": 192,
                       "arms": list(ARMS), "matrix_cells": 64})
    sources = d22.read_json(d22.DATA / "sources.json")
    tasks = {task["case_id"]: task for task in d22.examples("train")}
    attempted = 0
    try:
        with (folder / "predictions.jsonl").open("x", encoding="utf-8") as stream:
            for arm in ARMS:
                adapter = _adapter_path(arm)
                model, tokenizer = load(str(base), adapter_path=str(adapter) if adapter else None)
                model.eval()
                tokens = [tokenizer.encode(code, add_special_tokens=False) for code in d22.CODES]
                if tokens != [[32 + index] for index in range(6)]:
                    raise ValueError("unexpected action-letter token mapping")
                action_tokens = [single[0] for single in tokens]
                for cell in frozen["matrix"]:
                    task = tasks[cell["case_id"]]
                    source = sources[task["document"]]
                    prompt = d25.messages(task, source, cell["menu_id"])
                    ids = tokenizer.apply_chat_template(prompt, tokenize=True, add_generation_prompt=True,
                                                       enable_thinking=False, return_dict=False)
                    if not 0 < len(ids) <= 512:
                        raise ValueError("input outside preregistered budget")
                    started = time.monotonic()
                    logits = model(mx.array([ids]))[0, -1].astype(mx.float32)
                    scores = logits[mx.array(action_tokens)].tolist()
                    choice = d22.CODES[max(range(6), key=scores.__getitem__)]
                    target_token = 32 + d22.CODES.index(cell["gold_code"])
                    nll, margin = _target_stats(mx, logits, target_token, action_tokens)
                    row = {**cell, "arm": arm, "attempt": 1, "freeze": _digest(freeze_file),
                           "base_sha256": d22.BASE_SHA, "adapter_sha256": _adapter_sha(arm),
                           "messages": prompt, "input_tokens": len(ids), "scores": scores,
                           "choice": choice, "choice_action": d25.ACTION_BY_CODE[choice],
                           "restricted_correct": choice == cell["gold_code"],
                           "full_vocab_top": int(mx.argmax(logits).item()),
                           "target_full_vocab_nll": nll, "target_margin_vs_other_actions": margin,
                           "seconds": round(time.monotonic() - started, 4)}
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    attempted += 1
                del model, tokenizer
                mx.clear_cache()
        result = summarize(folder, freeze_file)
        d22.write(folder / "results.json", result)
        return folder / "results.json"
    except BaseException as error:
        failure = folder / "probe-failure.json"
        if not failure.exists():
            d22.write(failure, {"freeze": _digest(freeze_file), "error_type": type(error).__name__,
                                "error": str(error), "completed_rows": attempted})
        raise


def summarize(folder: Path, freeze_file: Path) -> dict[str, Any]:
    frozen = verify_freeze(freeze_file)
    expected = {(cell["case_id"], cell["menu_id"], arm): cell for cell in frozen["matrix"] for arm in ARMS}
    actual: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line in (folder / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row.get("case_id"), row.get("menu_id"), row.get("arm"))
        cell = expected.get(key)
        if cell is None or key in actual:
            raise ValueError("unexpected or duplicate D26 probe row")
        if row.get("attempt") != 1 or row.get("freeze") != _digest(freeze_file):
            raise ValueError("invalid D26 first-response receipt")
        if row.get("base_sha256") != d22.BASE_SHA or row.get("adapter_sha256") != _adapter_sha(key[2]):
            raise ValueError("D26 model fingerprint mismatch")
        task = next(task for task in d22.examples("train") if task["case_id"] == key[0])
        source = d22.read_json(d22.DATA / "sources.json")[task["document"]]
        if row.get("messages") != d25.messages(task, source, key[1]):
            raise ValueError("D26 prompt differs from frozen presentation")
        if row.get("gold_action") != cell["gold_action"] or row.get("gold_code") != cell["gold_code"]:
            raise ValueError("D26 gold action/code mismatch")
        scores = row.get("scores")
        if not isinstance(scores, list) or len(scores) != 6 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in scores):
            raise ValueError("D26 invalid action logits")
        if row.get("choice") != d22.CODES[max(range(6), key=scores.__getitem__)]:
            raise ValueError("D26 non-deterministic constrained choice")
        for field in ("target_full_vocab_nll", "target_margin_vs_other_actions"):
            if not isinstance(row.get(field), (int, float)) or not math.isfinite(row[field]):
                raise ValueError(f"D26 invalid {field}")
        actual[key] = row
    if set(actual) != set(expected) or len(actual) != 192:
        raise ValueError("D26 probe matrix is incomplete")
    by_arm = {}
    for arm in ARMS:
        rows = [actual[key] for key in actual if key[2] == arm]
        by_menu = {menu: sum(row["restricted_correct"] for row in rows if row["menu_id"] == menu) for menu in MENUS}
        by_arm[arm] = {"n": len(rows), "restricted_correct": sum(row["restricted_correct"] for row in rows),
                       "by_menu": by_menu, "mean_target_full_vocab_nll": round(sum(row["target_full_vocab_nll"] for row in rows) / len(rows), 6),
                       "mean_target_margin_vs_other_actions": round(sum(row["target_margin_vs_other_actions"] for row in rows) / len(rows), 6)}
    d25_fit = by_arm["d25_lora"]["restricted_correct"]
    classification = "training_actions_fully_fit_but_not_generalization_evidence" if d25_fit == 64 else "training_actions_not_fully_fit"
    return {"schema": "action-sft-terminal-fit-results/1", "freeze": _digest(freeze_file),
            "predictions_sha256": _digest(folder / "predictions.jsonl"), "rows": 192,
            "by_arm": by_arm, "d25_supervised_fit": {"n": 64, "restricted_correct": d25_fit,
                "classification": classification,
                "next_candidate": frozen["decision_rule"]["if_eq_64" if d25_fit == 64 else "if_lt_64"]},
            "scope": frozen["scope"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "freeze", "run", "verify"))
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
    if args.action == "verify":
        print(json.dumps(summarize(args.out, args.freeze), ensure_ascii=False, indent=2))
    else:
        if args.base is None:
            parser.error("run requires --base")
        print(run(args.base, args.out, args.freeze))


if __name__ == "__main__":
    main()
