"""Tests for experiments/runner.py (M13 step 5): job expansion, crash-safe resume, config guard.

The resume test runs the runner in a subprocess and hard-kills it (`--stop-after`, os._exit)
after k jobs, then reruns it and checks there are no duplicate or missing rows.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter

import pytest

from experiments.runner import (FIELDS, METHODS, STANDARD_FIELDS, append_row, build_jobs, existing_header,
                                instance_specs, job_key, load_config)
from pricing.common import ROOT

CONFIG = {
    "exp_id": "test_resume",
    "snapshot_date": "2026-09-21",
    "location_set": "core",
    "instances": [{"synthetic": {"n": [3, 5], "seeds": [1]}}],
    "methods": sorted(METHODS),
    "method_seeds": [0, 1],
    "time_limits": {"ilp_tight": 60, "ilp_mccormick": 60},
    "method_params": {"sa": {"alpha": 0.99}},
}
# 2 instances x (one job per deterministic method + 2 seeds per randomised one). Written as a
# sum over the registry rather than a literal, so adding a method (M16's b1_alt, M17's
# ablation variants) cannot silently change what this test is asserting.
N_JOBS = 2 * sum(2 if METHODS[m].randomised else 1 for m in METHODS)


def run(cfg_path, out, *extra) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "experiments.runner", str(cfg_path), "--out", str(out),
                           "--allow-dirty", *extra], cwd=ROOT, capture_output=True, text=True, timeout=300)


def rows(out) -> list[dict]:
    with open(out / "runs.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def keys(rs) -> Counter:
    return Counter((r["instance_id"], r["method"], r["seed"]) for r in rs)


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "test_resume.json"
    p.write_text(json.dumps(CONFIG), encoding="utf-8")
    return p


def test_standard_columns_first():
    assert FIELDS[:len(STANDARD_FIELDS)] == STANDARD_FIELDS
    assert len(set(FIELDS)) == len(FIELDS)


def test_smoke_config_expands():
    cfg, _ = load_config("smoke")
    specs = instance_specs(cfg)
    assert len(specs) == 4  # 2 sizes x 2 seeds
    # The smoke config is frozen: results/smoke was produced under its hash and the runner
    # refuses to mix results from a changed config (D-051), so methods added after that run
    # are not in the grid. b1_alt came with M16 (D-069); the ablation variants came with M17
    # (D-071) and are exercised by results/ablation and tests/test_ablations.py instead.
    ADDED_AFTER_SMOKE = {"b1_alt", "ilp_full", "ilp_no_edge_egress", "ilp_no_internet",
                         "ilp_undirected", "ilp_single_provider", "b1_storage",
                         "sa_random_init", "sa_no_swap"}
    assert set(cfg["methods"]) == set(METHODS) - ADDED_AFTER_SMOKE
    assert len(cfg["method_seeds"]) == 2


def test_scaling_config_job_grid():
    """M14 grid: 10 sizes x 5 seeds x 2 location sets; McCormick only for n <= 12 (method_max_n)."""
    cfg, _ = load_config("scaling")
    jobs = build_jobs(cfg)
    per = Counter(m for _, _, m, _, _ in jobs)
    assert per == {"ilp_tight": 100, "greedy_1opt": 100, "sa": 1000, "ilp_mccormick": 50}
    assert all(dict(spec.gen)["n"] <= 12 for _, spec, m, _, _ in jobs if m == "ilp_mccormick")
    assert {dict(spec.gen)["n"] for _, spec, m, _, _ in jobs if m == "ilp_tight"} == {4, 6, 8, 10, 12, 15, 20, 25, 30, 40}


def test_method_max_n_validation(tmp_path):
    cfg, _ = load_config("smoke")
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({**cfg, "methods": ["greedy"], "method_max_n": {"ilp_tight": 5}}), encoding="utf-8")
    with pytest.raises(ValueError, match="method_max_n"):
        load_config(str(p))
    topo = {**cfg, "instances": [{"topology": "topologies/t1_three_tier.json"}], "methods": ["greedy"],
            "method_max_n": {"greedy": 5}}
    with pytest.raises(ValueError, match="only to synthetic"):
        build_jobs(topo)


def test_resume_after_hard_kill(cfg_path, tmp_path):
    out = tmp_path / "out"
    first = run(cfg_path, out, "--stop-after", "5")
    assert first.returncode == 3, first.stdout + first.stderr
    assert len(rows(out)) == 5

    second = run(cfg_path, out)
    assert second.returncode == 0, second.stdout + second.stderr
    rs = rows(out)
    assert len(rs) == N_JOBS
    assert max(keys(rs).values()) == 1
    assert f"skipped (already present) 5 | run {N_JOBS - 5}" in second.stdout
    assert all(r["git_commit"] and r["snapshot_date"] == "2026-09-21" for r in rs)
    assert all(float(r["total_usd"]) > 0 for r in rs)
    assert {r["status"] for r in rs if r["method"].startswith("ilp")} == {"optimal"}
    assert sorted(r["seed"] for r in rs if r["method"] == "sa") == ["0", "0", "1", "1"]
    record = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert [s["jobs_run"] for s in record["sessions"]] == [0, N_JOBS - 5]  # killed session never finished
    assert [s["finished"] for s in record["sessions"]] == [False, True]
    assert set(record["instances"]) == {"syn_n3_s1@core", "syn_n5_s1@core"}

    third = run(cfg_path, out)
    assert third.returncode == 0 and len(rows(out)) == N_JOBS
    assert f"skipped (already present) {N_JOBS} | run 0" in third.stdout


def test_torn_last_line_is_rerun(cfg_path, tmp_path):
    out = tmp_path / "out"
    assert run(cfg_path, out, "--stop-after", "3").returncode == 3
    lines = (out / "runs.csv").read_bytes().splitlines(keepends=True)
    torn = lines[-1][: len(lines[-1]) // 2]
    (out / "runs.csv").write_bytes(b"".join(lines[:-1]) + torn)
    res = run(cfg_path, out)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "torn line" in res.stdout
    rs = rows(out)
    assert len(rs) == N_JOBS and max(keys(rs).values()) == 1


def test_refuses_changed_config(cfg_path, tmp_path):
    out = tmp_path / "out"
    assert run(cfg_path, out, "--stop-after", "1").returncode == 3
    changed = dict(CONFIG, method_seeds=[0, 1, 2])
    cfg_path.write_text(json.dumps(changed), encoding="utf-8")
    res = run(cfg_path, out)
    assert res.returncode == 2
    assert "different config" in res.stdout
    assert len(rows(out)) == 1


def test_unknown_method_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(dict(CONFIG, methods=["greedy", "magic"])), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown methods"):
        load_config(str(p))


# --------------------------------------------------------------- M16 replication axes


def test_draw_and_scale_axes_expand_instances():
    """draws x scales multiply the instance list and land in the instance id (M16 step 3)."""
    cfg = dict(CONFIG, draws=[0, 1, 2], scales=[1.0, 10.0])
    specs = instance_specs(cfg)
    assert len(specs) == 2 * 3 * 2
    assert {s.draw_id for s in specs} == {0, 1, 2}
    assert {s.scale for s in specs} == {1.0, 10.0}
    suffixes = {s.suffix() for s in specs}
    assert "@d=0@s=1" in suffixes and "@d=2@s=10" in suffixes


def test_no_axes_keeps_the_old_behaviour():
    specs = instance_specs(CONFIG)
    assert all(s.draw_id is None and s.scale is None and s.suffix() == "" for s in specs)


def test_timing_repeats_multiply_jobs_and_number_the_repeats():
    base = len(build_jobs(CONFIG))
    jobs = build_jobs(dict(CONFIG, timing_repeats=3))
    assert len(jobs) == 3 * base
    assert {rep for *_, rep in jobs} == {0, 1, 2}
    assert {rep for *_, rep in build_jobs(CONFIG)} == {None}
    with pytest.raises(ValueError, match="timing_repeats"):
        build_jobs(dict(CONFIG, timing_repeats=0))


def test_job_key_separates_repeats_and_is_backward_compatible():
    assert job_key("i@core", "sa", 1, 0) != job_key("i@core", "sa", 1, 1)
    assert job_key("i@core", "greedy", None, None) == job_key("i@core", "greedy", None, "")


def test_new_columns_exist_and_come_after_the_standard_ones():
    for col in ("draw_id", "repeat_id", "traffic_scale"):
        assert col in FIELDS and col not in STANDARD_FIELDS
    assert FIELDS[: len(STANDARD_FIELDS)] == STANDARD_FIELDS


def test_drawn_instances_are_paired_across_methods():
    """The same draw id gives the same instance to every method, so comparisons are paired."""
    cfg = dict(CONFIG, instances=[{"topology": "topologies/t2_pipeline.json"}], draws=[4], scales=None)
    specs = instance_specs(cfg)
    assert len(specs) == 1
    volumes = [[e["gb_per_month"] for e in specs[0].topology("core")["edges"]] for _ in range(2)]
    assert volumes[0] == volumes[1]


def test_append_row_keeps_an_existing_header(tmp_path):
    """A results dir written before the M16 columns existed keeps its own header on resume."""
    runs = tmp_path / "runs.csv"
    old = STANDARD_FIELDS
    runs.write_text(",".join(old) + "\n", encoding="utf-8")
    append_row(runs, {k: "x" for k in FIELDS})
    with open(runs, newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    assert list(got[0]) == old
    assert existing_header(runs) == old