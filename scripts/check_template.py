"""Run on the Mac (or Kaggle) before any training: checks the export against the REAL Qwen3 chat template.

  pip install transformers
  python scripts/check_template.py --records data/sft/C1/records.jsonl
  python scripts/check_template.py --budget data/export/B1.trl.jsonl data/export/C1.trl.jsonl data/export/D1.trl.jsonl

1) Prefix consistency: the rendered history must be a strict prefix of history + target, the target must
   end with <|im_end|>, and no tool observation may fall inside the supervised span.
2) --budget: supervised token counts per group must be within 5% of each other.
"""
import argparse
import json
import sys

from evidenceloop.data.export import check_prefix_consistency, expand


def make_render(tokenizer):
    def render(messages, tools, add_generation_prompt):
        msgs = []
        for m in messages:
            item = {"role": m["role"], "content": m.get("content") or ""}
            if m.get("tool_calls"):
                item["tool_calls"] = m["tool_calls"]
            msgs.append(item)
        return tokenizer.apply_chat_template(msgs, tools=tools, add_generation_prompt=add_generation_prompt,
                                             enable_thinking=False, tokenize=False)
    return render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-0.6B")
    ap.add_argument("--records")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--budget", nargs="+")
    args = ap.parse_args()
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model)
    render = make_render(tok)
    failed = False
    if args.records:
        with open(args.records, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh][: args.n]
        total = bad = 0
        for record in records:
            for sample in expand(record):
                total += 1
                problems = check_prefix_consistency(render, sample)
                if problems:
                    bad += 1
                    if bad <= 5:
                        print(sample["sample_id"], problems)
        print(f"prefix consistency: {total - bad}/{total} samples pass")
        failed |= bad > 0
    if args.budget:
        sizes = {}
        for path in args.budget:
            total_tokens = 0
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    s = json.loads(line)
                    prompt = render(s["prompt"], s["tools"], True)
                    full = render(s["prompt"] + s["completion"], s["tools"], False)
                    total_tokens += len(tok(full[len(prompt):], add_special_tokens=False)["input_ids"])
            sizes[path] = total_tokens
            print(f"{path}: {total_tokens} supervised tokens")
        low, high = min(sizes.values()), max(sizes.values())
        print(f"spread {high / low - 1:.1%} (must be <= 5%)")
        failed |= high > low * 1.05
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
