"""M09 A1 / M19 A2: every path in an evidence index exists, and every commit hash resolves.

    python -m analysis.check_evidence_index [index.md]

Run from the repo root; the default index is docs/review1/evidence_index.md and M19 passes
docs/review2/evidence_index.md. Exit 1 if a non-screenshot path is missing.
"""
import itertools, re, subprocess, sys
from pathlib import Path

root = Path.cwd()
index = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/review1/evidence_index.md")
text = (root / index).read_text(encoding="utf-8")
body = text.split("## How to reproduce")[0]

def expand(p):
    parts = re.split(r"(\{[^}]*\})", p)
    opts = [s[1:-1].split(",") if s.startswith("{") else [s] for s in parts]
    return ["".join(c) for c in itertools.product(*opts)]

ok = miss = 0
missing = []
for tok in re.findall(r"`([^`]+)`", body):
    tok = tok.split(" ")[0]
    if "/" not in tok or tok.startswith("python"):
        continue
    for p in expand(tok):
        if (root / p).exists():
            ok += 1
        else:
            miss += 1
            missing.append(p)
shots = [m for m in missing if m.startswith("evidence/screenshots/")]
other = [m for m in missing if m not in shots]
print(f"paths existing={ok} missing={miss} (screenshots={len(set(shots))}, other={len(set(other))})")
for m in sorted(set(other)):
    print("  MISSING non-screenshot:", m)
hashes = set(re.findall(r"commit `([0-9a-f]{7})`|`([0-9a-f]{7})`", text))
hs = sorted({h for pair in hashes for h in pair if h})
for h in hs:
    r = subprocess.run(["git", "cat-file", "-t", h], capture_output=True, text=True)
    print(f"  commit {h}: {r.stdout.strip() or 'NOT FOUND'}")
sys.exit(1 if other else 0)
