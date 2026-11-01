"""Report figures (M18 step 1, 03 §S10, 05 §5/§6).

Every figure has a pure `fN_data()` that builds the plotted numbers from committed results
files and a `fN_plot(df, path)` that draws them. Each one is written three ways — PNG at
200 dpi, PDF for the paper, and the CSV of exactly what was plotted — and every CSV carries
`n`, `mean` and a 95 % interval per plotted point, because 05 §6 forbids plotting a single
run anywhere and 04 §5.2 audits the CSVs for it. All intervals come from `analysis.stats`.

    R2-1 total monthly cost vs traffic scale, CI bands    results/replicates
    F0   SA convergence, mean +/- CI over seeds           results/heuristics/sa_traces.csv
    F1   cost breakdown at s = 1                          results/replicates
    F2   penalty of the baselines vs ILP across scales    results/replicates
    F3   providers used by the ILP + crossover rate       results/replicates
    F4   runtime vs n per method per L                    results/timing
    F5   optimality gap vs n (boxes over instances/seeds) results/scaling
    F6   gain decomposition waterfall                     results/ablation
    F7   sensitivity of the ILP's saving                  results/sensitivity

    python -m analysis.figures            # write PNG + PDF + CSV for every figure
    python -m analysis.figures --check    # regenerate the CSVs in memory, exit 1 on drift
    python -m analysis.figures --lint     # 04 §5.2: every CSV has mean, spread and n >= 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis import ablation_summary, replicated as R, scaling_summary  # noqa: E402
from analysis.stats import summarise, wilson  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
RES = ROOT / "results"

TOPOLOGIES = R.TOPOLOGIES
TOPO_LABEL = R.TOPO_LABEL
METHOD_LABEL = R.METHOD_LABEL
COST_PARTS = R.COST_PARTS

# Reference categorical palette of the dataviz skill, slots 1-4 in fixed order (never cycled).
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
HATCH = ["", "//", "\\\\", ".."]  # secondary encoding, so identity is not colour-only
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
METHOD_COLOR = {"ilp_tight": SLOT[0], "ilp_full": SLOT[0], "sa": SLOT[1], "greedy_1opt": SLOT[2],
                "b1": SLOT[1], "b1_alt": SLOT[3], "b2_best": SLOT[2], "b1_storage": SLOT[3],
                "ilp_no_edge_egress": SLOT[2]}
DPI = 200
STAT_COLS = ["n", "mean", "sd", "sem", "median", "ci_lo", "ci_hi", "ci_method"]
CAPTION = ("Mean over R = {n} traffic draws; error bars/bands are 95 % bootstrap CIs. "
           "Snapshot 2026-09-21, core location set.")


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _save(fig, stem: Path) -> None:
    """Write the figure as both PNG (200 dpi) and PDF (paper), then close it."""
    for ext in ("png", "pdf"):
        fig.savefig(stem.with_suffix(f".{ext}"), dpi=DPI, facecolor=SURFACE,
                    metadata={"Software": None} if ext == "png" else {"Creator": None})
    plt.close(fig)


def _suptitle(fig, text: str, width: int | None = None) -> None:
    """Figure title + caption, wrapped so a long caption never runs off the canvas."""
    import textwrap
    width = width or int(fig.get_figwidth() * 12)  # ~12 characters per inch at fontsize 9
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width) or [""]
    fig.suptitle("\n".join(lines), fontsize=9, color=INK)


def to_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, lineterminator="\n")


def _stats_row(values, **keys) -> dict:
    """One tidy summary row: the grouping keys plus `analysis.stats.summarise` of `values`."""
    s = summarise(values)
    return keys | {"n": s.n, "mean": round(s.mean, 8), "sd": round(s.sd, 8),
                   "sem": round(s.sem, 8), "median": round(s.median, 8),
                   "ci_lo": round(s.ci_lo, 8), "ci_hi": round(s.ci_hi, 8),
                   "ci_method": s.ci_method}


def _errorbars(ax, x, g, color, label, marker="o", ls="-", band=True):
    """Draw a mean line with its 95 % CI as a shaded band (or as bars when band=False)."""
    if band:
        _bands(ax, [(x, g, color)])
        _lines(ax, [(x, g, color, label, marker, ls)])
    else:
        ax.errorbar(x, g["mean"], yerr=[g["mean"] - g["ci_lo"], g["ci_hi"] - g["mean"]],
                    color=color, marker=marker, markersize=4, linestyle=ls, linewidth=2,
                    capsize=3, label=label)


def _bands(ax, series) -> None:
    """Shade every series' 95 % CI. Call this for ALL series before drawing any line, so a
    later series' band cannot hide an earlier series' mean."""
    for x, g, color in series:
        ax.fill_between(x, g["ci_lo"], g["ci_hi"], color=color, alpha=0.14, linewidth=0)


def _lines(ax, series) -> None:
    """Draw every series' mean on top of the bands."""
    for x, g, color, label, marker, ls in series:
        ax.plot(x, g["mean"], color=color, marker=marker, markersize=4, linestyle=ls,
                linewidth=2, label=label, zorder=3)


# ---------------------------------------------------------------- R2-1
R21_METHODS = ["ilp_tight", "sa", "greedy_1opt", "b1", "b2_best"]
# R2-1 is the only figure that puts the baselines and the solvers on one axes, so it needs
# five distinct hues; METHOD_COLOR reuses slots across the baseline-only and solver-only figures.
R21_STYLE = {"ilp_tight": (SLOT[0], "D", "-"), "sa": (SLOT[1], "o", "-"),
             "greedy_1opt": (SLOT[2], "^", "--"), "b1": (SLOT[3], "s", "-"),
             "b2_best": ("#8a63d2", "v", "--")}


def r21_data() -> pd.DataFrame:
    """Total monthly cost of each method at every swept traffic scale, per topology.

    This is the review-2 "baseline and proposed on the same axes" graph, so the baselines and
    the proposed optimum are summarised identically: mean over the 30 draws with a bootstrap CI.
    """
    df = R.draw_frame()
    base = R.base_edge_gb()
    cx = R.crossover_by_draw(df)
    rate = {t: float(g["crossover"].mean()) for t, g in cx.groupby("topology_id")}
    rows = []
    for t in TOPOLOGIES:
        for s in sorted(df["traffic_scale"].unique()):
            for m in R21_METHODS:
                g = df[(df["topology_id"] == t) & (df["method"] == m)
                       & (abs(df["traffic_scale"] - s) < 1e-12)]
                if g.empty:
                    raise ValueError(f"R2-1: no {m} rows for {t} at s = {s}")
                rows.append(_stats_row(g["total_usd"], topology_id=t, traffic_scale=s,
                                       edge_gb=round(base[t] * s, 6), method=m,
                                       crossover_rate=rate[t]))
    return pd.DataFrame(rows)


def r21_plot(df: pd.DataFrame, stem: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.2), constrained_layout=True)
    for ax, t in zip(axes, TOPOLOGIES):
        g = df[df["topology_id"] == t]
        series = []
        for m in R21_METHODS:
            h = g[g["method"] == m].sort_values("traffic_scale")
            color, marker, ls = R21_STYLE[m]
            series.append((h["traffic_scale"], h, color, METHOD_LABEL[m], marker, ls))
        _bands(ax, [(x, h, c) for x, h, c, _, _, _ in series])
        _lines(ax, series)
        if g["crossover_rate"].iloc[0] == 0:
            ax.text(0.97, 0.03, "no crossover in any draw", transform=ax.transAxes,
                    fontsize=7, color=INK2, va="bottom", ha="right")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(TOPO_LABEL[t], fontsize=10, color=INK)
        ax.set_xlabel("inter-component traffic scale s", color=INK2)
        _style(ax)
    axes[0].set_ylabel("total USD / month", color=INK2)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    n = int(df["n"].iloc[0])
    _suptitle(fig, "R2-1  Total monthly cost of each method vs traffic scale.  " + CAPTION.format(n=n)
                 + "\nThe bands are the spread of the drawn traffic, which every method shares on a "
                   "given draw; the paired differences between methods are in F2.")
    _save(fig, stem)


# ---------------------------------------------------------------- F0
F0_MIN_SEEDS = 3  # a step plotted from fewer seeds than this would be close to a single run


def f0_data() -> pd.DataFrame:
    """SA convergence on T3: mean +/- CI over seeds at each temperature step (D-079).

    Seeds stop at different temperatures, so a step is kept only while at least
    F0_MIN_SEEDS seeds are still running; later steps are dropped rather than plotted thin.
    """
    tr = R.sa_traces()
    opt = float(tr["ilp_optimum_usd"].iloc[0])
    rows = []
    for step, g in tr.groupby("temp_step"):
        if len(g) < F0_MIN_SEEDS:
            continue
        for series in ("best_usd", "current_usd", "temperature", "moves"):
            rows.append(_stats_row(g[series].astype(float), temp_step=int(step), series=series,
                                   ilp_optimum_usd=round(opt, 6)))
    return pd.DataFrame(rows).sort_values(["series", "temp_step"]).reset_index(drop=True)


def f0_plot(df: pd.DataFrame, stem: Path) -> None:
    best = df[df["series"] == "best_usd"].sort_values("temp_step")
    cur = df[df["series"] == "current_usd"].sort_values("temp_step")
    temp = df[df["series"] == "temperature"].sort_values("temp_step")
    opt = float(df["ilp_optimum_usd"].iloc[0])
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5.6), sharex=True, constrained_layout=True,
                                   gridspec_kw={"height_ratios": [2.2, 1]})
    for ax in (ax1, ax2):
        _style(ax)
    _errorbars(ax1, cur["temp_step"], cur, SLOT[0], "current (mean over seeds)", marker="")
    _errorbars(ax1, best["temp_step"], best, SLOT[1], "best so far (mean over seeds)", marker="")
    ax1.axhline(opt, color=INK2, linewidth=1, linestyle=(0, (4, 3)), label="ILP optimum")
    ax1.annotate(f"ILP optimum {opt:,.2f}", (best["temp_step"].max(), opt), xytext=(0, 5),
                 textcoords="offset points", ha="right", va="bottom", fontsize=8, color=INK2)
    ax1.set_ylabel("USD / month", color=INK2)
    ax1.legend(fontsize=8, frameon=False, loc="upper right")
    ax2.plot(temp["temp_step"], temp["mean"], color=SLOT[0], linewidth=1.5)
    ax2.set_yscale("log")
    ax2.set_ylabel("temperature", color=INK2)
    ax2.set_xlabel("temperature step", color=INK2)
    n = int(best["n"].max())
    _suptitle(fig, f"F0  SA convergence on T3 (core). Mean over {n} seeds; bands are 95 % bootstrap CIs; "
                 f"steps with < {F0_MIN_SEEDS} seeds still running are dropped.")
    _save(fig, stem)


# ---------------------------------------------------------------- F1
F1_METHODS = ["ilp_tight", "b1", "b1_alt", "b2_best", "greedy_1opt", "sa"]


def f1_data() -> pd.DataFrame:
    """Cost breakdown at s = 1: mean of each component and of the total, with CIs."""
    cp = R.cost_parts(R.S1)
    rows = []
    for t in TOPOLOGIES:
        for m in F1_METHODS:
            g = cp[(cp["topology_id"] == t) & (cp["method"] == m)]
            if g.empty:
                raise ValueError(f"F1: no {m} rows for {t} at s = 1")
            for part in COST_PARTS + ["total_usd"]:
                rows.append(_stats_row(g[part], topology_id=t, method=m, component=part))
    return pd.DataFrame(rows)


def f1_plot(df: pd.DataFrame, stem: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.4), constrained_layout=True)
    for ax, t in zip(axes, TOPOLOGIES):
        x = np.arange(len(F1_METHODS))
        bottom = np.zeros(len(F1_METHODS))
        for i, c in enumerate(COST_PARTS):
            v = np.array([float(df[(df["topology_id"] == t) & (df["method"] == m)
                                   & (df["component"] == c)]["mean"].iloc[0]) for m in F1_METHODS])
            ax.bar(x, v, bottom=bottom, width=0.62, color=SLOT[i], hatch=HATCH[i],
                   edgecolor=SURFACE, linewidth=1.0, label=c.replace("_usd", ""))
            bottom += v
        tot = df[(df["topology_id"] == t) & (df["component"] == "total_usd")].set_index("method")
        tot = tot.loc[F1_METHODS]
        ax.errorbar(x, tot["mean"], yerr=[tot["mean"] - tot["ci_lo"], tot["ci_hi"] - tot["mean"]],
                    fmt="none", ecolor=INK, elinewidth=1.2, capsize=3)
        for xi, m in zip(x, F1_METHODS):
            ax.text(xi, float(tot.loc[m, "ci_hi"]), f"{float(tot.loc[m, 'mean']):,.0f}",
                    ha="center", va="bottom", fontsize=7, color=INK)
        ax.set_xticks(x, [METHOD_LABEL[m] for m in F1_METHODS], rotation=30, ha="right")
        ax.set_title(TOPO_LABEL[t], fontsize=10, color=INK)
        ax.set_ylim(0, float(tot["ci_hi"].max()) * 1.14)
        _style(ax)
    axes[0].set_ylabel("USD / month", color=INK2)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8, frameon=False, loc="outside lower center", ncols=4)
    n = int(df["n"].iloc[0])
    _suptitle(fig, "F1  Monthly cost breakdown by method at s = 1.  Bars are component means; "
                 "error bars are the 95 % bootstrap CI of the total.  " + CAPTION.format(n=n))
    _save(fig, stem)


# ---------------------------------------------------------------- F2
F2_METHODS = ["b1", "b1_alt", "b2_best", "greedy_1opt", "sa"]


def f2_data() -> pd.DataFrame:
    """Penalty (C(M) - C(ILP)) / C(ILP) vs traffic scale, paired per draw."""
    s = R.summary()
    s = s[(s["metric"] == "penalty_vs_ilp_pct") & s["method"].isin(F2_METHODS)]
    s["topology_id"] = pd.Categorical(s["topology_id"], TOPOLOGIES, ordered=True)
    s["method"] = pd.Categorical(s["method"], F2_METHODS, ordered=True)
    out = s.sort_values(["topology_id", "method", "traffic_scale"])
    return out.astype({"topology_id": str, "method": str}).reset_index(drop=True)


def f2_plot(df: pd.DataFrame, stem: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9), constrained_layout=True)
    for ax, t in zip(axes, TOPOLOGIES):
        g = df[df["topology_id"] == t]
        for m in ["b1", "b1_alt", "b2_best"]:
            h = g[g["method"] == m].sort_values("traffic_scale")
            _errorbars(ax, h["traffic_scale"], h, METHOD_COLOR[m], METHOD_LABEL[m],
                       marker="s" if m == "b1_alt" else "o", ls="--" if m == "b1_alt" else "-")
        ax.set_xscale("log")
        ax.set_title(TOPO_LABEL[t], fontsize=10, color=INK)
        ax.set_xlabel("inter-component traffic scale s", color=INK2)
        _style(ax)
    axes[0].set_ylabel("penalty vs ILP optimum, %", color=INK2)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    n = int(df["n"].iloc[0])
    _suptitle(fig, "F2  Egress penalty of the baselines vs traffic scale.  " + CAPTION.format(n=n))
    _save(fig, stem)


# ---------------------------------------------------------------- F3
F3_METHODS = ["ilp_tight", "b1", "b1_alt"]


def f3_data() -> pd.DataFrame:
    """Providers used vs scale (mean with CI), plus the per-draw crossover rate (Wilson CI)."""
    s = R.summary()
    s = s[(s["metric"] == "providers_used") & s["method"].isin(F3_METHODS)]
    rows = []
    for t in TOPOLOGIES:
        for m in F3_METHODS:
            for _, r in s[(s["topology_id"] == t) & (s["method"] == m)].sort_values(
                    "traffic_scale").iterrows():
                rows.append({"topology_id": t, "panel": "providers_used", "method": m,
                             "traffic_scale": r["traffic_scale"],
                             **{c: r[c] for c in STAT_COLS}})
    df = R.draw_frame()
    for variant in ("b1", "b1_alt"):
        cx = R.crossover_by_draw(df, variant)
        for t, g in cx.groupby("topology_id"):
            k, n = int(g["crossover"].sum()), len(g)
            p, lo, hi = wilson(k, n)
            rows.append({"topology_id": t, "panel": "crossover_rate", "method": variant,
                         "traffic_scale": "", "n": n, "mean": round(p, 8), "sd": "",
                         "sem": "", "median": "", "ci_lo": round(lo, 8), "ci_hi": round(hi, 8),
                         "ci_method": "wilson", "crossovers": k})
    return pd.DataFrame(rows)


def f3_plot(df: pd.DataFrame, stem: Path) -> None:
    # The two panels share one tidy CSV, so the numeric columns arrive as objects (the
    # crossover rows leave sd/sem/median empty); cast the columns each panel actually plots.
    num = ["traffic_scale", "mean", "ci_lo", "ci_hi"]
    prov = df[df["panel"] == "providers_used"].astype({c: float for c in num})
    rate = df[df["panel"] == "crossover_rate"].astype({c: float for c in num[1:]})
    fig, axes = plt.subplots(1, 4, figsize=(13.5, 3.6), constrained_layout=True,
                             gridspec_kw={"width_ratios": [1, 1, 1, 0.7]})
    for ax, t in zip(axes[:3], TOPOLOGIES):
        g = prov[prov["topology_id"] == t]
        for m, off in (("b1", 0.06), ("b1_alt", -0.06), ("ilp_tight", 0.0)):
            h = g[g["method"] == m].sort_values("traffic_scale")
            ax.fill_between(h["traffic_scale"], h["ci_lo"] + off, h["ci_hi"] + off,
                            color=METHOD_COLOR[m], alpha=0.18, linewidth=0)
            ax.plot(h["traffic_scale"], h["mean"] + off, color=METHOD_COLOR[m],
                    marker="D" if m == "ilp_tight" else "o", markersize=4, linewidth=2,
                    label=METHOD_LABEL[m])
        ax.set_xscale("log")
        ax.set_yticks([1, 2, 3])
        ax.set_ylim(0.5, 3.3)
        ax.set_title(TOPO_LABEL[t], fontsize=10, color=INK)
        ax.set_xlabel("inter-component traffic scale s", color=INK2)
        _style(ax)
    axes[0].set_ylabel("providers used", color=INK2)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    ax = axes[3]
    g = rate[rate["method"] == "b1"].set_index("topology_id").loc[TOPOLOGIES]
    x = np.arange(len(TOPOLOGIES))
    ax.bar(x, g["mean"], width=0.6, color=SLOT[0], edgecolor=SURFACE)
    ax.errorbar(x, g["mean"], yerr=[g["mean"] - g["ci_lo"], g["ci_hi"] - g["mean"]], fmt="none",
                ecolor=INK, elinewidth=1.2, capsize=3)
    for xi, (_, r) in zip(x, g.iterrows()):
        ax.text(xi, float(r["ci_hi"]), f"{int(r['crossovers'])}/{int(r['n'])}", ha="center",
                va="bottom", fontsize=7, color=INK)
    ax.set_xticks(x, [R.TOPO[t] for t in TOPOLOGIES])
    ax.set_ylim(0, max(0.25, float(g["ci_hi"].max()) * 1.25))
    ax.set_ylabel("crossover rate over draws", color=INK2)
    ax.set_title("crossover rate (95 % Wilson)", fontsize=10, color=INK)
    _style(ax)
    n = int(prov["n"].iloc[0])
    _suptitle(fig, "F3  Providers used by the ILP optimum and by B1 vs traffic scale (lines offset by "
                 "+/-0.06 for visibility), and the share of draws with a crossover.  "
                 + CAPTION.format(n=n))
    _save(fig, stem)


# ---------------------------------------------------------------- F4
F4_METHODS = ["ilp_tight", "sa", "greedy_1opt"]


def f4_data() -> pd.DataFrame:
    """Runtime vs n per method per location set: mean over instances of the repeat means.

    The replication unit is the instance (3 per cell) and each instance's value is the mean
    of its 3 timing repeats (05 §5). All rows carry the same machine tag (I9).
    """
    t = R.timing_instance_means()
    rows = []
    for L in ("core", "ext"):
        for n in sorted(t["n_components"].unique()):
            for m in F4_METHODS:
                g = t[(t["location_set"] == L) & (t["n_components"] == n) & (t["method"] == m)]
                if g.empty:
                    continue
                rows.append(_stats_row(g["runtime_mean_s"], location_set=L, n_components=int(n),
                                       method=m, n_instances=len(g),
                                       n_repeats=int(g["n_repeats"].iloc[0])))
    return pd.DataFrame(rows)


def f4_plot(df: pd.DataFrame, stem: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True, sharey=True)
    for ax, L in zip(axes, ["core", "ext"]):
        g = df[df["location_set"] == L]
        for m in F4_METHODS:
            h = g[g["method"] == m].sort_values("n_components")
            _errorbars(ax, h["n_components"], h, METHOD_COLOR[m], METHOD_LABEL[m], band=False)
        ax.set_yscale("log")
        ax.set_title(f"{L} set", fontsize=10, color=INK)
        ax.set_xlabel("components n", color=INK2)
        ax.set_xticks(sorted(g["n_components"].unique()))
        _style(ax)
    axes[0].set_ylabel("wall-clock seconds", color=INK2)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    k = int(df["n_repeats"].iloc[0])
    _suptitle(fig, f"F4  Solver runtime vs problem size. Mean over {int(df['n'].iloc[0])} synthetic "
                 f"instances of each instance's mean over {k} timing repeats; error bars are 95 % CIs; "
                 "one machine (adi-laptop-win11).")
    _save(fig, stem)


# ---------------------------------------------------------------- F5
F5_METHODS = ["greedy_1opt", "sa"]


def f5_data() -> pd.DataFrame:
    """Optimality gap vs n: box statistics over instances x seeds, plus mean/CI over instances.

    The box is drawn over every run in the cell (never a single run); the summary columns
    describe the per-instance median-over-seeds sample, which is the replication unit of
    05 §4.2 and the one the lint test reads.
    """
    df = scaling_summary.load()
    df = df.merge(scaling_summary.reference(df), on="instance_id", how="left",
                  validate="many_to_one")
    df = df[df["method"].isin(F5_METHODS) & df["ref_proven"]]
    df = df.assign(gap_pct=100.0 * (df["total_usd"] - df["ref_total"]) / df["ref_total"])
    rows = []
    for L in ("core", "ext"):
        for m in F5_METHODS:
            for n in sorted(df["n"].unique()):
                g = df[(df["location_set"] == L) & (df["method"] == m) & (df["n"] == n)]
                if g.empty:
                    continue
                per_instance = g.groupby("instance_id")["gap_pct"].median()
                q1, med, q3 = (float(v) for v in np.percentile(g["gap_pct"], [25, 50, 75]))
                rows.append(_stats_row(per_instance, location_set=L, method=m, n_components=int(n),
                                       n_instances=len(per_instance), n_runs=len(g))
                            | {"run_min_pct": round(float(g["gap_pct"].min()), 8),
                               "run_q1_pct": round(q1, 8), "run_median_pct": round(med, 8),
                               "run_q3_pct": round(q3, 8),
                               "run_max_pct": round(float(g["gap_pct"].max()), 8)})
    return pd.DataFrame(rows)


def f5_plot(df: pd.DataFrame, stem: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.6), constrained_layout=True, sharey=True)
    for i, L in enumerate(["core", "ext"]):
        for j, m in enumerate(F5_METHODS):
            ax = axes[i, j]
            g = df[(df["location_set"] == L) & (df["method"] == m)].sort_values("n_components")
            stats = [{"med": r["run_median_pct"], "q1": r["run_q1_pct"], "q3": r["run_q3_pct"],
                      "whislo": r["run_min_pct"], "whishi": r["run_max_pct"], "fliers": [],
                      "mean": r["mean"], "label": str(int(r["n_components"]))}
                     for _, r in g.iterrows()]
            ax.bxp(stats, widths=0.55, patch_artist=True, showmeans=True,
                   boxprops={"facecolor": METHOD_COLOR[m], "alpha": 0.6, "edgecolor": INK2},
                   medianprops={"color": INK, "linewidth": 1.5},
                   meanprops={"marker": "d", "markerfacecolor": SURFACE, "markeredgecolor": INK},
                   whiskerprops={"color": INK2}, capprops={"color": INK2})
            for xi, (_, r) in enumerate(g.iterrows(), 1):
                ax.text(xi, ax.get_ylim()[1], f"n={int(r['n_runs'])}", ha="center", va="top",
                        fontsize=6, color=INK2)
            ax.axhline(5.0, color=INK2, linestyle="--", linewidth=1)
            ax.text(0.99, 5.0, "H2 gap limit 5%", transform=ax.get_yaxis_transform(), ha="right",
                    va="bottom", fontsize=7, color=INK2)
            ax.set_title(f"{METHOD_LABEL[m]}, {L} set", fontsize=10, color=INK)
            ax.set_xlabel("components n", color=INK2)
            _style(ax)
        axes[i, 0].set_ylabel("gap vs proven optimum, %", color=INK2)
    _suptitle(fig, "F5  Optimality gap of the heuristics vs n. Box = quartiles over all runs in the cell "
                 "(5 instances x seeds, n annotated), whiskers = min/max, diamond = mean over the "
                 "per-instance medians.")
    _save(fig, stem)


# ---------------------------------------------------------------- F6
# Short axis labels for the three §S12 steps; the full "buys" sentence is in the CSV.
F6_STEP_LABEL = {1: "storage", 2: "internet", 3: "egress coupling"}


def f6_data() -> pd.DataFrame:
    """The M17 gain decomposition: per (topology, scale, step) mean gain with its CI."""
    d = pd.read_csv(RES / "ablation" / "decomposition.csv")
    rows = []
    for _, r in d.iterrows():
        rows.append({"topology_id": r["topology_id"], "traffic_scale": r["traffic_scale"],
                     "step": int(r["step"]), "from_method": r["from_method"],
                     "to_method": r["to_method"], "buys": r["buys"], "n": int(r["n"]),
                     "mean": r["gain_usd_mean"], "sd": "", "sem": "", "median": "",
                     "ci_lo": r["gain_usd_ci_lo"], "ci_hi": r["gain_usd_ci_hi"],
                     "ci_method": "bootstrap", "total_gain_usd_mean": r["total_gain_usd_mean"],
                     "share_of_gain_pct_mean": r["share_of_gain_pct_mean"]})
    return pd.DataFrame(rows)


def f6_plot(df: pd.DataFrame, stem: Path) -> None:
    scales = sorted(df["traffic_scale"].unique())
    fig, axes = plt.subplots(len(scales), 3, figsize=(12.5, 3.4 * len(scales)),
                             constrained_layout=True, squeeze=False)
    for i, s in enumerate(scales):
        for j, t in enumerate(TOPOLOGIES):
            ax = axes[i][j]
            g = df[(df["topology_id"] == t) & (df["traffic_scale"] == s)].sort_values("step")
            total = float(g["total_gain_usd_mean"].iloc[0])
            level, x, labels = 0.0, [], []
            for k, (_, r) in enumerate(g.iterrows()):
                gain = float(r["mean"])
                ax.bar(k, gain, bottom=level, width=0.6,
                       color=SLOT[2] if gain >= 0 else SLOT[1], edgecolor=SURFACE)
                ax.errorbar(k, level + gain, yerr=[[gain - float(r["ci_lo"])],
                                                   [float(r["ci_hi"]) - gain]], fmt="none",
                            ecolor=INK, elinewidth=1.2, capsize=3)
                level += gain
                x.append(k)
                labels.append(f"{int(r['step'])} {F6_STEP_LABEL[int(r['step'])]}")
            ax.bar(len(g), total, width=0.6, color=SLOT[0], edgecolor=SURFACE)
            ax.annotate(f"G = {total:,.3g}", (len(g), total), xytext=(0, 4),
                        textcoords="offset points", ha="center",
                        va="bottom" if total >= 0 else "top", fontsize=7, color=INK)
            ax.axhline(0, color=INK2, linewidth=1)
            ax.set_xticks(x + [len(g)], labels + ["G total"], rotation=20, ha="right", fontsize=7)
            ax.set_title(f"{TOPO_LABEL[t]}, s = {s:g}", fontsize=10, color=INK)
            _style(ax)
        axes[i][0].set_ylabel("gain USD / month", color=INK2)
    n = int(df["n"].iloc[0])
    _suptitle(fig, "F6  Where the gain G = C(B1) - C(ILP) comes from: steps b1 -> b1_storage -> "
                 "ilp_no_edge_egress -> ilp_full.  " + CAPTION.format(n=n))
    _save(fig, stem)


# ---------------------------------------------------------------- F7
def f7_data() -> pd.DataFrame:
    """The ILP's saving vs B1 under the two M17 price-world sweeps, per draw (D-073).

    Saving = (C(B1) - C(ILP)) / C(B1) on the same draw, summarised over draws. The egress
    panel is read at k = 4 locations per provider (exactly the core set) and the locations
    panel at multiplier 1 (the real snapshot).
    """
    rows_in = ablation_summary.read_runs(ablation_summary.SENSITIVITY)
    draws = ablation_summary.per_draw(rows_in, ablation_summary.SENSITIVITY_KEYS)
    by_cfg: dict[tuple, dict[str, dict[str, float]]] = {}
    for (t, loc, mult, k, m, d), vals in draws.items():
        by_cfg.setdefault((t, float(mult), int(k)), {}).setdefault(d, {})[m] = vals["total_usd"]
    rows = []
    for (t, mult, k), per_d in sorted(by_cfg.items()):
        ds = sorted((d for d, c in per_d.items() if {"b1", "ilp_full"} <= set(c)), key=int)
        if not ds:
            continue
        saving = [100.0 * (per_d[d]["b1"] - per_d[d]["ilp_full"]) / per_d[d]["b1"] for d in ds]
        rows.append(_stats_row(saving, topology_id=t, egress_mult=mult, locs_per_provider=k,
                               metric="ilp_saving_vs_b1_pct"))
    return pd.DataFrame(rows).sort_values(["topology_id", "egress_mult", "locs_per_provider"]
                                          ).reset_index(drop=True)


F7_BASE_K, F7_BASE_MULT = 4, 1.0


def f7_plot(df: pd.DataFrame, stem: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True, sharey=True)
    a = df[df["locs_per_provider"] == F7_BASE_K]
    for t in TOPOLOGIES:
        h = a[a["topology_id"] == t].sort_values("egress_mult")
        _errorbars(axes[0], h["egress_mult"], h, SLOT[TOPOLOGIES.index(t)], R.TOPO_LABEL[t])
    axes[0].set_xlabel(f"cross-provider egress price multiplier (at k = {F7_BASE_K} locations/provider)",
                       color=INK2)
    b = df[abs(df["egress_mult"] - F7_BASE_MULT) < 1e-12]
    for t in TOPOLOGIES:
        h = b[b["topology_id"] == t].sort_values("locs_per_provider")
        _errorbars(axes[1], h["locs_per_provider"], h, SLOT[TOPOLOGIES.index(t)], R.TOPO_LABEL[t])
    axes[1].set_xlabel("locations per provider (at the real egress prices)", color=INK2)
    axes[1].set_xticks(sorted(b["locs_per_provider"].unique()))
    for ax in axes:
        ax.axhline(20.0, color=INK2, linestyle="--", linewidth=1)
        ax.text(0.99, 20.0, "H1 threshold 20%", transform=ax.get_yaxis_transform(), ha="right",
                va="bottom", fontsize=7, color=INK2)
        _style(ax)
    axes[0].set_ylabel("ILP saving vs B1, %", color=INK2)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    n = int(df["n"].iloc[0])
    _suptitle(fig, f"F7  Sensitivity of the ILP's saving over B1 to the price world. Mean over {n} draws; "
                   f"error bands are 95 % bootstrap CIs. Locations are prefixes of the extended set, so "
                   f"k = {F7_BASE_K} is exactly the core set and multiplier 1 the real snapshot.")
    _save(fig, stem)


FIGURES = {
    "R2-1_cost_vs_scale": (r21_data, r21_plot),
    "F0_sa_convergence": (f0_data, f0_plot),
    "F1_cost_breakdown": (f1_data, f1_plot),
    "F2_egress_penalty": (f2_data, f2_plot),
    "F3_providers_used": (f3_data, f3_plot),
    "F4_runtime_vs_n": (f4_data, f4_plot),
    "F5_gap_boxplots": (f5_data, f5_plot),
    "F6_gain_decomposition": (f6_data, f6_plot),
    "F7_sensitivity": (f7_data, f7_plot),
}
MIN_N = 3  # 04 §5: no configuration used in a figure may rest on fewer than 3 replicates


def render_csvs() -> dict[str, str]:
    return {name: to_csv(data()) for name, (data, _) in FIGURES.items()}


def lint(frames: dict[str, pd.DataFrame] | None = None) -> list[str]:
    """04 §5.2: every figure CSV carries `mean`, a spread column and n >= MIN_N.

    Returns one line per problem; an empty list means the figure set is publishable.
    """
    frames = frames or {name: data() for name, (data, _) in FIGURES.items()}
    bad = []
    for name, df in sorted(frames.items()):
        if "mean" not in df.columns:
            bad.append(f"{name}: no `mean` column")
        if "n" not in df.columns:
            bad.append(f"{name}: no `n` column")
            continue
        if not ({"sd", "ci_lo", "ci_hi"} & set(df.columns)):
            bad.append(f"{name}: no spread column (sd or ci_lo/ci_hi)")
        ns = pd.to_numeric(df["n"], errors="coerce")
        if ns.isna().any():
            bad.append(f"{name}: {int(ns.isna().sum())} row(s) with a non-numeric n")
        if (ns < MIN_N).any():
            worst = int(ns.min())
            bad.append(f"{name}: {int((ns < MIN_N).sum())} row(s) with n < {MIN_N} (min {worst})")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a committed CSV differs")
    ap.add_argument("--lint", action="store_true", help="04 §5.2 checks on the figure data, then exit")
    args = ap.parse_args(argv)
    if args.lint:
        bad = lint()
        for line in bad:
            print(f"LINT  {line}")
        print(f"figures --lint: {len(bad)} problem(s) over {len(FIGURES)} figures")
        return 1 if bad else 0
    if args.check:
        bad = [n for n, text in render_csvs().items()
               if not (FIG / f"{n}.csv").exists()
               or (FIG / f"{n}.csv").read_text(encoding="utf-8").replace("\r\n", "\n") != text]
        print("figures --check:",
              f"OK ({len(FIGURES)}/{len(FIGURES)} CSVs identical)" if not bad else f"DRIFT in {bad}")
        return 1 if bad else 0
    FIG.mkdir(exist_ok=True)
    for name, (data, plot) in FIGURES.items():
        df = data()
        (FIG / f"{name}.csv").write_text(to_csv(df), encoding="utf-8", newline="\n")
        plot(df, FIG / name)
        print(f"wrote figures/{name}.{{png,pdf,csv}} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
