"""
P5 environment verification.

Run this and screenshot the output. This is testbed evidence artefact #1.
It proves the solver is installed and actually solves, not just imports.

The smoke model is exposed as :func:`run_smoke_model` so that `tests/test_env.py`
can assert on it without re-running the printing wrapper.

Usage:  python verify_env.py
"""
import platform
import subprocess
import sys
import time
from typing import Any, Dict

import pulp

# Deliberately rigged so that the egress-blind answer is wrong.
# L2 has the cheapest compute, but reaching it from L0 costs a lot per GB.
COMPUTE = {("A", "L0"): 80,  ("A", "L1"): 120, ("A", "L2"): 100,
           ("B", "L0"): 100, ("B", "L1"): 110, ("B", "L2"): 85,
           ("C", "L0"): 100, ("C", "L1"): 115, ("C", "L2"): 88}
EGRESS = {("L0", "L0"): 0.0, ("L0", "L1"): 0.02, ("L0", "L2"): 0.09,
          ("L1", "L0"): 0.02, ("L1", "L1"): 0.0, ("L1", "L2"): 0.09,
          ("L2", "L0"): 0.09, ("L2", "L1"): 0.09, ("L2", "L2"): 0.0}
TRAFFIC = {("A", "B"): 800, ("B", "C"): 600}
COMPONENTS = ["A", "B", "C"]
LOCATIONS = ["L0", "L1", "L2"]


def run_smoke_model() -> Dict[str, Any]:
    """Solve the 3-component, 3-location egress-coupled placement smoke model.

    Builds the exact ILP over the rigged constants above, linearising the
    product of the two assignment variables on each traffic edge, solves it with
    CBC, and also computes the egress-blind greedy answer (cheapest compute per
    component) for comparison. Returns the status, objective, placements,
    the blind cost, the penalty of ignoring egress as a percentage, the solve
    time and the model size. Raises nothing; callers assert on the result.
    """
    m = pulp.LpProblem("smoke", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", (COMPONENTS, LOCATIONS), cat="Binary")
    y = pulp.LpVariable.dicts("y", (TRAFFIC.keys(), LOCATIONS, LOCATIONS), lowBound=0)

    m += (pulp.lpSum(COMPUTE[(c, l)] * x[c][l] for c in COMPONENTS for l in LOCATIONS)
          + pulp.lpSum(TRAFFIC[(u, v)] * EGRESS[(l, mm)] * y[(u, v)][l][mm]
                       for (u, v) in TRAFFIC for l in LOCATIONS for mm in LOCATIONS))

    for c in COMPONENTS:
        m += pulp.lpSum(x[c][l] for l in LOCATIONS) == 1
    for (u, v) in TRAFFIC:                       # linearise x[u][l] * x[v][m]
        for l in LOCATIONS:
            for mm in LOCATIONS:
                m += y[(u, v)][l][mm] >= x[u][l] + x[v][mm] - 1
                m += y[(u, v)][l][mm] <= x[u][l]
                m += y[(u, v)][l][mm] <= x[v][mm]

    t0 = time.time()
    status = m.solve(pulp.PULP_CBC_CMD(msg=False))
    elapsed = time.time() - t0

    placement = {c: next(l for l in LOCATIONS if x[c][l].value() > 0.5) for c in COMPONENTS}
    blind = {c: min(LOCATIONS, key=lambda l: COMPUTE[(c, l)]) for c in COMPONENTS}
    blind_cost = (sum(COMPUTE[(c, blind[c])] for c in COMPONENTS)
                  + sum(TRAFFIC[(u, v)] * EGRESS[(blind[u], blind[v])] for (u, v) in TRAFFIC))
    objective = pulp.value(m.objective)

    return {
        "status": pulp.LpStatus[status],
        "objective": objective,
        "placement": placement,
        "blind_cost": blind_cost,
        "blind_placement": blind,
        "penalty_pct": (blind_cost - objective) / objective * 100,
        "elapsed_s": elapsed,
        "n_variables": len(m.variables()),
        "n_constraints": len(m.constraints),
    }


def main() -> int:
    """Print the environment report and the smoke-model result; return an exit code."""
    print("=" * 68)
    print("P5 ENVIRONMENT VERIFICATION")
    print("=" * 68)
    print(f"timestamp   : {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"python      : {sys.version.split()[0]}")
    print(f"platform    : {platform.platform()}")

    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      stderr=subprocess.DEVNULL).decode().strip()
        print(f"git commit  : {sha}")
    except Exception:
        print("git commit  : (not a git repo yet - run 'git init && git commit')")

    print(f"pulp        : {pulp.__version__}")
    print(f"solvers     : {pulp.listSolvers(onlyAvailable=True)}")

    assert "PULP_CBC_CMD" in pulp.listSolvers(onlyAvailable=True), \
        "CBC not available - reinstall pulp"

    print("-" * 68)
    print("SOLVER SMOKE TEST: 3 components, 3 locations, egress-coupled objective")
    print("-" * 68)

    r = run_smoke_model()

    print(f"status              : {r['status']}")
    print(f"solve time          : {r['elapsed_s']:.3f} s")
    print(f"variables / constr. : {r['n_variables']} / {r['n_constraints']}")
    print(f"egress-aware optimum: {r['objective']:.2f}   {r['placement']}")
    print(f"egress-blind greedy : {r['blind_cost']:.2f}   {r['blind_placement']}")
    print(f"penalty of ignoring egress: {r['penalty_pct']:.1f}%")
    print("=" * 68)
    print("ENVIRONMENT OK" if r["status"] == "Optimal" else "ENVIRONMENT FAILED")
    print("=" * 68)
    return 0 if r["status"] == "Optimal" else 1


if __name__ == "__main__":
    sys.exit(main())
