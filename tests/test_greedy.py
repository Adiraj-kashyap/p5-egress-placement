"""M11: egress-aware greedy and greedy+1opt. Every cost is scored with `evaluate` (D-006)."""
import json
import math
import random

import pytest

from placement.cost import check_assignment, evaluate
from placement.greedy import (greedy, greedy_1opt, incident_edges, local_cost, one_opt,
                              traffic_order)
from placement.instance import Instance, load_instance
from pricing.common import ROOT
from tests.test_ilp import N_TINY, SNAPSHOT, TOPOLOGIES, brute_force, make_tiny


@pytest.fixture(scope="module")
def real():
    return [load_instance(t, SNAPSHOT, "core") for t in TOPOLOGIES]


def all_instances(real):
    return list(real) + [make_tiny(s) for s in range(N_TINY)]


def two_component_topology(gb: float, pin: str | None = None) -> dict:
    """Two small components a<->b with `gb` GB/month each way; `a` optionally pinned. Test input only."""
    return {
        "id": "two",
        "components": [
            {"id": "a", "vcpu": 2, "ram_gb": 8, "storage_gb": 0, "pinned_to": pin},
            {"id": "b", "vcpu": 2, "ram_gb": 8, "storage_gb": 0},
        ],
        "edges": [{"src": "a", "dst": "b", "gb_per_month": gb}, {"src": "b", "dst": "a", "gb_per_month": gb}],
        "internet_egress": [],
    }


def test_valid_assignments(real):
    for inst in all_instances(real):
        for a in (greedy(inst), greedy_1opt(inst)):
            check_assignment(inst, a)
            assert list(a) == list(inst.components)


def test_pins_respected(real):
    for inst in [make_tiny(s) for s in range(0, N_TINY, 4)]:  # these seeds pin the last component
        c = inst.components[-1]
        assert len(inst.allowed[c]) == 1
        for a in (greedy(inst), greedy_1opt(inst)):
            assert a[c] == inst.allowed[c][0]
    t1 = real[0]
    gcp = next(l for l in t1.locations if l.startswith("gcp:"))
    topo = json.loads((ROOT / TOPOLOGIES[0]).read_text(encoding="utf-8"))
    topo["components"][-1]["pinned_to"] = gcp
    inst = load_instance(topo, SNAPSHOT, "core")
    pinned = topo["components"][-1]["id"]
    for a in (greedy(inst), greedy_1opt(inst)):
        assert a[pinned] == gcp


@pytest.mark.parametrize("pin_provider", ["aws", "azure", "gcp"])
def test_huge_traffic_colocates(real, pin_provider):
    pin = next(l for l in real[0].locations if l.startswith(pin_provider + ":"))
    inst = load_instance(two_component_topology(1e7, pin), SNAPSHOT, "core")
    for a in (greedy(inst), greedy_1opt(inst)):
        assert a == {"a": pin, "b": pin}
    free = load_instance(two_component_topology(1e7), SNAPSHOT, "core")
    a = greedy(free)
    assert a["a"] == a["b"]
    assert evaluate(free, a).egress == 0.0


def test_1opt_never_worse_than_greedy(real):
    for inst in all_instances(real):
        g = evaluate(inst, greedy(inst)).total
        o = evaluate(inst, greedy_1opt(inst)).total
        assert o <= g + 1e-9 * max(1.0, g), inst.instance_id


def test_1opt_is_a_local_optimum(real):
    """No single relocation of the 1-opt result lowers evaluate() (checked by full re-scoring)."""
    for inst in all_instances(real):
        a = greedy_1opt(inst)
        base = evaluate(inst, a).total
        for c in inst.components:
            for loc in inst.allowed[c]:
                b = dict(a, **{c: loc})
                assert evaluate(inst, b).total >= base - 1e-9 * max(1.0, base), (inst.instance_id, c, loc)


def test_heuristics_not_below_exact_optimum():
    for s in range(N_TINY):
        inst = make_tiny(s)
        opt = brute_force(inst)
        for a in (greedy(inst), greedy_1opt(inst)):
            assert evaluate(inst, a).total >= opt - 1e-6


def test_local_cost_delta_equals_evaluate_delta(real):
    rng = random.Random(11)
    for inst in all_instances(real):
        inc = incident_edges(inst)
        a = {c: rng.choice(inst.allowed[c]) for c in inst.components}
        base = evaluate(inst, a).total
        for _ in range(30):
            c = rng.choice(inst.components)
            loc = rng.choice(inst.allowed[c])
            delta = local_cost(inst, inc, c, loc, a) - local_cost(inst, inc, c, a[c], a)
            assert math.isclose(evaluate(inst, dict(a, **{c: loc})).total - base, delta, abs_tol=1e-6)


def test_deterministic(real):
    for inst in all_instances(real):
        assert greedy(inst) == greedy(inst)
        assert greedy_1opt(inst) == greedy_1opt(inst)


def test_ties_go_to_smallest_location_id():
    locs = ("gcp:z", "aws:y", "azure:x")
    comps = ("c0", "c1")
    k = {(c, l): 100.0 for c in comps for l in locs}
    inst = Instance(
        instance_id="tie@test", topology_id="tie", snapshot_date="test", location_set="test",
        components=comps, locations=locs, shape={c: "small" for c in comps}, vcpu={c: 2 for c in comps},
        storage_gb={c: 0.0 for c in comps}, allowed={c: locs for c in comps}, usd_per_hour={},
        compute_month=k, storage_month={key: 0.0 for key in k}, k=k, edges=(("c0", "c1", 10.0),),
        internet_gb={}, r={l: 0.09 for l in locs},
        egress={(a, b): 0.0 if a == b else 0.02 for a in locs for b in locs},
    )
    assert greedy(inst) == {"c0": "aws:y", "c1": "aws:y"}


def test_traffic_order(real):
    t3 = real[2]
    order = traffic_order(t3)
    assert sorted(order) == sorted(t3.components)
    tot = {c: sum(gb for u, v, gb in t3.edges if c in (u, v)) for c in t3.components}
    assert [tot[c] for c in order] == sorted(tot.values(), reverse=True)


def test_one_opt_improves_a_bad_start(real):
    t3 = real[2]
    worst = {c: max(t3.allowed[c], key=lambda l: t3.k[(c, l)]) for c in t3.components}
    res = one_opt(t3, worst, max_passes=50)
    assert res.converged and res.moves > 0
    assert evaluate(t3, res.assignment).total < evaluate(t3, worst).total
    capped = one_opt(t3, worst, max_passes=1)
    assert capped.passes == 1
    assert evaluate(t3, capped.assignment).total <= evaluate(t3, worst).total


def test_run_heuristics_appends_rows(tmp_path):
    import csv
    from experiments import run_heuristics
    out = tmp_path / "heuristics"
    for _ in range(2):
        run_heuristics.main(["--repeats", "1", "--out", str(out)])
    with open(out / "runs.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 * len(TOPOLOGIES) * len(run_heuristics.METHODS)
    assert all(float(r["gap_vs_ilp_pct"]) >= -1e-6 for r in rows)
    assert all(r["ilp_proven_optimal"] == "True" for r in rows)
    assert json.loads((out / "config.json").read_text(encoding="utf-8"))["module"] == "M11"