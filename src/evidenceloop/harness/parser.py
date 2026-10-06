"""Strict parser for Qwen/Hermes-style tool calls.

As strict as the reference Hermes parser that serves Qwen in production (vLLM), and no stricter:
  - every call must be valid JSON with a string "name" and an object "arguments" (extra keys ignored)
  - the last call may lack its closing </tool_call>, as when generation stops right after the JSON
No repair of any kind: malformed JSON is a schema_error.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_OPEN, _CLOSE = "<tool_call>", "</tool_call>"
_CLOSED_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)


@dataclass
class ParsedOutput:
    content: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def parse_assistant_output(text: str) -> ParsedOutput:
    visible = _THINK.sub("", text)
    opens, closes = visible.count(_OPEN), visible.count(_CLOSE)
    if closes > opens or opens - closes > 1:
        return ParsedOutput(content=visible.strip(), error="unbalanced <tool_call> tags")
    blocks = _CLOSED_CALL.findall(visible)
    content = _CLOSED_CALL.sub("", visible)
    if opens - closes == 1:  # a final call without its closing tag
        head, _, tail = content.rpartition(_OPEN)
        blocks.append(tail)
        content = head
    calls = []
    for block in blocks:
        try:
            obj = json.loads(block.strip())
        except json.JSONDecodeError as exc:
            return ParsedOutput(content=visible.strip(), error=f"tool_call is not valid JSON: {exc.msg}")
        if not isinstance(obj, dict) or "name" not in obj or "arguments" not in obj:
            return ParsedOutput(content=visible.strip(), error="tool_call must contain name and arguments")
        if not isinstance(obj["name"], str) or not isinstance(obj["arguments"], dict):
            return ParsedOutput(content=visible.strip(), error="name must be a string and arguments an object")
        calls.append({"name": obj["name"], "arguments": obj["arguments"]})
    return ParsedOutput(content=content.strip(), calls=calls)


def format_tool_call(name: str, arguments: dict[str, Any]) -> str:
    return _OPEN + "\n" + json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False) + "\n" + _CLOSE
