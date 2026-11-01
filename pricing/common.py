"""Shared helpers: dated snapshot directories, logging, HTTP with retry."""
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DATE = os.environ.get("P5_SNAPSHOT_DATE", date.today().isoformat())
SNAPSHOT_DIR = ROOT / "snapshots" / SNAPSHOT_DATE
LOG_DIR = ROOT / "logs"


def get_logger(name):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(name)-12s  %(levelname)-7s  %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(LOG_DIR / f"pull_{SNAPSHOT_DATE}.log")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log


def get_json(url, log, params=None, retries=4, timeout=60):
    """GET with exponential backoff. Logs the status code of every attempt."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            log.info("GET %s -> HTTP %s", r.url.split("?")[0], r.status_code)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("attempt %d failed (%s); retrying in %ds", attempt, exc, wait)
            time.sleep(wait)


def write_snapshot(name, rows, log, meta=None):
    """Persist rows to snapshots/<date>/<name>.json with provenance metadata."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{name}.json"
    payload = {
        "snapshot_date": SNAPSHOT_DATE,
        "pulled_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "row_count": len(rows),
        "meta": meta or {},
        "rows": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    size_mb = path.stat().st_size / 1e6
    log.info("WROTE %s  rows=%d  size=%.2f MB", path.relative_to(ROOT), len(rows), size_mb)
    return path


def peak_rss_mb():
    """Peak resident memory of this process in MB (getrusage on Unix, psapi on Windows)."""
    try:
        import resource
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return kb / 1024 if sys.platform != "darwin" else kb / 1e6
    except ImportError:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        c = Counters()
        c.cb = ctypes.sizeof(c)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle), ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize / 1e6


def read_snapshot(name):
    with open(SNAPSHOT_DIR / f"{name}.json") as f:
        return json.load(f)["rows"]


# Location sets (D-002). `core` = 4 regions/provider (12) for application experiments;
# `ext` = 8/provider (24) for scaling, and core is a subset of ext. The four extra regions
# per provider are chosen as geographic analogues (US west, EU central, Japan, Brazil) so the
# ext set spans NA/EU/AS/SA on every provider (D-018).
LOCATIONS_CORE = {
    "aws": ["us-east-1", "eu-west-1", "ap-south-1", "ap-southeast-1"],
    "azure": ["eastus", "westeurope", "centralindia", "southeastasia"],
    "gcp": ["us-east4", "europe-west1", "asia-south1", "asia-southeast1"],
}
LOCATIONS_EXT = {
    "aws": LOCATIONS_CORE["aws"] + ["us-west-2", "eu-central-1", "ap-northeast-1", "sa-east-1"],
    "azure": LOCATIONS_CORE["azure"] + ["westus2", "germanywestcentral", "japaneast", "brazilsouth"],
    "gcp": LOCATIONS_CORE["gcp"] + ["us-west1", "europe-west3", "asia-northeast1", "southamerica-east1"],
}
# Backward-compatible alias used by build_cost_model.py and the fixtures generator.
LOCATIONS = LOCATIONS_CORE

# Coarse continent tags, used to price inter-region transfer within a provider.
CONTINENT = {
    "us-east-1": "NA", "eu-west-1": "EU", "ap-south-1": "AS", "ap-southeast-1": "AS",
    "eastus": "NA", "westeurope": "EU", "centralindia": "AS", "southeastasia": "AS",
    "us-east4": "NA", "europe-west1": "EU", "asia-south1": "AS", "asia-southeast1": "AS",
    "us-west-2": "NA", "eu-central-1": "EU", "ap-northeast-1": "AS", "sa-east-1": "SA",
    "westus2": "NA", "germanywestcentral": "EU", "japaneast": "AS", "brazilsouth": "SA",
    "us-west1": "NA", "europe-west3": "EU", "asia-northeast1": "AS", "southamerica-east1": "SA",
}


def location_id(provider, region):
    """Canonical location id, e.g. location_id('aws', 'us-east-1') -> 'aws:us-east-1'."""
    return f"{provider}:{region}"
