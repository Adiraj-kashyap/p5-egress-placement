"""M13 step 1: seeded synthetic service topologies for the scaling and sweep experiments.

`synthetic(n, location_set, seed, ...)` returns a topology dict that validates against
`topologies/schema.json` (checked on every call). The graph depends only on the generator
arguments other than `location_set`, so the same seed gives the same service graph on `core`
and `ext` (paired comparison across location sets, D-050). Every random draw comes from one
`random.Random` built from the arguments; there is no global RNG state.

Model (D-050):
- Components c0..c{n-1}; shape drawn uniformly from the four standard shapes (2/8, 4/16, 8/32,
  16/64 vCPU/GiB); 30% hold object storage, lognormal with median 100 GB (sigma 1).
- Call graph: a random recursive tree over a shuffled order (the i-th node is called by a
  uniformly chosen earlier node, so the graph is connected), plus extra caller->callee pairs drawn
  uniformly from the remaining unordered pairs until round(density * n(n-1)/2) pairs communicate
  (never fewer than n-1). Calls go from earlier to later in the order, so the call graph is a DAG.
- Every communicating pair is a request edge (caller->callee) and a response edge
  (callee->caller); each directed edge draws its own volume from `volume_dist` with median
  `median_gb` GB/month ("lognormal": sigma 1; "uniform": U(0, 2*median); "constant": median).
- Internet egress: the entry component (first in the order) always sends, every other
  component with probability 0.1; volumes from the same distribution.
- Pins: round(pin_fraction * n) components, chosen uniformly, pinned to a uniformly drawn provider.

Run: python -m experiments.generate --n 10 --seed 1 [--location-set core] [--out file.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from pathlib import Path

from placement.instance import LOCATION_SETS, SHAPES
from topologies.validate import PROVIDERS, validate_topology

VOLUME_DISTS = ("lognormal", "uniform", "constant")
DEFAULTS = {"density": 0.25, "volume_dist": "lognormal", "median_gb": 200.0, "pin_fraction": 0.0}
LOGNORMAL_SIGMA = 1.0
STORAGE_P, STORAGE_MEDIAN_GB = 0.3, 100.0
INTERNET_P = 0.1


def _volume(rng: random.Random, dist: str, median: float) -> float:
    """One edge volume in GB/month, rounded to 0.01 GB."""
    if dist == "lognormal":
        v = rng.lognormvariate(math.log(median), LOGNORMAL_SIGMA)
    elif dist == "uniform":
        v = rng.uniform(0.0, 2.0 * median)
    else:
        v = median
    return round(v, 2)


def topology_id(n: int, seed: int, density: float, volume_dist: str, median_gb: float,
                pin_fraction: float) -> str:
    """Stable id `syn_n<n>_s<seed>`, plus a short hash of the parameters when they are not the defaults."""
    base = f"syn_n{n}_s{seed}"
    params = {"density": density, "volume_dist": volume_dist, "median_gb": float(median_gb),
              "pin_fraction": pin_fraction}
    if params == DEFAULTS:
        return base
    digest = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:8]
    return f"{base}_{digest}"


def synthetic(n: int, location_set: str, seed: int, density: float = 0.25, volume_dist: str = "lognormal",
              median_gb: float = 200, pin_fraction: float = 0.0) -> dict:
    """Return a seeded, connected, schema-valid synthetic service topology with `n` components.

    See the module docstring for the model. `location_set` ("core" or "ext") is validated and
    recorded in `assumptions` but does not change the graph (D-050). Raises ValueError on bad
    arguments, and AssertionError if the result fails schema validation (a generator bug).
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if location_set not in LOCATION_SETS:
        raise ValueError(f"unknown location set {location_set!r}")
    if not 0.0 <= density <= 1.0:
        raise ValueError("density must be in [0, 1]")
    if volume_dist not in VOLUME_DISTS:
        raise ValueError(f"volume_dist must be one of {VOLUME_DISTS}")
    if median_gb <= 0:
        raise ValueError("median_gb must be > 0")
    if not 0.0 <= pin_fraction <= 1.0:
        raise ValueError("pin_fraction must be in [0, 1]")

    rng = random.Random(f"p5-synthetic|{n}|{seed}|{density}|{volume_dist}|{float(median_gb)}|{pin_fraction}")
    tag = f"synthetic:seed={seed}"
    ids = [f"c{i}" for i in range(n)]

    components = []
    for cid in ids:
        _, vcpu, ram = rng.choice(SHAPES)
        storage = round(rng.lognormvariate(math.log(STORAGE_MEDIAN_GB), LOGNORMAL_SIGMA), 1) \
            if rng.random() < STORAGE_P else 0
        components.append({"id": cid, "vcpu": vcpu, "ram_gb": ram, "storage_gb": storage, "pinned_to": None})
    for i in sorted(rng.sample(range(n), round(pin_fraction * n))):
        components[i]["pinned_to"] = rng.choice(PROVIDERS)

    order = ids[:]
    rng.shuffle(order)
    pos = {c: i for i, c in enumerate(order)}
    pairs = [(order[rng.randrange(i)], order[i]) for i in range(1, n)]  # spanning tree, caller first
    tree = {frozenset(p) for p in pairs}
    target = max(n - 1, round(density * n * (n - 1) / 2))
    rest = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if frozenset((a, b)) not in tree]
    for a, b in rng.sample(rest, min(len(rest), target - len(pairs))):
        pairs.append((a, b) if pos[a] < pos[b] else (b, a))

    edges = []
    for caller, callee in pairs:
        edges.append({"src": caller, "dst": callee, "gb_per_month": _volume(rng, volume_dist, median_gb),
                      "provenance": tag, "rationale": "request"})
        edges.append({"src": callee, "dst": caller, "gb_per_month": _volume(rng, volume_dist, median_gb),
                      "provenance": tag, "rationale": "response"})
    internet = [{"src": c, "gb_per_month": _volume(rng, volume_dist, median_gb), "provenance": tag,
                 "rationale": "entry component" if c == order[0] else "sampled"}
                for c in ids if c == order[0] or rng.random() < INTERNET_P]

    doc = {
        "id": topology_id(n, seed, density, volume_dist, median_gb, pin_fraction),
        "description": f"Synthetic {n}-component service graph (experiments.generate, seed {seed}).",
        "provenance": "synthetic",
        "assumptions": {"generator": "experiments.generate.synthetic", "n": n, "seed": seed,
                        "location_set": location_set, "density": density, "volume_dist": volume_dist,
                        "median_gb": float(median_gb), "pin_fraction": pin_fraction,
                        "communicating_pairs": len(pairs), "entry_component": order[0]},
        "components": components,
        "edges": edges,
        "internet_egress": internet,
    }
    errors = validate_topology(doc)
    assert not errors, f"generator produced an invalid topology: {errors[:3]}"
    return doc


def canonical_sha256(doc: dict) -> str:
    """SHA-256 of the canonical JSON form (sorted keys), used to record and re-check generated instances."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    """Generate one topology and print it (or write it to --out)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--location-set", default="core", choices=sorted(LOCATION_SETS))
    ap.add_argument("--density", type=float, default=DEFAULTS["density"])
    ap.add_argument("--volume-dist", default=DEFAULTS["volume_dist"], choices=VOLUME_DISTS)
    ap.add_argument("--median-gb", type=float, default=DEFAULTS["median_gb"])
    ap.add_argument("--pin-fraction", type=float, default=DEFAULTS["pin_fraction"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    doc = synthetic(args.n, args.location_set, args.seed, args.density, args.volume_dist, args.median_gb,
                    args.pin_fraction)
    text = json.dumps(doc, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
