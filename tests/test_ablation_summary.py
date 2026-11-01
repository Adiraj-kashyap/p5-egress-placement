"""Tests for analysis/ablation_summary.py (M17 step 5).

These exercise the *summariser*, so they run on small hand-built rows rather than on the real
results: a fixture here can never reach a reported number (02 §1 non-negotiable 1), and the
real rows are checked instead by `--check` drift and `--verify` (A1) against
`results/ablation/runs.csv`.

What matters and is asserted here: the per-draw pairing, the median-over-seeds collapse
(D-068), that the decomposition telescopes in the rendered CSV, and that the generated README
tells the truth about which step dominates — including when it is not the egress step.
"""
from __future__ import annotations

import csv
import io

import pytest

import analysis.ablation_summary as A

HEADER_EXTRA = {"location_set": "core", "egress_share": "0", "providers_used": "1",
                "runtime_s": "0.1", "exp_id": "t"}


def row(topology, scale, method, draw, total, seed="", **kw):
    """One runs.csv row with just the columns the summariser reads."""
    return {"topology_id": topology, "traffic_scale": str(scale), "method": method,
            "draw_id": str(draw), "total_usd": str(total), "seed": seed, **HEADER_EXTRA, **kw}


def chain(topology, scale, draw, b1, b1_storage, no_edge, full):
    """The four costs of one draw along the decomposition chain."""
    return [row(topology, scale, "b1", draw, b1),
            row(topology, scale, "b1_storage", draw, b1_storage),
            row(topology, scale, "ilp_no_edge_egress", draw, no_edge),
            row(topology, scale, "ilp_full", draw, full)]


@pytest.fixture
def rows():
    """Three draws on one topology: step 3 (egress coupling) is the largest step."""
    out = []
    for d, (b1, bs, ne, full) in enumerate([(200, 190, 180, 100), (210, 198, 186, 104),
                                            (190, 183, 175, 99)]):
        out += chain("t1", 1.0, d, b1, bs, ne, full)
    return out


def parse(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_decomposition_telescopes_in_the_rendered_csv(rows):
    """The three step gains sum to the reported total gain."""
    out = parse(A.render_decomposition(rows))
    assert len(out) == 3
    assert sum(float(r["gain_usd_mean"]) for r in out) == pytest.approx(
        float(out[0]["total_gain_usd_mean"]), rel=1e-9)
    assert [int(r["step"]) for r in out] == [1, 2, 3]
    assert [r["from_method"] for r in out] == ["b1", "b1_storage", "ilp_no_edge_egress"]


def test_decomposition_has_three_steps_per_topology_and_scale():
    """A4: 3 steps x 3 topologies, each with a CI."""
    rows = []
    for t in ("t1", "t2", "t3"):
        for d, (b1, bs, ne, full) in enumerate([(200, 190, 180, 100), (210, 198, 186, 104),
                                                (190, 183, 175, 99)]):
            rows += chain(t, 1.0, d, b1, bs, ne, full)
    out = parse(A.render_decomposition(rows))
    assert len(out) == 9
    assert {r["topology_id"] for r in out} == {"t1", "t2", "t3"}
    for r in out:
        assert int(r["n"]) == 3
        assert float(r["gain_usd_ci_lo"]) <= float(r["gain_usd_mean"]) <= float(r["gain_usd_ci_hi"])


def test_penalty_is_paired_per_draw(rows):
    """penalty_vs_ilp_pct is the mean of per-draw penalties, not a ratio of means."""
    out = {(r["method"], r["metric"]): r for r in parse(A.render(A.samples(rows, A.ABLATION_KEYS),
                                                                A.ABLATION_KEYS))}
    expected = sum(100.0 * (b1 - f) / f for b1, f in [(200, 100), (210, 104), (190, 99)]) / 3
    assert float(out[("b1", "penalty_vs_ilp_pct")]["mean"]) == pytest.approx(expected)
    assert int(out[("b1", "penalty_vs_ilp_pct")]["n"]) == 3
    assert float(out[("ilp_full", "penalty_vs_ilp_pct")]["mean"]) == pytest.approx(0.0)


def test_seeds_collapse_to_their_median(rows):
    """D-068: a randomised variant contributes one value per draw, the median over its seeds."""
    rows = rows + [row("t1", 1.0, "sa", 0, v, seed=str(i)) for i, v in enumerate([101, 150, 103])]
    out = {(r["method"], r["metric"]): r for r in parse(A.render(A.samples(rows, A.ABLATION_KEYS),
                                                                A.ABLATION_KEYS))}
    sa = out[("sa", "total_usd")]
    assert int(sa["n"]) == 1 and float(sa["mean"]) == pytest.approx(103.0)  # median, not mean


def test_verify_catches_a_variant_beating_the_optimum(rows, monkeypatch, tmp_path):
    """A variant cheaper than the proven optimum on a draw is a bug, and --verify says so."""
    # Replace draw 0's b1_storage row rather than adding one: a drawn value is the median over
    # that method's rows (D-068), so an extra row would only pull the draw down to 120 (D-074).
    bad = [r for r in rows if not (r["method"] == "b1_storage" and r["draw_id"] == "0")]
    bad += [row("t1", 1.0, "b1_storage", 0, 50)]
    _write_runs(tmp_path, bad, monkeypatch)
    out = A.verify()
    assert any("< ilp_full" in line for line in out)


def test_verify_passes_on_consistent_rows(rows, monkeypatch, tmp_path):
    _write_runs(tmp_path, rows, monkeypatch)
    assert A.verify() == []


def _write_runs(tmp_path, rows, monkeypatch):
    """Point the module at a temporary results/ablation containing `rows`."""
    d = tmp_path / "ablation"
    d.mkdir()
    with (d / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(A, "ABLATION", d)
    return d


def test_readme_is_short_and_names_the_dominant_step(rows):
    """Step 3 is the largest here, so the README must say the egress step dominates."""
    text = A.render_readme(rows)
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(text.splitlines()) <= 15, text
    assert "step 3" in text
    assert "Egress coupling (step 3) is the largest step at 1 of 1" in text
    assert "GENERATED" in text


def test_readme_states_plainly_when_egress_does_not_dominate():
    """The honest case: a per-component step is larger, and the note must say so."""
    rows = []
    for d, (b1, bs, ne, full) in enumerate([(200, 120, 110, 105), (210, 125, 116, 110),
                                            (190, 118, 108, 104)]):
        rows += chain("t1", 1.0, d, b1, bs, ne, full)
    text = A.render_readme(rows)
    assert "step 1" in text
    assert "does NOT dominate anywhere" in text
    assert "NOT caused by modelling inter-component egress" in text
    assert len(text.splitlines()) <= 15


def test_dominant_step_is_by_signed_gain_not_magnitude():
    """A step that made the true cost worse cannot be reported as causing the gain."""
    steps = [{"step": 1, "from_method": "b1", "gain_usd_mean": -500.0},
             {"step": 3, "from_method": "ilp_no_edge_egress", "gain_usd_mean": 10.0}]
    assert A._dominant(steps) == ("step 3", True)


def test_order_sorts_numeric_columns_numerically():
    """Scales must sort 1 < 2 < 10, not as the strings '1' < '10' < '2'."""
    keys = [("t", "10.0"), ("t", "2.0"), ("t", "1.0")]
    assert [k[1] for k in sorted(keys, key=A._order)] == ["1.0", "2.0", "10.0"]


def test_sensitivity_keys_include_both_price_axes():
    """A sensitivity row is comparable only within its grid point (D-073)."""
    assert "egress_mult" in A.SENSITIVITY_KEYS and "locs_per_provider" in A.SENSITIVITY_KEYS
    assert A.SENSITIVITY_KEYS[-1] == "method"
    assert A.ABLATION_KEYS[-1] == "method"
