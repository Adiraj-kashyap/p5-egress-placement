"""Replication guard: every configuration that feeds a figure must have n >= 3 (M16 step 7).

Non-negotiable 8 (plan v2) forbids a single-run number in any figure or comparison table.
This script is the machine check behind it: it reads every `results/*/runs.csv`, groups the
rows by **configuration** and reports the smallest and median group size per directory.

A configuration is (workload/instance cell, traffic scale, location set, method[, variant]),
05 §2. The replication unit inside a group differs by directory and is stated in REGISTRY:

    replicates  one value per traffic draw (R = 30), SA seeds collapsed to their median
    timing      one value per timing repeat (k = 3), of an otherwise identical job
    scaling     one value per synthetic instance in the (n, L) cell (5)
    ablation    one value per traffic draw (R = 30) per ablation variant (M17)
    sensitivity one value per traffic draw (R = 10) per price-world grid point (M17)

Directories not in REGISTRY are reported but not enforced: they are the plan-v1 single-run
experiments (exact, heuristics, baselines, sweep, smoke), which plan v2 supersedes for
figures. M18 must plot the replicated directories.

    python -m experiments.check_replication            # all registered dirs
    python -m experiments.check_replication replicates # one dir
exit 0 = every enforced configuration has n >= 3; exit 1 = some configuration is short;
exit 2 = a required directory is missing.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pricing.common import ROOT

RESULTS = ROOT / "results"
MIN_N = 3


@dataclass(frozen=True)
class DirSpec:
    """How to group one results directory into configurations."""

    name: str
    unit: str  # the replication unit, for the report
    keys: tuple[str, ...]  # row columns that identify a configuration
    collapse_seed: bool  # SA seeds are part of the configuration, not extra replicates
    enforced: bool = True


REGISTRY: dict[str, DirSpec] = {
    "replicates": DirSpec("replicates", "traffic draw",
                          ("topology_id", "location_set", "traffic_scale", "method"), True),
    "timing": DirSpec("timing", "timing repeat",
                      ("instance_id", "location_set", "method", "seed"), False),
    "scaling": DirSpec("scaling", "synthetic instance",
                       ("n_components", "location_set", "method", "seed"), False),
    # M17. The configuration includes the ablation variant (the `method` column) and, for the
    # sensitivity grid, the two price-world axes, which are their own columns (06 §S12).
    "ablation": DirSpec("ablation", "traffic draw",
                        ("topology_id", "location_set", "traffic_scale", "method"), True),
    "sensitivity": DirSpec("sensitivity", "traffic draw",
                           ("topology_id", "location_set", "traffic_scale", "egress_mult",
                            "locs_per_provider", "method"), True),
}


def read_rows(runs: Path) -> list[dict]:
    """Rows of a runs.csv (empty list if the file does not exist)."""
    if not runs.exists():
        return []
    with runs.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group(rows: list[dict], spec: DirSpec) -> dict[tuple, int]:
    """Configuration key -> number of replicate values.

    With `collapse_seed`, all SA seeds of one draw count as a single value (the method's
    reported result on that draw is the median over its seeds), so the replicate count is
    the number of distinct draws / repeats, not the number of rows.
    """
    seen: dict[tuple, set] = defaultdict(set)
    for i, r in enumerate(rows):
        key = tuple(r.get(k, "") for k in spec.keys)
        if spec.collapse_seed:
            unit = r.get("draw_id", "") or r.get("repeat_id", "") or str(i)
        else:
            unit = r.get("repeat_id", "") or r.get("draw_id", "") or r.get("instance_id", "") or str(i)
        seen[key].add(unit)
    return {k: len(v) for k, v in seen.items()}


def check_dir(spec: DirSpec) -> tuple[bool, str]:
    """(ok, one report line) for one registered results directory."""
    runs = RESULTS / spec.name / "runs.csv"
    rows = read_rows(runs)
    if not rows:
        return (not spec.enforced,
                f"{spec.name:<12} MISSING     {runs.relative_to(ROOT)} does not exist or is empty")
    counts = group(rows, spec)
    lo = min(counts.values())
    med = statistics.median(counts.values())
    short = sorted(k for k, v in counts.items() if v < MIN_N)
    ok = (lo >= MIN_N) or not spec.enforced
    verdict = "OK " if lo >= MIN_N else ("FAIL" if spec.enforced else "warn")
    line = (f"{spec.name:<12} {verdict}  rows {len(rows):>6}  configurations {len(counts):>5}  "
            f"min n {lo:>3}  median n {med:>5.1f}  unit: {spec.unit}")
    if short:
        line += f"\n{'':14}{len(short)} configuration(s) below n = {MIN_N}, e.g. {short[:3]}"
    return ok, line


def main(argv: list[str] | None = None) -> int:
    """Check the registered results directories; return the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dirs", nargs="*", default=None,
                    help=f"results directories to check (default: all of {sorted(REGISTRY)})")
    args = ap.parse_args(argv)
    names = args.dirs or sorted(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"unknown results directory {unknown}; known: {sorted(REGISTRY)}")
        return 2

    print(f"replication check (05 §2): every enforced configuration needs n >= {MIN_N}")
    ok_all = True
    for name in names:
        ok, line = check_dir(REGISTRY[name])
        print(line)
        ok_all &= ok
    others = sorted(p.parent.name for p in RESULTS.glob("*/runs.csv") if p.parent.name not in REGISTRY)
    if others:
        print(f"{'':14}not enforced (plan-v1, single-run by construction): {', '.join(others)}")
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
