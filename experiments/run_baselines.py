"""M08 step 5: baselines B1 and B2 on T1-T3 over the `core` location set.

Writes `results/baselines/{runs.csv, config.json, run.log}` and prints the baseline table.
Every cost comes from `placement.cost.evaluate` on the committed cost model and topologies.

Run: python -m experiments.run_baselines [--snapshot-date 2026-09-21] [--tee evidence/logs/M08_baselines.txt]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from placement.baselines import PROVIDERS, b1_cheapest_per_vcpu, b1_tied_locations, b2_best, b2_single_provider
from placement.cost import CostBreakdown, evaluate
from placement.instance import HOURS_PER_MONTH, Instance, load_instance
from pricing.common import ROOT

EXP_ID = "baselines"
TOPOLOGIES = ["topologies/t1_three_tier.json", "topologies/t2_pipeline.json",
              "topologies/t3_microservices.json"]
METHODS = ["B1", "B2-aws", "B2-azure", "B2-gcp", "B2-best"]
RUNS_FIELDS = ["exp_id", "instance_id", "method", "seed", "n_components", "n_locations", "total_usd",
               "compute_usd", "storage_usd", "egress_usd", "internet_usd", "egress_share",
               "providers_used", "runtime_s", "status", "assignment_json", "git_commit", "snapshot_date"]

log = logging.getLogger("run_baselines")


def setup_logging(out_dir: Path, tee: Path | None) -> None:
    """Log to stdout, logs/run_baselines_<date>.log, results/<exp>/run.log and the optional tee file."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    plain = logging.Formatter("%(message)s")
    stamped = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
    (ROOT / "logs").mkdir(exist_ok=True)
    targets = [(logging.StreamHandler(sys.stdout), plain),
               (logging.FileHandler(ROOT / "logs" / f"run_baselines_{date.today().isoformat()}.log",
                                    encoding="utf-8"), stamped),
               (logging.FileHandler(out_dir / "run.log", mode="w", encoding="utf-8"), stamped)]
    if tee is not None:
        tee.parent.mkdir(parents=True, exist_ok=True)
        targets.append((logging.FileHandler(tee, mode="w", encoding="utf-8"), plain))
    for handler, fmt in targets:
        handler.setFormatter(fmt)
        log.addHandler(handler)


def git_commit() -> str:
    """Short HEAD hash, suffixed `-dirty` when tracked or untracked files differ; `unknown` without git."""
    exe = shutil.which("git")
    if exe is None:
        return "unknown"
    try:
        head = subprocess.run([exe, "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run([exe, "status", "--porcelain"], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("-dirty" if dirty else "")


def sha256(path: Path) -> str:
    """Hex SHA-256 of a file, recorded in config.json so inputs can be matched later."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_methods(inst: Instance) -> list[tuple[str, dict[str, str], CostBreakdown, float, str]]:
    """Run the five baseline methods on one instance: (method, assignment, cost, runtime_s, note)."""
    out = []
    t0 = time.perf_counter()
    a = b1_cheapest_per_vcpu(inst)
    out.append(("B1", a, evaluate(inst, a), time.perf_counter() - t0, ""))
    for p in PROVIDERS:
        t0 = time.perf_counter()
        a = b2_single_provider(inst, p)
        out.append((f"B2-{p}", a, evaluate(inst, a), time.perf_counter() - t0, next(iter(a.values()))))
    t0 = time.perf_counter()
    p, a, cb = b2_best(inst)
    out.append(("B2-best", a, cb, time.perf_counter() - t0, f"= B2-{p}"))
    return out


def log_b1_ties(inst: Instance, b1_total: float) -> None:
    """Log B1's tie sets and the total under the opposite final tie-break (sensitivity, D-039)."""
    alt = {}
    for c in inst.components:
        tied = b1_tied_locations(inst, c)
        alt[c] = tied[-1]
        if len(tied) > 1:
            log.info("  B1 tie for %-16s %s", c, ", ".join(tied))
    alt_total = evaluate(inst, alt).total
    if alt == b1_cheapest_per_vcpu(inst):
        log.info("  B1 has no remaining ties; assignment is unique")
    else:
        log.info("  B1 sensitivity: last-location-id tie-break gives total %.2f (reported B1 %.2f)",
                 alt_total, b1_total)


def main(argv: list[str] | None = None) -> None:
    """Run all topologies x {B1, B2-aws, B2-azure, B2-gcp, B2-best}; write results and the table."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-date", default=os.environ.get("P5_SNAPSHOT_DATE", "2026-09-21"))
    ap.add_argument("--location-set", default="core", choices=["core", "ext"])
    ap.add_argument("--out", default=f"results/{EXP_ID}")
    ap.add_argument("--tee", default=None, help="also write the console output to this file (UTF-8)")
    args = ap.parse_args(argv)

    commit = git_commit()  # before the log files are truncated, which would mark the tree dirty
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir, ROOT / args.tee if args.tee else None)
    log.info("M08 baselines | snapshot %s | location set %s | git %s", args.snapshot_date,
             args.location_set, commit)

    rows = []
    for topo_path in TOPOLOGIES:
        inst = load_instance(topo_path, args.snapshot_date, args.location_set)
        results = run_methods(inst)
        log.info("")
        log.info("%s  (%d components, %d locations)", inst.instance_id, inst.n_components, inst.n_locations)
        log.info("  %-9s %11s %11s %9s %10s %10s %7s %4s  %s", "method", "total_usd", "compute", "storage",
                 "egress", "internet", "eg_shr", "prov", "placement")
        for method, a, cb, runtime, note in results:
            placed = note if method.startswith("B2") else ", ".join(f"{c}@{a[c]}" for c in inst.components)
            log.info("  %-9s %11.2f %11.2f %9.2f %10.2f %10.2f %6.2f%% %4d  %s", method, cb.total, cb.compute,
                     cb.storage, cb.egress, cb.internet, 100 * cb.egress_share, cb.providers_used, placed)
            rows.append({
                "exp_id": EXP_ID, "instance_id": inst.instance_id, "method": method, "seed": "",
                "n_components": inst.n_components, "n_locations": inst.n_locations,
                "total_usd": round(cb.total, 6), "compute_usd": round(cb.compute, 6),
                "storage_usd": round(cb.storage, 6), "egress_usd": round(cb.egress, 6),
                "internet_usd": round(cb.internet, 6), "egress_share": round(cb.egress_share, 8),
                "providers_used": cb.providers_used, "runtime_s": f"{runtime:.6f}", "status": "ok",
                "assignment_json": json.dumps({c: a[c] for c in inst.components}, separators=(",", ":")),
                "git_commit": commit, "snapshot_date": args.snapshot_date,
            })
        log_b1_ties(inst, results[0][2].total)

    with open(out_dir / "runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUNS_FIELDS)
        w.writeheader()
        w.writerows(rows)
    config = {
        "exp_id": EXP_ID,
        "module": "M08",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": commit,
        "snapshot_date": args.snapshot_date,
        "cost_model_dir": f"cost_model/{args.snapshot_date}",
        "location_set": args.location_set,
        "hours_per_month": HOURS_PER_MONTH,
        "methods": METHODS,
        "topologies": {p: {"sha256": sha256(ROOT / p)} for p in TOPOLOGIES},
        "rules": {
            "B1": "per component, min usd_per_hour/vcpu of its fixed shape; ties -> lower compute+storage "
                  "monthly bill -> smallest location id (D-039). Egress ignored when choosing, charged when scored.",
            "B2": "per provider, the single region minimising total compute+storage; ties -> smallest location id.",
            "B2-best": "B2 provider with the lowest evaluated total; ties -> aws, azure, gcp order.",
            "egress_share": "inter-component egress_usd / total_usd; internet egress reported separately (D-040).",
            "seed": "empty: all M08 methods are deterministic.",
        },
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log.info("")
    log.info("wrote %s (%d rows) and config.json", (out_dir / "runs.csv").relative_to(ROOT).as_posix(), len(rows))


if __name__ == "__main__":
    main()
