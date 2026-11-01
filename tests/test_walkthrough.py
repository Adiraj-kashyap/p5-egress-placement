"""M22 walkthrough: every chapter renders headless, and what it shows comes from the files
it cites (non-negotiable 1).

Rendering uses `streamlit.testing.v1.AppTest`, which runs the real `demo/app.py` and each
page script in-process without a server or browser.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from demo import core, explain

APP = str(core.ROOT / "demo" / "app.py")


def render(page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    if page is not None:
        at.switch_page(page)
        at.run()
    return at


# --------------------------------------------------------------------------- rendering

@pytest.mark.parametrize("chapter", explain.CHAPTERS, ids=lambda c: c.file)
def test_every_chapter_renders_without_exception(chapter):
    at = render(None if chapter.file == explain.CHAPTERS[0].file else chapter.file)
    assert not at.exception, [e.value for e in at.exception]
    assert at.title, chapter.file


def test_chapter_files_exist_and_are_in_order():
    for c in explain.CHAPTERS:
        assert (core.ROOT / "demo" / c.file).exists(), c.file
    assert [c.file for c in explain.CHAPTERS] == sorted(c.file for c in explain.CHAPTERS)


def test_solvers_chapter_solves_live_when_asked():
    at = render("chapters/04_solvers.py")
    next(b for b in at.button if b.label == "Solve now").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "outcome" in at.session_state
    ilp = next(r for r in at.session_state["outcome"].results if r.method == "ilp_tight")
    assert ilp.proven_optimal


def test_cost_model_sandbox_reprices_on_change():
    """Loading the ILP optimum into the sandbox shows a bill equal to the optimum."""
    at = render("chapters/03_cost_model.py")
    next(b for b in at.button if b.label == "Show the ILP optimum").click().run()
    assert not at.exception, [e.value for e in at.exception]
    bill = next(m for m in at.metric if m.label == "Your monthly bill")
    opt = next(m for m in at.metric if m.label == "ILP optimum")
    assert bill.value == opt.value


def test_testbed_chapter_cached_fallback_renders():
    at = render("chapters/09_testbed.py")
    next(b for b in at.button if b.label == "Use cached measurement").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(m.label == "ILP optimum" for m in at.metric)


# --------------------------------------------------------------------------- sources


def test_verdicts_parse_matches_the_generated_table():
    v = explain.verdicts()
    assert set(v) == {"H1", "H2", "H3"}
    text = explain.read(explain.VERDICTS)
    for h, d in v.items():
        assert f"| {h} | **{d['verdict']}** |" in text
        assert d["section"]


def test_hypotheses_are_the_frozen_brief_text():
    hyp = explain.hypotheses()
    assert set(hyp) == {"H1", "H2", "H3"}
    brief = " ".join(explain.read(explain.BRIEF).split())
    for stmt in hyp.values():
        assert stmt in brief


def test_price_loaders_match_the_cost_model():
    core_locs = explain.locations("core")
    assert len(core_locs) == 12 and len(explain.locations("ext")) == 24
    assert len(explain.compute_prices("core")) == 12
    eg = explain.egress_prices("core")
    assert len(eg) == 12 * 12
    assert all(r["usd_per_gb"] == 0 for r in eg if r["from"] == r["to"])
    assert {r["rule"] for r in eg} == {"R1", "R2", "R3"}
    counts = explain.price_row_counts()
    assert counts == {"compute": 96, "egress": 576, "internet": 24, "storage": 24}


def test_topology_summary_and_dot():
    for label in core.TOPOLOGIES:
        topo = explain.topology(label)
        s = explain.topology_summary(topo)
        assert s["components"] == len(topo["components"])
        dot = explain.topology_dot(topo)
        assert dot.startswith("digraph") and dot.count("->") >= s["edges"]


def test_every_cited_source_exists():
    for rel in (explain.BRIEF, explain.VERDICTS, explain.H1_TABLE, explain.ABLATION,
                explain.THREATS, explain.VALIDATION, explain.MEASUREMENT, *explain.RUN_FILES):
        assert (core.ROOT / rel).exists(), rel


def test_md_table_reads_only_the_first_table():
    _, checks = explain.validation_checks()
    assert [c["Check"] for c in checks] == [f"V{i}" for i in range(1, 11)]


def test_no_legacy_pages_directory():
    """A `demo/pages/` folder switches on Streamlit's legacy auto-discovery, which serves
    pages directly by URL without running app.py (so `demo` is not importable and every
    deep link crashes). AppTest does not catch that, so guard the name itself."""
    assert not (core.ROOT / "demo" / "pages").exists()
