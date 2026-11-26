import pytest

from evidenceloop.tasks.generator import generate_split


@pytest.fixture(scope="session")
def calibration():
    pubs, privs, rejects = generate_split("calibration", 30)
    return pubs, {p["task_id"]: p for p in privs}, rejects


@pytest.fixture(scope="session")
def validation_pool():
    pubs, privs, _ = generate_split("validation", 60)
    return pubs, {p["task_id"]: p for p in privs}


@pytest.fixture(scope="session")
def ood_pool():
    pubs, privs, rejects = generate_split("test_ood", 60)
    return pubs, {p["task_id"]: p for p in privs}, rejects


@pytest.fixture(scope="session")
def judge_runs(tmp_path_factory, validation_pool):
    """Run directories shaped like the Mac's runs/, built with the scripted solver. Three stand in for real
    models with a known way of replying; one stays a mock run. Used by the judge-calibration tests."""
    import json

    from evidenceloop.harness.loop import run_episodes
    from evidenceloop.harness.scripted import ScriptedBackend
    from evidenceloop.verify.verifier import evaluate

    pubs, privs = validation_pool
    root = tmp_path_factory.mktemp("judge") / "runs"
    variants = {"validation_qwen3-4b": (None, "Qwen/Qwen3-4B"),             # saves and says so
                "validation_qwen3-0.6b": ("no_save_claim", "Qwen/Qwen3-0.6B"),  # says saved, never saved
                "validation_qwen3-1.7b": ("publish", "Qwen/Qwen3-1.7B"),       # says not published, published
                "scripted_check": (None, None)}
    for name, (corruption, model) in variants.items():
        traces = run_episodes(pubs[:30], ScriptedBackend(corruption=corruption))
        for index, trace in enumerate(traces):
            if model:
                trace["execution_mode"] = "real_model"
                trace["backend"] = {"backend": "mlx", "model": model, "execution_mode": "real_model"}
            if model == "Qwen/Qwen3-4B" and index % 3 == 0:
                trace["final_message"] = '{"unit": "V"}'  # the draft exists, the reply never says so
            if model == "Qwen/Qwen3-4B" and index == 1:
                trace.update(final_message=None, termination="budget_exhausted")
            if model == "Qwen/Qwen3-4B" and index == 2:
                trace["termination"] = "infra_error"
        (root / name).mkdir(parents=True)
        for file, rows in (("traces.jsonl", traces), ("evals.jsonl", [evaluate(t, privs[t["task_id"]]) for t in traces])):
            (root / name / file).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return root
