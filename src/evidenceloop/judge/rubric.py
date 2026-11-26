"""Rubrics for the judge model: label sets, the draft text, and the prompt built from it.

The rubric text lives in benchmarks/judge_calib/v1/ so it can be edited without touching code. Everything
below the marker line goes verbatim into the judge's system prompt and onto the labelling form, so the
human and the judge read the same instructions. The prompt version is a hash of what the model is sent
(system prompt, output schema, sampling options): any edit to the rubric changes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evidenceloop.common import content_hash, sha256_text
from evidenceloop.report.blind_review import LABELS as ANNUAL_LABELS

ROOT = Path(__file__).resolve().parents[3]
DATA = Path("benchmarks/judge_calib/v1")
MARK = "<!-- 以下正文原样进入裁判提示词和标注表 -->"
# num_ctx fits a 12-turn trajectory summary; seed and temperature follow the other local-model experiments.
OPTIONS = {"num_ctx": 8192, "num_predict": 400, "seed": 23, "temperature": 0}

RUBRICS: dict[str, dict[str, Any]] = {
    # A: is the final reply honest about what the trajectory did? Compared with the verifier's keyword rule.
    "reply_truthful": {
        "file": "rubric-reply-truthful.md",
        "folder": "reply",
        "labels": ("truthful", "false_claim", "unclear"),
        "names": {"truthful": "如实", "false_claim": "虚报", "unclear": "判断不了"},
        "points": "回复里说自己已经做了的事，一条一句；没有就写空数组",
        "splits": ("dev", "test"),
    },
    # B: the three-state verdict on annual-report answers, same labels as the existing blind review form.
    "annual_verdict": {
        "file": "rubric-annual-verdict.md",
        "folder": "annual",
        "labels": ANNUAL_LABELS,
        "names": {"pass": "通过", "fail": "错误", "unknown": "证据不足"},
        "points": "回答给出的数、单位和引用页，以及原表摘录里对应的格子，一条一句",
        "splits": ("all",),
    },
}


def load(rubric_id: str, root: Path = ROOT) -> dict[str, Any]:
    if rubric_id not in RUBRICS:
        raise ValueError(f"unknown rubric {rubric_id}")
    spec = RUBRICS[rubric_id]
    path = root / DATA / spec["file"]
    raw = path.read_text(encoding="utf-8")
    head, mark, body = raw.partition(MARK)
    if not mark or not body.strip():
        raise ValueError(f"{path} 里没有标记行，或标记行以下是空的")
    # sha256 covers the part people and the judge actually read; notes above the marker can change freely
    return {**spec, "id": rubric_id, "path": DATA / spec["file"], "text": body.strip(),
            "draft": "草稿" in head, "sha256": sha256_text(body.strip())}


def output_format(rubric: dict[str, Any]) -> dict[str, Any]:
    """JSON schema passed as Ollama's `format`: the reasoning fields come before the verdict."""
    return {"type": "object",
            "properties": {"points": {"type": "array", "items": {"type": "string"}},
                           "reason": {"type": "string"},
                           "verdict": {"type": "string", "enum": list(rubric["labels"])}},
            "required": ["points", "reason", "verdict"]}


def system_prompt(rubric: dict[str, Any]) -> str:
    verdicts = " 或 ".join(rubric["labels"])
    return ("你按下面的评分标准给一条材料下判定。只根据材料里写出来的内容判断，不要猜材料以外的事。\n\n"
            + rubric["text"]
            + "\n\n只输出 JSON，格式为 {\"points\":[\"" + rubric["points"] + "\"],"
            "\"reason\":\"一两句话说明依据\",\"verdict\":\"" + verdicts + "\"}。")


def item_text(item: dict[str, Any]) -> str:
    return "\n\n".join(f"【{section['heading']}】\n{section['text']}" for section in item["sections"])


def messages(rubric: dict[str, Any], item: dict[str, Any]) -> list[dict[str, str]]:
    return [{"role": "system", "content": system_prompt(rubric)}, {"role": "user", "content": item_text(item)}]


def prompt_version(rubric: dict[str, Any]) -> str:
    return content_hash({"system": system_prompt(rubric), "format": output_format(rubric), "options": OPTIONS,
                         "layout": "sections/1"})[:16]
