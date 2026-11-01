"""Hypothesis verdicts H1-H3 (M18 step 3) -> docs/report/verdicts.md.

This module implements the decision rules of `docs/methodology/statistical_protocol.md §4`, which were frozen
when plan v2 was applied, against the thresholds of `docs/methodology/project_brief.md §4`
(`analysis.thresholds`, integrity rule I5). A rule is applied to an **interval**, never to a
point estimate: the plan-v1 verdicts were computed from point estimates and were explicitly
provisional (D-065), and this file replaces them.

The numbers come from `analysis.hypotheses`, which `analysis.tables` also uses, so every
figure quoted here appears in a generated table (checked by `analysis.check_numbers`).

    python -m analysis.verdicts            # write docs/report/verdicts.md
    python -m analysis.verdicts --check    # regenerate in memory, exit 1 on drift
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from analysis import hypotheses as HYP
from analysis import tables as T
from analysis.thresholds import (H1_MIN_REDUCTION, H2_MAX_GAP, H2_MIN_SPEEDUP, H3_RANGE,
                                 H3_REFUTE_RATE, H3_SUPPORT_RATE, MIN_QUALIFYING_INSTANCES)

SUPPORTED, REFUTED, INCONCLUSIVE = "SUPPORTED", "REFUTED", "INCONCLUSIVE"


@dataclass
class Verdict:
    hid: str
    verdict: str
    lines: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    per_topology: dict[str, str] = field(default_factory=dict)


def _aggregate(per_topology: dict[str, str]) -> str:
    """05 §4.1's aggregation: all SUPPORTED -> SUPPORTED, any REFUTED -> REFUTED, else
    INCONCLUSIVE. H3 has no aggregation rule of its own, so the same shape is applied to it
    (D-080) and the per-topology verdicts are always reported beside it."""
    values = set(per_topology.values())
    if values == {SUPPORTED}:
        return SUPPORTED
    if REFUTED in values:
        return REFUTED
    return INCONCLUSIVE


def _interval_rule(lo: float, hi: float, threshold: float, direction: str) -> str:
    """The shared shape of 05 §4: SUPPORTED when the whole CI clears the threshold, REFUTED
    when the whole CI misses it, INCONCLUSIVE when the CI straddles it.

    direction "ge": the hypothesis claims the quantity is >= threshold.
    direction "le": the hypothesis claims the quantity is <= threshold.
    """
    if direction == "ge":
        return SUPPORTED if lo >= threshold else (REFUTED if hi < threshold else INCONCLUSIVE)
    return SUPPORTED if hi <= threshold else (REFUTED if lo > threshold else INCONCLUSIVE)


def h1() -> Verdict:
    """05 §4.1: per-draw reduction rho vs the frozen 20 % threshold, per topology."""
    rows = HYP.h1_rows(H1_MIN_REDUCTION)
    primary = [r for r in rows if r.variant == "b1"]
    per_topology = {r.topology_id: _interval_rule(r.rho.ci_lo, r.rho.ci_hi, H1_MIN_REDUCTION, "ge")
                    for r in primary}
    lines = [f"Rule (`05 §4.1`): per topology, rho_d = (C(B1) - C(ILP)) / C(B1) on each of R = "
             f"{primary[0].rho.n} traffic draws. SUPPORTED if the 95 % CI of mean(rho) lies at or "
             f"above {100 * H1_MIN_REDUCTION:g}%, REFUTED if it lies entirely below, INCONCLUSIVE if it "
             f"straddles. Overall: SUPPORTED only if all three topologies are; REFUTED if any is. "
             f"B1 is the reported tie-break (D-039, D-076); B1-alt is reported as robustness.", ""]
    for r in primary:
        lines.append(
            f"- {T.TOPO[r.topology_id]}: reduction {T.pctv(100 * r.rho.mean)}% +/- "
            f"{T.pctv(100 * r.rho.sd)}%, 95 % CI {T.ci(100 * r.rho.ci_lo, 100 * r.rho.ci_hi)}% "
            f"(C(B1) {T.usd(r.b1_usd.mean)}, C(ILP) {T.usd(r.ilp_usd.mean)} USD/month); "
            f"one-sided Wilcoxon of rho > {100 * H1_MIN_REDUCTION:g}%: p = {T.pval(r.wilcoxon_p)} "
            f"-> **{per_topology[r.topology_id]}**.")
    verdict = _aggregate(per_topology)
    supported = [T.TOPO[t] for t, v in per_topology.items() if v == SUPPORTED]
    refuted = [T.TOPO[t] for t, v in per_topology.items() if v == REFUTED]
    lines += ["", f"Overall **{verdict}**: " + (
        f"{', '.join(refuted)} {'is' if len(refuted) == 1 else 'are'} refuted"
        + (f", although {', '.join(supported)} clears the threshold on its own"
           if supported else "") + "."
        if refuted else "every topology clears the threshold.")]
    alt = [r for r in rows if r.variant == "b1_alt"]
    lines.append("")
    lines.append(
        "Robustness (B1-alt, the opposite storage tie-break): reduction "
        + ", ".join(f"{T.TOPO[r.topology_id]} {T.pctv(100 * r.rho.mean)}%" for r in alt)
        + ". B1-alt already places every component in the cheapest single location, so the ILP "
          "cannot improve on it and the verdict against that variant is REFUTED on all three "
          "topologies. The reported verdict therefore does not depend on the tie-break in the "
          "direction that would flatter the method.")
    return Verdict("H1", verdict, lines,
                   ["results/replicates/runs.csv", "docs/report/tables/h1_replicated.md",
                    "figures/F1_cost_breakdown.csv", "figures/R2-1_cost_vs_scale.csv"],
                   per_topology)


def h2() -> Verdict:
    """05 §4.2: SA's gap and speed-up in the qualifying cells, each judged on its own CI."""
    gap, per_instance = HYP.h2_gap()
    sp, wide = HYP.h2_speedup()
    lines = [f"Rule (`05 §4.2`): over instances in cells with n >= {HYP.H2_MIN_N} and |L| >= "
             f"{HYP.H2_MIN_L} where CBC proved optimality, the median SA gap (median over seeds per "
             f"instance) and the median speed-up t(ILP) / t(SA) from timing-repeat means. SUPPORTED "
             f"needs the gap CI upper <= {100 * H2_MAX_GAP:g}% **and** the speed-up CI lower >= "
             f"{H2_MIN_SPEEDUP}x; REFUTED if the gap CI lower exceeds the limit or the speed-up CI "
             f"upper falls below it. Fewer than {MIN_QUALIFYING_INSTANCES} qualifying instances would "
             f"make it INCONCLUSIVE by rule.", ""]
    if min(gap.n, sp.n) < MIN_QUALIFYING_INSTANCES:
        lines.append(f"- Only {min(gap.n, sp.n)} qualifying instance(s): the exact frontier was "
                     "reached before the H2 condition, which is itself a finding.")
        return Verdict("H2", INCONCLUSIVE, lines,
                       ["results/scaling/runs.csv", "results/timing/summary.csv"])
    gap_v = _interval_rule(gap.ci_lo, gap.ci_hi, 100 * H2_MAX_GAP, "le")
    sp_v = _interval_rule(sp.ci_lo, sp.ci_hi, H2_MIN_SPEEDUP, "ge")
    lines += [
        f"- Gap clause: median SA gap {T.pctv(gap.mean)}% over {gap.n} instances, 95 % CI "
        f"{T.ci(gap.ci_lo, gap.ci_hi)}% (worst instance {T.pctv(per_instance.max())}%) vs the "
        f"{100 * H2_MAX_GAP:g}% limit -> **{gap_v}**.",
        f"- Speed-up clause: median speed-up {T.ratio(sp.median)}x over {sp.n} timing instances, "
        f"95 % CI {T.ci(sp.ci_lo, sp.ci_hi, T.ratio)}x (best instance "
        f"{T.ratio(wide['speedup'].max())}x) vs the {H2_MIN_SPEEDUP}x requirement -> **{sp_v}**.",
    ]
    if REFUTED in (gap_v, sp_v):
        verdict = REFUTED
    elif gap_v == sp_v == SUPPORTED:
        verdict = SUPPORTED
    else:
        verdict = INCONCLUSIVE
    lines += ["", f"H2 is a conjunction, so it is **{verdict}**: SA is well inside the accuracy "
                  "limit, but on these instances it is not faster than CBC at all, let alone "
                  f"{H2_MIN_SPEEDUP}x. CBC proves optimality quickly here (the frontier was never "
                  "reached, D-055), so the speed-up clause is refuted on measured data rather than "
                  "left untested. The two clauses rest on different instance counts by D-077."]
    return Verdict("H2", verdict, lines,
                   ["results/scaling/runs.csv", "results/timing/summary.csv",
                    "docs/report/tables/h1_replicated.md", "docs/report/tables/scaling.md",
                    "figures/F4_runtime_vs_n.csv", "figures/F5_gap_boxplots.csv"])


def h3() -> Verdict:
    """05 §4.3: does a traffic-scale crossover exist, in the base sweep and across draws?"""
    rows = [r for r in HYP.h3_rows() if r.variant == "b1"]
    per_topology = {}
    lines = [f"Rule (`05 §4.3`): per topology and per draw, find the crossover scale by the frozen "
             f"D-056 rule over s = {T.scale(H3_RANGE[0])}-{T.scale(H3_RANGE[1])}. SUPPORTED if a "
             f"crossover exists in the base (undrawn) sweep **and** in at least "
             f"{100 * H3_SUPPORT_RATE:g}% of draws; REFUTED if it exists in at most "
             f"{100 * H3_REFUTE_RATE:g}% of them. The draws sweep {HYP.n_scale_points()} scale points "
             f"across the same range (D-078).", ""]
    for r in rows:
        if r.rate <= H3_REFUTE_RATE:
            v = REFUTED
        elif r.base_crossover and r.rate >= H3_SUPPORT_RATE:
            v = SUPPORTED
        else:
            v = INCONCLUSIVE
        per_topology[r.topology_id] = v
        thr = ("not defined (no draw has one)" if r.threshold_gb is None
               else f"median {T.usd(r.threshold_gb.median)} GB/month, 95 % CI "
                    f"{T.ci(r.threshold_gb.ci_lo, r.threshold_gb.ci_hi, T.usd)}")
        lines.append(f"- {T.TOPO[r.topology_id]}: {r.crossovers}/{r.n_draws} draws show a crossover "
                     f"({T.pctv(100 * r.rate)}%, 95 % Wilson CI "
                     f"{T.ci(100 * r.rate_lo, 100 * r.rate_hi)}%); base sweep: "
                     f"{'yes' if r.base_crossover else 'no'}; threshold {thr} -> **{v}**.")
    verdict = _aggregate(per_topology)
    lines += ["", f"Overall **{verdict}** (aggregated as in `05 §4.1`, D-080). The reason is the same "
                  "everywhere: the ILP optimum already uses one provider at the smallest swept scale, "
                  "so there is no multi-provider region below a threshold for the optimum to leave. "
                  f"Reason recorded on every draw: \"{rows[0].reason}\"."]
    mins = T.own_cost_minimisers()
    common = {t: m[1] for t, m in mins.items()}
    lines.append("")
    if all(common.values()):
        lines.append("Why this is structural rather than a grid artefact (D-060): for every component "
                     "of T1-T3 its own cost (compute + storage + internet) is minimised at "
                     + ", ".join(f"{T.TOPO[t]} {'/'.join(f'`{l}`' for l in common[t])}"
                                 for t in T.TOPOLOGIES)
                     + ". Inter-component egress is never negative and is zero when all components "
                       "share a location, so placing everything there is optimal at every traffic "
                       "scale s >= 0 in this snapshot. No finer grid and no further draw can produce "
                       "a crossover here; a topology whose components have different own-cost "
                       "minimisers (for example one pinned to another provider) could.")
    else:
        lines.append("No single location minimises every component's own cost (cost_model.md).")
    return Verdict("H3", verdict, lines,
                   ["results/replicates/runs.csv", "results/sweep/crossover.csv",
                    "docs/report/tables/h1_replicated.md", "docs/report/tables/crossover.md",
                    "docs/report/tables/cost_model.md", "figures/F3_providers_used.csv"],
                   per_topology)


def all_verdicts() -> list[Verdict]:
    return [h1(), h2(), h3()]


def render() -> str:
    vs = all_verdicts()
    out = ["# Hypothesis verdicts", "",
           "Generated by `python -m analysis.verdicts`; do not edit. The thresholds are the frozen "
           "constants of `00_PROJECT_BRIEF.md §4` (`analysis/thresholds.py`); the decision rules are "
           "`05_STATISTICS.md §4`, applied to 95 % intervals rather than to point estimates. These "
           "verdicts replace the provisional plan-v1 ones (D-065).", "",
           "| Hypothesis | Verdict | Per topology |", "|---|---|---|"]
    for v in vs:
        per = ", ".join(f"{T.TOPO[t]} {x}" for t, x in v.per_topology.items()) or "-"
        out.append(f"| {v.hid} | **{v.verdict}** | {per} |")
    for v in vs:
        out += ["", f"## {v.hid}: {v.verdict}", ""] + v.lines + [
            "", "Sources: " + ", ".join(f"`{s}`" for s in v.sources)]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    return T.check_or_write({T.ROOT / "docs" / "report" / "verdicts.md": render()}, args.check,
                            "verdicts")


if __name__ == "__main__":
    sys.exit(main())
