"""Offline tests for pricing/pull_aws.py parsers, using excerpts recorded from the live Price List
API on 2026-09-21 (tests/data/aws_*_sample.csv). No network access.

Samples: EC2 = sa-east-1, first 100 rows of the file plus every on-demand m5.{large..4xlarge},
m5a.large and m5.metal row (all OS / licence variants, so the filters have decoys); data
transfer = us-east-1, the AWS Outbound and InterRegion Outbound rows (including rows sent *to*
us-east-1 from other regions); S3 = sa-east-1 General Purpose storage rows.
"""
from pathlib import Path

import pytest

from pricing import pull_aws
from pricing.aws_regions import AWS_LOCATION_NAMES
from pricing.common import LOCATIONS_EXT

DATA = Path(__file__).parent / "data"


def _rows(name, only=None):
    with open(DATA / name, encoding="utf-8") as f:
        return list(pull_aws.iter_offer_rows(f, only=only))


@pytest.fixture(scope="module")
def compute():
    rows = _rows("aws_ec2_sample.csv", only=("instance type", set(pull_aws.M5_SHAPES)))
    return pull_aws.parse_compute(rows, "sa-east-1")


@pytest.fixture(scope="module")
def egress():
    return pull_aws.parse_egress(_rows("aws_dt_sample.csv"), "us-east-1")


def test_header_is_lowercased_and_metadata_skipped():
    rows = _rows("aws_ec2_sample.csv")
    assert "capacitystatus" in rows[0] and "operating system" in rows[0]
    assert rows[0]["sku"]  # the first record is data, not one of the 5 metadata lines


def test_region_names_cover_ext_regions():
    assert set(AWS_LOCATION_NAMES) == set(LOCATIONS_EXT["aws"])


def test_compute_has_exactly_the_four_m5_shapes(compute):
    assert sorted(r["instance_type"] for r in compute) == [
        "m5.2xlarge", "m5.4xlarge", "m5.large", "m5.xlarge"]
    assert {r["shape"]: (r["vcpu"], r["ram_gb"]) for r in compute} == {
        "small": (2, 8.0), "medium": (4, 16.0), "large": (8, 32.0), "xlarge": (16, 64.0)}


def test_compute_filters_out_decoys(compute):
    """The sample holds Windows/RHEL/SQL, dedicated and m5a/m5.metal rows; none may survive."""
    raw = _rows("aws_ec2_sample.csv", only=("instance type", set(pull_aws.M5_SHAPES)))
    assert len(raw) > 4 * len(compute)
    assert len({r["sku"] for r in compute}) == 4
    assert all(r["region"] == "sa-east-1" and r["usd_per_hour"] > 0 for r in compute)


def test_compute_prices_scale_with_size(compute):
    price = {r["shape"]: r["usd_per_hour"] for r in compute}
    assert price["medium"] == pytest.approx(2 * price["small"])
    assert price["xlarge"] == pytest.approx(8 * price["small"])


def test_egress_internet_tiers_and_free_allowance(egress):
    tiers = sorted((r for r in egress if r["kind"] == "internet"), key=lambda r: r["tier_min_gb"])
    assert [r["usd_per_gb"] for r in tiers] == [0.09, 0.085, 0.07, 0.05]
    assert tiers[0]["tier_min_gb"] == 0 and tiers[-1]["tier_max_gb"] is None
    assert pull_aws.first_paid_internet_rate(egress, "us-east-1")["usd_per_gb"] == 0.09
    free = [r for r in egress if r["kind"] == "internet_free_allowance"]
    assert len(free) == 1 and free[0]["usd_per_gb"] == 0 and free[0]["tier_max_gb"] == 100


def test_egress_inter_region_is_sender_side_and_ext_only(egress):
    pairs = [r for r in egress if r["kind"] == "inter_region"]
    assert {r["dst_region"] for r in pairs} == set(LOCATIONS_EXT["aws"]) - {"us-east-1"}
    assert all(r["region"] == "us-east-1" and r["usd_per_gb"] > 0 for r in pairs)


def test_egress_ignores_rows_sent_to_the_region():
    """Read as us-west-2, the us-east-1 file yields only the one row sent *by* us-west-2 (to
    us-east-1) - not us-east-1's own internet tiers or its 7 outbound pairs."""
    rows = pull_aws.parse_egress(_rows("aws_dt_sample.csv"), "us-west-2")
    assert [(r["kind"], r["region"], r["dst_region"]) for r in rows
            if r["kind"] != "internet_free_allowance"] == [("inter_region", "us-west-2", "us-east-1")]


def test_storage_takes_s3_standard_only():
    rows = pull_aws.parse_storage(_rows("aws_s3_sample.csv"), "sa-east-1")
    assert [(r["tier_min_gb"], r["usd_per_gb_month"]) for r in rows] == [
        (0.0, 0.0405), (51200.0, 0.039), (512000.0, 0.037)]
    assert all(r["storage_class"] == "S3 Standard" for r in rows)


def test_num_handles_open_ended_tier():
    assert pull_aws._num("Inf") is None and pull_aws._num("") is None
    assert pull_aws._num("0.0900000000") == 0.09


def test_first_paid_internet_rate_missing_region():
    assert pull_aws.first_paid_internet_rate([], "us-east-1") is None
