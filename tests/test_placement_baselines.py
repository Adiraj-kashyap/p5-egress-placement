"""M08: cost evaluator and baselines B1/B2, on a hand-computed toy and on the committed T1-T3."""
import math

import pytest

from placement.baselines import b1_cheapest_per_vcpu, b1_tied_locations, b2_best, b2_single_provider
from placement.cost import evaluate
from placement.instance import HOURS_PER_MONTH, Instance, load_instance, provider_of, shape_for

SNAPSHOT = "2026-09-21"
TOPOLOGIES = ["topologies/t1_three_tier.json", "topologies/t2_pipeline.json",
              "topologies/t3_microservices.json"]

X, Y, Z = "aws:x", "aws:y", "gcp:z"


def make_toy() -> Instance:
    """Two components (a small, b medium with 100 GB), three locations; prices chosen by hand."""
    locs = (X, Y, Z)
    comps = ("a", "b")
    shape = {"a": "small", "b": "medium"}
    vcpu = {"a": 2, "b": 4}
    storage_gb = {"a": 0.0, "b": 100.0}
    hourly = {("small", X): 0.10, ("small", Y): 0.12, ("small", Z): 0.08,
              ("medium", X): 0.20, ("medium", Y): 0.24, ("medium", Z): 0.20}
    st_rate = {X: 0.02, Y: 0.03, Z: 0.01}
    cm = {(c, l): hourly[(shape[c], l)] * HOURS_PER_MONTH for c in comps for l in locs}
    sm = {(c, l): storage_gb[c] * st_rate[l] for c in comps for l in locs}
    egress = {(X, X): 0.0, (X, Y): 0.02, (X, Z): 0.09,
              (Y, X): 0.01, (Y, Y): 0.0, (Y, Z): 0.08,
              (Z, X): 0.12, (Z, Y): 0.12, (Z, Z): 0.0}
    return Instance(
        instance_id="toy@test", topology_id="toy", snapshot_date="test", location_set="test",
        components=comps, locations=locs, shape=shape, vcpu=vcpu, storage_gb=storage_gb,
        allowed={c: locs for c in comps}, usd_per_hour=hourly, compute_month=cm, storage_month=sm,
        k={key: cm[key] + sm[key] for key in cm},
        edges=(("a", "b", 100.0), ("b", "a", 50.0)),
        internet_gb={"a": 10.0}, r={X: 0.09, Y: 0.08, Z: 0.12}, egress=egress,
    )


@pytest.fixture(scope="module")
def real():
    return [load_instance(t, SNAPSHOT, "core") for t in TOPOLOGIES]


# ---- evaluate -------------------------------------------------------------------------------

def test_evaluate_hand_computed():
    inst = make_toy()
    cb = evaluate(inst, {"a": X, "b": Z})
    # compute 0.10*730 + 0.20*730 = 73 + 146; storage 100*0.01; egress 100*0.09 + 50*0.12; internet 10*0.09
    assert math.isclose(cb.compute, 219.0, rel_tol=1e-9)
    assert math.isclose(cb.storage, 1.0, rel_tol=1e-9)
    assert math.isclose(cb.egress, 15.0, rel_tol=1e-9)
    assert math.isclose(cb.internet, 0.9, rel_tol=1e-9)
    assert math.isclose(cb.total, 235.9, rel_tol=1e-9)
    assert math.isclose(cb.egress_share, 15.0 / 235.9, rel_tol=1e-9)
    assert cb.providers_used == 2


def test_evaluate_directed_sender_pays():
    inst = make_toy()
    # a at Y, b at X: a->b uses egress[Y,X]=0.01, b->a uses egress[X,Y]=0.02
    cb = evaluate(inst, {"a": Y, "b": X})
    assert math.isclose(cb.egress, 100 * 0.01 + 50 * 0.02, rel_tol=1e-9)
    assert cb.providers_used == 1


def test_evaluate_same_location_has_no_transfer_cost():
    inst = make_toy()
    assert evaluate(inst, {"a": Z, "b": Z}).egress == 0.0


def test_evaluate_invariant_to_dict_order(real):
    for inst in real:
        a = b1_cheapest_per_vcpu(inst)
        forward = evaluate(inst, dict(a))
        backward = evaluate(inst, dict(reversed(list(a.items()))))
        assert forward == backward


def test_evaluate_rejects_bad_assignments():
    inst = make_toy()
    with pytest.raises(ValueError):
        evaluate(inst, {"a": X})
    with pytest.raises(ValueError):
        evaluate(inst, {"a": X, "b": X, "c": X})
    with pytest.raises(ValueError):
        evaluate(inst, {"a": X, "b": "azure:nowhere"})


def test_terms_sum_to_total(real):
    for inst in real:
        for a in (b1_cheapest_per_vcpu(inst), b2_single_provider(inst, "gcp")):
            cb = evaluate(inst, a)
            assert math.isclose(cb.compute + cb.storage + cb.egress + cb.internet, cb.total, rel_tol=1e-6)


# ---- instance -------------------------------------------------------------------------------

def test_shape_for_picks_smallest_fitting_shape():
    assert shape_for(2, 8) == "small"
    assert shape_for(3, 8) == "medium"
    assert shape_for(2, 20) == "large"
    assert shape_for(16, 64) == "xlarge"
    with pytest.raises(ValueError):
        shape_for(32, 64)


def test_real_instance_dimensions(real):
    t1, t2, t3 = real
    assert [i.n_components for i in real] == [4, 7, 11]
    assert all(i.n_locations == 12 for i in real)
    assert t1.shape == {"web": "small", "api": "medium", "cache": "small", "db": "medium"}
    # k = hourly * 730 + storage; egress diagonal zero
    assert math.isclose(t1.k[("db", "aws:us-east-1")], 0.192 * 730 + 200 * 0.023, rel_tol=1e-9)
    assert all(t1.egress[(l, l)] == 0.0 for l in t1.locations)
    assert load_instance(TOPOLOGIES[0], SNAPSHOT, "ext").n_locations == 24


# ---- baselines ------------------------------------------------------------------------------

def test_b1_toy_picks_min_price_per_vcpu_then_storage():
    inst = make_toy()
    # a: 0.10/2, 0.12/2, 0.08/2 -> Z. b: X and Z tie at 0.05/vCPU; storage 100*0.01 < 100*0.02 -> Z.
    assert b1_cheapest_per_vcpu(inst) == {"a": Z, "b": Z}


def test_b1_minimises_price_per_vcpu_on_real_data(real):
    for inst in real:
        a = b1_cheapest_per_vcpu(inst)
        for c in inst.components:
            best = min(inst.usd_per_hour[(inst.shape[c], l)] / inst.vcpu[c] for l in inst.allowed[c])
            got = inst.usd_per_hour[(inst.shape[c], a[c])] / inst.vcpu[c]
            assert math.isclose(got, best, rel_tol=1e-9)
            assert a[c] in b1_tied_locations(inst, c)


def test_b2_uses_exactly_one_region(real):
    for inst in [make_toy(), *real]:
        providers = {provider_of(l) for l in inst.locations}
        for p in providers:
            a = b2_single_provider(inst, p)
            assert len(set(a.values())) == 1
            assert provider_of(next(iter(a.values()))) == p
            assert evaluate(inst, a).egress == 0.0


def test_b2_toy_picks_cheapest_region_for_compute_plus_storage():
    inst = make_toy()
    # aws:x = 73 + 146 + 2 = 221 < aws:y = 87.6 + 175.2 + 3
    assert set(b2_single_provider(inst, "aws").values()) == {X}
    assert set(b2_single_provider(inst, "gcp").values()) == {Z}


def test_b2_best_is_min_of_the_three(real):
    for inst in real:
        p, a, cb = b2_best(inst)
        totals = {q: evaluate(inst, b2_single_provider(inst, q)).total for q in ("aws", "azure", "gcp")}
        assert math.isclose(cb.total, min(totals.values()), rel_tol=1e-9)
        assert math.isclose(totals[p], cb.total, rel_tol=1e-9)
        assert evaluate(inst, a) == cb
