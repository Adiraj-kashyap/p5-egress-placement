"""Report tables (M16 step 2): Markdown tables in docs/report/tables/, built only from
committed results and cost-model files. Every number the report quotes must appear in
one of these tables (checked by `python -m analysis.check_numbers`).

    cost_model.md   per-location unit prices + single-location totals of T1-T3   cost_model/2026-09-21/
    baselines.md    B1, B1-alt, B2-* on T1-T3                                    results/baselines, results/sweep
    exact.md        ILP (tight, McCormick) and heuristics on T1-T3               results/exact, results/heuristics
    scaling.md      scaling summary, frontier, pooled H2 figures                  results/scaling
    sweep.md        penalty vs traffic scale, H1 reductions, rate sensitivity     results/sweep, results/sweep_sensitivity
    crossover.md    crossover rows (D-056 rules)                                  results/sweep*/crossover.csv

    python -m analysis.tables            # write the tables
    python -m analysis.tables --check    # regenerate in memory, exit 1 on drift
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import hypotheses as HYP
from analysis import scaling_summary
from analysis.thresholds import H1_MIN_REDUCTION as H1_THRESHOLD
from placement.cost import evaluate
from placement.instance import load_instance
from pricing.common import LOCATIONS_CORE, location_id

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "report" / "tables"
PAPER = ROOT / "paper" / "tables"
SNAPSHOT = "2026-09-21"
COST_MODEL = ROOT / "cost_model" / SNAPSHOT
RES = ROOT / "results"

TOPOLOGIES = ["t1_three_tier", "t2_pipeline", "t3_microservices"]
TOPO = {"t1_three_tier": "T1", "t2_pipeline": "T2", "t3_microservices": "T3"}
SWEEP_POINTS = (0.01, 0.1, 1.0, 10.0, 100.0)  # grid points i = 0, 6, 12, 18, 24 of D-056
H2_MIN_N, H2_MIN_L = 15, 20  # qualifying cells of H2 (00 §4); verdict thresholds live in verdicts.py
TOL = 1e-6
# The §S12 ablation variants, in the order the ablation table lists them (M17).
ABLATION_VARIANTS = ["b1", "b1_storage", "ilp_no_edge_egress", "ilp_no_internet",
                     "ilp_undirected", "ilp_single_provider", "b2_best", "sa",
                     "sa_random_init", "sa_no_swap"]


# ---------------------------------------------------------------- formatting
def usd(x: float) -> str:
    return f"{x:,.2f}"


def pct(frac: float) -> str:
    """A fraction shown as a percentage with 2 decimals (no % sign; column headers say %)."""
    return f"{100 * frac:.2f}"


def pctv(v: float) -> str:
    """A value that is already in percent."""
    return f"{v:.2f}" if abs(v) >= 0.005 or v == 0 else f"{v:.4f}"


def secs(x: float) -> str:
    return f"{x:.3g}" if x >= 0.001 else f"{x:.2e}"


def ratio(x: float) -> str:
    return f"{x:.2f}"


def ci(lo: float, hi: float, fmt=None) -> str:
    """A 95 % interval as [lo, hi], formatted with the caller's number format."""
    fmt = fmt or pctv
    return f"[{fmt(lo)}, {fmt(hi)}]"


def pval(p: float) -> str:
    """A p-value at 3 decimals, with the usual floor rather than a misleading 0.000."""
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def scale(x: float) -> str:
    return f"{x:g}"


def md_table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def _is(x: pd.Series, v: float) -> pd.Series:
    return np.isclose(x.astype(float), v, rtol=1e-9, atol=1e-12)


# ---------------------------------------------------------------- data shared with verdicts.py
def sweep_summary(rate: float = 1.0) -> pd.DataFrame:
    path = RES / ("sweep" if rate == 1.0 else "sweep_sensitivity") / "summary.csv"
    s = pd.read_csv(path)
    return s[_is(s["rate_factor"], rate)]


def at_s1() -> pd.DataFrame:
    """One row per topology at s = 1, rate x1 (H1 source, D-059)."""
    s = sweep_summary()
    s = s[_is(s["scale"], 1.0)].set_index("topology_id").loc[TOPOLOGIES]
    return s


def crossover_rows() -> pd.DataFrame:
    a = pd.read_csv(RES / "sweep" / "crossover.csv")
    b = pd.read_csv(RES / "sweep_sensitivity" / "crossover.csv")
    return pd.concat([a.assign(source="sweep"), b.assign(source="sweep_sensitivity")], ignore_index=True)


def scaling_qualifying() -> pd.DataFrame:
    """SA rows of results/scaling/summary.csv in the H2 condition (n >= 15, |L| >= 20)."""
    s = pd.read_csv(RES / "scaling" / "summary.csv")
    return s[(s["method"] == "sa") & (s["n"] >= H2_MIN_N) & (s["n_locations"] >= H2_MIN_L)
             & (s["ref_proven_instances"] > 0)].sort_values("n").reset_index(drop=True)


def scaling_pooled(method: str = "sa") -> dict:
    """Pooled H2 figures over every qualifying instance, with the D-054 definitions:
    per instance, gap = median over seeds, runtime = median over seeds; then medians."""
    df = scaling_summary.load()
    df = df.merge(scaling_summary.reference(df), on="instance_id", how="left", validate="many_to_one")
    q = df[(df["method"] == method) & (df["n"] >= H2_MIN_N) & (df["n_locations"] >= H2_MIN_L) & df["ref_proven"]]
    q = q.assign(gap_pct=100.0 * (q["total_usd"] - q["ref_total"]) / q["ref_total"])
    per = q.groupby("instance_id").agg(gap_pct=("gap_pct", "median"), runtime_s=("runtime_s", "median"),
                                       ref_runtime_s=("ref_runtime_s", "first"))
    sp = per["ref_runtime_s"] / per["runtime_s"]
    return {"instances": len(per), "runs": len(q), "gap_median_pct": float(per["gap_pct"].median()),
            "gap_max_instance_median_pct": float(per["gap_pct"].max()),
            "speedup_median": float(sp.median()), "speedup_max": float(sp.max()),
            "n_values": sorted(int(n) for n in q["n"].unique())}


# ---------------------------------------------------------------- tables
def _src(*paths: str) -> str:
    return "Source: " + ", ".join(f"`{p}`" for p in paths) + ". Generated by `python -m analysis.tables`; do not edit.\n"


def t_cost_model() -> str:
    comp = pd.read_csv(COST_MODEL / "compute.csv")
    comp["loc"] = comp["provider"] + ":" + comp["region"]
    comp["per_vcpu"] = comp["usd_per_hour"] / comp["vcpu"]
    stor = pd.read_csv(COST_MODEL / "storage.csv").assign(loc=lambda d: d["provider"] + ":" + d["region"])
    inet = pd.read_csv(COST_MODEL / "internet.csv").assign(loc=lambda d: d["provider"] + ":" + d["region"])
    eg = pd.read_csv(COST_MODEL / "egress.csv")
    eg["src"] = eg["src_provider"] + ":" + eg["src_region"]
    eg["dst"] = eg["dst_provider"] + ":" + eg["dst_region"]
    eg = eg[eg["src"] != eg["dst"]]
    core = {location_id(p, r) for p, regions in LOCATIONS_CORE.items() for r in regions}
    rows = []
    for loc, g in comp.groupby("loc", sort=True):
        pv = g["per_vcpu"].round(9).unique()
        e = eg[eg["src"] == loc]["usd_per_gb"]
        rows.append([f"`{loc}`", "core" if loc in core else "ext",
                     f"{pv.min():.4f}" if len(pv) == 1 else f"{pv.min():.4f}-{pv.max():.4f}",
                     f"{float(stor.loc[stor['loc'] == loc, 'usd_per_gb_month'].iloc[0]):.4f}",
                     f"{float(inet.loc[inet['loc'] == loc, 'usd_per_gb'].iloc[0]):.4f}",
                     f"{e.min():.4f}-{e.max():.4f}"])
    out = "# Cost model summary (snapshot 2026-09-21)\n\n" + _src(
        "cost_model/2026-09-21/{compute,storage,internet,egress}.csv")
    out += ("\nUSD per vCPU-hour is the list price of the location's shape divided by its vCPUs, over all four "
            "shapes (one value = identical for every shape). Egress is the range of the location's outgoing "
            "rates to the other 23 locations, sender pays.\n\n")
    out += md_table(["location", "set", "USD per vCPU-hour", "storage USD/GB-month", "internet USD/GB",
                     "outgoing inter-location USD/GB (min-max)"], rows)
    # single-location totals: every component on one location, evaluated by the shared evaluator
    rows2 = []
    totals = {}
    for t in TOPOLOGIES:
        inst = load_instance(ROOT / "topologies" / f"{t}.json", SNAPSHOT, "core")
        for loc in inst.locations:
            if all(loc in inst.allowed[c] for c in inst.components):
                totals.setdefault(loc, {})[t] = evaluate(inst, {c: loc for c in inst.components}).total
    for loc in sorted(totals):
        rows2.append([f"`{loc}`"] + [usd(totals[loc][t]) if t in totals[loc] else "n/a" for t in TOPOLOGIES])
    best = {t: min(totals, key=lambda l: (totals[l].get(t, np.inf), l)) for t in TOPOLOGIES}
    out += ("\n## Single-location totals, USD/month (core set, traffic scale s = 1)\n\n"
            "Every component on one location; `placement/cost.py::evaluate` on "
            "`topologies/*.json`. Inter-component egress is 0 by construction.\n\n")
    out += md_table(["location", "T1", "T2", "T3"], rows2)
    out += "\nCheapest single location: " + ", ".join(f"{TOPO[t]} `{best[t]}` ({usd(totals[best[t]][t])})"
                                                      for t in TOPOLOGIES) + ".\n"
    out += ("\n## Per-component own-cost minimisers (core set)\n\n"
            "Own cost of component c at l = compute + storage + internet GB x internet rate (no inter-component "
            "egress). If one location minimises the own cost of every component, placing everything there is "
            "optimal for every traffic scale s >= 0, because inter-component egress is >= 0 and is 0 when all "
            "components share a location.\n\n")
    rows3 = []
    for t, (n_comp, common, tied) in own_cost_minimisers().items():
        rows3.append([TOPO[t], n_comp, ", ".join(f"`{l}`" for l in common) or "none", tied])
    out += md_table(["topology", "components", "location minimising every component's own cost",
                     "components with a tied minimiser"], rows3)
    return out


def own_cost_minimisers() -> dict[str, tuple[int, list[str], int]]:
    """Per topology: (components, locations that minimise every component's own cost, #components
    whose own-cost minimum is attained at more than one location). Relative tie tolerance 1e-12."""
    out = {}
    for t in TOPOLOGIES:
        inst = load_instance(ROOT / "topologies" / f"{t}.json", SNAPSHOT, "core")
        arg = []
        for c in inst.components:
            own = {l: inst.k[(c, l)] + inst.internet_gb.get(c, 0.0) * inst.r[l] for l in inst.allowed[c]}
            m = min(own.values())
            arg.append({l for l, v in own.items() if v <= m * (1 + 1e-12)})
        out[t] = (len(inst.components), sorted(set.intersection(*arg)), sum(len(a) > 1 for a in arg))
    return out


def t_baselines() -> str:
    b = pd.read_csv(RES / "baselines" / "runs.csv")
    s1 = at_s1()
    rows = []
    for t in TOPOLOGIES:
        g = b[b["instance_id"] == f"{t}@core"]
        for _, r in g.iterrows():
            rows.append([TOPO[t], r["method"], usd(r["total_usd"]), usd(r["compute_usd"]), usd(r["storage_usd"]),
                         usd(r["egress_usd"]), usd(r["internet_usd"]), int(r["providers_used"])])
        rows.append([TOPO[t], "B1-alt (opposite tie-break, D-039)", usd(s1.loc[t, "b1_alt_total_usd"]),
                     "", "", "", "", int(s1.loc[t, "b1_alt_providers_used"])])
        b1 = float(g.loc[g["method"] == "B1", "total_usd"].iloc[0])
        if abs(b1 - s1.loc[t, "b1_total_usd"]) > TOL:
            raise ValueError(f"{t}: B1 in results/baselines ({b1}) != sweep s=1 ({s1.loc[t, 'b1_total_usd']})")
    return ("# Baselines on T1-T3 (core set, s = 1), USD/month\n\n"
            + _src("results/baselines/runs.csv", "results/sweep/summary.csv (B1-alt, s = 1)")
            + "\n" + md_table(["topology", "method", "total", "compute", "storage", "egress", "internet",
                               "providers"], rows))


def t_exact() -> str:
    e = pd.read_csv(RES / "exact" / "runs.csv")
    h = pd.read_csv(RES / "heuristics" / "runs.csv")
    s1 = at_s1()
    rows = []
    for t in TOPOLOGIES:
        for m, g in e[e["instance_id"] == f"{t}@core"].groupby("method", sort=True):
            proven = int((g["proven_optimal"].astype(str).str.lower() == "true").sum())
            rows.append([TOPO[t], m, usd(g["total_usd"].median()), f"{proven}/{len(g)}",
                         secs(g["runtime_s"].median()), int(g["n_vars"].iloc[0]), int(g["n_constraints"].iloc[0]),
                         int(g["providers_used"].iloc[0])])
        tight = float(e.loc[(e["instance_id"] == f"{t}@core") & (e["method"] == "ILP-tight"), "total_usd"].median())
        if abs(tight - s1.loc[t, "ilp_total_usd"]) > TOL:
            raise ValueError(f"{t}: exact ILP {tight} != sweep s=1 {s1.loc[t, 'ilp_total_usd']}")
    out = ("# Exact ILP and heuristics on T1-T3 (core set, s = 1)\n\n"
           + _src("results/exact/runs.csv", "results/heuristics/runs.csv")
           + "\n## ILP (CBC, single thread)\n\n"
           + md_table(["topology", "formulation", "total USD/month (median)", "proven optimal",
                       "runtime s (median)", "variables", "constraints", "providers"], rows))
    rows = []
    for t in TOPOLOGIES:
        for m in ["greedy", "greedy_1opt", "sa"]:
            g = h[(h["instance_id"] == f"{t}@core") & (h["method"] == m)]
            at_opt = int((g["gap_vs_ilp_pct"].abs() <= 1e-7).sum())
            rows.append([TOPO[t], m, len(g), usd(g["total_usd"].median()), pctv(g["gap_vs_ilp_pct"].median()),
                         pctv(g["gap_vs_ilp_pct"].max()), f"{at_opt}/{len(g)}", secs(g["runtime_s"].median())])
    out += ("\n## Heuristics (greedy repeats, SA = one run per seed)\n\n"
            + md_table(["topology", "method", "runs", "total USD/month (median)", "gap vs ILP % (median)",
                        "gap % (max)", "runs at optimum", "runtime s (median)"], rows))
    return out


def t_scaling() -> str:
    s = pd.read_csv(RES / "scaling" / "summary.csv")
    f = pd.read_csv(RES / "scaling" / "frontier.csv")
    rows = []
    for (L, n), g in s.groupby(["location_set", "n"], sort=True):
        g = g.set_index("method")
        ilp, sa, gr = g.loc["ilp_tight"], g.loc["sa"], g.loc["greedy_1opt"]
        rows.append([L, int(ilp["n_locations"]), int(n), f"{int(ilp['proven_optimal'])}/{int(ilp['instances'])}",
                     secs(ilp["runtime_median_s"]), secs(ilp["runtime_max_s"]),
                     pctv(sa["gap_median_of_instance_medians_pct"]), pctv(sa["gap_max_pct"]),
                     secs(sa["runtime_median_s"]), ratio(sa["speedup_median"]),
                     pctv(gr["gap_median_pct"]), pctv(gr["gap_max_pct"]), secs(gr["runtime_median_s"]),
                     ratio(gr["speedup_median"])])
    out = ("# Scaling and optimality-gap experiment (synthetic, 5 instances per cell, SA 10 seeds)\n\n"
           + _src("results/scaling/summary.csv", "results/scaling/frontier.csv", "results/scaling/runs.csv")
           + "\nGap = (C(method) - C(ILP)) / C(ILP) against the proven-optimal tight ILP (D-054). "
             "SA gap (median) = median over instances of the median over seeds. Speed-up = ILP runtime / "
             "method runtime, median over instances.\n\n"
           + md_table(["set", "L", "n", "ILP proven", "ILP s (median)", "ILP s (max)", "SA gap % (median)",
                       "SA gap % (max run)", "SA s (median)", "SA speed-up", "Greedy+1-opt gap % (median)",
                       "Greedy+1-opt gap % (max)", "Greedy+1-opt s (median)", "Greedy+1-opt speed-up"], rows))
    out += "\n## Exact frontier (largest n with >= 4/5 proven optimal within 600 s)\n\n"
    out += md_table(["set", "L", "largest n tested", "finding", "ILP s (median at largest n)", "ILP s (max overall)"],
                    [[r["location_set"], int(r["n_locations"]), int(r["largest_n_tested"]), r["finding"],
                      secs(r["ilp_runtime_median_s_at_largest_n"]), secs(r["ilp_runtime_max_s_overall"])]
                     for _, r in f.iterrows()])
    q = scaling_qualifying()
    p = scaling_pooled()
    out += (f"\n## H2 condition: SA on n >= {H2_MIN_N}, L >= {H2_MIN_L} (ext set)\n\n"
            + md_table(["n", "instances proven", "SA gap % (median over seeds, median over instances)",
                        "SA speed-up (median)", "SA speed-up (min)"],
                       [[int(r["n"]), f"{int(r['ref_proven_instances'])}/{int(r['instances'])}",
                         pctv(r["gap_median_of_instance_medians_pct"]), ratio(r["speedup_median"]),
                         ratio(r["speedup_min"])] for _, r in q.iterrows()]
                       + [[f"pooled ({', '.join(map(str, p['n_values']))})", f"{p['instances']} instances",
                           pctv(p["gap_median_pct"]), ratio(p["speedup_median"]),
                           f"max {ratio(p['speedup_max'])}"]]))
    return out


def t_sweep() -> str:
    out = ("# Traffic-scale sweep (core set; inter-component volumes x s, internet unchanged)\n\n"
           + _src("results/sweep/summary.csv", "results/sweep_sensitivity/summary.csv")
           + "\nPenalty = (C(M) - C(ILP)) / C(ILP). H1 reduction = (C(B1) - C(ILP)) / C(B1). "
             "Selected grid points; the full 25-point grid is in the source files and figures F2/F3.\n\n")
    s = sweep_summary()
    rows = []
    for t in TOPOLOGIES:
        g = s[s["topology_id"] == t]
        for v in SWEEP_POINTS:
            r = g[_is(g["scale"], v)].iloc[0]
            rows.append([TOPO[t], scale(v), usd(r["edge_gb"]), usd(r["ilp_total_usd"]), int(r["ilp_providers_used"]),
                         int(r["b1_providers_used"]), pct(r["b1_penalty"]), pct(r["b1_alt_penalty"]),
                         pct(r["b2_best_penalty"]), pct(r["greedy_1opt_penalty"]), pct(r["sa_median_penalty"]),
                         pct(r["h1_reduction_vs_b1"]), pct(r["h1_reduction_vs_b1_alt"])])
    out += md_table(["topology", "s", "edge GB/month", "ILP USD/month", "ILP providers", "B1 providers",
                     "B1 penalty %", "B1-alt penalty %", "B2-best penalty %", "Greedy+1-opt penalty %",
                     "SA median penalty %", "H1 reduction vs B1 %", "H1 reduction vs B1-alt %"], rows)
    s1all = sweep_summary()
    out += (f"\nMain grid (rate x1): {len(s1all)} (topology, s) points; ILP providers used min "
            f"{int(s1all['ilp_providers_used'].min())}, max {int(s1all['ilp_providers_used'].max())}.\n")
    out += "\n## Whole grid (25 points, s = 0.01-100) per inter-region rate factor\n\n"
    rows = []
    for rate in (0.75, 1.0, 1.25):
        s = sweep_summary(rate)
        for t in TOPOLOGIES:
            g = s[s["topology_id"] == t]
            r1 = g[_is(g["scale"], 1.0)].iloc[0]
            rows.append([f"x{rate:g}", TOPO[t], len(g), int(g["ilp_providers_used"].min()),
                         int(g["ilp_providers_used"].max()), int((g["single_provider_optimal"].astype(str) == "True").sum()),
                         pct(r1["b1_penalty"]), pct(g["b1_penalty"].max()), pct(r1["h1_reduction_vs_b1"]),
                         pct(r1["h1_reduction_vs_b1_alt"])])
    out += md_table(["rate factor", "topology", "grid points", "ILP providers (min)", "ILP providers (max)",
                     "points where B2-best = ILP", "B1 penalty % at s = 1", "B1 penalty % (max over grid)",
                     "H1 reduction vs B1 % at s = 1", "H1 reduction vs B1-alt % at s = 1"], rows)
    return out


def t_crossover() -> str:
    c = crossover_rows()
    rows = [[r["source"], TOPO.get(r["topology_id"], r["topology_id"]), f"x{r['rate_factor']:g}", r["criterion"],
             r["b1_variant"], int(r["b1_providers_used"]), f"{scale(r['scale_min'])}-{scale(r['scale_max'])}",
             "" if pd.isna(r["s_star"]) else scale(r["s_star"]), r["crossover"], r["reason"]]
            for _, r in c.iterrows()]
    return ("# Crossover table (rules frozen in D-056)\n\n"
            + _src("results/sweep/crossover.csv", "results/sweep_sensitivity/crossover.csv")
            + "\ns* = smallest grid point from which the optimum uses 1 provider at every larger point. A crossover "
              "needs a multi-provider optimum below s* and a multi-provider B1 above it.\n\n"
            + md_table(["source", "topology", "rate", "criterion", "B1 variant", "B1 providers", "swept s",
                        "s*", "crossover", "reason"], rows))


# ---------------------------------------------------------------- replicated tables (M18)
def t_h1_replicated() -> str:
    """T-H1 of 04 §3: the replicated H1 table, mean +/- sd, 95 % CI and Wilcoxon p."""
    rows = []
    for r in HYP.h1_rows(H1_THRESHOLD):
        rho = r.rho
        rows.append([TOPO[r.topology_id], HYP.B1_LABEL[r.variant], rho.n,
                     usd(r.b1_usd.mean), usd(r.ilp_usd.mean),
                     f"{pctv(100 * rho.mean)} +/- {pctv(100 * rho.sd)}",
                     ci(100 * rho.ci_lo, 100 * rho.ci_hi), rho.ci_method,
                     pval(r.wilcoxon_p)])
    out = ("# T-H1  Replicated cost reduction of the ILP over B1 (core set, s = 1)\n\n"
           + _src("results/replicates/runs.csv", "results/replicates/summary.csv")
           + f"\nReduction rho = (C(B1) - C(ILP)) / C(B1), computed on each traffic draw and then "
             f"summarised (05 §4.1). The replication unit is the draw; the two costs on a row come "
             f"from the **same** draw, so the comparison is paired. CIs are 95 % percentile bootstrap "
             f"(B = 10,000). The Wilcoxon column is a one-sided signed-rank test of "
             f"rho > {100 * H1_THRESHOLD:g}%, the frozen H1 threshold.\n\n"
           + md_table(["topology", "baseline", "draws", "mean C(B1) USD/mo", "mean C(ILP) USD/mo",
                       "reduction % (mean +/- sd)", "95% CI %", "CI method", "Wilcoxon p"], rows))
    gap, per_instance = HYP.h2_gap()
    sp, wide = HYP.h2_speedup()
    out += (f"\n## T-H2  SA gap and speed-up in the qualifying cells (n >= {HYP.H2_MIN_N}, "
            f"|L| >= {HYP.H2_MIN_L})\n\n"
            + _src("results/scaling/runs.csv", "results/timing/summary.csv")
            + "\nThe gap sample is one value per qualifying synthetic instance (its median over SA "
              "seeds); the speed-up sample is one value per qualifying timing instance, each the mean "
              "of its ILP repeats over the mean of its SA repeats (D-077). Both CIs bootstrap over "
              "instances, so the two clauses have different n.\n\n"
            + md_table(["quantity", "instances", "mean", "sd", "median", "95% CI", "CI method"],
                       [["SA gap vs proven optimum, %", gap.n, pctv(gap.mean), pctv(gap.sd),
                         pctv(gap.median), ci(gap.ci_lo, gap.ci_hi), gap.ci_method],
                        ["SA speed-up t(ILP) / t(SA), x", sp.n, ratio(sp.mean), ratio(sp.sd),
                         ratio(sp.median), ci(sp.ci_lo, sp.ci_hi, ratio), sp.ci_method]]))
    out += ("\nPer qualifying timing instance:\n\n"
            + md_table(["instance", "n", "ILP s (mean of repeats)", "SA s (mean of repeats)",
                        "speed-up"],
                       [[f"`{r['instance_id']}`", int(r["n_components"]), secs(r["ilp_tight"]),
                         secs(r["sa"]), ratio(r["speedup"])] for _, r in wide.iterrows()]))
    out += (f"\nGap sample: {len(per_instance)} instances, worst instance median "
            f"{pctv(per_instance.max())}%, best {pctv(per_instance.min())}%.\n")
    rows = []
    for r in HYP.h3_rows():
        rows.append([TOPO[r.topology_id], HYP.B1_LABEL[r.variant], f"{r.crossovers}/{r.n_draws}",
                     pctv(100 * r.rate), ci(100 * r.rate_lo, 100 * r.rate_hi),
                     "yes" if r.base_crossover else "no",
                     "n/a" if r.threshold_gb is None else usd(r.threshold_gb.median)])
    out += (f"\n## T-H3  Per-draw crossover rate ({HYP.n_scale_points()}-point scale grid, "
            f"s = 0.01-100)\n\n"
            + _src("results/replicates/runs.csv", "results/sweep/crossover.csv")
            + "\nThe D-056 crossover rule applied to each draw's own sweep (D-078). The rate interval "
              "is the Wilson score interval, as `05 §5` requires for a proportion. \"base sweep\" is "
              "the undrawn M15 result. The frozen decision rates are 80% of draws for SUPPORTED and "
              "20% for REFUTED.\n\n"
            + md_table(["topology", "baseline", "draws with a crossover", "rate %", "95% Wilson CI %",
                        "base sweep", "median threshold GB/month"], rows))
    return out


def t_ablation() -> str:
    """T-ABL of 04 §3: which ingredient of the model causes the gain (M17)."""
    d = pd.read_csv(RES / "ablation" / "decomposition.csv")
    s = pd.read_csv(RES / "ablation" / "summary.csv")
    rows = []
    for (t, sc), g in d.groupby(["topology_id", "traffic_scale"], sort=True):
        g = g.sort_values("step")
        cells = [f"{usd(r['gain_usd_mean'])} {ci(r['gain_usd_ci_lo'], r['gain_usd_ci_hi'], usd)}"
                 for _, r in g.iterrows()]
        best = g.loc[g["gain_usd_mean"].idxmax()]
        rows.append([TOPO[t], scale(sc), int(g["n"].iloc[0]),
                     usd(g["total_gain_usd_mean"].iloc[0]), *cells,
                     f"step {int(best['step'])}"])
    out = ("# T-ABL  Gain decomposition: which ingredient causes C(B1) - C(ILP)\n\n"
           + _src("results/ablation/decomposition.csv", "results/ablation/summary.csv")
           + "\nG = C(B1) - C(ILP) on a draw, split along b1 -> b1_storage -> ilp_no_edge_egress -> "
             "ilp_full (06 §S12). Each step's gain is the paired per-draw difference of the two "
             "variants' **true** costs, so the three steps sum to G on every draw. Mean [95 % CI], "
             "USD/month.\n\n"
           + md_table(["topology", "s", "draws", "G USD/mo", "1 storage", "2 internet",
                       "3 egress coupling", "largest step"], rows))
    v = s[(s["metric"] == "penalty_vs_ilp_pct") & (abs(s["traffic_scale"] - 1.0) < TOL)]
    rows = []
    for t in TOPOLOGIES:
        g = v[v["topology_id"] == t].set_index("method")
        for m in ABLATION_VARIANTS:
            if m not in g.index:
                continue
            r = g.loc[m]
            rows.append([TOPO[t], m, int(r["n"]), pctv(r["mean"]), pctv(r["sd"]),
                         ci(r["ci_lo"], r["ci_hi"])])
    out += ("\n## Cost penalty of each ablated variant vs the full ILP (s = 1, core)\n\n"
            "Every variant's assignment is scored by the full `placement/cost.py::evaluate`, so a "
            "variant that ignores a cost term is still charged for it (D-071).\n\n"
            + md_table(["topology", "variant", "draws", "penalty % (mean)", "sd",
                        "95% CI %"], rows))
    return out


def t_sensitivity() -> str:
    """How the ILP's saving over B1 moves with the price world (M17 sensitivity, D-073)."""
    from analysis import figures  # the figure CSV is the committed, audited form of these numbers
    d = figures.f7_data()
    rows = []
    for t in TOPOLOGIES:
        for _, r in d[(d["topology_id"] == t)
                      & (d["locs_per_provider"] == figures.F7_BASE_K)].sort_values(
                          "egress_mult").iterrows():
            rows.append([TOPO[t], f"x{r['egress_mult']:g}", int(r["locs_per_provider"]),
                         int(r["n"]), pctv(r["mean"]), ci(r["ci_lo"], r["ci_hi"])])
    out = ("# Sensitivity of the ILP's saving over B1 to the price world\n\n"
           + _src("results/sensitivity/runs.csv", "results/sensitivity/summary.csv",
                  "figures/F7_sensitivity.csv")
           + "\nSaving = (C(B1) - C(ILP)) / C(B1) on the same draw. The location grids nest, so "
             f"k = {figures.F7_BASE_K} locations per provider is exactly the core set and multiplier "
             "x1 is the real snapshot (D-073).\n\n"
           + md_table(["topology", "egress multiplier", "locations/provider", "draws",
                       "saving % (mean)", "95% CI %"], rows))
    rows = []
    for t in TOPOLOGIES:
        for _, r in d[(d["topology_id"] == t)
                      & (abs(d["egress_mult"] - figures.F7_BASE_MULT) < TOL)].sort_values(
                          "locs_per_provider").iterrows():
            rows.append([TOPO[t], f"x{r['egress_mult']:g}", int(r["locs_per_provider"]),
                         int(r["n"]), pctv(r["mean"]), ci(r["ci_lo"], r["ci_hi"])])
    out += ("\n## Saving vs the number of locations per provider (real egress prices)\n\n"
            + md_table(["topology", "egress multiplier", "locations/provider", "draws",
                        "saving % (mean)", "95% CI %"], rows))
    return out


TABLES = {"cost_model.md": t_cost_model, "baselines.md": t_baselines, "exact.md": t_exact,
          "scaling.md": t_scaling, "sweep.md": t_sweep, "crossover.md": t_crossover,
          "h1_replicated.md": t_h1_replicated, "ablation.md": t_ablation,
          "sensitivity.md": t_sensitivity}


def render() -> dict[str, str]:
    return {name: fn() for name, fn in TABLES.items()}


# ---------------------------------------------------------------- LaTeX for the paper
LATEX_ESCAPE = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _tex_cell(cell: str) -> str:
    """Escape one Markdown cell for LaTeX, keeping `code` spans and **bold** readable."""
    parts, out = re.split(r"(`[^`]*`)", cell), []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            inner = "".join(LATEX_ESCAPE.get(c, c) for c in part[1:-1])
            out.append(r"\texttt{" + inner + "}")
        else:
            out.append("".join(LATEX_ESCAPE.get(c, c) for c in part))
    return "".join(out).replace(r"\*\*", "")


def to_latex(md: str, name: str) -> str:
    """Turn one generated Markdown table file into LaTeX tabulars for `paper/`.

    Only the tables are carried over: the prose around them belongs to the paper's own text,
    and a caption line records which Markdown file (and therefore which results file) it came
    from, so a number in the paper can still be traced back (I1).
    """
    blocks, rows, out = [], [], []
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        else:
            if rows:
                blocks.append(rows)
            rows = []
    for i, block in enumerate(blocks, 1):
        header, body = block[0], [r for r in block[2:]]
        cols = "l" + "r" * (len(header) - 1)
        out += [f"% generated by `python -m analysis.tables --latex` from docs/report/tables/{name}",
                r"\begin{table}[t]", r"\centering", r"\small",
                r"\begin{tabular}{" + cols + "}", r"\toprule",
                " & ".join(_tex_cell(c) for c in header) + r" \\", r"\midrule"]
        out += [" & ".join(_tex_cell(c) for c in row) + r" \\" for row in body]
        out += [r"\bottomrule", r"\end{tabular}",
                r"\caption{" + _tex_cell(name.replace(".md", "")) + f" ({i} of {len(blocks)}). "
                r"Generated; see \texttt{docs/report/tables/" + _tex_cell(name) + "}.}",
                r"\label{tab:" + name.replace(".md", "") + f"-{i}" + "}", r"\end{table}", ""]
    return "\n".join(out)


def render_latex() -> dict[str, str]:
    return {name.replace(".md", ".tex"): to_latex(text, name) for name, text in render().items()}


def check_or_write(outputs: dict[str, Path | str], check: bool, label: str) -> int:
    """Shared by tables/verdicts/results_text: write {path: text}, or diff it with --check."""
    bad = []
    for path, text in outputs.items():
        path = Path(path)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
                bad.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if check:
        print(f"{label} --check:", f"OK ({len(outputs)}/{len(outputs)} identical)" if not bad else f"DRIFT in {bad}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--latex", action="store_true",
                    help="also write the LaTeX form of every table to paper/tables/")
    args = ap.parse_args(argv)
    outputs = {OUT / k: v for k, v in render().items()}
    if args.latex:
        outputs |= {PAPER / k: v for k, v in render_latex().items()}
    return check_or_write(outputs, args.check, "tables")


if __name__ == "__main__":
    sys.exit(main())
