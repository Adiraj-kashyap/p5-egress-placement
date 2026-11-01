"""M14: scaling summary definitions (D-054) and drift against committed outputs."""
import pandas as pd

from analysis import scaling_summary as ss


def _row(inst, method, total, rt, n=4, L="core", seed=None, proven=None, tl=None):
    return {"instance_id": f"{inst}@{L}", "method": method, "seed": seed, "n_components": n,
            "n_locations": 12, "location_set": L, "total_usd": total, "runtime_s": rt,
            "proven_optimal": proven, "time_limit_s": tl}


def _frame(rows):
    df = pd.DataFrame(rows)
    df["n"] = df["n_components"]
    df["L"] = df["location_set"]
    return df


def test_gap_uses_only_proven_reference_and_speedup_uses_seed_median():
    rows = [_row("a", "ilp_tight", 100.0, 2.0, proven=True, tl=600),
            _row("b", "ilp_tight", 100.0, 2.0, proven=False, tl=600)]
    rows += [_row("a", "sa", 100.0 + s, 1.0 + s, seed=s) for s in (0, 1, 2)]
    rows += [_row("b", "sa", 50.0, 0.1, seed=s) for s in (0, 1, 2)]  # unproven ref: ignored
    s = ss.summarise(_frame(rows)).set_index("method")
    assert s.loc["sa", "gap_median_pct"] == 1.0
    assert s.loc["sa", "gap_min_pct"] == 0.0
    assert s.loc["sa", "speedup_median"] == 1.0  # 2.0 / median(1, 2, 3)
    assert s.loc["ilp_tight", "proven_optimal"] == 1


def test_frontier_needs_four_of_five_and_reports_not_reached():
    rows = []
    for n, proven in ((4, 5), (6, 4), (8, 3)):
        rows += [_row(f"i{n}_{k}", "ilp_tight", 1.0, 1.0, n=n, proven=k < proven, tl=600) for k in range(5)]
    f = ss.frontier(ss.summarise(_frame(rows))).iloc[0]
    assert f["frontier_n"] == 6 and f["frontier_reached"] and f["first_failing_n"] == 8
    rows = [_row(f"j{k}", "ilp_tight", 1.0, 1.0, proven=True, tl=600) for k in range(5)]
    f = ss.frontier(ss.summarise(_frame(rows))).iloc[0]
    assert not f["frontier_reached"] and f["finding"].startswith("not reached")


def test_committed_summary_reproduces():
    assert ss.main(["--check"]) == 0
