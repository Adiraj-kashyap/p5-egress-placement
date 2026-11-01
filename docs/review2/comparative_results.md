# Comparative results — proposed method vs baselines, on the same axes

Review-2 rubric line: *"Comparative results vs baseline — at least one graph with the baseline and
the proposed method on the same axes" (3 marks)*.

Everything on this page is a **mean over R = 30 traffic draws** with a 95 % CI. No value comes from
a single run (non-negotiable 8). Sources are the generated tables and figure CSVs; regenerate with
`python -m analysis.figures` then `python -m analysis.tables --latex`.

## What is being compared

| Name | What it does | Code |
|---|---|---|
| **ILP (proposed)** | exact minimisation of compute + storage + per-edge egress + internet egress | `placement/ilp.py` |
| **SA** | simulated annealing from the greedy start, 5 seeds per draw (median taken, D-068) | `placement/annealing.py` |
| **greedy / greedy+1-opt** | egress-aware greedy, then 1-opt local search | `placement/greedy.py` |
| **B1 (baseline)** | egress-blind: cheapest USD/vCPU-hour per component, ties broken on storage (D-039) | `placement/baselines.py` |
| **B1-alt (baseline)** | same rule, opposite storage tie-break — reported because B1 is tie-break sensitive | `placement/baselines.py` |
| **B2-best (baseline)** | best single provider, all components on one provider | `placement/baselines.py` |

## Figure R2-1 — the headline graph

**File:** `figures/R2-1_cost_vs_scale.png` (also `.pdf`); data `figures/R2-1_cost_vs_scale.csv`
(135 rows, one per topology × scale × method, each with `n`, `mean`, `ci_lo`, `ci_hi`).

> **Figure R2-1.** Total monthly cost (USD, log axis) against inter-component traffic scale s,
> for ILP, SA, B1 and B2-best on T1, T2 and T3. Mean over R = 30 traffic draws; error bars /
> bands are 95 % bootstrap CIs (B = 10,000). Snapshot 2026-09-21, core location set (12
> locations). s = 1 is the measured/stated volume of the topology.

**How to read it:** the ILP and B2-best lines lie on top of each other at every scale, SA sits on
them to within a fraction of a percent, and B1 is a separate line above them whose distance grows
with s. The gap between the B1 line and the ILP line **is** the cost of ignoring egress.

## Figure F1 — where the money goes

**File:** `figures/F1_cost_breakdown.png`; data `figures/F1_cost_breakdown.csv` (90 rows).

> **Figure F1.** Monthly cost split into compute, storage, inter-component egress and internet
> egress, for each method on T1–T3 at s = 1. Mean over R = 30 traffic draws; error bars are 95 %
> bootstrap CIs. Snapshot 2026-09-21, core location set. Bars start at zero (05 §6).

Component means, USD/month (from `figures/F1_cost_breakdown.csv`):

| Topology | Method | compute | storage | inter-component egress | internet egress | total |
|---|---|---|---|---|---|---|
| T1 | B1 | 420.48 | 4.16 | 14.54 | 58.82 | 498.00 |
| T1 | ILP | 420.48 | 4.16 | **0.00** | 56.86 | 481.50 |
| T2 | B1 | 981.12 | 46.80 | 306.90 | 0.99 | 1,335.81 |
| T2 | ILP | 981.12 | 46.80 | **0.00** | 0.96 | 1,028.88 |
| T3 | B1 | 840.96 | 0.00 | 0.00 | 1,017.60 | 1,858.56 |
| T3 | ILP | 840.96 | 0.00 | 0.00 | 983.68 | 1,824.64 |

Compute is identical in every row: B1 and the ILP buy the same machines, because the cheapest
USD/vCPU-hour is available in more than one location. **The entire difference is data movement.**

## The replicated H1 table

Source: `docs/report/tables/h1_replicated.md` (table T-H1), from `results/replicates/`.
ρ = (C(B1) − C(ILP)) / C(B1), computed **per draw** so the comparison is paired; CIs are 95 %
percentile bootstrap; the Wilcoxon column is a one-sided signed-rank test of ρ > 20 %.

| Topology | Baseline | Draws | mean C(B1) | mean C(ILP) | reduction % (mean ± sd) | 95 % CI | Wilcoxon p |
|---|---|---|---|---|---|---|---|
| T1 | B1 | 30 | 498.00 | 481.50 | 3.29 ± 0.71 | [3.04, 3.54] | 1.000 |
| T1 | B1-alt | 30 | 481.50 | 481.50 | 0.00 ± 0.00 | [0.00, 0.00] | 1.000 |
| T2 | B1 | 30 | 1,335.81 | 1,028.88 | **22.55 ± 5.81** | **[20.52, 24.59]** | **0.015** |
| T2 | B1-alt | 30 | 1,028.88 | 1,028.88 | 0.00 ± 0.00 | [0.00, 0.00] | 1.000 |
| T3 | B1 | 30 | 1,858.56 | 1,824.64 | 1.76 ± 0.31 | [1.65, 1.87] | 1.000 |
| T3 | B1-alt | 30 | 1,824.64 | 1,824.64 | 0.00 ± 0.00 | [0.00, 0.00] | 1.000 |

**Verdict on H1 (frozen rule 05 §4.1, applied to the interval, not the point estimate):
REFUTED overall, SUPPORTED on T2.** The full reasoning is in `docs/report/verdicts.md`.
The threshold (20 %) was frozen before any of these runs and was not touched (D-081).

## Interpretation, one paragraph per topology

**T1 — three-tier web application (measured traffic).** Reduction **3.29 %, CI [3.04, 3.54] %**:
real but far below the 20 % hypothesis, so H1 is refuted here. The reason is visible in F1: T1's
bill is 84 % compute, and its inter-component traffic — 1,265.5 GB/month measured on the kind
testbed (M07) — is worth only 14.54 USD/month when B1 splits the tiers across providers. Egress
matters relative to the *savings available*, not relative to the bill: the ILP removes 100 % of
the inter-component egress, and that is still only 3 % of the total. Note that this is the one
topology whose volumes are measured rather than stated, and its uncertainty model resamples the
three real M07 runs (05 §3).

**T2 — data pipeline.** Reduction **22.55 %, CI [20.52, 24.59] %**, Wilcoxon p = 0.015: the CI
lower bound clears the frozen 20 % threshold, so **H1 is supported on T2** — the single strongest
result in the project. T2 moves 3,621 GB/month between components with almost no user-facing
traffic (0.99 USD/month internet), so the egress-blind split is charged 306.90 USD/month for data
movement that the ILP reduces to exactly zero. **The margin is narrow — half a percentage point on
the CI lower bound** — and F7 shows it would not survive a 25 % cut in egress prices (the saving
falls to 19.83 % at ×0.75). This must be stated whenever the T2 result is quoted.

**T3 — microservices (Online Boutique).** Reduction **1.76 %, CI [1.65, 1.87] %**, the smallest of
the three. F1 explains why: B1 already places all of T3's components in one location, so its
inter-component egress is 0.00 in both rows. The entire 33.92 USD/month difference is **internet**
egress — the ILP picks a location with a cheaper end-user rate for the ~10,900 GB/month of
user-facing traffic, while B1 leaves some components in regions whose internet rate is higher. So on T3 the method wins on a term the hypothesis was
not about, and the egress-coupling story does not apply.

**Across the three:** the size of the saving tracks one ratio — inter-component GB/month divided by
total bill — and nothing else. T2 is the only topology where that ratio is large, and it is the
only topology where the hypothesis holds.

## Robustness: the baseline is not a straw man

B1 is tie-break sensitive (D-039): AWS `us-east-1` and Azure `eastus` cost exactly the same per
vCPU-hour for all four shapes, so which one B1 picks depends on a storage tie-break. Under the
opposite tie-break (**B1-alt**) the baseline already colocates everything and the ILP's saving is
**exactly 0.00 % on all three topologies**. Both variants are reported everywhere, and the verdict
is taken against the variant that does *not* flatter the method. This is the most important caveat
on the headline number and it is repeated in `threats_to_validity.md` (internal validity).

## Method accuracy (O3, supporting)

From `docs/report/tables/exact.md` and T-H2 in `docs/report/tables/h1_replicated.md`:
SA reaches the proven optimum on T1 and T2 (10/10 seeds) and on 8/10 seeds on T3; greedy+1-opt is
0.50 % / 0.00 % / 1.83 % above it in under a millisecond. Over the 25 qualifying synthetic
instances SA's median gap is **0.10 %, CI [0.07, 0.13] %** — inside H2's 5 % clause — but its
speed-up over CBC is **0.63×, CI [0.21, 1.04]×**, far below the 10× clause, so **H2 is REFUTED**
on the conjunction. CBC simply proves optimality quickly at these sizes.
