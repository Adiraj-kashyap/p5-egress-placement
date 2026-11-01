"""Placement instance: one topology priced on one cost-model snapshot over one location set.

An `Instance` holds everything a placement method or the cost evaluator needs, pre-computed
from `cost_model/<date>/*.csv` and a topology JSON:

- `k[(c, l)]`       monthly compute (usd_per_hour x 730) + storage of component c at location l
- `r[l]`            internet (end-user) egress rate of sender location l, USD/GB
- `egress[(a, b)]`  directed transfer rate from location a to b, USD/GB, sender pays (D-005)

Each component's shape is fixed in advance as the smallest standard shape meeting its
vCPU/RAM requirement (D-004); the decision variable is location only.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pricing.common import LOCATIONS_CORE, LOCATIONS_EXT, ROOT, location_id

HOURS_PER_MONTH = 730

# Same standard shapes as pricing/build_cost_model.py (03_SKILLS §S5), smallest first.
SHAPES = [
    ("small", 2, 8),
    ("medium", 4, 16),
    ("large", 8, 32),
    ("xlarge", 16, 64),
]

LOCATION_SETS = {"core": LOCATIONS_CORE, "ext": LOCATIONS_EXT}


def shape_for(vcpu: float, ram_gb: float) -> str:
    """Return the smallest standard shape with at least `vcpu` vCPUs and `ram_gb` GB of RAM.

    Implements D-004. Raises ValueError when no standard shape is large enough, so an
    oversized component is never silently priced on a smaller machine.
    """
    for name, s_vcpu, s_ram in SHAPES:
        if s_vcpu >= vcpu and s_ram >= ram_gb:
            return name
    raise ValueError(f"no standard shape meets vcpu={vcpu}, ram_gb={ram_gb}")


def provider_of(location: str) -> str:
    """Provider part of a location id, e.g. provider_of('aws:us-east-1') -> 'aws'."""
    return location.split(":", 1)[0]


@dataclass(frozen=True, eq=False)
class Instance:
    """A priced placement problem. Built by `load_instance`; treat as read-only.

    Components and locations are kept in a fixed order (topology order, and LOCATIONS_*
    provider-major order) so every method iterates them deterministically.
    """

    instance_id: str
    topology_id: str
    snapshot_date: str
    location_set: str
    components: tuple[str, ...]
    locations: tuple[str, ...]
    shape: Mapping[str, str]
    vcpu: Mapping[str, int]
    storage_gb: Mapping[str, float]
    allowed: Mapping[str, tuple[str, ...]]
    usd_per_hour: Mapping[tuple[str, str], float]
    compute_month: Mapping[tuple[str, str], float]
    storage_month: Mapping[tuple[str, str], float]
    k: Mapping[tuple[str, str], float]
    edges: tuple[tuple[str, str, float], ...]
    internet_gb: Mapping[str, float]
    r: Mapping[str, float]
    egress: Mapping[tuple[str, str], float]

    @property
    def n_components(self) -> int:
        """Number of components to place."""
        return len(self.components)

    @property
    def n_locations(self) -> int:
        """Number of candidate locations in the location set."""
        return len(self.locations)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_topology(topology: str | Path | Mapping) -> dict:
    """Load a topology JSON from a path (absolute or repo-relative), or pass a dict through."""
    if isinstance(topology, Mapping):
        return dict(topology)
    path = Path(topology)
    if not path.is_absolute():
        path = ROOT / path
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_instance(topology: str | Path | Mapping, snapshot_date: str,
                  location_set: str = "core", cost_model_dir: str | Path | None = None) -> Instance:
    """Build an `Instance` from a topology and the cost model of `snapshot_date`.

    Reads compute, storage, egress and internet CSVs from `cost_model/<snapshot_date>/`
    (or `cost_model_dir`), restricts them to the `core` or `ext` location set, fixes each
    component's shape (D-004) and pre-computes k, r and the directed egress matrix. `pinned_to`
    may be a provider (the schema form; allowed = that provider's regions) or a location id. A price
    missing for any required (shape, location) or location pair raises KeyError.
    """
    topo = load_topology(topology)
    if location_set not in LOCATION_SETS:
        raise ValueError(f"unknown location set {location_set!r}")
    locs = tuple(location_id(p, reg) for p, regs in LOCATION_SETS[location_set].items() for reg in regs)
    loc_set = set(locs)
    cm = Path(cost_model_dir) if cost_model_dir else ROOT / "cost_model" / snapshot_date

    hourly = {(row["shape"], location_id(row["provider"], row["region"])): float(row["usd_per_hour"])
              for row in _read_csv(cm / "compute.csv")}
    storage_rate = {location_id(row["provider"], row["region"]): float(row["usd_per_gb_month"])
                    for row in _read_csv(cm / "storage.csv")}
    internet_rate = {location_id(row["provider"], row["region"]): float(row["usd_per_gb"])
                     for row in _read_csv(cm / "internet.csv")}
    egress_all = {(location_id(row["src_provider"], row["src_region"]),
                   location_id(row["dst_provider"], row["dst_region"])): float(row["usd_per_gb"])
                  for row in _read_csv(cm / "egress.csv")}

    comps = tuple(c["id"] for c in topo["components"])
    shape, vcpu, storage_gb, allowed = {}, {}, {}, {}
    for c in topo["components"]:
        cid = c["id"]
        shape[cid] = shape_for(c["vcpu"], c["ram_gb"])
        vcpu[cid] = next(v for n, v, _ in SHAPES if n == shape[cid])
        storage_gb[cid] = float(c.get("storage_gb") or 0.0)
        pin = c.get("pinned_to")
        if not pin:
            allowed[cid] = locs
        elif pin in LOCATION_SETS[location_set]:  # a provider (the schema form): any of its regions (D-048)
            allowed[cid] = tuple(l for l in locs if provider_of(l) == pin)
        elif pin in loc_set:  # a single location id
            allowed[cid] = (pin,)
        else:
            raise ValueError(f"{cid} pinned to {pin}, which is neither a provider nor a location in {location_set}")

    usd_per_hour = {(s, l): hourly[(s, l)] for s in set(shape.values()) for l in locs}
    compute_month = {(c, l): usd_per_hour[(shape[c], l)] * HOURS_PER_MONTH for c in comps for l in locs}
    storage_month = {(c, l): storage_gb[c] * storage_rate[l] for c in comps for l in locs}
    k = {key: compute_month[key] + storage_month[key] for key in compute_month}

    edges = tuple((e["src"], e["dst"], float(e["gb_per_month"])) for e in topo["edges"])
    internet_gb: dict[str, float] = {}
    for e in topo.get("internet_egress", []):
        internet_gb[e["src"]] = internet_gb.get(e["src"], 0.0) + float(e["gb_per_month"])
    for u, v, _ in edges:
        if u not in shape or v not in shape:
            raise ValueError(f"edge {u}->{v} references an unknown component")

    return Instance(
        instance_id=f"{topo['id']}@{location_set}",
        topology_id=topo["id"],
        snapshot_date=snapshot_date,
        location_set=location_set,
        components=comps,
        locations=locs,
        shape=shape,
        vcpu=vcpu,
        storage_gb=storage_gb,
        allowed=allowed,
        usd_per_hour=usd_per_hour,
        compute_month=compute_month,
        storage_month=storage_month,
        k=k,
        edges=edges,
        internet_gb=internet_gb,
        r={l: internet_rate[l] for l in locs},
        egress={(a, b): egress_all[(a, b)] for a in locs for b in locs},
    )
