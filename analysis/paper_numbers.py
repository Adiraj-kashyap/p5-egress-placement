"""Every number the paper quotes (M21 step 3) -> paper/numbers.tex.

The paper never types a number. `paper/main.tex` writes `\\N{h1.t2.red}` and this module
defines that key from the committed results, using the same sources and the same formatting
functions as `analysis/tables.py` and `analysis/results_text.py`, so a number in the PDF is a
number in a generated table or results file. An undefined key stops the LaTeX build.

    python -m analysis.paper_numbers            # write paper/numbers.tex
    python -m analysis.paper_numbers --check    # regenerate in memory, exit 1 on drift
    python -m analysis.paper_numbers --list     # print key = value
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import pandas as pd

from analysis import figures as F
from analysis import hypotheses as HYP
from analysis import replicated as R
from analysis import stats as S
from analysis import tables as T
from analysis import verdicts as V
from analysis.thresholds import H1_MIN_REDUCTION, H2_MAX_GAP, H2_MIN_SPEEDUP, H3_RANGE
from experiments import generate as G
from experiments import uncertainty as U
from placement import annealing as A
from topologies import build as TB

OUT = T.ROOT / "paper" / "numbers.tex"
TID = {"t1_three_tier": "t1", "t2_pipeline": "t2", "t3_microservices": "t3"}


def _count(rel: str) -> int:
    with (T.ROOT / rel).open(encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


def _int(x: float) -> str:
    return f"{int(round(x)):,}"


def numbers() -> dict[str, str]:
    n: dict[str, str] = {}
    vs = {v.hid: v for v in V.all_verdicts()}

    # snapshot and cost model
    n["snapshot"] = T.SNAPSHOT
    for name in ("compute", "egress", "internet", "storage"):
        n[f"rows.{name}"] = _int(_count(f"cost_model/{T.SNAPSHOT}/{name}.csv"))
    comp = pd.read_csv(T.COST_MODEL / "compute.csv")
    comp["loc"] = comp["provider"] + ":" + comp["region"]
    per_vcpu = (comp["usd_per_hour"] / comp["vcpu"]).groupby(comp["loc"])
    n["vcpu.aws"] = f"{per_vcpu.min()['aws:us-east-1']:.4f}"
    n["vcpu.azure"] = f"{per_vcpu.min()['azure:eastus']:.4f}"
    n["hours"] = _int(round(comp["usd_per_month"].iloc[0] / comp["usd_per_hour"].iloc[0]))
    fr = pd.read_csv(T.RES / "scaling" / "frontier.csv").set_index("location_set")
    n["L.core"] = _int(fr.loc["core", "n_locations"])
    n["L.ext"] = _int(fr.loc["ext", "n_locations"])

    # topologies and the testbed
    for t in T.TOPOLOGIES:
        d = json.loads((T.ROOT / "topologies" / f"{t}.json").read_text(encoding="utf-8"))
        k = TID[t]
        n[f"{k}.n"] = _int(len(d["components"]))
        n[f"{k}.edges"] = _int(len(d["edges"]))
        n[f"{k}.edgegb"] = T.usd(sum(e["gb_per_month"] for e in d["edges"]))
        n[f"{k}.netgb"] = T.usd(sum(e["gb_per_month"] for e in d["internet_egress"]))
    meas = pd.read_csv(T.ROOT / "testbed" / "measurements" / "summary.csv")
    n["tb.runs"] = _int(meas["runs"].iloc[0])
    n["tb.edges"] = _int(len(meas))
    n["tb.maxcv"] = T.pctv(100 * meas["bytes_per_request_cv"].max())
    runs = pd.read_csv(T.ROOT / "testbed" / "measurements" / "runs.csv").drop_duplicates("run_id")
    n["tb.minutes"] = _int(runs["duration_s"].min() // 60)
    n["tb.users"] = _int(runs["users"].iloc[0])
    n["tb.rps"] = _int(TB.T1_RATE)

    # exact model sizes and runtimes (core, s = 1)
    ex = pd.read_csv(T.RES / "exact" / "runs.csv")
    ex = ex[ex["formulation"] == "tight"]
    for t in T.TOPOLOGIES:
        r = ex[ex["instance_id"] == f"{t}@core"]
        n[f"{TID[t]}.vars"] = _int(r["n_vars"].iloc[0])
        n[f"{TID[t]}.cons"] = _int(r["n_constraints"].iloc[0])
        n[f"{TID[t]}.ilpsec"] = T.secs(r["runtime_s"].median())

    # heuristics on T1-T3 (core, s = 1)
    he = pd.read_csv(T.RES / "heuristics" / "runs.csv")
    med = he.groupby(["instance_id", "method"])[["gap_vs_ilp_pct", "runtime_s"]].median()
    for t in T.TOPOLOGIES:
        for m, mk in (("greedy", "greedy"), ("greedy_1opt", "onep"), ("sa", "sa")):
            g = med.loc[(f"{t}@core", m)]
            n[f"{TID[t]}.{mk}.gap"] = T.pctv(g["gap_vs_ilp_pct"])
            n[f"{TID[t]}.{mk}.sec"] = T.secs(g["runtime_s"])

    # H1
    h1 = {r.topology_id: r for r in HYP.h1_rows(H1_MIN_REDUCTION) if r.variant == "b1"}
    alt = {r.topology_id: r for r in HYP.h1_rows(H1_MIN_REDUCTION) if r.variant == "b1_alt"}
    n["R"] = _int(h1[T.TOPOLOGIES[0]].rho.n)
    n["h1.thr"] = f"{100 * H1_MIN_REDUCTION:g}"
    for t, r in h1.items():
        k = TID[t]
        n[f"h1.{k}.red"] = T.pctv(100 * r.rho.mean)
        n[f"h1.{k}.sd"] = T.pctv(100 * r.rho.sd)
        n[f"h1.{k}.lo"] = T.pctv(100 * r.rho.ci_lo)
        n[f"h1.{k}.hi"] = T.pctv(100 * r.rho.ci_hi)
        n[f"h1.{k}.p"] = T.pval(r.wilcoxon_p)
        n[f"h1.{k}.b1"] = T.usd(r.b1_usd.mean)
        n[f"h1.{k}.ilp"] = T.usd(r.ilp_usd.mean)
        n[f"h1.{k}.alt"] = T.pctv(100 * alt[t].rho.mean)
        n[f"h1.{k}.verdict"] = vs["H1"].per_topology[t]
    n["h1.verdict"] = vs["H1"].verdict

    # H2
    gap, per_instance = HYP.h2_gap()
    sp, wide = HYP.h2_speedup()
    n["h2.maxgap"] = f"{100 * H2_MAX_GAP:g}"
    n["h2.minsp"] = f"{H2_MIN_SPEEDUP:g}"
    n["h2.minn"] = _int(HYP.H2_MIN_N)
    n["h2.minl"] = _int(HYP.H2_MIN_L)
    n["h2.gap"] = T.pctv(gap.mean)
    n["h2.gap.lo"] = T.pctv(gap.ci_lo)
    n["h2.gap.hi"] = T.pctv(gap.ci_hi)
    n["h2.gap.n"] = _int(gap.n)
    n["h2.gap.worst"] = T.pctv(per_instance.max())
    n["h2.sp"] = T.ratio(sp.median)
    n["h2.sp.lo"] = T.ratio(sp.ci_lo)
    n["h2.sp.hi"] = T.ratio(sp.ci_hi)
    n["h2.sp.n"] = _int(sp.n)
    n["h2.sp.best"] = T.ratio(wide["speedup"].max())
    n["h2.verdict"] = vs["H2"].verdict

    # H3
    h3 = {r.topology_id: r for r in HYP.h3_rows() if r.variant == "b1"}
    r3 = h3[T.TOPOLOGIES[0]]
    n["h3.points"] = _int(HYP.n_scale_points())
    n["h3.smin"] = T.scale(H3_RANGE[0])
    n["h3.smax"] = T.scale(H3_RANGE[1])
    n["h3.cross"] = _int(r3.crossovers)
    n["h3.draws"] = _int(r3.n_draws)
    n["h3.rate"] = T.pctv(100 * r3.rate)
    n["h3.rate.hi"] = T.pctv(100 * r3.rate_hi)
    n["h3.allzero"] = "yes" if all(r.crossovers == 0 for r in h3.values()) else "no"
    n["h3.verdict"] = vs["H3"].verdict

    # traffic sweep at the top of the range (base sweep, undrawn)
    sw = T.sweep_summary()
    top = sw[T._is(sw["scale"], H3_RANGE[1])].set_index("topology_id")
    for t in T.TOPOLOGIES:
        k = TID[t]
        n[f"sw.{k}.ilp"] = T.usd(top.loc[t, "ilp_total_usd"])
        n[f"sw.{k}.b1"] = T.usd(top.loc[t, "b1_total_usd"])
        n[f"sw.{k}.pen"] = _int(100 * top.loc[t, "b1_penalty"])
        n[f"sw.{k}.prov"] = _int(top.loc[t, "ilp_providers_used"])

    # scaling experiment
    sr = pd.read_csv(T.RES / "scaling" / "runs.csv")
    n["sc.nmin"] = _int(sr["n_components"].min())
    n["sc.nmax"] = _int(sr["n_components"].max())
    per_cell = sr.groupby(["n_components", "n_locations"])["instance_id"].nunique()
    n["sc.percell"] = _int(per_cell.min())
    n["sc.seeds"] = _int(sr[sr["method"] == "sa"].groupby("instance_id")["seed"].nunique().min())
    n["sc.maxsec.core"] = T.secs(fr.loc["core", "ilp_runtime_max_s_overall"])
    n["sc.maxsec.ext"] = T.secs(fr.loc["ext", "ilp_runtime_max_s_overall"])
    n["sc.limit"] = _int(pd.read_csv(T.RES / "exact" / "runs.csv")["time_limit_s"].iloc[0])
    tm = pd.read_csv(T.RES / "timing" / "summary.csv")
    n["tm.repeats"] = _int(tm["n"].max())

    # ablation (s = 1)
    de = pd.read_csv(T.RES / "ablation" / "decomposition.csv")
    for t in T.TOPOLOGIES:
        for i in (1, 2, 3):
            r = de[(de["topology_id"] == t) & (de["step"] == i) & T._is(de["traffic_scale"], 1.0)].iloc[0]
            k = f"ab.{TID[t]}.s{'abc'[i - 1]}"
            n[k] = T.usd(r["gain_usd_mean"])
            n[k + ".lo"] = T.usd(r["gain_usd_ci_lo"])
            n[k + ".hi"] = T.usd(r["gain_usd_ci_hi"])
    n["ab.points"] = _int(len(de.groupby(["topology_id", "traffic_scale"])))

    # price sensitivity (F7)
    sens = F.f7_data()
    for t in T.TOPOLOGIES:
        for mult, mk in ((0.5, "half"), (0.75, "tq"), (1.0, "one"), (1.5, "onehalf")):
            r = sens[(sens["topology_id"] == t) & T._is(sens["egress_mult"], mult)
                     & (sens["locs_per_provider"] == F.F7_BASE_K)].iloc[0]
            n[f"se.{TID[t]}.{mk}"] = T.pctv(r["mean"])

    for mult, mk in ((0.5, "half"), (0.75, "tq"), (1.0, "one"), (1.5, "onehalf")):
        n[f"se.mult.{mk}"] = f"{mult:g}"
    n["se.n"] = _int(sens["n"].min())
    n["se.k"] = _int(F.F7_BASE_K)

    # method constants the text states
    n["s1"] = T.scale(R.S1)
    n["ci"] = f"{100 * S.CI_LEVEL:g}"
    n["boot.b"] = _int(S.BOOTSTRAP_B)
    n["boot.seed"] = str(S.BOOTSTRAP_SEED)
    n["smalln"] = _int(S.SMALL_N)
    sa = json.loads((T.RES / "heuristics" / "config_sa.json").read_text(encoding="utf-8"))
    n["sa.seeds"] = _int(len(sa["seeds"]))
    n["sa.alpha"] = f"{sa['params']['alpha']:g}"
    n["sa.stale"] = _int(sa["params"]["max_stale"])
    n["sa.prelocate"] = _int(100 * sa["params"]["p_relocate"])
    n["sa.probe"] = _int(sa["params"]["probe_moves"])
    n["sa.accept"] = _int(100 * A.TARGET_ACCEPT)
    n["sa.tmin"] = f"$10^{{{round(math.log10(A.T_MIN_RATIO))}}}$"

    n["unc.rate"] = f"{U.RATE_SIGMA:g}"
    n["unc.global"] = f"{U.GLOBAL_SIGMA:g}"
    n["unc.edge"] = f"{U.EDGE_SIGMA:g}"
    n["unc.seed"] = _int(U.DRAW_SEED_BASE)
    n["gen.density"] = f"{G.DEFAULTS['density']:g}"
    n["gen.median"] = _int(G.DEFAULTS["median_gb"])

    # run counts
    for rel, k in (("results/replicates/runs.csv", "rep"), ("results/scaling/runs.csv", "scale"),
                   ("results/ablation/runs.csv", "abl"), ("results/sensitivity/runs.csv", "sens")):
        n[f"runs.{k}"] = _int(_count(rel))
    return n


def render() -> str:
    lines = ["% generated by `python -m analysis.paper_numbers` from the committed results; do not edit",
             r"% \N{key} prints a value; an unknown key is a build error.",
             r"\makeatletter",
             r"\DeclareRobustCommand{\N}[1]{\@ifundefined{pn@#1}{\errmessage{paper number '#1' undefined}}"
             r"{\@nameuse{pn@#1}}}"]
    for k, v in numbers().items():
        lines.append(r"\@namedef{pn@" + k + "}{" + v.replace("%", r"\%").replace("<", r"$<$") + "}")
    lines.append(r"\makeatother")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list:
        for k, v in numbers().items():
            print(f"{k} = {v}")
        return 0
    text = render()
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print(f"numbers.tex: {'OK' if same else 'DRIFT'}")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(T.ROOT).as_posix()} ({len(numbers())} numbers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
