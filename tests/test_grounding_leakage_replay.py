from evidenceloop.common import content_hash
from evidenceloop.harness.loop import run_episodes
from evidenceloop.harness.scripted import ScriptedBackend
from evidenceloop.tasks.generator import OOD_TEMPLATES, generate_split
from evidenceloop.verify.grounding import ungrounded_arguments


def test_reference_trajectories_are_grounded(calibration, ood_pool):
    for pubs in (calibration[0], ood_pool[0]):
        for trace in run_episodes(pubs, ScriptedBackend()):
            assert ungrounded_arguments(trace["messages"]) == []


def test_canary_never_reaches_the_agent(calibration):
    pubs, privs, _ = calibration
    for trace in run_episodes(pubs, ScriptedBackend()):
        canary = privs[trace["task_id"]]["canary"]
        assert all(canary not in (m.get("content") or "") for m in trace["messages"])
        assert canary not in str(trace["events"])


def test_splits_do_not_share_instances_or_ood_templates():
    keys = {}
    for split in ("train_mining", "validation", "test_id", "test_ood"):
        pubs, privs, _ = generate_split(split, 40)
        keys[split] = {p["dedup_key"] for p in privs}
        templates = {p["knobs"]["template"] for p in pubs}
        if split == "test_ood":
            assert templates <= set(OOD_TEMPLATES)
        else:
            assert not templates & set(OOD_TEMPLATES)
    splits = list(keys)
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            assert not keys[a] & keys[b], (a, b)


def test_replay_is_deterministic(calibration):
    pubs = calibration[0][:10]
    first = run_episodes(pubs, ScriptedBackend())
    second = run_episodes(pubs, ScriptedBackend())
    assert [content_hash(t) for t in first] == [content_hash(t) for t in second]
    regenerated, _, _ = generate_split("calibration", 10)
    assert [p["task_id"] for p in regenerated] == [p["task_id"] for p in pubs]
