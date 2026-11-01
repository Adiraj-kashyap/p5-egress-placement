"""Simulated annealing over location assignments (03_SKILLS §S7).

State = a full assignment. A move relocates one random component to a random other allowed
location (probability `P_RELOCATE`) or swaps the locations of two components (the rest). The
cost change of a move is computed incrementally from the moved components' incident edges
(`placement.greedy.local_cost`, O(degree)); a swap is two sequential relocations, so the edge
between the two swapped components is priced exactly once at its new endpoints.

T0 is calibrated so about 80% of uphill moves in a 200-move probe from the start state would be
accepted. Cooling is geometric (T <- alpha * T) every `moves_per_temp` moves (default n * |L|).
The run stops when T < 1e-4 * T0, after `max_stale` consecutive stale temperature steps, or at
`time_limit`. Stale rule: see `anneal` and D-046.

The returned assignment is the best one visited, never worse than the start. Its cost is taken
from `placement.cost.evaluate` (D-006); the incremental running cost is only used for acceptance.
Every random choice comes from `random.Random(seed)`, so a fixed seed gives an identical result
(unless `time_limit` cuts the run).
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Literal, Mapping

from placement.cost import check_assignment, evaluate
from placement.greedy import TIE_REL_TOL, greedy, incident_edges, local_cost
from placement.instance import Instance

P_RELOCATE = 0.8
PROBE_MOVES = 200
TARGET_ACCEPT = 0.8
T_MIN_RATIO = 1e-4

# A move: ("relocate", c, new_loc) or ("swap", c1, c2).
Move = tuple


@dataclass(frozen=True)
class TracePoint:
    """State at the end of one temperature step (the convergence trace)."""

    temp_step: int
    moves: int
    temperature: float
    current: float
    best: float


@dataclass(frozen=True)
class AnnealResult:
    """Outcome of `anneal`. `total` and `initial_total` come from `evaluate`."""

    assignment: dict[str, str]
    total: float
    initial_total: float
    seed: int
    init: str
    alpha: float
    t0: float
    moves_per_temp: int
    max_stale: int
    stale_rule: str
    temp_steps: int
    moves_tried: int
    moves_accepted: int
    uphill_accepted: int
    stop_reason: str
    runtime_s: float
    trace: tuple[TracePoint, ...]


Result = AnnealResult  # name used by the M12 module spec


def movable_components(instance: Instance) -> list[str]:
    """Components with more than one allowed location, in topology order (pins never move)."""
    return [c for c in instance.components if len(instance.allowed[c]) > 1]


def propose_move(instance: Instance, assignment: Mapping[str, str], rng: random.Random,
                 movable: list[str], p_relocate: float = P_RELOCATE) -> Move | None:
    """Draw one random move from `rng`; None if no component can move.

    With probability `p_relocate`, or when no valid swap is drawn, relocate a random movable
    component to a random other allowed location. Otherwise swap two random movable components
    that sit at different locations, each allowed at the other's location.
    `p_relocate=1.0` disables swap moves entirely (M17's `sa_no_swap` ablation, D-071); the
    default reproduces M12 exactly.
    """
    if not movable:
        return None
    if len(movable) >= 2 and rng.random() >= p_relocate:
        c1, c2 = rng.sample(movable, 2)
        l1, l2 = assignment[c1], assignment[c2]
        if l1 != l2 and l2 in instance.allowed[c1] and l1 in instance.allowed[c2]:
            return ("swap", c1, c2)
    c = rng.choice(movable)
    options = [l for l in instance.allowed[c] if l != assignment[c]]
    return ("relocate", c, rng.choice(options))


def apply_move(assignment: dict[str, str], move: Move) -> None:
    """Apply `move` to `assignment` in place. Applying a swap twice restores the state."""
    if move[0] == "relocate":
        assignment[move[1]] = move[2]
    else:
        _, c1, c2 = move
        assignment[c1], assignment[c2] = assignment[c2], assignment[c1]


def move_delta(instance: Instance, inc: Mapping[str, list[tuple[str, str, float]]],
               assignment: dict[str, str], move: Move) -> float:
    """Exact change in total cost if `move` were applied to the full `assignment`. O(degree).

    A relocation is `local_cost(new) - local_cost(old)`. A swap is done as two relocations in
    sequence (c1 moves first, then c2 is priced against c1's new location), so the edge shared
    by c1 and c2 is counted correctly. `assignment` is restored before returning.
    """
    if move[0] == "relocate":
        _, c, new = move
        return (local_cost(instance, inc, c, new, assignment)
                - local_cost(instance, inc, c, assignment[c], assignment))
    _, c1, c2 = move
    l1, l2 = assignment[c1], assignment[c2]
    d1 = local_cost(instance, inc, c1, l2, assignment) - local_cost(instance, inc, c1, l1, assignment)
    assignment[c1] = l2
    try:
        d2 = local_cost(instance, inc, c2, l1, assignment) - local_cost(instance, inc, c2, l2, assignment)
    finally:
        assignment[c1] = l1
    return d1 + d2


def calibrate_t0(uphill: list[float], target: float = TARGET_ACCEPT) -> float:
    """Temperature at which the mean of exp(-d/T) over the uphill deltas equals `target`.

    Solved by bisection on log T (the mean is increasing in T). With no uphill deltas the
    landscape gave nothing to calibrate on; the caller then uses a tiny fallback T0.
    """
    if not uphill:
        return 0.0
    def acc(t: float) -> float:
        return sum(math.exp(-d / t) for d in uphill) / len(uphill)
    lo, hi = min(uphill) * 1e-3, max(uphill) * 1e3
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if acc(mid) < target:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1 + 1e-9:
            break
    return hi


def _initial(instance: Instance, init: str | Mapping[str, str], rng: random.Random) -> tuple[dict[str, str], str]:
    if isinstance(init, Mapping):
        a = {c: init[c] for c in instance.components}
        check_assignment(instance, a)
        return a, "given"
    if init == "greedy":
        return greedy(instance), "greedy"
    if init == "random":
        return {c: rng.choice(instance.allowed[c]) for c in instance.components}, "random"
    raise ValueError(f"unknown init {init!r}")


def anneal(instance: Instance, seed: int, init: str | Mapping[str, str] = "greedy", alpha: float = 0.995,
           moves_per_temp: int | None = None, max_stale: int = 20, time_limit: float | None = None,
           stale_rule: Literal["descent", "best"] = "descent",
           p_relocate: float = P_RELOCATE) -> AnnealResult:
    """Simulated annealing from `init` ("greedy", "random" or an assignment); returns the best state.

    `moves_per_temp` defaults to n * |L| (03_SKILLS §S7). A temperature step is *stale* under
    `stale_rule="descent"` (default, D-046) when the best cost did not improve and no strictly
    downhill move was accepted during the step, i.e. the search is frozen in a local minimum.
    `stale_rule="best"` is the literal reading (best did not improve), kept for the D-046
    comparison. Improvements smaller than `TIE_REL_TOL` relative are treated as ties. The trace
    holds one point per temperature step (step 0 = the start state at T0).
    `p_relocate` is the probability of a relocation rather than a swap; 1.0 turns swaps off
    for M17's `sa_no_swap` ablation (D-071). The default is M12's behaviour unchanged.
    """
    t_start = time.perf_counter()
    rng = random.Random(seed)
    inc = incident_edges(instance)
    movable = movable_components(instance)
    a, init_name = _initial(instance, init, rng)
    start_a = dict(a)
    initial_total = evaluate(instance, a).total
    mpt = moves_per_temp or instance.n_components * instance.n_locations
    tol = TIE_REL_TOL * max(1.0, abs(initial_total))

    uphill = []
    for _ in range(PROBE_MOVES if movable else 0):
        d = move_delta(instance, inc, a, propose_move(instance, a, rng, movable, p_relocate))
        if d > tol:
            uphill.append(d)
    t0 = calibrate_t0(uphill) or tol  # no uphill move seen: freeze almost at once
    t_min = T_MIN_RATIO * t0

    current = best = initial_total
    best_a = dict(a)
    temp = t0
    trace = [TracePoint(0, 0, t0, current, best)]
    steps = tried = accepted = uphill_acc = stale = 0
    stop = "no_movable_component" if not movable else ""
    while not stop:
        improved_best = descended = False
        for _ in range(mpt):
            move = propose_move(instance, a, rng, movable, p_relocate)
            d = move_delta(instance, inc, a, move)
            tried += 1
            if d <= 0.0 or rng.random() < math.exp(-d / temp):
                apply_move(a, move)
                current += d
                accepted += 1
                if d > tol:
                    uphill_acc += 1
                elif d < -tol:
                    descended = True
                if current < best - tol:
                    best, best_a, improved_best = current, dict(a), True
        steps += 1
        temp *= alpha
        trace.append(TracePoint(steps, tried, temp, current, best))
        stale = 0 if improved_best or (stale_rule == "descent" and descended) else stale + 1
        if temp < t_min:
            stop = "t_min"
        elif stale >= max_stale:
            stop = "stale"
        elif time_limit is not None and time.perf_counter() - t_start > time_limit:
            stop = "time_limit"

    check_assignment(instance, best_a)
    total = evaluate(instance, best_a).total
    if total > initial_total:  # float drift in the running sum; never return worse than the start
        best_a, total = start_a, initial_total
    return AnnealResult(
        assignment={c: best_a[c] for c in instance.components}, total=total, initial_total=initial_total,
        seed=seed, init=init_name, alpha=alpha, t0=t0, moves_per_temp=mpt, max_stale=max_stale,
        stale_rule=stale_rule, temp_steps=steps, moves_tried=tried, moves_accepted=accepted,
        uphill_accepted=uphill_acc, stop_reason=stop, runtime_s=time.perf_counter() - t_start,
        trace=tuple(trace),
    )
