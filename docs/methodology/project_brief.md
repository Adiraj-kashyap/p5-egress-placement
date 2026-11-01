# 00 — Project Brief

## §1 Problem

Public cloud providers bill compute per hour, storage per GB-month, and **outbound** network
transfer per GB. The per-GB transfer rate depends on the sending provider and region and on
whether the receiver is in the same region, another region of the same provider, or outside
the provider. When an application is split into communicating components, the transfer cost
is defined over **pairs** of placements, so choosing each component's location independently
(the common practice) ignores a term that can exceed the compute saving that motivated the
choice. Placement is a coupled optimisation problem.

## §2 Objectives

| ID | Objective | Modules |
|---|---|---|
| O1 | Unified cost model spanning compute, storage and inter-provider transfer for AWS, GCP and Azure from published pricing APIs | M02–M05 |
| O2 | Formulate multi-component placement as an optimisation problem with explicit egress between communicating components | M10 |
| O3 | Solve exactly for small instances, heuristically for large ones, and quantify the heuristic optimality gap | M10–M14 |
| O4 | Measure the total cost penalty of placement approaches that ignore egress | M15–M16 |

## §3 Scope

- Providers: AWS, GCP, Azure. Public price lists only (AWS Price List bulk API, GCP Cloud
  Billing Catalog API, Azure Retail Prices API).
- Pricing basis: Linux, on-demand, shared tenancy. No spot, reserved or Windows.
- Locations: `core` set = 4 regions per provider (12). `ext` set = 8 per provider (24), used
  only for scaling experiments. Region lists live in `pricing/common.py`.
- Applications: T1 three-tier web (measured on the testbed), T2 data pipeline,
  T3 microservice application (Online Boutique shape), plus synthetic graphs for scaling.
- Decision variable: **location** of each component. Each component's instance shape is fixed
  in advance as the smallest shape meeting its vCPU/RAM requirement (D-004).
- Solver: PuLP + CBC. Heuristics: egress-aware greedy, simulated annealing.

## §4 Hypotheses — FROZEN. Do not change after results exist.

**H1 (O4).** For T1–T3 at their stated traffic volumes (edges ≥ 500 GB/month in aggregate),
the egress-aware ILP placement reduces total monthly cost by **≥ 20%** relative to baseline B1.

**H2 (O3).** Simulated annealing stays within **5%** of the CBC optimum (median over seeds)
while reducing wall-clock time by **≥ 10×**, at ≥ 15 components and ≥ 20 candidate locations,
on instances where CBC proves optimality.

**H3 (O4, the headline).** There exists a traffic scale threshold T such that above T the
cost-optimal placement uses a single provider while B1 remains multi-provider; below T the
ordering inverts. Falsified if no crossover appears anywhere in the swept range
(scale factors 10⁻² to 10²).

Each hypothesis is reported as SUPPORTED / REFUTED / INCONCLUSIVE with the numbers.

## §5 Baselines (named in the assignment)

- **B1 — Cheapest-per-vCPU, independent.** For each component independently, choose the
  location minimising `usd_per_hour / vcpu` for its fixed shape. Egress is ignored when
  choosing, but **charged** when evaluating.
- **B2 — Single-provider.** For each provider P, place every component in P's single
  cheapest region for the application's total compute+storage bill. Report B2-aws,
  B2-azure, B2-gcp and B2-best = min of the three.

Both are evaluated with the same cost evaluator as every other method (§6, D-006).

## §6 Cost model and metrics

Monthly cost of assignment `a` (component → location):

```
C(a) = Σ_c  compute[shape(c), a(c)] · 730
     + Σ_c  storage_gb(c) · storage[a(c)]
     + Σ_(u→v)  gb(u→v) · egress[a(u), a(v)]          # directed edges, sender pays
     + Σ_c  gb(c→internet) · internet[a(c)]            # traffic to end users
```

| Metric | Definition |
|---|---|
| Total monthly cost | C(a), USD |
| Egress share | egress terms / C(a) |
| Egress penalty of method M | (C(M) − C(ILP)) / C(ILP) |
| Optimality gap of heuristic H | (C(H) − C(ILP)) / C(ILP), only where CBC status = Optimal |
| Solver runtime | wall-clock seconds, same machine, recorded with machine spec |
| Providers used | number of distinct providers in a(·) |

## §7 Review mapping

| Review 1 component | Marks | Produced by |
|---|---|---|
| Literature survey (12–15 papers ≥2021, gap table) | 3 | M01 |
| Problem statement + falsifiable hypothesis | 2 | M09 (from §1, §4) |
| Testbed / environment evidence (screenshots, logs; slides alone = 0) | 3 | M00, M02–M05, M07 |
| Baseline reproduced with numbers | 2 | M08 |

Later reviews: formulation and exact solver (M10), heuristics and gap (M11–M14),
penalty and crossover (M15–M16), report (M17–M18).

## §8 Prior work already done (in `seed/`)

- `seed/p5/` — pricing pullers for all three providers, cost-model builder, `verify_env.py`
  with an egress-coupled smoke test, fixtures generator. Tested offline against fixtures only;
  **never run against live APIs**. Egress edges there are undirected; M08 upgrades to directed.
- `seed/P5_literature_survey.md` — 16 candidate papers with gap table, gap statement,
  hypotheses. Rows 12–15 and all Limitation cells still need verification (M01).
