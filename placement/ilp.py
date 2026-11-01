"""Exact egress-coupled placement ILP, solved with CBC through PuLP (03_SKILLS §S6).

Variables: x[c,l] in {0,1} (component c at allowed location l) and, per merged edge pair
P = {u, v}, continuous y[P,l,m] >= 0 standing for x[u,l] * x[v,m]. The two directions of an
edge share one y-set with coefficient w_uv * egress[l,m] + w_vu * egress[m,l].

    min  sum k[c,l] x[c,l] + sum q[c] r[l] x[c,l] + sum_P sum_(l,m) W[P,l,m] y[P,l,m]
    s.t. sum_l x[c,l] = 1                                  for all c
         tight:     sum_m y[P,l,m] = x[u,l]   for all P, l ;   sum_l y[P,l,m] = x[v,m]   for all P, m
         mccormick: y[P,l,m] >= x[u,l] + x[v,m] - 1        for all P, l, m

Pinned components only get x variables at their pinned location. The objective equals
`placement.cost.evaluate` on the returned assignment (tested, 02 §1 I8); the full derivation
is in docs/report/formulation.md.
"""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pulp

from placement.cbc_log import parse_cbc_log_file
from placement.instance import Instance

FORMULATIONS = ("tight", "mccormick")

log = logging.getLogger("placement.ilp")


@dataclass(frozen=True)
class Result:
    """Outcome of one ILP solve.

    `objective` is CBC's objective value (None if no integer solution was found);
    `proven_optimal` and `best_bound` come from the CBC log, not PuLP's status (§S6).
    `status` is PuLP's status string. `runtime_s` is wall time around the CBC call
    (model build excluded); `cbc_wall_s` is CBC's own reported wall time.
    """

    assignment: dict[str, str] | None
    objective: float | None
    status: str
    proven_optimal: bool
    best_bound: float | None
    gap: float | None
    runtime_s: float
    cbc_wall_s: float | None
    build_s: float
    n_vars: int
    n_constraints: int
    n_binaries: int
    n_pairs: int
    formulation: str
    cbc_result: str
    nodes: int | None
    log_path: str | None


def merged_pairs(instance: Instance) -> dict[tuple[str, str], tuple[float, float]]:
    """Merge directed edges into unordered pairs: {(u, v): (w_uv, w_vu)} with u before v in component order.

    Parallel edges in the same direction are summed. Self-loops (u == v) are returned under
    (u, u) with all their volume in w_uv; they cost gb * egress[l, l] and stay linear in x.
    """
    order = {c: i for i, c in enumerate(instance.components)}
    pairs: dict[tuple[str, str], list[float]] = {}
    for u, v, gb in instance.edges:
        if order[u] <= order[v]:
            pairs.setdefault((u, v), [0.0, 0.0])[0] += gb
        else:
            pairs.setdefault((v, u), [0.0, 0.0])[1] += gb
    return {p: (w[0], w[1]) for p, w in pairs.items()}


def build_model(instance: Instance, formulation: Literal["tight", "mccormick"] = "tight"
                ) -> tuple[pulp.LpProblem, dict[tuple[str, str], pulp.LpVariable], int]:
    """Build the PuLP model of `instance`. Returns (problem, x variables, number of merged pairs).

    Raises ValueError on an unknown formulation, or for `mccormick` if any merged egress
    coefficient is negative (the one-sided McCormick bound is only exact for a minimisation
    with non-negative coefficients).
    """
    if formulation not in FORMULATIONS:
        raise ValueError(f"unknown formulation {formulation!r}; expected one of {FORMULATIONS}")
    idx = {l: i for i, l in enumerate(instance.locations)}
    cidx = {c: i for i, c in enumerate(instance.components)}
    prob = pulp.LpProblem(f"placement_{formulation}", pulp.LpMinimize)
    x = {(c, l): prob.add_variable(f"x_{cidx[c]}_{idx[l]}", cat=pulp.LpBinary)
         for c in instance.components for l in instance.allowed[c]}

    lin = {key: instance.k[key] + instance.internet_gb.get(key[0], 0.0) * instance.r[key[1]] for key in x}
    quad_terms = []
    pairs = merged_pairs(instance)
    for pi, ((u, v), (w_uv, w_vu)) in enumerate(pairs.items()):
        if u == v:
            for l in instance.allowed[u]:
                lin[(u, l)] += w_uv * instance.egress[(l, l)]
            continue
        lu, lv = instance.allowed[u], instance.allowed[v]
        y = {}
        for l in lu:
            for m in lv:
                coef = w_uv * instance.egress[(l, m)] + w_vu * instance.egress[(m, l)]
                if formulation == "mccormick" and coef < 0:
                    raise ValueError(f"negative egress coefficient on {u}-{v} at ({l}, {m})")
                y[(l, m)] = prob.add_variable(f"y_{pi}_{idx[l]}_{idx[m]}", lowBound=0)
                if coef:
                    quad_terms.append((y[(l, m)], coef))
        if formulation == "tight":
            for l in lu:
                prob += pulp.lpSum(y[(l, m)] for m in lv) == x[(u, l)], f"row_{pi}_{idx[l]}"
            for m in lv:
                prob += pulp.lpSum(y[(l, m)] for l in lu) == x[(v, m)], f"col_{pi}_{idx[m]}"
        else:
            for (l, m), var in y.items():
                prob += var >= x[(u, l)] + x[(v, m)] - 1, f"mc_{pi}_{idx[l]}_{idx[m]}"

    prob += pulp.lpSum(coef * var for var, coef in
                       [(x[key], c) for key, c in lin.items()] + quad_terms), "total_cost"
    for c in instance.components:
        prob += pulp.lpSum(x[(c, l)] for l in instance.allowed[c]) == 1, f"assign_{cidx[c]}"
    return prob, x, len(pairs)


def solve_ilp(instance: Instance, time_limit: float = 600,
              formulation: Literal["tight", "mccormick"] = "tight",
              log_path: str | Path | None = None) -> Result:
    """Solve the placement ILP of `instance` with CBC (threads=1) and return a `Result`.

    The CBC log is written to `log_path` (or a temporary file that is deleted afterwards)
    and parsed for proven optimality, best bound and gap. The assignment is read from the
    binaries (x > 0.5); it is None when CBC found no integer solution.
    """
    t0 = time.perf_counter()
    prob, x, n_pairs = build_model(instance, formulation)
    build_s = time.perf_counter() - t0

    tmp = None
    if log_path is None:
        tmp = tempfile.NamedTemporaryFile(prefix="cbc_", suffix=".log", delete=False)
        tmp.close()
        path = Path(tmp.name)
    else:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, logPath=str(path), threads=1)
    t0 = time.perf_counter()
    prob.solve(solver)
    runtime_s = time.perf_counter() - t0
    summary = parse_cbc_log_file(path)
    if tmp is not None:
        path.unlink(missing_ok=True)

    status = pulp.LpStatus[prob.status]
    assignment = None
    if prob.sol_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible):
        assignment = {}
        for c in instance.components:
            chosen = [l for l in instance.allowed[c] if (x[(c, l)].varValue or 0.0) > 0.5]
            if len(chosen) != 1:
                raise RuntimeError(f"CBC returned {len(chosen)} locations for {c}")
            assignment[c] = chosen[0]
    objective = pulp.value(prob.objective) if assignment is not None else None
    result = Result(
        assignment=assignment, objective=objective, status=status,
        proven_optimal=summary.proven_optimal, best_bound=summary.best_bound, gap=summary.gap,
        runtime_s=runtime_s, cbc_wall_s=summary.wall_s, build_s=build_s,
        n_vars=prob.numVariables(), n_constraints=prob.numConstraints(),
        n_binaries=len(x), n_pairs=n_pairs, formulation=formulation,
        cbc_result=summary.result, nodes=summary.nodes,
        log_path=None if tmp is not None else str(path),
    )
    log.info("ILP %s | %s | n=%d L=%d | vars=%d cons=%d | %s (%s) | obj=%s bound=%s | %.3f s | log %s",
             instance.instance_id, formulation, instance.n_components, instance.n_locations,
             result.n_vars, result.n_constraints, status, summary.result or "no CBC result",
             f"{objective:.6f}" if objective is not None else "-",
             f"{summary.best_bound:.6f}" if summary.best_bound is not None else "-",
             runtime_s, result.log_path or "(temp, deleted)")
    return result
