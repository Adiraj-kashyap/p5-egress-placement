"""
Objective O1: build the unified cost model from one dated snapshot (01_CONVENTIONS §4).

Outputs, over the `ext` location set (24 locations = 8 regions x 3 providers):
  cost_model/<date>/compute.csv   provider,region,shape,instance_type,vcpu,ram_gb,usd_per_hour,usd_per_month,source
  cost_model/<date>/storage.csv   provider,region,storage_class,usd_per_gb_month,source
  cost_model/<date>/egress.csv    src_provider,src_region,dst_provider,dst_region,usd_per_gb,rule,source
  cost_model/<date>/internet.csv  provider,region,usd_per_gb,tier,source

EGRESS RULES (03_SKILLS §S4; state these in the report):
  R1  same provider, same region       -> $0.00/GB (intra-zone assumed; cross-zone ignored)
  R2  same provider, different region  -> that provider's inter-region rate for the pair
                                          (AWS: per region pair SKU; Azure: intra-continent
                                          meter of the sender or the sender continent's
                                          intercontinental meter (D-034); GCP: group matrix)
  R3  different provider               -> the SENDER's internet egress rate from the sender
                                          region (GCP: for the receiver's destination group)
  R4  ingress                          -> $0.00 on all three (never billed, so not a column)
Every tiered price is flattened to its first paid tier: the lowest tier_min with price > 0
(D-007, D-018, D-025, D-028). Every egress cell records `rule` and `source` (SKU / meter id
or `fallback:<reason>`); the fallback count is logged and reported by validate_cost_model.

Usage:  python -m pricing.build_cost_model      (honours P5_SNAPSHOT_DATE)
"""
import csv
import json
import logging
import sys
from pathlib import Path

from pricing.common import CONTINENT, LOCATIONS_EXT, ROOT, SNAPSHOT_DATE, SNAPSHOT_DIR
from pricing.gcp_regions import INTER_REGION_GROUP

log = logging.getLogger("costmodel")
OUT_DIR = ROOT / "cost_model" / SNAPSHOT_DATE

HOURS_PER_MONTH = 730

# Same general-purpose family class on every provider (03_SKILLS §S5, D-024, D-027).
SHAPES = [
    {"name": "small",  "vcpu": 2,  "ram_gb": 8},
    {"name": "medium", "vcpu": 4,  "ram_gb": 16},
    {"name": "large",  "vcpu": 8,  "ram_gb": 32},
    {"name": "xlarge", "vcpu": 16, "ram_gb": 64},
]

# GCP destination group for internet egress, keyed by the receiver's continent tag (D-028).
GCP_DST_GROUP = {
    "NA": "North America",
    "EU": "Europe",
    "AS": "Asia Excl Korea, Indonesia",
    "SA": "Australia, Indonesia, Korea, South America, Saudi Arabia",
}
# Azure intercontinental meter per sender continent ("... Data Transfer Out - <X> To Any").
AZURE_INTERCONT = {"NA": "NAM or EU", "EU": "NAM or EU", "AS": "ASIA", "SA": "LATAM"}

COMPUTE_FIELDS = ["provider", "region", "shape", "instance_type", "vcpu", "ram_gb",
                  "usd_per_hour", "usd_per_month", "source"]
STORAGE_FIELDS = ["provider", "region", "storage_class", "usd_per_gb_month", "source"]
EGRESS_FIELDS = ["src_provider", "src_region", "dst_provider", "dst_region", "usd_per_gb",
                 "rule", "source"]
INTERNET_FIELDS = ["provider", "region", "usd_per_gb", "tier", "source"]

RULE_R1 = "R1"
RULE_R2 = "R2"
RULE_R3 = "R3"


def locations():
    """All ext locations as (provider, region), provider-major, in LOCATIONS_EXT order."""
    return [(p, r) for p, rs in LOCATIONS_EXT.items() for r in rs]


def first_paid(rows, tier_key="tier_min_gb", price_key="usd_per_gb"):
    """The row of the first paid tier: lowest tier_min with price > 0, or None."""
    paid = [r for r in rows if r[price_key] > 0]
    return min(paid, key=lambda r: r[tier_key] or 0) if paid else None


# ---------------------------------------------------------------- compute
def build_compute(aws, azure, gcp):
    rows = []
    for provider, src, id_key in (("aws", aws, "sku"), ("azure", azure, "meter_id")):
        for region in LOCATIONS_EXT[provider]:
            for shape in SHAPES:
                hits = [r for r in src if r["region"] == region and r["shape"] == shape["name"]]
                if len(hits) != 1:
                    raise ValueError(f"{provider}:{region} {shape['name']}: {len(hits)} rows, need 1")
                r = hits[0]
                if r["vcpu"] != shape["vcpu"] or float(r["ram_gb"]) != shape["ram_gb"]:
                    raise ValueError(f"{provider}:{region} {r['instance_type']} does not match {shape}")
                rows.append(_compute_row(provider, region, shape, r["instance_type"],
                                         r["usd_per_hour"], f"sku:{r[id_key]}"))
    for region in LOCATIONS_EXT["gcp"]:
        rate = {}
        for res in ("core", "ram"):
            hits = [r for r in gcp if r["region"] == region and r["resource"] == res
                    and r["family"] == "N2"]
            if len(hits) != 1:
                raise ValueError(f"gcp:{region} N2 {res}: {len(hits)} rows, need 1")
            rate[res] = hits[0]["usd_per_hour"]
        for shape in SHAPES:
            hourly = gcp_composed_hourly(shape["vcpu"], shape["ram_gb"], rate["core"], rate["ram"])
            rows.append(_compute_row("gcp", region, shape, f"n2-standard-{shape['vcpu']}", hourly,
                                     f"composed:N2 core {rate['core']}/vCPU-h + "
                                     f"ram {rate['ram']}/GiB-h (public page, D-026/D-027)"))
    log.info("compute rows built: %d", len(rows))
    return rows


def gcp_composed_hourly(vcpu, ram_gib, core_rate, ram_rate):
    """GCP N2 shape price = vCPU x core rate + GiB x RAM rate (D-027)."""
    return vcpu * core_rate + ram_gib * ram_rate


def _compute_row(provider, region, shape, instance_type, usd_per_hour, source):
    return {"provider": provider, "region": region, "shape": shape["name"],
            "instance_type": instance_type, "vcpu": shape["vcpu"], "ram_gb": shape["ram_gb"],
            "usd_per_hour": round(usd_per_hour, 6),
            "usd_per_month": round(usd_per_hour * HOURS_PER_MONTH, 4), "source": source}


# ---------------------------------------------------------------- storage
def build_storage(aws, azure, gcp):
    rows = []
    for provider, src, id_key in (("aws", aws, "sku"), ("azure", azure, "meter_id"),
                                  ("gcp", gcp, "source")):
        for region in LOCATIONS_EXT[provider]:
            hits = [r for r in src if r["region"] == region and (r["tier_min_gb"] or 0) == 0]
            if len(hits) != 1:
                raise ValueError(f"{provider}:{region} storage: {len(hits)} base-tier rows, need 1")
            r = hits[0]
            src_txt = f"sku:{r[id_key]}" if provider != "gcp" else r["source"]
            rows.append({"provider": provider, "region": region,
                         "storage_class": r["storage_class"],
                         "usd_per_gb_month": round(r["usd_per_gb_month"], 6), "source": src_txt})
    log.info("storage rows built: %d", len(rows))
    return rows


# ---------------------------------------------------------------- egress
class EgressResolver:
    """Resolves directed $/GB rates from the three egress snapshots (flattened tiers)."""

    def __init__(self, aws, azure, gcp):
        self.aws, self.azure, self.gcp = aws, azure, gcp

    # --- internet (R3 and internet.csv)
    def internet(self, provider, region, dst_continent=None):
        """(usd_per_gb, tier_label, source). dst_continent only matters for GCP."""
        if provider == "aws":
            r = first_paid([x for x in self.aws if x["kind"] == "internet" and x["region"] == region])
            return self._hit(r, lambda r: (f"first paid tier from {r['tier_min_gb']:g} GB",
                                           f"sku:{r['sku']}"), provider, region)
        if provider == "azure":
            r = first_paid([x for x in self.azure
                            if x["category"] == "internet_out" and x["region"] == region])
            return self._hit(r, lambda r: (f"first paid tier from {r['tier_min_gb']:g} GB (MGN)",
                                           f"sku:{r['meter_id']}"), provider, region)
        group = GCP_DST_GROUP[dst_continent or CONTINENT[region]]
        r = first_paid([x for x in self.gcp if x["kind"] == "internet"
                        and x["from_region"] == region and x["to_group"] == group],
                       tier_key="tier_min_gib")
        return self._hit(r, lambda r: (f"first paid tier from {r['tier_min_gib']:g} GiB to {group}",
                                       f"page:{r['source']}#internet:{region}->{group}"),
                         provider, region)

    @staticmethod
    def _hit(row, describe, provider, region):
        if row is None:
            raise ValueError(f"no internet egress price for {provider}:{region}")
        tier, source = describe(row)
        return row["usd_per_gb"], tier, source

    # --- inter-region (R2)
    def inter_region(self, provider, src, dst):
        """(usd_per_gb, source); source is 'fallback:<reason>' when no SKU resolves."""
        if provider == "aws":
            r = first_paid([x for x in self.aws if x["kind"] == "inter_region"
                            and x["region"] == src and x.get("dst_region") == dst])
            if r:
                return r["usd_per_gb"], f"sku:{r['sku']}"
            return None, "fallback:aws pair SKU missing"
        if provider == "azure":
            if CONTINENT[src] == CONTINENT[dst]:
                r = first_paid([x for x in self.azure if x["category"] == "inter_region"
                                and x["region"] == src])
                if r:
                    return r["usd_per_gb"], f"sku:{r['meter_id']} (intra-continent)"
                return None, "fallback:azure sender meter missing"
            label = f"Inter Continent Data Transfer Out - {AZURE_INTERCONT[CONTINENT[src]]} To Any"
            r = first_paid([x for x in self.azure if x["category"] == "inter_region_continent_fallback"
                            and x["region"] == "Intercontinental" and x["meter_name"] == label])
            if r:
                return r["usd_per_gb"], f"sku:{r['meter_id']} (intercontinental, D-034)"
            return None, "fallback:azure intercontinental meter missing"
        fg, tg = INTER_REGION_GROUP[src], INTER_REGION_GROUP[dst]
        r = first_paid([x for x in self.gcp if x["kind"] == "inter_region"
                        and x["from_group"] == fg and x["to_group"] == tg], tier_key="tier_min_gib")
        if r:
            return r["usd_per_gb"], f"page:{r['source']}#inter_region:{fg}->{tg}"
        return None, "fallback:gcp group pair missing"


# Published continent-pair rates, used only if a pair has no snapshot price. Loudly logged.
FALLBACK_INTER_REGION = {
    ("NA", "NA"): 0.02, ("EU", "EU"): 0.02, ("EU", "NA"): 0.05, ("AS", "AS"): 0.08,
    ("AS", "NA"): 0.08, ("AS", "EU"): 0.08,
}
FALLBACK_INTER_REGION_SA = 0.16


def build_egress(resolver):
    rows, fallbacks = [], 0
    for sp, sr in locations():
        for dp, dr in locations():
            if (sp, sr) == (dp, dr):
                rate, rule, source = 0.0, RULE_R1, "rule:R1 same region"
            elif sp == dp:
                rule = RULE_R2
                rate, source = resolver.inter_region(sp, sr, dr)
                if rate is None:
                    fallbacks += 1
                    pair = tuple(sorted((CONTINENT[sr], CONTINENT[dr])))
                    rate = FALLBACK_INTER_REGION.get(pair, FALLBACK_INTER_REGION_SA)
                    log.warning("FALLBACK %s:%s -> %s: %s, rate %.4f", sp, sr, dr, source, rate)
            else:
                rule = RULE_R3
                rate, _, source = resolver.internet(sp, sr, dst_continent=CONTINENT[dr])
            rows.append({"src_provider": sp, "src_region": sr, "dst_provider": dp,
                         "dst_region": dr, "usd_per_gb": round(rate, 6), "rule": rule,
                         "source": source})
    log.info("egress matrix built: %d cells, %d R2 cells used fallback rates", len(rows), fallbacks)
    return rows


def build_internet(resolver):
    """Egress to end users on the internet. GCP uses the sender's own continent group
    (users are assumed near the region; D-034)."""
    rows = []
    for p, r in locations():
        rate, tier, source = resolver.internet(p, r)
        rows.append({"provider": p, "region": r, "usd_per_gb": round(rate, 6), "tier": tier,
                     "source": source})
    log.info("internet rows built: %d", len(rows))
    return rows


# ---------------------------------------------------------------- io
def load_snapshot(name, snapshot_dir=SNAPSHOT_DIR):
    path = Path(snapshot_dir) / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("meta", {}).get("FIXTURE") or payload.get("FIXTURE"):
        raise ValueError(f"{path.name} is a FIXTURE snapshot; refusing to build a cost model (I2)")
    log.info("loaded %-16s rows=%d  snapshot_date=%s", name, len(payload["rows"]),
             payload.get("snapshot_date"))
    return payload["rows"]


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    log.info("WROTE %s  rows=%d", path.relative_to(ROOT).as_posix(), len(rows))


def build_all(snapshot_dir=SNAPSHOT_DIR):
    s = {n: load_snapshot(n, snapshot_dir) for n in
         ("aws_compute", "azure_compute", "gcp_compute", "aws_storage", "azure_storage",
          "gcp_storage", "aws_egress", "azure_egress", "gcp_egress")}
    resolver = EgressResolver(s["aws_egress"], s["azure_egress"], s["gcp_egress"])
    return {
        "compute": build_compute(s["aws_compute"], s["azure_compute"], s["gcp_compute"]),
        "storage": build_storage(s["aws_storage"], s["azure_storage"], s["gcp_storage"]),
        "egress": build_egress(resolver),
        "internet": build_internet(resolver),
    }


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s  %(name)-10s  %(levelname)-7s  %(message)s")
    log.info("building cost model for snapshot %s", SNAPSHOT_DATE)
    tables = build_all()
    for name, fields in (("compute", COMPUTE_FIELDS), ("storage", STORAGE_FIELDS),
                         ("egress", EGRESS_FIELDS), ("internet", INTERNET_FIELDS)):
        write_csv(OUT_DIR / f"{name}.csv", tables[name], fields)
    log.info("cost model complete for snapshot %s", SNAPSHOT_DATE)


if __name__ == "__main__":
    main()
