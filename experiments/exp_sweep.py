"""M15: traffic sweep, egress penalty and crossover (O4, H1, H3), plus the inter-region rate sensitivity.

For T1-T3 on the core set, every inter-component edge volume is multiplied by s in logspace(-2, 2, 25)
(internet egress is not scaled, 03 §S9). Each scaled instance is solved by the methods in
`experiments/configs/sweep.json`, using the runner's method registry and row format (M13, D-051),
plus `b1_alt` = B1 under the opposite final tie-break (D-039). Rows go to `results/sweep/runs.csv`
with extra columns scale, rate_factor, base_edge_gb, edge_gb. The sensitivity part repeats the grid
with every inter-region egress rate multiplied by 0.75 and 1.25 -> `results/sweep_sensitivity/`.
`--summarize` derives summary.csv (penalties, providers used, egress share per point) and
crossover.csv (rules frozen in D-056 before any result existed), and checks A1/A2.

Run:  python -m experiments.exp_sweep --part main --tee evidence/logs/M15_sweep.txt
      python -m experiments.exp_sweep --part sensitivity --tee evidence/logs/M15_sensitivity.txt
      python -m experiments.exp_sweep --summarize --tee evidence/logs/M15_summary.txt
Resumable: finished (instance, method, seed) rows are skipped on a rerun.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import statistics
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from experiments.generate import canonical_sha256
from experiments.run_exact import machine_tag
from experiments.runner import FIELDS, METHODS, Method, _timed, git_state, job_key, read_done, rel, setup_logging
from placement.baselines import b1_tied_locations
from placement.cost import evaluate
from placement.instance import HOURS_PER_MONTH, Instance, load_instance, load_topology
from pricing.common import ROOT

SWEEP_FIELDS = FIELDS + ["scale", "rate_factor", "base_edge_gb", "edge_gb"]
# Inputs whose change would change a result. Other dirty paths (e.g. a parallel tab's state/ or results/)
# are tolerated and listed in config.json (D-056).
GUARDED = ("placement/", "pricing/", "cost_model/", "topologies/", "experiments/")
REL_TOL = 1e-9  # ties and the A2 comparison: relative tolerance on USD totals

log = logging.getLogger("runner")


def b1_alt(inst: Instance) -> dict[str, str]:
    """B1 with the opposite final tie-break: the last location id of each component's tie set (D-039)."""
    return {c: b1_tied_locations(inst, c)[-1] for c in inst.components}


SWEEP_METHODS: dict[str, Method] = {**METHODS, "b1_alt": Method(lambda inst, s, tl, p, lg: _timed(lambda: b1_alt(inst)))}


def scales(cfg: dict) -> list[float]:
    """The scale grid: 10 ** (a + i (b - a) / (n - 1)), i = 0..n-1 (s = 1 is exact at the middle point)."""
    a, b, n = cfg["scales"]["logspace"]
    return [10 ** (a + i * (b - a) / (n - 1)) for i in range(n)]


def scaled_instance(base: Instance, scale: float, rate_factor: float) -> Instance:
    """`base` with every edge volume x scale and every inter-region egress rate x rate_factor."""
    sid = f"{base.instance_id}@s={scale:.6g}" + ("" if rate_factor == 1.0 else f"@r={rate_factor:g}")
    return replace(base, instance_id=sid,
                   edges=tuple((u, v, gb * scale) for u, v, gb in base.edges),
                   egress={k: v * rate_factor for k, v in base.egress.items()})


def guarded_dirty(out_dir: Path) -> tuple[str, list[str], list[str]]:
    """(commit, dirty guarded paths, other dirty paths), ignoring `out_dir`."""
    commit, dirty = git_state(out_dir)
    guarded = [p for p in dirty if p.startswith(GUARDED)]
    return commit, guarded, [p for p in dirty if p not in guarded]


def run_part(cfg: dict, cfg_path: Path, part: str, allow_dirty: bool) -> None:
    """Run the main grid (rate factor 1) or the sensitivity grid; append rows; resume-safe."""
    sens = cfg["sensitivity"]
    exp_id = cfg["exp_id"] if part == "main" else sens["exp_id"]
    factors = [1.0] if part == "main" else [float(f) for f in sens["rate_factors"]]
    methods = cfg["methods"] if part == "main" else sens["methods"]
    out_dir = ROOT / "results" / exp_id
    commit, guarded, other = guarded_dirty(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if (commit == "unknown" or guarded) and not allow_dirty:
        log.error("refusing to run: git %s, %d changed input path(s) (e.g. %s). Commit first, put git on PATH, "
                  "or pass --allow-dirty.", commit, len(guarded), guarded[:3])
        raise SystemExit(2)
    if guarded:
        commit += "-dirty"
    tag = machine_tag()
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg_sha = canonical_sha256(cfg)
    snapshot, ls = cfg["snapshot_date"], cfg.get("location_set", "core")
    seeds, time_limits, params = cfg.get("method_seeds", []), cfg.get("time_limits", {}), cfg.get("method_params", {})

    config_path = out_dir / "config.json"
    record = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else None
    if record is not None and record.get("config_sha256") != cfg_sha:
        log.error("refusing to mix results: %s was produced by a different config (sha256 %s, now %s)",
                  rel(config_path), record.get("config_sha256"), cfg_sha)
        raise SystemExit(2)
    if record is None:
        record = {"exp_id": exp_id, "part": part, "created_utc": run_utc, "config_path": rel(cfg_path),
                  "config_sha256": cfg_sha, "config": cfg, "snapshot_date": snapshot,
                  "cost_model_dir": f"cost_model/{snapshot}", "location_set": ls, "hours_per_month": HOURS_PER_MONTH,
                  "scales": scales(cfg), "rate_factors": factors, "methods": methods, "method_seeds": seeds,
                  "threads": 1, "machine_tag": tag, "git_commit": commit, "instances": {}, "sessions": [],
                  "notes": {"scale": "multiplies every inter-component edge volume; internet egress unchanged",
                            "rate_factor": "multiplies every inter-region egress USD/GB (intra- and cross-provider)",
                            "b1_alt": "B1 with the opposite final tie-break (last location id), D-039",
                            "runtime_s": "not a reported metric in M15; M14 may run in parallel on the same machine"}}
    session = {"run_utc": run_utc, "git_commit": commit, "machine_tag": tag, "other_dirty_paths": len(other),
               "jobs_run": 0, "jobs_skipped": 0, "jobs_failed": 0, "wall_s": None, "finished": False}
    record["sessions"].append(session)
    config_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    runs = out_dir / "runs.csv"
    done = read_done(runs)
    grid = scales(cfg)
    jobs = [(t, f, s, m, sd) for t in cfg["topologies"] for f in factors for s in grid for m in methods
            for sd in (seeds if SWEEP_METHODS[m].randomised else [None])]
    log.info("M15 sweep | part %s | exp %s | config %s (sha256 %s) | snapshot %s | machine %s | git %s | run %s | "
             "%d jobs", part, exp_id, rel(cfg_path), cfg_sha[:12], snapshot, tag, commit, run_utc, len(jobs))
    t_start = time.perf_counter()
    bases: dict[str, tuple[Instance, str, float]] = {}
    failures = []
    current: tuple | None = None
    inst: Instance | None = None
    for i, (t, f, s, m, sd) in enumerate(jobs, 1):
        if t not in bases:
            topo = load_topology(t)
            b = load_instance(topo, snapshot, ls)
            bases[t] = (b, canonical_sha256(topo), sum(gb for _, _, gb in b.edges))
        base, topo_sha, base_gb = bases[t]
        if current != (t, f, s):
            inst = scaled_instance(base, s, f)
            h = canonical_sha256({"topology_sha256": topo_sha, "scale": s, "rate_factor": f})
            prev = record["instances"].get(inst.instance_id)
            if prev is not None and prev["sha256"] != h:
                log.error("instance %s changed since the first run; refusing to mix", inst.instance_id)
                raise SystemExit(2)
            record["instances"][inst.instance_id] = {"source": t, "topology_sha256": topo_sha, "scale": s,
                                                     "rate_factor": f, "sha256": h, "edge_gb": base_gb * s}
            current = (t, f, s)
        key = job_key(inst.instance_id, m, sd)
        if key in done:
            session["jobs_skipped"] += 1
            continue
        method = SWEEP_METHODS[m]
        cbc_log = None
        if method.uses_cbc:
            (out_dir / "cbc").mkdir(exist_ok=True)
            cbc_log = out_dir / "cbc" / f"{inst.instance_id.replace('@', '_').replace('=', '')}__{m}.log"
        tl = time_limits.get(m)
        try:
            res = method.run(inst, sd, tl, dict(params.get(m, {})), cbc_log)
            if res.assignment is None:
                raise RuntimeError(f"no assignment (status {res.status})")
            bad = [c for c in inst.components if res.assignment.get(c) not in inst.allowed[c]]
            if bad:
                raise RuntimeError(f"assignment violates allowed locations for {bad[:3]}")
        except Exception as exc:  # no row, so a rerun retries it
            failures.append(f"{inst.instance_id} {m} seed={sd}: {type(exc).__name__}: {exc}")
            session["jobs_failed"] += 1
            log.error("job %d/%d FAILED %s %s seed=%s: %s", i, len(jobs), inst.instance_id, m, sd, exc)
            continue
        cb = evaluate(inst, res.assignment)
        row = {k: "" for k in SWEEP_FIELDS}
        row.update({"exp_id": exp_id, "instance_id": inst.instance_id, "method": m, "seed": "" if sd is None else sd,
                    "n_components": inst.n_components, "n_locations": inst.n_locations,
                    "total_usd": round(cb.total, 6), "compute_usd": round(cb.compute, 6),
                    "storage_usd": round(cb.storage, 6), "egress_usd": round(cb.egress, 6),
                    "internet_usd": round(cb.internet, 6), "egress_share": round(cb.egress_share, 8),
                    "providers_used": cb.providers_used, "runtime_s": f"{res.runtime_s:.6f}", "status": res.status,
                    "assignment_json": json.dumps(res.assignment, separators=(",", ":")), "git_commit": commit,
                    "snapshot_date": snapshot, "run_utc": run_utc, "topology_id": inst.topology_id,
                    "location_set": ls, "time_limit_s": "" if tl is None else tl, "machine_tag": tag,
                    "detail_json": json.dumps(res.extra.get("detail", {}), separators=(",", ":")),
                    "scale": repr(s), "rate_factor": f, "base_edge_gb": round(base_gb, 6),
                    "edge_gb": round(base_gb * s, 6)})
        for k in ("proven_optimal", "best_bound", "mip_gap", "n_vars", "n_constraints"):
            if res.extra.get(k) is not None:
                row[k] = res.extra[k]
        with_header = not runs.exists() or runs.stat().st_size == 0
        _append(runs, row, with_header)
        done.add(key)
        session["jobs_run"] += 1
        if m == "ilp_tight" or i % 50 == 0:
            log.info("job %d/%d %-34s %-11s seed=%-2s %-8s total=%12.2f prov=%d", i, len(jobs), inst.instance_id,
                     m, "" if sd is None else sd, res.status, cb.total, cb.providers_used)
    session.update({"wall_s": round(time.perf_counter() - t_start, 3), "finished": True})
    config_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    log.info("jobs %d | skipped %d | run %d | failed %d | wall %.1f s", len(jobs), session["jobs_skipped"],
             session["jobs_run"], session["jobs_failed"], session["wall_s"])
    if failures:
        for msg in failures:
            log.error("failed: %s", msg)
        raise SystemExit(1)


def _append(runs: Path, row: dict, with_header: bool) -> None:
    """runner.append_row with the sweep's wider header (same flush + fsync semantics)."""
    with open(runs, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SWEEP_FIELDS)
        if with_header:
            w.writeheader()
        w.writerow(row)
        fh.flush()
        os.fsync(fh.fileno())


# ----------------------------------------------------------------------------------------------- summary
def _pen(x: float, opt: float) -> float:
    return (x - opt) / opt


def summarize_rows(rows: list[dict], grid: list[float]) -> tuple[list[dict], list[dict], list[str]]:
    """(summary rows, crossover rows, A2 violations) from runs.csv rows. Rules: D-056."""
    by = {}
    for r in rows:
        by.setdefault((r["topology_id"], float(r["rate_factor"]), float(r["scale"])), {}).setdefault(
            r["method"], []).append(r)
    summary, violations = [], []
    for (topo, f, s), ms in sorted(by.items()):
        ilp = ms["ilp_tight"][0]
        opt = float(ilp["total_usd"])
        out = {"topology_id": topo, "rate_factor": f, "scale": s, "base_edge_gb": float(ilp["base_edge_gb"]),
               "edge_gb": float(ilp["edge_gb"]), "ilp_status": ilp["status"], "ilp_total_usd": opt,
               "ilp_providers_used": int(ilp["providers_used"]), "ilp_egress_share": float(ilp["egress_share"]),
               "ilp_egress_usd": float(ilp["egress_usd"])}
        if ilp["status"] != "optimal":
            violations.append(f"{topo} r={f} s={s:.6g}: ILP status {ilp['status']} (not proven optimal)")
        for m, rs in ms.items():
            if m == "ilp_tight":
                continue
            totals = [float(r["total_usd"]) for r in rs]
            for r, x in zip(rs, totals):
                if x < opt - REL_TOL * max(1.0, opt):
                    violations.append(f"{topo} r={f} s={s:.6g}: {m} seed={r['seed']} {x:.6f} < ILP {opt:.6f}")
            if m == "sa":
                med = statistics.median(totals)
                out.update({"sa_median_usd": med, "sa_min_usd": min(totals), "sa_max_usd": max(totals),
                            "sa_n_seeds": len(totals), "sa_median_penalty": _pen(med, opt),
                            "sa_seeds_at_opt": sum(abs(x - opt) <= REL_TOL * opt for x in totals)})
            else:
                x = totals[0]
                out.update({f"{m}_total_usd": x, f"{m}_providers_used": int(rs[0]["providers_used"]),
                            f"{m}_penalty": _pen(x, opt), f"{m}_egress_share": float(rs[0]["egress_share"])})
        for v in ("b1", "b1_alt"):
            if f"{v}_total_usd" in out:  # H1 form (D-041): reduction of ILP relative to B1
                out[f"h1_reduction_vs_{v}"] = (out[f"{v}_total_usd"] - opt) / out[f"{v}_total_usd"]
        if "b2_best_total_usd" in out:  # tie-robust: some single-provider placement is optimal
            out["single_provider_optimal"] = abs(out["b2_best_total_usd"] - opt) <= REL_TOL * opt
        summary.append(out)

    crossover = []
    groups = sorted({(r["topology_id"], r["rate_factor"]) for r in summary})
    for topo, f in groups:
        pts = sorted((r for r in summary if (r["topology_id"], r["rate_factor"]) == (topo, f)),
                     key=lambda r: r["scale"])
        for criterion, single in (("ilp_providers_used", lambda r: r["ilp_providers_used"] == 1),
                                  ("single_provider_optimal", lambda r: bool(r.get("single_provider_optimal")))):
            idx = None  # smallest index from which every larger scale is single-provider
            for i in range(len(pts) - 1, -1, -1):
                if single(pts[i]):
                    idx = i
                else:
                    break
            for v in ("b1", "b1_alt"):
                if f"{v}_providers_used" not in pts[0]:
                    continue
                b1_prov = sorted({p[f"{v}_providers_used"] for p in pts})
                row = {"topology_id": topo, "rate_factor": f, "criterion": criterion, "b1_variant": v,
                       "b1_providers_used": ",".join(map(str, b1_prov)), "base_edge_gb": pts[0]["base_edge_gb"],
                       "n_points": len(pts), "scale_min": pts[0]["scale"], "scale_max": pts[-1]["scale"],
                       "s_star": "", "s_below": "", "T_gb_month": "", "T_below_gb_month": "",
                       "multi_below": "", "b1_multi_above": "", "crossover": "no", "reason": ""}
                if idx is None:
                    row["reason"] = "optimum multi-provider at the largest scale"
                else:
                    ps = pts[idx]
                    row.update({"s_star": ps["scale"], "T_gb_month": ps["edge_gb"],
                                "multi_below": idx > 0,
                                "b1_multi_above": all(p[f"{v}_providers_used"] > 1 for p in pts[idx:])})
                    if idx > 0:
                        row.update({"s_below": pts[idx - 1]["scale"], "T_below_gb_month": pts[idx - 1]["edge_gb"]})
                    if idx == 0:
                        row["reason"] = "optimum single-provider at every scale (no inversion in range)"
                    elif not row["b1_multi_above"]:
                        row["reason"] = f"{v} is single-provider above s_star"
                    else:
                        row.update({"crossover": "yes", "reason": "optimum multi below s_star, single from s_star; "
                                                                  f"{v} multi-provider"})
                crossover.append(row)
    missing = [(t, f, s) for t, f in groups for s in grid
               if not any(r["topology_id"] == t and r["rate_factor"] == f and math.isclose(r["scale"], s)
                          for r in summary)]
    violations += [f"missing point {m}" for m in missing]
    return summary, crossover, violations


def _write(path: Path, rows: list[dict]) -> None:
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.10g}" if isinstance(v, float) else v) for k, v in r.items()})


def summarize(cfg: dict) -> None:
    """Write summary.csv and crossover.csv for both parts; log A1 counts, A2, H1 at s=1 and the crossovers."""
    grid = scales(cfg)
    bad_total = 0
    for exp_id, methods in ((cfg["exp_id"], cfg["methods"]), (cfg["sensitivity"]["exp_id"],
                                                             cfg["sensitivity"]["methods"])):
        out_dir = ROOT / "results" / exp_id
        runs = out_dir / "runs.csv"
        if not runs.exists():
            log.warning("%s: no runs.csv yet", rel(out_dir))
            continue
        with open(runs, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        summary, crossover, bad = summarize_rows(rows, grid)
        _write(out_dir / "summary.csv", summary)
        _write(out_dir / "crossover.csv", crossover)
        log.info("== %s: %d rows -> summary.csv (%d points), crossover.csv (%d rows)", exp_id, len(rows), len(summary),
                 len(crossover))
        counts = {}
        for r in rows:
            counts.setdefault((r["topology_id"], r["rate_factor"], r["method"]), set()).add(r["scale"])
        for (t, f, m), ss in sorted(counts.items()):
            n_rows = sum(1 for r in rows if (r["topology_id"], r["rate_factor"], r["method"]) == (t, f, m))
            log.info("  A1 %-16s r=%-5s %-12s scales=%2d rows=%3d", t, f, m, len(ss), n_rows)
        log.info("  A2 violations (method below ILP, ILP not optimal, missing points): %d", len(bad))
        for b in bad[:20]:
            log.error("  A2 %s", b)
        bad_total += len(bad)
        for r in summary:
            if math.isclose(r["scale"], 1.0):
                log.info("  s=1 %-16s r=%-5s ILP %10.2f prov=%d | B1 %10.2f pen %.4f red %.4f | B1-alt %10.2f pen %.4f "
                         "red %.4f | B2 %10.2f pen %.4f", r["topology_id"], r["rate_factor"], r["ilp_total_usd"],
                         r["ilp_providers_used"], r["b1_total_usd"], r["b1_penalty"], r["h1_reduction_vs_b1"],
                         r["b1_alt_total_usd"], r["b1_alt_penalty"], r["h1_reduction_vs_b1_alt"],
                         r["b2_best_total_usd"], r["b2_best_penalty"])
        for c in crossover:
            log.info("  X %-16s r=%-5s %-24s %-7s B1prov=%s s*=%s T=%s GB/mo crossover=%s (%s)", c["topology_id"],
                     c["rate_factor"], c["criterion"], c["b1_variant"], c["b1_providers_used"],
                     f"{c['s_star']:.4g}" if c["s_star"] != "" else "-",
                     f"{c['T_gb_month']:.1f}" if c["T_gb_month"] != "" else "-", c["crossover"], c["reason"])
    if bad_total:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="sweep")
    ap.add_argument("--part", choices=["main", "sensitivity"], default=None)
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--tee", default=None)
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args(argv)
    path = ROOT / "experiments" / "configs" / f"{args.config}.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    unknown = [m for m in cfg["methods"] + cfg["sensitivity"]["methods"] if m not in SWEEP_METHODS]
    if unknown:
        raise SystemExit(f"unknown methods {unknown}")
    log_dir = ROOT / "results" / (cfg["exp_id"] if args.part != "sensitivity" else cfg["sensitivity"]["exp_id"])
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(log_dir, (ROOT / args.tee) if args.tee else None)
    if args.part:
        run_part(cfg, path, args.part, args.allow_dirty)
    if args.summarize:
        summarize(cfg)


if __name__ == "__main__":
    main()
