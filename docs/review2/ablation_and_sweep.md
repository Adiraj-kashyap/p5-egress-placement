# Ablation and parameter sweep — which component causes the gain

Review-2 rubric line: *"Ablation or parameter sweep — which component causes the gain, or how the
result moves with load, scale or cost" (2 marks)*.

All values are means over draws with 95 % bootstrap CIs. Sources: `results/ablation/`,
`results/sensitivity/`, `results/replicates/`, `results/sweep/`; tables
`docs/report/tables/{ablation,sensitivity,sweep,crossover}.md`.

## The five-line answer

1. The gain G = C(B1) − C(ILP) is decomposed along b1 → b1_storage → ilp_no_edge_egress → ilp_full,
   so each step adds exactly one ingredient and the three steps sum to G on every draw (D-071).
2. **Step 3, coupling the placement decisions through per-edge egress, is the largest step at
   6 of 6 (topology, scale) points** — it is the ingredient that causes the gain.
3. Step 1 (pricing storage alongside compute) is **exactly 0.00 everywhere**: B1's tie-break
   already lands on the cheapest storage, so storage explains none of the gain.
4. Step 2 (adding user-facing internet egress) is **negative on T1 and T3** (−96.44 and
   −91.95 USD/month at s = 1): that ingredient *alone* makes the true cost worse, and step 3 more
   than recovers it. Only on T2 is step 2 positive (+107.58).
5. Therefore the method's value is not "a better price table" but "treating the edges as coupled":
   an optimiser given every cost term except edge egress is **worse than the egress-blind baseline**
   on two of the three topologies.

## Figure F6 — gain decomposition

**File:** `figures/F6_gain_decomposition.png`; data `figures/F6_gain_decomposition.csv` (18 rows).

> **Figure F6.** Decomposition of the ILP's gain over B1 into three ingredients (storage pricing,
> internet egress, per-edge egress coupling), for T1–T3 at s = 1 and s = 100. Each bar is the
> paired per-draw difference of two variants' *true* costs; mean over R = 30 draws, error bars are
> 95 % bootstrap CIs. Snapshot 2026-09-21, core location set.

Table T-ABL (`docs/report/tables/ablation.md`), USD/month, mean [95 % CI]:

| Topology | s | G | 1 storage | 2 internet | 3 egress coupling | largest |
|---|---|---|---|---|---|---|
| T1 | 1 | 16.50 | 0.00 [0.00, 0.00] | −96.44 [−105.28, −88.07] | **112.94 [103.12, 123.29]** | step 3 |
| T1 | 100 | 1,455.65 | 0.00 | −9,838.50 [−10,740.26, −8,983.67] | **11,294.15 [10,312.00, 12,329.24]** | step 3 |
| T2 | 1 | 306.93 | 0.00 | 107.58 [91.70, 124.37] | **199.35 [176.28, 223.89]** | step 3 |
| T2 | 100 | 30,689.58 | 0.00 | 10,754.29 [9,166.72, 12,433.03] | **19,935.29 [17,627.71, 22,389.42]** | step 3 |
| T3 | 1 | 33.92 | 0.00 | −91.95 [−108.61, −77.07] | **125.87 [108.54, 144.98]** | step 3 |
| T3 | 100 | 33.92 | 0.00 | −12,553.31 [−14,462.13, −10,823.60] | **12,587.23 [10,853.61, 14,498.46]** | step 3 |

The second ablation scale is s = 100 rather than a crossover point, because the sweep found no
crossover to sample (D-058, D-067); s = 100 is the egress-heaviest end of the frozen M15 range
(D-072).

## Ablated variants — the cost of removing one ingredient

Every variant is the same tight ILP on an instance rebuilt with one term removed, and its
assignment is then scored by the **real** `evaluate()`, so a crippled variant is charged what its
choice truly costs (D-071). Penalty vs the full ILP, s = 1, core, 30 draws
(`docs/report/tables/ablation.md`):

| Variant | What it drops | T1 % | T2 % | T3 % |
|---|---|---|---|---|
| `b1` | the baseline (egress-blind) | 3.40 [3.14, 3.68] | 29.83 [26.42, 33.32] | 1.79 [1.68, 1.91] |
| `b1_storage` | baseline + storage-aware tie-break | 3.40 [3.14, 3.68] | 29.83 [26.42, 33.32] | 1.79 [1.68, 1.91] |
| `ilp_no_edge_egress` | **per-edge egress** | **23.30 [21.52, 25.15]** | 19.37 [17.13, 21.76] | **6.86 [6.10, 7.72]** |
| `ilp_no_internet` | internet egress | 0.00 | 0.00 | 1.79 [1.68, 1.91] |
| `ilp_undirected` | direction of the egress price | 0.00 | 0.00 | 0.00 |
| `ilp_single_provider` | multi-provider freedom | 0.00 | 0.00 | 0.00 |
| `sa_random_init` | greedy warm start | 0.00 | 0.08 [0.03, 0.14] | 0.20 [0.05, 0.41] |
| `sa_no_swap` | the swap move | 0.00 | 0.00 | 0.11 [0.00, 0.26] |

Three things follow. **(a)** Dropping per-edge egress is the single most damaging ablation on
T1 and T3 — worse than using the baseline outright (23.30 % vs 3.40 % on T1). **(b)**
`ilp_undirected` and `ilp_single_provider` cost 0.00 % here: the optimum is single-provider in
this snapshot, so the directionality of the price matrix and the freedom to split providers are
not *exercised* on T1–T3, even though the model supports them. That is a limitation of the
instances, not evidence that direction does not matter — see `threats_to_validity.md`. **(c)** SA's
design choices are worth ≤ 0.2 %, confirming the heuristic is not doing the work; the formulation is.

## Traffic sweep — how the result moves with load

**Files:** `figures/F2_egress_penalty.png` (data 135 rows), `figures/F3_providers_used.png` (87 rows);
tables `docs/report/tables/{sweep,crossover}.md`; runs `results/sweep/` (1,500 jobs) and
`results/replicates/` (8,100 jobs).

> **Figure F2.** Cost penalty of each method relative to the ILP optimum (%) against
> inter-component traffic scale s ∈ [0.01, 100], per topology. Mean over R = 30 traffic draws,
> 95 % bootstrap CI bands. Snapshot 2026-09-21, core location set.
>
> **Figure F3.** Number of distinct providers used by the optimal placement against s, with the
> per-draw crossover rate. Mean over R = 30 draws; Wilson intervals for the rate.

At s = 1 the B1 penalty is 3.40 % / 29.83 % / 1.79 % (T1/T2/T3). On T1 and T2 it rises
monotonically with s and becomes the dominant cost term at the top of the range
(T1 0.43 % → 300.36 %, T2 0.30 % → 2,982.56 % from s = 0.01 to s = 100); on T3 it is **flat at
1.79 % at every scale**, because B1 already colocates T3's components, so scaling the
inter-component edges changes nothing and the whole gap stays internet egress. B1-alt and B2-best
are 0 % at every scale. **The ILP uses exactly one provider at all 810
(topology, scale, draw) points, with sd 0.0**, so no crossover exists anywhere in the swept range:
**H3 is REFUTED** on all three topologies, 0/30 draws, Wilson CI [0.00, 11.35] %.

This refutation is **structural, not a grid artefact** (D-060): every component of T1–T3
minimises its own compute + storage + internet cost at `azure:eastus`, and inter-component egress
is never negative and is zero when everything shares a location. So colocation is optimal at
every s ≥ 0 in this snapshot, and no finer grid or further draw could produce a crossover. A
topology whose components have different own-cost minimisers — for example one pinned to another
provider for compliance — could still show one; the machinery to test that exists
(`pinned_to`, D-048) and is the obvious next experiment.

## Price sensitivity — how the result moves with cost

**File:** `figures/F7_sensitivity.png`; data `figures/F7_sensitivity.csv` (60 rows); table
`docs/report/tables/sensitivity.md`; runs `results/sensitivity/` (1,800 jobs).

> **Figure F7.** ILP saving over B1 (%) as every egress price in the snapshot is scaled by
> ×0.5 … ×1.5, and as the number of candidate locations per provider varies (1, 2, 4, 8).
> Mean over 10 draws per point, 95 % bootstrap CIs. ×1 and k = 4 reproduce the real snapshot and
> the core set exactly (D-073).

| Egress × | T1 saving % | T2 saving % | T3 saving % |
|---|---|---|---|
| ×0.50 | 1.99 [1.74, 2.25] | 14.20 [12.49, 16.00] | 1.78 [1.56, 1.99] |
| ×0.75 | 2.75 [2.41, 3.11] | 19.83 [17.62, 22.19] | 1.78 [1.56, 1.99] |
| **×1.00** | **3.50 [3.07, 3.95]** | **24.75 [22.16, 27.50]** | **1.78 [1.56, 1.99]** |
| ×1.25 | 4.24 [3.72, 4.78] | 29.09 [26.21, 32.12] | 1.78 [1.56, 1.99] |
| ×1.50 | 4.96 [4.37, 5.59] | 32.94 [29.86, 36.18] | 1.78 [1.56, 1.99] |

**The T2 result is price-fragile.** Cloud egress prices have historically fallen, and a 25 % cut
takes T2's saving to 19.83 %, below the frozen threshold — the one supported hypothesis would flip.
T3 is completely flat because its gain is internet egress, which this axis does not touch.
Widening the candidate set from 1 to 8 locations per provider changes the saving by at most
0.10 pp: **the result is driven by the price structure, not by the size of the search space.**
