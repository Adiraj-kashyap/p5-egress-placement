"""Live-testbed wrappers for the demo: kubectl and locust behind timeouts that never raise.

Every function here returns a small result object with `ok` and a human-readable `message`.
A missing binary, a dead cluster, a timeout or a non-zero exit code all come back as
`ok=False` with an explanation — the demo must degrade to the cached measurement, never
show a traceback on the projector (M20 step 3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from demo.core import ROOT, cached_measurement

NAMESPACE = "p5"
PODS = ("web", "api", "cache", "db")
DEFAULT_HOST = "http://127.0.0.1:30080"  # NodePort, not port-forward (D-035)

#: Same (src, dst, service, peer, field) mapping as `testbed.measure.run_measurement`, so a
#: demo measurement and an M07 measurement mean exactly the same thing.
EDGES = (
    ("web", "api", "web", "api", "bytes_sent"),
    ("api", "web", "web", "api", "bytes_received"),
    ("api", "cache", "api", "cache", "bytes_sent"),
    ("cache", "api", "api", "cache", "bytes_received"),
    ("api", "db", "api", "db", "bytes_sent"),
    ("db", "api", "api", "db", "bytes_received"),
)
CLIENT_EDGE = ("web", "client", "bytes_sent")  # web -> internet


@dataclass
class Status:
    """Result of a cluster probe."""

    ok: bool
    message: str
    pods: list[dict] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True when all four expected pods exist and are Running."""
        names = {p["name"].split("-")[0] for p in self.pods}
        return self.ok and set(PODS) <= names and all(p["phase"] == "Running" for p in self.pods)


@dataclass
class Measurement:
    """Per-edge bytes/request, either measured live or taken from the committed M07 run."""

    ok: bool
    source: str  # "live" | "cached"
    message: str
    bytes_per_request: dict[tuple[str, str], float] = field(default_factory=dict)
    internet_bytes: float | None = None
    served_requests: int = 0
    duration_s: float = 0.0


def _run(cmd: list[str], timeout: float) -> tuple[bool, str, str]:
    """Run `cmd`, returning (ok, stdout, message). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "", f"{cmd[0]} is not on PATH"
    except subprocess.TimeoutExpired:
        return False, "", f"{cmd[0]} timed out after {timeout:g} s"
    except OSError as exc:
        return False, "", f"{cmd[0]} could not be started: {exc}"
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        return False, p.stdout, f"{cmd[0]} exited {p.returncode}: {tail[-1] if tail else 'no output'}"
    return True, p.stdout, "ok"


def cluster_status(timeout: float = 15.0) -> Status:
    """Probe `kubectl get pods -n p5`. Returns ok=False with a reason if anything is wrong."""
    ok, out, msg = _run(["kubectl", "-n", NAMESPACE, "get", "pods", "-o", "json"], timeout)
    if not ok:
        return Status(False, f"Cluster not reachable: {msg}")
    try:
        items = json.loads(out).get("items", [])
    except json.JSONDecodeError:
        return Status(False, "Cluster not reachable: kubectl returned unparsable JSON")
    pods = [{"name": i["metadata"]["name"], "phase": i["status"].get("phase", "?"),
             "ready": all(c.get("ready") for c in i["status"].get("containerStatuses", []) or [{}])}
            for i in items]
    if not pods:
        return Status(False, f"Namespace {NAMESPACE} has no pods - apply testbed/k8s/", pods)
    running = sum(p["phase"] == "Running" for p in pods)
    return Status(True, f"{running}/{len(pods)} pods Running in namespace {NAMESPACE}", pods)


def _pod_json(deploy: str, path: str, post: bool = False, timeout: float = 60.0) -> tuple[bool, dict, str]:
    """GET/POST an endpoint on pod loopback via `kubectl exec` and parse the JSON reply."""
    method = "POST" if post else "GET"
    code = ("import urllib.request,json;r=urllib.request.Request('http://localhost:8000%s',"
            "data=b'' if '%s'=='POST' else None,method='%s');"
            "print(urllib.request.urlopen(r).read().decode())" % (path, method, method))
    ok, out, msg = _run(["kubectl", "-n", NAMESPACE, "exec", f"deploy/{deploy}", "--",
                         "python", "-c", code], timeout)
    if not ok:
        return False, {}, msg
    try:
        return True, json.loads(out), "ok"
    except json.JSONDecodeError:
        return False, {}, f"{deploy} returned unparsable JSON from {path}"


def _locust_path() -> str:
    return str(Path(sys.executable).with_name("locust"))


def measure(duration_s: int = 60, users: int = 20, spawn_rate: int = 5,
            host: str = DEFAULT_HOST, seed: int = 42,
            work_dir: str | Path | None = None) -> Measurement:
    """Reset the counters, run locust headless for `duration_s`, and read the per-edge bytes.

    Returns `ok=False` with a message on any failure; the caller then offers the cached
    measurement. The locust timeout is `duration_s` plus 90 s of slack for start-up and
    shutdown.
    """
    status = cluster_status()
    if not status.ready:
        return Measurement(False, "live", status.message or "cluster not ready")

    for deploy, path in (("web", "/reset"), ("api", "/reset?flush_cache=true")):
        ok, _, msg = _pod_json(deploy, path, post=True)
        if not ok:
            return Measurement(False, "live", f"could not reset {deploy}: {msg}")

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="p5_demo_"))
    work.mkdir(parents=True, exist_ok=True)
    prefix = work / "demo"
    cmd = [_locust_path(), "-f", "testbed/load/locustfile.py", "--headless",
           "-u", str(users), "-r", str(spawn_rate), "-t", f"{duration_s}s",
           "--host", host, "--csv", str(prefix), "--only-summary", "--loglevel", "WARNING"]
    t0 = time.monotonic()
    try:
        flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)  # D-022
        with (work / "locust.txt").open("w", encoding="utf-8") as out:
            subprocess.run(cmd, cwd=ROOT, env={**os.environ, "LOCUST_SEED": str(seed)},
                           stdout=out, stderr=subprocess.STDOUT,
                           timeout=duration_s + 90, creationflags=flags)
    except FileNotFoundError:
        return Measurement(False, "live", "locust is not installed in this venv")
    except subprocess.TimeoutExpired:
        return Measurement(False, "live", f"locust did not finish within {duration_s + 90} s")
    except OSError as exc:
        return Measurement(False, "live", f"locust could not be started: {exc}")
    duration = time.monotonic() - t0

    ok_w, web, msg_w = _pod_json("web", "/metrics.json")
    ok_a, api, msg_a = _pod_json("api", "/metrics.json")
    if not (ok_w and ok_a):
        return Measurement(False, "live", f"could not read counters: {msg_w if not ok_w else msg_a}")

    served = int(web.get("requests", 0))
    if served <= 0:
        return Measurement(False, "live", "the load run served 0 requests - is the NodePort up?")

    snaps = {"web": web, "api": api}
    bpr = {(src, dst): snaps[svc]["edges"].get(peer, {}).get(field, 0) / served
           for src, dst, svc, peer, field in EDGES}
    svc, peer, fld = CLIENT_EDGE
    internet = snaps[svc]["edges"].get(peer, {}).get(fld, 0) / served

    return Measurement(True, "live",
                       f"{served:,} requests served in {duration:.0f} s "
                       f"({users} users, seed {seed})",
                       bpr, internet, served, duration)


def cached() -> Measurement:
    """The committed M07 measurement, used whenever the live path is unavailable."""
    bpr = cached_measurement()
    internet = bpr.get(("web", "internet"))
    edges = {k: v for k, v in bpr.items() if "internet" not in k}
    return Measurement(True, "cached",
                       "Cached M07 measurement: 3 x 10 min locust runs, max CV 0.87% "
                       "(testbed/measurements/summary.csv)",
                       edges, internet, 0, 0.0)


def measure_or_cached(**kwargs) -> Measurement:
    """Try a live measurement; fall back to the cached one, keeping the live failure reason."""
    live = measure(**kwargs)
    if live.ok:
        return live
    fallback = cached()
    fallback.message = f"Live measurement unavailable ({live.message}). {fallback.message}"
    return fallback
