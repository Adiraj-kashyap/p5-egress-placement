"""M20 acceptance tests for the live demo.

Covers: the app module imports without launching a server (A2's precondition), the solver
wrappers return results for T1-T3 quickly (A3), the testbed wrappers degrade to a message
instead of raising when the cluster is unreachable (A4), and the offline preflight exits 0
(A1). Nothing here needs Docker, a cluster or the network.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from demo import build_cache, core, preflight, testbed
from placement.cost import evaluate

FAST_METHODS = ("ilp_tight", "greedy_1opt", "b1", "b2_best")


# --------------------------------------------------------------------------- cache

def test_cache_matches_figures():
    """demo/cache/ is a byte-for-byte copy of the M18 figure CSVs it claims to copy."""
    assert build_cache.build(check=True) == 0


def test_cache_manifest_lists_every_file():
    manifest = core.cache_manifest()
    assert set(manifest["files"]) == set(core.CACHE_FILES)
    for name, entry in manifest["files"].items():
        assert entry["rows"] > 0, name
        assert len(entry["sha256"]) == 64, name


def test_cached_curves_carry_confidence_intervals():
    """Non-negotiable 8: no single-run value is plotted - every cached row has n and a CI."""
    for name in core.CACHE_FILES:
        rows = core.load_cache_csv(name)
        assert rows, name
        for row in rows:
            assert int(row["n"]) >= 3, f"{name}: n = {row['n']}"
            assert float(row["ci_lo"]) <= float(row["mean"]) <= float(row["ci_hi"]), name


# --------------------------------------------------------------------------- solving

@pytest.mark.parametrize("label", list(core.TOPOLOGIES))
def test_run_methods_on_each_topology(label):
    inst = core.build_instance(core.TOPOLOGIES[label], "core")
    out = core.run_methods(inst, FAST_METHODS)
    assert len(out.results) == len(FAST_METHODS)
    for r in out.results:
        assert not r.note.startswith("FAILED"), f"{label} {r.method}: {r.note}"
        assert set(r.assignment) == set(inst.components)
        # the demo may never invent a cost: it must equal `evaluate` on the assignment
        assert r.cost.total == pytest.approx(evaluate(inst, r.assignment).total)
    ilp = next(r for r in out.results if r.method == "ilp_tight")
    assert ilp.proven_optimal
    for r in out.results:
        assert r.total >= ilp.total - 1e-6, f"{r.method} beat the proven optimum"


def test_run_methods_for_all_three_topologies_under_ten_seconds():
    """M20 step 5: T1-T3 together in < 10 s, so the demo never stalls on stage."""
    t0 = time.perf_counter()
    for path in core.TOPOLOGIES.values():
        core.run_methods(core.build_instance(path, "core"), FAST_METHODS)
    assert time.perf_counter() - t0 < 10.0


def test_t3_ilp_within_the_demo_budget():
    """A3: the T3 ILP solve stays inside the 5 s budget preflight enforces."""
    inst = core.build_instance(core.TOPOLOGIES["T3 microservices"], "core")
    t0 = time.perf_counter()
    out = core.run_methods(inst, ("ilp_tight",))
    assert time.perf_counter() - t0 < preflight.T3_ILP_BUDGET_S
    assert out.results[0].total == pytest.approx(1789.88, rel=1e-4)  # M10 optimum


def test_traffic_scale_scales_edges_only():
    """s multiplies inter-component volumes; internet egress is unchanged (as in M15)."""
    base = core.build_instance(core.TOPOLOGIES["T2 pipeline"], "core", 1.0)
    scaled = core.build_instance(core.TOPOLOGIES["T2 pipeline"], "core", 10.0)
    assert sum(gb for _, _, gb in scaled.edges) == pytest.approx(
        10 * sum(gb for _, _, gb in base.edges))
    assert scaled.internet_gb == base.internet_gb


def test_synthetic_instance_is_solvable():
    out = core.run_methods(core.synthetic_instance(8, "core", seed=1), ("greedy_1opt", "b1"))
    assert all(r.total > 0 for r in out.results)


def test_unknown_method_is_reported_not_raised():
    inst = core.build_instance(core.TOPOLOGIES["T1 three-tier (measured)"], "core")
    out = core.run_methods(inst, ("b1", "not_a_method"))
    assert out.results[1].note.startswith("FAILED")
    assert out.best.method == "b1"


def test_cost_and_placement_rows_are_complete():
    inst = core.build_instance(core.TOPOLOGIES["T1 three-tier (measured)"], "core")
    out = core.run_methods(inst, ("ilp_tight", "b1"))
    prows = core.placement_rows(inst, out.results)
    assert len(prows) == inst.n_components
    crows = core.cost_rows(out)
    assert {r["method"] for r in crows} == {r.label for r in out.results}
    assert min(r["penalty_vs_best_pct"] for r in crows) == pytest.approx(0.0)


def test_provider_colour_is_defined_for_every_location():
    inst = core.build_instance(core.TOPOLOGIES["T1 three-tier (measured)"], "ext")
    assert all(core.provider_colour(loc) != "#888888" for loc in inst.locations)


# --------------------------------------------------------------------------- testbed

def test_cluster_status_without_kubectl_is_a_message(monkeypatch):
    """A4: a missing or dead kubectl is a warning line, never an exception."""
    def boom(*a, **k):
        raise FileNotFoundError("kubectl")
    monkeypatch.setattr(subprocess, "run", boom)
    status = testbed.cluster_status()
    assert status.ok is False and status.ready is False
    assert "not reachable" in status.message


def test_measure_falls_back_to_cached_when_the_cluster_is_down(monkeypatch):
    """A4: the Measure button's path returns the cached measurement plus the reason."""
    monkeypatch.setattr(testbed, "cluster_status",
                        lambda *a, **k: testbed.Status(False, "Cluster not reachable: stopped"))
    meas = testbed.measure_or_cached(duration_s=5)
    assert meas.ok and meas.source == "cached"
    assert "Live measurement unavailable" in meas.message
    assert meas.bytes_per_request  # usable numbers, not an empty dict


def test_cached_measurement_reproduces_the_committed_t1():
    """Re-pricing T1 from the cached bytes/request must give the committed T1 cost."""
    meas = testbed.cached()
    fresh = core.t1_from_bytes(meas.bytes_per_request, 50.0, meas.internet_bytes)
    new = core.build_instance(fresh, "core")
    old = core.build_instance(core.TOPOLOGIES["T1 three-tier (measured)"], "core")
    a_new = core.run_methods(new, ("ilp_tight",)).results[0]
    a_old = core.run_methods(old, ("ilp_tight",)).results[0]
    assert a_new.total == pytest.approx(a_old.total, rel=1e-6)


def test_t1_from_bytes_changes_the_volumes_it_is_given():
    meas = testbed.cached()
    doubled = {k: 2 * v for k, v in meas.bytes_per_request.items()}
    topo = core.t1_from_bytes(doubled, 50.0)
    base = core.build_instance(core.TOPOLOGIES["T1 three-tier (measured)"], "core")
    scaled = core.build_instance(topo, "core")
    assert sum(gb for _, _, gb in scaled.edges) == pytest.approx(
        2 * sum(gb for _, _, gb in base.edges))


# --------------------------------------------------------------------------- preflight

def test_offline_preflight_exits_zero():
    """A1."""
    assert preflight.main(["--offline"]) == 0
