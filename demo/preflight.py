"""Pre-demo check list (§S13). Run it at T-30 min; every line must be a checkmark.

    python -m demo.preflight            # full, including Docker and the kind cluster
    python -m demo.preflight --offline  # skip everything that needs the testbed

Prints one OK/FAIL/WARN line per check and exits 1 if any *required* check failed. In
`--offline` mode the testbed checks are skipped entirely, so the demo can be rehearsed (and
CI-tested) on a machine with no Docker.
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The T3 ILP must stay well inside this on the demo machine (M20 A3).
T3_ILP_BUDGET_S = 5.0


class Checks:
    """Collects OK/WARN/FAIL lines and decides the exit code."""

    def __init__(self) -> None:
        self.failed = 0
        self.warned = 0

    def ok(self, name: str, detail: str = "") -> None:
        print(f"OK    {name}" + (f" - {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        print(f"FAIL  {name} - {detail}")

    def warn(self, name: str, detail: str) -> None:
        self.warned += 1
        print(f"WARN  {name} - {detail}")


def check_deps(ck: Checks) -> None:
    for mod in ("streamlit", "pulp", "matplotlib", "pandas", "numpy", "scipy"):
        try:
            m = importlib.import_module(mod)
            ck.ok(f"import {mod}", getattr(m, "__version__", ""))
        except Exception as exc:
            ck.fail(f"import {mod}", f"{type(exc).__name__}: {exc}")

    # locust is deliberately NOT imported (D-084): it monkey-patches gevent into the
    # process, which fails with a RecursionError once ssl has been imported (as streamlit
    # does). The demo only ever runs locust as a subprocess, so that is what is checked.
    from demo.testbed import _locust_path

    try:
        p = subprocess.run([_locust_path(), "--version"], capture_output=True, text=True,
                           timeout=60)
        if p.returncode == 0:
            ck.ok("locust executable", p.stdout.strip() or p.stderr.strip())
        else:
            ck.fail("locust executable", f"exited {p.returncode}")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        ck.fail("locust executable", f"{type(exc).__name__}: {exc}")


def check_data(ck: Checks) -> None:
    from demo import build_cache, core

    cm = ROOT / "cost_model" / core.SNAPSHOT_DATE
    missing = [f for f in ("compute.csv", "storage.csv", "egress.csv", "internet.csv")
               if not (cm / f).exists()]
    if missing:
        ck.fail("cost model", f"{cm.name}: missing {', '.join(missing)}")
    else:
        ck.ok("cost model", f"cost_model/{core.SNAPSHOT_DATE}/ complete")

    for label, path in core.TOPOLOGIES.items():
        if (ROOT / path).exists():
            ck.ok(f"topology {label}", path)
        else:
            ck.fail(f"topology {label}", f"{path} missing")

    import contextlib
    import io

    buf = io.StringIO()  # keep build_cache's own lines out of the check list
    with contextlib.redirect_stdout(buf):
        rc = build_cache.build(check=True)
    if rc == 0:
        n = len(core.cache_manifest().get("files", {}))
        ck.ok("demo cache", f"{n} cached CSVs match figures/")
    else:
        ck.fail("demo cache", buf.getvalue().strip().splitlines()[0]
                if buf.getvalue().strip() else "run `python -m demo.build_cache`")


def check_solve(ck: Checks) -> None:
    from demo import core

    t0 = time.perf_counter()
    try:
        inst = core.build_instance(core.TOPOLOGIES["T3 microservices"], "core")
        out = core.run_methods(inst, ("ilp_tight",))
        res = out.results[0]
    except Exception as exc:
        ck.fail("T3 ILP solve", f"{type(exc).__name__}: {exc}")
        return
    elapsed = time.perf_counter() - t0
    if res.note.startswith("FAILED"):
        ck.fail("T3 ILP solve", res.note)
    elif elapsed > T3_ILP_BUDGET_S:
        ck.fail("T3 ILP solve", f"{elapsed:.2f} s exceeds the {T3_ILP_BUDGET_S:g} s budget")
    else:
        ck.ok("T3 ILP solve", f"${res.total:,.2f}/mo in {elapsed:.2f} s "
                              f"({'proven optimal' if res.proven_optimal else res.note})")


def check_app_imports(ck: Checks) -> None:
    # Import the app module without launching a server: Streamlit tolerates this, and it
    # catches syntax errors and bad imports before the demo starts. Importing the app
    # outside `streamlit run` makes every widget log a "missing ScriptRunContext" warning,
    # so the streamlit loggers are silenced for the duration - this preflight must stay
    # readable at a glance.
    import logging

    quiet = [logging.getLogger(n) for n in ("streamlit", "streamlit.runtime")]
    levels = [lg.level for lg in quiet]
    for lg in quiet:
        lg.setLevel(logging.CRITICAL)
    try:
        importlib.import_module("demo.app")
        ck.ok("demo/app.py imports", "no server started")
    except Exception as exc:
        ck.fail("demo/app.py imports", f"{type(exc).__name__}: {exc}")
    finally:
        for lg, lvl in zip(quiet, levels):
            lg.setLevel(lvl)


def check_testbed(ck: Checks) -> None:
    from demo import testbed

    try:
        p = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=30)
        if p.returncode == 0:
            ck.ok("docker engine", p.stdout.strip())
        else:
            ck.fail("docker engine", (p.stderr or "not running").strip().splitlines()[-1])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        ck.fail("docker engine", f"{type(exc).__name__}: {exc}")

    status = testbed.cluster_status()
    if status.ready:
        ck.ok("kind cluster p5", status.message)
    elif status.ok:
        ck.fail("kind cluster p5", status.message)
    else:
        ck.fail("kind cluster p5", status.message + " (fallback: Use cached measurement)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true",
                    help="skip the Docker and kind cluster checks")
    args = ap.parse_args(argv)

    ck = Checks()
    print(f"P5 demo preflight ({'offline' if args.offline else 'full'})")
    check_deps(ck)
    check_data(ck)
    check_solve(ck)
    check_app_imports(ck)
    if args.offline:
        print("SKIP  docker engine, kind cluster p5 (--offline)")
    else:
        check_testbed(ck)

    print(f"\n{ck.failed} failed, {ck.warned} warning(s)")
    if ck.failed:
        print("Not ready. Fix the FAIL lines above, or run the demo with cached measurements.")
    else:
        print("Ready.")
    return 1 if ck.failed else 0


if __name__ == "__main__":
    sys.exit(main())
