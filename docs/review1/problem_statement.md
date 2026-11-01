# P5 — Problem statement

**Egress-aware cost-optimal placement of workloads across multiple public cloud providers**

## Problem (in our words)

AWS, Azure and GCP each charge for three things: compute by the hour, storage by the
GB-month, and data that *leaves* a region by the GB. The last charge depends on where the
data goes. Traffic inside one region is free. Traffic to another region of the same provider
costs a little. Traffic to another provider or to the internet costs more, and the sender pays.

A real application is several components that talk to each other all month: a web tier, an
API, a cache, a database. Teams usually shop for each component on its own and pick the
cheapest compute available. That ignores the transfer bill, which depends on *pairs* of
choices: where the sender runs and where the receiver runs. A saving on one component's
hourly rate can be cancelled, or reversed, by the traffic it now sends across a provider
boundary. Choosing where to run components is therefore one joint optimisation problem, not
many independent ones.

We build a dated, three-provider cost model from the providers' public price lists, measure
real traffic volumes on a local testbed, and solve the joint placement problem exactly and
heuristically. Then we measure how much money egress-blind placement wastes.

## Objectives

| ID | Objective | Where |
|---|---|---|
| O1 | A unified cost model covering compute, storage and inter-provider transfer for AWS, GCP and Azure, built from public pricing APIs and pages | M02–M05 (done) |
| O2 | A formulation of multi-component placement as an optimisation problem with explicit egress on each communicating edge | M10 |
| O3 | Exact solutions for small instances, heuristics for large ones, and a measured heuristic optimality gap | M10–M14 |
| O4 | The total-cost penalty of placement methods that ignore egress | M15–M16 |

## Scope

- **Providers:** AWS, GCP, Azure. Public list prices only. One dated snapshot (2026-09-21).
- **Pricing basis:** Linux, on-demand, shared tenancy. No spot, reserved or Windows pricing.
- **Locations:** `core` set = 4 regions per provider (12 locations); `ext` set = 8 per
  provider (24), used only for scaling experiments.
- **Applications:** T1 three-tier web app (traffic measured on a local kind testbed), T2 data
  pipeline, T3 microservice app shaped like Online Boutique, plus synthetic graphs for scaling.
- **Decision:** the location of each component. Each component's instance shape is fixed in
  advance as the smallest shape that meets its vCPU/RAM need.
- **Methods:** exact ILP (PuLP + CBC), egress-aware greedy, simulated annealing; compared
  against baselines B1 (cheapest per vCPU, chosen per component) and B2 (single provider).
- **Out of scope:** latency, availability SLAs, negotiated discounts, free-tier allowances,
  data-residency rules, dynamic re-placement over time.

## What is and is not new

Prior work already prices data transfer in some placement settings. SkyPilot (NSDI 2023)
prices inter-task egress for batch DAG jobs. At least one workflow scheduler uses fixed
per-provider transfer rates. See `closest_prior_work.md`. Our contribution is narrower. We
study **always-on, multi-component services** with **monthly per-edge traffic**, on a
**dated three-provider snapshot built from the public price lists**, and we report a
**measured heuristic optimality gap** against a proven optimum.
