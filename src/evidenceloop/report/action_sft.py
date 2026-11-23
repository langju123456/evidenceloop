"""D22: offline restricted-action SFT and first-response replay for edited reports."""

import argparse
import hashlib
import json
import math
import random
import subprocess
import time
from importlib.metadata import version
from pathlib import Path

from evidenceloop.report.annual import read_json
from evidenceloop.report.calculation import calculate

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "benchmarks/report_sft/v1"
ARMS = ("base", "coached", "lora")
EVAL = ("dev", "holdout", "regression")
CODES = "ABCDEF"
OPTIONS = ("A=FY2025同比，B=FY2025贡献，C=FY2024同比，D=FY2024贡献，"
           "E=按用户要求暂停，F=表中缺少计算所需年度。")
RULE = ("先分别追踪用户最终确认的年份、指标；提案被否决时恢复原项；用户叫停优先。"
        "同比用前一年分项收入，贡献用公司总收入净变化，两年数值都要存在。")
BASE_SHA = "f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b"
WEIGHTS = "model.safetensors"
CONFIG = {"fine_tune_type": "lora", "num_layers": 4, "lora_parameters": {
    "rank": 4, "scale": 8.0, "dropout": 0.0, "keys": ["self_attn.q_proj", "self_attn.v_proj"]}}
SEED = 23
FILES = [*sorted(DATA.glob("*.json")), Path(__file__), ROOT / "docs/report-lab/11-action-sft-freeze.md",
         ROOT / "src/evidenceloop/report/calculation.py", ROOT / "src/evidenceloop/report/annual.py"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def frozen(commit):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("use the full freeze commit")
    for path in FILES:
        before = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{commit}:{path.relative_to(ROOT)}"])
        if path.read_bytes() != before:
            raise ValueError(f"changed after freeze: {path.name}")


def write(path, obj):
    with path.open("x") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def examples(split):
    return read_json(DATA / f"{split}.json")


def messages(task, source, arm):
    system = "请从六个工具动作中选一个执行，只输出一个英文字母。" + OPTIONS
    if arm == "coached":
        system += RULE
    cells = source["cells"]
    table = [f"FY20{y}: {cells['S'+y]} / {cells['T'+y]}" for y in ("25", "24", "23") if 'S'+y in cells]
    user = (f"{source['name']}。每行依次为{source['segment']}与总收入，单位{source['unit']}。\n"
            + "\n".join(table) + f"\n送审前动作 {task['initial']}。\n"
            + "\n".join(f"分析师：{t}" for t in task["turns"]))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def execute(code, source):
    if code in ("E", "F"):
        return {"action": "hold", "reason": "user_paused" if code == "E" else "missing_evidence"}
    year, metric = {"A": (25, "growth"), "B": (25, "contribution"),
                    "C": (24, "growth"), "D": (24, "contribution")}[code]
    numerator = [f"S{year}", f"S{year-1}"]
    denominator = [numerator[1]] if metric == "growth" else [f"T{year}", f"T{year-1}"]
    try:
        numeric = calculate("cells", {"numerator": numerator, "denominator": denominator}, source["cells"])
    except ValueError as e:
        return {"action": "invalid_calculation", "error": str(e)}
    return {"action": "compute", "year": 2000+year, "metric": metric, "page": source["page"], **numeric}


def check_data():
    used = {k: set() for k in ("document", "family", "turns", "case_id")}
    sources = read_json(DATA / "sources.json")
    for split in ("train", *EVAL):
        rows = examples(split)
        assert rows and len({r["case_id"] for r in rows}) == len(rows)
        for key in used:
            values = {tuple(r[key]) if key == "turns" else r[key] for r in rows}
            assert not values & used[key], f"split overlap in {key}"
            used[key].update(values)
        for row in rows:
            assert row["split"] == split and row["gold"] in CODES and row["initial"] in CODES[:4]
            assert execute(row["gold"], sources[row["document"]])["action"] != "invalid_calculation"


def encode(tok, task, source, arm):
    ids = tok.apply_chat_template(messages(task, source, arm), tokenize=True,
                                  add_generation_prompt=True, enable_thinking=False, return_dict=False)
    if not 0 < len(ids) <= 512:
        raise ValueError("input outside preregistered budget")
    return ids


def train(base, sources, folder, freeze):
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from mlx_lm import load
    from mlx_lm.tuner.utils import linear_to_lora_layers

    model, tok = load(str(base))
    model.freeze()
    mx.random.seed(SEED)
    linear_to_lora_layers(model, CONFIG["num_layers"], CONFIG["lora_parameters"])
    model.train()
    params = dict(tree_flatten(model.trainable_parameters()))
    if len(params) != 16 or any(k.rsplit(".", 1)[-1] not in ("lora_a", "lora_b") for k in params):
        raise ValueError("unexpected trainable weights")
    optimizer = optim.Adam(learning_rate=0.0002)
    encoded = []
    for case in examples("train"):
        ids = encode(tok, case, sources[case["document"]], "base")
        target = tok.encode(case["gold"], add_special_tokens=False)
        assert len(target) == 1
        encoded.append((case["case_id"], mx.array([ids]), mx.array(target)))

    def loss_fn(net, inputs, target):
        logits = net(inputs)[:, -1, :].astype(mx.float32)
        return nn.losses.cross_entropy(logits, target).mean()

    gradient = nn.value_and_grad(model, loss_fn)
    rng = random.Random(SEED)
    steps = []
    start = time.monotonic()
    for epoch in (1, 2):
        order = list(range(len(encoded)))
        rng.shuffle(order)
        for i in order:
            case_id, inputs, target = encoded[i]
            loss, grads = gradient(model, inputs, target)
            optimizer.update(model, grads)
            mx.eval(model.trainable_parameters(), optimizer.state, loss)
            value = loss.item()
            if not math.isfinite(value):
                raise ValueError("non-finite training loss")
            steps.append({"epoch": epoch, "case_id": case_id, "loss": value, "input_tokens": inputs.size})
        print(f"trained epoch {epoch}, steps {len(steps)}, last loss {value:.4f}", flush=True)
    adapter = folder / "adapter"
    adapter.mkdir()
    weights = dict(tree_flatten(model.trainable_parameters()))
    delta_max = max(float(mx.max(mx.abs(w)).item()) for k, w in weights.items() if k.endswith("lora_b"))
    if not delta_max > 0:
        raise ValueError("LoRA B matrices did not update")
    mx.save_safetensors(str(adapter / "adapters.safetensors"), weights)
    write(adapter / "adapter_config.json", CONFIG)
    write(folder / "training.json", {"freeze": freeze, "base_sha256": BASE_SHA, "steps": steps, "seed": SEED,
          "trainable_parameters": sum(w.size for w in weights.values()), "largest_abs_B": delta_max,
          "seconds": round(time.monotonic() - start, 3), "peak_memory_bytes": mx.get_peak_memory(),
          "adapter_sha256": sha(adapter / "adapters.safetensors"), "runtime": runtime()})


def runtime():
    import mlx.core as mx
    return {"device": mx.device_info()["device_name"], **{k: version(k) for k in ("mlx", "mlx-lm", "transformers")}}


def collect(base, folder, sources, freeze):
    import mlx.core as mx
    from mlx_lm import load
    log = read_json(folder / "training.json")
    assert log["freeze"] == freeze and log["base_sha256"] == BASE_SHA
    assert log["adapter_sha256"] == sha(folder / "adapter/adapters.safetensors")
    assert read_json(folder / "adapter/adapter_config.json") == CONFIG
    with (folder / "predictions.jsonl").open("x") as out:
        for arm in ARMS:
            adapter = str(folder / "adapter") if arm == "lora" else None
            model, tok = load(str(base), adapter_path=adapter)
            model.eval()
            tokens = [tok.encode(c, add_special_tokens=False) for c in CODES]
            assert tokens == [[n] for n in range(32, 38)]
            for split in EVAL:
                for case in examples(split):
                    source = sources[case["document"]]
                    ids = encode(tok, case, source, arm)
                    start = time.monotonic()
                    logits = model(mx.array([ids]))[0, -1].astype(mx.float32)
                    scores = logits[mx.array([t[0] for t in tokens])].tolist()
                    full = mx.argmax(logits).item()
                    row = dict(case_id=case["case_id"], split=split, arm=arm, freeze=freeze, attempt=1,
                               base_sha256=BASE_SHA, adapter_sha256=log["adapter_sha256"] if adapter else None,
                               messages=messages(case, source, arm), input_tokens=len(ids), scores=scores,
                               full_vocab_top=int(full), seconds=round(time.monotonic()-start, 4))
                    out.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+"\n")
                    out.flush()
            del model, tok
            mx.clear_cache()
            print(f"archived {arm}", flush=True)


def summarize(folder, sources, freeze):
    training = read_json(folder / "training.json")
    fingerprint = sha(folder / "adapter/adapters.safetensors")
    assert training["adapter_sha256"] == fingerprint and training["freeze"] == freeze
    data = {c["case_id"]: c for split in EVAL for c in examples(split)}
    reference = read_json(DATA / "finance-reference.json")
    actual = {}
    for line in (folder / "predictions.jsonl").read_text().splitlines():
        row = json.loads(line)
        arm, cid = row["arm"], row["case_id"]
        case = data[cid]
        key = (arm, cid)
        assert arm in ARMS and key not in actual and row["split"] == case["split"]
        assert row["attempt"] == 1 and row["freeze"] == freeze and row["base_sha256"] == BASE_SHA
        assert row["adapter_sha256"] == (fingerprint if arm == "lora" else None)
        src = sources[case["document"]]
        assert row["messages"] == messages(case, src, arm)
        scores = row["scores"]
        assert len(scores) == 6 and all(math.isfinite(s) for s in scores)
        choice = CODES[max(range(6), key=scores.__getitem__)]
        receipt = execute(choice, src)
        correct_value = reference[case["document"]].get(case["gold"])
        actual[key] = dict(arm=arm, case_id=cid, document=case["document"], split=case["split"],
                           gold=case["gold"], choice=choice, receipt=receipt,
                           passed=choice == case["gold"] and receipt.get("value") == correct_value,
                           unconstrained_correct=row["full_vocab_top"] == 32+CODES.index(case["gold"]))
    assert len(actual) == len(data)*len(ARMS)
    summary = {}
    for split in EVAL:
        summary[split] = {}
        for arm in ARMS:
            rows = [r for r in actual.values() if r["arm"] == arm and r["split"] == split]
            paired = [(r, actual["base", r["case_id"]]) for r in rows]
            summary[split][arm] = dict(n=len(rows), passed=sum(r["passed"] for r in rows),
                unconstrained=sum(r["unconstrained_correct"] for r in rows),
                fixed=[r["case_id"] for r,b in paired if r["passed"] and not b["passed"]],
                lost=[r["case_id"] for r,b in paired if not r["passed"] and b["passed"]])
    held = [c for c in data.values() if c["split"] == "holdout"]
    gate = {}
    for control in ("base", "coached"):
        by_document = {}
        unsafe = []
        for case in held:
            cid = case["case_id"]
            doc = case["document"]
            b = actual[control, cid]
            c = actual["lora", cid]
            by_document[doc] = by_document.get(doc, 0) + int(c["passed"]) - int(b["passed"])
            if case["gold"] in "EF" and b["passed"] and c["choice"] in "ABCD":
                unsafe.append(cid)
        gate[control] = {"net_gain": sum(by_document.values()), "by_document": by_document,
                         "holds_changed_to_compute": unsafe}
    keeps_regression = summary["regression"]["lora"]["passed"] >= summary["regression"]["base"]["passed"]
    eligible = keeps_regression and all(g["net_gain"] >= 2 and min(g["by_document"].values()) >= 0
                                        and not g["holds_changed_to_compute"] for g in gate.values())
    return {"gate_passed": eligible, "gate_by_control": gate, "oracle_retained": keeps_regression,
            "freeze": freeze, "predictions_sha256": sha(folder / "predictions.jsonl"),
            "adapter_sha256": fingerprint, "summary": summary, "rows": list(actual.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "train", "collect", "score"))
    parser.add_argument("--freeze")
    parser.add_argument("--base", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.action == "check":
        check_data()
        return
    frozen(args.freeze)
    sources = read_json(DATA / "sources.json")
    if args.action == "score":
        print(json.dumps(summarize(args.out, sources, args.freeze), indent=2, ensure_ascii=False))
        return
    if not args.base.is_dir() or sha(args.base / WEIGHTS) != BASE_SHA:
        raise ValueError("wrong base snapshot")
    profile = read_json(DATA / "model.json")
    for name, digest in profile["files"].items():
        if sha(args.base / name) != digest:
            raise ValueError(f"mismatched model file {name}")
    if runtime() != profile["runtime"]:
        raise ValueError("training or inference runtime differs from freeze")
    if args.action == "train":
        args.out.mkdir(parents=True, exist_ok=False)
        train(args.base, sources, args.out, args.freeze)
    else:
        collect(args.base, args.out, sources, args.freeze)


if __name__ == "__main__":
    main()
