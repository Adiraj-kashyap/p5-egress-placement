"""M15 sweep: scale grid, scaled instances, B1-alt, and the crossover / A2 rules of D-056."""
import json

import pytest

from experiments.exp_sweep import b1_alt, scaled_instance, scales, summarize_rows
from placement.baselines import b1_cheapest_per_vcpu
from placement.cost import evaluate
from placement.instance import load_instance
from pricing.common import ROOT

CFG = json.loads((ROOT / "experiments" / "configs" / "sweep.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def t1():
    return load_instance("topologies/t1_three_tier.json", "2026-09-21", "core")


def test_scale_grid():
    g = scales(CFG)
    assert len(g) == 25
    assert g[0] == pytest.approx(0.01) and g[-1] == pytest.approx(100.0)
    assert g[12] == 1.0  # s = 1 is an exact grid point (H1 evidence)
    assert all(b > a for a, b in zip(g, g[1:]))


def test_scaled_instance_scales_edges_and_rates_only(t1):
    a = b1_cheapest_per_vcpu(t1)
    base = evaluate(t1, a)
    x = evaluate(scaled_instance(t1, 10.0, 1.0), a)
    assert x.egress == pytest.approx(10 * base.egress)
    assert (x.compute, x.storage, x.internet) == (base.compute, base.storage, base.internet)
    y = evaluate(scaled_instance(t1, 1.0, 1.25), a)
    assert y.egress == pytest.approx(1.25 * base.egress)
    assert y.internet == base.internet  # internet rates are not inter-region rates
    assert scaled_instance(t1, 1.0, 1.0).instance_id != scaled_instance(t1, 1.0, 1.25).instance_id


def test_b1_alt_is_the_opposite_tie_break(t1):
    # D-039: the opposite final tie-break gives B1 = B2-azure = 481.18 on T1 (reported B1 497.58)
    assert round(evaluate(t1, b1_cheapest_per_vcpu(t1)).total, 2) == 497.58
    assert round(evaluate(t1, b1_alt(t1)).total, 2) == 481.18


def _rows(topo, grid, ilp_prov, b1_prov=2, ilp_total=100.0, b1_total=110.0, b2_total=None):
    out = []
    for s, p in zip(grid, ilp_prov):
        common = {"topology_id": topo, "rate_factor": "1.0", "scale": repr(s), "base_edge_gb": "10",
                  "edge_gb": str(10 * s), "status": "optimal", "egress_share": "0.1", "egress_usd": "1", "seed": ""}
        out.append({**common, "method": "ilp_tight", "total_usd": str(ilp_total), "providers_used": str(p)})
        for m, tot, pr in (("b1", b1_total, b1_prov), ("b1_alt", ilp_total, 1),
                           ("b2_best", ilp_total if b2_total is None else b2_total, 1)):
            out.append({**common, "method": m, "total_usd": str(tot), "providers_used": str(pr)})
    return out


def _x(cross, criterion="ilp_providers_used", variant="b1"):
    return next(c for c in cross if c["criterion"] == criterion and c["b1_variant"] == variant)


def test_crossover_found_at_first_stable_single_point():
    g = [0.01, 0.1, 1.0, 10.0, 100.0]
    _, cross, bad = summarize_rows(_rows("T", g, [2, 1, 2, 1, 1]), g)
    assert bad == []
    c = _x(cross)
    assert c["crossover"] == "yes" and c["s_star"] == 10.0 and c["s_below"] == 1.0
    assert c["T_gb_month"] == 100.0 and c["T_below_gb_month"] == 10.0
    assert _x(cross, variant="b1_alt")["crossover"] == "no"  # B1-alt is single-provider


def test_no_crossover_cases():
    g = [0.01, 1.0, 100.0]
    _, cross, _ = summarize_rows(_rows("T", g, [1, 1, 1]), g)
    assert _x(cross)["crossover"] == "no" and "every scale" in _x(cross)["reason"]
    _, cross, _ = summarize_rows(_rows("T", g, [1, 1, 2]), g)
    assert _x(cross)["crossover"] == "no" and _x(cross)["s_star"] == ""


def test_a2_flags_method_below_ilp_and_missing_points():
    g = [0.01, 1.0, 100.0]
    rows = _rows("T", g, [1, 1, 1], b2_total=99.0)
    _, _, bad = summarize_rows(rows, g)
    assert len(bad) == 3 and all("b2_best" in b for b in bad)
    _, _, bad = summarize_rows(_rows("T", g[:2], [1, 1]), g)
    assert any("missing point" in b for b in bad)


def test_tie_robust_single_provider_criterion():
    g = [0.01, 1.0, 100.0]
    summary, cross, _ = summarize_rows(_rows("T", g, [2, 2, 2]), g)  # multi-provider ILP, but B2 ties it
    assert all(r["single_provider_optimal"] for r in summary)
    assert _x(cross, "single_provider_optimal")["reason"].startswith("optimum single-provider at every scale")
