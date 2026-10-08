"""Rebuild a merged model from a saved adapter, e.g. W in a new Kaggle session (only the adapter is kept;
the merged model is several GB).

  python scripts/merge_lora.py --train-log runs/W25/train_log.json --out runs/W25/merged

The base model, the adapter directory and the dtype are read from the training log. The new model's
fingerprint is compared with the one recorded when W was first merged: the same means the same weights.
A different one can come from other library versions; evaluations then carry the new fingerprint.
"""
import argparse
import json
import os

from evidenceloop.harness.backends import weights_fingerprint
from evidenceloop.train.sft import merge


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-log", required=True, help="the train_log.json written next to the adapter")
    ap.add_argument("--adapter", help="where the adapter is now, if it moved (default: the path in the log)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.train_log, encoding="utf-8") as fh:
        log = json.load(fh)
    adapter = args.adapter or log["adapter_dir"]
    if not os.path.isdir(adapter):
        raise SystemExit(f"找不到 adapter 目录 {adapter}（用 --adapter 指定）")
    if weights_fingerprint(adapter) != log["adapter_fingerprint"]:
        raise SystemExit(f"{adapter} 和训练日志里记的 adapter 不是同一个")
    base = log["config"]["base"]
    if log.get("base_fingerprint") and weights_fingerprint(base) != log["base_fingerprint"]:
        raise SystemExit(f"{base} 不是训练这个 adapter 时用的那份基座（例如 W 被重新合并过），不能合并")

    import torch

    merge(base, adapter, args.out, torch.float16 if log["dtype"] == "float16" else torch.float32)
    fingerprint = weights_fingerprint(args.out)
    expected = log.get("merged_fingerprint")
    print(f"merged model: {args.out}  fingerprint {fingerprint}")
    if expected and fingerprint == expected:
        print("和训练时合并出的模型一致")
    elif expected:
        print(f"注意：训练时合并出的是 {expected}，这次不同（多半是库的版本变了）。之后的轨迹记录里会是这次的指纹。")


if __name__ == "__main__":
    main()
