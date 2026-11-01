"""Egress-aware greedy placement and its 1-opt local search (03_SKILLS §S7).

`greedy` places components one at a time, heaviest-traffic first, each at the location that
minimises its own monthly cost plus the transfer cost to and from the components already
placed. `greedy_1opt` then keeps relocating single components while a move lowers the total.

Both return an assignment only; the cost is always taken from `placement.cost.evaluate`
(D-006). The per-component `local_cost` is a partial cost used to *compare* candidate
locations; it is never reported.

Ties (D-044): two candidate costs within `TIE_REL_TOL` of each other count as equal, and the
lexicographically smallest location id wins. Component order ties keep topology order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from placement.cost import check_assignment
from placement.instance import Instance

TIE_REL_TOL = 1e-9  # relative; D-039 shows aws/azure compute prices tie exactly


@dataclass(frozen=True)
class LocalSearchResult:
    """Outcome of `one_opt`: the final assignment, completed passes and applied moves."""

    assignment: dict[str, str]
    passes: int
    moves: int
    converged: bool


def incident_edges(instance: Instance) -> dict[str, list[tuple[str, str, float]]]:
    """Map each component to the directed edges (src, dst, gb) that touch it.

    A self-loop appears once in its component's list. Used for O(degree) cost deltas.
    """
    inc: dict[str, list[tuple[str, str, float]]] = {c: [] for c in instance.components}
    for u, v, gb in instance.edges:
        inc[u].append((u, v, gb))
        if v != u:
            inc[v].append((u, v, gb))
    return inc


def traffic_order(instance: Instance) -> list[str]:
    """Components sorted by total incident inter-component traffic (GB/month), descending.

    Internet traffic is not counted: it does not couple components. Equal totals keep the
    topology order (stable sort), so the order is deterministic.
    """
    total = {c: 0.0 for c in instance.components}
    for u, v, gb in instance.edges:
        total[u] += gb
        if v != u:
            total[v] += gb
    return sorted(instance.components, key=lambda c: -total[c])


def local_cost(instance: Instance, inc: Mapping[str, list[tuple[str, str, float]]], c: str, loc: str,
               assignment: Mapping[str, str]) -> float:
    """Cost terms of component `c` placed at `loc`, given the (possibly partial) `assignment`.

    Sums c's compute + storage, its internet egress, and the transfer on every edge between c
    and a component present in `assignment` (sender pays). Edges to unplaced components are
    skipped. Every term of `evaluate` that depends on c's location is included, so for a full
    assignment `local_cost(c, l1) - local_cost(c, l0)` is exactly the change in total cost of
    moving c from l0 to l1.
    """
    cost = instance.k[(c, loc)] + instance.internet_gb.get(c, 0.0) * instance.r[loc]
    for u, v, gb in inc[c]:
        if u == v:
            cost += gb * instance.egress[(loc, loc)]
        elif u == c:
            if v in assignment:
                cost += gb * instance.egress[(loc, assignment[v])]
        elif u in assignment:
            cost += gb * instance.egress[(assignment[u], loc)]
    return cost


def _best_location(instance: Instance, inc: Mapping[str, list[tuple[str, str, float]]], c: str,
                   assignment: Mapping[str, str]) -> tuple[str, float]:
    """Cheapest allowed location for c by `local_cost`; near-ties go to the smallest location id."""
    costs = {loc: local_cost(instance, inc, c, loc, assignment) for loc in instance.allowed[c]}
    best = min(costs.values())
    tol = TIE_REL_TOL * max(1.0, abs(best))
    loc = min(l for l, v in costs.items() if v <= best + tol)
    return loc, costs[loc]


def greedy(instance: Instance) -> dict[str, str]:
    """Egress-aware greedy assignment (03_SKILLS §S7).

    Visits components in `traffic_order` and puts each at the allowed location minimising its
    compute + storage + internet cost plus transfer to and from already-placed neighbours.
    Pinned components can only go to their pin. Deterministic: no randomness, ties broken by
    location id (D-044). Runs in O(n · |L| · degree).
    """
    inc = incident_edges(instance)
    assignment: dict[str, str] = {}
    for c in traffic_order(instance):
        assignment[c], _ = _best_location(instance, inc, c, assignment)
    out = {c: assignment[c] for c in instance.components}
    check_assignment(instance, out)
    return out


def one_opt(instance: Instance, start: Mapping[str, str], max_passes: int = 50) -> LocalSearchResult:
    """Single-component relocation local search from `start`.

    Each pass visits components in `traffic_order`; for each, it moves the component to its
    best allowed location (by exact incremental delta) if that lowers the total by more than
    `TIE_REL_TOL` relative to the component's current local cost. Stops after a pass with no
    move (`converged=True`) or after `max_passes` passes. Never raises the total cost.
    """
    check_assignment(instance, start)
    inc = incident_edges(instance)
    order = traffic_order(instance)
    a = dict(start)
    passes = moves = 0
    converged = False
    while passes < max_passes:
        passes += 1
        moved = False
        for c in order:
            current = local_cost(instance, inc, c, a[c], a)
            loc, cost = _best_location(instance, inc, c, a)
            if loc != a[c] and cost < current - TIE_REL_TOL * max(1.0, abs(current)):
                a[c] = loc
                moves += 1
                moved = True
        if not moved:
            converged = True
            break
    out = {c: a[c] for c in instance.components}
    return LocalSearchResult(assignment=out, passes=passes, moves=moves, converged=converged)


def greedy_1opt(instance: Instance, max_passes: int = 50) -> dict[str, str]:
    """`greedy` followed by `one_opt` (the §S7 `greedy+1opt` variant); returns the assignment."""
    return one_opt(instance, greedy(instance), max_passes).assignment
