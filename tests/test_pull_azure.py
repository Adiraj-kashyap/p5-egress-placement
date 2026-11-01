"""Offline tests for pricing/pull_azure.py parsers, using a response recorded from the live API
(tests/data/azure_sample.json). No network access."""
import json
from pathlib import Path

import pytest

from pricing import pull_azure
from pricing.azure_shapes import AZURE_SHAPES, SHAPE_TO_SKU
from pricing.common import CONTINENT, LOCATIONS_CORE, LOCATIONS_EXT, location_id

SAMPLE = json.loads((Path(__file__).parent / "data" / "azure_sample.json").read_text(encoding="utf-8"))


def test_location_sets():
    for provider in ("aws", "azure", "gcp"):
        assert len(LOCATIONS_CORE[provider]) == 4
        assert len(LOCATIONS_EXT[provider]) == 8
        assert set(LOCATIONS_CORE[provider]) <= set(LOCATIONS_EXT[provider])
        assert len(set(LOCATIONS_EXT[provider])) == 8
        for region in LOCATIONS_EXT[provider]:
            assert region in CONTINENT
    assert location_id("aws", "us-east-1") == "aws:us-east-1"


def test_shapes_match_project_shapes():
    assert [AZURE_SHAPES[SHAPE_TO_SKU[s]] for s in ("small", "medium", "large", "xlarge")] == [
        (2, 8), (4, 16), (8, 32), (16, 64)]


def test_parse_compute_drops_spot_lowpriority_windows():
    raw = SAMPLE["compute"]
    assert any("Spot" in r["skuName"] for r in raw)          # sample really contains the noise
    assert any("Windows" in r["productName"] for r in raw)
    rows = pull_azure.parse_compute(raw)
    assert len(rows) == 4                                     # one Linux on-demand row per shape
    assert {r["shape"] for r in rows} == {"small", "medium", "large", "xlarge"}
    for r in rows:
        assert "Spot" not in r["sku_name"] and "Low Priority" not in r["sku_name"]
        assert "Windows" not in r["product_name"]
        assert (r["vcpu"], r["ram_gb"]) == AZURE_SHAPES[r["instance_type"]]
        assert r["usd_per_hour"] > 0


def test_parse_compute_price_scales_with_size():
    by_shape = {r["shape"]: r["usd_per_hour"] for r in pull_azure.parse_compute(SAMPLE["compute"])}
    assert by_shape["small"] < by_shape["medium"] < by_shape["large"] < by_shape["xlarge"]


def test_parse_egress_categories_and_regions():
    rows = pull_azure.parse_egress(SAMPLE["egress"], regions=["eastus", "brazilsouth"])
    cats = {r["category"] for r in rows}
    assert {"internet_out", "inter_region", "inter_region_continent_fallback"} <= cats
    assert all(r["unit"] == "1 GB" for r in rows)             # hourly China meters dropped
    regional = [r for r in rows if r["category"] != "inter_region_continent_fallback"]
    assert {r["region"] for r in regional} <= {"eastus", "brazilsouth"}   # japaneast filtered out


def test_first_paid_internet_rate_skips_free_tier():
    rows = pull_azure.parse_egress(SAMPLE["egress"], regions=["eastus", "brazilsouth"])
    us = pull_azure.first_paid_internet_rate(rows, "eastus")
    assert us["tier_min_gb"] == 100 and us["usd_per_gb"] == pytest.approx(0.087)
    br = pull_azure.first_paid_internet_rate(rows, "brazilsouth")
    assert br["usd_per_gb"] > us["usd_per_gb"]
    assert pull_azure.first_paid_internet_rate(rows, "nowhere") is None


def test_inter_region_rate_is_sender_specific():
    rows = pull_azure.parse_egress(SAMPLE["egress"], regions=["eastus", "brazilsouth"])
    rate = {r["region"]: r["usd_per_gb"] for r in rows if r["category"] == "inter_region"}
    assert rate["eastus"] == pytest.approx(0.02)
    assert rate["brazilsouth"] == pytest.approx(0.16)         # asymmetric across senders


def test_parse_storage_hot_lrs_base_tier():
    rows = pull_azure.parse_storage(SAMPLE["storage"])
    assert rows, "no Hot LRS data-stored rows"
    base = min(rows, key=lambda r: r["tier_min_gb"])
    assert base["tier_min_gb"] == 0
    assert 0.005 <= base["usd_per_gb_month"] <= 0.1
