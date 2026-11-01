"""
GCP price puller (M04). Writes snapshots/<date>/gcp_{compute,egress,storage}.json.

Source order (D-021):
  (a) GCP_API_KEY in the environment or .env, and a test call to the Cloud Billing Catalog
      API returns 200  ->  official API (03_SKILLS S3).
  (b) the calculator price list (cloudpricingcalculator.appspot.com) - probed in M04 on
      2026-09-21, HTTP 404, so not implemented.
  (c) otherwise  ->  the public pricing pages on cloud.google.com, parsed by
      pricing/gcp_pages.py; also writes snapshots/<date>/gcp_manual.csv. This closes M04 as
      DONE_WITH_WAIVER.

IMPORTANT MODELLING NOTE
GCP does not price whole instance types. Compute Engine SKUs are priced per vCPU-hour and
per GiB-RAM-hour separately, by machine family. An "n2-standard-4" cost must therefore be
COMPOSED as  4 * core_rate + 16 * ram_rate. Only the N2 family is kept (comparable to
AWS m5 and Azure Dsv5). Network is Premium Tier (the GCP default).

The API key never reaches a log or a file: every log record passes through `redact()`, and
HTTP errors are re-raised with the query string removed.

Usage:  python -m pricing.pull_gcp [--source auto|api|pages] [--record-sample]
"""
import argparse
import csv
import json
import logging
import os
import re
import sys

import requests

from pricing import gcp_pages
from pricing.common import LOCATIONS_EXT, ROOT, SNAPSHOT_DATE, SNAPSHOT_DIR, write_snapshot
from pricing.gcp_regions import CONTINENT_GROUPS, INTER_REGION_GROUP, PRICING_GROUP, unmapped_regions

BASE = "https://cloudbilling.googleapis.com/v1"
COMPUTE_ENGINE_SERVICE = "6F81-5844-456A"
EVIDENCE_LOG = ROOT / "evidence" / "logs" / "M04_gcp_pull.txt"
SAMPLE_PATH = ROOT / "tests" / "data" / "gcp_sample.json"
SAMPLE_REGIONS = ["us-east4", "europe-west3", "southamerica-east1"]
REGIONS = LOCATIONS_EXT["gcp"]

_KEY_RE = re.compile(r"key=[^&\s\"'<>]*")
_AIZA_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")


def redact(text: str) -> str:
    """Remove API-key material from a string: `key=<value>` pairs and bare Google keys.

    The replacement deliberately does not contain the text "key=" so the M04 acceptance
    grep (`key=` count must be 0) stays meaningful.
    """
    return _AIZA_RE.sub("[redacted]", _KEY_RE.sub("[api-key-redacted]", text))


class RedactFilter(logging.Filter):
    """Logging filter that renders each record and passes it through `redact()`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def get_logger() -> logging.Logger:
    """Logger writing to stdout and evidence/logs/M04_gcp_pull.txt (UTF-8), key-redacted.

    Written directly as UTF-8 because PowerShell 5.1 `Tee-Object` writes UTF-16.
    """
    log = logging.getLogger("gcp")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(name)-6s  %(levelname)-7s  %(message)s")
    EVIDENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(EVIDENCE_LOG, "w", encoding="utf-8")):
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        log.addHandler(h)
    return log


def load_api_key() -> str:
    """Return GCP_API_KEY from the environment, else from `.env` at the repo root, else ''."""
    key = os.environ.get("GCP_API_KEY", "").strip()
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GCP_API_KEY":
                key = value.strip().strip("\"'")
    return key


# ---------------------------------------------------------------- (a) official API

def api_get(path: str, key: str, log, params: dict = None) -> dict:
    """GET a Cloud Billing Catalog API path; errors are re-raised with the key redacted."""
    try:
        r = requests.get(f"{BASE}/{path}", params={**(params or {}), "key": key}, timeout=60)
        log.info("GET %s/%s -> HTTP %s", BASE, path, r.status_code)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        raise RuntimeError(redact(str(exc))) from None


def api_available(key: str, log) -> bool:
    """Preflight: True if `GET /v1/services?pageSize=1` succeeds with this key."""
    try:
        api_get("services", key, log, {"pageSize": 1})
        return True
    except RuntimeError as exc:
        log.warning("Cloud Billing API test call failed: %s", exc)
        return False


def _paged(path: str, field: str, key: str, log) -> list:
    rows, token = [], None
    while True:
        params = {"pageSize": 5000, **({"pageToken": token} if token else {})}
        data = api_get(path, key, log, params)
        rows.extend(data.get(field, []))
        token = data.get("nextPageToken")
        if not token:
            log.info("%s: %d %s", path, len(rows), field)
            return rows


def find_service_id(services: list, display_name: str) -> str:
    """Return the serviceId whose displayName matches exactly; raise KeyError if absent."""
    for s in services:
        if s.get("displayName") == display_name:
            return s["serviceId"]
    raise KeyError(f"service {display_name!r} not in services list")


def sku_tiers(sku: dict) -> list:
    """Return [(start_usage_amount, usd)] for a SKU's first pricingInfo; [] if absent."""
    try:
        rates = sku["pricingInfo"][0]["pricingExpression"]["tieredRates"]
    except (KeyError, IndexError):
        return []
    return [(float(t.get("startUsageAmount", 0)),
             int(t["unitPrice"].get("units", 0) or 0) + int(t["unitPrice"].get("nanos", 0) or 0) / 1e9)
            for t in rates]


def first_paid(tiers: list):
    """Price of the first tier with price > 0 (03_SKILLS S3 base rate), or None."""
    return next((usd for _, usd in tiers if usd > 0), None)


_N2_RE = re.compile(r"^N2 Instance (Core|Ram) running in ")


def parse_api_compute(skus: list, regions: list) -> list:
    """N2 on-demand core and RAM rates per region from Compute Engine SKUs.

    Keeps resourceFamily Compute, usageType OnDemand, resourceGroup CPU/RAM and a
    description starting "N2 Instance Core/Ram running in" (so custom, sole-tenant and other
    families are excluded). Two different rates for one region/resource raise ValueError.
    """
    found = {}
    for sku in skus:
        cat = sku.get("category", {})
        m = _N2_RE.match(sku.get("description", ""))
        if not m or cat.get("resourceFamily") != "Compute" or cat.get("usageType") != "OnDemand" \
                or cat.get("resourceGroup") not in ("CPU", "RAM"):
            continue
        usd = first_paid(sku_tiers(sku))
        resource = "core" if m.group(1) == "Core" else "ram"
        for region in sku.get("serviceRegions", []):
            if region in regions and usd is not None:
                k = (region, resource)
                if k in found and found[k][0] != usd:
                    raise ValueError(f"conflicting N2 {resource} rates in {region}")
                found[k] = (usd, sku.get("skuId"))
    return [{"provider": "gcp", "region": r, "family": "N2", "usage": "OnDemand", "resource": res,
             "usd_per_hour": usd, "unit": "vCPU-hour" if res == "core" else "GiB-hour",
             "sku_id": sku_id, "source": "api"}
            for (r, res), (usd, sku_id) in sorted(found.items())]


_EGRESS_RE = re.compile(
    r"^Network (Internet|Inter Region) (?:Egress|Data Transfer Out) from (.+?) to (.+)$")


def parse_api_egress(skus: list, regions: list) -> list:
    """Premium-tier egress SKUs parsed into (kind, from_group, to_group, tiers).

    Descriptions follow "Network Internet|Inter Region Egress|Data Transfer Out from <A> to
    <B>" (03_SKILLS S3); Standard Tier SKUs are dropped. Internet rows are expanded to every
    ext region whose PRICING_GROUP equals <A>. All tiers are kept (per GiB, as in the API).
    """
    rows = []
    for sku in skus:
        desc = sku.get("description", "")
        m = _EGRESS_RE.match(desc)
        if sku.get("category", {}).get("resourceFamily") != "Network" or not m or "Standard Tier" in desc:
            continue
        kind = "internet" if m.group(1) == "Internet" else "inter_region"
        tiers = sku_tiers(sku)
        senders = [r for r in regions if PRICING_GROUP[r] == m.group(2)] if kind == "internet" else [None]
        for region in senders:
            for i, (lo, usd) in enumerate(tiers):
                hi = tiers[i + 1][0] if i + 1 < len(tiers) else None
                rows.append({"provider": "gcp", "kind": kind, "network_tier": "premium",
                             "from_region": region, "from_group": m.group(2), "to_group": m.group(3),
                             "tier_min_gib": lo, "tier_max_gib": hi, "usd_per_gib": usd,
                             "usd_per_gb": round(usd / gcp_pages.GIB_IN_GB, 9),
                             "sku_id": sku.get("skuId"), "source": "api"})
    return rows


def parse_api_storage(skus: list, regions: list) -> list:
    """Standard-class regional Cloud Storage rate per region (first tier, per GiB-month)."""
    found = {}
    for sku in skus:
        cat = sku.get("category", {})
        if cat.get("resourceFamily") != "Storage" or cat.get("resourceGroup") != "RegionalStorage" \
                or not sku.get("description", "").startswith("Standard Storage"):
            continue
        sr = sku.get("serviceRegions", [])
        tiers = sku_tiers(sku)
        if len(sr) == 1 and sr[0] in regions and tiers:
            found[sr[0]] = tiers[0][1]
    return [{"provider": "gcp", "region": r, "storage_class": "STANDARD", "location_type": "region",
             "tier_min_gb": 0, "usd_per_gib_month": usd,
             "usd_per_gb_month": round(usd / gcp_pages.GIB_IN_GB, 9), "source": "api"}
            for r, usd in sorted(found.items())]


def pull_from_api(key: str, log) -> tuple:
    """Pull compute, egress and storage rows from the Cloud Billing Catalog API."""
    services = _paged("services", "services", key, log)
    storage_id = find_service_id(services, "Cloud Storage")
    log.info("Cloud Storage service id discovered: %s", storage_id)
    ce = _paged(f"services/{COMPUTE_ENGINE_SERVICE}/skus", "skus", key, log)
    st = _paged(f"services/{storage_id}/skus", "skus", key, log)
    meta = {"source": "cloud_billing_catalog_api", "api": BASE, "auth": "api_key",
            "compute_service": COMPUTE_ENGINE_SERVICE, "storage_service": storage_id}
    return (parse_api_compute(ce, REGIONS), parse_api_egress(ce, REGIONS),
            parse_api_storage(st, REGIONS), meta)


# ---------------------------------------------------------------- (c) public pages

def pull_from_pages(log, record_sample: bool = False) -> tuple:
    """Pull compute, egress and storage rows from the public pricing pages (gcp_pages)."""
    compute_page, compute_prov = gcp_pages.fetch_page(gcp_pages.COMPUTE_URL, log)
    network_page, network_prov = gcp_pages.fetch_page(gcp_pages.NETWORK_URL, log)
    storage_page, storage_prov = gcp_pages.fetch_page(gcp_pages.STORAGE_URL, log)

    section = gcp_pages.extract_n2_section(compute_page)
    tables = gcp_pages.parse_n2_tables(section)
    log.info("compute: N2 hourly tables for %d regions", len(tables))
    compute = gcp_pages.build_compute_rows(tables, REGIONS, gcp_pages.COMPUTE_URL)
    internet = gcp_pages.parse_internet_egress(network_page, REGIONS, PRICING_GROUP.get, gcp_pages.NETWORK_URL)
    inter = gcp_pages.parse_inter_region_matrix(network_page, gcp_pages.NETWORK_URL)
    storage = gcp_pages.parse_standard_storage(storage_page, REGIONS, gcp_pages.STORAGE_URL)

    if record_sample:
        sample = {
            "_note": "Verbatim excerpts of the public GCP pricing pages (no API key involved), "
                     "recorded by `python -m pricing.pull_gcp --record-sample`.",
            "regions": SAMPLE_REGIONS,
            "provenance": [compute_prov, network_prov, storage_prov],
            "compute_n2_excerpt": gcp_pages.excerpt_regions(section, SAMPLE_REGIONS),
            "network_internet_excerpt": gcp_pages.excerpt_regions(network_page, SAMPLE_REGIONS),
            "network_inter_region_html": gcp_pages.inter_region_excerpt(network_page),
            "storage_excerpt": gcp_pages.excerpt_regions(storage_page, SAMPLE_REGIONS),
        }
        SAMPLE_PATH.write_text(json.dumps(sample, indent=1), encoding="utf-8")
        log.info("recorded offline test sample %s (%d bytes)", SAMPLE_PATH.relative_to(ROOT),
                 SAMPLE_PATH.stat().st_size)

    meta = {"source": "public_pricing_pages", "waiver": "D-021 path (c): no API key; "
            "calculator price list returned HTTP 404", "pages": [compute_prov, network_prov, storage_prov]}
    return compute, internet + inter, storage, meta


def write_manual_csv(compute: list, egress: list, storage: list, meta: dict) -> str:
    """Write snapshots/<date>/gcp_manual.csv: every figure in one flat table with its page."""
    accessed = {p["url"]: p["accessed_utc"] for p in meta.get("pages", [])}
    path = SNAPSHOT_DIR / "gcp_manual.csv"
    cols = ["kind", "region", "from_group", "to_group", "item", "tier_min_gib", "tier_max_gib",
            "unit", "usd", "source_url", "accessed_utc"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in compute:
            w.writerow({"kind": "compute", "region": r["region"], "item": f"N2 {r['resource']} (derived)",
                        "unit": f"USD per {r['unit']}", "usd": r["usd_per_hour"],
                        "source_url": r["source"], "accessed_utc": accessed.get(r["source"])})
        for r in egress:
            w.writerow({"kind": r["kind"], "region": r["from_region"] or "", "from_group": r["from_group"],
                        "to_group": r["to_group"], "item": "premium tier data transfer out",
                        "tier_min_gib": r["tier_min_gib"], "tier_max_gib": r["tier_max_gib"],
                        "unit": "USD per GiB", "usd": r["usd_per_gib"], "source_url": r["source"],
                        "accessed_utc": accessed.get(r["source"])})
        for r in storage:
            w.writerow({"kind": "storage", "region": r["region"], "item": "Standard storage, region",
                        "unit": "USD per GiB-month", "usd": r["usd_per_gib_month"],
                        "source_url": r["source"], "accessed_utc": accessed.get(r["source"])})
    return str(path.relative_to(ROOT))


def summarize(compute: list, egress: list, storage: list, log) -> bool:
    """Log the A1-A3 acceptance facts and return True if all hold."""
    ok = True
    for r in REGIONS:
        n = {res: sum(1 for c in compute if c["region"] == r and c["resource"] == res) for res in ("core", "ram")}
        rates = {c["resource"]: c["usd_per_hour"] for c in compute if c["region"] == r}
        log.info("A1 %-20s core=%s ram=%s  counts=%s", r, rates.get("core"), rates.get("ram"), n)
        ok &= n == {"core": 1, "ram": 1}
    internet_regions = {e["from_region"] for e in egress if e["kind"] == "internet"}
    for g in CONTINENT_GROUPS:
        members = [r for r in REGIONS if PRICING_GROUP[r] == g]
        have = [r for r in members if r in internet_regions]
        log.info("A2 internet %-8s regions with rates %d/%d", g, len(have), len(members))
        ok &= len(have) == len(members) > 0
    inter = {(e["from_group"], e["to_group"]) for e in egress if e["kind"] == "inter_region"}
    groups = sorted(set(INTER_REGION_GROUP.values()))
    missing = [(a, b) for a in groups for b in groups if (a, b) not in inter]
    log.info("A2 inter-region group pairs for ext regions: %d/%d present, missing=%s",
             len(groups) ** 2 - len(missing), len(groups) ** 2, missing)
    ok &= not missing
    have_storage = {s["region"] for s in storage}
    log.info("A3 storage regions %d/%d, missing=%s", len(have_storage & set(REGIONS)), len(REGIONS),
             sorted(set(REGIONS) - have_storage))
    ok &= set(REGIONS) <= have_storage
    return ok


def main(argv: list = None) -> int:
    """Run the GCP pull; returns 0 if the A1-A3 facts hold, 1 otherwise."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--source", choices=["auto", "api", "pages"], default="auto")
    ap.add_argument("--record-sample", action="store_true", help="write tests/data/gcp_sample.json")
    args = ap.parse_args(argv)
    log = get_logger()
    log.info("snapshot_date=%s  regions=%s", SNAPSHOT_DATE, REGIONS)
    if unmapped_regions():
        raise SystemExit(f"regions missing from gcp_regions: {unmapped_regions()}")

    key = load_api_key() if args.source in ("auto", "api") else ""
    log.info("GCP_API_KEY present: %s", bool(key))
    use_api = bool(key) and api_available(key, log)
    if args.source == "api" and not use_api:
        raise SystemExit("--source api requested but the Cloud Billing API is not usable")
    if use_api:
        compute, egress, storage, meta = pull_from_api(key, log)
    else:
        log.info("using key-free public pricing pages (D-021 path c)")
        compute, egress, storage, meta = pull_from_pages(log, record_sample=args.record_sample)

    meta.update({"network_tier": "premium", "compute_family": "N2", "regions": REGIONS,
                 "units": "compute USD per vCPU-hour / GiB-hour; egress usd_per_gib and usd_per_gb "
                          "(1 GiB = 1.073741824 GB); storage usd_per_gib_month and usd_per_gb_month"})
    write_snapshot("gcp_compute", compute, log, meta=meta)
    write_snapshot("gcp_egress", egress, log, meta=meta)
    write_snapshot("gcp_storage", storage, log, meta=meta)
    if meta["source"] == "public_pricing_pages":
        log.info("WROTE %s", write_manual_csv(compute, egress, storage, meta))
    ok = summarize(compute, egress, storage, log)
    log.info("gcp pull complete: acceptance facts A1-A3 %s", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
