"""M06: topology schema, referential checks, committed files and volume totals."""
import copy
import json
from pathlib import Path

import pytest

from topologies import build
from topologies.validate import main as validate_main, summarise, validate_topology

TOPO = Path(__file__).resolve().parent.parent / "topologies"
FILES = ["t1_three_tier.json", "t2_pipeline.json", "t3_microservices.json"]


def load(name):
    return json.loads((TOPO / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FILES)
def test_committed_topology_is_valid(name):
    assert validate_topology(load(name)) == []


@pytest.mark.parametrize("name", FILES)
def test_every_volume_has_provenance_and_rationale(name):
    doc = load(name)
    for e in doc["edges"] + doc["internet_egress"]:
        assert e["provenance"].strip() and e["rationale"].strip()


@pytest.mark.parametrize("name", FILES)
def test_h1_traffic_condition(name):
    s = summarise(load(name))
    print(f"{s['id']}: inter_component_gb={s['inter_component_gb']} internet_gb={s['internet_gb']}")
    assert s["inter_component_gb"] >= 500


def test_committed_files_match_builder():
    for name, doc in zip(build.FILENAMES, build.build_all()):
        assert load(name) == json.loads(json.dumps(doc)), f"{name} is stale: run python -m topologies.build"


def test_t2_t3_totals_reported():
    t2, t3 = summarise(load(FILES[1])), summarise(load(FILES[2]))
    print(f"T2 edge volume sum = {t2['inter_component_gb']} GB/month over {t2['edges']} edges")
    print(f"T3 edge volume sum = {t3['inter_component_gb']} GB/month over {t3['edges']} edges")
    assert t2["inter_component_gb"] == pytest.approx(3621.0)
    assert t3["edges"] == 30


def test_t3_has_eleven_online_boutique_services():
    ids = {c["id"] for c in load(FILES[2])["components"]}
    assert ids == {"frontend", "cart", "productcatalog", "currency", "payment", "shipping",
                   "email", "checkout", "recommendation", "ad", "redis-cart"}


def test_gb_per_month_unit():
    # 1 kB per request at 1 req/s for 30 days = 2.592 GB
    assert build.gb_per_month(1000, 1) == pytest.approx(2.592)


@pytest.fixture
def t1():
    return copy.deepcopy(load(FILES[0]))


def test_rejects_missing_endpoint(t1):
    t1["edges"][0]["dst"] = "nope"
    assert any("not a component" in e for e in validate_topology(t1))


def test_rejects_self_edge(t1):
    t1["edges"][0]["dst"] = t1["edges"][0]["src"]
    assert any("self-edge" in e for e in validate_topology(t1))


def test_rejects_negative_volume(t1):
    t1["edges"][0]["gb_per_month"] = -1
    assert validate_topology(t1)


def test_rejects_bad_pin(t1):
    t1["components"][0]["pinned_to"] = "oracle"
    assert validate_topology(t1)


def test_accepts_valid_pin(t1):
    t1["components"][0]["pinned_to"] = "gcp"
    assert validate_topology(t1) == []


def test_rejects_empty_provenance(t1):
    t1["internet_egress"][0]["provenance"] = ""
    assert validate_topology(t1)


def test_rejects_duplicate_edge_and_component(t1):
    t1["edges"].append(dict(t1["edges"][0]))
    t1["components"].append(dict(t1["components"][0]))
    errs = validate_topology(t1)
    assert any("duplicate edge" in e for e in errs) and any("duplicate component" in e for e in errs)


def test_cli_skips_schema_and_passes():
    assert validate_main([str(TOPO / "*.json")]) == 0
