"""End-to-end smoke run on the CPU with a tiny random model: train two steps, save the adapter, merge it
into W, then let W play two episodes through the transformers backend. Also: the hand-written loss equals
the library's, the merge really changes the weights, and an out-of-memory micro-batch is split and
retried. Skipped where torch is missing."""
import json
import math
import os

import pytest

try:
    import peft  # noqa: F401
    import tokenizers  # noqa: F401
    import torch
    import transformers

    transformers.Qwen3ForCausalLM  # noqa: B018 - Qwen3 needs transformers >= 4.51
except (ImportError, AttributeError):  # also a broken or too old install, not only a missing one
    pytest.skip("needs torch, peft, tokenizers and transformers >= 4.51", allow_module_level=True)

from evidenceloop.data.build import build_training_set  # noqa: E402
from evidenceloop.data.export import expand, to_format  # noqa: E402
from evidenceloop.harness.backends import HFBackend, load_causal_lm  # noqa: E402
from evidenceloop.harness.loop import run_episodes  # noqa: E402
from evidenceloop.tasks.generator import generate_split  # noqa: E402
from evidenceloop.train.sft import TrainConfig, example_loss, prepare, train  # noqa: E402

TEMPLATE = (
    "{{- '<|im_start|>system\\n' + messages[0]['content'] + '\\n# Tools\\n' + (tools | tojson) + '<|im_end|>\\n' -}}"
    "{%- for m in messages[1:] -%}"
    "{%- if m['role'] == 'user' -%}{{- '<|im_start|>user\\n' + m['content'] + '<|im_end|>\\n' -}}"
    "{%- elif m['role'] == 'tool' -%}"
    "{{- '<|im_start|>user\\n<tool_response>\\n' + m['content'] + '\\n</tool_response><|im_end|>\\n' -}}"
    "{%- else -%}{{- '<|im_start|>assistant\\n' -}}"
    "{%- if loop.last -%}{{- '<think>\\n\\n</think>\\n\\n' -}}{%- endif -%}"
    "{{- m['content'] or '' -}}"
    "{%- for c in m['tool_calls'] or [] -%}"
    "{{- '<tool_call>\\n' + ({'name': c['function']['name'], 'arguments': c['function']['arguments']} | tojson)"
    " + '\\n</tool_call>' -}}"
    "{%- endfor -%}{{- '<|im_end|>\\n' -}}{%- endif -%}"
    "{%- endfor -%}"
    "{%- if add_generation_prompt -%}{{- '<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n' -}}{%- endif -%}"
)


def _tiny_model(path, corpus):
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    tok.train_from_iterator(corpus, trainers.BpeTrainer(
        vocab_size=3000, special_tokens=["<|endoftext|>", "<|im_start|>", "<|im_end|>"],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tok.add_tokens(["<tool_call>", "</tool_call>", "<think>", "</think>", "<tool_response>", "</tool_response>"])
    fast = transformers.PreTrainedTokenizerFast(tokenizer_object=tok, eos_token="<|im_end|>", pad_token="<|endoftext|>")
    fast.chat_template = TEMPLATE
    config = transformers.Qwen3Config(
        vocab_size=len(fast), hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=4,
        num_key_value_heads=2, head_dim=8, max_position_embeddings=32768, tie_word_embeddings=True,
        eos_token_id=fast.eos_token_id, pad_token_id=fast.pad_token_id)
    torch.manual_seed(0)
    transformers.Qwen3ForCausalLM(config).save_pretrained(path)
    fast.save_pretrained(path)


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    d = tmp_path_factory.mktemp("smoke")
    records = build_training_set("uniform", 11, 2)["records"]
    samples = [to_format(s, "trl") for r in records for s in expand(r)]
    data = d / "dose.trl.jsonl"
    data.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in samples), encoding="utf-8")
    base = d / "tiny"
    _tiny_model(str(base), [json.dumps(s, ensure_ascii=False) for s in samples])
    return {"dir": d, "samples": samples, "data": data, "base": base}


def test_hand_written_loss_equals_the_library_loss(tiny):
    tokenizer = transformers.AutoTokenizer.from_pretrained(str(tiny["base"]))
    examples, _ = prepare(tokenizer, tiny["samples"][:4], max_len=10**6)
    model = load_causal_lm(str(tiny["base"]), torch.float32).eval()
    for ex in examples:
        with torch.no_grad():
            mine = example_loss(model, ex, "cpu") / ex["n_supervised"]
            library = model(input_ids=torch.tensor([ex["input_ids"]]), labels=torch.tensor([ex["labels"]])).loss
        assert abs(mine.item() - library.item()) < 1e-5


def test_train_merge_and_play(tiny):
    d, base = tiny["dir"], tiny["base"]
    cfg = TrainConfig(base=str(base), data=str(tiny["data"]), out=str(d / "W"), merge_out=str(d / "W" / "merged"),
                      epochs=1, grad_accum=4, max_steps=2, max_len=10**6)
    log = train(cfg)
    assert log["optimizer_steps"] == 2 and len(log["steps"]) == 2 and log["skipped_steps"] == 0
    assert all(math.isfinite(s["loss"]) and s["supervised_tokens"] > 0 for s in log["steps"])
    assert log["examples"] == len(tiny["samples"]) and log["supervised_tokens_trained"] > 0
    assert log["trainable_parameters"] < log["total_parameters"]
    assert os.path.exists(os.path.join(log["adapter_dir"], "adapter_config.json"))
    saved = json.load(open(d / "W" / "train_log.json", encoding="utf-8"))
    assert saved["data_sha256"] == log["data_sha256"] and saved["merged_fingerprint"] == log["merged_fingerprint"]

    # the merge changed the weights, and W computes what base + adapter computes
    from peft import PeftModel

    plain = load_causal_lm(str(base), torch.float32).eval()
    merged = load_causal_lm(str(d / "W" / "merged"), torch.float32).eval()
    name = "model.layers.0.self_attn.q_proj.weight"
    assert not torch.equal(plain.state_dict()[name], merged.state_dict()[name])
    with_adapter = PeftModel.from_pretrained(load_causal_lm(str(base), torch.float32), log["adapter_dir"]).eval()
    ids = torch.tensor([list(range(5, 45))])
    with torch.no_grad():
        assert torch.allclose(merged(input_ids=ids).logits, with_adapter(input_ids=ids).logits, atol=1e-4)
        assert not torch.allclose(merged(input_ids=ids).logits, plain(input_ids=ids).logits, atol=1e-6)

    tasks = generate_split("validation", 2)[0]
    w = HFBackend(str(d / "W" / "merged"), max_tokens=8, gen_batch=2)
    base_plus_adapter = HFBackend(str(base), adapter_path=log["adapter_dir"], max_tokens=8, gen_batch=1)
    for backend in (w, base_plus_adapter):
        traces = run_episodes(tasks, backend, max_turns=2)
        assert len(traces) == 2 and all(t["raw_outputs"] for t in traces)
        assert backend.describe()["backend"] == "hf"
    # the traces say exactly which weights played: W's fingerprint is the one in its training log
    assert w.describe()["model_fingerprint"] == log["merged_fingerprint"]
    assert base_plus_adapter.describe()["adapter_fingerprint"] == log["adapter_fingerprint"]
    assert "model_fingerprint" in base_plus_adapter.describe()  # the tiny base is a local directory too
    assert saved["git"].keys() == {"commit", "dirty"} and saved["base_fingerprint"] == base_plus_adapter.describe()["model_fingerprint"]
    # one model directory, one spelling: a trailing slash must not look like another model when resuming
    assert HFBackend(str(d / "W" / "merged") + "/", max_tokens=8, gen_batch=2).describe() == w.describe()
    assert w.describe()["gen_batch"] == 2

    # a new session keeps only the adapter: merging it again gives the same W
    import runpy
    import sys

    from evidenceloop.harness.backends import weights_fingerprint

    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "merge_lora.py")
    argv = sys.argv
    sys.argv = ["merge_lora.py", "--train-log", str(d / "W" / "train_log.json"), "--out", str(d / "W2")]
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        sys.argv = argv
    assert weights_fingerprint(str(d / "W2")) == log["merged_fingerprint"]

    # an adapter is only merged onto the base it was trained on
    wrong = dict(saved, base_fingerprint="0" * 16)
    (d / "W" / "wrong_log.json").write_text(json.dumps(wrong), encoding="utf-8")
    sys.argv = ["merge_lora.py", "--train-log", str(d / "W" / "wrong_log.json"), "--out", str(d / "W3")]
    try:
        with pytest.raises(SystemExit):
            runpy.run_path(script, run_name="__main__")
    finally:
        sys.argv = argv
    assert not (d / "W3").exists()


def test_a_run_that_has_to_stop_keeps_its_log(tiny, monkeypatch):
    import evidenceloop.train.sft as sft

    monkeypatch.setattr(sft, "example_loss", lambda *a, **k: torch.tensor(float("inf"), requires_grad=True))
    out = tiny["dir"] / "stopped"
    with pytest.raises(RuntimeError):
        train(TrainConfig(base=str(tiny["base"]), data=str(tiny["data"]), out=str(out), epochs=1, grad_accum=4,
                          max_steps=2, max_len=10**6))
    log = json.load(open(out / "train_log.json", encoding="utf-8"))
    assert "loss" in log["aborted"] and log["optimizer_steps"] == 0 and log["planned_steps"] == 2
    assert not (out / "adapter").exists(), "no adapter that looks finished"


def test_an_out_of_memory_micro_batch_is_split_and_retried(tiny):
    class FakeOOM(Exception):
        pass

    backend = HFBackend(str(tiny["base"]), max_tokens=4, gen_batch=4)
    calls = []

    def generate(prompts):
        calls.append(len(prompts))
        if len(prompts) > 1:
            raise FakeOOM()
        return [f"out:{prompts[0].count('Q')}"]

    backend._oom, backend._generate = FakeOOM, generate
    batch = [[{"role": "system", "content": "s"}, {"role": "user", "content": "Q" * k}] for k in (3, 1, 2)]
    assert backend.generate_batch(batch, tools=[]) == ["out:3", "out:1", "out:2"], "each answer back in its place"
    assert calls == [3, 1, 2, 1, 1] and backend.oom_splits == 2

    def always(prompts):
        raise FakeOOM()

    backend._generate = always
    assert backend.generate_batch(batch[:1], tools=[]) == [None], "even alone it does not fit"
    assert backend.oom_failures == 1

    # in an episode, only the conversation that did not fit ends as infra_error; the others go on
    def only_short(prompts):
        if len(prompts) > 1:
            raise FakeOOM()
        if len(prompts[0]) > shortest:
            raise FakeOOM()
        return ['<tool_call>\n{"name": "list_datasets", "arguments": {}}\n</tool_call>']

    from evidenceloop.env.tools import tool_schemas
    from evidenceloop.harness.backends import render_prompt

    tasks = generate_split("validation", 2)[0]
    tasks[1] = dict(tasks[1], system_prompt=tasks[0]["system_prompt"], prompt=tasks[0]["prompt"] + " " + "Q" * 50)
    shortest = len(render_prompt(backend.tokenizer, [{"role": "system", "content": tasks[0]["system_prompt"]},
                                                     {"role": "user", "content": tasks[0]["prompt"]}], tool_schemas()))
    backend._generate = only_short
    traces = run_episodes(tasks, backend, max_turns=1)
    assert [t["termination"] for t in traces] == ["budget_exhausted", "infra_error"]
    assert traces[0]["events"][0]["kind"] == "tool_call"
