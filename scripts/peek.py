"""Show what the model actually did, task by task.

  python scripts/peek.py runs/smoke_mlx            # every task, short
  python scripts/peek.py runs/smoke_mlx --full     # plus each raw model output
"""
import json
import os
import sys


def main():
    run_dir = sys.argv[1]
    full = "--full" in sys.argv
    evals = {}
    eval_path = os.path.join(run_dir, "evals.jsonl")
    if os.path.exists(eval_path):
        evals = {e["task_id"]: e for e in map(json.loads, open(eval_path, encoding="utf-8"))}
    for line in open(os.path.join(run_dir, "traces.jsonl"), encoding="utf-8"):
        trace = json.loads(line)
        result = evals.get(trace["task_id"], {})
        verdict = "成功" if result.get("task_success") else (result.get("failure") or {}).get("primary", "?")
        print(f"== {trace['task_id']} | {trace['turns']} 轮 | {trace['termination']} | {verdict}")
        for ev in trace["events"]:
            if ev["kind"] == "tool_call":
                status = ev["observation"].get("error", "ok")
                print(f"   {ev['turn']:>2}. {ev['tool']}({json.dumps(ev['args'], ensure_ascii=False)[:120]}) -> {status}")
            else:
                print(f"   {ev['turn']:>2}. [{ev['kind']}] {ev.get('detail', '')[:120]}")
        print(f"   最终回复：{(trace['final_message'] or '')[:160]}")
        if full:
            for i, raw in enumerate(trace["raw_outputs"], 1):
                print(f"   --- 第 {i} 轮原始输出 ---\n{raw[:1200]}")
        print()


if __name__ == "__main__":
    main()
