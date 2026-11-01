"""Tests for experiments/generate.py (M13 step 5) and the provider-pin support it relies on (D-048, D-049)."""
from __future__ import annotations

import pytest

from experiments.generate import DEFAULTS, canonical_sha256, synthetic
from placement.baselines import b2_best, b2_single_provider
from placement.greedy import greedy
from placement.ilp import solve_ilp
from placement.instance import SHAPES, load_instance, provider_of
from topologies.validate import validate_topology

SNAPSHOT = "2026-09-21"
SIZES = (1, 2, 3, 7, 20, 50)


def undirected_components(doc: dict) -> int:
    """Number of weakly connected components of the topology's edge graph."""
    parent = {c["id"]: c["id"] for c in doc["components"]}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in doc["edges"]:
        parent[find(e["src"])] = find(e["dst"])
    return len({find(c) for c in parent})


@pytest.mark.parametrize("n", SIZES)
def test_deterministic(n):
    a, b = synthetic(n, "core", 7), synthetic(n, "core", 7)
    assert a == b
    assert canonical_sha256(a) == canonical_sha256(b)


def test_seed_changes_graph():
    assert canonical_sha256(synthetic(20, "core", 1)) != canonical_sha256(synthetic(20, "core", 2))


def test_location_set_does_not_change_graph():
    a, b = synthetic(15, "core", 3), synthetic(15, "ext", 3)
    for key in ("id", "components", "edges", "internet_egress"):
        assert a[key] == b[key]
    assert a["assumptions"]["location_set"] == "core" and b["assumptions"]["location_set"] == "ext"


@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_valid_connected_paired(n, seed):
    doc = synthetic(n, "core", seed)
    assert validate_topology(doc) == []
    assert doc["provenance"] == "synthetic" and doc["id"] == f"syn_n{n}_s{seed}"
    assert all(e["provenance"] == f"synthetic:seed={seed}" for e in doc["edges"] + doc["internet_egress"])
    assert undirected_components(doc) == 1
    directed = {(e["src"], e["dst"]) for e in doc["edges"]}
    assert len(directed) == len(doc["edges"])  # no duplicates
    assert all((v, u) in directed for u, v in directed)  # request/response pairs
    pairs = len(directed) // 2
    assert pairs == doc["assumptions"]["communicating_pairs"]
    assert pairs == (0 if n == 1 else max(n - 1, round(0.25 * n * (n - 1) / 2)))
    shapes = {(v, r) for _, v, r in SHAPES}
    assert all((c["vcpu"], c["ram_gb"]) in shapes for c in doc["components"])
    assert all(c["pinned_to"] is None for c in doc["components"])
    assert any(i["rationale"] == "entry component" for i in doc["internet_egress"])


def test_density_bounds():
    assert len(synthetic(10, "core", 1, density=1.0)["edges"]) == 10 * 9
    assert len(synthetic(10, "core", 1, density=0.0)["edges"]) == 2 * 9  # spanning tree floor


def test_volume_distributions():
    const = synthetic(10, "core", 1, volume_dist="constant", median_gb=50)
    assert {e["gb_per_month"] for e in const["edges"]} == {50.0}
    uni = synthetic(30, "core", 1, volume_dist="uniform", median_gb=100)
    assert all(0 <= e["gb_per_month"] <= 200 for e in uni["edges"])
    logn = synthetic(60, "core", 1, density=0.5, median_gb=200)
    vols = sorted(e["gb_per_month"] for e in logn["edges"])
    assert 120 < vols[len(vols) // 2] < 330  # sample median near 200 (sigma 1, ~1,770 draws)


def test_non_default_params_change_id():
    assert synthetic(5, "core", 1)["id"] == "syn_n5_s1"
    other = synthetic(5, "core", 1, density=0.5)["id"]
    assert other.startswith("syn_n5_s1_") and other != synthetic(5, "core", 1, median_gb=300)["id"]
    assert synthetic(5, "core", 1, **DEFAULTS)["id"] == "syn_n5_s1"


@pytest.mark.parametrize("bad", [dict(n=0), dict(location_set="mars"), dict(density=1.5),
                                 dict(volume_dist="pareto"), dict(median_gb=0), dict(pin_fraction=-0.1)])
def test_bad_arguments(bad):
    args = {"n": 5, "location_set": "core", "seed": 1, **bad}
    with pytest.raises(ValueError):
        synthetic(**args)


def test_provider_pins_load_and_solve():
    doc = synthetic(10, "core", 4, pin_fraction=0.3)
    pinned = {c["id"]: c["pinned_to"] for c in doc["components"] if c["pinned_to"]}
    assert len(pinned) == 3 and set(pinned.values()) <= {"aws", "gcp", "azure"}
    inst = load_instance(doc, SNAPSHOT, "core")
    for c, p in pinned.items():
        assert inst.allowed[c] and all(provider_of(l) == p for l in inst.allowed[c])
        assert set(inst.allowed[c]) == {l for l in inst.locations if provider_of(l) == p}
    res = solve_ilp(inst, 60)
    a = greedy(inst)
    for c, p in pinned.items():
        assert provider_of(res.assignment[c]) == p and provider_of(a[c]) == p


def test_b2_best_skips_infeasible_providers():
    doc = synthetic(4, "core", 1)
    doc["components"][0]["pinned_to"] = "gcp"
    inst = load_instance(doc, SNAPSHOT, "core")
    with pytest.raises(ValueError):
        b2_single_provider(inst, "aws")
    p, a, _ = b2_best(inst)
    assert p == "gcp" and all(provider_of(l) == "gcp" for l in a.values())
    doc["components"][1]["pinned_to"] = "aws"
    with pytest.raises(ValueError):
        b2_best(load_instance(doc, SNAPSHOT, "core"))


def test_unknown_pin_rejected():
    doc = synthetic(3, "core", 1)
    doc["components"][0]["pinned_to"] = "oracle"
    with pytest.raises(ValueError):
        load_instance(doc, SNAPSHOT, "core")
