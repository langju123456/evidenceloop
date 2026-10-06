"""Every identifier an agent passes to a tool must already appear in what it has seen.

Context = system prompt + user prompt + earlier tool observations. The agent's own earlier text does
not count: a value it invented and then used is still invented.

Version strings like "v2" are ambiguous across resources, so a version is grounded only if it is
known for that resource: mentioned next to the resource id in the prompt, or returned by a tool
for that resource.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

_ID_NEAR_VERSION = re.compile(r"((?:ds|pr)_[a-z]+_\d+)\D{0,12}?(v\d+)")
_PLAIN_IDS = ("resource_id", "dataset_id", "protocol_id", "table_ref", "draft_id")


def _identifiers(args: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    """(argument, value, resource the value must belong to or None)."""
    found: list[tuple[str, str, str | None]] = []
    for key in _PLAIN_IDS:
        if isinstance(args.get(key), str):
            found.append((key, args[key], None))
    if isinstance(args.get("version"), str):
        resource = args.get("dataset_id") or args.get("protocol_id") or args.get("resource_id")
        found.append(("version", args["version"], resource if isinstance(resource, str) else None))
    report = args.get("report")
    if isinstance(report, dict):
        for part in ("dataset", "protocol"):
            ref = report.get(part)
            if isinstance(ref, dict) and isinstance(ref.get("id"), str):
                found.append((f"report.{part}.id", ref["id"], None))
                if isinstance(ref.get("version"), str):
                    found.append((f"report.{part}.version", ref["version"], ref["id"]))
    return found


def _learn(text: str, known: dict[str, set[str]]) -> None:
    for resource, version in _ID_NEAR_VERSION.findall(text):
        known[resource].add(version)
    try:
        obs = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(obs, dict):
        return
    if isinstance(obs.get("resource_id"), str) and isinstance(obs.get("versions"), list):
        known[obs["resource_id"]].update(v["version"] for v in obs["versions"] if isinstance(v, dict) and "version" in v)
    for key in ("dataset_id", "protocol_id"):
        if isinstance(obs.get(key), str) and isinstance(obs.get("version"), str):
            known[obs[key]].add(obs["version"])


def ungrounded_arguments(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    context, known, violations = "", defaultdict(set), []
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            for call in message.get("tool_calls", []):
                fn = call["function"]
                args = fn["arguments"] if isinstance(fn["arguments"], dict) else {}
                for key, value, resource in _identifiers(args):
                    grounded = value in known[resource] if resource is not None else value in context
                    if not grounded:
                        violations.append({"message_index": index, "tool": fn["name"], "argument": key, "value": value})
        else:
            text = message.get("content") or ""
            context += "\n" + text
            _learn(text, known)
    return violations
