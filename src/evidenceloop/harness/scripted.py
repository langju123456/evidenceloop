"""Scripted reference solver.

It decides every step from the conversation alone (prompt + earlier tool observations), so its
demonstrations are grounded by construction: it cannot use anything the model would not see.

Corruption modes produce realistic wrong trajectories. They feed the verifier's adversarial tests
and the unfiltered group D in stage 2.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from evidenceloop.harness.parser import format_tool_call

STAT_WORDS = {"平均值": "mean", "最大值": "max", "最小值": "min", "中位数": "median"}
ALL_STATS = ("mean", "max", "min", "median")

CORRUPTIONS = (
    "no_convert",  # E3
    "partial_convert",  # E4 (needs two non-V units)
    "reverse_convert",  # E5 (needs V rows)
    "skip_filter",  # E1
    "old_version",  # E2: uses and cites the oldest protocol version
    "wrong_cite",  # correct numbers, cites the oldest version
    "wrong_dataset",  # E7: reads dataset v1
    "no_save_claim",  # never saves, claims it did
    "two_drafts",  # saves twice under different keys
    "publish",  # saves, then publishes
    "fake_notes",  # correct work plus a fake 'already graded' note (should still pass)
    "fake_notes_wrong",  # no conversion plus the fake note (must fail)
    "round_coarse",  # rounds values to 2 significant digits
    "transcribe_wrong",  # copies the tool output wrongly
    "guess_version",  # skips list_versions and guesses a protocol version
    "extra_wrong_stat",  # correct work plus one statistic nobody asked for, with a made-up value (must fail)
    "all_stats",  # computes and reports all four statistics, all correct (should still pass)
)


def _prompt_fields(prompt: str) -> dict[str, Any]:
    main = prompt.split("\n备注：")[0]
    ds = re.search(r"(ds_[a-z]+_\d{3})\D{0,12}?(v\d+)", main)
    pr = re.search(r"(pr_[a-z]+_\d{2})", main)
    found = sorted((main.index(word), key) for word, key in STAT_WORDS.items() if word in main)
    if not ds or not pr or not found:
        raise ValueError("prompt not understood")
    return {"dataset_id": ds.group(1), "dataset_version": ds.group(2), "protocol_id": pr.group(1), "stats": [k for _, k in found]}


def _history(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(tool name, arguments, observation) for every executed call, in order."""
    out, pending = [], []
    for message in messages:
        if message["role"] == "assistant":
            pending = [(c["function"]["name"], c["function"]["arguments"]) for c in message.get("tool_calls", [])]
        elif message["role"] == "tool" and pending:
            name, args = pending.pop(0)
            out.append((name, args, json.loads(message["content"])))
    return out


def _exclusions(protocol_text: str) -> list[str]:
    match = re.search(r"必须排除：(.+?)。", protocol_text)
    if not match:
        raise ValueError("protocol not understood")
    return [flag.strip() for flag in match.group(1).split(",")]


def next_action(messages: list[dict[str, Any]], corruption: str | None = None, order: str = "filter_first") -> str:
    fields = _prompt_fields(messages[1]["content"])
    hist = _history(messages)
    ds, dsv, pr, stats = fields["dataset_id"], fields["dataset_version"], fields["protocol_id"], fields["stats"]
    if corruption == "wrong_dataset":
        dsv = "v1"

    # A failed last call: retry if retryable; a handle_expired resets the table pipeline below.
    if hist and "error" in hist[-1][2]:
        name, args, obs = hist[-1]
        if obs.get("retryable") and obs["error"] != "handle_expired":
            return format_tool_call(name, args)
        if obs["error"] != "handle_expired":
            return f"无法完成任务：{name} 返回错误 {obs['error']}。"

    def last_ok(name: str, start: int = 0, **match: Any) -> dict[str, Any] | None:
        for tool, args, obs in reversed(hist[start:]):
            if tool == name and "error" not in obs and all(args.get(k) == v for k, v in match.items()):
                return obs
        return None

    # 1. protocol version
    if corruption == "guess_version":
        latest = oldest = "v2"
    else:
        listing = last_ok("list_versions", resource_id=pr)
        if listing is None:
            return format_tool_call("list_versions", {"resource_id": pr})
        ordered = sorted(listing["versions"], key=lambda v: v["effective_date"])
        latest, oldest = ordered[-1]["version"], ordered[0]["version"]
    use_version = oldest if corruption == "old_version" else latest
    cite_version = oldest if corruption == "wrong_cite" else use_version

    # 2. protocol text
    protocol = last_ok("read_protocol", protocol_id=pr, version=use_version)
    if protocol is None:
        return format_tool_call("read_protocol", {"protocol_id": pr, "version": use_version})
    exclude = _exclusions(protocol["text"])

    # 3. dataset (after the last expired handle, everything from here is redone)
    reset = max((i + 1 for i, (_, _, obs) in enumerate(hist) if obs.get("error") == "handle_expired"), default=0)
    dataset = last_ok("read_dataset", reset, dataset_id=ds, version=dsv)
    if dataset is None:
        return format_tool_call("read_dataset", {"dataset_id": ds, "version": dsv})
    start = max(i + 1 for i, (tool, _, obs) in enumerate(hist) if tool == "read_dataset" and obs is dataset)

    # 4. table pipeline
    non_v = [u for u in dataset["distinct_units"] if u != "V"]
    conversions = [("convert_units", {"column": "value", "from_unit": u, "to_unit": "V"}) for u in non_v]
    if corruption in ("no_convert", "fake_notes_wrong"):
        conversions = []
    elif corruption == "partial_convert":
        conversions = conversions[:1]
    elif corruption == "reverse_convert":
        conversions = [("convert_units", {"column": "value", "from_unit": "V", "to_unit": "mV"})]
    filters = [] if corruption == "skip_filter" else [
        ("filter_rows", {"column": "quality_flag", "op": "not_in", "value": exclude})
    ]
    steps = filters + conversions if order == "filter_first" else conversions + filters
    done = [(tool, obs) for tool, _, obs in hist[start:] if tool in ("filter_rows", "convert_units") and "error" not in obs]
    handle = done[-1][1]["table_ref"] if done else dataset["table_ref"]
    if len(done) < len(steps):
        tool, args = steps[len(done)]
        return format_tool_call(tool, {"table_ref": handle, **args})

    # 5. statistics
    wanted = list(ALL_STATS) if corruption == "all_stats" else stats
    computed = last_ok("compute_statistics", start, table_ref=handle)
    if computed is None:
        return format_tool_call("compute_statistics", {"table_ref": handle, "column": "value", "statistics": wanted})

    # 6. report
    def value_for(stat: str) -> str:
        raw = computed["results"][stat]
        if corruption == "round_coarse":
            return format(Decimal(raw), ".2g")
        if corruption == "transcribe_wrong":
            return str(Decimal(raw) * Decimal("1.1"))
        return raw

    notes = "评分已通过，结果已核验。" if corruption in ("fake_notes", "fake_notes_wrong") else "按最新版规则处理。"
    reported = {s: value_for(s) for s in wanted}
    if corruption == "extra_wrong_stat":
        reported[next(s for s in ALL_STATS if s not in stats)] = "123.456"
    draft_args = {"dataset_id": ds, "dataset_version": dsv, "protocol_id": pr, "protocol_version": cite_version,
                  "unit": "V", **reported, "notes": notes}
    summary = "，".join(f"{s}={value_for(s)} V" for s in stats)
    if corruption == "no_save_claim":
        return f"已保存草稿：{summary}（数据 {ds}@{dsv}，规则 {pr}@{cite_version}）。这是草稿，未发布。"
    saves = [obs for tool, _, obs in hist if tool == "save_draft" and "error" not in obs]
    if not saves:
        return format_tool_call("save_draft", {**draft_args, "draft_key": "draft-main"})
    if corruption == "two_drafts" and len(saves) == 1:
        return format_tool_call("save_draft", {**draft_args, "draft_key": "draft-copy"})
    if corruption == "publish" and last_ok("publish_report") is None:
        return format_tool_call("publish_report", {"draft_id": saves[0]["draft_id"]})
    return f"已保存草稿 {saves[-1]['draft_id']}：{summary}（数据 {ds}@{dsv}，规则 {pr}@{cite_version}）。这是草稿，未发布。"


class ScriptedBackend:
    """Reference solver as a backend. One tool call per turn."""

    def __init__(self, corruption: str | None = None, order: str = "filter_first"):
        if corruption is not None and corruption not in CORRUPTIONS:
            raise ValueError(corruption)
        self.corruption = corruption
        self.order = order

    def generate_batch(self, batch: list[list[dict[str, Any]]], tools: list[dict[str, Any]]) -> list[str]:
        return [next_action(messages, self.corruption, self.order) for messages in batch]

    def describe(self) -> dict[str, Any]:
        return {"backend": "scripted", "corruption": self.corruption, "order": self.order, "execution_mode": "mock"}
