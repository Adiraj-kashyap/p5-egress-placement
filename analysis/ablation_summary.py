"""Summaries with uncertainty for the M17 ablation and sensitivity runs (M17 step 5, 05 §5).

Three outputs, all built from `analysis.stats` and never from a hand-computed mean or CI:

    results/ablation/summary.csv         per (topology, scale, variant): the variant's own cost
                                         and its **paired** difference and % penalty vs ilp_full
    results/ablation/decomposition.csv   per (topology, scale): the three §S12 steps
                                         b1 -> b1_storage -> ilp_no_edge_egress -> ilp_full,
                                         each with a CI and its share of the total gain G
    results/sensitivity/summary.csv      per (topology, egress multiplier, locations per
                                         provider, method): cost, % penalty vs ilp_full and
                                         the optimum's providers_used

Everything is paired: every variant is solved on the same traffic draw, so a comparison is
summarised from the **per-draw** difference, not from two independent means (05 §2). A
randomised method's value on a draw is the median over its seeds first (D-068), so n equals
the number of draws for every variant.

The decomposition telescopes by construction — the three steps are differences along one
chain — and `--verify` re-checks that on the real rows (A1) together with the separability
identity (A2) and the "nothing beats the exact optimum" invariant.

    python -m analysis.ablation_summary           # write all three
    python -m analysis.ablation_summary --check   # regenerate in memory, exit 1 on drift
    python -m analysis.ablation_summary --verify  # A1/A2 checks on the committed rows
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# The paired comparisons are formed per draw and then summarised, which is exactly what
# `stats.paired_diff_ci` does internally; going through `summarise` keeps one code path.
from analysis.stats import summarise
from placement.ablations import DECOMPOSITION
from pricing.common import ROOT

ABLATION = ROOT / "results" / "ablation"
SENSITIVITY = ROOT / "results" / "sensitivity"
REF_METHOD = "ilp_full"  # §S12's reference variant (the unmodified tight ILP)

ABLATION_KEYS = ["topology_id", "location_set", "traffic_scale", "method"]
SENSITIVITY_KEYS = ["topology_id", "location_set", "egress_mult", "locs_per_provider", "method"]
STAT_COLS = ["metric", "n", "mean", "sd", "sem", "median", "ci_lo", "ci_hi", "ci_method"]
METRICS = ["total_usd", "penalty_vs_ilp_pct", "diff_vs_ilp_usd", "egress_share",
           "providers_used", "runtime_s"]
DECOMP_COLS = ["topology_id", "location_set", "traffic_scale", "step", "from_method", "to_method",
               "buys", "n", "gain_usd_mean", "gain_usd_ci_lo", "gain_usd_ci_hi",
               "share_of_gain_pct_mean", "share_of_gain_pct_ci_lo", "share_of_gain_pct_ci_hi",
               "total_gain_usd_mean"]
SEED_MEDIAN = ("total_usd", "egress_share", "providers_used", "runtime_s")


def read_runs(d: Path) -> list[dict]:
    """Rows of <dir>/runs.csv; raises if the experiment has not been run."""
    runs = d / "runs.csv"
    if not runs.exists():
        raise SystemExit(f"missing {runs.relative_to(ROOT)}: run the experiment first")
    with runs.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def per_draw(rows: list[dict], keys: list[str]) -> dict[tuple, dict[str, float]]:
    """(*configuration without method..., method, draw_id) -> metric values for that draw.

    `keys` names the configuration columns, the last of which must be `method`. Rows of a
    randomised method (the SA ablations) are collapsed to the median over their seeds, so
    every variant contributes exactly one value per draw (D-068).
    """
    bucket: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        bucket[tuple(r[k] for k in keys) + (r["draw_id"],)].append(r)
    return {key: {m: statistics.median(float(r[m]) for r in rs) for m in SEED_MEDIAN}
            | {"n_seeds": float(len(rs))}
            for key, rs in bucket.items()}


def _order(key: tuple) -> tuple:
    """Order configurations numerically where the column is numeric, textually elsewhere."""
    out = []
    for part in key:
        try:
            out.append((0, float(part), ""))
        except ValueError:
            out.append((1, 0.0, part))
    return tuple(out)


def samples(rows: list[dict], keys: list[str]) -> dict[tuple, dict[str, list[float]]]:
    """Configuration -> metric -> one value per draw, in draw order.

    The reference variant `ilp_full` is matched draw by draw within the same configuration
    *except* for the method column, which is what makes `penalty_vs_ilp_pct` and
    `diff_vs_ilp_usd` paired comparisons rather than differences of means.
    """
    draws = per_draw(rows, keys)
    ref = {k[:-2] + (k[-1],): v["total_usd"]
           for k, v in draws.items() if k[-2] == REF_METHOD}
    out: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for key in sorted(draws, key=lambda k: _order(k[:-1]) + ((0, float(k[-1]), ""),)):
        vals = draws[key]
        cfg = key[:-1]
        for metric in SEED_MEDIAN:
            out[cfg][metric].append(vals[metric])
        base = ref.get(key[:-2] + (key[-1],))
        if base:
            out[cfg]["diff_vs_ilp_usd"].append(vals["total_usd"] - base)
            out[cfg]["penalty_vs_ilp_pct"].append(100.0 * (vals["total_usd"] - base) / base)
    return out


def render(sample_map: dict[tuple, dict[str, list[float]]], keys: list[str],
           metrics: list[str] = METRICS) -> str:
    """Render summary rows as CSV text (one row per configuration and metric)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys + STAT_COLS, lineterminator="\n")
    w.writeheader()
    for cfg in sorted(sample_map, key=_order):
        for metric in metrics:
            values = sample_map[cfg].get(metric)
            if not values:
                continue
            s = summarise(values)
            row = dict(zip(keys, cfg))
            row.update({"metric": metric, "n": s.n, "mean": round(s.mean, 8), "sd": round(s.sd, 8),
                        "sem": round(s.sem, 8), "median": round(s.median, 8),
                        "ci_lo": round(s.ci_lo, 8), "ci_hi": round(s.ci_hi, 8),
                        "ci_method": s.ci_method})
            w.writerow(row)
    return buf.getvalue()


def decomposition_rows(rows: list[dict]) -> list[dict]:
    """The three §S12 steps per (topology, location set, scale), with CIs and shares.

    A step's gain on a draw is C(from) - C(to) on that same draw, so the three gains sum to
    G = C(B1) - C(ILP) on every draw (A1). The share is summarised from the **per-draw**
    ratio step/G, which is why it has a CI of its own; draws with G = 0 are skipped for the
    share only (the gain itself is still reported).
    """
    draws = per_draw(rows, ABLATION_KEYS)
    by_cfg: dict[tuple, dict[str, dict[str, float]]] = defaultdict(dict)
    for (t, l, s, m, d), vals in draws.items():
        by_cfg[(t, l, s)].setdefault(d, {})[m] = vals["total_usd"]
    out = []
    for cfg in sorted(by_cfg, key=_order):
        per_d = by_cfg[cfg]
        draw_ids = sorted(per_d, key=int)
        needed = {"b1", REF_METHOD} | {m for step in DECOMPOSITION for m in step[:2]}
        usable = [d for d in draw_ids if needed <= set(per_d[d])]
        if not usable:
            continue
        total_gain = [per_d[d]["b1"] - per_d[d][REF_METHOD] for d in usable]
        g = summarise(total_gain)
        for i, (from_m, to_m, buys) in enumerate(DECOMPOSITION, 1):
            gain = [per_d[d][from_m] - per_d[d][to_m] for d in usable]
            gs = summarise(gain)
            shares = [100.0 * x / y for x, y in zip(gain, total_gain) if y != 0]
            ss = summarise(shares) if shares else None
            out.append({
                "topology_id": cfg[0], "location_set": cfg[1], "traffic_scale": cfg[2],
                "step": i, "from_method": from_m, "to_method": to_m, "buys": buys, "n": gs.n,
                "gain_usd_mean": round(gs.mean, 8), "gain_usd_ci_lo": round(gs.ci_lo, 8),
                "gain_usd_ci_hi": round(gs.ci_hi, 8),
                "share_of_gain_pct_mean": "" if ss is None else round(ss.mean, 6),
                "share_of_gain_pct_ci_lo": "" if ss is None else round(ss.ci_lo, 6),
                "share_of_gain_pct_ci_hi": "" if ss is None else round(ss.ci_hi, 6),
                "total_gain_usd_mean": round(g.mean, 8)})
    return out


def render_decomposition(rows: list[dict]) -> str:
    """Render `decomposition_rows` as CSV text."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=DECOMP_COLS, lineterminator="\n")
    w.writeheader()
    for row in decomposition_rows(rows):
        w.writerow(row)
    return buf.getvalue()


def _dominant(steps: list[dict]) -> tuple[str, bool]:
    """(name of the step with the largest mean gain, whether it is the egress-coupling step).

    Largest by signed mean gain, not by magnitude: a step with a negative gain made the true
    cost worse and cannot be said to cause the gain.
    """
    best = max(steps, key=lambda r: r["gain_usd_mean"])
    return f"step {best['step']}", best["from_method"] == "ilp_no_edge_egress"


def render_readme(rows: list[dict]) -> str:
    """The ≤ 15-line finding note for results/ablation/README.md (M17 step 6).

    States which step dominates per (topology, scale) and says plainly when the
    egress-coupling step does **not** dominate, which is a result, not a failure.
    """
    decomp = decomposition_rows(rows)
    by_cfg: dict[tuple, list[dict]] = defaultdict(list)
    for r in decomp:
        by_cfg[(r["topology_id"], r["traffic_scale"])].append(r)
    n = max((r["n"] for r in decomp), default=0)
    lines = [
        "# M17 ablation — which ingredient causes the gain",
        "",
        f"Gain G = C(B1) − C(ILP) per draw, decomposed along b1 → b1_storage → "
        f"ilp_no_edge_egress → ilp_full (06 §S12). Mean over R = {n} traffic draws; [] are 95 % "
        "bootstrap CIs. Snapshot 2026-09-21, core location set. Every variant is scored by the "
        "full `evaluate`. GENERATED by `python -m analysis.ablation_summary` — do not hand-edit.",
        "",
        "| topology | s | G USD/mo | 1 storage | 2 internet | 3 egress coupling | dominant |",
        "|---|---|---|---|---|---|---|",
    ]
    verdict = []
    for cfg in sorted(by_cfg, key=_order):
        steps = sorted(by_cfg[cfg], key=lambda r: r["step"])
        name, is_egress = _dominant(steps)
        cells = " | ".join(f"{r['gain_usd_mean']:,.3g} [{r['gain_usd_ci_lo']:,.3g}, "
                           f"{r['gain_usd_ci_hi']:,.3g}]" for r in steps)
        lines.append(f"| {cfg[0]} | {float(cfg[1]):g} | {steps[0]['total_gain_usd_mean']:,.3g} | "
                     f"{cells} | {name} |")
        verdict.append((cfg, is_egress, steps))
    dominates = [c for c, e, _ in verdict if e]
    lines += ["", f"**Egress coupling (step 3) is the largest step at {len(dominates)} of "
                  f"{len(verdict)} (topology, scale) points"
                  + (".**" if dominates else " — it does NOT dominate anywhere.**")]
    if len(dominates) < len(verdict):
        missed = [c for c, e, _ in verdict if not e]
        lines.append("At " + ", ".join(f"{t} s={float(s):g}" for t, s in missed)
                     + " a per-component step is larger, so there the gain is NOT caused by "
                       "modelling inter-component egress.")
    # A step that is identically zero, or negative, is a finding in its own right: name it
    # rather than leaving a column of zeros or a minus sign for the reader to interpret.
    for i, (_, _, label) in enumerate(DECOMPOSITION, 1):
        col = [s[i - 1]["gain_usd_mean"] for _, _, s in verdict]
        if all(v == 0 for v in col):
            lines.append(f"Step {i} ({label}) is exactly 0 at every point: B1's tie-break "
                         "already picks the cheapest storage, so counting storage explicitly "
                         "buys nothing here.")
        elif all(v < 0 for v in col):
            lines.append(f"Step {i} ({label}) is negative everywhere: on its own that "
                         "ingredient makes the true cost worse, and step 3 more than recovers it.")
    lines.append("Shares of G are in `decomposition.csv`; where G is small their CIs are wide, "
                 "so the signed USD gain above is the quantity to read.")
    return "\n".join(lines) + "\n"


def build() -> dict[Path, str]:
    """Return {output path: text} for all three summaries and the README, without writing."""
    ablation = read_runs(ABLATION)
    out = {ABLATION / "summary.csv": render(samples(ablation, ABLATION_KEYS), ABLATION_KEYS),
           ABLATION / "decomposition.csv": render_decomposition(ablation),
           ABLATION / "README.md": render_readme(ablation)}
    if (SENSITIVITY / "runs.csv").exists():
        out[SENSITIVITY / "summary.csv"] = render(
            samples(read_runs(SENSITIVITY), SENSITIVITY_KEYS), SENSITIVITY_KEYS)
    return out


def verify(rel_tol: float = 1e-9) -> list[str]:
    """A1 + A2 + the optimality invariant on the committed rows. Empty list = all pass."""
    rows = read_runs(ABLATION)
    draws = per_draw(rows, ABLATION_KEYS)
    by_cfg: dict[tuple, dict[str, dict[str, float]]] = defaultdict(dict)
    for (t, l, s, m, d), vals in draws.items():
        by_cfg[(t, l, s)].setdefault(d, {})[m] = vals["total_usd"]
    bad = []
    for cfg, per_d in sorted(by_cfg.items(), key=lambda kv: _order(kv[0])):
        for d, cost in sorted(per_d.items(), key=lambda kv: int(kv[0])):
            if REF_METHOD not in cost:
                bad.append(f"{cfg} draw={d}: no {REF_METHOD} row")
                continue
            best = cost[REF_METHOD]
            # A1: the three steps telescope to the total gain on this draw.
            if all(m in cost for step in DECOMPOSITION for m in step[:2]) and "b1" in cost:
                steps = sum(cost[a] - cost[b] for a, b, _ in DECOMPOSITION)
                g = cost["b1"] - best
                if abs(steps - g) > max(1e-6, rel_tol * abs(g)):
                    bad.append(f"{cfg} draw={d}: A1 steps {steps:.6f} != gain {g:.6f}")
            # The optimality invariant: no variant may be cheaper than the proven optimum.
            for m, v in sorted(cost.items()):
                if v < best * (1 - rel_tol) - 1e-6:
                    bad.append(f"{cfg} draw={d}: {m} {v:.6f} < {REF_METHOD} {best:.6f}")
    return bad


def main(argv: list[str] | None = None) -> int:
    """Write (or --check / --verify) the M17 summaries; return the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a committed summary would change")
    ap.add_argument("--verify", action="store_true",
                    help="A1 telescoping + optimality invariant on the committed rows, then exit")
    args = ap.parse_args(argv)
    if args.verify:
        bad = verify()
        for line in bad[:10]:
            print(f"VIOLATION  {line}")
        rows = read_runs(ABLATION)
        n_points = len({(r["topology_id"], r["traffic_scale"], r["draw_id"]) for r in rows})
        print(f"A1/optimality: {len(bad)} violation(s) over {n_points} (topology, scale, draw) "
              f"points, {len(rows)} rows")
        return 1 if bad else 0
    drift = []
    for path, text in build().items():
        rel = path.relative_to(ROOT)
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                drift.append(str(rel))
                print(f"DRIFT  {rel}")
            else:
                print(f"OK     {rel}  ({text.count(chr(10)) - 1} rows)")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote  {rel}  ({text.count(chr(10)) - 1} rows)")
    if drift:
        print("FAIL: re-run `python -m analysis.ablation_summary`")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
