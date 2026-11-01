"""Traffic uncertainty draws: turn one topology into R replicate topologies (M16, 05 §3).

Every method in the project is deterministic, so replicates cannot come from re-running a
solver (D-064). They come from the uncertainty in the *input*: how much traffic each edge
actually carries in a month. This module implements the two registered models of 05 §3.

**Measured volumes (T1, provenance "measured").** Per-edge bytes per request are resampled
with replacement from the M07 measurement runs. Per-request samples were not recorded, so
the resampling pool is the three per-run means in `testbed/measurements/runs.csv`
(05 §3 explicitly allows this fallback). One request-rate factor `exp(N(0, 0.25**2))` per
draw is shared by every edge, because load moves together.

**Stated volumes (T2, T3, provenance "stated").** Each edge volume is multiplied by a shared
load factor `exp(N(0, 0.3**2))` and an independent per-edge factor `exp(N(0, 0.3**2))`,
both with median 1.

Draw seeds are `draw_seed = DRAW_SEED_BASE + draw_id` (05 §3), so draw k is reproducible
from the draw id alone and is the *same* draw for every method — comparisons are paired.

    from experiments.uncertainty import draw_topology
    t = draw_topology(json.load(open("topologies/t1_three_tier.json")), 7)
"""
from __future__ import annotations

import copy
import csv
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_RUNS = ROOT / "testbed" / "measurements" / "runs.csv"

DRAW_SEED_BASE = 10_000
RATE_SIGMA = 0.25  # measured topologies: request-rate factor
GLOBAL_SIGMA = 0.3  # stated topologies: shared load factor
EDGE_SIGMA = 0.3  # stated topologies: independent per-edge factor
SECONDS_PER_MONTH = 2_592_000
INTERNET_DST = "internet"


def draw_seed(draw_id: int) -> int:
    """Return the frozen seed of a draw (05 §3: 10,000 + draw_id)."""
    if draw_id < 0:
        raise ValueError(f"draw_id must be >= 0, got {draw_id}")
    return DRAW_SEED_BASE + int(draw_id)


@lru_cache(maxsize=1)
def measurement_pool() -> dict[tuple[str, str], tuple[float, ...]]:
    """Return the per-edge resampling pool of bytes/request from the M07 runs.

    Key is (src, dst) with dst "internet" for end-user egress; the value is one entry per
    measurement run (3 runs in M07).
    """
    pool: dict[tuple[str, str], list[float]] = {}
    with MEASUREMENT_RUNS.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["src"], row["dst"])
            pool.setdefault(key, []).append(float(row["bytes_per_request"]))
    if not pool:
        raise RuntimeError(f"no measurement rows in {MEASUREMENT_RUNS}")
    return {k: tuple(v) for k, v in pool.items()}


def _gb_per_month(bytes_per_request: float, requests_per_s: float) -> float:
    """Convert bytes/request at a request rate into GB/month (GB = 1e9 bytes, 30-day month)."""
    return round(bytes_per_request * requests_per_s * SECONDS_PER_MONTH / 1e9, 6)


def _draw_measured(topology: dict, rng: np.random.Generator) -> dict:
    """Resample per-edge bytes/request and apply one shared request-rate factor."""
    doc = copy.deepcopy(topology)
    assumptions = doc.get("assumptions") or {}
    base_rate = float(assumptions.get("requests_per_s", 0.0))
    if base_rate <= 0:
        raise ValueError(
            f"measured topology {doc.get('id')!r} has no positive assumptions.requests_per_s"
        )
    pool = measurement_pool()
    rate_factor = float(np.exp(rng.normal(0.0, RATE_SIGMA)))
    rate = base_rate * rate_factor

    bpr: dict[str, float] = {}
    for edge in doc["edges"]:
        key = (edge["src"], edge["dst"])
        if key not in pool:
            raise KeyError(f"no measurement pool for edge {key[0]}->{key[1]}")
        sample = float(rng.choice(pool[key]))
        bpr[f"{key[0]}->{key[1]}"] = sample
        edge["gb_per_month"] = _gb_per_month(sample, rate)
        edge["provenance"] = "draw:measured-resample"

    for item in doc.get("internet_egress", []):
        key = (item["src"], INTERNET_DST)
        if key not in pool:
            raise KeyError(f"no measurement pool for internet egress from {item['src']}")
        sample = float(rng.choice(pool[key]))
        item["gb_per_month"] = _gb_per_month(sample, rate)

    assumptions = dict(assumptions)
    # recorded unrounded, so that these parameters reproduce the volumes above exactly
    assumptions["requests_per_s"] = rate
    assumptions["rate_factor"] = rate_factor
    assumptions["bytes_per_request"] = bpr
    assumptions["note"] = (
        "Uncertainty draw (05 §3, measured model): bytes/request resampled with replacement "
        "from the M07 per-run means; one shared request-rate factor exp(N(0, 0.25^2))."
    )
    doc["assumptions"] = assumptions
    return doc


def _draw_stated(topology: dict, rng: np.random.Generator) -> dict:
    """Scale every volume by a shared load factor and an independent per-edge factor."""
    doc = copy.deepcopy(topology)
    global_factor = float(np.exp(rng.normal(0.0, GLOBAL_SIGMA)))

    for edge in doc["edges"]:
        edge_factor = float(np.exp(rng.normal(0.0, EDGE_SIGMA)))
        edge["gb_per_month"] = round(
            float(edge["gb_per_month"]) * global_factor * edge_factor, 6
        )
        edge["provenance"] = "draw:stated-lognormal"
    for item in doc.get("internet_egress", []):
        edge_factor = float(np.exp(rng.normal(0.0, EDGE_SIGMA)))
        item["gb_per_month"] = round(
            float(item["gb_per_month"]) * global_factor * edge_factor, 6
        )

    assumptions = dict(doc.get("assumptions") or {})
    assumptions["global_factor"] = global_factor
    assumptions["note"] = (
        "Uncertainty draw (05 §3, stated model): volume x exp(N(0, 0.3^2))_global "
        "x exp(N(0, 0.3^2))_edge."
    )
    doc["assumptions"] = assumptions
    return doc


def draw_topology(topology: dict, draw_id: int) -> dict:
    """Return draw `draw_id` of `topology` as a new topology dict (05 §3).

    The model is chosen by the topology's own `provenance`: "measured" resamples the M07
    measurements, "stated" and "synthetic" apply the lognormal load/edge factors. The
    returned document keeps the same id and components and carries
    `provenance = "draw:<id>"` plus the draw parameters under `assumptions`. The input
    document is not modified.
    """
    provenance = str(topology.get("provenance", "stated"))
    rng = np.random.default_rng(draw_seed(draw_id))
    if provenance.startswith("draw:"):
        raise ValueError("cannot draw from a topology that is already a draw")
    if provenance == "measured":
        doc = _draw_measured(topology, rng)
    elif provenance in ("stated", "synthetic"):
        doc = _draw_stated(topology, rng)
    else:
        raise ValueError(f"unknown provenance {provenance!r}")
    assumptions = dict(doc.get("assumptions") or {})
    assumptions.update(
        {"draw_id": int(draw_id), "draw_seed": draw_seed(draw_id), "base_provenance": provenance}
    )
    doc["assumptions"] = assumptions
    doc["provenance"] = f"draw:{int(draw_id)}"
    return doc


def scale_edges(topology: dict, scale: float) -> dict:
    """Return a copy of `topology` with every **inter-component** edge volume x `scale`.

    Internet egress is deliberately left unchanged, which is the traffic-scale definition
    M15 used (03 §S9): s moves the traffic that placement can avoid, not the traffic that
    must leave to end users. Compute and storage requirements are unchanged. Keeping this
    identical to M15 is what makes the M16 scale grid comparable with the M15 sweep.
    """
    if scale <= 0:
        raise ValueError(f"scale must be > 0, got {scale}")
    doc = copy.deepcopy(topology)
    for edge in doc["edges"]:
        edge["gb_per_month"] = round(float(edge["gb_per_month"]) * scale, 6)
    assumptions = dict(doc.get("assumptions") or {})
    assumptions["traffic_scale"] = float(scale)
    doc["assumptions"] = assumptions
    return doc
