"""Terminal views of the project for the live review (the `review/*.bat` launchers call this).

Every number comes from the same loaders and solvers the Streamlit walkthrough uses
(`demo.explain`, `demo.core`), so the terminal and the browser can never disagree.
No network calls, nothing written to disk.

Usage:  python -m demo.show {pricing,workloads,testbed,solve,sweep,verdicts} [options]
"""

from __future__ import annotations

import argparse
import sys

from demo import core, explain

TOPO_KEYS = {k.split()[0]: k for k in core.TOPOLOGIES}  # "T1" -> "T1 three-tier (measured)"


# --------------------------------------------------------------------------- printing

def say(text: str = "") -> None:
    print(text, flush=True)


def heading(text: str) -> None:
    say()
    say(text)
    say("-" * len(text))


def fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}" if abs(v) < 1 else f"{v:,.2f}"
    return "-" if v is None or v == "" else str(v)


def table(rows: list[dict], cols: list[str] | None = None) -> None:
    if not rows:
        say("  (no rows)")
        return
    cols = cols or list(rows[0])
    cells = [[fmt(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    say("  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    say("  " + "  ".join("-" * w for w in widths))
    for row in cells:
        say("  " + "  ".join(v.ljust(w) for v, w in zip(row, widths)))


def usd(x: float) -> str:
    return f"USD {x:,.2f}/month"


# --------------------------------------------------------------------------- views

def show_pricing(args) -> None:
    heading(f"Committed price snapshot: cost_model/{core.SNAPSHOT_DATE}/ (public price lists, no account)")
    table([{"table": k, "rows": v} for k, v in explain.price_row_counts().items()])

    heading(f"Compute: cheapest general-purpose shape per location ({args.locations} set)")
    table(sorted(explain.compute_prices(args.locations), key=lambda r: r["usd_per_vcpu_hour"]))

    heading("Data transfer (egress) rules: what one GB costs between two locations")
    table(explain.egress_rule_summary(args.locations))

    heading("Internet egress and object storage per location")
    table(explain.internet_storage_prices(args.locations))

    summary, checks = explain.validation_checks()
    heading(f"Cost-model validation ({explain.VALIDATION}): {summary}")
    table(checks, ["Check", "Description", "Result"])


def show_workloads(args) -> None:
    for key, label in TOPO_KEYS.items():
        topo = explain.topology(label)
        heading(f"{label}  ({core.TOPOLOGIES[label]})")
        say(f"  {topo.get('description', '')}")
        s = explain.topology_summary(topo)
        say(f"  {s['components']} components, {s['edges']} edges, {s['vcpu']} vCPU, "
            f"{s['edge_gb_month']:,.1f} GB/month between components, "
            f"{s['internet_gb_month']:,.1f} GB/month to the internet")
        say()
        table(topo["components"], ["id", "vcpu", "ram_gb", "storage_gb", "pinned_to"])
        say()
        table(sorted(topo["edges"], key=lambda e: -e["gb_per_month"]),
              ["src", "dst", "gb_per_month"])


def show_testbed(args) -> None:
    heading(f"Measured traffic on the kind testbed ({explain.MEASUREMENT})")
    say("  Bytes per request on every edge, from locust load runs against 4 pods on Kubernetes.")
    say("  cv_pct = coefficient of variation across runs (low = repeatable measurement).")
    say()
    table(explain.measurement_rows())


def _solve(label: str, scale: float, methods, locations: str) -> core.RunOutcome:
    inst = core.build_instance(core.TOPOLOGIES[label], locations, traffic_scale=scale)
    return core.run_methods(inst, methods=methods, traffic_scale=scale)


def show_solve(args) -> None:
    label = TOPO_KEYS[args.topology]
    methods = tuple(args.methods.split(","))
    heading(f"Live solve: {label}, {args.locations} locations, traffic scale s = {args.scale:g}")
    say("  Building the instance from the committed prices and topology, then running: "
        + ", ".join(core.METHODS[m] for m in methods))
    out = _solve(label, args.scale, methods, args.locations)

    heading("Where each method puts each component")
    table(core.placement_rows(out.instance, out.results))

    heading("Monthly bill per method (every bill scored by placement.cost.evaluate)")
    table(core.cost_rows(out), ["method", "total", "compute", "egress", "internet", "storage",
                                "providers_used", "penalty_vs_best_pct", "runtime_s", "note"])

    best = out.best
    heading("Reading it")
    say(f"  Cheapest: {best.label} at {usd(best.total)}.")
    pen = out.penalty_pct("b1")
    if pen is not None:
        say(f"  The egress-blind baseline B1 pays {pen:,.2f} % more than that.")


def show_sweep(args) -> None:
    label = TOPO_KEYS[args.topology]
    scales = [float(s) for s in args.scales.split(",")]
    heading(f"Traffic sweep on {label}: inter-component traffic multiplied by s")
    say("  Internet egress stays fixed; only component-to-component GB is scaled (as in the M15 sweep).")
    rows = []
    for s in scales:
        out = _solve(label, s, ("ilp_tight", "b1"), args.locations)
        ilp = next(r for r in out.results if r.method == "ilp_tight")
        b1 = next(r for r in out.results if r.method == "b1")
        rows.append({"s": f"{s:g}", "ILP USD/month": ilp.total, "ILP providers": ilp.cost.providers_used,
                     "B1 USD/month": b1.total, "B1 providers": b1.cost.providers_used,
                     "B1 penalty %": 100.0 * (b1.total - ilp.total) / ilp.total,
                     "ILP proven optimal": ilp.proven_optimal})
        say(f"  solved s = {s:g}")
    say()
    table(rows)


def show_verdicts(args) -> None:
    heading("Experiment runs behind the verdicts (rows in the committed results)")
    table([{"file": k, "rows": v} for k, v in explain.run_counts().items()])
    hyps, verdicts = explain.hypotheses(), explain.verdicts()
    for h in ("H1", "H2", "H3"):
        heading(f"{h}: {verdicts[h]['verdict']}")
        say("  Pre-registered: " + hyps[h].replace("**", ""))
        for b in explain.verdict_bullets(h):
            say("  * " + b.replace("**", ""))
    say()
    say(f"  Full text: {explain.VERDICTS}")


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--locations", choices=["core", "ext"], default="core")
    sub = ap.add_subparsers(dest="view", required=True)
    sub.add_parser("pricing")
    sub.add_parser("workloads")
    sub.add_parser("testbed")
    p = sub.add_parser("solve")
    p.add_argument("--topology", choices=list(TOPO_KEYS), default="T1")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--methods", default="ilp_tight,sa,greedy_1opt,b1,b2_best")
    p = sub.add_parser("sweep")
    p.add_argument("--topology", choices=list(TOPO_KEYS), default="T2")
    p.add_argument("--scales", default="0.01,0.1,1,10,100")
    sub.add_parser("verdicts")
    args = ap.parse_args(argv)
    {"pricing": show_pricing, "workloads": show_workloads, "testbed": show_testbed,
     "solve": show_solve, "sweep": show_sweep, "verdicts": show_verdicts}[args.view](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
