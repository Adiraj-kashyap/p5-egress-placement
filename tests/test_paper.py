"""The paper sources (M21): bibliography, number macros and the A3-A5 source checks."""
import re

from analysis import check_paper as cp
from analysis import make_bib
from analysis import paper_numbers as pn
from analysis import verdicts as V


def test_refs_bib_is_fresh_render_of_verified_rows():
    assert make_bib.OUT.read_text(encoding="utf-8") == make_bib.render()
    assert len(make_bib.keys()) == len(make_bib.verified_rows())


def test_numbers_tex_is_fresh_render():
    assert pn.OUT.read_text(encoding="utf-8") == pn.render()


def test_numbers_match_the_verdicts():
    n = pn.numbers()
    vs = {v.hid: v.verdict for v in V.all_verdicts()}
    assert (n["h1.verdict"], n["h2.verdict"], n["h3.verdict"]) == (vs["H1"], vs["H2"], vs["H3"])


def test_every_key_used_in_main_tex_is_defined():
    tex = cp.TEX.read_text(encoding="utf-8")
    used = set(re.findall(r"\\(?:N|pct|usdm)\{([^}#]*)\}", tex))
    assert used, "main.tex quotes no generated numbers"
    assert used <= set(pn.numbers()), sorted(used - set(pn.numbers()))


def test_source_checks_pass():
    """A3 sections, A4 verified citations, A5 no typed numbers (A1/A2 need a compiled PDF)."""
    tex = cp.TEX.read_text(encoding="utf-8")
    cited = {k.strip() for g in re.findall(r"\\cite\{([^}]*)\}", tex) for k in g.split(",")}
    assert all(re.search(p, tex) for p in cp.SECTIONS.values())
    assert cited and cited <= make_bib.keys()
    assert not cp.stray_digits(tex)


def test_typed_number_is_caught():
    tex = cp.TEX.read_text(encoding="utf-8")
    assert not cp.stray_digits(tex)
    assert cp.stray_digits(tex.replace(r"\pct{h1.thr} threshold", r"20\% threshold", 1))
    assert cp.stray_digits(tex.replace(r"$\alpha=\N{sa.alpha}$", r"$\alpha=0.995$", 1))
