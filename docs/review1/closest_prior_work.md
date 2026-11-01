# Closest prior work and what P5 adds

Two verified papers sit closest to P5. One is closest in **method**, the other in **formulation**.
Both were read against their full text (`lit_verification.csv`, rows 11 and 3).

## Closest in method: R. Sinha, NCI MSc thesis (2023) [11]

*Optimization of Multi-Cloud Workload Placement for Performance and Cost Efficiency*, National
College of Ireland. Grey literature, not peer-reviewed.

- **What it does.** Recommends a cloud provider per application component. It uses stochastic hill
  climbing and simulated annealing over pricing fetched from cloud APIs, with machine-learning
  prediction of CPU and memory needs and Docker-based workload simulation (abstract).
- **Where it stops.** The provider set is AWS and Azure, with no GCP. No integer-programming
  formulation appears in the text, so there is no exact optimum and no optimality gap for its
  heuristics. A search of the full text finds no inter-component egress or data-transfer term.

## Closest in formulation: SkyPilot, NSDI 2023 [3]

- **What it does.** An intercloud broker whose optimizer solves an ILP over a DAG of tasks. Each
  task is assigned a cloud, zone and instance, and inter-task egress is included in the cost.
  In its ML-pipeline example the optimizer pays $13 of egress to reach a cheaper TPU.
- **Where it stops.** Its tasks are coarse-grained batch computations executed once. It is not
  presented as a model of always-on services exchanging a steady monthly volume per edge. It
  prices from an internal catalog of long-term prices, not a dated snapshot. It does not study
  how far a heuristic is from the exact optimum.

An earlier draft of this survey claimed that SkyPilot leaves egress out of its objective. The
full text shows otherwise, so that claim was removed and P5's novelty is stated more narrowly
below.

## Three differentiators of P5

1. **Egress-coupled placement of always-on multi-component applications.** The objective prices
   monthly traffic on each directed component pair with a provider-pair egress tariff, for
   application topologies such as three-tier and pipeline. Component-placement work in the
   survey (rows 5-8) treats this traffic as a co-location constraint, a per-node coefficient or
   a per-link cost. SkyPilot prices egress for one-shot task DAGs.
2. **A dated, reproducible three-provider price snapshot.** Prices come from the public AWS
   Price List, GCP Cloud Billing Catalog and Azure Retail Prices APIs, stored with a date. The
   surveyed work uses hand-transcribed rates (row 9), AWS only (row 15), two providers (row 11)
   or an internal catalog (row 3).
3. **Exact solution, measured heuristic gap, and egress-blind penalty.** The same formulation is
   solved exactly with CBC and compared with a greedy heuristic and simulated annealing, giving
   an optimality gap (G4). The cost of ignoring egress is measured against that optimum, and
   the traffic level at which single-provider placement becomes optimal is located (H3).

Differentiators 1 and 2 are claims about the surveyed literature, not about all literature.
They hold for the 14 papers in `gap_table.md` and may not hold for work outside that search.
