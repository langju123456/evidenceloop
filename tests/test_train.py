"""The training script's pure parts: the loss mask, the step plan, the learning-rate schedule."""
import json

import pytest

from evidenceloop.data.build import build_training_set
from evidenceloop.data.export import EOS, expand, to_format
from evidenceloop.train.sft import build_example, lr_factor, plan_windows, prepare, steps_for


def _qwen_like(messages, tools, add_generation_prompt, buggy=False):
    out = "<|im_start|>system\n" + messages[0]["content"] + "\n# Tools\n" + json.dumps(tools, ensure_ascii=False) + EOS + "\n"
    last = len(messages) - 1
    for i, m in enumerate(messages[1:], start=1):
        if m["role"] == "user":
            out += "<|im_start|>user\n" + m["content"] + EOS + "\n"
        elif m["role"] == "tool":
            out += "<|im_start|>user\n<tool_response>\n" + m["content"] + "\n</tool_response>" + EOS + "\n"
        else:
            think = "<think>\n\n</think>\n\n" if (i == last and not buggy) else ""
            calls = "".join("<tool_call>\n" + json.dumps({"name": c["function"]["name"], "arguments": c["function"]["arguments"]},
                                                         ensure_ascii=False) + "\n</tool_call>" for c in m.get("tool_calls") or [])
            out += "<|im_start|>assistant\n" + think + (m.get("content") or "") + calls + EOS + "\n"
    if add_generation_prompt:
        out += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    return out


class CharTokenizer:
    """One token per character; enough to check where the mask falls."""

    chat_template = "stub"

    def __init__(self, buggy=False):
        self.buggy = buggy

    def apply_chat_template(self, messages, tools=None, add_generation_prompt=False, enable_thinking=True, tokenize=False):
        return _qwen_like(messages, tools, add_generation_prompt, buggy=self.buggy)

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}


@pytest.fixture(scope="module")
def samples():
    records = build_training_set("uniform", 5, 2)["records"]
    return [to_format(s, "trl") for r in records for s in expand(r)]


def test_only_the_next_assistant_message_is_supervised(samples):
    for sample in samples:
        example, reason = build_example(CharTokenizer(), sample, max_len=10**7)
        assert reason is None
        n = example["n_prompt"]
        assert example["labels"][:n] == [-100] * n
        target = "".join(chr(i) for i in example["input_ids"][n:])
        assert example["labels"][n:] == example["input_ids"][n:] and example["n_supervised"] == len(target)
        assert target.endswith(EOS) and target.count(EOS) == 1, "cut right after <|im_end|>"
        assert "<|im_start|>" not in target and "<tool_response>" not in target
        expected = sample["completion"][0]
        if expected.get("tool_calls"):
            assert expected["tool_calls"][0]["function"]["name"] in target


def test_long_samples_are_skipped_and_broken_templates_stop_the_run(samples):
    example, reason = build_example(CharTokenizer(), samples[0], max_len=10)
    assert example is None and reason == "too_long"
    examples, skipped = prepare(CharTokenizer(), samples, max_len=10)
    assert not examples and skipped["too_long"] == len(samples)
    with pytest.raises(RuntimeError):
        prepare(CharTokenizer(buggy=True), samples, max_len=10**7)


def test_each_epoch_sees_every_sample_once():
    windows = plan_windows(10, epochs=2, grad_accum=4, seed=0)
    assert [len(w) for w in windows] == [4, 4, 4, 4, 4]
    flat = [i for w in windows for i in w]
    assert sorted(flat[:10]) == list(range(10)) and sorted(flat[10:]) == list(range(10))
    assert plan_windows(10, 2, 4, seed=0) == windows and plan_windows(10, 2, 4, seed=1) != windows
    assert len(plan_windows(10, 2, 4, seed=0, max_steps=2)) == 2
    assert steps_for(10, 2, 4) == 5


def test_learning_rate_warms_up_then_decays_to_near_zero():
    factors = [lr_factor(s, 20, 5) for s in range(20)]
    assert factors[:5] == [0.2, 0.4, 0.6, 0.8, 1.0]
    assert all(a >= b for a, b in zip(factors[4:], factors[5:]))
    assert 0 < factors[-1] < 0.1
    assert lr_factor(0, 1, 5) > 0
