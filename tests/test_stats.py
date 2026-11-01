"""Known-answer and coverage tests for analysis/stats.py (M16 A4)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from analysis import stats


def test_constant_sample_has_zero_sd_and_collapsed_ci():
    s = stats.summarise([7.5] * 30)
    assert s.n == 30
    assert s.mean == pytest.approx(7.5)
    assert s.sd == 0.0
    assert s.sem == 0.0
    assert s.ci_lo == s.ci_hi == pytest.approx(7.5)
    assert s.ci_method == "degenerate"


def test_single_value_is_degenerate():
    s = stats.summarise([3.0])
    assert s.n == 1 and s.sd == 0.0 and s.ci_lo == s.ci_hi == 3.0


def test_mean_sd_sem_median_known_answer():
    s = stats.summarise([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert s.mean == pytest.approx(5.0)
    assert s.sd == pytest.approx(2.13808993, rel=1e-6)  # ddof=1
    assert s.sem == pytest.approx(2.13808993 / math.sqrt(8), rel=1e-6)
    assert s.median == pytest.approx(4.5)


def test_summarise_is_deterministic():
    rng = np.random.default_rng(1)
    sample = rng.normal(10, 2, 30).tolist()
    a, b = stats.summarise(sample), stats.summarise(sample)
    assert a == b


def test_ci_contains_the_mean_and_shrinks_with_n():
    rng = np.random.default_rng(7)
    small = stats.summarise(rng.normal(0, 1, 12))
    large = stats.summarise(rng.normal(0, 1, 400))
    for s in (small, large):
        assert s.ci_lo <= s.mean <= s.ci_hi
    assert (large.ci_hi - large.ci_lo) < (small.ci_hi - small.ci_lo)


def test_small_n_takes_the_wider_of_bootstrap_and_t():
    rng = np.random.default_rng(3)
    sample = rng.normal(5, 1, 6)
    s = stats.summarise(sample)
    assert s.n < stats.SMALL_N
    assert s.ci_method in {"bootstrap", "t"}
    t_lo, t_hi = stats._t_ci(np.asarray(sample, dtype=float))
    b_lo, b_hi = stats._bootstrap_ci(np.asarray(sample, dtype=float))
    assert (s.ci_hi - s.ci_lo) == pytest.approx(max(t_hi - t_lo, b_hi - b_lo))


def test_empty_and_nonfinite_are_rejected():
    with pytest.raises(ValueError):
        stats.summarise([])
    with pytest.raises(ValueError):
        stats.summarise([1.0, float("nan")])


def test_coverage_simulation_is_close_to_95_percent():
    """500 normal samples of n = 30: the CI should cover the true mean ~95 % of the time."""
    rng = np.random.default_rng(20260922)
    true_mean = 12.0
    covered = 0
    trials = 500
    for _ in range(trials):
        sample = rng.normal(true_mean, 3.0, 30)
        s = stats.summarise(sample)
        if s.ci_lo <= true_mean <= s.ci_hi:
            covered += 1
    coverage = covered / trials
    assert 0.92 <= coverage <= 0.98, f"coverage {coverage:.3f} outside [0.92, 0.98]"


def test_paired_diff_ci_excludes_zero_for_a_real_shift():
    rng = np.random.default_rng(11)
    base = rng.normal(100, 5, 30)
    better = base - 3.0 + rng.normal(0, 0.2, 30)
    s = stats.paired_diff_ci(base, better)
    assert s.mean == pytest.approx(3.0, abs=0.3)
    assert s.ci_lo > 0


def test_paired_diff_ci_of_identical_samples_is_zero():
    sample = [1.0, 2.0, 3.0, 4.0]
    s = stats.paired_diff_ci(sample, sample)
    assert s.mean == 0.0 and s.ci_lo == s.ci_hi == 0.0


def test_paired_helpers_reject_misaligned_input():
    with pytest.raises(ValueError):
        stats.paired_diff_ci([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        stats.paired_ratio_ci([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        stats.paired_ratio_ci([1.0], [0.0])


def test_paired_ratio_ci_known_answer():
    s = stats.paired_ratio_ci([2.0, 4.0, 6.0], [1.0, 2.0, 3.0])
    assert s.mean == pytest.approx(2.0)
    assert s.sd == 0.0


def test_wilcoxon_greater_detects_a_positive_median():
    rng = np.random.default_rng(5)
    shifted = rng.normal(1.0, 0.5, 20)
    _, p = stats.wilcoxon_greater(shifted, mu=0.0)
    assert p < 0.01
    _, p_null = stats.wilcoxon_greater(rng.normal(0.0, 0.5, 20), mu=0.0)
    assert p_null > 0.05


def test_wilcoxon_greater_on_all_zero_differences():
    stat, p = stats.wilcoxon_greater([2.0, 2.0, 2.0], mu=2.0)
    assert stat == 0.0 and p == 1.0


def test_wilson_known_answers():
    p, lo, hi = stats.wilson(0, 30)
    assert p == 0.0 and lo == 0.0 and 0.0 < hi < 0.2
    p, lo, hi = stats.wilson(30, 30)
    assert p == 1.0 and hi == pytest.approx(1.0) and 0.8 < lo < 1.0
    # hand-computed for k=8, n=20, z=1.95996: centre 0.41608, half-width 0.19731
    p, lo, hi = stats.wilson(8, 20)
    assert p == pytest.approx(0.4)
    assert lo == pytest.approx(0.21877, abs=1e-4)
    assert hi == pytest.approx(0.61339, abs=1e-4)


def test_wilson_rejects_bad_input():
    with pytest.raises(ValueError):
        stats.wilson(1, 0)
    with pytest.raises(ValueError):
        stats.wilson(5, 3)


def test_formatting_precision_rules():
    assert stats.fmt_cost(1789.8765) == "1,790"
    assert stats.fmt_cost(4.81176) == "4.81"
    assert stats.fmt_pct(3.4142) == "3.4"
