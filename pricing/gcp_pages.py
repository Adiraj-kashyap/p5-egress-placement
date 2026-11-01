"""Key-free GCP price source: the public pricing pages on cloud.google.com (D-021 path c).

Used by pull_gcp.py when no GCP_API_KEY is available. Instead of hand-typing numbers into
gcp_manual.csv, this module downloads the pages and parses the price tables they embed, so
the transcription is reproducible and every number traces to a page, a region label and an
access time.

Page layout (observed 2026-09-21). The pricing pages render one region (Iowa) as HTML and
embed every other region's table in a JSON-like data blob. In that blob each table is
immediately followed by its region label, e.g. `..."$0.124718 / 1 hour"]],1]]]],"Tokyo
(asia-northeast1)",[3],1]`. So the text between two consecutive labels is one region's table
(`split_region_tables`). The inter-region matrix on the network page is a plain HTML table.

Units: the pages quote network and storage per GiB (2^30 bytes); the project unit is GB
(10^9 bytes, 01_CONVENTIONS S3). Rows keep the page's per-GiB figure and add the per-GB
conversion. N2 compute is published per machine type; the per-vCPU and per-GiB-RAM rates
(03_SKILLS S3) are recovered by least squares over all N2 predefined machine types of a
region, and the fit residual is recorded.
"""
import hashlib
import html
import re
import time

import requests

COMPUTE_URL = "https://cloud.google.com/products/compute/pricing/general-purpose"
NETWORK_URL = "https://cloud.google.com/vpc/network-pricing"
STORAGE_URL = "https://cloud.google.com/storage/pricing"
USER_AGENT = "Mozilla/5.0 (P5 pricing snapshot; read-only)"

GIB_IN_GB = 1.073741824  # 1 GiB = 2^30 bytes = 1.073741824 GB
FIT_TOLERANCE = 1e-5     # USD/hour; published machine prices carry 6 decimals
HOURS_PER_MONTH = 730    # 01_CONVENTIONS S3, also the pages' own hour->month factor

LABEL_RE = re.compile(r'"([^"\\]{1,60}) \(([a-z]+-[a-z]+\d+)\)",\[(\d+)\]')
N2_ANCHOR = '1,"n2-machine-types"],[[1,2,3]'
SECTION_ANCHOR_RE = re.compile(r'1,"[a-z0-9-]+-machine-types"\],\[\[1,2,3\]')
_CELL = r'\[1,1,null,\[null,\[null,"\\u003cp\\u003e'
N2_ROW_RE = re.compile(
    r'(n2-(?:standard|highmem|highcpu)-\d+)\\u003c/p\\u003e"\]\]\],'
    + _CELL + r'(\d+)\\u003c/p\\u003e"\]\]\],'
    + _CELL + r'([\d.]+) GiB\\u003c/p\\u003e"\]\]\],'
    + r'\[1,1,null,\[null,\[null,"\$([\d.]+) / 1 hour"')
INTERNET_SPLIT = "Network (data transfer out) TO "
TIER_RE = re.compile(
    r'\[null,\[null,"([\d,]+) gibibyte (?:to ([\d,]+) gibibyte|and above)"\]\],'
    r'\[null,\[null,"\$([\d.]+)(?: \(Free\))? / 1 gibibyte')
# Any price cell; the unit is checked separately so a column can never be skipped. The first
# (Standard) cell may carry a free-tier suffix: "$0.02 / 1 gibibyte month, per 1 month / account".
STORAGE_PRICE_RE = re.compile(r'"\$([\d.]+) / 1 ([^",]+)')
INTER_REGION_HEADING_RE = re.compile(r"<h\d[^>]*>\s*Inter-region data transfer\s*</h\d>")


def fetch_page(url: str, log, retries: int = 4, timeout: int = 180) -> tuple:
    """Download one public pricing page and return (text, provenance dict).

    Provenance holds the requested and final URL, HTTP status, byte size, SHA-256 and the
    UTC access time, so a reader can tell exactly which page version fed the snapshot.
    Retries with exponential backoff; raises on the last failure.
    """
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            log.info("GET %s -> HTTP %s (%d bytes, final %s)", url, r.status_code, len(r.content), r.url)
            r.raise_for_status()
            return r.text, {
                "url": url, "final_url": r.url, "http_status": r.status_code,
                "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                "accessed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            log.warning("attempt %d failed (%s); retrying in %ds", attempt, exc, 2 ** attempt)
            time.sleep(2 ** attempt)


def split_region_tables(text: str) -> list:
    """Split an embedded-data blob into (region, table_text, label_text) triples.

    A table is the text between the previous region label and its own label. Region-list
    entries (`"Tokyo (asia-northeast1)","Osaka ..."`) are not labels because a label is
    followed by `,[<n>]`.
    """
    out, prev = [], 0
    for m in LABEL_RE.finditer(text):
        out.append((m.group(2), text[prev:m.start()], m.group(0)))
        prev = m.end()
    return out


def _strip(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# ---------------------------------------------------------------- compute (N2)

def extract_n2_section(page: str) -> str:
    """Return the embedded-data section of the N2 machine family (up to the next family).

    Raises ValueError if the N2 anchor is missing, i.e. the page layout changed.
    """
    i = page.find(N2_ANCHOR)
    if i < 0:
        raise ValueError("N2 section anchor not found: compute pricing page layout changed")
    m = SECTION_ANCHOR_RE.search(page, i + len(N2_ANCHOR))
    return page[i:m.start() if m else len(page)]


def parse_n2_tables(section: str) -> dict:
    """Parse on-demand hourly N2 predefined machine prices per region.

    Returns {region: {machine_type: (vcpu, ram_gib, usd_per_hour)}}. Only the first price
    column (Default = on-demand) of hourly tables is read; monthly and CUD columns are
    ignored. A machine type seen twice in one region with different prices raises
    ValueError rather than silently picking one.
    """
    out = {}
    for region, table, _ in split_region_tables(section):
        for m in N2_ROW_RE.finditer(table):
            row = (int(m.group(2)), float(m.group(3)), float(m.group(4)))
            seen = out.setdefault(region, {}).get(m.group(1))
            if seen is not None and seen != row:
                raise ValueError(f"conflicting prices for {region} {m.group(1)}: {seen} vs {row}")
            out[region][m.group(1)] = row
    return out


def fit_core_ram(machines: dict) -> tuple:
    """Least-squares fit of price = vcpu*core + ram_gib*ram over a region's machine types.

    Returns (core_usd_per_vcpu_hour, ram_usd_per_gib_hour, max_abs_residual, n_types).
    Raises ValueError with fewer than two machine types or a singular system (all types
    with the same RAM/vCPU ratio cannot separate the two rates).
    """
    rows = list(machines.values())
    if len(rows) < 2:
        raise ValueError("need at least two machine types to separate core and RAM rates")
    svv = sum(v * v for v, _, _ in rows)
    svm = sum(v * m for v, m, _ in rows)
    smm = sum(m * m for _, m, _ in rows)
    svp = sum(v * p for v, _, p in rows)
    smp = sum(m * p for _, m, p in rows)
    det = svv * smm - svm * svm
    if abs(det) < 1e-9:
        raise ValueError("machine types do not separate core and RAM (singular fit)")
    core = round((svp * smm - smp * svm) / det, 9)
    ram = round((svv * smp - svm * svp) / det, 9)
    resid = max(abs(v * core + m * ram - p) for v, m, p in rows)
    return core, ram, resid, len(rows)


def build_compute_rows(tables: dict, regions: list, source: str) -> list:
    """Turn parsed N2 tables into snapshot rows: one core and one RAM rate per region.

    Regions missing from the page are skipped (the acceptance check reports them). A fit
    residual above FIT_TOLERANCE raises ValueError: it would mean the page prices are not
    a linear core+RAM composition and the derived rates cannot be trusted.
    """
    rows = []
    for region in regions:
        if region not in tables:
            continue
        core, ram, resid, n = fit_core_ram(tables[region])
        if resid > FIT_TOLERANCE:
            raise ValueError(f"{region}: N2 core/RAM fit residual {resid:.2e} exceeds {FIT_TOLERANCE}")
        common = {"provider": "gcp", "region": region, "family": "N2", "usage": "OnDemand",
                  "n_machine_types": n, "max_fit_residual_usd_per_hour": round(resid, 9),
                  "source": source}
        rows.append({**common, "resource": "core", "usd_per_hour": core, "unit": "vCPU-hour"})
        rows.append({**common, "resource": "ram", "usd_per_hour": ram, "unit": "GiB-hour"})
    return rows


# ---------------------------------------------------------------- network

def parse_internet_egress(page: str, regions: list, group_of, source: str) -> list:
    """Parse Premium Tier internet data-transfer-out tiers for the given source regions.

    Returns one row per (region, destination group, tier) with the per-GiB page price and
    the per-GB conversion. Destination groups are the page's own names ("North America",
    "Australia, Indonesia, Korea, South America, Saudi Arabia", ...). The HTML-rendered
    default table has no embedded tiers and is ignored; a (region, group) with two different
    tier lists raises ValueError.
    """
    found = {}
    for region, table, _ in split_region_tables(page):
        if region not in regions:
            continue
        for piece in table.split(INTERNET_SPLIT)[1:]:
            group = piece.split(" (per GiB in USD)")[0]
            tiers = TIER_RE.findall(piece.split("Network (data transfer in)")[0])
            if not tiers or len(group) > 80:
                continue
            key = (region, group)
            if key in found and found[key] != tiers:
                raise ValueError(f"conflicting internet tiers for {key}")
            found[key] = tiers
    rows = []
    for (region, group), tiers in sorted(found.items()):
        for lo, hi, price in tiers:
            usd = float(price)
            rows.append({
                "provider": "gcp", "kind": "internet", "network_tier": "premium",
                "from_region": region, "from_group": group_of(region), "to_group": group,
                "tier_min_gib": float(lo.replace(",", "")),
                "tier_max_gib": float(hi.replace(",", "")) if hi else None,
                "usd_per_gib": usd, "usd_per_gb": round(usd / GIB_IN_GB, 9), "source": source,
            })
    return rows


def parse_inter_region_matrix(page: str, source: str) -> list:
    """Parse the 'Inter-region data transfer' source-group x destination-group matrix.

    Rows of the HTML table are the sender's group, columns the destination's group; footnote
    digits ("Asia3") are stripped. N/A cells are skipped. Raises ValueError if the heading or
    table is missing or a row's cell count does not match the header.
    """
    h = INTER_REGION_HEADING_RE.search(page)
    if not h:
        raise ValueError("inter-region heading not found: network pricing page layout changed")
    start = page.find("<table", h.end())
    end = page.find("</table>", start)
    if start < 0 or end < 0:
        raise ValueError("inter-region table not found")
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", page[start:end], re.S)
    grid = [[_strip(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)] for tr in trs]
    header = [re.sub(r"\d+$", "", c).strip() for c in grid[0][1:]]
    if "North America" not in header:
        raise ValueError(f"unexpected inter-region header: {header}")
    rows = []
    for cells in grid[1:]:
        if len(cells) != len(header) + 1:
            raise ValueError(f"inter-region row has {len(cells)} cells, header has {len(header) + 1}")
        src = re.sub(r"\d+$", "", cells[0]).strip()
        for dst, cell in zip(header, cells[1:]):
            m = re.fullmatch(r"\$([\d.]+)", cell)
            if not m:
                continue  # N/A
            usd = float(m.group(1))
            rows.append({
                "provider": "gcp", "kind": "inter_region", "network_tier": "premium",
                "from_region": None, "from_group": src, "to_group": dst,
                "tier_min_gib": 0.0, "tier_max_gib": None,
                "usd_per_gib": usd, "usd_per_gb": round(usd / GIB_IN_GB, 9), "source": source,
            })
    return rows


# ---------------------------------------------------------------- storage

def parse_standard_storage(page: str, regions: list, source: str) -> list:
    """Parse the Standard-class, single-region Cloud Storage at-rest price per region.

    Uses the monthly tables whose header starts with "Standard storage": the first price
    cell after that header is the Standard column and must be "/ 1 gibibyte month"
    (hourly tables are skipped; a column is never skipped). The page
    also has a Dual-region table labelled with the same region names (billed per underlying
    region, 4 columns); only the Region table carries the fifth "Rapid Cache storage" column,
    which is how the two are told apart. Multi-region locations ("Asia (asia)") have no
    `xx-yyyyN` id and are never matched.

    Cross-check: where the region's hourly Standard price is also present, hourly x 730 must
    round to the monthly price (within 1e-4 USD), else ValueError.
    """
    found, hourly = {}, {}
    for region, table, _ in split_region_tables(page):
        if region not in regions:
            continue
        i = table.find("Standard storage")
        if i < 0 or "Nearline storage" not in table[i:]:
            continue
        m = STORAGE_PRICE_RE.search(table, i)
        if not m or "Rapid Cache storage" not in table[i:m.start()]:
            continue
        usd = float(m.group(1))
        if m.group(2) == "gibibyte hour":
            hourly[region] = usd
            continue
        if m.group(2) != "gibibyte month":
            continue
        if region in found and found[region] != usd:
            raise ValueError(f"conflicting Standard storage prices for {region}: {found[region]} vs {usd}")
        found[region] = usd
    for region, usd in found.items():
        if region in hourly and abs(hourly[region] * HOURS_PER_MONTH - usd) > 1e-4:
            raise ValueError(f"{region}: hourly {hourly[region]} x 730 disagrees with monthly {usd}")
    return [{
        "provider": "gcp", "region": r, "storage_class": "STANDARD", "location_type": "region",
        "tier_min_gb": 0, "usd_per_gib_month": usd, "usd_per_gb_month": round(usd / GIB_IN_GB, 9),
        "source": source,
    } for r, usd in sorted(found.items())]


# ---------------------------------------------------------------- sample recording

def excerpt_regions(text: str, regions: list) -> str:
    """Concatenate the tables (with their labels) of the given regions from a blob.

    The result parses exactly like the original for those regions, which is what the
    offline tests need; it is a verbatim excerpt of the live page, not synthetic data.
    """
    return "".join(table + label for region, table, label in split_region_tables(text) if region in regions)


def inter_region_excerpt(page: str) -> str:
    """Return the verbatim HTML from the inter-region heading to the end of its table."""
    h = INTER_REGION_HEADING_RE.search(page)
    return page[h.start():page.find("</table>", h.end()) + len("</table>")]
