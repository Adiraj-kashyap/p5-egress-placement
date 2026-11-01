"""Build the T1-T3 topology JSON files and topologies/README.md from stated parameters.

Every edge volume in t1/t2/t3 is computed here from the parameters below, so a reviewer
can trace each number to a stated assumption (D-031). Run: python -m topologies.build
Units: GB = 1e9 bytes, month = 30 days = 2,592,000 s (01_CONVENTIONS.md §3).

T1 volumes are measured: bytes per request come from the M07 testbed summary
(testbed/measurements/summary.csv), scaled to the stated rate T1_RATE.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from topologies.validate import get_logger, summarise, validate_topology

HERE = Path(__file__).resolve().parent
SECONDS_PER_MONTH = 2_592_000


def gb_per_month(bytes_per_request: float, requests_per_s: float) -> float:
    """Convert an average byte count per request at a request rate into GB/month.

    Result is rounded to 3 decimals so the committed JSON is stable across platforms.
    """
    return round(bytes_per_request * requests_per_s * SECONDS_PER_MONTH / 1e9, 3)


# --------------------------------------------------------------------------- T1
T1_RATE = 50.0  # HTTP requests/s at web; stated production rate (03 §S8 default, about 129.6 M requests/month)
T1_SUMMARY = HERE.parent / "testbed" / "measurements" / "summary.csv"  # M07 step 7 output
T1_MEASURED = "measured:M07 kind testbed, 3 x 10 min locust runs (testbed/measurements/summary.csv)"
T1_COMPONENTS = [
    ("web", 2, 8, 0, "HTTP front end / page renderer (module spec 2 vCPU / 8 GB)"),
    ("api", 4, 16, 0, "application API (module spec 4 vCPU / 16 GB)"),
    ("cache", 2, 8, 0, "in-memory cache in front of db (module spec 2 vCPU / 8 GB)"),
    ("db", 4, 16, 200, "relational database, 200 GB data (module spec)"),
]
# (src, dst): what the measured bytes on that edge are
T1_EDGE_WHAT = {
    ("web", "api"): "HTTP requests web sends to api",
    ("api", "web"): "api JSON responses the pages are rendered from",
    ("api", "cache"): "redis commands (GET, and SET on a miss)",
    ("cache", "api"): "redis replies (cached JSON)",
    ("api", "db"): "postgres protocol: queries on cache misses and order writes",
    ("db", "api"): "postgres protocol: result rows and acknowledgements",
}


def t1_measured_bytes() -> dict[tuple[str, str], float]:
    """Return mean bytes per served web request per directed edge from the M07 summary."""
    with T1_SUMMARY.open(newline="", encoding="utf-8") as f:
        return {(r["src"], r["dst"]): float(r["bytes_per_request_mean"]) for r in csv.DictReader(f)}


def build_t1() -> dict:
    """Return the T1 three-tier topology with volumes measured on the M07 testbed."""
    bpr = t1_measured_bytes()
    edges = [
        {"src": s, "dst": d, "gb_per_month": gb_per_month(bpr[(s, d)], T1_RATE),
         "provenance": T1_MEASURED,
         "rationale": f"{bpr[(s, d)]:g} B per web request (measured) x {T1_RATE:g} req/s: {why}"}
        for (s, d), why in T1_EDGE_WHAT.items()
    ]
    internet_b = bpr[("web", "internet")]
    return {
        "id": "t1_three_tier",
        "description": "Three-tier web application (web, api, cache, db). The testbed application of M07.",
        "provenance": "measured",
        "assumptions": {
            "requests_per_s": T1_RATE,
            "bytes_per_request": {f"{s}->{d}": bpr[(s, d)] for (s, d) in T1_EDGE_WHAT},
            "internet_bytes_per_request": internet_b,
            "note": ("bytes_per_request = mean TCP-payload bytes per served web request over 3 runs "
                     "(testbed/measurements/summary.csv); volumes = bytes x requests_per_s x 2,592,000 s. "
                     "Rescale by changing requests_per_s."),
        },
        "references": [],
        "components": [
            {"id": c, "vcpu": v, "ram_gb": r, "storage_gb": st, "pinned_to": None, "rationale": why}
            for c, v, r, st, why in T1_COMPONENTS
        ],
        "edges": edges,
        "internet_egress": [{
            "src": "web", "gb_per_month": gb_per_month(internet_b, T1_RATE),
            "provenance": T1_MEASURED,
            "rationale": f"{internet_b:g} B HTTP response per web request (measured) x {T1_RATE:g} req/s to end users",
        }],
    }


# --------------------------------------------------------------------------- T2
T2_RAW_GB = 1000.0  # raw events arriving at ingest per month (about 386 kB/s, 3.1 Mbit/s average)
T2_COMPONENTS = [
    ("ingest", 2, 8, 0, "stateless HTTP/stream collector"),
    ("queue", 4, 16, 250, "log-structured queue; 7-day retention of 1 TB/month is about 233 GB"),
    ("transform-1", 4, 16, 0, "parse/clean/filter worker"),
    ("transform-2", 4, 16, 0, "sessionisation/enrichment worker"),
    ("aggregate", 4, 16, 0, "joins both transform outputs and rolls them up"),
    ("warehouse", 8, 32, 2000, "columnar warehouse, 2 TB (module spec); about 20 months at 100 GB/month"),
    ("dashboard", 2, 8, 0, "BI dashboard server"),
]
# (src, dst): (fraction of T2_RAW_GB, rationale)
T2_FRACTIONS = {
    ("ingest", "queue"): (1.00, "ingest forwards every raw event unchanged"),
    ("queue", "transform-1"): (1.00, "fan-out: transform-1 consumes the full topic"),
    ("queue", "transform-2"): (1.00, "fan-out: transform-2 consumes the full topic"),
    ("transform-1", "aggregate"): (0.30, "parsing and filtering keeps about 30% of the bytes"),
    ("transform-2", "aggregate"): (0.20, "sessionised records are about 20% of the raw bytes"),
    ("aggregate", "warehouse"): (0.10, "compressed columnar batches of rolled-up and retained detail rows, about 10%"),
    ("warehouse", "dashboard"): (0.02, "query result sets for dashboards, about 2%"),
    ("dashboard", "warehouse"): (0.001, "SQL queries sent to the warehouse, about 0.1%"),
}
T2_INTERNET_FRACTION = 0.01  # rendered dashboards and CSV exports to analysts


def build_t2() -> dict:
    """Return the T2 data-pipeline topology; volumes are fractions of 1 TB/month raw input."""
    edges = [
        {"src": s, "dst": d, "gb_per_month": round(f * T2_RAW_GB, 3),
         "provenance": "stated:fraction of 1 TB/month raw input",
         "rationale": f"{f:g} x {T2_RAW_GB:g} GB: {why}"}
        for (s, d), (f, why) in T2_FRACTIONS.items()
    ]
    return {
        "id": "t2_pipeline",
        "description": "Batch/stream data pipeline: ingest -> queue -> two transforms -> aggregate -> warehouse -> dashboard.",
        "provenance": "stated",
        "assumptions": {
            "raw_input_gb_per_month": T2_RAW_GB,
            "edge_fraction_of_raw": {f"{s}->{d}": f for (s, d), (f, _) in T2_FRACTIONS.items()},
            "internet_fraction_of_raw": T2_INTERNET_FRACTION,
            "note": "Raw input arrives from the internet (ingress, free, not modelled). Queue control traffic (acks, offsets) is under 1% and omitted.",
        },
        "references": [],
        "components": [
            {"id": c, "vcpu": v, "ram_gb": r, "storage_gb": st, "pinned_to": None, "rationale": why}
            for c, v, r, st, why in T2_COMPONENTS
        ],
        "edges": edges,
        "internet_egress": [{
            "src": "dashboard", "gb_per_month": round(T2_INTERNET_FRACTION * T2_RAW_GB, 3),
            "provenance": "stated:fraction of 1 TB/month raw input",
            "rationale": f"{T2_INTERNET_FRACTION:g} x {T2_RAW_GB:g} GB: dashboards and exports viewed by analysts",
        }],
    }


# --------------------------------------------------------------------------- T3
T3_REPO = "https://github.com/GoogleCloudPlatform/microservices-demo"
T3_RATE = 100.0          # HTTP requests/s at frontend (about 259 M requests/month)
T3_CART_ITEMS = 2        # average distinct items in a cart (stated)
T3_N_PRODUCTS = 9        # products in src/productcatalogservice/products.json (verified)
T3_REC_IDS = 5           # recommendationservice max_responses = 5 (verified)
T3_FRAMING_B = 150       # per gRPC message: HTTP/2 HEADERS (HPACK) + DATA frame + gRPC prefix + trailers (estimate)
T3_PAGE_B = 50_000       # rendered HTML page + amortised uncached static assets to the user (estimate)
T3_REDIRECT_B = 500      # 302 response from POST /setCurrency and POST /cart
n = T3_CART_ITEMS
# rpc: (request payload bytes, response payload bytes); protobuf sizes estimated from the .proto fields
T3_RPC_BYTES = {
    "GetSupportedCurrencies": (0, 165),         # about 33 three-letter codes
    "Convert": (30, 25),                         # Money (currency, units, nanos) + target code
    "ListProducts": (0, T3_N_PRODUCTS * 520),   # full catalog, about 520 B per product
    "GetProduct": (20, 520),
    "GetCart": (40, 40 + 30 * n),                # user id (UUID) -> items
    "AddItem": (70, 0),
    "EmptyCart": (40, 0),
    "ListRecommendations": (60, T3_REC_IDS * 12),
    "GetQuote": (100 + 30 * n, 25),              # address + items -> Money
    "GetAds": (20, 150),
    "PlaceOrder": (225, 180 + 55 * n),           # user, currency, address, email, card -> OrderResult
    "Charge": (75, 36),
    "ShipOrder": (100 + 30 * n, 20),
    "SendOrderConfirmation": (30 + 180 + 55 * n, 0),
    "redis:read": (100, 30 + 30 * n),            # RESP protocol, no gRPC framing
    "redis:write": (100 + 30 * n, 10),
}
T3_SERVICES = {  # rpc -> callee
    "GetSupportedCurrencies": "currency", "Convert": "currency",
    "ListProducts": "productcatalog", "GetProduct": "productcatalog",
    "GetCart": "cart", "AddItem": "cart", "EmptyCart": "cart",
    "ListRecommendations": "recommendation", "GetQuote": "shipping", "ShipOrder": "shipping",
    "GetAds": "ad", "PlaceOrder": "checkout", "Charge": "payment",
    "SendOrderConfirmation": "email", "redis:read": "redis-cart", "redis:write": "redis-cart",
}
# Calls each callee makes while serving one RPC: rpc -> [(nested rpc, count)]
T3_NESTED = {
    "ListRecommendations": [("ListProducts", 1)],                        # recommendation_server.py
    "PlaceOrder": [("GetCart", 1), ("GetProduct", n), ("Convert", n + 1), ("GetQuote", 1),
                   ("Charge", 1), ("ShipOrder", 1), ("EmptyCart", 1),
                   ("SendOrderConfirmation", 1)],                        # checkoutservice/main.go
    "GetCart": [("redis:read", 1)],
    "AddItem": [("redis:read", 1), ("redis:write", 1)],
    "EmptyCart": [("redis:write", 1)],
}
_REC = [("ListRecommendations", 1), ("GetProduct", T3_REC_IDS)]  # frontend rpc.go getRecommendations
# Frontend handler -> direct RPCs (src/frontend/handlers.go)
T3_HANDLERS = {
    "home": [("GetSupportedCurrencies", 1), ("ListProducts", 1), ("GetCart", 1),
             ("Convert", T3_N_PRODUCTS), ("GetAds", 1)],
    "product": [("GetProduct", 1), ("GetSupportedCurrencies", 1), ("GetCart", 1), ("Convert", 1),
                *_REC, ("GetAds", 1)],
    "add_to_cart": [("GetProduct", 1), ("AddItem", 1)],
    "view_cart": [("GetSupportedCurrencies", 1), ("GetCart", 1), *_REC, ("GetQuote", 1), ("Convert", 1),
                  ("GetProduct", n), ("Convert", n)],
    "place_order": [("PlaceOrder", 1), *_REC, ("GetSupportedCurrencies", 1)],
    "set_currency": [],
}
# HTTP requests per 19 locust task runs (weights index 1, setCurrency 2, browseProduct 10,
# addToCart 2, viewCart 3, checkout 1). The HTTP client follows 302s: POST /setCurrency -> GET /
# (no Referer sent), and addToCart does GET /product then POST /cart -> GET /cart.
T3_HANDLER_COUNTS = {"home": 1 + 2, "set_currency": 2, "product": 10 + 2, "add_to_cart": 2,
                     "view_cart": 3 + 2, "place_order": 1}
T3_RENDERED = {"home", "product", "view_cart", "place_order"}
T3_COMPONENTS = [
    ("frontend", 4, 16, "Go HTTP server; renders every page and fans out to 7 services"),
    ("cart", 2, 8, "C# cart service"), ("productcatalog", 2, 8, "Go catalog service"),
    ("currency", 2, 8, "Node.js currency conversion"), ("payment", 2, 8, "Node.js mock payment"),
    ("shipping", 2, 8, "Go shipping quotes/shipments"), ("email", 2, 8, "Python mock email"),
    ("checkout", 2, 8, "Go order orchestration"), ("recommendation", 2, 8, "Python recommendations"),
    ("ad", 2, 8, "Java text ads"), ("redis-cart", 2, 8, "Redis holding carts in memory"),
]


def t3_edge_bytes() -> dict[tuple[str, str], float]:
    """Return average bytes per frontend HTTP request on every directed T3 edge.

    Walks each handler's RPCs (and the RPCs the callees make in turn), weights handlers by
    the load-generator mix, and adds T3_FRAMING_B to every gRPC message. The request goes
    caller->callee and the response callee->caller.
    """
    total = sum(T3_HANDLER_COUNTS.values())
    out: dict[tuple[str, str], float] = {}

    def walk(caller: str, rpc: str, count: float) -> None:
        callee = T3_SERVICES[rpc]
        req, resp = T3_RPC_BYTES[rpc]
        frame = 0 if rpc.startswith("redis:") else T3_FRAMING_B
        out[(caller, callee)] = out.get((caller, callee), 0.0) + count * (req + frame)
        out[(callee, caller)] = out.get((callee, caller), 0.0) + count * (resp + frame)
        for sub, k in T3_NESTED.get(rpc, []):
            walk(callee, sub, count * k)

    for handler, calls in T3_HANDLERS.items():
        w = T3_HANDLER_COUNTS[handler] / total
        for rpc, k in calls:
            walk("frontend", rpc, w * k)
    return out


def build_t3() -> dict:
    """Return the T3 Online Boutique topology (11 services, request + response edges)."""
    total = sum(T3_HANDLER_COUNTS.values())
    edges = []
    for (s, d), b in sorted(t3_edge_bytes().items()):
        direction = "requests" if _is_caller(s, d) else "responses"
        edges.append({
            "src": s, "dst": d, "gb_per_month": gb_per_month(b, T3_RATE),
            "provenance": "stated:payload estimate x load-generator mix x 100 req/s",
            "rationale": f"{direction} {s}->{d}: {b:.0f} B per frontend request x {T3_RATE:g} req/s",
        })
    page_b = sum(T3_HANDLER_COUNTS[h] * (T3_PAGE_B if h in T3_RENDERED else T3_REDIRECT_B)
                 for h in T3_HANDLER_COUNTS) / total
    return {
        "id": "t3_microservices",
        "description": "Google Online Boutique (microservices-demo): 11 services, gRPC call graph from the source code.",
        "provenance": "stated",
        "assumptions": {
            "frontend_http_requests_per_s": T3_RATE,
            "handler_mix_per_25_requests": T3_HANDLER_COUNTS,
            "cart_items": T3_CART_ITEMS, "catalog_products": T3_N_PRODUCTS,
            "recommendation_ids": T3_REC_IDS, "grpc_framing_bytes_per_message": T3_FRAMING_B,
            "rpc_payload_bytes": {k: list(v) for k, v in T3_RPC_BYTES.items()},
            "page_bytes": T3_PAGE_B, "redirect_bytes": T3_REDIRECT_B,
            "note": "Call graph and counts verified in the repository source (evidence/logs/M06_online_boutique_sources.txt); payload sizes are estimates. loadgenerator is excluded (it stands in for users).",
        },
        "references": [
            f"GoogleCloudPlatform/microservices-demo (Online Boutique), {T3_REPO}, main branch, "
            "fetched 2026-09-21: src/frontend/handlers.go, src/frontend/rpc.go, "
            "src/checkoutservice/main.go, src/recommendationservice/recommendation_server.py, "
            "src/loadgenerator/locustfile.py, src/productcatalogservice/products.json",
        ],
        "components": [
            {"id": c, "vcpu": v, "ram_gb": r, "storage_gb": 0, "pinned_to": None, "rationale": why}
            for c, v, r, why in T3_COMPONENTS
        ],
        "edges": edges,
        "internet_egress": [{
            "src": "frontend", "gb_per_month": gb_per_month(page_b, T3_RATE),
            "provenance": "stated:page-size estimate x load-generator mix x 100 req/s",
            "rationale": f"{page_b:.0f} B per request ({T3_PAGE_B} B rendered pages, {T3_REDIRECT_B} B redirects) x {T3_RATE:g} req/s",
        }],
    }


def _is_caller(src: str, dst: str) -> bool:
    """True if src calls dst in the T3 call graph (so src->dst carries requests)."""
    callers = {("frontend", T3_SERVICES[r]) for calls in T3_HANDLERS.values() for r, _ in calls}
    for rpc, subs in T3_NESTED.items():
        callers |= {(T3_SERVICES[rpc], T3_SERVICES[s]) for s, _ in subs}
    return (src, dst) in callers


# --------------------------------------------------------------------------- README
def _table(doc: dict) -> list[str]:
    """Return markdown rows for one topology's edges and internet egress."""
    rows = ["| From | To | GB/month | Provenance | Rationale |", "|---|---|---:|---|---|"]
    for e in doc["edges"]:
        rows.append(f"| {e['src']} | {e['dst']} | {e['gb_per_month']:,.2f} | {e['provenance']} | {e['rationale']} |")
    for x in doc["internet_egress"]:
        rows.append(f"| {x['src']} | *internet* | {x['gb_per_month']:,.2f} | {x['provenance']} | {x['rationale']} |")
    s = summarise(doc)
    rows.append(f"| **total inter-component** | | **{s['inter_component_gb']:,.2f}** | | {s['edges']} directed edges |")
    return rows


def _components(doc: dict) -> list[str]:
    """Return markdown rows for one topology's components."""
    rows = ["| Component | vCPU | RAM GB | Storage GB | Pinned | Note |", "|---|---:|---:|---:|---|---|"]
    for c in doc["components"]:
        rows.append(f"| {c['id']} | {c['vcpu']} | {c['ram_gb']:g} | {c['storage_gb']:g} | {c['pinned_to'] or '-'} | {c.get('rationale', '')} |")
    return rows


def render_readme(docs: list[dict]) -> str:
    """Return topologies/README.md: conventions, then component and edge tables per topology."""
    t1, t2, t3 = docs
    lines = [
        "# Application topologies",
        "",
        "Generated by `python -m topologies.build`; do not edit by hand. Validate with",
        "`python -m topologies.validate topologies/*.json`. Schema: `schema.json` (JSON Schema 2020-12).",
        "",
        "Conventions: edges are **directed** and a request/response pair is two edges; the sender",
        "pays egress (D-005). Volumes are GB (10^9 bytes) per 30-day month. Provenance tags:",
        "`placeholder` (stand-in, replaced later), `stated` (derived from the stated assumptions",
        "below), `measured` (testbed, M07), `synthetic` (generated, M13). Every component is one",
        "VM sized to the smallest shape meeting its vCPU/RAM (D-004); `storage_gb` is priced as",
        "standard object storage. H1 needs at least 500 GB/month of inter-component traffic per",
        "topology; all three meet it (totals below).",
        "",
        "## T1 three-tier web (`t1_three_tier.json`), provenance: measured",
        "",
        "Bytes per served web request on each directed edge were measured on the M07 kind testbed",
        "(3 x 10 min locust runs, browse/detail/order mix 6/3/1; `testbed/measurements/summary.csv`,",
        "method in `testbed/README.md`). They are TCP-payload bytes, averaged over all requests of",
        "the mix. Volumes are those bytes at the stated production rate of",
        f"**{T1_RATE:g} HTTP requests/s** at `web`; to rescale, multiply by (new rate / {T1_RATE:g}).",
        "",
        *_components(t1), "", *_table(t1), "",
        "## T2 data pipeline (`t2_pipeline.json`), provenance: stated",
        "",
        f"Raw input is {T2_RAW_GB:g} GB/month (about 386 kB/s, 3.1 Mbit/s average) arriving from the",
        "internet (ingress is free and not modelled). Both transforms consume the full queue topic",
        "(fan-out, two different jobs), so the ingest side carries 3 TB/month; each later stage",
        "reduces the bytes. Queue control traffic (acks, offsets) is under 1% and omitted.",
        "",
        *_components(t2), "", *_table(t2), "",
        "## T3 microservices (`t3_microservices.json`), provenance: stated",
        "",
        f"Shape: Google's Online Boutique, {T3_REPO} (main branch, source read 2026-09-21).",
        "The 11 services and their calls come from the source: frontend handlers",
        "(`src/frontend/handlers.go`, `rpc.go`), checkout (`src/checkoutservice/main.go`),",
        "recommendation (`recommendation_server.py`, which lists the full catalog per call and",
        "returns at most 5 ids; the frontend then fetches each id with GetProduct), and cart ->",
        "redis-cart. `loadgenerator` is excluded; it stands in for the users.",
        "",
        f"Request mix: the repository's Locust weights (index 1, setCurrency 2, browseProduct 10,",
        "addToCart 2, viewCart 3, checkout 1). Following redirects, 19 task runs make 25 frontend",
        f"HTTP requests: {', '.join(f'{k} {v}' for k, v in T3_HANDLER_COUNTS.items())}.",
        f"Stated rate: **{T3_RATE:g} frontend HTTP requests/s** (about 259 M/month), an average cart",
        f"of {T3_CART_ITEMS} items, {T3_N_PRODUCTS} catalog products. Payload sizes are estimates of the",
        f"protobuf messages (listed in the JSON `assumptions.rpc_payload_bytes`), plus {T3_FRAMING_B} B",
        f"of HTTP/2 and gRPC framing per message. Users receive {T3_PAGE_B // 1000} kB per rendered page",
        f"(HTML plus amortised uncached static assets) and {T3_REDIRECT_B} B per redirect.",
        "M15 sweeps all volumes by 10^-2 to 10^2, which covers errors in these estimates.",
        "",
        *_components(t3), "", *_table(t3), "",
        "## Totals",
        "",
        "| Topology | Components | Directed edges | Inter-component GB/month | Internet GB/month |",
        "|---|---:|---:|---:|---:|",
    ]
    for d in docs:
        s = summarise(d)
        lines.append(f"| {s['id']} | {s['components']} | {s['edges']} | {s['inter_component_gb']:,.2f} | {s['internet_gb']:,.2f} |")
    return "\n".join(lines) + "\n"


def build_all() -> list[dict]:
    """Return the three topology documents (T1, T2, T3) without writing anything."""
    return [build_t1(), build_t2(), build_t3()]


FILENAMES = ["t1_three_tier.json", "t2_pipeline.json", "t3_microservices.json"]


def main() -> int:
    """Validate and write the three topology files and README.md; exit 1 if any is invalid."""
    log = get_logger("build_topologies")
    docs = build_all()
    for name, doc in zip(FILENAMES, docs):
        errors = validate_topology(doc)
        if errors:
            for err in errors:
                log.error("%s: %s", name, err)
            return 1
        (HERE / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
        s = summarise(doc)
        log.info("wrote %s: %d components, %d edges, inter_component_gb=%.2f internet_gb=%.2f",
                 name, s["components"], s["edges"], s["inter_component_gb"], s["internet_gb"])
    (HERE / "README.md").write_text(render_readme(docs), encoding="utf-8", newline="\n")
    log.info("wrote README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
