"""D16 on the CPU with a tiny random model: the DPO loss against numbers worked out by hand and against an
independent computation from the full logits, the reference being the model with its adapter disabled, and a
short training run through scripts/train_dpo.py. Skipped where torch is missing."""
import json
import math
import os
import runpy
import sys

import pytest
from test_train_smoke import _tiny_model  # skips this module too where torch, peft or transformers are missing

import torch  # noqa: E402

from evidenceloop.data import prefs  # noqa: E402
from evidenceloop.data.build import build_training_set  # noqa: E402
from evidenceloop.harness.backends import load_causal_lm, weights_fingerprint  # noqa: E402
from evidenceloop.train import dpo  # noqa: E402
from evidenceloop.train.sft import lora_model  # noqa: E402

LN2 = math.log(2)


def test_loss_equals_hand_computed_values():
    t = lambda v: torch.tensor(float(v), requires_grad=True)  # noqa: E731
    # the policy has not moved from the reference: -log sigmoid(0) = ln 2, whatever the log-probabilities are
    assert dpo.dpo_loss(t(-12.5), t(-3.0), -12.5, -3.0, beta=0.1).item() == pytest.approx(LN2, abs=1e-7)
    # chosen up by 1 nat, rejected down by 1 nat: margin 2, beta 0.5 -> -log sigmoid(1) = ln(1 + 1/e)
    loss = dpo.dpo_loss(t(-2), t(-5), -3.0, -4.0, beta=0.5)
    assert loss.item() == pytest.approx(0.3132616875182229, abs=1e-6)
    # moved the wrong way: chosen down by 2, rejected up by 5: margin -7, beta 0.1 -> ln(1 + e^0.7)
    loss = dpo.dpo_loss(t(-10), t(-4), -8.0, -9.0, beta=0.1)
    assert loss.item() == pytest.approx(1.1031860488854525, abs=1e-6)
    # only the difference between the two movements matters, and beta scales it
    assert dpo.dpo_loss(t(-2), t(-5), -3.0, -4.0, beta=0.5).item() == pytest.approx(
        dpo.dpo_loss(t(-102), t(-55), -103.0, -54.0, beta=0.5).item(), abs=1e-6)
    assert dpo.dpo_loss(t(-2), t(-5), -3.0, -4.0, beta=1.0).item() == pytest.approx(math.log1p(math.exp(-2.0)), abs=1e-6)
    # far out the loss stays finite: ~0 when the margin is large, ~beta * |margin| when it is large the wrong way
    assert dpo.dpo_loss(t(0), t(-9000), 0.0, 0.0, beta=0.1).item() == pytest.approx(0.0, abs=1e-6)
    assert dpo.dpo_loss(t(-9000), t(0), 0.0, 0.0, beta=0.1).item() == pytest.approx(900.0, rel=1e-6)


def test_gradient_raises_chosen_and_lowers_rejected():
    chosen, rejected = torch.tensor(-2.0, requires_grad=True), torch.tensor(-5.0, requires_grad=True)
    beta = 0.5
    dpo.dpo_loss(chosen, rejected, -3.0, -4.0, beta).backward()
    weight = beta / (1 + math.e)  # beta * sigmoid(-beta * margin), with beta * margin = 1
    assert chosen.grad.item() == pytest.approx(-weight, abs=1e-7), "descending the loss raises log pi(chosen)"
    assert rejected.grad.item() == pytest.approx(weight, abs=1e-7), "and lowers log pi(rejected)"


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    d = tmp_path_factory.mktemp("dpo")
    data = build_training_set("uniform", 11, 2)
    orders = {r["task_id"]: r["demo_order"] for r in data["records"]}
    built = prefs.build_pairs(data["tasks"], data["privates"], orders, prefs.ScriptedSource())
    pairs = [prefs.to_trl(p) for p in built["pairs"]]
    path = d / "prefs.trl.jsonl"
    path.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs), encoding="utf-8")
    base = d / "tiny"
    _tiny_model(str(base), [json.dumps(p, ensure_ascii=False) for p in pairs])
    tokenizer = __import__("transformers").AutoTokenizer.from_pretrained(str(base))
    examples, skipped = dpo.prepare_pairs(tokenizer, pairs, max_len=10**6)
    assert len(examples) == len(pairs) and not skipped
    return {"dir": d, "pairs": pairs, "data": path, "base": base, "examples": examples}


def _reply_logp(model, example):
    """log pi(reply | prompt) from the full logits: every position, then only the reply's tokens are summed."""
    ids = torch.tensor([example["input_ids"]])
    with torch.no_grad():
        logp = torch.log_softmax(model(input_ids=ids).logits[0].double(), dim=-1)
    n = example["n_prompt"]
    return sum(logp[t - 1, example["input_ids"][t]].item() for t in range(n, len(example["input_ids"])))


def test_pair_log_probabilities_and_loss_equal_an_independent_computation(tiny):
    model = load_causal_lm(str(tiny["base"]), torch.float32).eval()
    for example in tiny["examples"][:6]:
        with torch.no_grad():
            chosen, rejected = dpo.pair_logps(model, example, "cpu")
        mine = (chosen.item(), rejected.item())
        theirs = (_reply_logp(model, example["chosen"]), _reply_logp(model, example["rejected"]))
        assert mine == pytest.approx(theirs, abs=1e-3)
        # and through the library's own masked loss (a mean over the same tokens)
        for side, value in zip(dpo.SIDES, mine):
            ex = example[side]
            with torch.no_grad():
                library = model(input_ids=torch.tensor([ex["input_ids"]]), labels=torch.tensor([ex["labels"]])).loss
            assert value == pytest.approx(-library.item() * ex["n_supervised"], abs=1e-3)
        ref = (theirs[0] - 1.5, theirs[1] + 0.5)  # a reference that liked chosen less and rejected more
        margin = (theirs[0] - ref[0]) - (theirs[1] - ref[1])
        loss = dpo.dpo_loss(chosen, rejected, ref[0], ref[1], beta=0.1)
        assert loss.item() == pytest.approx(math.log1p(math.exp(-0.1 * margin)), abs=1e-4)
        assert margin == pytest.approx(2.0, abs=1e-9)


def test_the_reference_is_the_model_with_its_adapter_disabled(tiny):
    cfg = dpo.DPOConfig(base=str(tiny["base"]), data=str(tiny["data"]), out="unused", gradient_checkpointing=False)
    torch.manual_seed(0)
    model = lora_model(cfg, "cpu", use_fp16=False)
    plain = load_causal_lm(str(tiny["base"]), torch.float32).eval()
    examples = tiny["examples"][:5]
    base_logps = [(_reply_logp(plain, e["chosen"]), _reply_logp(plain, e["rejected"])) for e in examples]

    flat = lambda rows: [v for row in rows for v in row]  # noqa: E731
    model.train()
    fresh = dpo.reference_logps(model, examples, "cpu")
    assert model.training, "the mode it was in is restored"
    assert flat(fresh) == pytest.approx(flat(base_logps), abs=1e-3)

    # give the adapter something to say: the policy moves, the reference does not
    with torch.no_grad():
        for name, param in model.named_parameters():
            if "lora_B" in name:
                param.add_(0.05 * torch.randn_like(param))
    model.eval()
    causal_lm = model.get_base_model()
    with torch.no_grad():
        policy = [tuple(v.item() for v in dpo.pair_logps(causal_lm, e, "cpu")) for e in examples]
    moved = dpo.reference_logps(model, examples, "cpu")
    assert flat(moved) == pytest.approx(flat(fresh), abs=1e-5), "computed once or again later, the reference is the same"
    assert all(abs(p[0] - r[0]) > 1e-3 for p, r in zip(policy, moved)), "the adapter is on again for the policy"
    with torch.no_grad():
        again = [tuple(v.item() for v in dpo.pair_logps(causal_lm, e, "cpu")) for e in examples]
    assert again == policy


def _mean_loss(model, examples, reference, beta):
    causal_lm = model.get_base_model()
    model.eval()
    with torch.no_grad():
        losses = [dpo.dpo_loss(*dpo.pair_logps(causal_lm, e, "cpu"), r[0], r[1], beta).item() for e, r in zip(examples, reference)]
    return sum(losses) / len(losses)


def test_train_dpo_script_runs_and_moves_toward_chosen(tiny):
    out = tiny["dir"] / "P"
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "train_dpo.py")
    n_pairs = len(tiny["pairs"])
    argv = sys.argv
    sys.argv = ["train_dpo.py", "--base", str(tiny["base"]), "--data", str(tiny["data"]), "--out", str(out), "--seed", "1",
                "--grad-accum", "4", "--lr", "1e-3", "--max-len", "1000000"]
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        sys.argv = argv
    log = json.load(open(out / "train_log.json", encoding="utf-8"))
    assert log["loss"] == "dpo" and log["config"]["beta"] == 0.1 and log["config"]["seed"] == 1
    assert log["pairs"] == log["pairs_in_file"] == n_pairs and log["sequences_per_epoch"] == 2 * n_pairs
    assert log["planned_steps"] == log["optimizer_steps"] == math.ceil(n_pairs / 4) and log["skipped_steps"] == 0
    assert log["steps"][0]["loss"] == pytest.approx(LN2, abs=1e-5), "a fresh adapter has not moved from the reference"
    assert log["steps"][0]["improved"] == 0
    assert all(math.isfinite(s["loss"]) and s["pairs"] <= 4 and s["supervised_tokens"] > 0 for s in log["steps"])
    assert log["base_fingerprint"] == weights_fingerprint(str(tiny["base"])) and log["data_sha256"]
    assert log["adapter_fingerprint"] == weights_fingerprint(log["adapter_dir"])
    assert os.path.exists(os.path.join(log["adapter_dir"], "adapter_config.json"))
    assert log["trainable_parameters"] < log["total_parameters"] and log["git"].keys() == {"commit", "dirty"}

    # the reference in the log is the plain base model's, one (chosen, rejected) per pair
    reference = log["reference"]
    plain = load_causal_lm(str(tiny["base"]), torch.float32).eval()
    assert len(reference["logps"]) == n_pairs
    for example, (chosen, rejected) in list(zip(tiny["examples"], reference["logps"]))[:4]:
        assert (chosen, rejected) == pytest.approx((_reply_logp(plain, example["chosen"]), _reply_logp(plain, example["rejected"])), abs=1e-3)
    assert reference["chosen_more_likely"] == sum(1 for c, r in reference["logps"] if c > r)
    assert reference["mean_logp_chosen"] == pytest.approx(sum(c for c, _ in reference["logps"]) / n_pairs, abs=1e-3)

    # after one pass over the pairs, the adapter prefers chosen over rejected more than the reference does
    from peft import PeftModel

    trained = PeftModel.from_pretrained(load_causal_lm(str(tiny["base"]), torch.float32), log["adapter_dir"])
    after = _mean_loss(trained, tiny["examples"], reference["logps"], beta=0.1)
    assert after < LN2 - 1e-3, after
    with trained.disable_adapter():
        assert _mean_loss(trained, tiny["examples"], reference["logps"], beta=0.1) == pytest.approx(LN2, abs=1e-4)


def test_a_run_that_has_to_stop_keeps_its_log(tiny, monkeypatch):
    out = tiny["dir"] / "stopped"
    cfg = dpo.DPOConfig(base=str(tiny["base"]), data=str(tiny["data"]), out=str(out), grad_accum=4, max_steps=2, max_len=10**6)
    real = dpo.pair_logps
    calls = {"n": 0}

    def overflow_after_reference(*args, **kwargs):
        calls["n"] += 1
        chosen, rejected = real(*args, **kwargs)
        return (chosen * float("inf"), rejected) if calls["n"] > len(tiny["examples"]) else (chosen, rejected)

    monkeypatch.setattr(dpo, "pair_logps", overflow_after_reference)
    with pytest.raises(RuntimeError):
        dpo.train(cfg)
    log = json.load(open(out / "train_log.json", encoding="utf-8"))
    assert "loss" in log["aborted"] and log["optimizer_steps"] == 0 and log["planned_steps"] == 2
    assert len(log["reference"]["logps"]) == len(tiny["examples"]), "the reference pass is kept"
    assert not (out / "adapter").exists(), "no adapter that looks finished"
