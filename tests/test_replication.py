"""Tests for the replication guard and the replicate/timing summaries (M16 steps 7-8)."""
from __future__ import annotations

import csv

import pytest

from analysis.replicate_summary import (REPLICATE_KEYS, ilp_violations, replicate_samples,
                                        render, timing_samples)
from experiments.check_replication import MIN_N, REGISTRY, DirSpec, group


def rep_row(topology="t1_three_tier", scale="1.0", method="b1", draw=0, total=100.0,
            seed="", runtime=0.01):
    return {"topology_id": topology, "location_set": "core", "traffic_scale": scale,
            "method": method, "draw_id": str(draw), "repeat_id": "", "seed": str(seed),
            "total_usd": str(total), "egress_share": "0.1", "providers_used": "1",
            "runtime_s": str(runtime), "instance_id": f"{topology}@core@d={draw}@s={scale}",
            "n_components": "4"}


def test_group_counts_draws_not_rows():
    """5 SA seeds on one draw are one replicate, not five (05 §2, D-068)."""
    spec = REGISTRY["replicates"]
    rows = [rep_row(method="sa", draw=d, seed=s) for d in range(4) for s in range(5)]
    counts = group(rows, spec)
    assert list(counts.values()) == [4]


def test_group_separates_scales_and_methods():
    spec = REGISTRY["replicates"]
    rows = [rep_row(method=m, scale=s, draw=d)
            for m in ("b1", "ilp_tight") for s in ("1.0", "10.0") for d in range(3)]
    counts = group(rows, spec)
    assert len(counts) == 4 and set(counts.values()) == {3}


def test_group_uses_repeat_id_for_timing():
    spec = REGISTRY["timing"]
    rows = [{"instance_id": "syn_n8_s1@core", "location_set": "core", "method": "sa",
             "seed": "0", "repeat_id": str(r), "draw_id": ""} for r in range(3)]
    assert list(group(rows, spec).values()) == [3]


def test_min_n_is_three():
    assert MIN_N == 3


def test_registry_enforces_the_replicated_dirs():
    assert REGISTRY["replicates"].enforced and REGISTRY["timing"].enforced
    assert all(isinstance(s, DirSpec) for s in REGISTRY.values())


def test_replicate_samples_are_paired_against_the_ilp_of_the_same_draw():
    rows = []
    for d, (ilp, b1) in enumerate([(100.0, 110.0), (200.0, 202.0), (50.0, 75.0)]):
        rows.append(rep_row(method="ilp_tight", draw=d, total=ilp))
        rows.append(rep_row(method="b1", draw=d, total=b1))
    s = replicate_samples(rows)
    pen = s[("t1_three_tier", "core", "1.0", "b1")]["penalty_vs_ilp_pct"]
    assert pen == pytest.approx([10.0, 1.0, 50.0])
    assert s[("t1_three_tier", "core", "1.0", "ilp_tight")]["penalty_vs_ilp_pct"] == pytest.approx([0, 0, 0])


def test_sa_seeds_collapse_to_their_median_per_draw():
    rows = [rep_row(method="sa", draw=0, seed=s, total=t)
            for s, t in enumerate([100.0, 101.0, 105.0])]
    rows += [rep_row(method="sa", draw=1, seed=s, total=t)
             for s, t in enumerate([200.0, 200.0, 260.0])]
    s = replicate_samples(rows)
    assert s[("t1_three_tier", "core", "1.0", "sa")]["total_usd"] == pytest.approx([101.0, 200.0])


def test_render_writes_one_row_per_metric_with_ci_columns():
    rows = [rep_row(method="ilp_tight", draw=d, total=100.0 + d) for d in range(5)]
    rows += [rep_row(method="b1", draw=d, total=110.0 + d) for d in range(5)]
    text = render(replicate_samples(rows), REPLICATE_KEYS, ["total_usd", "penalty_vs_ilp_pct"])
    got = list(csv.DictReader(text.splitlines()))
    assert {r["metric"] for r in got} == {"total_usd", "penalty_vs_ilp_pct"}
    for r in got:
        assert int(r["n"]) == 5
        assert float(r["ci_lo"]) <= float(r["mean"]) <= float(r["ci_hi"])
    b1_total = next(r for r in got if r["method"] == "b1" and r["metric"] == "total_usd")
    assert float(b1_total["mean"]) == pytest.approx(112.0)


def test_timing_samples_group_repeats():
    rows = [{"instance_id": "syn_n8_s1@core", "location_set": "core", "n_components": "8",
             "method": "ilp_tight", "seed": "", "repeat_id": str(r), "runtime_s": str(0.1 + r / 100)}
            for r in range(3)]
    s = timing_samples(rows)
    key = ("syn_n8_s1@core", "core", "8", "ilp_tight", "")
    assert s[key]["runtime_s"] == pytest.approx([0.1, 0.11, 0.12])
    text = render(s, list(key and ["instance_id", "location_set", "n_components", "method", "seed"]),
                  ["runtime_s"])
    got = list(csv.DictReader(text.splitlines()))
    assert len(got) == 1 and int(got[0]["n"]) == 3


def test_ilp_violations_flags_a_method_cheaper_than_the_optimum():
    rows = [rep_row(method="ilp_tight", draw=0, total=100.0),
            rep_row(method="b1", draw=0, total=99.0)]
    bad = ilp_violations(rows)
    assert len(bad) == 1 and "b1" in bad[0]


def test_ilp_violations_is_empty_when_the_ilp_is_best():
    rows = [rep_row(method="ilp_tight", draw=d, total=100.0) for d in range(3)]
    rows += [rep_row(method="greedy_1opt", draw=d, total=100.0 + d) for d in range(3)]
    assert ilp_violations(rows) == []


def test_ilp_violations_reports_a_missing_reference():
    assert ilp_violations([rep_row(method="b1", draw=0)])[0].endswith("to compare against")