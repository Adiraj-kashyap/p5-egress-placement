"""Offline tests for pricing/pull_gcp.py, pricing/gcp_pages.py and pricing/gcp_regions.py.

The page parsers run on tests/data/gcp_sample.json: verbatim excerpts of the public pricing
pages (cloud.google.com, no API key) recorded on 2026-09-21 by
`python -m pricing.pull_gcp --record-sample`, for us-east4, europe-west3 and
southamerica-east1. The storage excerpt includes the Dual-region tables for the same regions,
which act as decoys. No network access.

The Cloud Billing API parsers cannot be tested on recorded data because no API key exists
(D-021); they are tested on small SKU dicts written in this file, shaped like the documented
API response (03_SKILLS S3). Those dicts are test inputs only and never feed a snapshot.
"""
import json
import logging
from pathlib import Path

import pytest

from pricing import gcp_pages, pull_gcp
from pricing.common import LOCATIONS_EXT
from pricing.gcp_regions import (CONTINENT_GROUPS, INTER_REGION_GROUP, PRICING_GROUP,
                                 pricing_group, unmapped_regions)

DATA = Path(__file__).parent / "data"
REGIONS = ["us-east4", "europe-west3", "southamerica-east1"]


@pytest.fixture(scope="module")
def sample():
    return json.loads((DATA / "gcp_sample.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def n2(sample):
    return gcp_pages.parse_n2_tables(sample["compute_n2_excerpt"])


@pytest.fixture(scope="module")
def internet(sample):
    return gcp_pages.parse_internet_egress(sample["network_internet_excerpt"], REGIONS,
                                           pricing_group, "page")


@pytest.fixture(scope="module")
def inter(sample):
    return gcp_pages.parse_inter_region_matrix(sample["network_inter_region_html"], "page")


# ---------------------------------------------------------------- sample hygiene

def test_sample_is_key_free_and_complete(sample):
    text = json.dumps(sample)
    assert "key=" not in text and "AIza" not in text
    assert sample["regions"] == REGIONS
    assert [p["http_status"] for p in sample["provenance"]] == [200, 200, 200]


# ---------------------------------------------------------------- regions

def test_every_ext_region_is_mapped():
    assert unmapped_regions() == []
    assert set(PRICING_GROUP.values()) == set(CONTINENT_GROUPS)
    assert set(INTER_REGION_GROUP) == set(LOCATIONS_EXT["gcp"])


def test_unknown_region_fails_loudly():
    with pytest.raises(KeyError):
        pricing_group("mars-north1")


# ---------------------------------------------------------------- compute

def test_n2_tables_cover_three_families_hourly_only(n2):
    assert set(n2) == set(REGIONS)
    for machines in n2.values():
        assert {m.split("-")[1] for m in machines} == {"standard", "highmem", "highcpu"}
        assert machines["n2-standard-4"][:2] == (4, 16.0)
    assert n2["us-east4"]["n2-standard-2"][2] == pytest.approx(0.109378)  # hourly, not monthly


def test_core_ram_fit_is_exact_and_matches_page(n2):
    core, ram, resid, n = gcp_pages.fit_core_ram(n2["us-east4"])
    assert (core, ram) == (pytest.approx(0.035605), pytest.approx(0.004771))
    assert resid < 1e-9 and n == len(n2["us-east4"]) >= 20
    for v, m, p in n2["southamerica-east1"].values():
        c, r, _, _ = gcp_pages.fit_core_ram(n2["southamerica-east1"])
        assert v * c + m * r == pytest.approx(p, abs=1e-6)


def test_compute_rows_one_core_one_ram_per_region(n2):
    rows = gcp_pages.build_compute_rows(n2, REGIONS + ["asia-south1"], "page")
    assert len(rows) == 6  # asia-south1 is not in the sample, so it is skipped, not invented
    for region in REGIONS:
        assert sorted(r["resource"] for r in rows if r["region"] == region) == ["core", "ram"]
    assert {r["family"] for r in rows} == {"N2"}


def test_fit_rejects_unseparable_inputs():
    with pytest.raises(ValueError):
        gcp_pages.fit_core_ram({"a": (2, 8.0, 0.1)})
    with pytest.raises(ValueError):
        gcp_pages.fit_core_ram({"a": (2, 8.0, 0.1), "b": (4, 16.0, 0.2)})  # same RAM/vCPU ratio


def test_large_fit_residual_raises():
    tables = {"r1": {"a": (2, 2.0, 0.1), "b": (2, 8.0, 0.2), "c": (2, 16.0, 0.9)}}
    with pytest.raises(ValueError):
        gcp_pages.build_compute_rows(tables, ["r1"], "page")


def test_conflicting_machine_price_raises(sample):
    excerpt = sample["compute_n2_excerpt"]
    tampered = excerpt + excerpt.replace("$0.109378 / 1 hour", "$0.2 / 1 hour", 1)
    with pytest.raises(ValueError):
        gcp_pages.parse_n2_tables(tampered)


def test_missing_n2_anchor_raises():
    with pytest.raises(ValueError):
        gcp_pages.extract_n2_section("<html>no pricing here</html>")


# ---------------------------------------------------------------- network

def test_internet_rows_per_region_and_group(internet):
    groups = {(r["from_region"], r["to_group"]) for r in internet}
    for region in REGIONS:
        assert {g for reg, g in groups if reg == region} >= {"North America", "Europe",
                                                             "Asia Excl Korea, Indonesia"}
    assert {r["network_tier"] for r in internet} == {"premium"}


def test_internet_tiers_and_units(internet):
    na = sorted((r["tier_min_gib"], r["tier_max_gib"], r["usd_per_gib"]) for r in internet
                if r["from_region"] == "us-east4" and r["to_group"] == "North America")
    assert na == [(0.0, 1024.0, 0.12), (1024.0, 10240.0, 0.11), (10240.0, None, 0.08)]
    sa = [r for r in internet if r["from_region"] == "southamerica-east1" and r["to_group"] == "Europe"]
    first_paid = min((r for r in sa if r["usd_per_gib"] > 0), key=lambda r: r["tier_min_gib"])
    assert first_paid["usd_per_gib"] == 0.19
    assert first_paid["usd_per_gb"] == pytest.approx(0.19 / 1.073741824)


def test_free_first_tier_is_kept_as_zero(internet):
    asia = sorted((r["tier_min_gib"], r["usd_per_gib"]) for r in internet
                  if r["from_region"] == "us-east4" and r["to_group"] == "Asia Excl Korea, Indonesia")
    assert asia[0] == (0.0, 0.0) and asia[1] == (1.0, 0.12)


def test_inter_region_matrix(inter):
    cell = {(r["from_group"], r["to_group"]): r["usd_per_gib"] for r in inter}
    assert cell[("North America", "North America")] == 0.02
    assert cell[("North America", "Europe")] == 0.05
    assert cell[("Europe", "Asia")] == 0.08
    assert cell[("South America", "North America")] == 0.14
    assert ("Indonesia", "Indonesia") not in cell  # N/A on the page
    groups = set(INTER_REGION_GROUP.values())
    assert {(a, b) for a in groups for b in groups} <= set(cell)


def test_inter_region_missing_heading_raises():
    with pytest.raises(ValueError):
        gcp_pages.parse_inter_region_matrix("<h4>Something else</h4><table></table>", "page")


# ---------------------------------------------------------------- storage

def test_standard_regional_storage_ignores_dual_region(sample):
    rows = gcp_pages.parse_standard_storage(sample["storage_excerpt"], REGIONS, "page")
    got = {r["region"]: r["usd_per_gib_month"] for r in rows}
    assert got == {"us-east4": 0.023, "europe-west3": 0.023, "southamerica-east1": 0.035}
    assert {r["storage_class"] for r in rows} == {"STANDARD"}


def test_storage_hourly_monthly_disagreement_raises(sample):
    tampered = sample["storage_excerpt"].replace('"$0.023 / 1 gibibyte month', '"$0.03 / 1 gibibyte month')
    with pytest.raises(ValueError):
        gcp_pages.parse_standard_storage(tampered, REGIONS, "page")


# ---------------------------------------------------------------- key hygiene

def test_redact_removes_key_material():
    fake = "AIza" + "B" * 35
    out = pull_gcp.redact(f"GET https://cloudbilling.googleapis.com/v1/services?key={fake}&pageSize=1")
    assert "key=" not in out and "AIza" not in out and "pageSize=1" in out


def test_log_records_are_redacted():
    rec = logging.LogRecord("gcp", logging.WARNING, __file__, 1, "failed: %s", ("url?key=abcdefgh123",), None)
    pull_gcp.RedactFilter().filter(rec)
    assert "key=" not in rec.getMessage()


def test_load_api_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("GCP_API_KEY", raising=False)
    monkeypatch.setattr(pull_gcp, "ROOT", tmp_path)
    assert pull_gcp.load_api_key() == ""
    (tmp_path / ".env").write_text("OTHER=1\nGCP_API_KEY=abc\n", encoding="utf-8")
    assert pull_gcp.load_api_key() == "abc"


# ---------------------------------------------------------------- API path (synthetic SKU dicts)

def _sku(desc, family, group, regions, prices, usage="OnDemand", sku_id="X"):
    rates = [{"startUsageAmount": lo, "unitPrice": {"units": str(int(p)), "nanos": round((p % 1) * 1e9)}}
             for lo, p in prices]
    return {"skuId": sku_id, "description": desc, "serviceRegions": regions,
            "category": {"resourceFamily": family, "resourceGroup": group, "usageType": usage},
            "pricingInfo": [{"pricingExpression": {"tieredRates": rates}}]}


def test_api_compute_keeps_only_n2_on_demand_core_and_ram():
    skus = [
        _sku("N2 Instance Core running in Americas", "Compute", "CPU", ["us-east4"], [(0, 0.0356)]),
        _sku("N2 Instance Ram running in Americas", "Compute", "RAM", ["us-east4"], [(0, 0.0048)]),
        _sku("N2 Custom Instance Core running in Americas", "Compute", "CPU", ["us-east4"], [(0, 0.04)]),
        _sku("N2D AMD Instance Core running in Americas", "Compute", "CPU", ["us-east4"], [(0, 0.03)]),
        _sku("N2 Instance Core running in Americas", "Compute", "CPU", ["us-east4"], [(0, 0.008)],
             usage="Preemptible"),
    ]
    rows = pull_gcp.parse_api_compute(skus, ["us-east4"])
    assert [(r["resource"], r["usd_per_hour"]) for r in rows] == [("core", 0.0356), ("ram", 0.0048)]


def test_api_egress_and_storage_and_service_lookup():
    skus = [
        _sku("Network Inter Region Data Transfer Out from Americas to EMEA", "Network", "X", [], [(0, 0.05)]),
        _sku("Network Internet Data Transfer Out from EMEA to Americas", "Network", "X", [],
             [(0, 0), (1, 0.12), (1024, 0.11)]),
        _sku("Network Internet Data Transfer Out from EMEA to Americas Standard Tier", "Network", "X", [], [(0, 0.085)]),
    ]
    rows = pull_gcp.parse_api_egress(skus, LOCATIONS_EXT["gcp"])
    assert {r["kind"] for r in rows} == {"inter_region", "internet"}
    inet = [r for r in rows if r["kind"] == "internet"]
    assert {r["from_region"] for r in inet} == {"europe-west1", "europe-west3"}
    assert pull_gcp.first_paid([(r["tier_min_gib"], r["usd_per_gib"]) for r in inet
                                if r["from_region"] == "europe-west1"]) == 0.12
    st = pull_gcp.parse_api_storage(
        [_sku("Standard Storage Frankfurt", "Storage", "RegionalStorage", ["europe-west3"], [(0, 0.023)]),
         _sku("Standard Storage Dual-region", "Storage", "DualRegionalStorage", ["europe-west3"], [(0, 0.03)])],
        ["europe-west3"])
    assert [(r["region"], r["usd_per_gib_month"]) for r in st] == [("europe-west3", 0.023)]
    services = [{"serviceId": "A", "displayName": "Compute Engine"}, {"serviceId": "B", "displayName": "Cloud Storage"}]
    assert pull_gcp.find_service_id(services, "Cloud Storage") == "B"
    with pytest.raises(KeyError):
        pull_gcp.find_service_id(services, "BigQuery")
