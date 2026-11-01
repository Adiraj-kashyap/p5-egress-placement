"""M11 step 3: greedy and greedy+1opt on T1-T3, with the gap to the exact ILP optimum.

Appends one row per (topology, method, repeat) to `results/heuristics/runs.csv` and writes
`config.json` and `run.log`. The heuristics are deterministic; repeats exist only for timing
(medians are reported, D-043). The reference optimum is re-solved here with the tight ILP
(`placement.ilp.solve_ilp`, M10) and cross-checked against M10's latest rows in
`results/exact/runs.csv`. Every cost comes from `placement.cost.evaluate`.

Run: python -m experiments.run_heuristics [--repeats 5] [--location-set core] [--tee evidence/logs/M11_heuristics.txt]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from experiments.run_baselines import TOPOLOGIES, git_commit, sha256
from experiments.run_exact import machine_tag
from placement.baselines import b1_cheapest_per_vcpu, b2_best
from placement.cost import evaluate
from placement.greedy import TIE_REL_TOL, greedy, one_opt
from placement.ilp import solve_ilp
from placement.instance import HOURS_PER_MONTH, load_instance
from pricing.common import ROOT

EXP_ID = "heuristics"
METHODS = ("greedy", "greedy_1opt")
MAX_PASSES = 50
RUNS_FIELDS = ["exp_id", "run_utc", "instance_id", "method", "repeat", "seed", "n_components", "n_locations",
               "total_usd", "compute_usd", "storage_usd", "egress_usd", "internet_usd", "egress_share",
               "providers_used", "runtime_s", "passes", "moves", "converged", "max_passes", "ilp_optimum_usd",
               "ilp_proven_optimal", "gap_vs_ilp_pct", "assignment_json", "machine_tag", "git_commit",
               "snapshot_date"]

log = logging.getLogger("run_heuristics")


def setup_logging(out_dir: Path, tee: Path | None) -> None:
    """Log to stdout, logs/run_heuristics_<date>.log, <out>/run.log and the optional tee file."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    plain = logging.Formatter("%(message)s")
    stamped = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    (ROOT / "logs").mkdir(exist_ok=True)
    targets = [(logging.StreamHandler(sys.stdout), plain),
               (logging.FileHandler(ROOT / "logs" / f"run_heuristics_{date.today().isoformat()}.log",
                                    encoding="utf-8"), stamped),
               (logging.FileHandler(out_dir / "run.log", mode="w", encoding="utf-8"), stamped)]
    if tee is not None:
        tee.parent.mkdir(parents=True, exist_ok=True)
        targets.append((logging.FileHandler(tee, mode="w", encoding="utf-8"), plain))
    for handler, fmt in targets:
        handler.setFormatter(fmt)
        log.addHandler(handler)
    logging.getLogger("placement.ilp").setLevel(logging.WARNING)


def m10_optimum(instance_id: str) -> float | None:
    """Tight-ILP total of `instance_id` from the latest run in results/exact/runs.csv, or None."""
    path = ROOT / "results" / "exact" / "runs.csv"
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["instance_id"] == instance_id and r["formulation"] == "tight"]
    if not rows:
        return None
    latest = max(r["run_utc"] for r in rows)
    return float(next(r for r in rows if r["run_utc"] == latest)["total_usd"])


def run_method(inst, method: str):
    """Run one heuristic; return (assignment, runtime_s, passes, moves, converged). 1-opt time includes greedy."""
    t0 = time.perf_counter()
    if method == "greedy":
        a = greedy(inst)
        return a, time.perf_counter() - t0, "", "", ""
    res = one_opt(inst, greedy(inst), MAX_PASSES)
    return res.assignment, time.perf_counter() - t0, res.passes, res.moves, res.converged


def main(argv: list[str] | None = None) -> None:
    """Run greedy and greedy+1opt on T1-T3 x repeats; append rows to runs.csv; log the summary table."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-date", default=os.environ.get("P5_SNAPSHOT_DATE", "2026-09-21"))
    ap.add_argument("--location-set", default="core", choices=["core", "ext"])
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--out", default=f"results/{EXP_ID}")
    ap.add_argument("--tee", default=None, help="also write the console output to this file (UTF-8)")
    args = ap.parse_args(argv)

    commit = git_commit()  # before any file is written, which would mark the tree dirty
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir, ROOT / args.tee if args.tee else None)
    tag = machine_tag()
    log.info("M11 heuristics | snapshot %s | location set %s | repeats %d | max_passes %d | machine %s | git %s",
             args.snapshot_date, args.location_set, args.repeats, MAX_PASSES, tag, commit)

    rows, failures = [], []
    for topo_path in TOPOLOGIES:
        inst = load_instance(topo_path, args.snapshot_date, args.location_set)
        b1 = evaluate(inst, b1_cheapest_per_vcpu(inst)).total
        b2p, _, b2cb = b2_best(inst)
        ilp = solve_ilp(inst, 600, "tight")
        opt = evaluate(inst, ilp.assignment).total
        prev = m10_optimum(inst.instance_id) if args.location_set == "core" else None
        if prev is not None and not math.isclose(prev, opt, rel_tol=1e-6):
            failures.append(f"{inst.instance_id}: ILP optimum {opt} differs from M10 runs.csv {prev}")
        log.info("")
        log.info("%s  (%d components, %d locations)   B1 %.2f   B2-best %.2f (%s)   ILP %.2f (proven %s; M10 %s)",
                 inst.instance_id, inst.n_components, inst.n_locations, b1, b2cb.total, b2p, opt,
                 ilp.proven_optimal, f"{prev:.2f}" if prev is not None else "n/a")
        log.info("  %-12s %11s %9s %9s %9s %4s %6s %5s %11s  %s", "method", "total_usd", "gap_%", "egress",
                 "internet", "prov", "passes", "moves", "median_s", "placement")
        totals = {}
        for method in METHODS:
            times, first = [], None
            for rep in range(1, args.repeats + 1):
                a, rt, passes, moves, conv = run_method(inst, method)
                cb = evaluate(inst, a)
                if first is not None and a != first[0]:
                    failures.append(f"{inst.instance_id} {method} r{rep}: assignment differs between repeats")
                first = first or (a, cb, passes, moves)
                times.append(rt)
                gap = 100.0 * (cb.total - opt) / opt
                rows.append({
                    "exp_id": EXP_ID, "run_utc": run_utc, "instance_id": inst.instance_id, "method": method,
                    "repeat": rep, "seed": "", "n_components": inst.n_components, "n_locations": inst.n_locations,
                    "total_usd": round(cb.total, 6), "compute_usd": round(cb.compute, 6),
                    "storage_usd": round(cb.storage, 6), "egress_usd": round(cb.egress, 6),
                    "internet_usd": round(cb.internet, 6), "egress_share": round(cb.egress_share, 8),
                    "providers_used": cb.providers_used, "runtime_s": f"{rt:.6f}", "passes": passes,
                    "moves": moves, "converged": conv, "max_passes": MAX_PASSES if method != "greedy" else "",
                    "ilp_optimum_usd": round(opt, 6), "ilp_proven_optimal": ilp.proven_optimal,
                    "gap_vs_ilp_pct": round(gap, 6),
                    "assignment_json": json.dumps(a, separators=(",", ":")),
                    "machine_tag": tag, "git_commit": commit, "snapshot_date": args.snapshot_date,
                })
            a, cb, passes, moves = first
            totals[method] = cb.total
            placed = ", ".join(f"{c}@{a[c]}" for c in inst.components)
            if len(set(a.values())) == 1:
                placed = f"all @ {next(iter(a.values()))}"
            log.info("  %-12s %11.2f %9.3f %9.2f %9.2f %4d %6s %5s %11.6f  %s", method, cb.total,
                     100.0 * (cb.total - opt) / opt, cb.egress, cb.internet, cb.providers_used, passes, moves,
                     statistics.median(times), placed)
            if cb.total < opt - 1e-6 * max(1.0, opt):
                failures.append(f"{inst.instance_id} {method}: {cb.total} below the ILP optimum {opt}")
        if totals["greedy_1opt"] > totals["greedy"] + TIE_REL_TOL * max(1.0, totals["greedy"]):
            failures.append(f"{inst.instance_id}: greedy_1opt {totals['greedy_1opt']} > greedy {totals['greedy']}")

    runs = out_dir / "runs.csv"
    new = not runs.exists()
    with open(runs, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUNS_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    config = {
        "exp_id": EXP_ID, "module": "M11", "created_utc": run_utc, "git_commit": commit,
        "snapshot_date": args.snapshot_date, "cost_model_dir": f"cost_model/{args.snapshot_date}",
        "location_set": args.location_set, "hours_per_month": HOURS_PER_MONTH, "methods": list(METHODS),
        "repeats": args.repeats, "max_passes": MAX_PASSES, "tie_rel_tol": TIE_REL_TOL, "machine_tag": tag,
        "seeds": [], "reference": "tight ILP (placement.ilp.solve_ilp, CBC threads=1, time limit 600 s)",
        "topologies": {p: {"sha256": sha256(ROOT / p)} for p in TOPOLOGIES},
        "notes": {
            "runtime_s": "wall time of the method; greedy_1opt includes its greedy start.",
            "gap_vs_ilp_pct": "100 * (total - ILP optimum) / ILP optimum, both from evaluate().",
            "runs.csv": "append-only; one row per (topology, method, repeat); run_utc groups a run.",
        },
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log.info("")
    log.info("appended %d rows to %s", len(rows), Path(args.out, "runs.csv").as_posix())
    if failures:
        for msg in failures:
            log.error("check failed: %s", msg)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
