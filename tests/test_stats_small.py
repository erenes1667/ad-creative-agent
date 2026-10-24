from adcreative.stats import spearman


def test_spearman_needs_three():
    assert spearman([], []) is None and spearman([1, 2], [2, 1]) is None
