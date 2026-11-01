"""Data and text loaders for the walkthrough chapters (M22) — no Streamlit, no network.

The walkthrough explains the project in its own words, but every *number* it shows is read
here from a committed, generated file (non-negotiable 1): the price tables in
`cost_model/<date>/`, the topologies, the figure CSVs cached in `demo/cache/`, and the
generated Markdown in `docs/report/`. Prose sections that are already written elsewhere
(the brief's hypotheses, the verdict paragraphs, the five-line ablation answer) are parsed
out of their source files rather than copied, so the app cannot drift from them.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from demo import core
from pricing.common import LOCATIONS_CORE, LOCATIONS_EXT

ROOT = core.ROOT
COST_DIR = ROOT / "cost_model" / core.SNAPSHOT_DATE

#: Every file a chapter cites as a source; the walkthrough test checks each one exists.
BRIEF = "docs/methodology/project_brief.md"
VERDICTS = "docs/report/verdicts.md"
H1_TABLE = "docs/report/tables/h1_replicated.md"
ABLATION = "docs/review2/ablation_and_sweep.md"
THREATS = "docs/review2/threats_to_validity.md"
VALIDATION = f"cost_model/{core.SNAPSHOT_DATE}/validation.md"
MEASUREMENT = "testbed/measurements/summary.csv"


@dataclass(frozen=True)
class Chapter:
    """One page of the walkthrough, in reading order."""

    file: str      # path under demo/, as st.Page / st.page_link expect it
    title: str
    icon: str
    blurb: str     # one line for the chapter map on the Start page

    @property
    def slug(self) -> str:
        """Stable URL path: the file stem without its number, e.g. `h1` for 05_h1.py."""
        return Path(self.file).stem.split("_", 1)[1]


CHAPTERS = (
    Chapter("chapters/00_start.py", "Start here", ":material/flag:",
            "The question, the four objectives, the three hypotheses and their verdicts."),
    Chapter("chapters/01_pricing.py", "1 · Pricing data", ":material/payments:",
            "O1: real list prices for compute, storage and egress from AWS, Azure and GCP."),
    Chapter("chapters/02_workloads.py", "2 · Workloads", ":material/hub:",
            "The three applications being placed, and the traffic between their parts."),
    Chapter("chapters/03_cost_model.py", "3 · Cost model", ":material/functions:",
            "O2: the cost formula. Place components yourself and watch the bill change."),
    Chapter("chapters/04_solvers.py", "4 · Solvers, live", ":material/bolt:",
            "O3: ILP, greedy and annealing against the baselines, solved in front of you."),
    Chapter("chapters/05_h1.py", "5 · H1 egress penalty", ":material/trending_down:",
            "How much ignoring egress costs, over 30 replicated traffic draws."),
    Chapter("chapters/06_h2.py", "6 · H2 heuristics", ":material/speed:",
            "Is simulated annealing near-optimal and faster than the exact solver?"),
    Chapter("chapters/07_h3.py", "7 · H3 traffic sweep", ":material/show_chart:",
            "Does a single provider take over above some traffic level?"),
    Chapter("chapters/08_why.py", "8 · Why: ablation", ":material/science:",
            "Which ingredient of the model produces the gain, and how prices move it."),
    Chapter("chapters/09_testbed.py", "9 · Live testbed", ":material/lan:",
            "Measure real traffic on a Kubernetes testbed, then re-optimise from it."),
    Chapter("chapters/10_conclusion.py", "10 · Limits and conclusion", ":material/task_alt:",
            "What the evidence supports, what it does not, and the threats to validity."),
)


def chapter_index(file: str) -> int:
    return next(i for i, c in enumerate(CHAPTERS) if c.file == file)


# --------------------------------------------------------------------------- Markdown


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def md_section(rel: str, heading: str) -> str:
    """Body of the first heading whose text starts with `heading`, up to the next heading
    of the same or a higher level. Raises KeyError if the heading is absent."""
    lines = read(rel).splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#+)\s+(.*)$", line)
        if m and m.group(2).strip().startswith(heading):
            level = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                n = re.match(r"^(#+)\s", nxt)
                if n and len(n.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    raise KeyError(f"{rel}: no heading starting {heading!r}")


def md_table(text: str) -> list[dict[str, str]]:
    """The first pipe table in `text` as a list of dicts (bold markers stripped)."""
    rows: list[str] = []
    for ln in text.splitlines():
        if ln.strip().startswith("|"):
            rows.append(ln)
        elif rows:
            break
    if len(rows) < 2:
        return []
    split = lambda ln: [c.strip().replace("**", "") for c in ln.strip().strip("|").split("|")]
    header = split(rows[0])
    return [dict(zip(header, split(ln))) for ln in rows[2:]]


def problem_statement() -> str:
    return md_section(BRIEF, "§1 Problem")


def objectives() -> list[dict[str, str]]:
    return md_table(md_section(BRIEF, "§2 Objectives"))


def hypotheses() -> dict[str, str]:
    """{'H1': statement, ...} exactly as frozen in the brief §4."""
    text = md_section(BRIEF, "§4 Hypotheses")
    out = {}
    for para in re.split(r"\n\s*\n", text):
        m = re.match(r"\*\*(H\d) \(([^)]*)\)\.\*\*\s*(.*)", para.strip(), re.S)
        if m:
            out[m.group(1)] = " ".join(m.group(3).split())
    return out


def verdicts() -> dict[str, dict]:
    """Per hypothesis: overall verdict, per-topology verdicts, and the generated paragraph."""
    rows = md_table(read(VERDICTS))
    out = {}
    for row in rows:
        h = row["Hypothesis"]
        per = {}
        for part in row["Per topology"].split(","):
            bits = part.split()
            if len(bits) == 2:
                per[bits[0]] = bits[1]
        out[h] = {"verdict": row["Verdict"], "per_topology": per,
                  "section": md_section(VERDICTS, f"{h}:")}
    return out


def verdict_bullets(h: str) -> list[str]:
    """The '- T1: ...' style lines of one verdict section."""
    return [ln[2:] for ln in verdicts()[h]["section"].splitlines() if ln.startswith("- ")]


# --------------------------------------------------------------------------- prices


def locations(location_set: str = "core") -> list[str]:
    table = LOCATIONS_CORE if location_set == "core" else LOCATIONS_EXT
    return [f"{p}:{r}" for p, regions in table.items() for r in regions]


def _rows(name: str) -> list[dict]:
    with (COST_DIR / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def compute_prices(location_set: str = "core") -> list[dict]:
    """One row per location: price per vCPU-hour (all shapes in a family scale linearly,
    validation V5) and the monthly price of the smallest shape."""
    keep = set(locations(location_set))
    out = []
    for r in _rows("compute.csv"):
        loc = f"{r['provider']}:{r['region']}"
        if loc in keep and r["shape"] == "small":
            out.append({"location": loc, "provider": r["provider"],
                        "instance_type": r["instance_type"],
                        "usd_per_vcpu_hour": float(r["usd_per_hour"]) / float(r["vcpu"]),
                        "usd_per_month_small": float(r["usd_per_month"])})
    return out


#: Rule ids used in egress.csv -> plain-language meaning (from the `source` column `rule:R1 ...`).
RULE_TEXT = {"R1": "same region (free)", "R2": "same provider, other region",
             "R3": "to another provider (internet rate)"}


def egress_prices(location_set: str = "core") -> list[dict]:
    keep = set(locations(location_set))
    out = []
    for r in _rows("egress.csv"):
        src, dst = f"{r['src_provider']}:{r['src_region']}", f"{r['dst_provider']}:{r['dst_region']}"
        if src in keep and dst in keep:
            out.append({"from": src, "to": dst, "usd_per_gb": float(r["usd_per_gb"]),
                        "rule": r["rule"], "meaning": RULE_TEXT.get(r["rule"], r["rule"])})
    return out


def egress_rule_summary(location_set: str = "core") -> list[dict]:
    rows = egress_prices(location_set)
    out = []
    for rule in sorted({r["rule"] for r in rows}):
        vals = [r["usd_per_gb"] for r in rows if r["rule"] == rule]
        out.append({"rule": rule, "meaning": RULE_TEXT.get(rule, rule), "cells": len(vals),
                    "min_usd_per_gb": min(vals), "max_usd_per_gb": max(vals)})
    return out


def internet_storage_prices(location_set: str = "core") -> list[dict]:
    keep = set(locations(location_set))
    storage = {f"{r['provider']}:{r['region']}": r for r in _rows("storage.csv")}
    out = []
    for r in _rows("internet.csv"):
        loc = f"{r['provider']}:{r['region']}"
        if loc in keep:
            s = storage[loc]
            out.append({"location": loc, "internet_usd_per_gb": float(r["usd_per_gb"]),
                        "storage_class": s["storage_class"],
                        "storage_usd_per_gb_month": float(s["usd_per_gb_month"])})
    return out


def price_row_counts() -> dict[str, int]:
    return {name.removesuffix(".csv"): len(_rows(name))
            for name in ("compute.csv", "egress.csv", "internet.csv", "storage.csv")}


def validation_checks() -> tuple[str, list[dict]]:
    """(result line, check table) from the generated cost-model validation report."""
    text = read(VALIDATION)
    result = next((ln.strip("* ") for ln in text.splitlines() if ln.startswith("**Result")), "")
    return result, md_table(text)


# --------------------------------------------------------------------------- workloads


def topology(label: str) -> dict:
    return json.loads((ROOT / core.TOPOLOGIES[label]).read_text(encoding="utf-8"))


def topology_dot(topo: dict) -> str:
    """Graphviz DOT for a topology: components as boxes, edges labelled with GB/month,
    internet egress as a dashed edge to a 'users' node. Rendered client-side by Streamlit."""
    lines = ['digraph G {', 'rankdir=LR; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", fillcolor="#eef3fb", color="#2a78d6",'
             ' fontname="Helvetica", fontsize=11];',
             'edge [fontname="Helvetica", fontsize=9, color="#52514e", fontcolor="#52514e"];']
    for c in topo["components"]:
        extra = f"\\n{c['storage_gb']:g} GB stored" if c.get("storage_gb") else ""
        lines.append(f'"{c["id"]}" [label="{c["id"]}\\n{c["vcpu"]} vCPU / {c["ram_gb"]:g} GB{extra}"];')
    for e in topo["edges"]:
        lines.append(f'"{e["src"]}" -> "{e["dst"]}" [label="{e["gb_per_month"]:,.1f}"];')
    if topo.get("internet_egress"):
        lines.append('"users" [shape=ellipse, fillcolor="#fdf1e9", color="#eb6834", label="end users"];')
        for ie in topo["internet_egress"]:
            lines.append(f'"{ie["src"]}" -> "users" [style=dashed, color="#eb6834", '
                         f'label="{ie["gb_per_month"]:,.1f}"];')
    lines.append("}")
    return "\n".join(lines)


def topology_summary(topo: dict) -> dict:
    return {"components": len(topo["components"]),
            "edges": len(topo["edges"]),
            "edge_gb_month": sum(e["gb_per_month"] for e in topo["edges"]),
            "internet_gb_month": sum(ie["gb_per_month"] for ie in topo.get("internet_egress", [])),
            "vcpu": sum(c["vcpu"] for c in topo["components"]),
            "storage_gb": sum(c.get("storage_gb", 0) for c in topo["components"])}


def measurement_rows() -> list[dict]:
    with (ROOT / MEASUREMENT).open(newline="", encoding="utf-8") as f:
        return [{"edge": f"{r['src']} → {r['dst']}", "runs": int(r["runs"]),
                 "served_requests": int(r["served_requests"]),
                 "bytes_per_request": float(r["bytes_per_request_mean"]),
                 "cv_pct": 100 * float(r["bytes_per_request_cv"])}
                for r in csv.DictReader(f)]


# --------------------------------------------------------------------------- results


def count_rows(rel: str) -> int:
    """Data rows in a committed CSV (header excluded)."""
    with (ROOT / rel).open(encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


#: Results that the replicated statistics rest on: directory -> what it holds.
RUN_FILES = {"results/replicates/runs.csv": "replicated traffic draws (H1, H3)",
             "results/scaling/runs.csv": "scaling and optimality gap (H2)",
             "results/ablation/runs.csv": "ablation variants",
             "results/sensitivity/runs.csv": "price sensitivity grid"}


def run_counts() -> dict[str, int]:
    return {rel: count_rows(rel) for rel in RUN_FILES if (ROOT / rel).exists()}


def threats_by_category() -> dict[str, list[dict]]:
    """{'Construct validity': [rows...], ...} from the review-2 threats document."""
    text = read(THREATS)
    out = {}
    for m in re.finditer(r"^## (\w+ validity)", text, re.M):
        out[m.group(1)] = md_table(md_section(THREATS, m.group(1)))
    return out
