"""LoRA DPO (stage 5, D16). Runs on Kaggle's T4; a CPU run with a tiny model works as a smoke test.

  # smoke test: three optimizer steps, nothing kept
  python scripts/train_dpo.py --base runs/W25/merged --data data/stage5/prefs_s1.trl.jsonl --out runs/smoke --max-steps 3

  # P1: preference pairs only, from W25
  python scripts/train_dpo.py --base runs/W25/merged --data data/stage5/prefs_s1.trl.jsonl --seed 1 --out runs/P1

  # CP1: the same pairs, from W25 with C1 merged in
  python scripts/merge_lora.py --train-log runs/C1/train_log.json --out runs/WC1/merged
  python scripts/train_dpo.py --base runs/WC1/merged --data data/stage5/prefs_s1.trl.jsonl --seed 1 --out runs/CP1

The reference model is --base itself: its log-probabilities are computed once, with the new adapter disabled.
The loss, where it is computed and what gets logged are explained in src/evidenceloop/train/dpo.py. The settings
below are the defaults; D16 fixes the ones used for the formal runs.
"""
import argparse
import json

from evidenceloop.train.dpo import DPOConfig, train
from evidenceloop.train.sft import TARGET_MODULES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="a model name or a merged model directory; also the reference model")
    ap.add_argument("--data", required=True, help="preference pairs: one {prompt, chosen, rejected, tools} per line")
    ap.add_argument("--out", required=True)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--target-modules", default=",".join(TARGET_MODULES))
    ap.add_argument("--grad-accum", type=int, default=8, help="pairs per optimizer step (two sequences each)")
    ap.add_argument("--warmup-steps", type=int, default=5)
    ap.add_argument("--max-len", type=int, default=8192, help="pairs with a longer side are skipped and counted")
    ap.add_argument("--max-steps", type=int, default=0, help="stop after this many optimizer steps (smoke test)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-gradient-checkpointing", action="store_true")
    ap.add_argument("--fp32", action="store_true", help="train in fp32 even on a GPU")
    args = ap.parse_args()
    cfg = DPOConfig(
        base=args.base, data=args.data, out=args.out, beta=args.beta, lr=args.lr, epochs=args.epochs, rank=args.rank,
        alpha=args.alpha, dropout=args.dropout, target_modules=args.target_modules.split(","),
        grad_accum=args.grad_accum, warmup_steps=args.warmup_steps, max_len=args.max_len, max_steps=args.max_steps,
        seed=args.seed, gradient_checkpointing=not args.no_gradient_checkpointing, fp32=args.fp32,
    )
    log = train(cfg)
    summary = {k: log.get(k) for k in ("pairs", "skipped", "optimizer_steps", "skipped_steps", "sequences_per_epoch",
                                       "supervised_tokens_per_epoch", "max_sequence_length", "trainable_parameters",
                                       "dtype", "gpu", "peak_memory_gb", "seconds", "adapter_fingerprint")}
    summary["reference"] = {k: v for k, v in log["reference"].items() if k != "logps"}
    summary["first_and_last_loss"] = [log["steps"][0]["loss"], log["steps"][-1]["loss"]]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"adapter: {log['adapter_dir']}")


if __name__ == "__main__":
    main()
