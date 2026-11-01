"""Parse a CBC log for what PuLP's status hides (03_SKILLS §S6).

PuLP reports `Optimal` for a time-limited CBC run that found any integer solution, so
proven optimality, the best bound and the gap are read from CBC's own summary block:

    Result - Optimal solution found            (or: Result - Stopped on time limit)
    Objective value:                123.45
    Lower bound:                    120.00     (only printed when the search did branch or stop)
    Gap:                            0.03
    Enumerated nodes:               17
    Total iterations:               2048
    Time (CPU seconds):             0.21
    Time (Wallclock seconds):       0.23
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_NUM = r"(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
_FIELDS = {
    "objective": rf"^Objective value:\s+{_NUM}",
    "lower_bound": rf"^Lower bound:\s+{_NUM}",
    "gap": rf"^Gap:\s+{_NUM}",
    "nodes": rf"^Enumerated nodes:\s+{_NUM}",
    "iterations": rf"^Total iterations:\s+{_NUM}",
    "cpu_s": rf"^Time \(CPU seconds\):\s+{_NUM}",
    "wall_s": rf"^Time \(Wallclock seconds\):\s+{_NUM}",
}


@dataclass(frozen=True)
class CbcSummary:
    """CBC's final summary. `result` is the text after `Result - `, or '' if CBC never printed one.

    `proven_optimal` is True only for `Result - Optimal solution found`. `best_bound` is the
    printed lower bound, or the objective itself when CBC proved optimality without printing
    one (solved in presolve or at the root). Missing numbers are None.
    """

    result: str
    proven_optimal: bool
    stopped_on_time: bool
    objective: float | None
    best_bound: float | None
    gap: float | None
    nodes: int | None
    iterations: int | None
    cpu_s: float | None
    wall_s: float | None


def parse_cbc_log(text: str) -> CbcSummary:
    """Parse the text of a CBC log into a `CbcSummary`.

    Only the last summary block counts (a log holds one per solve). Raises nothing on a
    truncated log: fields that are absent come back as None and `result` as ''.
    """
    results = re.findall(r"^Result - (.+?)\s*$", text, flags=re.M)
    tail = text[text.rfind("Result - "):] if results else text
    vals: dict[str, float | None] = {}
    for key, pat in _FIELDS.items():
        found = re.findall(pat, tail, flags=re.M)
        vals[key] = float(found[-1]) if found else None
    result = results[-1] if results else ""
    proven = result.startswith("Optimal solution found")
    bound = vals["lower_bound"]
    if bound is None and proven:
        bound = vals["objective"]
    gap = vals["gap"]
    if gap is None and proven:
        gap = 0.0
    return CbcSummary(
        result=result,
        proven_optimal=proven,
        stopped_on_time="time" in result.lower(),
        objective=vals["objective"],
        best_bound=bound,
        gap=gap,
        nodes=int(vals["nodes"]) if vals["nodes"] is not None else None,
        iterations=int(vals["iterations"]) if vals["iterations"] is not None else None,
        cpu_s=vals["cpu_s"],
        wall_s=vals["wall_s"],
    )


def parse_cbc_log_file(path: str | Path) -> CbcSummary:
    """Read a CBC log file (any encoding CBC writes is ASCII-safe) and parse it."""
    return parse_cbc_log(Path(path).read_text(encoding="utf-8", errors="replace"))
