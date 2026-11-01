"""The H1-H3 quantities of 05 §4, computed once and shared by `analysis.tables` and
`analysis.verdicts` so that a table and a verdict can never disagree.

This module computes *numbers*, never verdicts: the frozen thresholds and the
SUPPORTED/REFUTED/INCONCLUSIVE rules live in `analysis.verdicts`, which is the only place
allowed to read `00_PROJECT_BRIEF.md §4`. Every interval comes from `analysis.stats`.

    h1_rows()   per topology and B1 variant: the per-draw reduction rho, its CI and a
                one-sided Wilcoxon test of rho > the threshold (05 §4.1)
    h2_gap() / h2_speedup()
                the SA gap over qualifying scaling instances and the SA speed-up over
                qualifying timing instances, both bootstrapped over instances (05 §4.2, D-077)
    h3_rows()   per topology: the share of draws with a crossover (Wilson) and, when any
                exist, the median crossover threshold in GB/month (05 §4.3, D-078)
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

import pandas as pd

from analysis import replicated as R
from analysis import scaling_summary
from analysis.stats import Summary, summarise, wilcoxon_greater, wilson

H2_MIN_N, H2_MIN_L = 15, 20  # the qualifying cell of 05 §4.2 (00 §4); thresholds: verdicts.py
B1_VARIANTS = ["b1", "b1_alt"]
B1_LABEL = {"b1": "B1 (reported tie-break)", "b1_alt": "B1-alt (opposite tie-break, D-039)"}


@dataclass(frozen=True)
class H1Row:
    """One topology x B1 variant: the per-draw reduction and its test against a threshold."""

    topology_id: str
    variant: str
    rho: Summary          # reduction as a fraction, e.g. 0.21 = 21 %
    wilcoxon_stat: float
    wilcoxon_p: float
    threshold: float
    b1_usd: Summary
    ilp_usd: Summary


def h1_rows(threshold: float, scale: float = R.S1) -> list[H1Row]:
    """05 §4.1 for both B1 variants, at the operating point s = 1 on the core set."""
    df = R.draw_frame()
    out = []
    for t in R.TOPOLOGIES:
        for v in B1_VARIANTS:
            rho = R.reduction(df, t, v, scale)
            pair = R.paired(df, t, scale, [v, R.REF_METHOD])
            stat, p = wilcoxon_greater(rho, threshold)
            out.append(H1Row(t, v, summarise(rho), stat, p, threshold,
                             summarise(pair[v]), summarise(pair[R.REF_METHOD])))
    return out


def _scaling_gaps() -> pd.DataFrame:
    """Per-run SA gap vs the proven optimum, with the cell columns (D-054 reference)."""
    df = scaling_summary.load()
    df = df.merge(scaling_summary.reference(df), on="instance_id", how="left",
                  validate="many_to_one")
    df = df[(df["method"] == "sa") & df["ref_proven"]]
    return df.assign(gap_pct=100.0 * (df["total_usd"] - df["ref_total"]) / df["ref_total"])


def h2_gap() -> tuple[Summary, pd.Series]:
    """SA gap in the qualifying cells: per instance the median over seeds, then over instances.

    Returns (summary over instances, the per-instance sample indexed by instance id).
    """
    df = _scaling_gaps()
    q = df[(df["n"] >= H2_MIN_N) & (df["n_locations"] >= H2_MIN_L)]
    per_instance = q.groupby("instance_id")["gap_pct"].median()
    return summarise(per_instance), per_instance


def h2_speedup() -> tuple[Summary, pd.DataFrame]:
    """SA speed-up t_ILP / t_SA from timing-repeat means, over the qualifying instances.

    Only instances whose ILP solve is proven optimal count, as 05 §4.2 requires; the
    location set is `ext` (|L| = 24 >= 20) and n >= 15 (D-077).
    """
    t = R.timing_instance_means()
    t = t[(t["location_set"] == "ext") & (t["n_components"] >= H2_MIN_N)]
    wide = t.pivot_table(index=["instance_id", "n_components"], columns="method",
                         values="runtime_mean_s")
    proven = _timing_proven()
    wide = wide[[i in proven for i, _ in wide.index]]
    wide = wide.assign(speedup=wide["ilp_tight"] / wide["sa"])
    return summarise(wide["speedup"]), wide.reset_index()


def _timing_proven() -> set[str]:
    """Instance ids whose ILP runs in results/timing were all proven optimal."""
    with (R.RES / "timing" / "runs.csv").open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["method"] == "ilp_tight"]
    by_instance: dict[str, list[bool]] = {}
    for r in rows:
        by_instance.setdefault(r["instance_id"], []).append(
            str(r["proven_optimal"]).lower() == "true")
    return {i for i, flags in by_instance.items() if all(flags)}


@dataclass(frozen=True)
class H3Row:
    """One topology x B1 variant: the share of draws that show a crossover (05 §4.3)."""

    topology_id: str
    variant: str
    crossovers: int
    n_draws: int
    rate: float
    rate_lo: float
    rate_hi: float
    threshold_gb: Summary | None  # median crossover volume, when any draw has one
    base_crossover: bool          # does the undrawn M15 sweep show one?
    reason: str


def h3_rows() -> list[H3Row]:
    """05 §4.3 per topology, for both B1 variants, on the replicated scale grid (D-078)."""
    df = R.draw_frame()
    base = _base_sweep_crossover()
    out = []
    for v in B1_VARIANTS:
        cx = R.crossover_by_draw(df, v)
        for t in R.TOPOLOGIES:
            g = cx[cx["topology_id"] == t]
            k, n = int(g["crossover"].sum()), len(g)
            p, lo, hi = wilson(k, n)
            hit = g[g["crossover"]]
            gb = summarise(hit["T_gb_month"].astype(float)) if len(hit) else None
            reasons = sorted(set(g["reason"]))
            out.append(H3Row(t, v, k, n, p, lo, hi, gb, base.get((t, v), False),
                             "; ".join(reasons)))
    return out


def _base_sweep_crossover() -> dict[tuple[str, str], bool]:
    """(topology, B1 variant) -> did the base, undrawn M15 sweep find a crossover?"""
    c = pd.read_csv(R.RES / "sweep" / "crossover.csv")
    c = c[(c["criterion"] == "ilp_providers_used") & (abs(c["rate_factor"] - 1.0) < 1e-12)]
    return {(r["topology_id"], r["b1_variant"]): r["crossover"] == "yes" for _, r in c.iterrows()}


def n_scale_points() -> int:
    """How many traffic scales the replicated grid sweeps (the H3 grid resolution)."""
    return int(R.draw_frame()["traffic_scale"].nunique())
