"""Terminal views behind review/*.bat: every view runs, and a live solve prints the same
bill as `demo.core` computes (no second source of numbers)."""

from __future__ import annotations

import pytest

from demo import core, show


@pytest.mark.parametrize("argv", [["pricing"], ["workloads"], ["testbed"], ["verdicts"],
                                  ["solve", "--topology", "T1", "--methods", "ilp_tight,b1"],
                                  ["sweep", "--topology", "T2", "--scales", "1,100"]])
def test_every_view_runs(argv, capsys):
    assert show.main(argv) == 0
    assert capsys.readouterr().out.strip()


def test_solve_prints_the_core_bill(capsys):
    show.main(["solve", "--topology", "T1", "--methods", "ilp_tight,b1"])
    printed = capsys.readouterr().out
    inst = core.build_instance(core.TOPOLOGIES[show.TOPO_KEYS["T1"]])
    out = core.run_methods(inst, methods=("ilp_tight", "b1"))
    for r in out.results:
        assert show.fmt(r.total) in printed, r.label
