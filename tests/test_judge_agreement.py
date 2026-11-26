"""The agreement statistics on hand-worked numbers."""
import pytest

from evidenceloop.judge import agreement


def _pairs(table):
    return [(a, b) for (a, b), count in table.items() for _ in range(count)]


def test_kappa_matches_a_hand_worked_table():
    # 50 items: observed 35/50 = 0.7; chance = (25*30 + 25*20) / 2500 = 0.5; kappa = 0.4
    pairs = _pairs({("yes", "yes"): 20, ("yes", "no"): 5, ("no", "yes"): 10, ("no", "no"): 15})
    observed, kappa = agreement.cohen_kappa(pairs)
    assert observed == pytest.approx(0.7) and kappa == pytest.approx(0.4)
    assert agreement.confusion(pairs, ("yes", "no"), ("yes", "no")) == {"yes": {"yes": 20, "no": 5}, "no": {"yes": 10, "no": 15}}
    assert agreement.cohen_kappa([("a", "a"), ("b", "b"), ("c", "c")])[1] == pytest.approx(1.0)
    assert agreement.cohen_kappa([("a", "b"), ("b", "a")])[1] == pytest.approx(-1.0)
    assert agreement.cohen_kappa([("a", "a")] * 4) == (1.0, None), "one label on both sides: chance agreement is 1"


def test_mcnemar_exact_matches_binomial_tails():
    assert agreement.mcnemar_exact(1, 9) == pytest.approx(2 * (1 + 10) / 1024)
    assert agreement.mcnemar_exact(9, 1) == agreement.mcnemar_exact(1, 9)
    assert agreement.mcnemar_exact(0, 6) == pytest.approx(2 / 64)
    assert agreement.mcnemar_exact(4, 4) == 1.0 and agreement.mcnemar_exact(0, 0) == 1.0


def test_interval_resamples_whole_clusters_with_a_fixed_seed():
    human = {f"i{n}": "yes" if n % 2 else "no" for n in range(40)}
    other = {k: ("no" if k in ("i1", "i3", "i5", "i8") else v) for k, v in human.items()}
    clusters = {k: f"task{int(k[1:]) // 2}" for k in human}  # 20 clusters of two items
    first = agreement.compare(human, other, clusters, ("yes", "no"), ("yes", "no"), resamples=400)
    assert first == agreement.compare(human, other, clusters, ("yes", "no"), ("yes", "no"), resamples=400)
    interval = first["kappa_interval"]
    assert first["n"] == 40 and interval["clusters"] == 20 and interval["resamples"] == 400
    assert interval["low"] < first["kappa"] < interval["high"] <= 1
    few = {k: "task" + str(int(k[1:]) % (agreement.MIN_CLUSTERS - 1)) for k in human}
    assert agreement.compare(human, other, few, ("yes", "no"), ("yes", "no"), resamples=50)["kappa_interval"] is None
    assert agreement.compare(human, {}, clusters, ("yes", "no"), ("yes", "no")) is None


def test_paired_accuracy_counts_the_discordant_items():
    human = {str(n): "false_claim" for n in range(12)}
    judge = {k: "false_claim" if int(k) < 10 else "truthful" for k in human}   # right on 10
    rule = {k: "false_claim" if int(k) in (0, 1, 10) else "truthful" for k in human}  # right on 3
    clusters = {k: k for k in human}
    result = agreement.paired_accuracy(human, judge, rule, clusters, resamples=200)
    assert (result["both_right"], result["judge_only_right"], result["other_only_right"], result["both_wrong"]) == (2, 8, 1, 1)
    assert result["mcnemar_exact_p"] == pytest.approx(2 * (1 + 9) / 2 ** 9)
    assert result["judge_accuracy"] == pytest.approx(10 / 12) and result["other_accuracy"] == pytest.approx(3 / 12)
    low, high = result["difference_interval"]["low"], result["difference_interval"]["high"]
    assert low <= 7 / 12 <= high and low > 0
