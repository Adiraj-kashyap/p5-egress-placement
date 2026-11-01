"""M12 step 4: small SA parameter sanity sweep (alpha) and the stale-rule comparison (D-046).

Instances: T3 (core) and two seeded synthetic 20-component topologies priced on the real cost
model. The synthetic topologies exist only for this sanity sweep (sweep input, not a reported
result); M13 owns the experiment generator. For each alpha in ALPHAS and each seed in SEEDS it
runs `anneal` and logs median / best total, gap to the tight-ILP optimum and runtime. It also
runs both stale rules at the default alpha. Rows go to `results/sa_sweep/runs.csv` (append-only).

Run: python -m experiments.sweep_sa_alpha [--tee evidence/logs/M12_alpha_sweep.txt]
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import random
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from experiments.run_baselines import git_commit
from experiments.run_exact import machine_tag
from placement.annealing import anneal
from placement.cost import evaluate
from placement.greedy import greedy_1opt
from placement.ilp import solve_ilp
from placement.instance import load_instance
from pricing.common import ROOT

ALPHAS = (0.99, 0.995, 0.999)
DEFAULT_ALPHA = 0.995
SEEDS = (0, 1, 2, 3, 4)
SYNTHETIC_SEEDS = (101, 102)
FIELDS = ["exp_id", "run_utc", "instance_id", "alpha", "stale_rule", "seed", "total_usd", "initial_usd",
          "ilp_optimum_usd", "gap_vs_ilp_pct", "t0", "temp_steps", "moves_tried", "stop_reason", "runtime_s",
          "machine_tag", "git_commit", "snapshot_date"]

log = logging.getLogger("sweep_sa_alpha")


def synthetic_topology(seed: int, n: int = 20) -> dict:
    """Seeded random n-component topology (sweep input only, not a reported instance).

    A chain c0 -> c1 -> ... guarantees connectivity; extra forward edges appear with p=0.1.
    Volumes are log-uniform 10-3000 GB/month, a reverse edge (30% of the volume) appears with
    p=0.5, three components send log-uniform 50-5000 GB/month to the internet. Shapes are drawn
    from 2/4/8 vCPU with 4 GB RAM per vCPU; 30% of components hold 20-500 GB of storage.
    """
    rng = random.Random(seed)
    comps = []
    for i in range(n):
        v = rng.choice([2, 4, 8])
        comps.append({"id": f"c{i}", "vcpu": v, "ram_gb": 4 * v,
                      "storage_gb": round(rng.uniform(20, 500), 1) if rng.random() < 0.3 else 0})
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or rng.random() < 0.1:
                gb = round(math.exp(rng.uniform(math.log(10), math.log(3000))), 2)
                edges.append({"src": f"c{i}", "dst": f"c{j}", "gb_per_month": gb})
                if rng.random() < 0.5:
                    edges.append({"src": f"c{j}", "dst": f"c{i}", "gb_per_month": round(0.3 * gb, 2)})
    internet = [{"src": f"c{i}", "gb_per_month": round(math.exp(rng.uniform(math.log(50), math.log(5000))), 2)}
                for i in rng.sample(range(n), 3)]
    return {"id": f"syn{n}_s{seed}", "components": comps, "edges": edges, "internet_egress": internet}


def setup_logging(tee: Path | None) -> None:
    """Log to stdout, logs/sweep_sa_alpha_<date>.log and the optional tee file."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    (ROOT / "logs").mkdir(exist_ok=True)
    targets = [(logging.StreamHandler(sys.stdout), "%(message)s"),
               (logging.FileHandler(ROOT / "logs" / f"sweep_sa_alpha_{date.today().isoformat()}.log",
                                    encoding="utf-8"), "%(asctime)s %(levelname)s %(message)s")]
    if tee is not None:
        tee.parent.mkdir(parents=True, exist_ok=True)
        targets.append((logging.FileHandler(tee, mode="w", encoding="utf-8"), "%(message)s"))
    for handler, fmt in targets:
        handler.setFormatter(logging.Formatter(fmt))
        log.addHandler(handler)


def main(argv: list[str] | None = None) -> None:
    """Run the alpha sweep and the stale-rule comparison; append rows; log one summary line per cell."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-date", default=os.environ.get("P5_SNAPSHOT_DATE", "2026-09-21"))
    ap.add_argument("--out", default="results/sa_sweep")
    ap.add_argument("--tee", default=None)
    args = ap.parse_args(argv)

    commit = git_commit()
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(ROOT / args.tee if args.tee else None)
    tag = machine_tag()
    log.info("M12 SA sanity sweep | alphas %s | seeds %s | snapshot %s | machine %s | git %s",
             ALPHAS, SEEDS, args.snapshot_date, tag, commit)

    instances = [load_instance("topologies/t3_microservices.json", args.snapshot_date, "core")]
    instances += [load_instance(synthetic_topology(s), args.snapshot_date, "core") for s in SYNTHETIC_SEEDS]
    cells = [(a, "descent") for a in ALPHAS] + [(DEFAULT_ALPHA, "best")]
    rows = []
    for inst in instances:
        ilp = solve_ilp(inst, 600, "tight")
        opt = evaluate(inst, ilp.assignment).total
        g1 = evaluate(inst, greedy_1opt(inst)).total
        log.info("")
        log.info("%s (%d components, %d edges)  ILP %.2f (proven %s)  greedy_1opt %.2f (gap %.3f%%)",
                 inst.instance_id, inst.n_components, len(inst.edges), opt, ilp.proven_optimal, g1,
                 100 * (g1 - opt) / opt)
        log.info("  %-6s %-8s %11s %11s %9s %9s %6s %8s %9s  %s", "alpha", "stale", "median_usd", "best_usd",
                 "med_gap%", "best_gap%", "at_opt", "med_step", "median_s", "stop reasons")
        for alpha, rule in cells:
            res = [anneal(inst, seed=s, alpha=alpha, stale_rule=rule) for s in SEEDS]
            for r in res:
                rows.append({"exp_id": "sa_sweep", "run_utc": run_utc, "instance_id": inst.instance_id,
                             "alpha": alpha, "stale_rule": rule, "seed": r.seed, "total_usd": round(r.total, 6),
                             "initial_usd": round(r.initial_total, 6), "ilp_optimum_usd": round(opt, 6),
                             "gap_vs_ilp_pct": round(100 * (r.total - opt) / opt, 6), "t0": round(r.t0, 6),
                             "temp_steps": r.temp_steps, "moves_tried": r.moves_tried,
                             "stop_reason": r.stop_reason, "runtime_s": f"{r.runtime_s:.4f}",
                             "machine_tag": tag, "git_commit": commit, "snapshot_date": args.snapshot_date})
            totals = [r.total for r in res]
            at_opt = sum(math.isclose(t, opt, rel_tol=1e-9) for t in totals)
            stops = {s: sum(r.stop_reason == s for r in res) for s in sorted({r.stop_reason for r in res})}
            log.info("  %-6s %-8s %11.2f %11.2f %9.3f %9.3f %4d/%d %8d %9.2f  %s", alpha, rule,
                     statistics.median(totals), min(totals), 100 * (statistics.median(totals) - opt) / opt,
                     100 * (min(totals) - opt) / opt, at_opt, len(SEEDS),
                     statistics.median(r.temp_steps for r in res), statistics.median(r.runtime_s for r in res),
                     stops)

    path = out_dir / "runs.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    log.info("")
    log.info("appended %d rows to %s", len(rows), Path(args.out, "runs.csv").as_posix())


if __name__ == "__main__":
    main()
