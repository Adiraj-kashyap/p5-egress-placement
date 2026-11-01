"""Validate topology JSON files against topologies/schema.json plus referential checks.

Usage: python -m topologies.validate topologies/*.json
Glob patterns are expanded here because PowerShell does not expand them. schema.json
itself is skipped. Exit code 0 only if every topology is valid.
"""
from __future__ import annotations

import glob
import json
import logging
import sys
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
PROVIDERS = ("aws", "gcp", "azure")


def get_logger(name: str) -> logging.Logger:
    """Return a logger writing to stdout and logs/<name>_<date>.log.

    Handlers are attached once per process, so repeated calls are cheap.
    """
    log = logging.getLogger(name)
    if log.handlers:
        return log
    (ROOT / "logs").mkdir(exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(name)-12s  %(levelname)-7s  %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(ROOT / "logs" / f"{name}_{date.today().isoformat()}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log


def load_schema() -> dict:
    """Load the authoritative topology schema (JSON Schema draft 2020-12)."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_topology(doc: dict) -> list[str]:
    """Return a list of human-readable errors for one topology document (empty = valid).

    Runs the JSON Schema first; if the structure is valid it then checks what the schema
    cannot: unique component ids, edge and internet-egress endpoints exist, no self-edges,
    no duplicate (src, dst) edges, volumes >= 0 and pinned_to in {aws, gcp, azure, null}.
    """
    validator = Draft202012Validator(load_schema())
    errors = [f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
              for e in sorted(validator.iter_errors(doc), key=lambda e: list(map(str, e.path)))]
    if errors:
        return errors

    ids = [c["id"] for c in doc["components"]]
    known = set(ids)
    for cid in sorted(known):
        if ids.count(cid) > 1:
            errors.append(f"duplicate component id {cid!r}")
    for c in doc["components"]:
        if c["pinned_to"] is not None and c["pinned_to"] not in PROVIDERS:
            errors.append(f"component {c['id']!r}: pinned_to {c['pinned_to']!r} is not a provider")

    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(doc["edges"]):
        tag = f"edge {i} ({e['src']}->{e['dst']})"
        for end in ("src", "dst"):
            if e[end] not in known:
                errors.append(f"{tag}: {end} {e[end]!r} is not a component")
        if e["src"] == e["dst"]:
            errors.append(f"{tag}: self-edge")
        if (e["src"], e["dst"]) in seen:
            errors.append(f"{tag}: duplicate edge")
        seen.add((e["src"], e["dst"]))
        if e["gb_per_month"] < 0:
            errors.append(f"{tag}: negative volume")
        if not e["provenance"].strip():
            errors.append(f"{tag}: empty provenance")

    for i, x in enumerate(doc["internet_egress"]):
        if x["src"] not in known:
            errors.append(f"internet_egress {i}: src {x['src']!r} is not a component")
        if x["gb_per_month"] < 0:
            errors.append(f"internet_egress {i}: negative volume")
        if not x["provenance"].strip():
            errors.append(f"internet_egress {i}: empty provenance")
    return errors


def summarise(doc: dict) -> dict:
    """Return counts and aggregate volumes (GB/month) for one topology.

    `inter_component_gb` is the sum over directed edges; `internet_gb` is the sum of
    internet egress. H1 needs inter_component_gb >= 500 (00_PROJECT_BRIEF.md §4).
    """
    return {
        "id": doc["id"],
        "components": len(doc["components"]),
        "edges": len(doc["edges"]),
        "inter_component_gb": round(sum(e["gb_per_month"] for e in doc["edges"]), 3),
        "internet_gb": round(sum(x["gb_per_month"] for x in doc["internet_egress"]), 3),
    }


def expand(args: list[str]) -> list[Path]:
    """Expand glob patterns, drop schema.json, and return sorted unique paths."""
    paths: set[Path] = set()
    for a in args:
        matches = glob.glob(a) or [a]
        paths.update(Path(m) for m in matches)
    return sorted(p for p in paths if p.name != "schema.json")


def main(argv: list[str] | None = None) -> int:
    """Validate every file given on the command line; log a summary line per topology."""
    log = get_logger("validate")
    args = sys.argv[1:] if argv is None else argv
    paths = expand(args or [str(Path(__file__).resolve().parent / "t*.json")])
    if not paths:
        log.error("no topology files found")
        return 1
    bad = 0
    for p in paths:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("%s: INVALID (cannot read: %s)", p, exc)
            bad += 1
            continue
        errors = validate_topology(doc)
        if errors:
            bad += 1
            log.error("%s: INVALID (%d errors)", p, len(errors))
            for err in errors:
                log.error("    %s", err)
        else:
            s = summarise(doc)
            log.info("%s: VALID  components=%d edges=%d inter_component_gb=%.2f internet_gb=%.2f",
                     p, s["components"], s["edges"], s["inter_component_gb"], s["internet_gb"])
    log.info("%d/%d valid", len(paths) - bad, len(paths))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
