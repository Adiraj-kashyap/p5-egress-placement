"""M05 cost model: built from the committed 2026-09-21 snapshot plus small offline cases."""
import math

import pytest

from pricing import build_cost_model as bcm
from pricing import validate_cost_model as vcm
from pricing.common import LOCATIONS_EXT, ROOT

SNAP = ROOT / "snapshots" / "2026-09-21"


@pytest.fixture(scope="module")
def tables():
    return bcm.build_all(snapshot_dir=SNAP)


@pytest.fixture(scope="module")
def rate(tables):
    return {(f"{e['src_provider']}:{e['src_region']}", f"{e['dst_provider']}:{e['dst_region']}"):
            e["usd_per_gb"] for e in tables["egress"]}


def test_row_counts(tables):
    assert len(tables["compute"]) == 24 * 4
    assert len(tables["egress"]) == 24 * 24
    assert len(tables["internet"]) == 24
    assert len(tables["storage"]) == 24


def test_diagonal_zero_and_rule_r1(tables):
    diag = [e for e in tables["egress"]
            if (e["src_provider"], e["src_region"]) == (e["dst_provider"], e["dst_region"])]
    assert len(diag) == 24
    assert all(e["usd_per_gb"] == 0.0 and e["rule"] == "R1" for e in diag)


def test_all_prices_non_negative_and_finite(tables):
    for name, col in (("compute", "usd_per_hour"), ("storage", "usd_per_gb_month"),
                      ("egress", "usd_per_gb"), ("internet", "usd_per_gb")):
        for r in tables[name]:
            assert math.isfinite(r[col]) and r[col] >= 0, (name, r)


def test_off_diagonal_positive(tables):
    off = [e for e in tables["egress"] if e["rule"] != "R1"]
    assert all(e["usd_per_gb"] > 0 for e in off)


def test_rules_follow_endpoints(tables):
    for e in tables["egress"]:
        same_p = e["src_provider"] == e["dst_provider"]
        same_r = same_p and e["src_region"] == e["dst_region"]
        assert e["rule"] == ("R1" if same_r else "R2" if same_p else "R3")
        assert e["source"]


def test_asymmetric_where_expected(rate):
    # R3 is priced by the sender: AWS sa-east-1 internet 0.15 vs Azure eastus MGN 0.087.
    a, b = "aws:sa-east-1", "azure:eastus"
    assert rate[(a, b)] == pytest.approx(0.15)
    assert rate[(b, a)] == pytest.approx(0.087)
    # R2 on Azure depends on the sender continent: Brazil out 0.16, into Brazil from NA 0.05.
    assert rate[("azure:brazilsouth", "azure:eastus")] == pytest.approx(0.16)
    assert rate[("azure:eastus", "azure:brazilsouth")] == pytest.approx(0.05)


def test_r3_ignores_destination_except_gcp(rate):
    # AWS and Azure internet egress does not depend on who receives it.
    assert rate[("aws:us-east-1", "azure:brazilsouth")] == rate[("aws:us-east-1", "gcp:us-east4")]
    # GCP prices by destination group: South America group costs more than North America.
    assert rate[("gcp:us-east4", "aws:sa-east-1")] > rate[("gcp:us-east4", "aws:us-east-1")]


def test_azure_intercontinental_vs_intra(rate):
    assert rate[("azure:eastus", "azure:westus2")] == pytest.approx(0.02)
    assert rate[("azure:eastus", "azure:westeurope")] == pytest.approx(0.05)
    assert rate[("azure:westeurope", "azure:germanywestcentral")] == pytest.approx(0.02)


def test_no_fallback_cells(tables):
    assert not [e for e in tables["egress"] if e["source"].startswith("fallback:")]


def test_gcp_composition_arithmetic(tables):
    gcp_rows = bcm.load_snapshot("gcp_compute", SNAP)
    for region in LOCATIONS_EXT["gcp"]:
        core = next(r["usd_per_hour"] for r in gcp_rows if r["region"] == region and r["resource"] == "core")
        ram = next(r["usd_per_hour"] for r in gcp_rows if r["region"] == region and r["resource"] == "ram")
        for shape in bcm.SHAPES:
            row = next(c for c in tables["compute"] if c["provider"] == "gcp"
                       and c["region"] == region and c["shape"] == shape["name"])
            expect = shape["vcpu"] * core + shape["ram_gb"] * ram
            assert row["usd_per_hour"] == pytest.approx(expect, abs=1e-6)
            assert row["usd_per_month"] == pytest.approx(expect * 730, abs=1e-3)
            assert row["instance_type"] == f"n2-standard-{shape['vcpu']}"


def test_gcp_composition_formula():
    assert bcm.gcp_composed_hourly(2, 8, 0.031611, 0.004237) == pytest.approx(0.097118)


def test_first_paid_skips_free_tiers():
    rows = [{"tier_min_gb": 0.0, "usd_per_gb": 0.0}, {"tier_min_gb": 100.0, "usd_per_gb": 0.087},
            {"tier_min_gb": 10335.0, "usd_per_gb": 0.083}]
    assert bcm.first_paid(rows)["usd_per_gb"] == 0.087
    assert bcm.first_paid([{"tier_min_gb": 0.0, "usd_per_gb": 0.0}]) is None


def test_missing_r2_price_falls_back_and_is_marked():
    aws = [{"kind": "internet", "region": r, "tier_min_gb": 0.0, "usd_per_gb": 0.09, "sku": "X"}
           for r in LOCATIONS_EXT["aws"]]
    res = bcm.EgressResolver(aws, [], [])
    rate, source = res.inter_region("aws", "us-east-1", "eu-west-1")
    assert rate is None and source.startswith("fallback:")


def test_fixture_snapshot_refused(tmp_path):
    (tmp_path / "aws_compute.json").write_text('{"meta": {"FIXTURE": true}, "rows": []}')
    with pytest.raises(ValueError, match="FIXTURE"):
        bcm.load_snapshot("aws_compute", tmp_path)


def test_validator_passes_on_built_tables(tables):
    as_str = {n: [{k: str(v) for k, v in r.items()} for r in rows] for n, rows in tables.items()}
    checks, _ = vcm.run_checks(as_str["compute"], as_str["storage"], as_str["egress"], as_str["internet"])
    assert all(ok for _, _, ok, _ in checks), [c for c in checks if not c[2]]


def test_validator_catches_bad_diagonal(tables):
    as_str = {n: [{k: str(v) for k, v in r.items()} for r in rows] for n, rows in tables.items()}
    as_str["egress"][0]["usd_per_gb"] = "0.01"
    checks, _ = vcm.run_checks(as_str["compute"], as_str["storage"], as_str["egress"], as_str["internet"])
    assert not dict((c[0], c[2]) for c in checks)["V3"]
