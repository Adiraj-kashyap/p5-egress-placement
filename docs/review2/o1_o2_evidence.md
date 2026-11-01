# O1 and O2 — working code in version control

Review-2 rubric line: *"Objectives O1 and O2 evidenced — working code in a version-controlled
repository" (4 marks)*. Everything below is in this repository; no number on this page was typed
by hand.

Repository: see [`repo.md`](repo.md) (GitHub URL + green CI run).
Snapshot date used everywhere: **2026-09-21**. Location sets: `core` (12 locations) and
`ext` (24 locations), `provider:region`.

## Status of the build

| Fact | Value | Where it comes from |
|---|---|---|
| Commits on `main` | 68 at the start of M19, one per closed module plus run commits | `git log --oneline \| wc -l` |
| Modules closed with evidence | M00–M18 (19 of 25) | `state/STATE.md` module table |
| Tests | **407 passed** (~120 s) | `pytest -q -m "not live and not testbed"`, `logs/M19_pytest_ci_subset.txt` |
| CI | GitHub Actions, ubuntu-latest, Python 3.11, installs `requirements.lock.txt` | `.github/workflows/tests.yml` |
| Experiment rows produced | 8,100 replicates + 4,320 ablation + 1,800 sensitivity + 1,250 scaling + 1,500 sweep + 162 timing | `results/*/runs.csv` |

Every experiment row records the git commit it was produced at, the snapshot date and a machine
tag (`experiments/runner.py`, 01 §4); the runner refuses to start on a dirty working tree unless
`--allow-dirty` is passed, and the one run where that happened is recorded in D-053.

## O1 — unified cost model for AWS, Azure and GCP

**Objective.** *A unified cost model covering compute, storage and inter-provider transfer for
AWS, GCP and Azure, built from public pricing APIs and pages.*

| Piece | Code | Output | Tests |
|---|---|---|---|
| Azure pull (Retail Prices API) | `pricing/pull_azure.py` | `snapshots/2026-09-21/azure_*.json` (32 / 120 / 24 rows) | `tests/test_pull_azure.py` (8) |
| AWS pull (per-region bulk CSV) | `pricing/pull_aws.py`, `pricing/aws_regions.py` | `snapshots/2026-09-21/aws_*.json` (32 / 96 / 24) | `tests/test_pull_aws.py` (11) |
| GCP pull (public pricing pages, D-026) | `pricing/pull_gcp.py`, `pricing/gcp_pages.py` | `snapshots/2026-09-21/gcp_*.json` (16 / 217 / 8) | `tests/test_pull_gcp.py` (22) |
| Unification | `pricing/build_cost_model.py` | `cost_model/2026-09-21/{compute,storage,egress,internet}.csv` | `tests/test_cost_model.py` (16) |
| Validation | `pricing/validate_cost_model.py` | `cost_model/2026-09-21/validation.md` | same |
| Free-tier / secret guard | — | — | `tests/test_free_tier.py` (7) |

**Shape of the model.** 24 locations × 4 shapes = **96** compute rows (`usd_per_month` = hourly
× 730); **24** storage rows (USD/GB-month); **576** directed egress cells (24 × 24, sender pays);
**24** internet rows (end-user egress per sender region). Methodology: `cost_model/README.md`.
Summary table with every location's price: `docs/report/tables/cost_model.md`.

**Validation — 10 of 10 checks PASS** (`cost_model/2026-09-21/validation.md`):

| Check | Result |
|---|---|
| V1 compute = 24 × 4 = 96 rows | PASS (96 distinct) |
| V2 egress = 24 × 24 = 576 directed cells | PASS (576 distinct ordered pairs) |
| V3 diagonal is 0 | PASS (24/24) |
| V4 all prices finite, non-negative | PASS (0 bad values) |
| V5 per shape, max/min over core < 3× | PASS (1.250× for all four shapes) |
| V6 GCP composed vs AWS matched region within 0.5×–2× | PASS (32 ratios, 0.998–1.155) |
| V7 matrix asymmetric where senders differ | PASS (229 unordered pairs asymmetric) |
| V8 fallback cells ≤ 25% of R2 cells | PASS — **0 of 168 R2 cells (0.0%)** |
| V9 rule (R1/R2/R3) matches endpoints, every cell has a source | PASS (0 mismatches) |
| V10 internet and storage: one positive price per location | PASS (24 + 24 rows) |

Every egress cell carries its rule (**R1** same region 24, **R2** same provider 168, **R3**
cross-provider 384) and the SKU or page it came from, so any single price is traceable back to a
vendor identifier.

**The asymmetry that motivates the project is real, not assumed:** 229 of the 276 unordered
location pairs are priced differently in the two directions (V7).

## O2 — placement as an optimisation problem with explicit per-edge egress

**Objective.** *A formulation of multi-component placement as an optimisation problem with
explicit egress on each communicating edge.*

| Piece | Code / document |
|---|---|
| Written formulation, exactness proof, size formula, tight ⊂ McCormick relaxation | `docs/report/formulation.md` |
| ILP (two formulations, CBC single-threaded) | `placement/ilp.py`, `placement/cbc_log.py` |
| The one cost function everything is scored by | `placement/cost.py::evaluate` |
| Instance loading (locations, pins, rates) | `placement/instance.py` |
| Tests | `tests/test_ilp.py` (**55**), `tests/test_placement_baselines.py` (13) |

**Equivalence evidence (the claim "the ILP objective is the real cost").** `tests/test_ilp.py`
brute-forces **20 seeded tiny instances** over both formulations and requires the ILP objective to
equal `evaluate()` on the returned assignment and to equal the enumerated optimum; T1 at real
prices is included. The same file checks that `Result.proven_optimal` is parsed from the CBC log
rather than trusted from PuLP's status string — a real time-limited run reports PuLP `Optimal`
while CBC says "Stopped on time limit" with gap 2.89 (`tests/data/cbc_stopped_on_time.log`).

**T1–T3 solved to proven optimality** (core set, s = 1, median of 5 repeats, single thread;
source `results/exact/runs.csv`, table `docs/report/tables/exact.md`):

| Topology | Formulation | Optimum USD/month | Proven optimal | Median runtime s | Variables | Constraints |
|---|---|---|---|---|---|---|
| T1 three-tier | tight | 481.18 | 5/5 | 0.0627 | 480 | 76 |
| T1 three-tier | McCormick | 481.18 | 5/5 | 0.0793 | 480 | 436 |
| T2 pipeline | tight | 1,028.79 | 5/5 | 0.0768 | 1,092 | 175 |
| T2 pipeline | McCormick | 1,028.79 | 5/5 | 0.107 | 1,092 | 1,015 |
| T3 microservices | tight | 1,789.88 | 5/5 | 0.121 | 2,292 | 371 |
| T3 microservices | McCormick | 1,789.88 | 5/5 | 0.16 | 2,292 | 2,171 |

Both formulations return the same optimum on all three topologies, and the tight one is smaller
and faster — the constraint-count column is the empirical form of the proof in `formulation.md`.
On the synthetic scaling grid every ILP up to n = 40 was proven optimal, the slowest in 46.3 s
(D-055), so the exact frontier was never reached within the studied range.

**Beyond O1/O2, the same code base carries O3 and O4** (evidence in
[`comparative_results.md`](comparative_results.md) and [`ablation_and_sweep.md`](ablation_and_sweep.md)):
`placement/greedy.py` (greedy + 1-opt), `placement/annealing.py` (SA), `placement/ablations.py`
(ablation variants), `experiments/` (runner, generator, uncertainty draws), `analysis/`
(stats, figures, tables, verdicts).

## Module and commit history

From `state/STATE.md`. "Commit" is the closing commit where STATE records one.

| Module | Title | Status | Commit |
|---|---|---|---|
| M00 | Bootstrap and environment evidence | DONE | 3c76e41 |
| M01 | Literature survey verification | DONE | d07839d |
| M02 | Azure pricing pull | DONE | 49144f3 |
| M03 | AWS pricing pull | DONE | 89e6907 |
| M04 | GCP pricing pull | DONE_WITH_WAIVER | c96d388 |
| M05 | Unified cost model and validation | DONE | 7580fb0 |
| M06 | Application topologies and schema | DONE | 985b002 |
| M07 | Testbed and measured traffic | DONE | dc365ec |
| M08 | Cost evaluator and baselines | DONE | d51adf8 |
| M09 | Review-1 pack | DONE | tag `review1` |
| M10 | Exact ILP | DONE | 89cb6a3 |
| M11 | Egress-aware greedy | DONE | 175b3e5 |
| M12 | Simulated annealing | DONE | 540c55c |
| M13 | Experiment harness and generator | DONE | c1dff72 |
| M14 | Scaling and optimality-gap experiment | DONE | see `git log` |
| M15 | Traffic sweep, penalty, crossover | DONE | see `git log` |
| M16 | Replication and uncertainty framework | DONE | see `git log` |
| M17 | Ablation study | DONE | see `git log` |
| M18 | Analysis, figures with CIs, verdicts | DONE | see `git log` |
| M19 | Review-2 pack (this pack) | in progress | this commit |

Each closed module has an entry in `state/AUDIT_LOG.md` with the real output of every acceptance
check, and every non-trivial choice is an ADR in `docs/design_decisions.md` (D-001 … D-083).
