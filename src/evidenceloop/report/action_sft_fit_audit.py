"""Offline erratum audit for D26 raw first responses.

The frozen D26 runner wrote ``choice_action`` by interpreting every letter as
the canonical menu.  That metadata is wrong for rotated rows.  This module
never edits the frozen probe, its raw responses, or its protocol; it derives a
separate semantic view from each stored letter and verifies all score-derived
fields that can be recomputed from the raw six-action logits.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from evidenceloop.report import action_sft as d22
from evidenceloop.report import action_sft_fit_probe as d26
from evidenceloop.report import action_sft_menu_aug as d25

ROOT = d22.ROOT
SOURCE = ROOT / "reports/report-lab/action-sft-fit-v1"
SOURCE_FREEZE = SOURCE / "freeze.json"
SOURCE_ROWS = SOURCE / "predictions.jsonl"


def action_for(menu_id: str, code: str) -> str:
    """Decode a letter through the selected menu, not the canonical menu."""
    matches = [action for action in d25.ACTION_BY_CODE.values() if d25.code_for(menu_id, action) == code]
    if len(matches) != 1:
        raise ValueError("cannot decode menu-specific action")
    return matches[0]


def audit_payload(rows: list[dict[str, Any]], freeze: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected = {(cell["case_id"], cell["menu_id"], arm): cell for cell in freeze["matrix"] for arm in d26.ARMS}
    seen: set[tuple[str, str, str]] = set()
    corrected = []
    stale_semantic_rows = []
    by_arm = {arm: 0 for arm in d26.ARMS}
    for raw in rows:
        key = (raw.get("case_id"), raw.get("menu_id"), raw.get("arm"))
        cell = expected.get(key)
        if cell is None or key in seen:
            raise ValueError("unexpected or duplicate raw D26 row")
        seen.add(key)
        scores = raw.get("scores")
        if not isinstance(scores, list) or len(scores) != 6 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in scores):
            raise ValueError("raw D26 action logits are invalid")
        if raw.get("attempt") != 1 or raw.get("freeze") != d22.sha(SOURCE_FREEZE):
            raise ValueError("raw D26 first-response receipt is invalid")
        if raw.get("base_sha256") != d22.BASE_SHA or raw.get("adapter_sha256") != d26._adapter_sha(key[2]):
            raise ValueError("raw D26 fingerprint mismatch")
        if not isinstance(raw.get("input_tokens"), int) or not 0 < raw["input_tokens"] <= 512:
            raise ValueError("raw D26 input budget is invalid")
        choice = d22.CODES[max(range(6), key=scores.__getitem__)]
        if raw.get("choice") != choice:
            raise ValueError("raw D26 choice does not match stored logits")
        target = d22.CODES.index(cell["gold_code"])
        derived_margin = scores[target] - max(value for index, value in enumerate(scores) if index != target)
        if not math.isclose(float(raw.get("target_margin_vs_other_actions")), derived_margin, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("raw D26 target margin does not match stored logits")
        derived_correct = choice == cell["gold_code"]
        if raw.get("restricted_correct") is not derived_correct:
            raise ValueError("raw D26 correctness flag does not match stored logits")
        semantic_choice = action_for(key[1], choice)
        prior_semantic = raw.get("choice_action")
        if prior_semantic != semantic_choice:
            stale_semantic_rows.append({"case_id": key[0], "menu_id": key[1], "arm": key[2],
                                        "stored_choice_action": prior_semantic,
                                        "derived_choice_action": semantic_choice})
        corrected.append({"case_id": key[0], "menu_id": key[1], "arm": key[2], "attempt": 1,
                          "gold_action": cell["gold_action"], "gold_code": cell["gold_code"],
                          "choice": choice, "choice_action": semantic_choice,
                          "restricted_correct": derived_correct,
                          "target_margin_vs_other_actions": derived_margin})
        by_arm[key[2]] += int(derived_correct)
    if set(seen) != set(expected) or len(seen) != 192:
        raise ValueError("raw D26 matrix is incomplete")
    return corrected, {
        "schema": "action-sft-terminal-fit-audit/1",
        "source_predictions_sha256": d22.sha(SOURCE_ROWS),
        "source_freeze_sha256": d22.sha(SOURCE_FREEZE),
        "rows": len(corrected),
        "derived_restricted_correct_by_arm": by_arm,
        "stale_choice_action_rows": stale_semantic_rows,
        "erratum": "Frozen D26 choice_action used canonical decoding on rotated rows. This audit derives semantics from menu_id and preserves raw first responses unchanged.",
        "not_recomputed": "full-vocabulary NLL cannot be reconstructed from archived six-action logits; it is retained only as raw diagnostic metadata.",
    }


def run(out: Path) -> Path:
    if out.exists():
        raise FileExistsError("refusing to overwrite D26 audit output")
    d26.verify_freeze(SOURCE_FREEZE)
    # The original validator checks prompts/gold/fingerprints; this audit then
    # independently derives the fields its scorer previously trusted.
    d26.summarize(SOURCE, SOURCE_FREEZE)
    freeze = d22.read_json(SOURCE_FREEZE)
    rows = [json.loads(line) for line in SOURCE_ROWS.read_text(encoding="utf-8").splitlines()]
    corrected, result = audit_payload(rows, freeze)
    out.mkdir(parents=True)
    with (out / "corrected-semantic-view.jsonl").open("x", encoding="utf-8") as stream:
        for row in corrected:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    d22.write(out / "audit.json", result)
    return out / "audit.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.out))


if __name__ == "__main__":
    main()
