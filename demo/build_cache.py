"""Build `demo/cache/` — the precomputed, replicated results the walkthrough draws.

The demo must not depend on `results/` or `figures/` being regenerated on the day, and it
must never compute a replicated curve live (8,100 jobs). This script copies the M18
figure CSVs the walkthrough chapters need into `demo/cache/` and writes a manifest recording where
each came from, its sha256 and its row count.

    python -m demo.build_cache [--check]

`--check` recopies nothing and exits 1 if any cached file is missing or differs from its
source, which is how the tests and preflight detect a stale cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(__file__).resolve().parent / "cache"
SOURCE_DIR = ROOT / "figures"

#: figure CSV -> what the walkthrough uses it for (M20 Crossover tab + M22 chapters).
SOURCES = {
    "R2-1_cost_vs_scale.csv": "cost vs traffic scale per method, with 95% CI (R2-1)",
    "F2_egress_penalty.csv": "egress penalty of B1/B2-best vs ILP across the scale sweep (F2)",
    "F3_providers_used.csv": "providers used by the ILP vs traffic scale (F3)",
    "F0_sa_convergence.csv": "SA best/current cost per temperature step over seeds (F0)",
    "F1_cost_breakdown.csv": "cost breakdown per method at s = 1, with 95% CI (F1)",
    "F4_runtime_vs_n.csv": "solver runtime vs component count (F4)",
    "F5_gap_boxplots.csv": "heuristic optimality gap vs component count (F5)",
    "F6_gain_decomposition.csv": "ablation: which ingredient causes the gain (F6)",
    "F7_sensitivity.csv": "ILP saving vs egress price x locations per provider (F7)",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def n_rows(path: Path) -> int:
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


def build(check: bool = False) -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    entries, problems = {}, []

    for name, purpose in SOURCES.items():
        src, dst = SOURCE_DIR / name, CACHE / name
        if not src.exists():
            problems.append(f"source missing: {src.relative_to(ROOT)} "
                            f"(run `python -m analysis.figures`)")
            continue
        digest = sha256(src)
        if check:
            if not dst.exists():
                problems.append(f"cache missing: {dst.relative_to(ROOT)}")
                continue
            if sha256(dst) != digest:
                problems.append(f"cache stale: {dst.relative_to(ROOT)} differs from its source")
                continue
        else:
            shutil.copyfile(src, dst)
        entries[name] = {"source": str(src.relative_to(ROOT)).replace("\\", "/"),
                         "purpose": purpose, "sha256": digest, "rows": n_rows(src)}

    if check:
        for line in problems:
            print(f"FAIL  {line}")
        if problems:
            print(f"cache check FAILED ({len(problems)} problem(s)); "
                  f"run `python -m demo.build_cache`")
            return 1
        print(f"cache OK: {len(entries)} file(s) match their sources in figures/")
        return 0

    if problems:
        for line in problems:
            print(f"FAIL  {line}")
        return 1

    manifest = {"built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "files": entries}
    (CACHE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                         encoding="utf-8")
    for name, e in entries.items():
        print(f"OK    {name}  {e['rows']} rows  <- {e['source']}")
    print("wrote " + str((CACHE / "manifest.json").relative_to(ROOT)).replace("\\", "/"))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the cache matches figures/ instead of rebuilding it")
    args = ap.parse_args(argv)
    return build(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
