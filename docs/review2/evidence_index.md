# Review-2 evidence index — rubric line → files

Every path below exists in this repository. Verify with:

    .\.venv\Scripts\python.exe -m analysis.check_evidence_index docs/review2/evidence_index.md

(exit 1 if any non-screenshot path is missing). Screenshots are listed separately because they are
added by hand.

---

## Line 1 — Objectives O1 and O2 evidenced (4 marks)

*Full credit: working code in a version-controlled repository.*

| Evidence | Path |
|---|---|
| The packaged argument | `docs/review2/o1_o2_evidence.md` |
| Repo URL + CI description + clean-clone reproduction | `docs/review2/repo.md` |
| CI workflow | `.github/workflows/tests.yml` |
| Test configuration and markers | `pytest.ini` |
| Pinned dependencies | `requirements.lock.txt` |
| Local run of the CI command (407 passed) | `logs/M19_pytest_ci_subset.txt` |
| **O1** price pulls | `pricing/pull_azure.py`, `pricing/pull_aws.py`, `pricing/pull_gcp.py`, `pricing/gcp_pages.py`, `pricing/aws_regions.py` |
| **O1** dated snapshots | `snapshots/2026-09-21/` |
| **O1** unified model + methodology | `pricing/build_cost_model.py`, `cost_model/2026-09-21/`, `cost_model/README.md` |
| **O1** validation, 10/10 PASS | `cost_model/2026-09-21/validation.md`, `pricing/validate_cost_model.py` |
| **O1** price summary table | `docs/report/tables/cost_model.md` |
| **O2** written formulation and proof | `docs/report/formulation.md` |
| **O2** solver + CBC log parser | `placement/ilp.py`, `placement/cbc_log.py` |
| **O2** the one cost function | `placement/cost.py` |
| **O2** brute-force equivalence tests | `tests/test_ilp.py` |
| **O2** proven-optimal solves on T1–T3 | `results/exact/runs.csv`, `docs/report/tables/exact.md` |
| Module history, audit trail, decisions | `state/STATE.md`, `state/AUDIT_LOG.md`, `docs/design_decisions.md` |

## Line 2 — Comparative results vs baseline (3 marks)

*Full credit: ≥ 1 graph with baseline and proposed method on the same axes.*

| Evidence | Path |
|---|---|
| The packaged argument, with captions and per-topology reading | `docs/review2/comparative_results.md` |
| **The graph** (PNG + PDF + data with n and CIs) | `figures/R2-1_cost_vs_scale.png`, `figures/R2-1_cost_vs_scale.pdf`, `figures/R2-1_cost_vs_scale.csv` |
| Cost breakdown by term | `figures/F1_cost_breakdown.png`, `figures/F1_cost_breakdown.csv` |
| Replicated H1 table (T-H1/T-H2/T-H3) | `docs/report/tables/h1_replicated.md` |
| Baselines B1, B1-alt, B2-best | `placement/baselines.py`, `docs/report/tables/baselines.md` |
| Replicated runs (8,100) and their summary | `results/replicates/` |
| Verdicts under the frozen rules | `docs/report/verdicts.md`, `analysis/verdicts.py`, `analysis/thresholds.py` |
| Narrative results section | `docs/report/results.md` |

## Line 3 — Ablation or parameter sweep (2 marks)

*Full credit: which component causes the gain, or how the result moves with load, scale or cost.*

| Evidence | Path |
|---|---|
| The packaged argument, incl. the 5-line answer | `docs/review2/ablation_and_sweep.md` |
| Ablation variants | `placement/ablations.py` |
| Ablation runs (4,320) + decomposition | `results/ablation/` |
| Gain-decomposition figure | `figures/F6_gain_decomposition.png`, `figures/F6_gain_decomposition.csv` |
| Ablation table (T-ABL + per-variant penalties) | `docs/report/tables/ablation.md` |
| Traffic sweep runs (1,500) | `results/sweep/`, `results/sweep_sensitivity/` |
| Sweep figures | `figures/F2_egress_penalty.png`, `figures/F3_providers_used.png` |
| Sweep + crossover tables | `docs/report/tables/sweep.md`, `docs/report/tables/crossover.md` |
| Price/location sensitivity runs (1,800) | `results/sensitivity/` |
| Sensitivity figure and table | `figures/F7_sensitivity.png`, `docs/report/tables/sensitivity.md` |
| Scaling and gap (1,250 jobs) | `results/scaling/`, `figures/F4_runtime_vs_n.png`, `figures/F5_gap_boxplots.png`, `docs/report/tables/scaling.md` |
| SA convergence over all seeds | `figures/F0_sa_convergence.png`, `results/heuristics/sa_traces.csv` |

## Line 4 — Threats to validity (1 mark)

| Evidence | Path |
|---|---|
| Four-category analysis with direction, mitigation, residual risk | `docs/review2/threats_to_validity.md` |
| Automated completeness + coverage check (A3) | `analysis/check_threats.py` |
| Source of the waivers and limitations it must cover | `state/AUDIT_LOG.md`, `docs/design_decisions.md` |
| Replication gate (n ≥ 3 everywhere) | `experiments/check_replication.py` |
| Statistical machinery behind every CI | `analysis/stats.py`, `experiments/uncertainty.py` |

## Supporting: statistical soundness (counts toward Review 3, shown here)

| Evidence | Path |
|---|---|
| Every figure's data carries n, mean and a 95 % CI (lint gate) | `analysis/figures.py` — run `python -m analysis.figures --lint`; data files sit next to each PNG, e.g. `figures/F7_sensitivity.csv` |
| Figure/table/verdict drift tests (33) | `tests/test_analysis.py` |
| Every number in the prose traced to a table | `analysis/check_numbers.py` |

## Screenshots (added by hand — H-15)

| Screenshot | Path | Status |
|---|---|---|
| Green GitHub Actions run | `evidence/screenshots/M19_ci_green.png` | ❌ pending H-15 |

Review-1 screenshots (8/8 present) remain valid and are indexed in
`docs/review1/evidence_index.md`.

## Slides

`docs/review2/slides_outline.md` — 9 slides, each naming the file to show.
