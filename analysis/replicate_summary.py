"""Summaries with uncertainty for the replicated experiments (M16 step 8, 05 §5).

Reads the two replicated results directories and writes one summary row per
(configuration, metric) with n, mean, sd, sem, median and a 95 % CI from `analysis.stats`:

    results/replicates/summary.csv   configuration = (topology, location set, traffic scale,
                                     method); replication unit = traffic draw (R = 30)
    results/timing/summary.csv       configuration = (instance, location set, method, seed);
                                     replication unit = timing repeat (k = 3)

Metrics for the replicates directory:
  total_usd              monthly cost of the method's assignment on that draw
  penalty_vs_ilp_pct     100 * (total - ilp_total) / ilp_total on the **same** draw; this is
                         the paired comparison of 05 §2, so its CI is the one M18 reports
  egress_share           inter-component egress / total
  providers_used         number of distinct providers in the assignment
  runtime_s              method wall time (for the replicates dir this is incidental; the
                         runtime error bars come from the timing directory)

SA is randomised, so its value on a draw is the **median over its seeds** first; the draws
are then the replication unit (D-068). This keeps n equal to the number of draws for every
method and keeps the comparison paired.

    python -m analysis.replicate_summary            # write both summaries
    python -m analysis.replicate_summary --check    # regenerate in memory, exit 1 on drift
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from analysis.stats import summarise
from pricing.common import ROOT

REPLICATES = ROOT / "results" / "replicates"
TIMING = ROOT / "results" / "timing"
REF_METHOD = "ilp_tight"

REPLICATE_KEYS = ["topology_id", "location_set", "traffic_scale", "method"]
TIMING_KEYS = ["instance_id", "location_set", "n_components", "method", "seed"]
STAT_COLS = ["metric", "n", "mean", "sd", "sem", "median", "ci_lo", "ci_hi", "ci_method"]
METRICS = ["total_usd", "penalty_vs_ilp_pct", "egress_share", "providers_used", "runtime_s"]


def read_runs(d: Path) -> list[dict]:
    """Rows of <dir>/runs.csv; raises if the experiment has not been run."""
    runs = d / "runs.csv"
    if not runs.exists():
        raise SystemExit(f"missing {runs.relative_to(ROOT)}: run the experiment first")
    with runs.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def per_draw(rows: list[dict]) -> dict[tuple, dict[str, float]]:
    """(topology, location_set, traffic_scale, method, draw_id) -> metric values.

    Rows of a randomised method are collapsed to the median over its seeds, so every method
    contributes exactly one value per draw.
    """
    bucket: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["topology_id"], r["location_set"], r["traffic_scale"], r["method"], r["draw_id"])
        bucket[key].append(r)
    out: dict[tuple, dict[str, float]] = {}
    for key, rs in bucket.items():
        out[key] = {
            "total_usd": statistics.median(float(r["total_usd"]) for r in rs),
            "egress_share": statistics.median(float(r["egress_share"]) for r in rs),
            "providers_used": statistics.median(float(r["providers_used"]) for r in rs),
            "runtime_s": statistics.median(float(r["runtime_s"]) for r in rs),
            "n_seeds": float(len(rs)),
        }
    return out


def replicate_samples(rows: list[dict]) -> dict[tuple, dict[str, list[float]]]:
    """Configuration -> metric -> one value per draw (draw order fixed by draw id)."""
    draws = per_draw(rows)
    ref = {(t, l, s, d): v["total_usd"] for (t, l, s, m, d), v in draws.items() if m == REF_METHOD}
    samples: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (t, l, s, m, d) in sorted(draws, key=lambda k: (k[0], k[1], float(k[2]), k[3], int(k[4]))):
        vals = draws[(t, l, s, m, d)]
        cfg = (t, l, s, m)
        for metric in ("total_usd", "egress_share", "providers_used", "runtime_s"):
            samples[cfg][metric].append(vals[metric])
        base = ref.get((t, l, s, d))
        if base:
            samples[cfg]["penalty_vs_ilp_pct"].append(100.0 * (vals["total_usd"] - base) / base)
    return samples


def timing_samples(rows: list[dict]) -> dict[tuple, dict[str, list[float]]]:
    """Configuration -> {"runtime_s": one value per timing repeat}."""
    samples: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in sorted(rows, key=lambda r: (r["instance_id"], r["method"], r["repeat_id"])):
        cfg = tuple(r[k] for k in TIMING_KEYS)
        samples[cfg]["runtime_s"].append(float(r["runtime_s"]))
    return samples


def render(samples: dict[tuple, dict[str, list[float]]], keys: list[str],
           metrics: list[str]) -> str:
    """Render summary rows as CSV text (one row per configuration and metric)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys + STAT_COLS, lineterminator="\n")
    w.writeheader()
    for cfg in sorted(samples):
        for metric in metrics:
            values = samples[cfg].get(metric)
            if not values:
                continue
            s = summarise(values)
            row = dict(zip(keys, cfg))
            row.update({"metric": metric, "n": s.n, "mean": round(s.mean, 8),
                        "sd": round(s.sd, 8), "sem": round(s.sem, 8), "median": round(s.median, 8),
                        "ci_lo": round(s.ci_lo, 8), "ci_hi": round(s.ci_hi, 8),
                        "ci_method": s.ci_method})
            w.writerow(row)
    return buf.getvalue()


def build() -> dict[Path, str]:
    """Return {output path: CSV text} for both summaries, without writing anything."""
    return {
        REPLICATES / "summary.csv": render(replicate_samples(read_runs(REPLICATES)),
                                           REPLICATE_KEYS, METRICS),
        TIMING / "summary.csv": render(timing_samples(read_runs(TIMING)),
                                       TIMING_KEYS, ["runtime_s"]),
    }


def ilp_violations(rows: list[dict], rel_tol: float = 1e-9) -> list[str]:
    """Draws where some method beat the exact optimum (M16 A2: that would be a bug).

    The ILP is solved to proven optimality on each draw, so no heuristic or baseline can be
    cheaper on that same draw by more than floating-point noise. Returns one line per
    violation, empty when the invariant holds.
    """
    draws = per_draw(rows)
    ref = {(t, l, s, d): v["total_usd"] for (t, l, s, m, d), v in draws.items() if m == REF_METHOD}
    out = []
    for (t, l, s, m, d), vals in sorted(draws.items()):
        if m == REF_METHOD:
            continue
        base = ref.get((t, l, s, d))
        if base is None:
            out.append(f"{t} {l} s={s} draw={d}: no {REF_METHOD} row to compare against")
        elif vals["total_usd"] < base * (1 - rel_tol):
            out.append(f"{t} {l} s={s} draw={d}: {m} {vals['total_usd']:.6f} < ilp {base:.6f}")
    return out


def main(argv: list[str] | None = None) -> int:
    """Write (or --check) both summary files; return the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a committed summary would change")
    ap.add_argument("--verify", action="store_true",
                    help="A2: check that no method beats the ILP optimum on any draw, then exit")
    args = ap.parse_args(argv)
    if args.verify:
        rows = read_runs(REPLICATES)
        bad = ilp_violations(rows)
        n_draws = len({(r["topology_id"], r["traffic_scale"], r["draw_id"]) for r in rows})
        for line in bad[:10]:
            print(f"VIOLATION  {line}")
        print(f"A2: {len(bad)} violation(s) over {n_draws} (topology, scale, draw) points, {len(rows)} rows")
        return 1 if bad else 0
    built = build()
    drift = []
    for path, text in built.items():
        rel = path.relative_to(ROOT)
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                drift.append(str(rel))
                print(f"DRIFT  {rel}")
            else:
                print(f"OK     {rel}  ({text.count(chr(10)) - 1} rows)")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote  {rel}  ({text.count(chr(10)) - 1} rows)")
    if drift:
        print("FAIL: re-run `python -m analysis.replicate_summary`")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
