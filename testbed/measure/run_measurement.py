"""M07 step 6: drive locust against the kind testbed and record per-edge bytes per run.

For each run: zero the app counters in web and api (api also flushes redis, so every run
starts from a cold cache), read eth0 rx/tx in all four pods, run locust headless at a fixed
user count, then read the counters and eth0 again. Writes one row per directed edge per run
to ``runs.csv`` and one row per pod per run to ``runs_interface.csv``.

Edge mapping (T1 component ids): web's ``api`` counter gives web->api (sent) and api->web
(received); web's ``client`` counter gives web->internet and internet->web; api's ``cache``
and ``db`` counters give api->cache, cache->api, api->db, db->api. api's ``web`` counter is
the api-side view of the web<->api edge and is kept as a cross-check (``api_side_bytes``).

Needs kubectl on PATH with KUBECONFIG pointing at cluster p5 and locust in the venv. Run
from the repo root (one 10-minute run per chunk, D-022):
    python -m testbed.measure.run_measurement --runs 1 --first-run 1 --duration 600
    (then --first-run 2, then --first-run 3)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("run_measurement")

NAMESPACE = "p5"
PODS = ("web", "api", "cache", "db")
# (src, dst, service whose counter is read, peer key, field)
EDGES = (
    ("web", "api", "web", "api", "bytes_sent"),
    ("api", "web", "web", "api", "bytes_received"),
    ("api", "cache", "api", "cache", "bytes_sent"),
    ("cache", "api", "api", "cache", "bytes_received"),
    ("api", "db", "api", "db", "bytes_sent"),
    ("db", "api", "api", "db", "bytes_received"),
    ("web", "internet", "web", "client", "bytes_sent"),
    ("internet", "web", "web", "client", "bytes_received"),
)
# api's own view of the web<->api edge, for the cross-check column
API_SIDE = {("web", "api"): "bytes_received", ("api", "web"): "bytes_sent"}
# app-layer peers whose bytes cross each pod's eth0
POD_APP_EDGES = {
    "web": (("web", "api"), ("web", "client")),
    "api": (("api", "web"), ("api", "cache"), ("api", "db")),
    "cache": (("api", "cache"),),
    "db": (("api", "db"),),
}
RUN_FIELDS = ["run_id", "seed", "started_utc", "duration_s", "users", "spawn_rate",
              "locust_requests", "locust_failures", "failure_rate", "served_requests",
              "src", "dst", "app_bytes", "bytes_per_request", "api_side_bytes"]
IFACE_FIELDS = ["run_id", "pod", "rx_bytes", "tx_bytes", "iface_bytes", "app_bytes",
                "app_iface_ratio"]


def kubectl_exec(deploy: str, *cmd: str) -> str:
    """Run a command in the first pod of ``deploy`` and return its stdout."""
    out = subprocess.run(["kubectl", "-n", NAMESPACE, "exec", f"deploy/{deploy}", "--", *cmd],
                         capture_output=True, text=True, timeout=60, check=True)
    return out.stdout


def http_local(deploy: str, path: str, post: bool = False) -> dict:
    """GET or POST ``http://localhost:8000<path>`` inside the pod (loopback, not eth0)."""
    method = "POST" if post else "GET"
    code = ("import urllib.request;r=urllib.request.Request('http://localhost:8000%s',"
            "data=b'' if '%s'=='POST' else None,method='%s');"
            "print(urllib.request.urlopen(r).read().decode())" % (path, method, method))
    return json.loads(kubectl_exec(deploy, "python", "-c", code))


def read_eth0(deploy: str) -> tuple[int, int]:
    """Return (rx_bytes, tx_bytes) of eth0 in the pod."""
    rx, tx = kubectl_exec(deploy, "cat", "/sys/class/net/eth0/statistics/rx_bytes",
                          "/sys/class/net/eth0/statistics/tx_bytes").split()
    return int(rx), int(tx)


def locust_totals(stats_csv: Path) -> tuple[int, int]:
    """Return (requests, failures) from the Aggregated row of a locust ``_stats.csv``."""
    with stats_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["Name"] == "Aggregated":
                return int(row["Request Count"]), int(row["Failure Count"])
    raise ValueError(f"no Aggregated row in {stats_csv}")


def edge_rows(run: dict, web: dict, api: dict) -> list[dict]:
    """Build the per-edge rows of one run from the two /metrics.json snapshots."""
    snaps = {"web": web, "api": api}
    served = web["requests"]
    rows = []
    for src, dst, svc, peer, field in EDGES:
        b = snaps[svc]["edges"].get(peer, {}).get(field, 0)
        side = API_SIDE.get((src, dst))
        rows.append({**run, "served_requests": served, "src": src, "dst": dst, "app_bytes": b,
                     "bytes_per_request": round(b / served, 3) if served else "",
                     "api_side_bytes": api["edges"].get("web", {}).get(side, 0) if side else ""})
    return rows


def iface_rows(run_id: str, before: dict, after: dict, web: dict, api: dict) -> list[dict]:
    """Build the per-pod interface cross-check rows of one run."""
    snaps = {"web": web, "api": api}
    rows = []
    for pod in PODS:
        rx = after[pod][0] - before[pod][0]
        tx = after[pod][1] - before[pod][1]
        app = sum(e["bytes_sent"] + e["bytes_received"]
                  for svc, peer in POD_APP_EDGES[pod]
                  for e in [snaps[svc]["edges"].get(peer, {"bytes_sent": 0, "bytes_received": 0})])
        rows.append({"run_id": run_id, "pod": pod, "rx_bytes": rx, "tx_bytes": tx,
                     "iface_bytes": rx + tx, "app_bytes": app,
                     "app_iface_ratio": round(app / (rx + tx), 4) if rx + tx else ""})
    return rows


def one_run(run_id: str, seed: int, args: argparse.Namespace, work: Path) -> tuple[list, list]:
    """Execute one measured load run and return (edge rows, interface rows)."""
    http_local("web", "/reset", post=True)
    http_local("api", "/reset?flush_cache=true", post=True)
    before = {p: read_eth0(p) for p in PODS}
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    prefix = work / run_id
    cmd = [str(Path(sys.executable).with_name("locust")), "-f", "testbed/load/locustfile.py",
           "--headless", "-u", str(args.users), "-r", str(args.spawn_rate),
           "-t", f"{args.duration}s", "--host", args.host, "--csv", str(prefix),
           "--only-summary", "--loglevel", "WARNING"]
    log.info("run %s seed %d: %s", run_id, seed, " ".join(cmd))
    # D-022: long runs at BelowNormal priority on the laptop
    flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    with (work / f"{run_id}_locust.txt").open("w", encoding="utf-8") as out:
        rc = subprocess.run(cmd, env={**os.environ, "LOCUST_SEED": str(seed)},
                            stdout=out, stderr=subprocess.STDOUT, creationflags=flags).returncode
    web = http_local("web", "/metrics.json")
    api = http_local("api", "/metrics.json")
    after = {p: read_eth0(p) for p in PODS}
    duration = time.monotonic() - t0
    reqs, fails = locust_totals(Path(f"{prefix}_stats.csv"))
    log.info("run %s done: locust rc=%d requests=%d failures=%d served=%d in %.1f s",
             run_id, rc, reqs, fails, web["requests"], duration)
    run = {"run_id": run_id, "seed": seed, "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "duration_s": round(duration, 1), "users": args.users, "spawn_rate": args.spawn_rate,
           "locust_requests": reqs, "locust_failures": fails,
           "failure_rate": round(fails / reqs, 6) if reqs else ""}
    return edge_rows(run, web, api), iface_rows(run_id, before, after, web, api)


def merge_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Write ``rows`` to ``path``, keeping existing rows of runs not in ``rows``, by run_id."""
    new_ids = {r["run_id"] for r in rows}
    kept = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            kept = [r for r in csv.DictReader(f) if r["run_id"] not in new_ids]
    write_csv(path, fields, sorted(kept + rows, key=lambda r: r["run_id"]))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Write ``rows`` to ``path`` with a header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, execute the runs and write the two CSV files."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--duration", type=int, default=600, help="seconds of load per run")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--spawn-rate", type=int, default=5)
    ap.add_argument("--first-run", type=int, default=1,
                    help="index of the first run; runs are r<first>..r<first+runs-1> and are "
                         "merged into existing CSVs, so runs can be done in separate chunks")
    ap.add_argument("--seed", type=int, default=7, help="run k uses seed + k - 1")
    ap.add_argument("--host", default="http://127.0.0.1:30080")
    ap.add_argument("--out-dir", default="testbed/measurements")
    ap.add_argument("--work-dir", default="logs/M07_locust", help="raw locust output")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    edges, ifaces = [], []
    for k in range(args.first_run, args.first_run + args.runs):
        e, i = one_run(f"r{k}", args.seed + k - 1, args, work)
        edges += e
        ifaces += i
    out = Path(args.out_dir)
    merge_csv(out / "runs.csv", RUN_FIELDS, edges)
    merge_csv(out / "runs_interface.csv", IFACE_FIELDS, ifaces)
    log.info("wrote %d edge rows and %d interface rows to %s", len(edges), len(ifaces), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
