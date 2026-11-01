"""M18: analysis outputs are deterministic, match the committed files, obey the figure lint
of 04 §5.2, and apply the frozen thresholds of 00_PROJECT_BRIEF.md §4 to intervals."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from analysis import (check_numbers, figures, hypotheses, results_text, tables, thresholds,
                      verdicts)

ROOT = Path(__file__).resolve().parents[1]
FIGURE_NAMES = {"R2-1_cost_vs_scale", "F0_sa_convergence", "F1_cost_breakdown",
                "F2_egress_penalty", "F3_providers_used", "F4_runtime_vs_n", "F5_gap_boxplots",
                "F6_gain_decomposition", "F7_sensitivity"}


def _committed(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_figure_csvs_deterministic_and_committed():
    first, second = figures.render_csvs(), figures.render_csvs()
    assert first == second
    assert set(first) == FIGURE_NAMES
    for name, text in first.items():
        assert _committed(ROOT / "figures" / f"{name}.csv") == text, \
            f"{name}.csv drifted; re-run analysis.figures"


@pytest.mark.parametrize("name", sorted(FIGURE_NAMES))
def test_every_figure_exists_in_three_formats(name):
    """M18 A1: PNG (200 dpi) for the pack, PDF for the paper, CSV for the audit."""
    for ext, min_bytes in (("png", 10_000), ("pdf", 4_000), ("csv", 100)):
        p = ROOT / "figures" / f"{name}.{ext}"
        assert p.exists(), f"{p.name} missing; re-run analysis.figures"
        assert p.stat().st_size > min_bytes, f"{p.name} is suspiciously small"


def test_figure_lint_passes():
    """04 §5.2: every figure CSV carries mean, a spread column and n >= 3 on every row."""
    assert figures.lint() == []


def test_lint_catches_a_single_run_figure():
    """The lint must actually fail on a figure that plots one run per point."""
    import pandas as pd
    bad = pd.DataFrame({"n": [1, 1], "mean": [1.0, 2.0], "ci_lo": [1.0, 2.0], "ci_hi": [1.0, 2.0]})
    worse = pd.DataFrame({"total_usd": [1.0]})
    problems = figures.lint({"bad": bad, "worse": worse})
    assert any("n < 3" in p for p in problems) and any("no `n` column" in p for p in problems)


def test_tables_deterministic_and_committed():
    first, second = tables.render(), tables.render()
    assert first == second
    for name, text in first.items():
        assert _committed(tables.OUT / name) == text, f"{name} drifted; re-run analysis.tables"


def test_latex_tables_committed():
    for name, text in tables.render_latex().items():
        assert _committed(tables.PAPER / name) == text, f"{name} drifted; re-run analysis.tables --latex"
        assert r"\begin{tabular}" in text and r"\bottomrule" in text


def test_verdicts_and_results_committed():
    assert _committed(ROOT / "docs" / "report" / "verdicts.md") == verdicts.render()
    assert _committed(ROOT / "docs" / "report" / "results.md") == results_text.render()


def test_thresholds_match_frozen_brief():
    brief = (ROOT / "docs" / "methodology" / "project_brief.md").read_text(encoding="utf-8")
    sec = brief.split("## §4", 1)[1].split("## §5", 1)[0]
    assert "**≥ 20%**" in sec and thresholds.H1_MIN_REDUCTION == 0.20
    assert "**5%**" in sec and thresholds.H2_MAX_GAP == 0.05
    assert "**≥ 10×**" in sec and thresholds.H2_MIN_SPEEDUP == 10
    assert "10⁻² to 10²" in sec and thresholds.H3_RANGE == (0.01, 100)
    # verdicts.py must keep reading them from the frozen module, never from results.
    assert verdicts.H1_MIN_REDUCTION is thresholds.H1_MIN_REDUCTION


def test_h3_decision_rates_come_from_the_statistics_file():
    stats_doc = (ROOT / "docs" / "methodology" / "statistical_protocol.md").read_text(encoding="utf-8")
    sec = stats_doc.split("**§4.3 H3.**", 1)[1].split("## §5", 1)[0]
    assert "≥ 80% of draws" in sec and thresholds.H3_SUPPORT_RATE == 0.80
    assert "≤ 20% of draws" in sec and thresholds.H3_REFUTE_RATE == 0.20


def test_every_verdict_is_one_of_three():
    for v in verdicts.all_verdicts():
        assert v.verdict in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"}
        assert v.sources and any(re.search(r"\d", line) for line in v.lines)
        assert all(x in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"} for x in v.per_topology.values())


@pytest.mark.parametrize("lo,hi,thr,direction,expected", [
    (0.21, 0.25, 0.20, "ge", "SUPPORTED"),
    (0.03, 0.04, 0.20, "ge", "REFUTED"),
    (0.19, 0.25, 0.20, "ge", "INCONCLUSIVE"),
    (0.20, 0.25, 0.20, "ge", "SUPPORTED"),   # the rule is "at or above", not "strictly above"
    (0.01, 0.04, 0.05, "le", "SUPPORTED"),
    (0.06, 0.09, 0.05, "le", "REFUTED"),
    (0.04, 0.09, 0.05, "le", "INCONCLUSIVE"),
])
def test_interval_rule_is_the_05_4_shape(lo, hi, thr, direction, expected):
    assert verdicts._interval_rule(lo, hi, thr, direction) == expected


def test_verdict_aggregation():
    agg = verdicts._aggregate
    assert agg({"a": "SUPPORTED", "b": "SUPPORTED"}) == "SUPPORTED"
    assert agg({"a": "SUPPORTED", "b": "REFUTED"}) == "REFUTED"
    assert agg({"a": "SUPPORTED", "b": "INCONCLUSIVE"}) == "INCONCLUSIVE"


def test_h1_is_computed_per_draw_and_paired():
    """The H1 sample must be one reduction per draw, not a ratio of two independent means."""
    rows = hypotheses.h1_rows(0.20)
    assert {r.variant for r in rows} == {"b1", "b1_alt"}
    for r in rows:
        assert r.rho.n == r.b1_usd.n == r.ilp_usd.n >= 3
        assert r.b1_usd.mean >= r.ilp_usd.mean - 1e-9  # the ILP can never be dearer than B1


def test_h2_clauses_have_their_own_instance_counts():
    gap, per_instance = hypotheses.h2_gap()
    sp, wide = hypotheses.h2_speedup()
    assert gap.n == len(per_instance) >= thresholds.MIN_QUALIFYING_INSTANCES
    assert sp.n == len(wide) >= thresholds.MIN_QUALIFYING_INSTANCES
    assert set(wide["n_components"]) <= {15, 20, 25, 30, 40}
    assert (wide["n_components"] >= hypotheses.H2_MIN_N).all()


def test_h3_rate_is_a_proportion_with_a_wilson_interval():
    for r in hypotheses.h3_rows():
        assert 0 <= r.rate <= 1 and r.rate_lo <= r.rate <= r.rate_hi
        assert r.crossovers <= r.n_draws and r.n_draws >= 3
        assert (r.threshold_gb is None) == (r.crossovers == 0)


@pytest.mark.parametrize("doc", ["docs/report/results.md", "docs/report/verdicts.md"])
def test_report_numbers_come_from_tables(doc):
    n, missing = check_numbers.check(ROOT / doc)
    assert n > 20 and missing == []


def test_number_checker_catches_a_typed_number(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("The ILP saves 12,345.67 USD (3.68x faster, T1, D-039, `aws:us-east-1`).",
                 encoding="utf-8")
    assert check_numbers.numbers(p.read_text(encoding="utf-8")) == ["12345.67", "3.68"]
    _, missing = check_numbers.check(p)
    assert missing == ["12345.67"]


def test_results_word_limit():
    assert len(results_text.render().split()) <= results_text.MAX_WORDS
