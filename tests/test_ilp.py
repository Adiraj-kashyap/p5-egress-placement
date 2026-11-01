"""M10: exact ILP vs brute force, vs the cost evaluator, vs the baselines; CBC log parsing."""
import itertools
import json
import math
import random
from pathlib import Path

import pytest

from placement.baselines import PROVIDERS, b1_cheapest_per_vcpu, b1_tied_locations, b2_single_provider
from placement.cbc_log import parse_cbc_log, parse_cbc_log_file
from placement.cost import evaluate
from placement.ilp import FORMULATIONS, build_model, merged_pairs, solve_ilp
from placement.instance import Instance, load_instance

SNAPSHOT = "2026-09-21"
TOPOLOGIES = ["topologies/t1_three_tier.json", "topologies/t2_pipeline.json",
              "topologies/t3_microservices.json"]
DATA = Path(__file__).parent / "data"
N_TINY = 20


def make_tiny(seed: int) -> Instance:
    """Random tiny instance (2-4 components, 2-4 locations) with both-direction edges,
    self-loops, internet traffic and, on some seeds, a pinned component. Test input only."""
    rng = random.Random(seed)
    n_c, n_l = rng.randint(2, 4), rng.randint(2, 4)
    comps = tuple(f"c{i}" for i in range(n_c))
    locs = tuple(f"{rng.choice(['aws', 'azure', 'gcp'])}:r{i}" for i in range(n_l))
    k = {(c, l): rng.uniform(20.0, 200.0) for c in comps for l in locs}
    egress = {(a, b): 0.0 if a == b else rng.choice([0.01, 0.02, 0.05, 0.09, 0.12]) for a in locs for b in locs}
    edges = []
    for u, v in itertools.product(comps, comps):
        if rng.random() < (0.1 if u == v else 0.5):
            edges.append((u, v, rng.uniform(10.0, 3000.0)))
    allowed = {c: locs for c in comps}
    if seed % 4 == 0:
        allowed[comps[-1]] = (rng.choice(locs),)
    return Instance(
        instance_id=f"tiny{seed}@test", topology_id=f"tiny{seed}", snapshot_date="test", location_set="test",
        components=comps, locations=locs, shape={c: "small" for c in comps}, vcpu={c: 2 for c in comps},
        storage_gb={c: 0.0 for c in comps}, allowed=allowed, usd_per_hour={}, compute_month=k,
        storage_month={key: 0.0 for key in k}, k=k, edges=tuple(edges),
        internet_gb={c: rng.uniform(0.0, 500.0) for c in comps if rng.random() < 0.5},
        r={l: rng.choice([0.05, 0.08, 0.09, 0.12]) for l in locs}, egress=egress,
    )


def brute_force(inst: Instance) -> float:
    """Minimum evaluate() total over every allowed assignment (itertools.product)."""
    best = math.inf
    for combo in itertools.product(*(inst.allowed[c] for c in inst.components)):
        best = min(best, evaluate(inst, dict(zip(inst.components, combo))).total)
    return best


@pytest.fixture(scope="module")
def real():
    return [load_instance(t, SNAPSHOT, "core") for t in TOPOLOGIES]


@pytest.fixture(scope="module")
def solved(real):
    return {(inst.topology_id, f): solve_ilp(inst, time_limit=120, formulation=f)
            for inst in real for f in FORMULATIONS}


# ---- A1: brute force -------------------------------------------------------------------------

@pytest.mark.parametrize("formulation", FORMULATIONS)
@pytest.mark.parametrize("seed", range(N_TINY))
def test_ilp_equals_brute_force_on_tiny(seed, formulation):
    inst = make_tiny(seed)
    res = solve_ilp(inst, time_limit=30, formulation=formulation)
    assert res.proven_optimal
    assert math.isclose(res.objective, brute_force(inst), rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(res.objective, evaluate(inst, res.assignment).total, rel_tol=1e-6, abs_tol=1e-6)


def test_tiny_set_covers_the_cases_it_claims():
    insts = [make_tiny(s) for s in range(N_TINY)]
    assert all(i.n_components <= 4 and i.n_locations <= 4 for i in insts)
    assert any(len(i.allowed[c]) == 1 for i in insts for c in i.components)  # pinned
    assert any(u == v for i in insts for u, v, _ in i.edges)  # self-loop
    assert any(all(w > 0 for w in p) for i in insts for (u, v), p in merged_pairs(i).items() if u != v)


def test_brute_force_on_t1_core_matches_ilp(real, solved):
    """T1 on core is 12^4 = 20,736 assignments: small enough to enumerate against the real prices."""
    t1 = real[0]
    assert math.isclose(solved[(t1.topology_id, "tight")].objective, brute_force(t1), rel_tol=1e-9)


# ---- evaluator, pins, baselines --------------------------------------------------------------

@pytest.mark.parametrize("formulation", FORMULATIONS)
def test_objective_equals_evaluate_on_real(real, solved, formulation):
    for inst in real:
        res = solved[(inst.topology_id, formulation)]
        assert res.proven_optimal, res.cbc_result
        assert math.isclose(res.objective, evaluate(inst, res.assignment).total, rel_tol=1e-9)


def test_formulations_agree_on_real(real, solved):
    for inst in real:
        a, b = solved[(inst.topology_id, "tight")], solved[(inst.topology_id, "mccormick")]
        assert math.isclose(a.objective, b.objective, rel_tol=1e-9)


def test_pinned_components_respected(real):
    t2 = real[1]
    pinned = {c: t2.locations[-1] for c in t2.components[:2]}
    inst = Instance(**{**t2.__dict__, "allowed": {c: (pinned[c],) if c in pinned else t2.allowed[c]
                                                   for c in t2.components}})
    for f in FORMULATIONS:
        res = solve_ilp(inst, time_limit=60, formulation=f)
        assert all(res.assignment[c] == loc for c, loc in pinned.items())
        assert res.objective >= solve_ilp(t2, time_limit=60, formulation=f).objective - 1e-6


def test_ilp_not_worse_than_any_baseline(real, solved):
    for inst in real:
        ilp = solved[(inst.topology_id, "tight")].objective
        candidates = [b1_cheapest_per_vcpu(inst), {c: b1_tied_locations(inst, c)[-1] for c in inst.components}]
        candidates += [b2_single_provider(inst, p) for p in PROVIDERS]
        for a in candidates:
            assert ilp <= evaluate(inst, a).total + 1e-6


def test_model_size_formula(real):
    for inst in real:
        pairs = merged_pairs(inst)
        n_p, L, n = len(pairs), inst.n_locations, inst.n_components
        tight, _, _ = build_model(inst, "tight")
        mc, _, _ = build_model(inst, "mccormick")
        assert tight.numVariables() == n * L + n_p * L * L == mc.numVariables()
        assert tight.numConstraints() == n + 2 * n_p * L
        assert mc.numConstraints() == n + n_p * L * L


def test_merged_pairs_keeps_total_volume(real):
    for inst in real:
        assert math.isclose(sum(a + b for a, b in merged_pairs(inst).values()),
                            sum(gb for _, _, gb in inst.edges), rel_tol=1e-12)


def test_unknown_formulation_rejected(real):
    with pytest.raises(ValueError):
        build_model(real[0], "textbook")


def test_log_path_is_kept(real, tmp_path):
    p = tmp_path / "sub" / "t1.log"
    res = solve_ilp(real[0], time_limit=60, log_path=p)
    assert res.log_path == str(p) and p.stat().st_size > 0


def test_run_exact_appends_rows(tmp_path):
    import csv
    from experiments import run_exact
    out = tmp_path / "exact"
    for _ in range(2):
        run_exact.main(["--repeats", "1", "--time-limit", "60", "--out", str(out)])
    with open(out / "runs.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 * len(TOPOLOGIES) * len(FORMULATIONS)
    assert all(r["proven_optimal"] == "True" for r in rows)
    assert all(math.isclose(float(r["total_usd"]), float(r["cbc_objective"]), rel_tol=1e-6) for r in rows)
    assert len(list((out / "cbc").glob("*.log"))) == len(rows)
    assert json.loads((out / "config.json").read_text(encoding="utf-8"))["module"] == "M10"


# ---- CBC log parsing (real CBC output, trimmed to the summary) ------------------------------

def test_parse_optimal_log():
    s = parse_cbc_log_file(DATA / "cbc_optimal.log")
    assert s.proven_optimal and not s.stopped_on_time
    assert s.result == "Optimal solution found"
    assert math.isclose(s.objective, 1789.880832)
    assert s.best_bound == s.objective and s.gap == 0.0 and s.nodes == 0


def test_parse_stopped_on_time_log():
    s = parse_cbc_log_file(DATA / "cbc_stopped_on_time.log")
    assert not s.proven_optimal and s.stopped_on_time
    assert s.result == "Stopped on time limit"
    assert math.isclose(s.objective, 4942.61033173)
    assert math.isclose(s.best_bound, 1269.196) and math.isclose(s.gap, 2.89)


def test_parse_empty_log():
    s = parse_cbc_log("")
    assert s.result == "" and not s.proven_optimal and s.objective is None and s.best_bound is None
