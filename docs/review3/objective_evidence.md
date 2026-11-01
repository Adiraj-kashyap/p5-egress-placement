# Objective-evidence matrix — Review 3 (M23 step 1)

Every cell is a path committed in this repository. Numbers are copied from generated files
(`docs/report/verdicts.md`, `docs/report/tables/*`, `cost_model/2026-09-21/validation.md`);
none is typed from memory. "Met" refers to the objective (build and measure); the hypothesis
verdicts are reported separately and two of the three are refuted.

| Objective | Code | Results | Figure / table | Paper section | Status |
|---|---|---|---|---|---|
| **O1** Unified cost model spanning compute, storage and inter-provider transfer for AWS, GCP, Azure from published pricing | `pricing/`, `cost_model/README.md` | `cost_model/2026-09-21/` — 96 compute rows, 576 directed egress cells, 24 internet, 24 storage; 10/10 validation checks; 0/168 same-provider fallbacks | `docs/report/tables/cost_model.md` | §III System and cost model | Met |
| **O2** Placement formulated as an optimisation problem with explicit egress between communicating components | `placement/ilp.py`, `placement/cost.py` | `results/exact/` — T1–T3 proven optimal in < 0.2 s; objective equal to `evaluate` on 20 brute-forced instances | `docs/report/formulation.md`, `docs/report/tables/exact.md` | §IV Problem formulation | Met |
| **O3** Solve exactly for small instances, heuristically for large ones, quantify the gap | `placement/ilp.py`, `placement/greedy.py`, `placement/annealing.py` | `results/scaling/` (1,250 runs), `results/timing/` (162 runs) — median SA gap 0.10 %, CI [0.07, 0.13] % | `figures/F4_runtime_vs_n.png`, `figures/F5_gap_boxplots.png`, `docs/report/tables/scaling.md` | §V Heuristics, §VII Evaluation (H2) | Met — H2 REFUTED (speed clause 0.63×) |
| **O4** Measure the total cost penalty of placements that ignore egress | `placement/baselines.py`, `placement/ablations.py`, `experiments/` | `results/replicates/` (8,100), `results/ablation/` (4,320), `results/sensitivity/` (1,800), `results/sweep/` | `figures/R2-1_cost_vs_scale.png`, `F1`, `F2`, `F3`, `F6`, `F7`; `docs/report/tables/h1_replicated.md` | §VII Evaluation (H1, ablation, H3, sensitivity) | Met — H1 REFUTED overall (SUPPORTED on T2), H3 REFUTED |

## Workloads covered

| Workload | Components | Inter-component traffic | Source of volumes |
|---|---|---|---|
| T1 three-tier web | 4 | 1,265.50 GB/month | **measured** on the kind testbed (`testbed/measurements/summary.csv`, max CV 0.87 %) |
| T2 data pipeline | 7 | 3,621.0 GB/month | stated (`topologies/`) |
| T3 microservices (Online Boutique shape) | 11, 30 edges | 2,768.94 GB/month | stated (`topologies/`) |
| Synthetic grid | 4–40 | generated | `experiments/` generator, `results/scaling/` |
