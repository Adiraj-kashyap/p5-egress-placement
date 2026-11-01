"""
Sanity-check the cost model (03_SKILLS §S5) and write cost_model/<date>/validation.md.

Checks (each PASS/FAIL):
  V1  compute.csv has 24 locations x 4 shapes = 96 rows, no duplicates
  V2  egress.csv has 24 x 24 = 576 directed cells, one per ordered pair
  V3  egress diagonal (R1) is 0 everywhere
  V4  every price in every table is a finite, non-negative number (no NaN)
  V5  for each shape, max/min price across the 12 core locations < 3x
  V6  GCP composed price within 0.5x-2x of the AWS price in the matched region
  V7  the matrix is asymmetric somewhere (egress[a][b] != egress[b][a])
  V8  fallback cells <= 25% of R2 cells
  V9  every egress cell has a rule in {R1, R2, R3} consistent with its endpoints, and a source
  V10 internet.csv and storage.csv have one row per ext location, all prices > 0

Exit status is 1 if any check fails.

Usage:  python -m pricing.validate_cost_model      (honours P5_SNAPSHOT_DATE)
"""
import csv
import math
import statistics
import sys
from pathlib import Path

from pricing.common import LOCATIONS_CORE, LOCATIONS_EXT, ROOT, SNAPSHOT_DATE

CM_DIR = ROOT / "cost_model" / SNAPSHOT_DATE
SHAPE_ORDER = ["small", "medium", "large", "xlarge"]
MAX_SPREAD = 3.0
GCP_AWS_BAND = (0.5, 2.0)
MAX_FALLBACK_SHARE = 0.25

# GCP region -> the AWS region it is the geographic analogue of (same position in LOCATIONS_EXT).
MATCHED_AWS = dict(zip(LOCATIONS_EXT["gcp"], LOCATIONS_EXT["aws"]))


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def run_checks(compute, storage, egress, internet):
    """Return (checks, stats). checks = list of (id, description, passed, detail)."""
    checks = []
    ext = {(p, r) for p, rs in LOCATIONS_EXT.items() for r in rs}
    core = {(p, r) for p, rs in LOCATIONS_CORE.items() for r in rs}

    keys = [(c["provider"], c["region"], c["shape"]) for c in compute]
    ok = (len(compute) == len(ext) * 4 and len(set(keys)) == len(keys)
          and {(p, r) for p, r, _ in keys} == ext)
    checks.append(("V1", "compute.csv = 24 locations x 4 shapes = 96 rows", ok,
                   f"{len(compute)} rows, {len(set(keys))} distinct"))

    pairs = [((e["src_provider"], e["src_region"]), (e["dst_provider"], e["dst_region"]))
             for e in egress]
    ok = len(egress) == len(ext) ** 2 and set(pairs) == {(a, b) for a in ext for b in ext}
    checks.append(("V2", "egress.csv = 24 x 24 = 576 directed cells", ok,
                   f"{len(egress)} rows, {len(set(pairs))} distinct ordered pairs"))

    rate = {pr: _num(e["usd_per_gb"]) for pr, e in zip(pairs, egress)}
    diag = [rate[(a, a)] for a in ext if (a, a) in rate]
    ok = len(diag) == len(ext) and all(v == 0.0 for v in diag)
    checks.append(("V3", "egress diagonal is 0", ok, f"{sum(v == 0.0 for v in diag)}/{len(ext)} zero"))

    bad = []
    for name, rows, col in (("compute", compute, "usd_per_hour"), ("compute", compute, "usd_per_month"),
                            ("storage", storage, "usd_per_gb_month"), ("egress", egress, "usd_per_gb"),
                            ("internet", internet, "usd_per_gb")):
        bad += [f"{name}.{col}[{i}]={r[col]!r}" for i, r in enumerate(rows)
                if _num(r[col]) is None or _num(r[col]) < 0]
    checks.append(("V4", "all prices finite and non-negative (no NaN)", not bad,
                   "0 bad values" if not bad else "; ".join(bad[:5])))

    spread = {}
    for s in SHAPE_ORDER:
        prices = [float(c["usd_per_hour"]) for c in compute
                  if c["shape"] == s and (c["provider"], c["region"]) in core]
        spread[s] = (min(prices), max(prices), max(prices) / min(prices), len(prices))
    ok = all(v[2] < MAX_SPREAD and v[3] == len(core) for v in spread.values())
    checks.append(("V5", f"per shape, max/min over 12 core locations < {MAX_SPREAD:g}x", ok,
                   ", ".join(f"{s} {v[2]:.3f}x" for s, v in spread.items())))

    price = {(c["provider"], c["region"], c["shape"]): float(c["usd_per_hour"]) for c in compute}
    ratios = [price[("gcp", g, s)] / price[("aws", a, s)]
              for g, a in MATCHED_AWS.items() for s in SHAPE_ORDER]
    ok = all(GCP_AWS_BAND[0] <= x <= GCP_AWS_BAND[1] for x in ratios)
    checks.append(("V6", "GCP composed / AWS matched-region price within 0.5x-2x", ok,
                   f"{len(ratios)} ratios, range {min(ratios):.3f}-{max(ratios):.3f}"))

    asym = sum(1 for (a, b), v in rate.items() if a < b and rate.get((b, a)) != v)
    checks.append(("V7", "matrix is asymmetric where prices differ by sender", asym > 0,
                   f"{asym} unordered pairs with egress[a][b] != egress[b][a]"))

    r2 = [e for e in egress if e["rule"] == "R2"]
    fb = [e for e in r2 if e["source"].startswith("fallback:")]
    share = len(fb) / len(r2) if r2 else 1.0
    checks.append(("V8", "fallback cells <= 25% of R2 cells", share <= MAX_FALLBACK_SHARE,
                   f"{len(fb)}/{len(r2)} R2 cells = {share:.1%}"))

    wrong = []
    for (a, b), e in zip(pairs, egress):
        expect = "R1" if a == b else "R2" if a[0] == b[0] else "R3"
        if e["rule"] != expect or not e["source"]:
            wrong.append(f"{a}->{b} rule={e['rule']}")
    checks.append(("V9", "rule matches endpoints (R1/R2/R3) and every cell has a source", not wrong,
                   f"{len(wrong)} mismatches" + (": " + "; ".join(wrong[:3]) if wrong else "")))

    ok = True
    for rows, col in ((internet, "usd_per_gb"), (storage, "usd_per_gb_month")):
        locs = [(r["provider"], r["region"]) for r in rows]
        ok &= len(locs) == len(ext) and set(locs) == ext and all((_num(r[col]) or 0) > 0 for r in rows)
    checks.append(("V10", "internet.csv and storage.csv: one positive price per ext location", ok,
                   f"internet {len(internet)} rows, storage {len(storage)} rows"))

    stats = {"spread": spread, "fallback": (len(fb), len(r2)), "egress_by_rule": {},
             "compute_ext": {}, "storage": {}, "internet": {}}
    for rule in ("R1", "R2", "R3"):
        v = [float(e["usd_per_gb"]) for e in egress if e["rule"] == rule]
        stats["egress_by_rule"][rule] = (len(v), min(v), statistics.median(v), max(v))
    for s in SHAPE_ORDER:
        for p in LOCATIONS_EXT:
            v = [float(c["usd_per_hour"]) for c in compute if c["shape"] == s and c["provider"] == p]
            stats["compute_ext"][(s, p)] = (min(v), statistics.median(v), max(v))
    for p in LOCATIONS_EXT:
        v = [float(r["usd_per_gb_month"]) for r in storage if r["provider"] == p]
        stats["storage"][p] = (min(v), statistics.median(v), max(v))
        v = [float(r["usd_per_gb"]) for r in internet if r["provider"] == p]
        stats["internet"][p] = (min(v), statistics.median(v), max(v))
    return checks, stats


def render(checks, stats, date):
    n_pass = sum(c[2] for c in checks)
    out = [f"# Cost model validation — snapshot {date}", "",
           "Generated by `python -m pricing.validate_cost_model`. Do not edit by hand.", "",
           f"**Result: {n_pass}/{len(checks)} checks PASS"
           f"{'' if n_pass == len(checks) else ' — FAILURES PRESENT'}.**", "",
           "| Check | Description | Result | Detail |", "|---|---|---|---|"]
    out += [f"| {i} | {d} | {'PASS' if ok else 'FAIL'} | {det} |" for i, d, ok, det in checks]
    fb, r2 = stats["fallback"]
    out += ["", f"Fallback cells: **{fb}** of {r2} R2 cells (R1 and R3 never use fallbacks).", "",
            "## Compute price spread over the 12 core locations (USD/hour)", "",
            "| Shape | Min | Max | Max/Min |", "|---|---|---|---|"]
    out += [f"| {s} | {v[0]:.4f} | {v[1]:.4f} | {v[2]:.3f} |" for s, v in stats["spread"].items()]
    out += ["", "## Compute price per provider over the 8 ext regions (USD/hour: min / median / max)", "",
            "| Shape | aws | azure | gcp |", "|---|---|---|---|"]
    for s in SHAPE_ORDER:
        cells = [" / ".join(f"{x:.4f}" for x in stats["compute_ext"][(s, p)]) for p in LOCATIONS_EXT]
        out.append(f"| {s} | " + " | ".join(cells) + " |")
    out += ["", "## Egress matrix by rule (USD/GB)", "",
            "| Rule | Cells | Min | Median | Max |", "|---|---|---|---|---|"]
    out += [f"| {r} | {v[0]} | {v[1]:.4f} | {v[2]:.4f} | {v[3]:.4f} |"
            for r, v in stats["egress_by_rule"].items()]
    out += ["", "## Internet egress and object storage per provider (min / median / max)", "",
            "| Provider | Internet USD/GB | Storage USD/GB-month |", "|---|---|---|"]
    for p in LOCATIONS_EXT:
        out.append(f"| {p} | " + " / ".join(f"{x:.4f}" for x in stats["internet"][p]) + " | "
                   + " / ".join(f"{x:.4f}" for x in stats["storage"][p]) + " |")
    return "\n".join(out) + "\n"


def main(cm_dir=CM_DIR):
    tables = {n: read_csv(Path(cm_dir) / f"{n}.csv") for n in ("compute", "storage", "egress", "internet")}
    checks, stats = run_checks(tables["compute"], tables["storage"], tables["egress"], tables["internet"])
    for i, d, ok, det in checks:
        print(f"{i:<4} {'PASS' if ok else 'FAIL'}  {d}  [{det}]")
    for r, v in stats["egress_by_rule"].items():
        print(f"egress {r}: cells={v[0]} min={v[1]:.4f} median={v[2]:.4f} max={v[3]:.4f}")
    path = Path(cm_dir) / "validation.md"
    path.write_text(render(checks, stats, Path(cm_dir).name), encoding="utf-8")
    print(f"WROTE {path.relative_to(ROOT).as_posix()}  {sum(c[2] for c in checks)}/{len(checks)} PASS")
    return 0 if all(c[2] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
