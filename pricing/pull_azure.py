"""
Azure Retail Prices API puller.

No account, no key, no auth. Pulls three categories for the `ext` Azure regions into
snapshots/<date>/:
  azure_compute.json  Dsv5 (D2s/D4s/D8s/D16s) Linux on-demand hourly prices, with vCPU/RAM
  azure_egress.json   Bandwidth meters: internet data-transfer-out tiers and inter-region rates
  azure_storage.json  Blob Storage Hot LRS "Data Stored" (USD per GB-month)

Docs: https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices

Usage:  python -m pricing.pull_azure
"""
import time

from pricing.azure_shapes import AZURE_SHAPES, DSV5_SOURCE_URL, SHAPE_TO_SKU
from pricing.common import LOCATIONS_EXT, get_json, get_logger, write_snapshot

API = "https://prices.azure.com/api/retail/prices"
log = get_logger("azure")

REGIONS = LOCATIONS_EXT["azure"]
PAGE_SLEEP_S = 0.2  # polite paging (03_SKILLS S1)

# SKU name fragments we never want: spot/low-priority pricing and Windows licences.
EXCLUDE_SKU = ("Spot", "Low Priority")
EXCLUDE_PRODUCT = ("Windows",)

# Bandwidth meters (armRegionName is the *sending* region for both).
#  - "Rtn Preference: MGN" is the Microsoft global network, the default routing for VM egress.
#  - "Bandwidth - Routing Preference: Internet" is the cheaper ISP-routed option; kept for the
#    record, not used as the base rate (D-019).
MGN_PRODUCT = "Rtn Preference: MGN"
ROUTING_INTERNET_PRODUCT = "Bandwidth - Routing Preference: Internet"
INTERNET_METER = "Standard Data Transfer Out"
INTER_REGION_METER = "Standard Inter-Region Data Transfer"
CONTINENT_PRODUCT = "Bandwidth Inter-Region"  # continent-level fallback rows (legacy meters)


def _paged(filter_expr):
    """Follow NextPageLink until exhausted. Azure returns 100 items per page."""
    rows, url, params, page = [], API, {"$filter": filter_expr}, 0
    while url:
        data = get_json(url, log, params=params)  # exponential backoff on 429/5xx inside
        rows.extend(data.get("Items", []))
        url = data.get("NextPageLink")
        params = None  # NextPageLink already carries the query string
        page += 1
        if url:
            time.sleep(PAGE_SLEEP_S)
        if page % 10 == 0:
            log.info("  ... %d pages, %d items so far", page, len(rows))
    return rows


def parse_compute(items):
    """Keep Linux on-demand Dsv5 rows of the four project shapes; attach vCPU/RAM."""
    sku_to_shape = {sku: shape for shape, sku in SHAPE_TO_SKU.items()}
    out = []
    for it in items:
        sku, product = it.get("skuName", ""), it.get("productName", "")
        arm_sku = it.get("armSkuName")
        if arm_sku not in AZURE_SHAPES:
            continue
        if any(x in sku for x in EXCLUDE_SKU) or any(x in product for x in EXCLUDE_PRODUCT):
            continue
        if it.get("unitOfMeasure") != "1 Hour" or it.get("type") != "Consumption":
            continue
        vcpu, ram_gb = AZURE_SHAPES[arm_sku]
        out.append({
            "provider": "azure",
            "region": it["armRegionName"],
            "instance_type": arm_sku,
            "shape": sku_to_shape[arm_sku],
            "vcpu": vcpu,
            "ram_gb": ram_gb,
            "product_name": product,
            "sku_name": sku,
            "usd_per_hour": it["retailPrice"],
            "meter_id": it.get("meterId"),
            "effective_date": it.get("effectiveStartDate"),
        })
    return out


def pull_compute():
    skus = " or ".join(f"armSkuName eq '{s}'" for s in AZURE_SHAPES)
    out = []
    for region in REGIONS:
        expr = (
            f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' "
            f"and priceType eq 'Consumption' and ({skus})"
        )
        log.info("compute: region=%s", region)
        items = _paged(expr)
        kept = parse_compute(items)
        log.info("compute: region=%s  fetched=%d  kept=%d", region, len(items), len(kept))
        out.extend(kept)
    return out


def _classify_bandwidth(it):
    """Return the egress category of a Bandwidth item, or None if it is not one we use."""
    if it.get("unitOfMeasure") != "1 GB":
        return None  # drops the hourly China-circuit meters
    product, meter = it.get("productName", ""), it.get("meterName", "")
    if product == MGN_PRODUCT and meter == INTERNET_METER:
        return "internet_out"
    if product == ROUTING_INTERNET_PRODUCT and meter == INTERNET_METER:
        return "internet_out_routing_pref_internet"
    if product == MGN_PRODUCT and meter == INTER_REGION_METER:
        return "inter_region"
    if product == CONTINENT_PRODUCT and "Data Transfer Out" in meter:
        return "inter_region_continent_fallback"
    return None


def parse_egress(items, regions=REGIONS):
    """Keep egress-relevant Bandwidth rows for `regions`; continent fallbacks are kept whole."""
    out = []
    for it in items:
        category = _classify_bandwidth(it)
        if category is None or it.get("type") != "Consumption":
            continue
        region = it.get("armRegionName")
        if category != "inter_region_continent_fallback" and region not in regions:
            continue
        out.append({
            "provider": "azure",
            "region": region,
            "category": category,
            "product_name": it.get("productName"),
            "sku_name": it.get("skuName"),
            "meter_name": it.get("meterName"),
            "unit": it.get("unitOfMeasure"),
            "tier_min_gb": it.get("tierMinimumUnits", 0),
            "usd_per_gb": it["retailPrice"],
            "meter_id": it.get("meterId"),
            "effective_date": it.get("effectiveStartDate"),
        })
    return out


def pull_egress():
    """serviceName 'Bandwidth' is small (~1.4k rows worldwide), so pull it once and filter."""
    log.info("egress: serviceName eq 'Bandwidth'")
    items = _paged("serviceName eq 'Bandwidth' and priceType eq 'Consumption'")
    out = parse_egress(items)
    log.info("egress: fetched=%d  kept=%d", len(items), len(out))
    return out


def parse_storage(items):
    """Blob Hot LRS 'Data Stored' tiers in USD per GB-month (tier_min_gb 0 is the base rate)."""
    out = []
    for it in items:
        if it.get("meterName") != "Hot LRS Data Stored" or it.get("unitOfMeasure") != "1 GB/Month":
            continue
        if it.get("type") != "Consumption":
            continue
        out.append({
            "provider": "azure",
            "region": it["armRegionName"],
            "storage_class": "Blob Hot LRS",
            "product_name": it.get("productName"),
            "sku_name": it.get("skuName"),
            "meter_name": it.get("meterName"),
            "tier_min_gb": it.get("tierMinimumUnits", 0),
            "usd_per_gb_month": it["retailPrice"],
            "meter_id": it.get("meterId"),
            "effective_date": it.get("effectiveStartDate"),
        })
    return out


def pull_storage():
    out = []
    for region in REGIONS:
        expr = (
            "serviceName eq 'Storage' and productName eq 'Blob Storage' and skuName eq 'Hot LRS' "
            f"and armRegionName eq '{region}' and priceType eq 'Consumption'"
        )
        log.info("storage: region=%s", region)
        items = _paged(expr)
        kept = parse_storage(items)
        log.info("storage: region=%s  fetched=%d  kept=%d", region, len(items), len(kept))
        out.extend(kept)
    return out


def first_paid_internet_rate(egress_rows, region):
    """Lowest-tier internet_out row with a price > 0 for `region` (D-007 flattening)."""
    tiers = [r for r in egress_rows
             if r["region"] == region and r["category"] == "internet_out" and r["usd_per_gb"] > 0]
    return min(tiers, key=lambda r: r["tier_min_gb"]) if tiers else None


def summarise(compute, egress, storage):
    log.info("SUMMARY rows: compute=%d egress=%d storage=%d", len(compute), len(egress), len(storage))
    log.info("%-20s %7s %7s %7s  %-24s %-18s %-12s", "region", "compute", "egress", "storage",
             "small(D2s_v5) $/h", "internet 1st paid", "inter-region")
    for region in REGIONS:
        c = [r for r in compute if r["region"] == region]
        e = [r for r in egress if r["region"] == region]
        s = [r for r in storage if r["region"] == region]
        small = [r["usd_per_hour"] for r in c if r["shape"] == "small"]
        paid = first_paid_internet_rate(egress, region)
        inter = [r["usd_per_gb"] for r in e if r["category"] == "inter_region"]
        log.info("%-20s %7d %7d %7d  %-24s %-18s %-12s", region, len(c), len(e), len(s),
                 f"{min(small):.4f}" if small else "MISSING",
                 f"{paid['usd_per_gb']:.4f} (>{paid['tier_min_gb']:g}GB)" if paid else "MISSING",
                 f"{inter[0]:.4f}" if inter else "MISSING")


if __name__ == "__main__":
    compute = pull_compute()
    write_snapshot("azure_compute", compute, log,
                   meta={"api": API, "auth": "none", "regions": REGIONS,
                         "family": "Dsv5", "os": "Linux", "price_type": "Consumption",
                         "shapes_source": DSV5_SOURCE_URL})
    egress = pull_egress()
    write_snapshot("azure_egress", egress, log,
                   meta={"api": API, "auth": "none", "service": "Bandwidth", "regions": REGIONS,
                         "base_internet_product": MGN_PRODUCT,
                         "note": "armRegionName is the sending region; tiers not flattened here"})
    storage = pull_storage()
    write_snapshot("azure_storage", storage, log,
                   meta={"api": API, "auth": "none", "service": "Storage",
                         "product": "Blob Storage", "sku": "Hot LRS", "regions": REGIONS})
    summarise(compute, egress, storage)
    log.info("azure pull complete")
