"""M07 step 7: summarise runs.csv into per-edge bytes/request with CV, and per-pod ratios.

Reads ``testbed/measurements/runs.csv`` and ``runs_interface.csv`` (written by
run_measurement.py) and writes ``summary.csv`` (one row per directed edge) and
``summary_interface.csv`` (one row per pod). CV = sample standard deviation (n-1) / mean of
the per-run bytes/request. Run from the repo root: python -m testbed.measure.summarize
"""
from __future__ import annotations

import argparse
import csv
import logging
import statistics
from pathlib import Path

log = logging.getLogger("summarize")

EDGE_FIELDS = ["src", "dst", "runs", "served_requests", "app_bytes", "bytes_per_request_mean",
               "bytes_per_request_sd", "bytes_per_request_cv", "bytes_per_request_min",
               "bytes_per_request_max"]
IFACE_FIELDS = ["pod", "runs", "app_bytes", "iface_bytes", "app_iface_ratio_mean",
                "app_iface_ratio_min", "app_iface_ratio_max"]


def read_csv(path: Path) -> list[dict]:
    """Return the rows of a CSV file as dicts."""
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarise_edges(rows: list[dict]) -> list[dict]:
    """Group run rows by (src, dst), keeping first-seen order, and compute the statistics."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["src"], r["dst"]), []).append(r)
    out = []
    for (src, dst), rs in groups.items():
        bpr = [int(r["app_bytes"]) / int(r["served_requests"]) for r in rs]
        mean = statistics.fmean(bpr)
        sd = statistics.stdev(bpr) if len(bpr) > 1 else 0.0
        out.append({"src": src, "dst": dst, "runs": len(rs),
                    "served_requests": sum(int(r["served_requests"]) for r in rs),
                    "app_bytes": sum(int(r["app_bytes"]) for r in rs),
                    "bytes_per_request_mean": round(mean, 3),
                    "bytes_per_request_sd": round(sd, 3),
                    "bytes_per_request_cv": round(sd / mean, 6) if mean else 0.0,
                    "bytes_per_request_min": round(min(bpr), 3),
                    "bytes_per_request_max": round(max(bpr), 3)})
    return out


def summarise_ifaces(rows: list[dict]) -> list[dict]:
    """Group interface rows by pod and report app/interface byte ratios across runs."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["pod"], []).append(r)
    out = []
    for pod, rs in groups.items():
        ratios = [int(r["app_bytes"]) / int(r["iface_bytes"]) for r in rs]
        out.append({"pod": pod, "runs": len(rs),
                    "app_bytes": sum(int(r["app_bytes"]) for r in rs),
                    "iface_bytes": sum(int(r["iface_bytes"]) for r in rs),
                    "app_iface_ratio_mean": round(statistics.fmean(ratios), 4),
                    "app_iface_ratio_min": round(min(ratios), 4),
                    "app_iface_ratio_max": round(max(ratios), 4)})
    return out


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Write ``rows`` to ``path`` with a header."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Read the run files, write the two summaries and log the headline statistics."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="testbed/measurements")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    d = Path(args.dir)
    edges = summarise_edges(read_csv(d / "runs.csv"))
    ifaces = summarise_ifaces(read_csv(d / "runs_interface.csv"))
    write_csv(d / "summary.csv", EDGE_FIELDS, edges)
    write_csv(d / "summary_interface.csv", IFACE_FIELDS, ifaces)
    for e in edges:
        log.info("%s->%s: %.1f B/request, CV %.2f%% over %d runs", e["src"], e["dst"],
                 e["bytes_per_request_mean"], 100 * e["bytes_per_request_cv"], e["runs"])
    for i in ifaces:
        log.info("pod %s: app/interface ratio %.3f (%.3f-%.3f)", i["pod"],
                 i["app_iface_ratio_mean"], i["app_iface_ratio_min"], i["app_iface_ratio_max"])
    log.info("max CV over edges = %.2f%%", 100 * max(e["bytes_per_request_cv"] for e in edges))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
