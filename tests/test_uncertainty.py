"""Tests for the traffic uncertainty draws (M16 step 2, 05 §3)."""
from __future__ import annotations

import copy
import json
import statistics
from pathlib import Path

import pytest

from experiments import uncertainty as unc

ROOT = Path(__file__).resolve().parents[1]
T1 = ROOT / "topologies" / "t1_three_tier.json"
T2 = ROOT / "topologies" / "t2_pipeline.json"
T3 = ROOT / "topologies" / "t3_microservices.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def t1() -> dict:
    return load(T1)


@pytest.fixture(scope="module")
def t2() -> dict:
    return load(T2)


def test_draw_seed_is_frozen():
    assert unc.draw_seed(0) == 10_000
    assert unc.draw_seed(29) == 10_029
    with pytest.raises(ValueError):
        unc.draw_seed(-1)


def test_measurement_pool_has_one_entry_per_run(t1):
    pool = unc.measurement_pool()
    for edge in t1["edges"]:
        assert len(pool[(edge["src"], edge["dst"])]) == 3
    assert len(pool[("web", "internet")]) == 3


@pytest.mark.parametrize("draw_id", [0, 7, 29])
def test_draws_are_reproducible_and_do_not_mutate_the_input(t1, draw_id):
    before = copy.deepcopy(t1)
    a = unc.draw_topology(t1, draw_id)
    b = unc.draw_topology(t1, draw_id)
    assert a == b
    assert t1 == before


def test_draw_metadata(t1, t2):
    d = unc.draw_topology(t1, 5)
    assert d["provenance"] == "draw:5"
    assert d["assumptions"]["draw_id"] == 5
    assert d["assumptions"]["draw_seed"] == 10_005
    assert d["assumptions"]["base_provenance"] == "measured"
    assert d["id"] == t1["id"]
    assert d["components"] == t1["components"]
    assert unc.draw_topology(t2, 5)["assumptions"]["base_provenance"] == "stated"
    with pytest.raises(ValueError):
        unc.draw_topology(d, 6)


def test_distinct_draws_differ(t1):
    a = unc.draw_topology(t1, 0)
    b = unc.draw_topology(t1, 1)
    assert [e["gb_per_month"] for e in a["edges"]] != [e["gb_per_month"] for e in b["edges"]]


def test_measured_draws_stay_within_the_observed_range_times_the_rate_factor(t1):
    """Each drawn volume is an observed bytes/request value at the drawn rate (05 §3)."""
    pool = unc.measurement_pool()
    for draw_id in range(30):
        d = unc.draw_topology(t1, draw_id)
        rate = d["assumptions"]["requests_per_s"]
        assert rate > 0
        for edge in d["edges"]:
            samples = pool[(edge["src"], edge["dst"])]
            lo = unc._gb_per_month(min(samples), rate)
            hi = unc._gb_per_month(max(samples), rate)
            assert lo - 1e-6 <= edge["gb_per_month"] <= hi + 1e-6
        for item in d["internet_egress"]:
            samples = pool[(item["src"], "internet")]
            lo = unc._gb_per_month(min(samples), rate)
            hi = unc._gb_per_month(max(samples), rate)
            assert lo - 1e-6 <= item["gb_per_month"] <= hi + 1e-6


def test_measured_rate_factor_is_lognormal_around_the_stated_rate(t1):
    base = t1["assumptions"]["requests_per_s"]
    factors = [unc.draw_topology(t1, i)["assumptions"]["rate_factor"] for i in range(30)]
    assert all(f > 0 for f in factors)
    assert 0.7 < statistics.median(factors) < 1.4  # median 1 in the model
    rates = [unc.draw_topology(t1, i)["assumptions"]["requests_per_s"] for i in range(30)]
    assert statistics.median(rates) == pytest.approx(base * statistics.median(factors), rel=1e-9)


def test_median_of_drawn_volumes_is_close_to_the_base(t2):
    """Both lognormal factors have median 1, so the draw median tracks the stated volume."""
    base = {(e["src"], e["dst"]): e["gb_per_month"] for e in t2["edges"]}
    draws = [unc.draw_topology(t2, i) for i in range(30)]
    for key, base_gb in base.items():
        vals = [
            e["gb_per_month"]
            for d in draws
            for e in d["edges"]
            if (e["src"], e["dst"]) == key
        ]
        assert statistics.median(vals) == pytest.approx(base_gb, rel=0.5)


def test_stated_draw_applies_a_shared_global_factor(t2):
    """Dividing out the per-edge factor is impossible, but all edges share one factor:
    the ratio of drawn to base volume must have the same geometric drift across edges."""
    d = unc.draw_topology(t2, 3)
    g = d["assumptions"]["global_factor"]
    assert g > 0
    base = {(e["src"], e["dst"]): e["gb_per_month"] for e in t2["edges"]}
    ratios = [e["gb_per_month"] / base[(e["src"], e["dst"])] / g for e in d["edges"]]
    assert all(r > 0 for r in ratios)
    assert 0.2 < statistics.median(ratios) < 5.0  # per-edge factors, median 1


def test_t3_draws_work():
    d = unc.draw_topology(load(T3), 11)
    assert d["provenance"] == "draw:11"
    assert len(d["edges"]) == 30
    assert all(e["gb_per_month"] > 0 for e in d["edges"])


def test_scale_edges_leaves_internet_egress_alone(t2):
    s = unc.scale_edges(t2, 4.0)
    for a, b in zip(s["edges"], t2["edges"]):
        assert a["gb_per_month"] == pytest.approx(b["gb_per_month"] * 4.0)
    for a, b in zip(s["internet_egress"], t2["internet_egress"]):
        assert a["gb_per_month"] == b["gb_per_month"]
    assert s["assumptions"]["traffic_scale"] == 4.0
    with pytest.raises(ValueError):
        unc.scale_edges(t2, 0)


def test_draw_then_scale_composes(t1):
    d = unc.draw_topology(t1, 2)
    s = unc.scale_edges(d, 0.5)
    assert s["provenance"] == "draw:2"
    for a, b in zip(s["edges"], d["edges"]):
        assert a["gb_per_month"] == pytest.approx(b["gb_per_month"] * 0.5)


def test_unknown_provenance_is_rejected(t1):
    bad = copy.deepcopy(t1)
    bad["provenance"] = "placeholder"
    with pytest.raises(ValueError):
        unc.draw_topology(bad, 0)
