"""Offline tests for the M07 measurement driver and summariser (no cluster needed)."""
from __future__ import annotations

import csv
import math

from testbed.measure import run_measurement as rm
from testbed.measure import summarize as sm

WEB = {"service": "web", "requests": 100,
       "edges": {"api": {"bytes_sent": 8_000, "bytes_received": 400_000},
                 "client": {"bytes_sent": 500_000, "bytes_received": 17_000}}}
API = {"service": "api", "requests": 100,
       "edges": {"web": {"bytes_sent": 400_000, "bytes_received": 8_000},
                 "cache": {"bytes_sent": 150_000, "bytes_received": 270_000},
                 "db": {"bytes_sent": 15_000, "bytes_received": 140_000}}}
RUN = {"run_id": "r1", "seed": 7}


def test_edge_rows_map_counters_to_directed_edges():
    rows = {(r["src"], r["dst"]): r for r in rm.edge_rows(RUN, WEB, API)}
    assert len(rows) == 8
    assert rows[("web", "api")]["app_bytes"] == 8_000
    assert rows[("api", "web")]["app_bytes"] == 400_000
    assert rows[("cache", "api")]["app_bytes"] == 270_000
    assert rows[("db", "api")]["bytes_per_request"] == 1_400.0
    assert rows[("web", "internet")]["app_bytes"] == 500_000
    # api's own view of the web<->api edge is carried as the cross-check
    assert rows[("web", "api")]["api_side_bytes"] == 8_000
    assert rows[("api", "web")]["api_side_bytes"] == 400_000
    assert rows[("api", "db")]["api_side_bytes"] == ""


def test_iface_rows_sum_the_app_edges_crossing_each_pod():
    before = {p: (1_000, 2_000) for p in rm.PODS}
    after = {"web": (501_000, 1_002_000), "api": (601_000, 602_000),
             "cache": (201_000, 302_000), "db": (21_000, 152_000)}
    rows = {r["pod"]: r for r in rm.iface_rows("r1", before, after, WEB, API)}
    assert rows["web"]["iface_bytes"] == 1_500_000
    assert rows["web"]["app_bytes"] == 8_000 + 400_000 + 500_000 + 17_000
    assert rows["cache"]["app_bytes"] == 420_000
    assert math.isclose(rows["db"]["app_iface_ratio"], 155_000 / 170_000, rel_tol=1e-3)


def test_merge_csv_replaces_same_run_and_keeps_others(tmp_path):
    p = tmp_path / "runs.csv"
    rm.merge_csv(p, ["run_id", "x"], [{"run_id": "r1", "x": 1}, {"run_id": "r2", "x": 2}])
    rm.merge_csv(p, ["run_id", "x"], [{"run_id": "r2", "x": 20}, {"run_id": "r3", "x": 3}])
    with p.open(newline="", encoding="utf-8") as f:
        assert [(r["run_id"], r["x"]) for r in csv.DictReader(f)] == [("r1", "1"), ("r2", "20"), ("r3", "3")]


def test_summarise_edges_cv_uses_sample_sd():
    rows = [{"src": "a", "dst": "b", "app_bytes": b, "served_requests": 100} for b in (900, 1000, 1100)]
    (s,) = sm.summarise_edges(rows)
    assert s["runs"] == 3 and s["bytes_per_request_mean"] == 10.0
    assert math.isclose(s["bytes_per_request_cv"], 0.1, rel_tol=1e-6)
    assert s["bytes_per_request_min"] == 9.0 and s["bytes_per_request_max"] == 11.0


def test_summarise_ifaces_ratio_range():
    rows = [{"pod": "db", "app_bytes": a, "iface_bytes": 1000} for a in (600, 700)]
    (s,) = sm.summarise_ifaces(rows)
    assert s["app_iface_ratio_min"] == 0.6 and s["app_iface_ratio_max"] == 0.7
    assert s["app_iface_ratio_mean"] == 0.65
