"""D16, the DPO trainer's pure parts: which tokens a pair's two log-probabilities are summed over, and the step plan."""
import dataclasses

import pytest
from test_train import CharTokenizer

from evidenceloop.data import prefs
from evidenceloop.data.build import build_training_set
from evidenceloop.data.export import EOS
from evidenceloop.train.dpo import DPOConfig, build_pair, prepare_pairs
from evidenceloop.train.sft import TrainConfig, plan_windows, steps_for


@pytest.fixture(scope="module")
def pairs():
    data = build_training_set("uniform", 5, 2)
    orders = {r["task_id"]: r["demo_order"] for r in data["records"]}
    built = prefs.build_pairs(data["tasks"], data["privates"], orders, prefs.ScriptedSource())
    return [prefs.to_trl(p) for p in built["pairs"]]


def _text(ids):
    return "".join(chr(i) for i in ids)


def test_both_sides_share_the_prompt_and_only_the_reply_is_counted(pairs):
    assert pairs
    for pair in pairs:
        example, reason = build_pair(CharTokenizer(), pair, max_len=10**7)
        assert reason is None
        chosen, rejected = example["chosen"], example["rejected"]
        n = chosen["n_prompt"]
        assert rejected["n_prompt"] == n and chosen["input_ids"][:n] == rejected["input_ids"][:n], "one prompt, two replies"
        assert chosen["input_ids"][n:] != rejected["input_ids"][n:]
        for side, message in ((chosen, pair["chosen"][0]), (rejected, pair["rejected"][0])):
            assert side["labels"][:n] == [-100] * n and side["labels"][n:] == side["input_ids"][n:]
            reply = _text(side["input_ids"][n:])
            assert side["n_supervised"] == len(reply)
            assert reply.endswith(EOS) and reply.count(EOS) == 1, "cut right after <|im_end|>"
            assert "<|im_start|>" not in reply and "<tool_response>" not in reply, "no history, no tool observation"
            if message.get("tool_calls"):
                assert message["tool_calls"][0]["function"]["name"] in reply
            else:
                assert message["content"] in reply
        # the prompt is rendered as at inference: it ends with the generation prompt, thinking off
        assert _text(chosen["input_ids"][:n]).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_long_pairs_are_skipped_and_broken_templates_stop_the_run(pairs):
    example, reason = build_pair(CharTokenizer(), pairs[0], max_len=10)
    assert example is None and reason == "too_long"
    examples, skipped = prepare_pairs(CharTokenizer(), pairs, max_len=10)
    assert not examples and skipped["too_long"] == len(pairs)
    with pytest.raises(RuntimeError):
        prepare_pairs(CharTokenizer(buggy=True), pairs, max_len=10**7)


def test_the_settings_are_sfts_except_what_d16_changes():
    dpo = dataclasses.asdict(DPOConfig(base="b", data="d", out="o"))
    sft = dataclasses.asdict(TrainConfig(base="b", data="d", out="o"))
    assert dpo["beta"] == 0.1 and dpo["epochs"] == 1 and dpo["grad_accum"] == 8
    for key in set(dpo) & set(sft) - {"epochs", "grad_accum"}:
        assert dpo[key] == sft[key], key
    assert set(dpo) - set(sft) == {"beta"} and set(sft) - set(dpo) == {"merge_out"}


def test_d16_step_counts_match_c():
    """Half of C's samples as pairs, 8 pairs per step: as many sequences per step and as many steps as C (D14)."""
    for c_samples, c_steps in ((814, 51), (818, 52), (815, 51)):
        n_pairs = c_samples // 2
        windows = plan_windows(n_pairs, epochs=1, grad_accum=8, seed=1)
        assert len(windows) == c_steps == steps_for(c_samples, 1, 16) == steps_for(n_pairs, 1, 8)
        assert sorted(i for w in windows for i in w) == list(range(n_pairs))
