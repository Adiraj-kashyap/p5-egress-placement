"""Estimators and uncertainty intervals for every plan-v2 figure and table (M16, 05 §5).

This is the single place where a mean, a spread or a confidence interval is computed.
M17 (ablation) and M18 (analysis) must call these functions rather than rolling their own,
so that every reported interval uses the same frozen rules:

- 95 % percentile bootstrap, B = 10,000 resamples, ``rng = np.random.default_rng(12345)``;
- for n < 10 the Student-t interval is also computed and the **wider** of the two is
  reported (05 §5), recorded in the ``ci_method`` field;
- comparisons between methods are **paired** (same traffic draw), so the difference is
  summarised, never two independent means (05 §2);
- proportions use the Wilson score interval.

Every function is deterministic: the bootstrap rng is re-seeded from BOOTSTRAP_SEED on
each call, so the same input always gives the same interval.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy import stats as scipy_stats

BOOTSTRAP_B = 10_000
BOOTSTRAP_SEED = 12345
CI_LEVEL = 0.95
SMALL_N = 10  # below this, also compute the t-interval and take the wider one


@dataclass(frozen=True)
class Summary:
    """Point estimate and 95 % interval for one configuration's metric."""

    n: int
    mean: float
    sd: float
    sem: float
    median: float
    ci_lo: float
    ci_hi: float
    ci_method: str  # "bootstrap" | "t" | "degenerate"

    def as_dict(self) -> dict[str, float | int | str]:
        """Return the summary as a plain dict, for a csv row."""
        return asdict(self)


def _as_array(values: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        raise ValueError("summarise() needs at least one value")
    if not np.all(np.isfinite(arr)):
        raise ValueError("summarise() got a non-finite value")
    return arr


def _bootstrap_ci(arr: np.ndarray, level: float = CI_LEVEL) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean (B = 10,000, fixed rng)."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = rng.integers(0, arr.size, size=(BOOTSTRAP_B, arr.size))
    means = arr[idx].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    lo, hi = np.percentile(means, [100 * alpha, 100 * (1 - alpha)])
    return float(lo), float(hi)


def _t_ci(arr: np.ndarray, level: float = CI_LEVEL) -> tuple[float, float]:
    """Student-t CI of the mean; degenerate to the point value when n < 2 or sd == 0."""
    n = arr.size
    mean = float(arr.mean())
    if n < 2:
        return mean, mean
    sem = float(arr.std(ddof=1) / math.sqrt(n))
    if sem == 0.0:
        return mean, mean
    half = float(scipy_stats.t.ppf(1 - (1 - level) / 2, df=n - 1) * sem)
    return mean - half, mean + half


def summarise(values: Iterable[float], level: float = CI_LEVEL) -> Summary:
    """Summarise a sample of a metric over its replication unit (05 §5).

    Returns n, mean, sd (ddof=1), sem, median and a 95 % CI of the mean. The CI is the
    percentile bootstrap; for n < 10 the t-interval is also computed and the wider of the
    two is returned. A constant sample gives sd 0 and a collapsed interval
    (``ci_method="degenerate"``).
    """
    arr = _as_array(values)
    n = int(arr.size)
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    sem = sd / math.sqrt(n) if n > 1 else 0.0
    median = float(np.median(arr))

    if n < 2 or sd == 0.0:
        return Summary(n, mean, sd, sem, median, mean, mean, "degenerate")

    b_lo, b_hi = _bootstrap_ci(arr, level)
    method = "bootstrap"
    lo, hi = b_lo, b_hi
    if n < SMALL_N:
        t_lo, t_hi = _t_ci(arr, level)
        if (t_hi - t_lo) > (b_hi - b_lo):
            lo, hi, method = t_lo, t_hi, "t"
    return Summary(n, mean, sd, sem, median, lo, hi, method)


def paired_diff_ci(
    a: Sequence[float], b: Sequence[float], level: float = CI_LEVEL
) -> Summary:
    """Summarise the paired difference a[i] - b[i] (05 §2: same draw, so pair them).

    ``a`` and ``b`` must be aligned element by element (same draw / instance / cell) and
    of equal length. The returned Summary describes the *difference*; a CI excluding 0
    means the two methods differ at the 5 % level.
    """
    arr_a, arr_b = _as_array(a), _as_array(b)
    if arr_a.size != arr_b.size:
        raise ValueError(
            f"paired_diff_ci needs aligned samples, got {arr_a.size} and {arr_b.size}"
        )
    return summarise(arr_a - arr_b, level)


def paired_ratio_ci(
    a: Sequence[float], b: Sequence[float], level: float = CI_LEVEL
) -> Summary:
    """Summarise the paired ratio a[i] / b[i] (e.g. speed-up), b[i] != 0 required."""
    arr_a, arr_b = _as_array(a), _as_array(b)
    if arr_a.size != arr_b.size:
        raise ValueError(
            f"paired_ratio_ci needs aligned samples, got {arr_a.size} and {arr_b.size}"
        )
    if np.any(arr_b == 0.0):
        raise ValueError("paired_ratio_ci got a zero denominator")
    return summarise(arr_a / arr_b, level)


def wilcoxon_greater(x: Sequence[float], mu: float = 0.0) -> tuple[float, float]:
    """One-sided Wilcoxon signed-rank test of H1: median(x) > mu.

    Returns (statistic, p_value). Zero differences are dropped (``zero_method="wilcox"``).
    If every value equals mu, the test is undefined and (0.0, 1.0) is returned.
    """
    arr = _as_array(x) - float(mu)
    nz = arr[arr != 0.0]
    if nz.size == 0:
        return 0.0, 1.0
    res = scipy_stats.wilcoxon(nz, alternative="greater", zero_method="wilcox")
    return float(res.statistic), float(res.pvalue)


def wilson(k: int, n: int, level: float = CI_LEVEL) -> tuple[float, float, float]:
    """Wilson score interval for a proportion k/n (05 §5: used for crossover rates).

    Returns (p_hat, lo, hi). n must be >= 1 and 0 <= k <= n.
    """
    if n < 1:
        raise ValueError("wilson() needs n >= 1")
    if not (0 <= k <= n):
        raise ValueError(f"wilson() needs 0 <= k <= n, got k={k}, n={n}")
    z = float(scipy_stats.norm.ppf(1 - (1 - level) / 2))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, centre - half), min(1.0, centre + half)


def fmt_cost(x: float) -> str:
    """Format a cost with 3 significant figures (05 §5 precision rule)."""
    if x == 0:
        return "0.00"
    digits = max(0, 3 - int(math.floor(math.log10(abs(x)))) - 1)
    return f"{x:,.{digits}f}"


def fmt_pct(x: float) -> str:
    """Format a percentage with 1 decimal (05 §5 precision rule)."""
    return f"{x:.1f}"
