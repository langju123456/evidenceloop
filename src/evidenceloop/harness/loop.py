"""Agent loop. Episodes advance in lockstep so a batching backend (vLLM) gets one big batch per turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from evidenceloop.common import ENV_VERSION, content_hash
from evidenceloop.env.tools import Environment, observation_text, tool_schemas
from evidenceloop.harness.parser import parse_assistant_output

DEFAULT_MAX_TURNS = 12


class Backend(Protocol):
    def generate_batch(self, batch: list[list[dict[str, Any]]], tools: list[dict[str, Any]]) -> list[str | None]:
        """One output per conversation; None when the backend could not run that one prompt."""
        ...

    def describe(self) -> dict[str, Any]: ...


@dataclass
class _Episode:
    task: dict[str, Any]
    env: Environment
    messages: list[dict[str, Any]]
    init_snapshot: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)
    raw_outputs: list[str] = field(default_factory=list)
    final_message: str | None = None
    termination: str | None = None
    turns: int = 0


def run_episodes(tasks: list[dict[str, Any]], backend: Backend, max_turns: int = DEFAULT_MAX_TURNS,
                 attempt_seed: int = 0) -> list[dict[str, Any]]:
    tools = tool_schemas()
    described = backend.describe()
    episodes = []
    for task in tasks:
        env = Environment(task, episode_seed=task["seed"] * 1000 + attempt_seed)
        messages = [{"role": "system", "content": task["system_prompt"]}, {"role": "user", "content": task["prompt"]}]
        episodes.append(_Episode(task=task, env=env, messages=messages, init_snapshot=env.snapshot()))

    for turn in range(1, max_turns + 1):
        active = [ep for ep in episodes if ep.termination is None]
        if not active:
            break
        try:
            outputs = backend.generate_batch([ep.messages for ep in active], tools)
        except Exception as exc:  # noqa: BLE001 - any backend failure is an infra_error
            for ep in active:
                ep.termination = "infra_error"
                ep.events.append({"turn": turn, "kind": "infra_error", "detail": repr(exc)})
            break
        for ep, text in zip(active, outputs):
            if text is None:  # this prompt alone could not be run (e.g. out of memory); the others go on
                ep.termination = "infra_error"
                ep.events.append({"turn": turn, "kind": "infra_error", "detail": "backend returned no output"})
                continue
            ep.turns = turn
            ep.raw_outputs.append(text)
            parsed = parse_assistant_output(text)
            if parsed.error:
                ep.messages.append({"role": "assistant", "content": text})
                obs = {"error": "invalid_tool_call", "message": parsed.error}
                ep.messages.append({"role": "tool", "content": observation_text(obs)})
                ep.events.append({"turn": turn, "kind": "parse_error", "detail": parsed.error})
                continue
            if not parsed.calls:
                ep.messages.append({"role": "assistant", "content": parsed.content})
                ep.final_message = parsed.content
                ep.termination = "final_answer"
                continue
            ep.messages.append({
                "role": "assistant",
                "content": parsed.content,
                "tool_calls": [{"type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                               for c in parsed.calls],
            })
            for call in parsed.calls:
                obs = ep.env.call(call["name"], call["arguments"])
                ep.messages.append({"role": "tool", "name": call["name"], "content": observation_text(obs)})
                ep.events.append({"turn": turn, "kind": "tool_call", "tool": call["name"], "args": call["arguments"],
                                  "observation": obs, "status": "error" if "error" in obs else "ok"})

    traces = []
    for ep in episodes:
        traces.append({
            "task_id": ep.task["task_id"],
            "split": ep.task["split"],
            "bucket": ep.task["bucket"],
            "attempt_seed": attempt_seed,
            "env_version": ENV_VERSION,
            "backend": described,
            "inference_config_hash": content_hash({"backend": described, "max_turns": max_turns}),
            "execution_mode": described.get("execution_mode", "real_model"),
            "messages": ep.messages,
            "events": ep.events,
            "raw_outputs": ep.raw_outputs,
            "final_message": ep.final_message,
            "termination": ep.termination or "budget_exhausted",
            "turns": ep.turns,
            "init_snapshot": ep.init_snapshot,
            "final_snapshot": ep.env.snapshot(),
        })
    return traces
