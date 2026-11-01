"""M12 steps 5-6: simulated annealing on T1-T3 with the fixed seed list, plus the F0 convergence figure.

Seeds come from `experiments/configs/sa_seeds.json` (03_SKILLS §S9). For each topology this
re-solves the tight ILP as the reference optimum (cross-checked against M10's runs.csv), runs
greedy+1opt as the heuristic reference, then `anneal` once per seed with the default parameters.
Rows are appended to `results/heuristics/runs.csv` with `method=sa` and the M11 columns; there
`passes` = temperature steps, `moves` = accepted moves and `converged` = stopped by T_min or the
stale rule (not by a time limit). SA-only fields go to `results/heuristics/sa_detail.csv`.
Every cost comes from `placement.cost.evaluate`.

Check (M12 A2): per topology, median SA total <= greedy+1opt total; exit 1 otherwise.

Run: python -m experiments.run_annealing [--tee evidence/logs/M12_annealing.txt]
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
from experiments.run_exact import machine_tag
from experiments.run_heuristics import RUNS_FIELDS, m10_optimum
from placement.annealing import P_RELOCATE, PROBE_MOVES, T_MIN_RATIO, TARGET_ACCEPT, anneal
from placement.cost import evaluate
from placement.greedy import TIE_REL_TOL, greedy_1opt
from placement.ilp import solve_ilp
from placement.instance import load_instance
from pricing.common import ROOT

EXP_ID = "heuristics"
SEEDS_FILE = "experiments/configs/sa_seeds.json"
TRACE_TOPOLOGY = "t3_microservices"
DETAIL_FIELDS = ["run_utc", "instance_id", "seed", "init", "initial_usd", "total_usd", "alpha", "t0",
                 "moves_per_temp", "max_stale", "stale_rule", "temp_steps", "moves_tried", "moves_accepted",
                 "uphill_accepted", "stop_reason", "runtime_s"]

log = logging.getLogger("run_annealing")


def setup_logging(tee: Path | None) -> None:
    """Log to stdout, logs/run_annealing_<date>.log and the optional tee file."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    (ROOT / "logs").mkdir(exist_ok=True)
    targets = [(logging.StreamHandler(sys.stdout), "%(message)s"),
               (logging.FileHandler(ROOT / "logs" / f"run_annealing_{date.today().isoformat()}.log",
                                    encoding="utf-8"), "%(asctime)s %(levelname)s %(message)s")]
    if tee is not None:
        tee.parent.mkdir(parents=True, exist_ok=True)
        targets.append((logging.FileHandler(tee, mode="w", encoding="utf-8"), "%(message)s"))
    for handler, fmt in targets:
        handler.setFormatter(logging.Formatter(fmt))
        log.addHandler(handler)


def append_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Append rows to a CSV, writing the header only when the file is new."""
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def save_trace(result, optimum: float, instance_id: str, csv_path: Path, png_path: Path) -> None:
    """Write the convergence trace CSV (one row per temperature step), then plot it with `plot_trace`."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instance_id", "seed", "alpha", "temp_step", "moves", "temperature", "current_usd",
                    "best_usd", "ilp_optimum_usd"])
        for p in result.trace:
            w.writerow([instance_id, result.seed, result.alpha, p.temp_step, p.moves, f"{p.temperature:.8g}",
                        f"{p.current:.6f}", f"{p.best:.6f}", f"{optimum:.6f}"])
    plot_trace(csv_path, png_path)


def save_all_traces(snapshot_date: str, location_set: str, out_dir: Path) -> Path:
    """Re-run SA on the trace topology once per seed and record EVERY seed's trace (D-079).

    M12 committed one seed's trace, but M18's F0 plots the mean +/- CI over seeds, so it needs
    all of them. Seeds, alpha and every other parameter are the M12 ones, so the totals this
    reproduces are the committed M12 totals; nothing here changes a recorded result.
    """
    seeds = json.loads((ROOT / SEEDS_FILE).read_text(encoding="utf-8"))["seeds"]
    topo = next(p for p in TOPOLOGIES if Path(p).stem == TRACE_TOPOLOGY)
    inst = load_instance(topo, snapshot_date, location_set)
    optimum = evaluate(inst, solve_ilp(inst, 600, "tight").assignment).total
    path = out_dir / "sa_traces.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["instance_id", "seed", "alpha", "temp_step", "moves", "temperature",
                    "current_usd", "best_usd", "ilp_optimum_usd"])
        for seed in seeds:
            r = anneal(inst, seed=seed)
            for p in r.trace:
                w.writerow([inst.instance_id, r.seed, r.alpha, p.temp_step, p.moves,
                            f"{p.temperature:.8g}", f"{p.current:.6f}", f"{p.best:.6f}",
                            f"{optimum:.6f}"])
            log.info("  seed %d: %d temperature steps, final %.2f (gap %.3f%%)", r.seed,
                     r.temp_steps, r.total, 100 * (r.total - optimum) / optimum)
    return path


def plot_trace(csv_path: Path, png_path: Path) -> None:
    """Draw the two-panel F0 figure (cost, then log temperature) from the trace CSV.

    Two stacked panels share the x axis (moves tried) instead of a dual y axis. Colours: the
    dataviz reference palette's categorical slots 1 (current) and 2 (best); the ILP optimum is
    a dashed neutral reference line.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with open(csv_path, newline="", encoding="utf-8") as f:
        pts = list(csv.DictReader(f))
    instance_id, seed = pts[0]["instance_id"], pts[0]["seed"]
    alpha = pts[0].get("alpha") or json.loads(
        (ROOT / "results" / EXP_ID / "config_sa.json").read_text(encoding="utf-8"))["params"]["alpha"]
    optimum = float(pts[0]["ilp_optimum_usd"])
    ink, muted, surface = "#0b0b0b", "#52514e", "#fcfcfb"
    blue, orange, grid = "#2a78d6", "#eb6834", "#e4e3df"
    x = [int(p["moves"]) / 1000 for p in pts]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.5, 5.2), sharex=True, dpi=200,
                                   gridspec_kw={"height_ratios": [2.2, 1]})
    fig.patch.set_facecolor(surface)
    for ax in (ax1, ax2):
        ax.set_facecolor(surface)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.tick_params(colors=muted, labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(grid)
    ax1.plot(x, [float(p["current_usd"]) for p in pts], color=blue, linewidth=1.2, label="current")
    ax1.plot(x, [float(p["best_usd"]) for p in pts], color=orange, linewidth=2, label="best so far")
    ax1.axhline(optimum, color=muted, linewidth=1, linestyle=(0, (4, 3)), label="ILP optimum")
    ax1.annotate(f"ILP optimum {optimum:,.2f}", (x[-1], optimum), xytext=(0, 5), textcoords="offset points",
                 ha="right", va="bottom", fontsize=8, color=muted)
    ax1.set_ylabel("USD / month", fontsize=9, color=ink)
    ax1.legend(frameon=False, fontsize=8, loc="upper right", labelcolor=ink)
    ax1.set_title(f"SA convergence on {instance_id} (seed {seed}, alpha {alpha})",
                  fontsize=10, color=ink, loc="left")
    ax2.plot(x, [float(p["temperature"]) for p in pts], color=blue, linewidth=1.5)
    ax2.set_yscale("log")
    ax2.set_ylabel("temperature", fontsize=9, color=ink)
    ax2.set_xlabel("moves tried (thousands)", fontsize=9, color=ink)
    fig.tight_layout()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, facecolor=surface)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    """Run SA x seeds on T1-T3; append rows; check A2; write F0 trace CSV and PNG."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-date", default=os.environ.get("P5_SNAPSHOT_DATE", "2026-09-21"))
    ap.add_argument("--location-set", default="core", choices=["core", "ext"])
    ap.add_argument("--out", default=f"results/{EXP_ID}")
    ap.add_argument("--tee", default=None)
    ap.add_argument("--replot", action="store_true",
                    help="superseded by M18: F0 is now the mean +/- CI over all seeds and is drawn by "
                         "`python -m analysis.figures` (D-079). Prints that and exits.")
    ap.add_argument("--traces", action="store_true",
                    help="only re-record every seed's SA trace on T3 -> results/heuristics/sa_traces.csv "
                         "(M18 F0, D-079); appends no run rows")
    args = ap.parse_args(argv)
    if args.replot:
        print("F0 is now built over every seed (D-079): run `python -m experiments.run_annealing "
              "--traces` then `python -m analysis.figures`. The M12 single-seed trace and plot are "
              "in the project archive.")
        return
    if args.traces:
        setup_logging(ROOT / args.tee if args.tee else None)
        logging.getLogger("placement.ilp").setLevel(logging.WARNING)
        log.info("M18 F0: re-recording every SA seed's trace on %s (%s, snapshot %s)",
                 TRACE_TOPOLOGY, args.location_set, args.snapshot_date)
        path = save_all_traces(args.snapshot_date, args.location_set, ROOT / args.out)
        log.info("wrote %s", path.relative_to(ROOT).as_posix())
        return

    commit = git_commit()
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(ROOT / args.tee if args.tee else None)
    logging.getLogger("placement.ilp").setLevel(logging.WARNING)
    seeds = json.loads((ROOT / SEEDS_FILE).read_text(encoding="utf-8"))["seeds"]
    tag = machine_tag()
    log.info("M12 simulated annealing | snapshot %s | location set %s | seeds %s | machine %s | git %s",
             args.snapshot_date, args.location_set, seeds, tag, commit)

    rows, detail, failures, trace_done = [], [], [], False
    for topo_path in TOPOLOGIES:
        inst = load_instance(topo_path, args.snapshot_date, args.location_set)
        ilp = solve_ilp(inst, 600, "tight")
        opt = evaluate(inst, ilp.assignment).total
        prev = m10_optimum(inst.instance_id) if args.location_set == "core" else None
        if prev is not None and not math.isclose(prev, opt, rel_tol=1e-6):
            failures.append(f"{inst.instance_id}: ILP optimum {opt} differs from M10 runs.csv {prev}")
        g1 = evaluate(inst, greedy_1opt(inst)).total
        res = [anneal(inst, seed=s) for s in seeds]
        for r in res:
            cb = evaluate(inst, r.assignment)
            rows.append({
                "exp_id": EXP_ID, "run_utc": run_utc, "instance_id": inst.instance_id, "method": "sa",
                "repeat": 1, "seed": r.seed, "n_components": inst.n_components, "n_locations": inst.n_locations,
                "total_usd": round(cb.total, 6), "compute_usd": round(cb.compute, 6),
                "storage_usd": round(cb.storage, 6), "egress_usd": round(cb.egress, 6),
                "internet_usd": round(cb.internet, 6), "egress_share": round(cb.egress_share, 8),
                "providers_used": cb.providers_used, "runtime_s": f"{r.runtime_s:.6f}", "passes": r.temp_steps,
                "moves": r.moves_accepted, "converged": r.stop_reason in ("t_min", "stale"), "max_passes": "",
                "ilp_optimum_usd": round(opt, 6), "ilp_proven_optimal": ilp.proven_optimal,
                "gap_vs_ilp_pct": round(100.0 * (cb.total - opt) / opt, 6),
                "assignment_json": json.dumps(r.assignment, separators=(",", ":")),
                "machine_tag": tag, "git_commit": commit, "snapshot_date": args.snapshot_date,
            })
            detail.append({"run_utc": run_utc, "instance_id": inst.instance_id, "seed": r.seed, "init": r.init,
                           "initial_usd": round(r.initial_total, 6), "total_usd": round(r.total, 6),
                           "alpha": r.alpha, "t0": round(r.t0, 6), "moves_per_temp": r.moves_per_temp,
                           "max_stale": r.max_stale, "stale_rule": r.stale_rule, "temp_steps": r.temp_steps,
                           "moves_tried": r.moves_tried, "moves_accepted": r.moves_accepted,
                           "uphill_accepted": r.uphill_accepted, "stop_reason": r.stop_reason,
                           "runtime_s": f"{r.runtime_s:.6f}"})
        totals = sorted(r.total for r in res)
        med = statistics.median(totals)
        q = statistics.quantiles(totals, n=4, method="inclusive")
        at_opt = sum(math.isclose(t, opt, rel_tol=1e-9) for t in totals)
        log.info("")
        log.info("%s (%d components, %d locations)  ILP %.2f (proven %s; M10 %s)  greedy_1opt %.2f (gap %.3f%%)",
                 inst.instance_id, inst.n_components, inst.n_locations, opt, ilp.proven_optimal,
                 f"{prev:.2f}" if prev is not None else "n/a", g1, 100 * (g1 - opt) / opt)
        log.info("  SA x%d: best %.2f (gap %.3f%%)  median %.2f (gap %.3f%%)  IQR [%.2f, %.2f]  at optimum %d/%d",
                 len(res), totals[0], 100 * (totals[0] - opt) / opt, med, 100 * (med - opt) / opt, q[0], q[2],
                 at_opt, len(res))
        log.info("  runtime median %.3f s [min %.3f, max %.3f]  temp steps median %d  T0 %.3f  stops %s",
                 statistics.median(r.runtime_s for r in res), min(r.runtime_s for r in res),
                 max(r.runtime_s for r in res), statistics.median(r.temp_steps for r in res), res[0].t0,
                 {s: sum(r.stop_reason == s for r in res) for s in sorted({r.stop_reason for r in res})})
        if med > g1 + TIE_REL_TOL * max(1.0, g1):
            failures.append(f"{inst.instance_id}: SA median {med} > greedy_1opt {g1} (A2)")
        else:
            log.info("  A2 PASS: SA median %.2f <= greedy_1opt %.2f", med, g1)
        if totals[0] < opt - 1e-6 * max(1.0, opt):
            failures.append(f"{inst.instance_id}: SA {totals[0]} below the ILP optimum {opt}")
        if inst.topology_id == TRACE_TOPOLOGY and not trace_done:
            save_trace(res[0], opt, inst.instance_id, ROOT / "figures" / "F0_sa_convergence.csv",
                       ROOT / "figures" / "F0_sa_convergence.png")
            trace_done = True
            log.info("  trace of seed %d -> figures/F0_sa_convergence.{png,csv} (%d points)", res[0].seed,
                     len(res[0].trace))

    append_csv(out_dir / "runs.csv", RUNS_FIELDS, rows)
    append_csv(out_dir / "sa_detail.csv", DETAIL_FIELDS, detail)
    config = {
        "exp_id": EXP_ID, "module": "M12", "method": "sa", "created_utc": run_utc, "git_commit": commit,
        "snapshot_date": args.snapshot_date, "location_set": args.location_set, "seeds_file": SEEDS_FILE,
        "seeds": seeds, "machine_tag": tag,
        "params": {"init": "greedy", "alpha": 0.995, "moves_per_temp": "n_components * n_locations",
                   "max_stale": 20, "stale_rule": "descent (D-046)", "p_relocate": P_RELOCATE,
                   "probe_moves": PROBE_MOVES, "target_accept": TARGET_ACCEPT, "t_min_ratio": T_MIN_RATIO,
                   "time_limit": None},
        "topologies": {p: {"sha256": sha256(ROOT / p)} for p in TOPOLOGIES},
        "notes": {"runs.csv columns for sa": "passes = temperature steps; moves = accepted moves; converged = "
                                             "stopped by t_min or stale rule; repeat = 1 (seeds vary instead)",
                  "sa_detail.csv": "SA-only fields, one row per (topology, seed), append-only"},
    }
    (out_dir / "config_sa.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log.info("")
    log.info("appended %d rows to %s and %s", len(rows), Path(args.out, "runs.csv").as_posix(),
             Path(args.out, "sa_detail.csv").as_posix())
    if failures:
        for msg in failures:
            log.error("check failed: %s", msg)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
