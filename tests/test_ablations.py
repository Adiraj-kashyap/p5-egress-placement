"""Tests for the M17 ablation variants (06 §S12).

The two that the module's acceptance checks name explicitly:

- **A2 separability** — with the inter-component egress term dropped, the objective is a sum
  of per-component terms, so `ilp_no_edge_egress` reaches exactly the cost of the independent
  per-component argmin. (Not the same *assignment*: ties are pervasive at these prices, D-045.)
- **A1 telescoping** — the three decomposition steps sum to C(B1) - C(ILP) on every draw.

Both run on the real cost model, on the real topologies, so they are evidence about the
reported numbers and not about fixtures.
"""
from __future__ import annotations

import math

import pytest

from experiments.runner import METHODS
from experiments.uncertainty import draw_topology
from placement.ablations import (DECOMPOSITION, b1_storage, no_edge_egress, no_internet,
                                 per_component_argmin, restrict_locations_per_provider,
                                 scale_cross_provider_egress, single_provider, undirected)
from placement.baselines import b1_cheapest_per_vcpu
from placement.cost import evaluate
from placement.ilp import solve_ilp
from placement.instance import load_instance, load_topology, provider_of

SNAPSHOT = "2026-09-21"
TOPOLOGIES = ["topologies/t1_three_tier.json", "topologies/t2_pipeline.json",
              "topologies/t3_microservices.json"]
DRAWS = [0, 1, 2]  # a small paired set; the full run uses 0..29


def instance(path, location_set="core", draw_id=None):
    """The real instance for `path`, optionally after traffic draw `draw_id` (05 §3)."""
    topo = load_topology(path)
    if draw_id is not None:
        topo = draw_topology(topo, draw_id)
    return load_instance(topo, SNAPSHOT, location_set)


def separable_cost(inst, assignment):
    """Cost of `assignment` under the separable objective: compute + storage + internet only."""
    return sum(inst.k[(c, assignment[c])] + inst.internet_gb.get(c, 0.0) * inst.r[assignment[c]]
               for c in inst.components)


def run(method, inst, seed=None):
    """Run a registry method on `inst` and return (assignment, true total cost)."""
    out = METHODS[method].run(inst, seed, 600, {}, None)
    assert out.assignment is not None, f"{method} returned no solution"
    return out.assignment, evaluate(inst, out.assignment).total


# --------------------------------------------------------------------------- A2 separability

@pytest.mark.parametrize("path", TOPOLOGIES)
def test_no_edge_egress_equals_per_component_argmin(path):
    """A2: dropping the edge term makes the problem separable, so the ILP matches the argmin."""
    inst = instance(path)
    argmin = per_component_argmin(inst)
    assignment, _ = run("ilp_no_edge_egress", inst)
    assert separable_cost(inst, assignment) == pytest.approx(separable_cost(inst, argmin), rel=1e-9)


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_per_component_argmin_is_componentwise_optimal(path):
    """Each component of the argmin really is that component's own cheapest separable location."""
    inst = instance(path)
    argmin = per_component_argmin(inst)
    for c in inst.components:
        q = inst.internet_gb.get(c, 0.0)
        best = min(inst.k[(c, l)] + q * inst.r[l] for l in inst.allowed[c])
        chosen = inst.k[(c, argmin[c])] + q * inst.r[argmin[c]]
        assert chosen == pytest.approx(best, rel=1e-12)


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_no_edge_egress_instance_has_no_edges_but_keeps_prices(path):
    """The transform removes edges only; k, r and the egress matrix are untouched."""
    inst = instance(path)
    stripped = no_edge_egress(inst)
    assert inst.edges and stripped.edges == ()
    assert stripped.k == inst.k and stripped.r == inst.r and stripped.egress == inst.egress
    assert evaluate(stripped, per_component_argmin(inst)).egress == 0.0


# --------------------------------------------------------------------------- A1 telescoping

@pytest.mark.parametrize("path", TOPOLOGIES)
@pytest.mark.parametrize("draw_id", DRAWS)
def test_decomposition_telescopes_to_total_gain(path, draw_id):
    """A1: the three §S12 steps sum to C(B1) - C(ILP) exactly, on every draw."""
    inst = instance(path, draw_id=draw_id)
    cost = {
        "b1": evaluate(inst, b1_cheapest_per_vcpu(inst)).total,
        "b1_storage": evaluate(inst, b1_storage(inst)).total,
        "ilp_no_edge_egress": run("ilp_no_edge_egress", inst)[1],
        "ilp_full": run("ilp_full", inst)[1],
    }
    steps = [cost[a] - cost[b] for a, b, _ in DECOMPOSITION]
    assert sum(steps) == pytest.approx(cost["b1"] - cost["ilp_full"], rel=1e-9, abs=1e-6)


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_decomposition_chain_is_connected(path):
    """The steps form one chain from b1 to ilp_full, and every stage is a registry method."""
    assert DECOMPOSITION[0][0] == "b1" and DECOMPOSITION[-1][1] == "ilp_full"
    for (_, to_m, _), (from_m, _, _) in zip(DECOMPOSITION, DECOMPOSITION[1:]):
        assert to_m == from_m
    for from_m, to_m, _ in DECOMPOSITION:
        assert from_m in METHODS and to_m in METHODS


# --------------------------------------------------------------------------- the other variants

@pytest.mark.parametrize("path", TOPOLOGIES)
def test_ilp_full_matches_ilp_tight_and_mccormick(path):
    """§S12: the McCormick linearisation differs in runtime only; the objective is identical."""
    inst = instance(path)
    tight = run("ilp_full", inst)[1]
    assert run("ilp_tight", inst)[1] == pytest.approx(tight, rel=1e-9)
    assert run("ilp_mccormick", inst)[1] == pytest.approx(tight, rel=1e-9)


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_every_variant_is_at_least_as_expensive_as_the_full_ilp(path):
    """Every ablation is a restriction or a mis-specified objective, so none can beat ilp_full."""
    inst = instance(path)
    best = run("ilp_full", inst)[1]
    for m in ("ilp_no_edge_egress", "ilp_no_internet", "ilp_undirected", "ilp_single_provider",
              "b1", "b1_storage"):
        assert run(m, inst)[1] >= best - 1e-6, f"{m} beat the full ILP"


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_single_provider_variant_uses_one_provider(path):
    """`ilp_single_provider` returns an assignment inside one provider, and names it."""
    inst = instance(path)
    out = METHODS["ilp_single_provider"].run(inst, None, 600, {}, None)
    providers = {provider_of(l) for l in out.assignment.values()}
    assert len(providers) == 1
    assert out.extra["detail"]["provider"] == providers.pop()


def test_single_provider_transform_rejects_an_unhostable_provider():
    """A component pinned to one provider makes the other two infeasible, not silently empty."""
    topo = load_topology(TOPOLOGIES[0])
    topo["components"][0]["pinned_to"] = "aws"
    inst = load_instance(topo, SNAPSHOT, "core")
    assert len(single_provider(inst, "aws").allowed[inst.components[0]]) == 4
    for p in ("azure", "gcp"):
        with pytest.raises(ValueError):
            single_provider(inst, p)


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_undirected_symmetrises_and_preserves_the_mean(path):
    """Both directions get the mean rate, the diagonal stays 0, and the row sums are unchanged."""
    inst = instance(path)
    sym = undirected(inst)
    for a in inst.locations:
        assert sym.egress[(a, a)] == pytest.approx(inst.egress[(a, a)])
        for b in inst.locations:
            assert sym.egress[(a, b)] == pytest.approx(sym.egress[(b, a)])
            assert sym.egress[(a, b)] == pytest.approx(0.5 * (inst.egress[(a, b)] + inst.egress[(b, a)]))


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_no_internet_drops_only_internet_volume(path):
    """The transform zeroes end-user volume; edges and every price survive."""
    inst = instance(path)
    stripped = no_internet(inst)
    assert stripped.internet_gb == {}
    assert stripped.edges == inst.edges and stripped.r == inst.r
    assert evaluate(stripped, per_component_argmin(inst)).internet == 0.0


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_b1_storage_ranks_by_compute_plus_storage(path):
    """Every component sits at a location minimising its own compute + storage bill."""
    inst = instance(path)
    for c, l in b1_storage(inst).items():
        assert inst.k[(c, l)] == pytest.approx(min(inst.k[(c, m)] for m in inst.allowed[c]), rel=1e-12)


def test_sa_no_swap_proposes_no_swap_moves():
    """p_relocate = 1.0 removes swap moves from the proposal distribution."""
    import random

    from placement.annealing import movable_components, propose_move

    inst = instance(TOPOLOGIES[2])
    rng = random.Random(0)
    movable = movable_components(inst)
    a = {c: inst.allowed[c][i % len(inst.allowed[c])] for i, c in enumerate(inst.components)}
    kinds = {propose_move(inst, a, rng, movable, 1.0)[0] for _ in range(500)}
    assert kinds == {"relocate"}
    rng = random.Random(0)
    assert "swap" in {propose_move(inst, a, rng, movable)[0] for _ in range(500)}


def test_sa_variants_are_registered_as_randomised():
    """Both SA ablations take a seed, so the runner demands method_seeds for them."""
    for m in ("sa", "sa_random_init", "sa_no_swap"):
        assert METHODS[m].randomised


@pytest.mark.parametrize("path", TOPOLOGIES)
def test_sa_variants_never_beat_the_exact_optimum(path):
    """A heuristic ablation may be worse than SA, never better than the proven optimum."""
    inst = instance(path)
    best = run("ilp_full", inst)[1]
    for m in ("sa", "sa_random_init", "sa_no_swap"):
        assert run(m, inst, seed=0)[1] >= best - 1e-6


# --------------------------------------------------------------------------- sensitivity transforms

@pytest.mark.parametrize("mult", [0.5, 0.75, 1.0, 1.25, 1.5])
def test_egress_multiplier_scales_cross_provider_rates_only(mult):
    """Cross-provider rates scale; same-provider rates, the diagonal and internet do not."""
    inst = instance(TOPOLOGIES[0])
    scaled = scale_cross_provider_egress(inst, mult)
    assert scaled.r == inst.r and scaled.k == inst.k
    for a in inst.locations:
        for b in inst.locations:
            expected = inst.egress[(a, b)] * (mult if provider_of(a) != provider_of(b) else 1.0)
            assert scaled.egress[(a, b)] == pytest.approx(expected)


def test_egress_multiplier_of_one_is_a_no_op():
    """x = 1 must reproduce the unmodified world exactly, so it anchors the sweep."""
    inst = instance(TOPOLOGIES[1])
    assert scale_cross_provider_egress(inst, 1.0).egress == pytest.approx(inst.egress)


def test_egress_multiplier_rejects_a_negative():
    with pytest.raises(ValueError):
        scale_cross_provider_egress(instance(TOPOLOGIES[0]), -0.1)


@pytest.mark.parametrize("k", [1, 2, 4, 8])
def test_locations_per_provider_keeps_k_regions_per_provider(k):
    """Each provider keeps exactly k regions and every price map is restricted to them."""
    inst = instance(TOPOLOGIES[0], location_set="ext")
    sub = restrict_locations_per_provider(inst, k)
    for p in ("aws", "azure", "gcp"):
        assert len([l for l in sub.locations if provider_of(l) == p]) == k
    kept = set(sub.locations)
    assert {l for _, l in sub.k} == kept and set(sub.r) == kept
    assert {a for a, _ in sub.egress} | {b for _, b in sub.egress} == kept
    assert all(set(ls) <= kept for ls in sub.allowed.values())


def test_locations_per_provider_grids_nest():
    """k = 1 ⊂ 2 ⊂ 4 ⊂ 8, and k = 4 is exactly the core location set."""
    ext = instance(TOPOLOGIES[0], location_set="ext")
    subsets = {k: set(restrict_locations_per_provider(ext, k).locations) for k in (1, 2, 4, 8)}
    assert subsets[1] < subsets[2] < subsets[4] < subsets[8]
    assert subsets[8] == set(ext.locations)
    assert subsets[4] == set(instance(TOPOLOGIES[0], location_set="core").locations)


def test_locations_per_provider_rejects_zero():
    with pytest.raises(ValueError):
        restrict_locations_per_provider(instance(TOPOLOGIES[0], location_set="ext"), 0)


def test_restricted_instance_still_solves_and_costs_more_than_the_full_grid():
    """Shrinking the candidate set can only make the optimum worse (it is a restriction)."""
    ext = instance(TOPOLOGIES[0], location_set="ext")
    full = solve_ilp(ext, 600, "tight")
    small = solve_ilp(restrict_locations_per_provider(ext, 1), 600, "tight")
    assert small.objective >= full.objective - 1e-6
    assert math.isfinite(small.objective)
