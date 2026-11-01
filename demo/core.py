"""Solver and data plumbing for the live demo — no Streamlit, no network.

Everything the demo shows is computed here from committed inputs only:
`cost_model/<date>/`, `topologies/*.json` and the precomputed CSVs in `demo/cache/`.
Every cost reported by this module comes from `placement.cost.evaluate` (D-006), so the
demo can never disagree with the experiments.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from experiments.generate import synthetic
from experiments.uncertainty import scale_edges
from placement.baselines import b1_cheapest_per_vcpu, b2_best
from placement.cost import CostBreakdown, evaluate
from placement.greedy import greedy, greedy_1opt
from placement.ilp import solve_ilp
from placement.instance import Instance, load_instance, load_topology, provider_of

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(__file__).resolve().parent / "cache"
SNAPSHOT_DATE = "2026-09-21"

TOPOLOGIES = {
    "T1 three-tier (measured)": "topologies/t1_three_tier.json",
    "T2 pipeline": "topologies/t2_pipeline.json",
    "T3 microservices": "topologies/t3_microservices.json",
}

#: Method id -> label shown in the UI. `b2_best` and the baselines are not "solvers" but
#: are run the same way so one table can hold them all.
METHODS = {
    "ilp_tight": "ILP (exact, CBC)",
    "sa": "Simulated annealing",
    "greedy_1opt": "Greedy + 1-opt",
    "greedy": "Greedy",
    "b1": "B1 cheapest-per-vCPU (egress-blind)",
    "b2_best": "B2-best single provider",
}

DEFAULT_METHODS = ("ilp_tight", "greedy_1opt", "b1", "b2_best")

#: Demo-only ILP time limit. The real experiments use 600 s (M13); here a solve that does
#: not finish quickly would ruin the demonstration, so it is capped and the cap is shown.
DEMO_TIME_LIMIT_S = 30.0

#: Colour per provider, used for the placement table and the provider legend.
PROVIDER_COLOURS = {"aws": "#ff9900", "azure": "#0078d4", "gcp": "#34a853"}


@dataclass
class MethodResult:
    """One method's answer on one instance, scored by `evaluate`."""

    method: str
    label: str
    assignment: dict[str, str]
    cost: CostBreakdown
    runtime_s: float
    #: Solver-specific notes for the UI (e.g. "proven optimal", "seed 0, 412 temperature steps").
    note: str = ""
    proven_optimal: bool | None = None

    @property
    def total(self) -> float:
        return self.cost.total


@dataclass
class RunOutcome:
    """Everything one Run button press produced."""

    instance: Instance
    results: list[MethodResult] = field(default_factory=list)
    traffic_scale: float = 1.0

    @property
    def succeeded(self) -> list[MethodResult]:
        """Results from methods that actually produced an assignment."""
        return [r for r in self.results if r.assignment]

    @property
    def best(self) -> MethodResult:
        """The cheapest result among the methods that succeeded.

        Failed methods carry a zero-cost placeholder, so they must be excluded here or a
        crashed solver would be shown as the winner and every penalty would be nonsense.
        """
        good = self.succeeded
        if not good:
            raise RuntimeError("no method produced an assignment")
        return min(good, key=lambda r: r.total)

    def penalty_pct(self, method: str) -> float | None:
        """Percent by which `method` exceeds the best result found in this run."""
        ref = self.best.total
        for r in self.results:
            if r.method == method and ref > 0 and r.assignment:
                return 100.0 * (r.total - ref) / ref
        return None


# --------------------------------------------------------------------------- instances


def build_instance(topology: str | Path | dict, location_set: str = "core",
                   traffic_scale: float = 1.0,
                   snapshot_date: str = SNAPSHOT_DATE) -> Instance:
    """Load a topology, scale its inter-component edges by `traffic_scale`, and price it.

    Internet egress is deliberately left unscaled, exactly as the M15 sweep does
    (`experiments.uncertainty.scale_edges`), so the demo slider means the same thing as
    the x-axis of the cached curves.
    """
    topo = load_topology(topology)
    if traffic_scale != 1.0:
        topo = scale_edges(topo, traffic_scale)
    return load_instance(topo, snapshot_date, location_set)


def synthetic_instance(n: int, location_set: str = "core", seed: int = 1,
                       traffic_scale: float = 1.0,
                       snapshot_date: str = SNAPSHOT_DATE) -> Instance:
    """Price a freshly generated synthetic topology of `n` components (M13 generator)."""
    return build_instance(synthetic(n, location_set, seed), location_set,
                          traffic_scale, snapshot_date)


# --------------------------------------------------------------------------- solvers


def _run_one(instance: Instance, method: str, sa_seed: int = 0,
             time_limit: float = DEMO_TIME_LIMIT_S) -> MethodResult:
    t0 = time.perf_counter()
    note, proven = "", None

    if method == "ilp_tight":
        res = solve_ilp(instance, time_limit=time_limit, formulation="tight")
        if res.assignment is None:
            raise RuntimeError(f"ILP found no integer solution (status {res.status})")
        assignment, proven = res.assignment, res.proven_optimal
        note = ("proven optimal" if res.proven_optimal
                else f"best found, not proven (limit {time_limit:g} s)")
    elif method == "greedy":
        assignment = greedy(instance)
    elif method == "greedy_1opt":
        assignment = greedy_1opt(instance)
    elif method == "sa":
        from placement.annealing import anneal  # local: keeps import cost off the fast paths
        res = anneal(instance, seed=sa_seed)
        assignment = res.assignment
        note = f"seed {sa_seed}, {res.temp_steps} temperature steps, stop: {res.stop_reason}"
    elif method == "b1":
        assignment = b1_cheapest_per_vcpu(instance)
    elif method == "b2_best":
        provider, assignment, _ = b2_best(instance)
        note = f"all components on {provider}"
    else:
        raise ValueError(f"unknown method {method!r}")

    runtime = time.perf_counter() - t0
    return MethodResult(method=method, label=METHODS[method], assignment=dict(assignment),
                        cost=evaluate(instance, assignment), runtime_s=runtime,
                        note=note, proven_optimal=proven)


def run_methods(instance: Instance, methods=DEFAULT_METHODS, sa_seed: int = 0,
                time_limit: float = DEMO_TIME_LIMIT_S,
                traffic_scale: float = 1.0) -> RunOutcome:
    """Run each method on `instance` and score every answer with `evaluate`.

    Methods are run in the order given. A method that raises is skipped with its error
    recorded as a note, so one failing solver cannot take the demo down.
    """
    out = RunOutcome(instance=instance, traffic_scale=traffic_scale)
    for m in methods:
        try:
            out.results.append(_run_one(instance, m, sa_seed=sa_seed, time_limit=time_limit))
        except Exception as exc:  # demo robustness: show it, do not crash
            out.results.append(MethodResult(
                method=m, label=METHODS.get(m, m), assignment={},
                cost=CostBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0),
                runtime_s=0.0, note=f"FAILED: {exc}"))
    return out


def placement_rows(instance: Instance, results: list[MethodResult]) -> list[dict]:
    """One row per component, one column per method: where that method put it."""
    rows = []
    for c in instance.components:
        row = {"component": c, "vCPU": instance.vcpu[c], "shape": instance.shape[c]}
        for r in results:
            row[r.label] = r.assignment.get(c, "-")
        rows.append(row)
    return rows


def cost_rows(outcome: RunOutcome) -> list[dict]:
    """One row per method: the cost breakdown plus penalty against the best method."""
    ref = outcome.best.total
    rows = []
    for r in outcome.results:
        rows.append({
            "method": r.label,
            "total": r.cost.total,
            "compute": r.cost.compute,
            "storage": r.cost.storage,
            "egress": r.cost.egress,
            "internet": r.cost.internet,
            "egress_share_pct": 100.0 * r.cost.egress_share,
            "providers_used": r.cost.providers_used,
            "penalty_vs_best_pct": (100.0 * (r.cost.total - ref) / ref
                                    if ref > 0 and r.assignment else ""),
            "runtime_s": r.runtime_s,
            "note": r.note,
        })
    return rows


def provider_colour(location: str) -> str:
    """Hex colour for a `provider:region` id, for the placement table."""
    try:
        return PROVIDER_COLOURS.get(provider_of(location), "#888888")
    except Exception:
        return "#888888"


# --------------------------------------------------------------------------- cache


CACHE_FILES = ("R2-1_cost_vs_scale.csv", "F2_egress_penalty.csv", "F3_providers_used.csv",
               "F0_sa_convergence.csv", "F1_cost_breakdown.csv", "F4_runtime_vs_n.csv",
               "F5_gap_boxplots.csv", "F6_gain_decomposition.csv", "F7_sensitivity.csv")


def load_cache_csv(name: str) -> list[dict]:
    """Read one cached summary CSV from `demo/cache/` as a list of dicts.

    Raises FileNotFoundError with the rebuild command if the cache was never built.
    """
    path = CACHE / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing - run `python -m demo.build_cache` before the demo")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cache_manifest() -> dict:
    """The manifest written by `demo.build_cache`, or {} when the cache is absent."""
    path = CACHE / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def curve(rows: list[dict], topology_id: str, method: str, value: str = "mean",
          method_key: str = "method") -> tuple[list[float], list[float], list[float], list[float]]:
    """Extract (scale, value, ci_lo, ci_hi) for one topology and method, sorted by scale."""
    sel = [r for r in rows if r["topology_id"] == topology_id and r[method_key] == method]
    sel.sort(key=lambda r: float(r["traffic_scale"]))
    return ([float(r["traffic_scale"]) for r in sel],
            [float(r[value]) for r in sel],
            [float(r["ci_lo"]) for r in sel],
            [float(r["ci_hi"]) for r in sel])


# --------------------------------------------------------------------------- testbed


def t1_from_bytes(bytes_per_request: dict[tuple[str, str], float], rate_per_s: float,
                  internet_bytes: float | None = None) -> dict:
    """Rebuild the T1 topology dict from fresh per-edge bytes/request measurements.

    Mirrors `topologies/build.py` exactly: GB/month = bytes x req/s x 2,592,000 / 1e9, and
    only the volumes change - components, shapes and storage stay as committed. Used by the
    Live testbed tab to re-optimise T1 on the spot from a measurement taken minutes earlier.
    """
    from topologies.build import gb_per_month

    topo = load_topology("topologies/t1_three_tier.json")
    for edge in topo["edges"]:
        key = (edge["src"], edge["dst"])
        if key in bytes_per_request:
            edge["gb_per_month"] = gb_per_month(bytes_per_request[key], rate_per_s)
            edge["rationale"] = (f"{bytes_per_request[key]:g} B per web request "
                                 f"(live demo measurement) x {rate_per_s:g} req/s")
    if internet_bytes is not None:
        for ie in topo.get("internet_egress", []):
            ie["gb_per_month"] = gb_per_month(internet_bytes, rate_per_s)
    topo.setdefault("assumptions", {})["requests_per_s"] = rate_per_s
    return topo


def cached_measurement() -> dict[tuple[str, str], float]:
    """Per-edge mean bytes/request from the committed M07 summary (the fallback measurement)."""
    path = ROOT / "testbed" / "measurements" / "summary.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return {(r["src"], r["dst"]): float(r["bytes_per_request_mean"])
                for r in csv.DictReader(f)}
