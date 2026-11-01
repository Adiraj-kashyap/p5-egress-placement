"""M12: simulated annealing. Deltas are checked against `evaluate` (D-006); results must be seeded."""
import json
import math
import random

import pytest

from placement.annealing import (anneal, apply_move, calibrate_t0, move_delta, movable_components,
                                 propose_move)
from placement.cost import check_assignment, evaluate
from placement.greedy import greedy, incident_edges
from placement.instance import load_instance
from pricing.common import ROOT
from tests.test_ilp import N_TINY, SNAPSHOT, TOPOLOGIES, brute_force, make_tiny

N_DELTA_MOVES = 1000


@pytest.fixture(scope="module")
def real():
    return [load_instance(t, SNAPSHOT, "core") for t in TOPOLOGIES]


def test_delta_matches_evaluate_on_1000_moves(real):
    """A1: 1,000 random moves (relocations and swaps, applied as a random walk) on T1-T3 and tiny
    instances; every incremental delta equals the change in `evaluate`."""
    rng = random.Random(12)
    instances = list(real) + [make_tiny(s) for s in range(N_TINY)]
    kinds = {"relocate": 0, "swap": 0}
    for i in range(N_DELTA_MOVES):
        inst = instances[i % len(instances)]
        inc = incident_edges(inst)
        a = {c: rng.choice(inst.allowed[c]) for c in inst.components}
        movable = movable_components(inst)
        move = propose_move(inst, a, rng, movable)
        if move is None:
            continue
        before = evaluate(inst, a).total
        snapshot = dict(a)
        d = move_delta(inst, inc, a, move)
        assert a == snapshot, "move_delta must not change the assignment"
        apply_move(a, move)
        check_assignment(inst, a)
        assert d == pytest.approx(evaluate(inst, a).total - before, rel=1e-9, abs=1e-7)
        kinds[move[0]] += 1
    assert sum(kinds.values()) == N_DELTA_MOVES
    assert kinds["swap"] >= 100 and kinds["relocate"] >= 600


def test_swap_delta_shared_edge():
    """A swap of two components joined by an edge prices that edge at the new endpoints."""
    inst = next(make_tiny(s) for s in range(N_TINY)
                if any(u != v for u, v, _ in make_tiny(s).edges) and len(make_tiny(s).locations) >= 2
                and not any(len(make_tiny(s).allowed[c]) == 1 for c in make_tiny(s).components))
    inc = incident_edges(inst)
    u, v, _ = next(e for e in inst.edges if e[0] != e[1])
    l0, l1 = inst.locations[0], inst.locations[1]
    a = {c: l0 for c in inst.components}
    a[u], a[v] = l0, l1
    before = evaluate(inst, a).total
    d = move_delta(inst, inc, a, ("swap", u, v))
    apply_move(a, ("swap", u, v))
    assert (a[u], a[v]) == (l1, l0)
    assert d == pytest.approx(evaluate(inst, a).total - before, rel=1e-9, abs=1e-7)


def test_same_seed_identical(real):
    """A3: same seed -> identical assignment, cost, counters and trace."""
    for inst in [real[0], real[2], make_tiny(3)]:
        r1, r2 = anneal(inst, seed=7), anneal(inst, seed=7)
        assert r1.assignment == r2.assignment
        assert r1.total == r2.total and r1.t0 == r2.t0
        assert (r1.temp_steps, r1.moves_tried, r1.moves_accepted) == (r2.temp_steps, r2.moves_tried,
                                                                      r2.moves_accepted)
        assert r1.trace == r2.trace


def test_different_seeds_explore_differently(real):
    traces = {anneal(real[2], seed=s).trace for s in range(3)}
    assert len(traces) == 3


def test_never_worse_than_start(real):
    for inst in list(real) + [make_tiny(s) for s in range(N_TINY)]:
        for init in ("greedy", "random"):
            r = anneal(inst, seed=1, init=init)
            check_assignment(inst, r.assignment)
            assert r.total <= r.initial_total + 1e-9
            assert r.total == pytest.approx(evaluate(inst, r.assignment).total, rel=1e-12)
        start = greedy(inst)
        assert anneal(inst, seed=1).initial_total == pytest.approx(evaluate(inst, start).total)


def test_pins_respected(real):
    for inst in [make_tiny(s) for s in range(0, N_TINY, 4)]:  # these seeds pin the last component
        c = inst.components[-1]
        assert len(inst.allowed[c]) == 1 and c not in movable_components(inst)
        for init in ("greedy", "random"):
            assert anneal(inst, seed=2, init=init).assignment[c] == inst.allowed[c][0]
    topo = json.loads((ROOT / TOPOLOGIES[0]).read_text(encoding="utf-8"))
    gcp = next(l for l in real[0].locations if l.startswith("gcp:"))
    topo["components"][-1]["pinned_to"] = gcp
    inst = load_instance(topo, SNAPSHOT, "core")
    for seed in range(3):
        assert anneal(inst, seed=seed, init="random").assignment[topo["components"][-1]["id"]] == gcp


def test_all_pinned_returns_start():
    inst = make_tiny(0)
    pinned = {c: (inst.locations[0],) for c in inst.components}
    object.__setattr__(inst, "allowed", pinned)
    r = anneal(inst, seed=0)
    assert r.stop_reason == "no_movable_component" and r.moves_tried == 0
    assert all(l == inst.locations[0] for l in r.assignment.values())


def test_reaches_brute_force_optimum_on_tiny():
    """SA from a random start finds the exhaustive optimum on the tiny instances (best of 3 seeds)."""
    for s in range(N_TINY):
        inst = make_tiny(s)
        best = min(anneal(inst, seed=k, init="random").total for k in range(3))
        assert best == pytest.approx(brute_force(inst), rel=1e-9)


def test_calibrate_t0_hits_target():
    ds = [1.0, 5.0, 20.0, 80.0]
    t0 = calibrate_t0(ds, 0.8)
    assert sum(math.exp(-d / t0) for d in ds) / len(ds) == pytest.approx(0.8, abs=1e-6)
    assert calibrate_t0([]) == 0.0


def test_cooling_and_trace(real):
    r = anneal(real[1], seed=4, alpha=0.9)
    assert r.moves_per_temp == real[1].n_components * real[1].n_locations
    assert r.trace[0].temperature == r.t0 and r.trace[0].moves == 0
    assert len(r.trace) == r.temp_steps + 1
    for p, q in zip(r.trace, r.trace[1:]):
        assert q.temperature == pytest.approx(p.temperature * 0.9)
        assert q.best <= p.best + 1e-9
    assert r.stop_reason in {"t_min", "stale"}


def test_time_limit_stops():
    inst = make_tiny(5)
    r = anneal(inst, seed=0, alpha=0.99999, max_stale=10**9, time_limit=0.05)
    assert r.stop_reason == "time_limit"


def test_literal_stale_rule_stops_hot(real):
    """D-046: with stale_rule='best' SA stops after max_stale steps while T is still ~0.9 T0."""
    r = anneal(real[2], seed=0, stale_rule="best")
    assert r.stop_reason == "stale" and r.temp_steps == 20
    assert r.trace[-1].temperature / r.t0 > 0.9
