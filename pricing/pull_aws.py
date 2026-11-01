"""
AWS Price List Bulk API puller.

No account and no credentials needed - the bulk offer files are public objects. The trap is
SIZE: the global EC2 index is several GB and even one region's CSV is hundreds of MB. We never
download the global index; for each of the 8 `ext` regions we stream that region's CSV and keep
only the rows we need, so memory stays flat. Writes to snapshots/<date>/:
  aws_compute.json  m5.{large,xlarge,2xlarge,4xlarge} Linux on-demand hourly prices, with vCPU/RAM
  aws_egress.json   AWSDataTransfer: internet-out tiers and inter-region outbound pairs (`kind`)
  aws_storage.json  S3 Standard storage tiers in USD per GB-month

Docs: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-ppslong.html

Usage:  python -m pricing.pull_aws
"""
import csv
import time

import requests

from pricing.aws_regions import AWS_LOCATION_NAMES
from pricing.common import LOCATIONS_EXT, get_json, get_logger, peak_rss_mb, write_snapshot

BASE = "https://pricing.us-east-1.amazonaws.com"
OFFER = BASE + "/offers/v1.0/aws/{offer}/current/region_index.json"
EC2_REGION_INDEX = OFFER.format(offer="AmazonEC2")
DT_REGION_INDEX = OFFER.format(offer="AWSDataTransfer")
S3_REGION_INDEX = OFFER.format(offer="AmazonS3")
log = get_logger("aws")

REGIONS = LOCATIONS_EXT["aws"]
META_LINES = 5  # AWS offer CSVs start with 5 metadata lines; the header is line 6
ATTEMPTS = 6

# Instance family (D-024): m5 = general purpose, Intel, 4 GiB per vCPU, the same class as Azure
# Dsv5 and GCP N2 (03_SKILLS S5). instance_type -> (project shape, vcpu, ram_gb).
M5_SHAPES = {
    "m5.large": ("small", 2, 8.0),
    "m5.xlarge": ("medium", 4, 16.0),
    "m5.2xlarge": ("large", 8, 32.0),
    "m5.4xlarge": ("xlarge", 16, 64.0),
}


def iter_offer_rows(lines, only=None):
    """Yield dict rows from the text lines of an AWS offer CSV, with lower-cased column names.

    Skips the 5 metadata lines and reads the header on line 6. `only` is an optional
    (column, allowed_values) pair applied on the raw row before a dict is built, which keeps
    scanning a multi-hundred-MB EC2 file cheap. Column names differ slightly between offer
    versions (`Capacitystatus` vs `CapacityStatus`), hence the lower-casing.
    """
    reader = csv.reader(lines)
    for _ in range(META_LINES):
        next(reader)
    header = [h.strip().lower() for h in next(reader)]
    idx = header.index(only[0]) if only else None
    for row in reader:
        if idx is not None and (len(row) <= idx or row[idx] not in only[1]):
            continue
        yield dict(zip(header, row))


def _stream_lines(url, session):
    """Yield decoded text lines of a large CSV without buffering the body."""
    with session.get(url, stream=True, timeout=(30, 300)) as r:
        log.info("GET %s -> HTTP %s", url.replace(BASE, ""), r.status_code)
        r.raise_for_status()
        for ln in r.iter_lines():
            yield ln.decode("utf-8", "replace")


def _retrying(fn, what):
    """Run fn(); on a network failure retry the whole call (a stream cannot resume mid-file).

    The AWS pricing host sometimes resets connections for several minutes after a large
    download (seen during M03), so the back-off is long: 10, 20, 40, 80, 160 s.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fn()
        except (requests.RequestException, OSError) as exc:
            if attempt == ATTEMPTS:
                raise
            wait = 10 * 2 ** (attempt - 1)
            log.warning("%s: attempt %d failed (%s: %s); retrying in %ds",
                        what, attempt, type(exc).__name__, exc, wait)
            time.sleep(wait)


def _get_index(url):
    """Fetch a region_index.json with the long back-off of `_retrying`."""
    return _retrying(lambda: get_json(url, log, retries=1), f"index {url.split('/')[-3]}")


def _region_csv_url(index, region):
    entry = index["regions"].get(region)
    if not entry:
        return None
    return BASE + entry["currentVersionUrl"].replace(".json", ".csv")


def _num(text):
    """Parse a price/range cell; 'Inf' (open-ended tier) becomes None."""
    if text in ("", "Inf"):
        return None
    return float(text)


def _check_location(row, region, what):
    """Warn if a row's Location text disagrees with aws_regions.py (renamed region?)."""
    loc = row.get("location") or row.get("from location")
    if loc and loc != AWS_LOCATION_NAMES[region]:
        log.warning("%s: region %s has Location %r, expected %r", what, region, loc,
                    AWS_LOCATION_NAMES[region])


def parse_compute(rows, region):
    """Keep Linux, shared-tenancy, on-demand, no-licence m5 rows of the four project shapes."""
    out = []
    for r in rows:
        shape = M5_SHAPES.get(r.get("instance type"))
        if shape is None:
            continue
        if r.get("termtype") != "OnDemand" or r.get("tenancy") != "Shared":
            continue
        if r.get("operating system") != "Linux" or r.get("pre installed s/w") not in ("", "NA"):
            continue
        if r.get("capacitystatus") != "Used" or r.get("unit") != "Hrs":
            continue
        if r.get("product family") != "Compute Instance":
            continue
        price = _num(r.get("priceperunit", ""))
        if not price or price <= 0:
            continue
        name, vcpu, ram_gb = shape
        _check_location(r, region, "compute")
        if int(r["vcpu"]) != vcpu or float(r["memory"].split()[0]) != ram_gb:
            log.warning("compute: %s in %s has vcpu=%s memory=%s, expected %s/%s - dropped",
                        r["instance type"], region, r["vcpu"], r["memory"], vcpu, ram_gb)
            continue
        out.append({
            "provider": "aws",
            "region": region,
            "instance_type": r["instance type"],
            "shape": name,
            "vcpu": vcpu,
            "ram_gb": ram_gb,
            "usd_per_hour": price,
            "sku": r["sku"],
            "rate_code": r["ratecode"],
            "effective_date": r.get("effectivedate"),
        })
    return out


def pull_compute(session):
    idx = _get_index(EC2_REGION_INDEX)
    out = []
    for region in REGIONS:
        url = _region_csv_url(idx, region)
        if url is None:
            log.error("compute: region %s missing from EC2 region index", region)
            continue

        def one_region():
            seen = [0]

            def counted():
                t_start = time.time()
                for ln in _stream_lines(url, session):
                    seen[0] += 1
                    if seen[0] % 200_000 == 0:  # makes a throttled (trickling) download visible
                        log.info("  ... %s: %d lines in %.0fs", region, seen[0], time.time() - t_start)
                    yield ln

            rows = iter_offer_rows(counted(), only=("instance type", set(M5_SHAPES)))
            return parse_compute(rows, region), seen[0]

        t0 = time.time()
        kept, lines = _retrying(one_region, f"compute {region}")
        log.info("compute: region=%s  scanned=%d lines  kept=%d  download+scan=%.1fs  peak_rss=%.0f MB",
                 region, lines, len(kept), time.time() - t0, peak_rss_mb())
        out.extend(kept)
    return out


def parse_egress(rows, region):
    """Keep internet-out tiers and sender-side inter-region pairs for one region's DT file.

    A region's AWSDataTransfer file also lists rows *sent to* that region from every other
    region, so a pair is kept only when the row's From Region Code is this region (sender pays,
    D-005) and its To Region Code is one of the ext regions. Ranges are in GB per month; a
    `None` upper bound is open-ended. The global 0-100 GB internet allowance is a region-less
    row priced 0; it is kept as kind `internet_free_allowance` so the base-rate choice is auditable.
    """
    out = []
    for r in rows:
        if r.get("termtype") != "OnDemand" or r.get("unit") != "GB":
            continue
        ttype = r.get("transfer type")
        price = _num(r.get("priceperunit", ""))
        if price is None:
            continue
        common = {
            "provider": "aws",
            "region": region,
            "tier_min_gb": _num(r["startingrange"]) or 0.0,
            "tier_max_gb": _num(r["endingrange"]),
            "usd_per_gb": price,
            "usage_type": r.get("usagetype"),
            "sku": r["sku"],
            "effective_date": r.get("effectivedate"),
        }
        if ttype == "AWS Outbound" and r.get("to location") == "External":
            if r.get("from region code") == region:
                out.append({**common, "kind": "internet"})
            elif not r.get("from region code") and price == 0:
                out.append({**common, "kind": "internet_free_allowance"})
        elif (ttype == "InterRegion Outbound" and r.get("from region code") == region
              and r.get("from location type") == "AWS Region" and r.get("to location type") == "AWS Region"
              and r.get("to region code") in REGIONS and r["to region code"] != region):
            out.append({**common, "kind": "inter_region", "dst_region": r["to region code"]})
    return out


def pull_egress(session):
    idx = _get_index(DT_REGION_INDEX)
    out = []
    for region in REGIONS:
        url = _region_csv_url(idx, region)
        if url is None:
            log.error("egress: region %s missing from AWSDataTransfer region index", region)
            continue
        t0 = time.time()
        kept = _retrying(lambda: parse_egress(iter_offer_rows(_stream_lines(url, session)), region),
                         f"egress {region}")
        pairs = sum(1 for k in kept if k["kind"] == "inter_region")
        log.info("egress: region=%s  kept=%d (internet tiers=%d, inter-region pairs=%d)  %.1fs",
                 region, len(kept), sum(1 for k in kept if k["kind"] == "internet"), pairs, time.time() - t0)
        out.extend(kept)
    return out


def parse_storage(rows, region):
    """S3 Standard ('General Purpose' / 'Standard') TimedStorage tiers in USD per GB-month."""
    out = []
    for r in rows:
        if r.get("product family") != "Storage" or r.get("termtype") != "OnDemand":
            continue
        if r.get("storage class") != "General Purpose" or r.get("volume type") != "Standard":
            continue
        usage = r.get("usagetype", "")
        if not usage.endswith("TimedStorage-ByteHrs") or "Annotation" in usage:
            continue
        if r.get("unit") != "GB-Mo" or r.get("region code") != region:
            continue
        _check_location(r, region, "storage")
        out.append({
            "provider": "aws",
            "region": region,
            "storage_class": "S3 Standard",
            "tier_min_gb": _num(r["startingrange"]) or 0.0,
            "tier_max_gb": _num(r["endingrange"]),
            "usd_per_gb_month": float(r["priceperunit"]),
            "usage_type": usage,
            "sku": r["sku"],
            "effective_date": r.get("effectivedate"),
        })
    return out


def pull_storage(session):
    idx = _get_index(S3_REGION_INDEX)
    out = []
    for region in REGIONS:
        url = _region_csv_url(idx, region)
        if url is None:
            log.error("storage: region %s missing from S3 region index", region)
            continue
        t0 = time.time()
        kept = _retrying(lambda: parse_storage(iter_offer_rows(_stream_lines(url, session)), region),
                         f"storage {region}")
        log.info("storage: region=%s  kept=%d  %.1fs", region, len(kept), time.time() - t0)
        out.extend(kept)
    return out


def first_paid_internet_rate(egress_rows, region):
    """Lowest-tier internet row with a price > 0 for `region` (D-007 flattening, done in M05)."""
    tiers = [r for r in egress_rows
             if r["region"] == region and r["kind"] == "internet" and r["usd_per_gb"] > 0]
    return min(tiers, key=lambda r: r["tier_min_gb"]) if tiers else None


def summarise(compute, egress, storage):
    log.info("SUMMARY rows: compute=%d egress=%d storage=%d", len(compute), len(egress), len(storage))
    log.info("%-16s %-8s %-22s %-20s %-6s %-12s", "region", "shapes", "m5.large $/h",
             "internet 1st tier", "pairs", "S3 $/GB-mo")
    for region in REGIONS:
        c = [r for r in compute if r["region"] == region]
        small = [r["usd_per_hour"] for r in c if r["shape"] == "small"]
        paid = first_paid_internet_rate(egress, region)
        pairs = sum(1 for r in egress if r["region"] == region and r["kind"] == "inter_region")
        s3 = [r["usd_per_gb_month"] for r in storage if r["region"] == region and r["tier_min_gb"] == 0]
        log.info("%-16s %-8s %-22s %-20s %-6d %-12s", region, len({r["shape"] for r in c}),
                 f"{min(small):.4f}" if small else "MISSING",
                 f"{paid['usd_per_gb']:.4f} (>{paid['tier_min_gb']:g}GB)" if paid else "MISSING",
                 pairs, f"{s3[0]:.4f}" if s3 else "MISSING")


def main():
    session = requests.Session()
    t0 = time.time()
    compute = pull_compute(session)
    write_snapshot("aws_compute", compute, log,
                   meta={"api": EC2_REGION_INDEX, "auth": "none", "regions": REGIONS,
                         "family": "m5", "os": "Linux", "tenancy": "Shared", "term": "OnDemand"})
    egress = pull_egress(session)
    write_snapshot("aws_egress", egress, log,
                   meta={"api": DT_REGION_INDEX, "auth": "none", "regions": REGIONS,
                         "note": "region = sending region; tiers not flattened here; the global "
                                 "0-100 GB internet allowance is kind internet_free_allowance"})
    storage = pull_storage(session)
    write_snapshot("aws_storage", storage, log,
                   meta={"api": S3_REGION_INDEX, "auth": "none", "regions": REGIONS,
                         "class": "S3 Standard"})
    summarise(compute, egress, storage)
    log.info("PEAK_RSS_MB=%.0f  total_time=%.0fs", peak_rss_mb(), time.time() - t0)
    log.info("aws pull complete")


if __name__ == "__main__":
    main()
