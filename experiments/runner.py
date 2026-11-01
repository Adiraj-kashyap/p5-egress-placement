"""M13 step 2-3: resumable experiment runner over an (instances x methods x seeds) grid.

Reads `experiments/configs/<exp>.json`, expands it into jobs and runs each job that is not yet
in `results/<exp>/runs.csv`. Each finished job is appended to runs.csv at once (flush + fsync),
so a crash loses at most the running job; a rerun skips every job already present (resume).
A torn last line from a hard kill is cut off before appending. `config.json` records the git
commit, machine tag, snapshot date, seeds, time limits, the config's hash and every instance's
hash; a rerun with a different config or a changed instance refuses to mix results (D-051).
Every cost comes from `placement.cost.evaluate`.

Config keys: exp_id, snapshot_date, location_set (str) or location_sets (list), instances (list of
{"topology": path} or {"synthetic": {"n": int|list, "seeds": list, <generator kwargs>}}), methods,
method_seeds (for randomised methods), time_limits {method: seconds|null}, method_params {method: {...}},
method_max_n {method: n} (optional; skip that method on synthetic instances with more than n components).

Plan-v2 replication axes (M16), all optional and all backward compatible:
  draws: [0, 1, ...]      solve every instance on each traffic uncertainty draw (05 §3);
                          the draw is applied to the topology, so every method sees the same draw
                          and comparisons are paired. Column `draw_id`.
  scales: [1.0, ...]      multiply every inter-component edge volume by s (M15's definition,
                          03 §S9: internet egress is not scaled). Part of the instance id.
  timing_repeats: k       re-run each identical job k times for runtime error bars (05 §2).
                          Column `repeat_id` (0..k-1); only the runtime differs between repeats.
An instance id carries its axes: `<topology>@<location_set>[@d=<draw>][@s=<scale>]`.

Run: python -m experiments.runner smoke [--out results/smoke] [--tee evidence/logs/M13_smoke.txt]
     (argument: a config name in experiments/configs/ or a path; --allow-dirty to run on a dirty tree)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from itertools import product
from pathlib import Path
from typing import Callable

from experiments.generate import canonical_sha256, synthetic
from experiments.run_exact import machine_tag
from experiments.uncertainty import draw_topology, scale_edges
from placement.ablations import (b1_storage, no_edge_egress, no_internet, restrict_locations_per_provider,
                                 scale_cross_provider_egress, solve_best_single_provider, undirected)
from placement.annealing import anneal
from placement.baselines import b1_cheapest_per_vcpu, b1_tied_locations, b2_best
from placement.cost import evaluate
from placement.greedy import greedy, greedy_1opt
from placement.ilp import solve_ilp
from placement.instance import HOURS_PER_MONTH, Instance, load_instance, load_topology
from pricing.common import ROOT

STANDARD_FIELDS = ["exp_id", "instance_id", "method", "seed", "n_components", "n_locations", "total_usd",
                   "compute_usd", "storage_usd", "egress_usd", "internet_usd", "egress_share", "providers_used",
                   "runtime_s", "status", "assignment_json", "git_commit", "snapshot_date"]  # 01 §4
EXTRA_FIELDS = ["run_utc", "topology_id", "location_set", "time_limit_s", "proven_optimal", "best_bound",
                "mip_gap", "n_vars", "n_constraints", "detail_json", "machine_tag",
                "draw_id", "repeat_id", "traffic_scale",  # M16: empty for pre-plan-v2 runs
                "egress_mult", "locs_per_provider"]  # M17: empty unless the sensitivity axes are used
FIELDS = STANDARD_FIELDS + EXTRA_FIELDS
DEFAULT_ILP_TIME_LIMIT = 600.0

log = logging.getLogger("runner")


@dataclass
class Outcome:
    """What a method returns to the runner: assignment (None = no solution), status, runtime and extras."""

    assignment: dict[str, str] | None
    status: str
    runtime_s: float
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Method:
    """A registry entry: `run(instance, seed, time_limit, params, cbc_log)` and whether it uses seeds."""

    run: Callable[[Instance, int | None, float | None, dict, Path | None], Outcome]
    randomised: bool = False
    uses_cbc: bool = False


def _timed(fn: Callable[[], dict[str, str]]) -> Outcome:
    t0 = time.perf_counter()
    a = fn()
    return Outcome(a, "ok", time.perf_counter() - t0)


def _ilp(formulation: str, transform: Callable[[Instance], Instance] | None = None):
    """An ILP method. `transform` (M17) is an ablation that cripples the *objective* only:
    the model is built on the transformed instance, and the I8 objective cross-check compares
    CBC against `evaluate` on that same transformed instance. The runner still scores the
    returned assignment with the full, true cost (06 §S12)."""
    def run(inst: Instance, seed, time_limit, params, cbc_log) -> Outcome:
        solve_on = transform(inst) if transform is not None else inst
        res = solve_ilp(solve_on, time_limit if time_limit is not None else DEFAULT_ILP_TIME_LIMIT, formulation,
                        log_path=cbc_log)
        status = "optimal" if res.proven_optimal else ("feasible" if res.assignment else "no_solution")
        if res.assignment is not None and res.objective is not None:
            total = evaluate(solve_on, res.assignment).total
            if not math.isclose(total, res.objective, rel_tol=1e-6, abs_tol=1e-6):  # 02 §1 I8
                raise RuntimeError(f"CBC objective {res.objective} != evaluate() {total}")
        return Outcome(res.assignment, status, res.runtime_s, {
            "proven_optimal": res.proven_optimal, "best_bound": res.best_bound, "mip_gap": res.gap,
            "n_vars": res.n_vars, "n_constraints": res.n_constraints,
            "detail": {"cbc_result": res.cbc_result, "nodes": res.nodes, "cbc_objective": res.objective,
                       "cbc_wall_s": res.cbc_wall_s, "build_s": res.build_s, "n_binaries": res.n_binaries,
                       "n_pairs": res.n_pairs}})
    return run


def _sa(inst: Instance, seed, time_limit, params, cbc_log, **fixed) -> Outcome:
    r = anneal(inst, seed=seed, time_limit=time_limit, **{**params, **fixed})
    return Outcome(r.assignment, "ok", r.runtime_s, {"detail": {
        "initial_usd": round(r.initial_total, 6), "t0": r.t0, "temp_steps": r.temp_steps,
        "moves_tried": r.moves_tried, "moves_accepted": r.moves_accepted, "stop_reason": r.stop_reason,
        "init": r.init, **fixed}})


def _ilp_single_provider(inst: Instance, seed, time_limit, params, cbc_log) -> Outcome:
    """M17 `ilp_single_provider`: the full ILP restricted to one provider, best of the three."""
    provider, res = solve_best_single_provider(inst, time_limit, cbc_log)
    status = "optimal" if res.proven_optimal else ("feasible" if res.assignment else "no_solution")
    return Outcome(res.assignment, status, res.runtime_s, {
        "proven_optimal": res.proven_optimal, "n_vars": res.n_vars, "n_constraints": res.n_constraints,
        "detail": {"provider": provider, "cbc_result": res.cbc_result, "nodes": res.nodes,
                   "cbc_objective": res.objective}})


METHODS: dict[str, Method] = {
    "ilp_tight": Method(_ilp("tight"), uses_cbc=True),
    "ilp_mccormick": Method(_ilp("mccormick"), uses_cbc=True),
    "greedy": Method(lambda inst, s, tl, p, lg: _timed(lambda: greedy(inst))),
    "greedy_1opt": Method(lambda inst, s, tl, p, lg: _timed(lambda: greedy_1opt(inst, **p))),
    "sa": Method(_sa, randomised=True),
    "b1": Method(lambda inst, s, tl, p, lg: _timed(lambda: b1_cheapest_per_vcpu(inst))),
    # B1 with the opposite final tie-break (D-039). M15 reported H1 against both variants, so the
    # replicated runs must carry both as well; identical to experiments.exp_sweep.b1_alt.
    "b1_alt": Method(lambda inst, s, tl, p, lg: _timed(
        lambda: {c: b1_tied_locations(inst, c)[-1] for c in inst.components})),
    "b2_best": Method(lambda inst, s, tl, p, lg: _timed(lambda: b2_best(inst)[1])),
    # ---- M17 ablation variants (06 §S12). Each cripples only the choice; the row's cost
    # columns always come from `evaluate` on the true instance, below in main().
    "ilp_full": Method(_ilp("tight"), uses_cbc=True),  # alias of ilp_tight, the §S12 reference name
    "ilp_no_edge_egress": Method(_ilp("tight", no_edge_egress), uses_cbc=True),
    "ilp_no_internet": Method(_ilp("tight", no_internet), uses_cbc=True),
    "ilp_undirected": Method(_ilp("tight", undirected), uses_cbc=True),
    "ilp_single_provider": Method(_ilp_single_provider, uses_cbc=True),
    "b1_storage": Method(lambda inst, s, tl, p, lg: _timed(lambda: b1_storage(inst))),
    "sa_random_init": Method(lambda inst, s, tl, p, lg: _sa(inst, s, tl, p, lg, init="random"),
                             randomised=True),
    "sa_no_swap": Method(lambda inst, s, tl, p, lg: _sa(inst, s, tl, p, lg, p_relocate=1.0),
                         randomised=True),
}


@dataclass(frozen=True)
class InstanceSpec:
    """One topology source: a repo path or synthetic generator arguments (without location_set)."""

    kind: str  # "topology" | "synthetic"
    path: str | None = None
    gen: tuple = ()
    draw_id: int | None = None  # M16: traffic uncertainty draw (05 §3)
    scale: float | None = None  # M16: inter-component traffic scale (03 §S9)
    egress_mult: float | None = None  # M17: cross-provider egress price multiplier (06 §S12)
    locs_per_provider: int | None = None  # M17: regions kept per provider (06 §S12)

    def topology(self, location_set: str) -> dict:
        """The topology dict for `location_set`, after the draw and the traffic scale."""
        if self.kind == "topology":
            topo = load_topology(self.path)
        else:
            topo = synthetic(location_set=location_set, **dict(self.gen))
        if self.draw_id is not None:
            topo = draw_topology(topo, self.draw_id)
        if self.scale is not None:
            topo = scale_edges(topo, self.scale)
        return topo

    def price_world(self, inst: Instance) -> Instance:
        """Apply the M17 price/location-set transforms, which change the true cost model itself.

        Unlike `topology()`, these are not part of the workload: they re-price the world the
        instance lives in, so a row produced under them is comparable only with rows under the
        same (egress_mult, locs_per_provider). Both are recorded as their own runs.csv columns.
        """
        if self.egress_mult is not None:
            inst = scale_cross_provider_egress(inst, self.egress_mult)
        if self.locs_per_provider is not None:
            inst = restrict_locations_per_provider(inst, self.locs_per_provider)
        return inst

    def suffix(self) -> str:
        """The `@d=..@s=..@x=..@k=..` part of the instance id (empty when no axis is used)."""
        out = "" if self.draw_id is None else f"@d={self.draw_id}"
        out += "" if self.scale is None else f"@s={self.scale:.6g}"
        out += "" if self.egress_mult is None else f"@x={self.egress_mult:.6g}"
        return out + ("" if self.locs_per_provider is None else f"@k={self.locs_per_provider}")

    def source(self) -> str:
        """Human-readable provenance for config.json."""
        base = self.path if self.kind == "topology" else "experiments.generate.synthetic" + json.dumps(dict(self.gen))
        return base + self.suffix()


def load_config(arg: str) -> tuple[dict, Path]:
    """Load a config by name (experiments/configs/<name>.json) or path; validate its keys."""
    path = Path(arg)
    if not path.suffix:
        path = ROOT / "experiments" / "configs" / f"{arg}.json"
    elif not path.is_absolute():
        path = (Path.cwd() / path) if (Path.cwd() / path).exists() else ROOT / path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for key in ("exp_id", "snapshot_date", "instances", "methods"):
        if key not in cfg:
            raise ValueError(f"{path}: missing key {key!r}")
    unknown = [m for m in cfg["methods"] if m not in METHODS]
    if unknown:
        raise ValueError(f"{path}: unknown methods {unknown}; known: {sorted(METHODS)}")
    if any(METHODS[m].randomised for m in cfg["methods"]) and not cfg.get("method_seeds"):
        raise ValueError(f"{path}: randomised methods need a non-empty method_seeds list")
    stray = [m for m in cfg.get("method_max_n", {}) if m not in cfg["methods"]]
    if stray:
        raise ValueError(f"{path}: method_max_n names methods not in methods: {stray}")
    return cfg, path


def location_sets(cfg: dict) -> list[str]:
    """The config's location sets, from `location_sets` (list) or `location_set` (str, default core)."""
    return list(cfg.get("location_sets") or [cfg.get("location_set", "core")])


def instance_specs(cfg: dict) -> list[InstanceSpec]:
    """Expand the config's `instances` list over n x seeds, then over `draws` x `scales` (M16)."""
    base: list[InstanceSpec] = []
    for entry in cfg["instances"]:
        if "topology" in entry:
            base.append(InstanceSpec("topology", path=entry["topology"]))
            continue
        gen = dict(entry["synthetic"])
        ns = gen.pop("n")
        seeds = gen.pop("seeds")
        for n, s in product(ns if isinstance(ns, list) else [ns], seeds):
            base.append(InstanceSpec("synthetic", gen=tuple(sorted({**gen, "n": n, "seed": s}.items()))))
    draws = cfg.get("draws") or [None]
    scales = cfg.get("scales") or [None]
    mults = cfg.get("egress_multipliers") or [None]  # M17
    kper = cfg.get("locations_per_provider") or [None]  # M17
    if draws == [None] and scales == [None] and mults == [None] and kper == [None]:
        return base
    return [InstanceSpec(b.kind, b.path, b.gen, d, None if s is None else float(s),
                         None if x is None else float(x), None if k is None else int(k))
            for b, d, s, x, k in product(base, draws, scales, mults, kper)]


def build_jobs(cfg: dict) -> list[tuple[str, InstanceSpec, str, int | None, int | None]]:
    """(location_set, spec, method, seed, repeat_id) for every job, grouped by instance.

    `method_max_n` {method: n} drops that method on synthetic instances with more than n components (M14 runs the
    McCormick ablation only for n <= 12); it cannot apply to repo topologies, whose size is unknown until loaded.
    """
    max_n = cfg.get("method_max_n", {})
    if "timing_repeats" in cfg:
        repeats = int(cfg["timing_repeats"])
        if repeats < 1:
            raise ValueError(f"timing_repeats must be >= 1, got {repeats}")
        repeat_ids: list[int | None] = list(range(repeats))
    else:
        repeat_ids = [None]  # no repeat axis: rows keep the pre-plan-v2 empty repeat_id
    jobs = []
    for ls, spec, m in product(location_sets(cfg), instance_specs(cfg), cfg["methods"]):
        if m in max_n:
            if spec.kind != "synthetic":
                raise ValueError(f"method_max_n[{m!r}] applies only to synthetic instances, not {spec.path}")
            if dict(spec.gen)["n"] > max_n[m]:
                continue
        for s, rep in product(cfg.get("method_seeds", []) if METHODS[m].randomised else [None],
                              repeat_ids):
            jobs.append((ls, spec, m, s, rep))
    return jobs


def job_key(instance_id: str, method: str, seed, repeat=None) -> tuple[str, str, str, str]:
    """Identity of a job inside one experiment (snapshot date is fixed per experiment by the config hash).

    `repeat` is the timing repeat index (M16); it is "" for every pre-plan-v2 row, which is
    exactly what a config without `timing_repeats` produces, so old results still resume.
    """
    return (instance_id, method, "" if seed is None else str(seed),
            "" if repeat in (None, "") else str(repeat))


def read_done(runs: Path) -> set[tuple[str, str, str, str]]:
    """Job keys already in runs.csv. A torn last line (hard kill mid-write) is truncated first."""
    if not runs.exists() or runs.stat().st_size == 0:
        return set()
    data = runs.read_bytes()
    if not data.endswith(b"\n"):
        keep = data[: data.rfind(b"\n") + 1]
        log.warning("runs.csv ends in a torn line (%d bytes); truncating it", len(data) - len(keep))
        with open(runs, "wb") as f:
            f.write(keep)
            f.flush()
            os.fsync(f.fileno())
    with open(runs, newline="", encoding="utf-8") as f:
        return {job_key(r["instance_id"], r["method"], r["seed"] or None, r.get("repeat_id"))
                for r in csv.DictReader(f)}


def existing_header(runs: Path) -> list[str] | None:
    """The column names already in runs.csv, or None if the file is new/empty."""
    if not runs.exists() or runs.stat().st_size == 0:
        return None
    with open(runs, newline="", encoding="utf-8") as f:
        return next(csv.reader(f), None)


def append_row(runs: Path, row: dict) -> None:
    """Append one row (header first if the file is new) and force it to disk.

    An existing file keeps its own header, so a results directory written before the M16
    columns existed can still be resumed without shifting its columns; the extra values
    are dropped for that directory.
    """
    header = existing_header(runs)
    new = header is None
    with open(runs, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header or FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def git_state(exclude: Path) -> tuple[str, list[str]]:
    """(short HEAD or 'unknown', changed paths outside `exclude`). The results dir itself may be dirty on resume."""
    exe = shutil.which("git")
    if exe is None:
        return "unknown", []
    try:
        head = subprocess.run([exe, "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        status = subprocess.run([exe, "status", "--porcelain", "--untracked-files=all"], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return "unknown", []
    try:
        prefix = exclude.resolve().relative_to(ROOT.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        prefix = None
    changed = [line[3:].strip('"') for line in status]
    return head, [p for p in changed if prefix is None or not p.startswith(prefix)]


def rel(path: Path) -> str:
    """Repo-relative posix path when inside the repo, else the absolute path."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def setup_logging(out_dir: Path, tee: Path | None) -> None:
    """Log to stdout, logs/runner_<date>.log, <out>/run.log (append) and the optional tee file."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    plain = logging.Formatter("%(message)s")
    stamped = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    (ROOT / "logs").mkdir(exist_ok=True)
    targets = [(logging.StreamHandler(sys.stdout), plain),
               (logging.FileHandler(ROOT / "logs" / f"runner_{date.today().isoformat()}.log", encoding="utf-8"),
                stamped),
               (logging.FileHandler(out_dir / "run.log", mode="a", encoding="utf-8"), stamped)]
    if tee is not None:
        tee.parent.mkdir(parents=True, exist_ok=True)
        targets.append((logging.FileHandler(tee, mode="w", encoding="utf-8"), plain))
    for handler, fmt in targets:
        handler.setFormatter(fmt)
        log.addHandler(handler)
    ilp_log = logging.getLogger("placement.ilp")  # per-solve lines go to the stamped files only (02 §7)
    ilp_log.setLevel(logging.INFO)
    ilp_log.handlers.clear()
    ilp_log.propagate = False
    for handler, _ in targets[1:3]:
        ilp_log.addHandler(handler)


def main(argv: list[str] | None = None) -> None:
    """Expand the config into jobs, skip finished ones, run the rest, append rows, update config.json."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", help="config name in experiments/configs/ or a path to a JSON file")
    ap.add_argument("--out", default=None, help="results directory (default results/<exp_id>)")
    ap.add_argument("--tee", default=None, help="also write the console output to this file (UTF-8)")
    ap.add_argument("--allow-dirty", action="store_true", help="run even if the tree outside --out is dirty")
    ap.add_argument("--stop-after", type=int, default=None,
                    help="testing aid: hard-exit (os._exit(3), no cleanup) after this many new rows")
    args = ap.parse_args(argv)

    cfg, cfg_path = load_config(args.config)
    exp_id = cfg["exp_id"]
    out_dir = Path(args.out) if args.out else ROOT / "results" / exp_id
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    commit, dirty = git_state(out_dir)  # before anything is written
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir, (ROOT / args.tee) if args.tee else None)
    if (commit == "unknown" or dirty) and not args.allow_dirty:
        log.error("refusing to run: git %s, %d changed path(s) outside %s (e.g. %s). Commit first, put git "
                  "on PATH, or pass --allow-dirty.", commit, len(dirty), rel(out_dir), dirty[:3])
        raise SystemExit(2)
    if dirty:
        commit += "-dirty"
    tag = machine_tag()
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg_sha = canonical_sha256(cfg)
    snapshot = cfg["snapshot_date"]
    time_limits = cfg.get("time_limits", {})
    params = cfg.get("method_params", {})
    seeds = cfg.get("method_seeds", [])

    config_path = out_dir / "config.json"
    record = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else None
    if record is not None and record.get("config_sha256") != cfg_sha:
        log.error("refusing to mix results: %s was produced by a different config (sha256 %s, now %s). "
                  "Use a new exp_id or --out.", rel(config_path), record.get("config_sha256"), cfg_sha)
        raise SystemExit(2)
    if record is None:
        record = {"exp_id": exp_id, "created_utc": run_utc, "config_path": rel(cfg_path), "config_sha256": cfg_sha,
                  "config": cfg, "snapshot_date": snapshot, "cost_model_dir": f"cost_model/{snapshot}",
                  "hours_per_month": HOURS_PER_MONTH, "method_seeds": seeds, "time_limits": time_limits,
                  "ilp_default_time_limit_s": DEFAULT_ILP_TIME_LIMIT, "threads": 1, "machine_tag": tag,
                  "git_commit": commit, "python": platform.python_version(), "instances": {}, "sessions": [],
                  "notes": {"runs.csv": "one row per (instance, method, seed); standard columns (01 §4) first; "
                                        "appended as each job finishes; resume skips present keys.",
                            "runtime_s": "method wall time; ILP = build + CBC; greedy_1opt includes greedy.",
                            "status": "optimal (ILP proven) | feasible (ILP incumbent, not proven) | "
                                      "no_solution | ok (heuristic or baseline)"}}

    runs = out_dir / "runs.csv"
    done = read_done(runs)
    jobs = build_jobs(cfg)
    log.info("M13 runner | exp %s | config %s (sha256 %s) | snapshot %s | machine %s | git %s | run %s",
             exp_id, rel(cfg_path), cfg_sha[:12], snapshot, tag, commit, run_utc)

    session = {"run_utc": run_utc, "git_commit": commit, "machine_tag": tag, "jobs_total": len(jobs),
               "jobs_skipped": 0, "jobs_run": 0, "jobs_failed": 0, "wall_s": None, "finished": False}
    record["sessions"].append(session)
    config_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    t_start = time.perf_counter()
    cache: dict[tuple[str, InstanceSpec], Instance] = {}
    failures, written = [], 0
    for i, (ls, spec, m, s, rep) in enumerate(jobs, 1):
        if (ls, spec) not in cache:
            topo = spec.topology(ls)
            inst = spec.price_world(load_instance(topo, snapshot, ls))
            if spec.suffix():
                inst = replace(inst, instance_id=inst.instance_id + spec.suffix())
            h = canonical_sha256(topo)
            prev = record["instances"].get(inst.instance_id)
            if prev is not None and prev["sha256"] != h:
                log.error("instance %s changed since the first run (sha256 %s -> %s); refusing to mix",
                          inst.instance_id, prev["sha256"][:12], h[:12])
                raise SystemExit(2)
            record["instances"][inst.instance_id] = {"source": spec.source(), "location_set": ls, "sha256": h,
                                                     "n_components": inst.n_components,
                                                     "n_locations": inst.n_locations, "n_edges": len(inst.edges)}
            if prev is None:
                config_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            cache = {(ls, spec): inst}  # jobs are grouped by instance; keep one in memory
        inst = cache[(ls, spec)]
        key = job_key(inst.instance_id, m, s, rep)
        if key in done:
            session["jobs_skipped"] += 1
            continue
        method = METHODS[m]
        cbc_log = None
        if method.uses_cbc:
            (out_dir / "cbc").mkdir(exist_ok=True)
            stem = inst.instance_id.replace("@", "_").replace("=", "")
            cbc_log = out_dir / "cbc" / f"{stem}__{m}{'' if rep is None else f'__r{rep}'}.log"
        tl = time_limits.get(m)
        try:
            res = method.run(inst, s, tl, dict(params.get(m, {})), cbc_log)
            if res.assignment is not None:
                bad = [c for c in inst.components if res.assignment.get(c) not in inst.allowed[c]]
                if bad:
                    raise RuntimeError(f"assignment violates allowed locations for {bad[:3]}")
        except Exception as exc:  # record, keep going; the job has no row, so a rerun retries it
            failures.append(f"{inst.instance_id} {m} seed={s}: {type(exc).__name__}: {exc}")
            session["jobs_failed"] += 1
            log.error("job %d/%d FAILED %s %s seed=%s: %s: %s", i, len(jobs), inst.instance_id, m, s,
                      type(exc).__name__, exc)
            continue
        row = {k: "" for k in FIELDS}
        row.update({"exp_id": exp_id, "instance_id": inst.instance_id, "method": m, "seed": "" if s is None else s,
                    "n_components": inst.n_components, "n_locations": inst.n_locations,
                    "runtime_s": f"{res.runtime_s:.6f}", "status": res.status, "git_commit": commit,
                    "snapshot_date": snapshot, "run_utc": run_utc, "topology_id": inst.topology_id,
                    "location_set": ls, "time_limit_s": "" if tl is None else tl, "machine_tag": tag,
                    "draw_id": "" if spec.draw_id is None else spec.draw_id,
                    "repeat_id": "" if rep is None else rep,
                    "traffic_scale": "" if spec.scale is None else repr(spec.scale),
                    "egress_mult": "" if spec.egress_mult is None else repr(spec.egress_mult),
                    "locs_per_provider": "" if spec.locs_per_provider is None else spec.locs_per_provider,
                    "detail_json": json.dumps(res.extra.get("detail", {}), separators=(",", ":"))})
        for k in ("proven_optimal", "best_bound", "mip_gap", "n_vars", "n_constraints"):
            if res.extra.get(k) is not None:
                row[k] = res.extra[k]
        if res.assignment is not None:
            cb = evaluate(inst, res.assignment)
            row.update({"total_usd": round(cb.total, 6), "compute_usd": round(cb.compute, 6),
                        "storage_usd": round(cb.storage, 6), "egress_usd": round(cb.egress, 6),
                        "internet_usd": round(cb.internet, 6), "egress_share": round(cb.egress_share, 8),
                        "providers_used": cb.providers_used,
                        "assignment_json": json.dumps(res.assignment, separators=(",", ":"))})
        append_row(runs, row)
        done.add(key)
        written += 1
        session["jobs_run"] += 1
        log.info("job %d/%d %-22s %-13s seed=%-3s %-8s total=%12s  %.4f s", i, len(jobs), inst.instance_id, m,
                 "" if s is None else s, res.status, row["total_usd"], res.runtime_s)
        if args.stop_after is not None and written >= args.stop_after:
            log.warning("--stop-after %d reached: hard exit (simulated crash)", args.stop_after)
            logging.shutdown()
            os._exit(3)

    session.update({"wall_s": round(time.perf_counter() - t_start, 3), "finished": True})
    config_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    with open(runs, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log.info("")
    log.info("jobs %d | skipped (already present) %d | run %d | failed %d | runs.csv rows %d | wall %.1f s",
             len(jobs), session["jobs_skipped"], session["jobs_run"], session["jobs_failed"], len(rows),
             session["wall_s"])
    log.info("  %-14s %5s %9s %14s", "method", "rows", "statuses", "median_runtime_s")
    for m in cfg["methods"]:
        mr = [r for r in rows if r["method"] == m]
        if mr:
            st = ",".join(sorted({r["status"] for r in mr}))
            log.info("  %-14s %5d %9s %14.4f", m, len(mr), st, statistics.median(float(r["runtime_s"]) for r in mr))
    if failures:
        for msg in failures:
            log.error("failed: %s", msg)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
