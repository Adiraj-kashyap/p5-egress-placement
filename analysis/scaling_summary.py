"""Scaling and optimality-gap summary (M14, O3/H2).

Reads results/scaling/runs.csv (written by `python -m experiments.runner scaling`)
and writes

    results/scaling/summary.csv   one row per (n, location_set, method)
    results/scaling/frontier.csv  one row per location_set (exact-solve frontier, §S9)

Definitions (D-054):
- reference optimum of an instance = the ilp_tight total, used only when that
  solve is proven optimal (CBC log, not PuLP status) within the time limit;
- gap_pct of a run = 100 * (total - reference) / reference;
- gap statistics pool every run of the method in the cell (5 instances x seeds);
  sa additionally reports the median over instances of the per-instance
  median over seeds (H2 wording: "median over seeds");
- speedup = median over instances of ilp_tight runtime / method runtime, where
  the method runtime of an instance is its median over seeds;
- frontier = largest n at which ilp_tight proves optimality within the time
  limit on >= 4 of the 5 instances of the cell.

    python -m analysis.scaling_summary            # write both files
    python -m analysis.scaling_summary --check    # regenerate in memory, exit 1 on drift
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "scaling" / "runs.csv"
SUMMARY = ROOT / "results" / "scaling" / "summary.csv"
FRONTIER = ROOT / "results" / "scaling" / "frontier.csv"

REF_METHOD = "ilp_tight"
ILP_METHODS = ("ilp_tight", "ilp_mccormick")
METHOD_ORDER = ["ilp_tight", "ilp_mccormick", "greedy_1opt", "sa"]
FRONTIER_MIN_PROVEN = 4
GAP_TOL = 1e-9  # relative; |gap| below this counts as "at optimum"


def _proven(df: pd.DataFrame) -> pd.Series:
    ok = df["proven_optimal"].astype(str).str.lower() == "true"
    within = df["runtime_s"] <= df["time_limit_s"].fillna(float("inf"))
    return ok & within


def load(path: Path = RUNS) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["n"] = df["n_components"].astype(int)
    df["L"] = df["location_set"]
    return df


def reference(df: pd.DataFrame) -> pd.DataFrame:
    ilp = df[df["method"] == REF_METHOD].copy()
    ilp["ref_proven"] = _proven(ilp)
    return ilp[["instance_id", "total_usd", "runtime_s", "ref_proven"]].rename(
        columns={"total_usd": "ref_total", "runtime_s": "ref_runtime_s"})


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(reference(df), on="instance_id", how="left", validate="many_to_one")
    df["gap_pct"] = 100.0 * (df["total_usd"] - df["ref_total"]) / df["ref_total"]
    rows = []
    for (n, L, method), g in df.groupby(["n", "L", "method"], sort=False):
        per_inst = g.groupby("instance_id").agg(
            runtime_s=("runtime_s", "median"), ref_runtime_s=("ref_runtime_s", "first"),
            ref_proven=("ref_proven", "first"), gap_pct=("gap_pct", "median"))
        on_opt = g[g["ref_proven"]]
        gaps = on_opt["gap_pct"]
        row = {
            "n": n, "location_set": L, "n_locations": int(g["n_locations"].iloc[0]), "method": method,
            "instances": g["instance_id"].nunique(), "runs": len(g),
            "proven_optimal": int(_proven(g).sum()) if method in ILP_METHODS else None,
            "proven_optimal_rate": float(_proven(g).mean()) if method in ILP_METHODS else None,
            "ref_proven_instances": int(per_inst["ref_proven"].sum()),
            "runtime_median_s": g["runtime_s"].median(),
            "runtime_q1_s": g["runtime_s"].quantile(0.25),
            "runtime_q3_s": g["runtime_s"].quantile(0.75),
            "runtime_max_s": g["runtime_s"].max(),
            "gap_median_pct": gaps.median() if len(gaps) else None,
            "gap_q1_pct": gaps.quantile(0.25) if len(gaps) else None,
            "gap_q3_pct": gaps.quantile(0.75) if len(gaps) else None,
            "gap_max_pct": gaps.max() if len(gaps) else None,
            "gap_min_pct": gaps.min() if len(gaps) else None,
            "gap_median_of_instance_medians_pct":
                per_inst.loc[per_inst["ref_proven"], "gap_pct"].median() if len(gaps) else None,
            "at_opt_fraction": float((gaps.abs() <= 100 * GAP_TOL).mean()) if len(gaps) else None,
        }
        pi = per_inst[per_inst["ref_proven"]]
        row["speedup_median"] = (pi["ref_runtime_s"] / pi["runtime_s"]).median() if len(pi) else None
        row["speedup_min"] = (pi["ref_runtime_s"] / pi["runtime_s"]).min() if len(pi) else None
        rows.append(row)
    out = pd.DataFrame(rows)
    out["_m"] = out["method"].map({m: i for i, m in enumerate(METHOD_ORDER)})
    out = out.sort_values(["location_set", "n", "_m"]).drop(columns="_m").reset_index(drop=True)
    return out


def frontier(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ilp = summary[summary["method"] == REF_METHOD]
    for L, g in ilp.groupby("location_set"):
        g = g.sort_values("n")
        ok = g[g["proven_optimal"] >= FRONTIER_MIN_PROVEN]
        failing = g[g["proven_optimal"] < FRONTIER_MIN_PROVEN]
        n_max = int(g["n"].max())
        f = int(ok["n"].max()) if len(ok) else None
        reached = len(failing) > 0
        rows.append({
            "location_set": L, "n_locations": int(g["n_locations"].iloc[0]),
            "frontier_n": f, "largest_n_tested": n_max,
            "frontier_reached": reached,
            "first_failing_n": int(failing["n"].min()) if reached else None,
            "finding": (f"exact frontier n = {f}" if reached
                        else f"not reached within n <= {n_max} (CBC proves optimality on >= "
                             f"{FRONTIER_MIN_PROVEN}/5 at every n)"),
            "ilp_runtime_median_s_at_largest_n": float(g.loc[g["n"] == n_max, "runtime_median_s"].iloc[0]),
            "ilp_runtime_max_s_overall": float(g["runtime_max_s"].max()),
        })
    return pd.DataFrame(rows)


def render(df: pd.DataFrame) -> tuple[str, str]:
    s, f = summarise(df), frontier(summarise(df))
    return s.to_csv(index=False, float_format="%.6g", lineterminator="\n"), \
        f.to_csv(index=False, float_format="%.6g", lineterminator="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="diff against the committed files")
    args = ap.parse_args(argv)
    s_txt, f_txt = render(load())
    if args.check:
        drift = [p.name for p, t in ((SUMMARY, s_txt), (FRONTIER, f_txt))
                 if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != t]
        print("drift: " + ", ".join(drift) if drift else "OK: summary.csv and frontier.csv reproduce")
        return 1 if drift else 0
    SUMMARY.write_text(s_txt, encoding="utf-8", newline="\n")
    FRONTIER.write_text(f_txt, encoding="utf-8", newline="\n")
    s = pd.read_csv(io.StringIO(s_txt))
    print(f"wrote {SUMMARY.relative_to(ROOT)} ({len(s)} rows) and {FRONTIER.relative_to(ROOT)}")
    print(f_txt, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
