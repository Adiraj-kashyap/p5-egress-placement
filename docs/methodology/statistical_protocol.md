# 05 — Statistical protocol (plan v2). Read by section.

## §1 Why this file exists
Review 3 requires ≥ 3 runs per configuration with mean and variance, and error bars; a
single-run bar chart scores zero. But ILP, B1, B2 and greedy are **deterministic**: running
them three times on identical input gives three identical numbers and zero variance. Reporting
that as "3 runs" is technically true and statistically meaningless, and a sharp examiner will
say so. Variance must come from **real sources of uncertainty** in the problem.

## §2 Replication units — what counts as a "run"

| Source | Applies to | How | Default n |
|---|---|---|---|
| **Traffic uncertainty draws** | T1, T2, T3, every method | Draw edge volumes from their uncertainty model (§3); solve every method on the same draw | R = 30 |
| **Instance replicates** | synthetic scaling | Independent synthetic instances per (n, L) cell (already in M14) | 5 (≥ 3 required) |
| **Seeds** | SA | Independent seeds per instance/draw | 10 (M14), 5 (M16 draws) |
| **Timing repeats** | runtime of every method | Re-run the identical job and time it; runtime genuinely varies | 3 |

A configuration = (workload, traffic scale, location set, method[, variant]). Each needs n ≥ 3
values of the reported metric. `experiments/check_replication.py` enforces this.

Because every method is solved on the **same** draws, comparisons are **paired**: compute the
per-draw difference or ratio, then summarise that. This removes shared noise and is much more
powerful than comparing two independent means.

## §3 Uncertainty models (register these; state them in the paper)

- **Measured volumes (T1):** per-edge bytes/request resampled with replacement from the M07
  measurement runs (use per-request samples if recorded, else the 3 run means), times a
  request-rate factor `exp(N(0, 0.25²))` around the stated production rate. One rate factor per
  draw, shared by all edges (load moves together).
- **Stated volumes (T2, T3):** `volume × exp(N(0, 0.3²))_global × exp(N(0, 0.3²))_edge`
  — a shared load factor and an independent per-edge factor, both median 1.
- **Prices:** held fixed at the snapshot (single snapshot is a declared threat). Price
  sensitivity is a separate sweep (M15 ×0.75/×1.25; M17), not a source of error bars.
- Draw seeds: `draw_seed = 10_000 + draw_id`. Fixed list; recorded in config.json.

## §4 Decision rules for verdicts — FROZEN once MIG-002 is applied

Thresholds come from `00_PROJECT_BRIEF.md §4`, unchanged. These rules say how a threshold is
judged against noisy data.

**§4.1 H1.** Per topology, compute the per-draw reduction `ρ_d = (C_B1 − C_ILP) / C_B1`.
Report mean, sd, 95% bootstrap CI of mean(ρ).
- SUPPORTED for that topology if CI lower bound ≥ 0.20.
- REFUTED if CI upper bound < 0.20.
- Otherwise INCONCLUSIVE.
Overall H1: SUPPORTED only if all three topologies are SUPPORTED; REFUTED if any is REFUTED;
else INCONCLUSIVE. Also report a one-sided Wilcoxon signed-rank test of `ρ_d − 0.20 > 0`.

**§4.2 H2.** Over instances in cells with n ≥ 15 and L ≥ 20 where CBC proved optimality:
median SA gap (median over seeds per instance, then over instances) and median speed-up
`t_ILP / t_SA` (timing-repeat means). Bootstrap CIs over instances.
- SUPPORTED if gap CI upper ≤ 0.05 and speed-up CI lower ≥ 10.
- REFUTED if gap CI lower > 0.05 or speed-up CI upper < 10.
- INCONCLUSIVE otherwise, or if fewer than 3 qualifying instances (then say so: the frontier
  was reached before the H2 condition — that itself is a finding).

**§4.3 H3.** For each topology and each draw, find the crossover scale (as M15 §3 defines it).
- SUPPORTED if a crossover exists in the base (undrawn) sweep and in ≥ 80% of draws.
- REFUTED if it exists in ≤ 20% of draws.
- INCONCLUSIVE between. Report the median crossover threshold in GB/month with its 95% CI.

## §5 Estimators and reporting

- **Mean ± sd** in tables; **95% CI** for error bars. State which in every caption.
- CI method: percentile bootstrap, B = 10,000 resamples, `rng = np.random.default_rng(12345)`.
  For n < 10, also report the t-interval and use the wider of the two.
- Runtime: report mean ± sd of timing repeats; plot on log axis with error bars;
  record machine tag.
- Proportions (e.g. crossover rate): Wilson score interval.
- Never report more precision than the CI supports: 3 significant figures for costs, 1 decimal
  for percentages.
- Caption template: *"Mean over R = 30 traffic draws; error bars are 95% bootstrap CIs.
  Snapshot 2026-MM-DD, core location set."*

## §6 What a figure may not do
- Plot a single run, anywhere, for any configuration.
- Plot bars without error bars.
- Mix runtimes from different machines.
- Show a y-axis starting above zero for cost bars (misleading); lines may use a log axis.
