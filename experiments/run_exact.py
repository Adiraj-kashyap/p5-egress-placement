"""M10 step 4: exact ILP on T1-T3, both formulations, over the `core` location set.

Appends one row per (topology, formulation, repeat) to `results/exact/runs.csv`, keeps every
CBC log under `results/exact/cbc/`, and writes `config.json` and `run.log`. Repeats exist only
to compare runtimes (A4); objectives are deterministic. Every cost is re-scored with
`placement.cost.evaluate` and the run fails if it disagrees with CBC's objective (02 §1 I8).

Run: python -m experiments.run_exact [--repeats 5] [--time-limit 600] [--tee evidence/logs/M10_exact.txt]
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
from datetime import date, datetime, timezone
from pathlib import Path

from experiments.run_baselines import TOPOLOGIES, git_commit, sha256
from placement.baselines import b1_cheapest_per_vcpu, b2_best
from placement.cost import evaluate
from placement.ilp import FORMULATIONS, solve_ilp
from placement.instance import HOURS_PER_MONTH, load_instance
from pricing.common import ROOT

EXP_ID = "exact"
RUNS_FIELDS = ["exp_id", "run_utc", "instance_id", "method", "formulation", "repeat", "seed", "n_components",
               "n_locations", "total_usd", "compute_usd", "storage_usd", "egress_usd", "internet_usd",
               "egress_share", "providers_used", "cbc_objective", "best_bound", "gap", "proven_optimal",
               "status", "cbc_result", "runtime_s", "cbc_wall_s", "build_s", "n_vars", "n_constraints",
               "n_binaries", "n_pairs", "time_limit_s", "threads", "cbc_log", "assignment_json",
               "machine_tag", "git_commit", "snapshot_date"]

log = logging.getLogger("run_exact")


def setup_logging(out_dir: Path, tee: Path | None) -> None:
    """Log to stdout, logs/run_exact_<date>.log, results/exact/run.log and the optional tee file."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    plain = logging.Formatter("%(message)s")
    stamped = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    (ROOT / "logs").mkdir(exist_ok=True)
    targets = [(logging.StreamHandler(sys.stdout), plain),
               (logging.FileHandler(ROOT / "logs" / f"run_exact_{date.today().isoformat()}.log",
                                    encoding="utf-8"), stamped),
               (logging.FileHandler(out_dir / "run.log", mode="w", encoding="utf-8"), stamped)]
    if tee is not None:
        tee.parent.mkdir(parents=True, exist_ok=True)
        targets.append((logging.FileHandler(tee, mode="w", encoding="utf-8"), plain))
    for handler, fmt in targets:
        handler.setFormatter(fmt)
        log.addHandler(handler)
    ilp_log = logging.getLogger("placement.ilp")  # per-solve lines go to the stamped files only
    ilp_log.setLevel(logging.INFO)
    ilp_log.handlers.clear()
    ilp_log.propagate = False
    for handler, _ in targets[1:3]:
        ilp_log.addHandler(handler)


def machine_tag() -> str:
    """`machine_tag` from evidence/logs/machine.txt (02 §1 I9), or 'unknown'."""
    path = ROOT / "evidence" / "logs" / "machine.txt"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("machine_tag"):
                return line.split(":", 1)[1].strip()
    return "unknown"


def main(argv: list[str] | None = None) -> None:
    """Solve T1-T3 x {tight, mccormick} x repeats; append rows to runs.csv; log the summary table."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-date", default=os.environ.get("P5_SNAPSHOT_DATE", "2026-09-21"))
    ap.add_argument("--location-set", default="core", choices=["core", "ext"])
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--time-limit", type=float, default=600)
    ap.add_argument("--out", default=f"results/{EXP_ID}")
    ap.add_argument("--tee", default=None, help="also write the console output to this file (UTF-8)")
    args = ap.parse_args(argv)

    commit = git_commit()  # before any file is written, which would mark the tree dirty
    now = datetime.now(timezone.utc)
    run_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = now.strftime("%Y%m%dT%H%M%S_%f")  # CBC log prefix; microseconds keep back-to-back runs apart
    out_dir = ROOT / args.out
    (out_dir / "cbc").mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir, ROOT / args.tee if args.tee else None)
    tag = machine_tag()
    log.info("M10 exact ILP | snapshot %s | location set %s | repeats %d | time limit %g s | threads 1 | "
             "machine %s | git %s", args.snapshot_date, args.location_set, args.repeats, args.time_limit, tag, commit)

    rows, failures = [], []
    for topo_path in TOPOLOGIES:
        inst = load_instance(topo_path, args.snapshot_date, args.location_set)
        b1 = evaluate(inst, b1_cheapest_per_vcpu(inst)).total
        b2p, _, b2cb = b2_best(inst)
        log.info("")
        log.info("%s  (%d components, %d locations)   B1 %.2f   B2-best %.2f (%s)", inst.instance_id,
                 inst.n_components, inst.n_locations, b1, b2cb.total, b2p)
        log.info("  %-10s %5s %6s %11s %11s %9s %6s %4s %11s  %s", "form", "vars", "cons", "total_usd",
                 "egress", "internet", "proven", "prov", "median_s", "placement")
        for form in FORMULATIONS:
            times, res0 = [], None
            for rep in range(1, args.repeats + 1):
                rel_log = Path(args.out) / "cbc" / f"{stamp}_{inst.topology_id}_{args.location_set}_{form}_r{rep}.log"
                res = solve_ilp(inst, args.time_limit, form, log_path=ROOT / rel_log)
                cb = evaluate(inst, res.assignment) if res.assignment else None
                if cb is None or not math.isclose(res.objective, cb.total, rel_tol=1e-6):
                    failures.append(f"{inst.instance_id} {form} r{rep}: objective {res.objective} vs evaluate "
                                    f"{cb.total if cb else None}")
                times.append(res.runtime_s)
                res0 = res0 or (res, cb)
                rows.append({
                    "exp_id": EXP_ID, "run_utc": run_utc, "instance_id": inst.instance_id,
                    "method": f"ILP-{form}", "formulation": form, "repeat": rep, "seed": "",
                    "n_components": inst.n_components, "n_locations": inst.n_locations,
                    "total_usd": round(cb.total, 6) if cb else "", "compute_usd": round(cb.compute, 6) if cb else "",
                    "storage_usd": round(cb.storage, 6) if cb else "", "egress_usd": round(cb.egress, 6) if cb else "",
                    "internet_usd": round(cb.internet, 6) if cb else "",
                    "egress_share": round(cb.egress_share, 8) if cb else "",
                    "providers_used": cb.providers_used if cb else "",
                    "cbc_objective": res.objective, "best_bound": res.best_bound, "gap": res.gap,
                    "proven_optimal": res.proven_optimal, "status": res.status, "cbc_result": res.cbc_result,
                    "runtime_s": f"{res.runtime_s:.6f}", "cbc_wall_s": res.cbc_wall_s, "build_s": f"{res.build_s:.6f}",
                    "n_vars": res.n_vars, "n_constraints": res.n_constraints, "n_binaries": res.n_binaries,
                    "n_pairs": res.n_pairs, "time_limit_s": args.time_limit, "threads": 1,
                    "cbc_log": rel_log.as_posix(),
                    "assignment_json": json.dumps(res.assignment, separators=(",", ":")) if res.assignment else "",
                    "machine_tag": tag, "git_commit": commit, "snapshot_date": args.snapshot_date,
                })
            res, cb = res0
            placed = ", ".join(f"{c}@{res.assignment[c]}" for c in inst.components) if res.assignment else "-"
            if res.assignment and len(set(res.assignment.values())) == 1:
                placed = f"all @ {next(iter(res.assignment.values()))}"
            log.info("  %-10s %5d %6d %11.2f %11.2f %9.2f %6s %4d %11.4f  %s", form, res.n_vars, res.n_constraints,
                     cb.total, cb.egress, cb.internet, res.proven_optimal, cb.providers_used,
                     statistics.median(times), placed)
        log.info("  ILP vs min(B1, B2-best): %.2f vs %.2f", res.objective, min(b1, b2cb.total))

    runs = out_dir / "runs.csv"
    new = not runs.exists()
    with open(runs, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUNS_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    config = {
        "exp_id": EXP_ID, "module": "M10", "created_utc": run_utc, "git_commit": commit,
        "snapshot_date": args.snapshot_date, "cost_model_dir": f"cost_model/{args.snapshot_date}",
        "location_set": args.location_set, "hours_per_month": HOURS_PER_MONTH,
        "formulations": list(FORMULATIONS), "repeats": args.repeats, "time_limit_s": args.time_limit,
        "solver": "CBC via pulp.PULP_CBC_CMD, threads=1, default gaps", "machine_tag": tag, "seeds": [],
        "topologies": {p: {"sha256": sha256(ROOT / p)} for p in TOPOLOGIES},
        "notes": {
            "runtime_s": "wall time around the CBC call (model build excluded; build_s separate).",
            "proven_optimal": "from the CBC log ('Result - Optimal solution found'), not PuLP's status.",
            "runs.csv": "append-only; one row per (topology, formulation, repeat); run_utc groups a run.",
        },
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log.info("")
    log.info("appended %d rows to %s; CBC logs in %s/cbc/", len(rows), Path(args.out, "runs.csv").as_posix(),
             Path(args.out).as_posix())
    if failures:
        for msg in failures:
            log.error("I8 violation: %s", msg)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
