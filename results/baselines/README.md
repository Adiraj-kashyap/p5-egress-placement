# Baselines B1, B2 on T1–T3 (M08)

Source: `python -m experiments.run_baselines` on cost model 2026-09-21, `core` locations (12); table in `run.log` and `evidence/logs/M08_baselines.txt`, rows in `runs.csv`.

1. B1 costs more than B2-best on T1 (497.58 vs 481.18 USD/month, +3.4%) and T2 (1,303.65 vs 1,028.79, +26.7%); on T3 it equals B2-aws (1,822.60 vs B2-best 1,789.88).
2. B1's extra cost is inter-component egress: 14.44 (T1) and 274.83 (T2) USD/month, 2.9% and 21.1% of its total. B2 has zero egress by construction.
3. Why B1 splits providers: aws:us-east-1 and azure:eastus tie exactly at 0.048 USD/vCPU-hour for every shape. Stateful components (db, queue, warehouse) go to azure:eastus for its cheaper storage; the rest go to aws:us-east-1 (smallest location id). See D-039.
4. **B1 depends on the tie-break.** Sending remaining ties to the last location id puts everything on azure:eastus, so B1 = B2-azure on all three (481.18 / 1,028.79 / 1,789.88). The run log prints this total for each topology.
5. B2-best is azure:eastus for all three topologies. It has the same compute bill as aws:us-east-1, with cheaper storage and a cheaper internet rate at the stated volumes.
6. GCP's cheapest core region (europe-west1) is 11.3% dearer on compute for these shape mixes, so B2-gcp is last everywhere.
7. Internet egress is a large term for T3 (54% of B1's total), but it cannot be avoided: every placement pays it at its region's rate.
8. No claim about the optimum is made here. The egress-aware optimum and the penalty come in M10 and M15.
