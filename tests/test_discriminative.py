from evidenceloop.oracle.oracle import non_discriminative_paths, solve


def test_every_accepted_task_separates_all_error_paths(calibration, ood_pool):
    for privs in (calibration[1], ood_pool[1]):
        for private in privs.values():
            assert not non_discriminative_paths(solve(private))
            assert private["error_paths"], "a task with no wrong paths tests nothing"


def test_error_paths_cover_the_knobs(ood_pool):
    pubs, privs, _ = ood_pool
    kinds = {path.split(":")[0] for p in privs.values() for path in p["error_paths"]}
    assert {"E1", "E2", "E3", "E4", "E5", "E6", "E7"} <= kinds
