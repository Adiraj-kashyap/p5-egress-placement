"""Shared loaders for the replicated (plan-v2) results, used by M18's figures, tables and
verdicts so that all three read the same numbers the same way.

Everything here is **per draw**: a traffic draw is the replication unit (05 §2), and a
randomised method's value on a draw is the median over its seeds first (D-068), so every
method contributes exactly one value per draw and every comparison is paired. Nothing in
this module computes a mean, a spread or an interval — that is `analysis.stats`'s job.

    draw_frame()        one row per (topology, scale, method, draw): total, providers, ...
    cost_parts(s)       the same, with the four cost components (SA: its median-total run)
    reduction(...)      per-draw rho = (C(baseline) - C(ILP)) / C(baseline), the H1 quantity
    crossover_by_draw() the D-056 crossover rule applied to each draw's own scale sweep
    base_edge_gb()      inter-component GB/month at s = 1, per topology
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from analysis.replicate_summary import REPLICATES, read_runs
from pricing.common import ROOT

RES = ROOT / "results"
REF_METHOD = "ilp_tight"
TOPOLOGIES = ["t1_three_tier", "t2_pipeline", "t3_microservices"]
TOPO = {"t1_three_tier": "T1", "t2_pipeline": "T2", "t3_microservices": "T3"}
TOPO_LABEL = {"t1_three_tier": "T1 three-tier", "t2_pipeline": "T2 pipeline",
              "t3_microservices": "T3 microservices"}
METHOD_LABEL = {"ilp_tight": "ILP (exact)", "sa": "SA", "greedy_1opt": "Greedy+1-opt",
                "b1": "B1", "b1_alt": "B1-alt", "b2_best": "B2-best",
                "ilp_full": "ILP (exact)", "b1_storage": "B1+storage",
                "ilp_no_edge_egress": "ILP, no edge egress", "ilp_no_internet": "ILP, no internet",
                "ilp_undirected": "ILP, undirected egress", "ilp_single_provider": "ILP, 1 provider",
                "sa_random_init": "SA (random init)", "sa_no_swap": "SA (no swap)"}
COST_PARTS = ["compute_usd", "storage_usd", "egress_usd", "internet_usd"]
S1 = 1.0  # the "measured or stated traffic" operating point


def _num(x: str) -> float:
    return float(x)


def draw_frame() -> pd.DataFrame:
    """One row per (topology, location set, traffic scale, method, draw), seeds collapsed.

    Columns: topology_id, location_set, traffic_scale (float), method, draw_id (int),
    total_usd, egress_share, providers_used, runtime_s, n_seeds.
    """
    bucket: dict[tuple, list[dict]] = defaultdict(list)
    for r in read_runs(REPLICATES):
        bucket[(r["topology_id"], r["location_set"], r["traffic_scale"], r["method"],
                r["draw_id"])].append(r)
    rows = []
    for (t, loc, s, m, d), rs in bucket.items():
        rows.append({
            "topology_id": t, "location_set": loc, "traffic_scale": _num(s), "method": m,
            "draw_id": int(d),
            "total_usd": statistics.median(_num(r["total_usd"]) for r in rs),
            "egress_share": statistics.median(_num(r["egress_share"]) for r in rs),
            "providers_used": statistics.median(_num(r["providers_used"]) for r in rs),
            "runtime_s": statistics.median(_num(r["runtime_s"]) for r in rs),
            "n_seeds": len(rs)})
    return pd.DataFrame(rows).sort_values(
        ["topology_id", "location_set", "traffic_scale", "method", "draw_id"]).reset_index(drop=True)


def cost_parts(scale: float = S1) -> pd.DataFrame:
    """Per-draw cost components at one traffic scale (F1's source).

    A randomised method has no meaningful "median breakdown", so its draw is represented by
    the actual run with the median total over its seeds (ties go to the smallest seed). That
    keeps compute + storage + egress + internet equal to the total on every row.
    """
    bucket: dict[tuple, list[dict]] = defaultdict(list)
    for r in read_runs(REPLICATES):
        if abs(_num(r["traffic_scale"]) - scale) > 1e-12:
            continue
        bucket[(r["topology_id"], r["method"], int(r["draw_id"]))].append(r)
    rows = []
    for (t, m, d), rs in bucket.items():
        rs = sorted(rs, key=lambda r: (_num(r["total_usd"]), int(r["seed"] or 0)))
        r = rs[(len(rs) - 1) // 2]
        rows.append({"topology_id": t, "method": m, "draw_id": d, "n_seeds": len(rs),
                     **{c: _num(r[c]) for c in COST_PARTS},
                     "total_usd": _num(r["total_usd"])})
    return pd.DataFrame(rows).sort_values(["topology_id", "method", "draw_id"]).reset_index(drop=True)


def paired(df: pd.DataFrame, topology: str, scale: float, methods: list[str],
           column: str = "total_usd") -> dict[str, list[float]]:
    """{method: one value per draw}, aligned by draw id across the requested methods.

    Only draws for which *every* requested method has a value are kept, so the returned
    lists are element-by-element paired and can go straight into `stats.paired_*`.
    """
    g = df[(df["topology_id"] == topology) & (abs(df["traffic_scale"] - scale) < 1e-12)
           & df["method"].isin(methods)]
    by_method = {m: dict(zip(h["draw_id"], h[column])) for m, h in g.groupby("method")}
    missing = [m for m in methods if m not in by_method]
    if missing:
        raise ValueError(f"{topology} s={scale}: no rows for {missing}")
    draws = sorted(set.intersection(*(set(v) for v in by_method.values())))
    return {m: [by_method[m][d] for d in draws] for m in methods}


def reduction(df: pd.DataFrame, topology: str, baseline: str = "b1",
              scale: float = S1) -> list[float]:
    """Per-draw H1 reduction rho_d = (C(baseline) - C(ILP)) / C(baseline) (05 §4.1)."""
    p = paired(df, topology, scale, [baseline, REF_METHOD])
    return [(b - i) / b for b, i in zip(p[baseline], p[REF_METHOD])]


def crossover_by_draw(df: pd.DataFrame, b1_variant: str = "b1") -> pd.DataFrame:
    """The D-056 crossover rule applied to each draw's own scale sweep (05 §4.3, D-078).

    Per (topology, draw): s* is the smallest swept scale from which the optimum uses one
    provider at every larger scale. A crossover needs s* to exist with a multi-provider
    optimum below it and a multi-provider baseline at and above it. Columns: topology_id,
    draw_id, s_star, T_gb_month, crossover (bool), reason.
    """
    base = base_edge_gb()
    out = []
    for (t, d), g in df[df["method"].isin([REF_METHOD, b1_variant])].groupby(
            ["topology_id", "draw_id"]):
        pts = g.pivot_table(index="traffic_scale", columns="method", values="providers_used")
        pts = pts.sort_index()
        if REF_METHOD not in pts or b1_variant not in pts:
            continue
        ilp = pts[REF_METHOD].to_list()
        b1 = pts[b1_variant].to_list()
        scales = list(pts.index)
        idx = None
        for i in range(len(scales) - 1, -1, -1):
            if ilp[i] == 1:
                idx = i
            else:
                break
        row = {"topology_id": t, "draw_id": int(d), "s_star": "", "T_gb_month": "",
               "crossover": False, "reason": ""}
        if idx is None:
            row["reason"] = "optimum multi-provider at the largest scale"
        else:
            row["s_star"] = scales[idx]
            row["T_gb_month"] = base[t] * scales[idx]
            if idx == 0:
                row["reason"] = "optimum single-provider at every scale (no inversion in range)"
            elif not all(v > 1 for v in b1[idx:]):
                row["reason"] = f"{b1_variant} is single-provider above s_star"
            else:
                row["crossover"] = True
                row["reason"] = "optimum multi below s_star, single from s_star; baseline multi-provider"
        out.append(row)
    return pd.DataFrame(out).sort_values(["topology_id", "draw_id"]).reset_index(drop=True)


def base_edge_gb() -> dict[str, float]:
    """Inter-component GB/month at s = 1 per topology (from the M15 sweep summary)."""
    s = pd.read_csv(RES / "sweep" / "summary.csv")
    return {t: float(g["base_edge_gb"].iloc[0]) for t, g in s.groupby("topology_id")}


def summary(path: Path = REPLICATES / "summary.csv") -> pd.DataFrame:
    """The committed replicate summary (one row per configuration and metric)."""
    return pd.read_csv(path)


def timing_instance_means() -> pd.DataFrame:
    """One row per (instance, location set, n, method): the mean of its 3 timing repeats.

    This is the timing-repeat mean that 05 §4.2 asks for; the replication unit above it is
    the instance. Taken from the committed summary so the mean is `stats.summarise`'s.
    """
    t = pd.read_csv(RES / "timing" / "summary.csv")
    t = t[t["metric"] == "runtime_s"]
    return t[["instance_id", "location_set", "n_components", "method", "n", "mean", "sd"]].rename(
        columns={"n": "n_repeats", "mean": "runtime_mean_s", "sd": "runtime_sd_s"}).reset_index(drop=True)


def sa_traces() -> pd.DataFrame:
    """Every SA seed's convergence trace on T3 (results/heuristics/sa_traces.csv, D-079)."""
    path = RES / "heuristics" / "sa_traces.csv"
    if not path.exists():
        raise SystemExit("missing results/heuristics/sa_traces.csv: run "
                         "`python -m experiments.run_annealing --traces`")
    with path.open(newline="", encoding="utf-8") as f:
        return pd.DataFrame(list(csv.DictReader(f))).astype(
            {"seed": int, "temp_step": int, "moves": int, "temperature": float,
             "current_usd": float, "best_usd": float, "ilp_optimum_usd": float})
