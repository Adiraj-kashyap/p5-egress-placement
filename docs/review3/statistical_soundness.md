# Statistical soundness — Review 3 (M23 step 2)

## Replication units

A replicate is an independent draw of the quantity that varies. **Deterministic re-runs of the
same input are not counted as replicates**: the solvers are deterministic given their input and
seed, so repeating one gives no information about variance.

| Results dir | Rows | Configurations | Min n | Median n | Unit of replication |
|---|---|---|---|---|---|
| `results/replicates/` | 8,100 | 162 | 30 | 30 | traffic draw from the uncertainty model |
| `results/ablation/` | 4,320 | 72 | 30 | 30 | traffic draw |
| `results/sensitivity/` | 1,800 | 180 | 10 | 10 | traffic draw |
| `results/scaling/` | 1,250 | 250 | 5 | 5 | synthetic instance |
| `results/timing/` | 162 | 54 | 3 | 3 | timing repeat |

`python -m experiments.check_replication`, run 2026-11-01:

```
ablation     OK   rows   4320  configurations    72  min n  30  median n  30.0  unit: traffic draw
replicates   OK   rows   8100  configurations   162  min n  30  median n  30.0  unit: traffic draw
scaling      OK   rows   1250  configurations   250  min n   5  median n   5.0  unit: synthetic instance
sensitivity  OK   rows   1800  configurations   180  min n  10  median n  10.0  unit: traffic draw
timing       OK   rows    162  configurations    54  min n   3  median n   3.0  unit: timing repeat
              not enforced (plan-v1, single-run by construction): baselines, exact, heuristics, sa_sweep, smoke, sweep, sweep_sensitivity
PASS
```

The non-enforced directories are plan-v1 single-run outputs; no reported figure is drawn from them.

## Figures: n and error-bar type

Read from each figure's companion CSV (`figures/*.csv`, columns `mean`, `sd`, `ci_lo`, `ci_hi`, `n`).

| Figure | Shows | n per point | Spread |
|---|---|---|---|
| R2-1 | total cost vs traffic scale, all methods | 30 draws | 95 % bootstrap CI band |
| F0 | SA convergence | 5–10 seeds | 95 % CI band |
| F1 | cost breakdown, B1 vs ILP | 30 draws | 95 % CI bars |
| F2 | egress penalty of B1 | 30 draws | 95 % CI band |
| F3 | providers used by the optimum | 30 draws | 95 % CI |
| F4 | runtime vs problem size | 3 instances × 3 repeats | 95 % CI bars |
| F5 | SA optimality gap | 5 instances | box plot + 95 % CI |
| F6 | gain decomposition (ablation) | 30 draws | 95 % CI bars |
| F7 | egress-price sensitivity | 10 draws | 95 % CI bars |

Methods (`analysis/stats.py`): 95 % percentile bootstrap, B = 10,000; methods share each draw, so
comparisons are paired and H1 uses a one-sided Wilcoxon signed-rank test; proportions (crossover
counts) use the Wilson interval. `analysis.figures --lint` refuses to draw from n < 3.

## Decision rules and verdicts

Rules are `docs/methodology/statistical_protocol.md §4`, applied to 95 % intervals against thresholds frozen
before any run (`analysis/thresholds.py`). Full text: `docs/report/verdicts.md`.

| Hypothesis | Rule (summary) | Result | Verdict |
|---|---|---|---|
| H1 | CI of mean reduction vs B1 ≥ 20 % on every topology | T1 3.29 % [3.04, 3.54]; T2 22.55 % [20.52, 24.59], p = 0.015; T3 1.76 % [1.65, 1.87] | **REFUTED** (SUPPORTED on T2 only) |
| H2 | gap CI upper ≤ 5 % **and** speed-up CI lower ≥ 10× | gap 0.10 % [0.07, 0.13]; speed-up 0.63× [0.21, 1.04] | **REFUTED** |
| H3 | crossover in base sweep and ≥ 80 % of draws | 0/30 draws on each topology, Wilson CI [0.00, 11.35] % | **REFUTED** |

## Workloads covered

T1 (measured on the kind testbed), T2, T3, and the synthetic grid (4–40 components, 12 or 24
locations). See `objective_evidence.md`.
