"""docs/review1/baseline_results.md must be a fresh render of results/baselines (M09 A4)."""
import csv
import re

from analysis import review1_tables as rt


def test_committed_pack_matches_fresh_render():
    assert rt.OUT.read_text(encoding="utf-8") == rt.render()


def test_every_runs_total_appears_in_pack():
    text = rt.OUT.read_text(encoding="utf-8")
    with rt.RUNS.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 15
    for r in rows:
        assert f"| {r['method']} | {float(r['total_usd']):,.2f} |" in text


def test_snapshot_date_is_stated():
    text = rt.OUT.read_text(encoding="utf-8")
    assert re.search(r"Pricing snapshot:\*\* 2026-09-21", text)
