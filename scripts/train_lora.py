"""LoRA SFT (stage 3). Runs on Kaggle's T4; a CPU run with a tiny model works as a smoke test.

  # smoke test: three optimizer steps, nothing kept
  python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/dose25.trl.jsonl --out runs/smoke --max-steps 3

  # one warm-up dose, then fold the adapter into the base to get W (D11)
  python scripts/train_lora.py --base Qwen/Qwen3-1.7B --data data/warmup/dose25.trl.jsonl \
      --out runs/W25 --merge-out runs/W25/merged

The steps, the loss mask and what gets logged are explained in src/evidenceloop/train/sft.py.
The settings below are the defaults; the ones used for the formal runs are recorded in D12 first.
"""
import argparse
import json

from evidenceloop.train.sft import TARGET_MODULES, TrainConfig, train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="model name or a merged model directory (W)")
    ap.add_argument("--data", required=True, help="an exported .trl.jsonl file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--merge-out", help="also save base + adapter as one model here")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--target-modules", default=",".join(TARGET_MODULES))
    ap.add_argument("--grad-accum", type=int, default=16, help="samples per optimizer step")
    ap.add_argument("--warmup-steps", type=int, default=5)
    ap.add_argument("--max-len", type=int, default=8192, help="longer samples are skipped and counted")
    ap.add_argument("--max-steps", type=int, default=0, help="stop after this many optimizer steps (smoke test)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-gradient-checkpointing", action="store_true")
    ap.add_argument("--fp32", action="store_true", help="train in fp32 even on a GPU")
    args = ap.parse_args()
    cfg = TrainConfig(
        base=args.base, data=args.data, out=args.out, merge_out=args.merge_out, lr=args.lr, epochs=args.epochs,
        rank=args.rank, alpha=args.alpha, dropout=args.dropout, target_modules=args.target_modules.split(","),
        grad_accum=args.grad_accum, warmup_steps=args.warmup_steps, max_len=args.max_len, max_steps=args.max_steps,
        seed=args.seed, gradient_checkpointing=not args.no_gradient_checkpointing, fp32=args.fp32,
    )
    log = train(cfg)
    summary = {k: log.get(k) for k in ("examples", "skipped", "optimizer_steps", "skipped_steps",
                                       "supervised_tokens_per_epoch", "supervised_tokens_trained",
                                       "max_sequence_length", "trainable_parameters", "dtype", "gpu",
                                       "peak_memory_gb", "seconds", "adapter_fingerprint", "merged_fingerprint")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"adapter: {log['adapter_dir']}" + (f"   merged model: {log['merged_to']}" if log.get("merged_to") else ""))


if __name__ == "__main__":
    main()
