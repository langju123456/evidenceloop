"""Run the frozen 72-cell diagnostic locally, once, without retraining.

Only each cell's messages reach the model. As in D22, the first-token decision
is constrained to the six legal action letters; full-vocabulary argmax is also
archived. No generated rationale or free-form tool arguments are evaluated.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from evidenceloop.report.action_sft import runtime, sha
from evidenceloop.report.action_sft_position import ARCHIVE


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol-version", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    if args.protocol_version == "v2":
        from evidenceloop.report.action_sft_position_v2 import manifest, score
    else:
        from evidenceloop.report.action_sft_position import manifest, score
    frozen = json.loads((args.out / "manifest.json").read_text())
    if frozen != manifest():
        raise ValueError("source or protocol changed after freeze")
    adapter = ARCHIVE / "adapter"
    if sha(args.base / "model.safetensors") != frozen["base_sha256"]:
        raise ValueError("base weights mismatch")
    if sha(adapter / "adapters.safetensors") != frozen["archived_adapter_sha256"]:
        raise ValueError("adapter weights mismatch")
    output = args.out / "responses.jsonl"
    if output.exists():
        raise FileExistsError("first responses already exist; never overwrite or silently retry")
    import mlx.core as mx
    from mlx_lm import load

    records = []
    started = time.monotonic()
    with output.open("x") as stream:
        for arm in frozen["protocol"]["arms"]:
            model, tokenizer = load(str(args.base), adapter_path=str(adapter) if arm == "lora" else None)
            model.eval()
            code_tokens = [tokenizer.encode(c, add_special_tokens=False) for c in "ABCDEF"]
            if code_tokens != [[n] for n in range(32, 38)]:
                raise ValueError("unexpected action-letter token mapping")
            for cell in frozen["matrix"]:
                if cell["arm"] != arm:
                    continue
                ids = tokenizer.apply_chat_template(cell["messages"], tokenize=True,
                    add_generation_prompt=True, enable_thinking=False, return_dict=False)
                if not 0 < len(ids) <= 512:
                    raise ValueError("input exceeds original D22 budget")
                before = time.monotonic()
                logits = model(mx.array([ids]))[0, -1].astype(mx.float32)
                scores = logits[mx.array([t[0] for t in code_tokens])].tolist()
                if not all(math.isfinite(x) for x in scores):
                    raise ValueError("nonfinite logits")
                full = int(mx.argmax(logits).item())
                record = {key: cell[key] for key in ("case_id", "menu_id", "arm")}
                record.update(attempt=1, answer="ABCDEF"[max(range(6), key=scores.__getitem__)],
                    scores=scores, full_vocab_top=full, input_tokens=len(ids),
                    messages=cell["messages"], manifest_sha256=sha(args.out / "manifest.json"),
                    seconds=round(time.monotonic() - before, 4))
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                records.append(record)
            del model, tokenizer
            mx.clear_cache()
            print(f"{arm}: archived {len(records)} total first responses", flush=True)
    result = score(records, frozen)
    result.update(environment=runtime(), seconds=round(time.monotonic() - started, 4),
        responses_sha256=sha(output), runner_sha256=sha(Path(__file__)),
        decoding="argmax over A-F first-token logits, same as D22; no free-form generation")
    with (args.out / "results.json").open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("n", "totals", "paired", "seconds")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
