# P5 Literature Survey and Gap Table
## Egress-Aware Cost-Optimal Placement of Workloads Across Multiple Public Cloud Providers

Review 1 deliverable: literature survey (12-15 papers from 2021 onwards). Every paper below was
fetched and its title, first author, year and venue confirmed (`lit_verification.csv`, column
`verified=yes`). Limitation cells were checked against the abstract and a keyword search of the
full text. Where a Limitation is a negative claim ("no egress term"), it rests on that search,
not on a line-by-line read. Papers are labelled **[peer-reviewed]**, **[preprint]** or
**[thesis]**.

---

## 1. Search strategy

**Sources:** IEEE Xplore, ACM Digital Library, USENIX Open Access, ScienceDirect, SpringerLink,
arXiv, PVLDB.

**Query strings:**
- `("multi-cloud" OR "cross-cloud") AND ("egress" OR "data transfer cost") AND (placement OR scheduling)`
- `("microservice placement" OR "component placement") AND ("integer linear programming" OR MILP) AND cost`
- `("cloud pricing API" OR "price list API") AND ("cost model") AND (AWS OR Azure OR GCP)`
- `("optimality gap" OR "simulated annealing") AND ("cloud placement") AND cost`

**Inclusion:** published 2021 or later; addresses placement, scheduling or data movement across
two or more cloud regions or providers; reports a monetary cost metric.

**Exclusion:** energy-only or makespan-only objectives with no monetary model; single-region
intra-datacenter scheduling; position papers without evaluation; papers whose scope could not be
shown to span two or more regions or providers.

**Screening outcome:** 16 candidates screened, 14 retained. Two were dropped and logged in
`docs/design_decisions.md`:
- *Data Placement for Multi-Tenant Data Federation on the Cloud* (arXiv 2021). It exists, but
  fails the multi-region/provider inclusion criterion.
- *Versluis and Iosup, FGCS 2021* (survey). The citation is real, but its Limitation cell in the
  seed could not be supported from the text.

---

## 2. Thematic clusters

- **C1 Cross-cloud data movement (rows 1, 2, 4, 12, 13, 14).** Optimise how bytes travel or are
  cached or replicated between fixed endpoints. Egress prices are modelled well. Compute placement
  is an input.
- **C2 Component placement with ILP or heuristics (rows 5, 6, 7, 8).** Optimise where components
  go. Inter-component communication appears as a co-location constraint, a per-node coefficient
  or a per-link cost, not as a provider-pair per-GB egress tariff.
- **C3 Brokers and multi-cloud schedulers (rows 3, 9, 15).** Use real or transcribed prices across
  providers. They handle one-shot task DAGs or workflows, or a single provider's price list.
- **C4 Configuration search with pricing APIs (row 11).** Heuristic search over live pricing
  APIs with no exact baseline.

The gap targeted by this project sits between C2 and C3. C3's SkyPilot (row 3) is the closest
formulation, and C4's thesis (row 11) is the closest method.

---

## 3. Gap table

| # | Paper (year, venue, type) | Method | Dataset / testbed | Metric | Limitation w.r.t. this project | Gap |
|---|---|---|---|---|---|---|
| 1 | Jain et al., *Skyplane*, 2023, NSDI [1] [peer-reviewed] | MILP planner over price and throughput grids; picks overlay relay paths under a price or throughput constraint | Live AWS, Azure and GCP regions; measured throughput grid | $/GB moved, throughput, cost vs direct path | Optimises the **route** between two fixed endpoints. Where compute lives is an input, not a decision. | G1 |
| 2 | Wooders et al., *Cloudcast*, 2024, NSDI [2] [peer-reviewed] | Cost-aware overlay multicast tree construction | Multi-region, multi-cloud configurations | Egress cost, replication speed-up (reports 61.5% cost reduction) | One-to-many replication topology. Endpoints are fixed and no compute cost is in the objective. | G1 |
| 3 | Yang et al., *SkyPilot*, 2023, NSDI [3] [peer-reviewed] | Intercloud broker; ILP over a task DAG, each task assigned a cloud, zone and instance | AWS, Azure, GCP; ML pipelines and batch jobs | Job cost and time, including inter-task egress | **Closest formulation.** Egress on DAG edges *is* priced, but for coarse-grained batch tasks run once. Not modelled: always-on services with monthly per-edge traffic, a dated three-API price snapshot, or a heuristic-vs-exact gap. | G2 |
| 4 | Park et al., *MACARON*, 2024, SOSP [4] [peer-reviewed] | Auto-configuring cloud cache that sizes the cache and mixes storage tiers | Traces from IBM, Uber and VMware | Total workload cost (reports 65% cross-cloud and 67% cross-region reduction) | Cuts egress **after** placement is fixed. Complementary to egress-aware placement, not a substitute. | G1 |
| 5 | Zambianco et al., *Cost Minimization in Multi-cloud Systems with Runtime Microservice Re-orchestration*, 2024, ICIN [5] [peer-reviewed] | ILP (variable-cost bin packing) plus two-step heuristic; co-location constraints | Kubernetes scheduler plugin over multi-cloud virtual nodes | Deployment cost, disruption, QoS violations | Cost is **node price only**. Traffic between microservices is a co-location *constraint*, never a priced per-GB term. | G2 |
| 6 | Zambianco et al., *Disruption-aware Microservice Re-orchestration for Cost-efficient Multi-cloud Deployments*, 2025, IEEE TSC [6] [peer-reviewed] | Multi-objective ILP plus iterative heuristic | Kubernetes scheduler plugin, multi-cloud nodes | Cost, disruption, QoS | Same gap as row 5. Any comparison of heuristic to optimum is on a cost model without egress. | G2 |
| 7 | Ouledsidi Ali et al., *CaMP-INC*, 2022, GLOBECOM [7] [peer-reviewed] | ILP plus heuristic; places microservices together with their databases | Simulated cloud-edge continuum | Placement cost, failure resilience (reports 15.8% average cost reduction) | Communication cost uses a per-physical-link cost on an edge-cloud topology. No provider-specific egress tariff. | G2 |
| 8 | Kontos et al., *Cloud-Native Applications' Workload Placement over the Edge-Cloud Continuum*, 2023, CLOSER [8] [peer-reviewed] | MILP, greedy heuristic and multi-agent rollout | Simulated layered edge-cloud | Total cost split into placement and networking | Networking cost is a **per-node coefficient times ingress data**, not a provider-pair egress tariff. Simulated infrastructure, no published price lists. | G2 |
| 9 | Tekawade and Banerjee, *Cost and Reliability Aware Scheduling of Workflows Across Multiple Clouds with Security Constraints*, 2023, arXiv [9] [preprint] | List-scheduling heuristic on cost, time and reliability; cipher assignment for data-transfer edges | Real scientific workflows (Epigenomics, CyberShake) | Makespan, monetary cost, reliability | Does price inter-provider transfer, using **static rates hand-transcribed from provider websites** (median across locations). Workflow scheduling, not service placement. No ILP and no dated API price snapshot. | G3 |
| 11 | Sinha, *Optimization of Multi-Cloud Workload Placement for Performance and Cost Efficiency*, 2023, NCI MSc thesis [11] [thesis] | Stochastic hill climbing and simulated annealing over live pricing APIs; Docker profiling | AWS and Azure pricing APIs; Docker containers | Configuration cost, predicted CPU and memory | **Closest method.** Two providers only, no GCP. No exact baseline, so no optimality gap. No inter-component egress term found in the text. Not peer-reviewed. | G4 |
| 12 | Eliav et al., *Understanding Cross-Cloud Interconnects*, 2026, arXiv, accepted IEEE CLOUD 2026 [12] [preprint] | Measurements of AWS-GCP interconnects plus ToggleCCI, an online algorithm switching between VPN and Cross-Cloud Interconnect | Live AWS-GCP measurements | $/GB, total link cost | Optimises the **link type** for one provider pair with endpoints fixed. Not a placement decision. Useful as a source of realistic egress figures. | G1 |
| 13 | Liu et al., *SkyStore*, 2025, PVLDB [13] [peer-reviewed] | TTL-based object replication and eviction policy | AWS, Azure and GCP object stores | Storage, transfer and request cost (up to 6x saving) | **Objects only.** Compute placement is out of scope. | G1 |
| 14 | Shu et al., *Serverless Replication of Object Storage across Multi-Vendor Clouds and Regions*, 2026, EuroSys [14] [peer-reviewed] | Serverless replication with an SLO-compliant plan and decentralised scheduling | Three major clouds | Replication delay and cost | Replication mechanism for stored objects. No compute-placement decision. | G1 |
| 15 | Christofidi et al., *HuntMS*, 2026, arXiv [15] [preprint] | Geo-distribution framework for microservices, carbon plus cost objective | DeathStarBench on AWS in Spain and Sweden | Carbon, cost (37.4% carbon and 3.6% cost reduction) | Objective dominated by carbon. **Evaluation is AWS-only**, and the paper lists other providers' data-transfer policies as future work. | G3 |

*Row numbers follow the seed file. Rows 10 and 16 were dropped, so the table has 14 rows.*

---

## 4. Synthesised gap statement

Four consistent gaps emerge from the Limitation column. Two of them are narrower than the seed
draft claimed, because full-text checking showed that SkyPilot (row 3) and one workflow
scheduler (row 9) do price inter-cloud egress.

**G1: Egress-aware systems take the endpoints as given.** Systems that model egress accurately
(rows 1, 2, 4, 12, 13, 14) optimise the route, cache, replica or link for data whose source and
destination are fixed. None decides where the compute components live.

**G2: For component placement, communication is a constraint or a generic cost, not a priced
provider-pair term.** In the component-placement formulations (rows 5-8), inter-component
traffic is a co-location requirement, a per-node coefficient or a per-link cost. The two works
that do price provider egress on task-graph edges are SkyPilot (row 3) and, with static rates,
row 9. Both target one-shot batch DAGs or workflows. None treats an **always-on multi-component
service with a steady monthly traffic volume per edge** as an egress-coupled placement problem.

**G3: Pricing is static, single-provider or catalog-internal.** Where prices appear they are
hand-transcribed (row 9), limited to AWS (row 15), or drawn from two providers (row 11).
SkyPilot keeps a long-term price catalog but does not present a dated, reproducible snapshot.
No retrieved work builds a dated three-provider snapshot from the public AWS, GCP and Azure
price APIs.

**G4: No optimality gap is reported for the egress-coupled problem.** Heuristic placements are
compared to benchmark schedulers (row 11) or to optima of an egress-free cost model (rows 5-6),
not to an exact solution of the same egress-aware formulation.

**Contribution of this project:** an exactly-solved, egress-coupled placement formulation for
always-on multi-component applications over a dated three-provider price snapshot, with a
measured optimality gap for heuristics, and a quantification of how far egress-blind placement
is from optimal.

---

## 5. References

Web-only references cite the URL confirmed on 2026-09-21.

[1] P. Jain, S. Kumar, S. Wooders, S. G. Patil, J. E. Gonzalez, and I. Stoica, "Skyplane: Optimizing transfer cost and throughput using cloud-aware overlays," in *Proc. 20th USENIX Symp. Networked Systems Design and Implementation (NSDI)*, 2023, pp. 1375-1389. https://www.usenix.org/conference/nsdi23/presentation/jain

[2] S. Wooders, S. Liu, P. Jain, X. Mo, J. E. Gonzalez, V. Liu, and I. Stoica, "Cloudcast: High-throughput, cost-aware overlay multicast in the cloud," in *Proc. 21st USENIX NSDI*, 2024, pp. 281-296. https://www.usenix.org/conference/nsdi24/presentation/wooders

[3] Z. Yang, Z. Wu, M. Luo, W.-L. Chiang, R. Bhardwaj, W. Kwon, S. Zhuang, F. S. Luan, G. Mittal, S. Shenker, and I. Stoica, "SkyPilot: An intercloud broker for sky computing," in *Proc. 20th USENIX NSDI*, 2023, pp. 437-455. https://www.usenix.org/conference/nsdi23/presentation/yang-zongheng

[4] H. Park, Z. Qiu, G. R. Ganger, and G. Amvrosiadis, "Reducing cross-cloud/region costs with the auto-configuring MACARON cache," in *Proc. ACM SIGOPS 30th Symp. Operating Systems Principles (SOSP)*, 2024, pp. 347-368. doi:10.1145/3694715.3695972. PDF: https://www.pdl.cmu.edu/PDL-FTP/CloudComputing/sosp24-final499.pdf

[5] M. Zambianco, S. Cretti, and D. Siracusa, "Cost minimization in multi-cloud systems with runtime microservice re-orchestration," in *Proc. 27th Conf. Innovation in Clouds, Internet and Networks (ICIN)*, 2024, pp. 65-72. https://arxiv.org/abs/2401.01408

[6] M. Zambianco, S. Cretti, and D. Siracusa, "Disruption-aware microservice re-orchestration for cost-efficient multi-cloud deployments," *IEEE Trans. Services Computing*, 2025, doi:10.1109/TSC.2025.3604373 (as listed on arXiv). https://arxiv.org/abs/2501.16143

[7] S. Ouledsidi Ali, H. Elbiaze, R. Glitho, and W. Ajib, "CaMP-INC: Components-aware microservices placement for in-network computing cloud-edge continuum," in *Proc. IEEE GLOBECOM*, 2022, pp. 2116-2121. https://arxiv.org/abs/2307.08898

[8] G. Kontos, P. Soumplis, P. Kokkinos, and E. Varvarigos, "Cloud-native applications' workload placement over the edge-cloud continuum," in *Proc. 13th Int. Conf. Cloud Computing and Services Science (CLOSER)*, 2023, pp. 57-66. https://www.scitepress.org/Papers/2023/118501/118501.pdf

[9] A. Tekawade and S. Banerjee, "Cost and reliability aware scheduling of workflows across multiple clouds with security constraints," arXiv:2304.00313, 2023 (preprint). https://arxiv.org/abs/2304.00313

[11] R. Sinha, "Optimization of multi-cloud workload placement for performance and cost efficiency," M.Sc. thesis, National College of Ireland, Dublin, 2023. https://norma.ncirl.ie/7416/

[12] E. Eliav, I. Keslassy, D. Breitgand, D. H. Lorenz, and A. Weit, "Understanding cross-cloud interconnects: Hands-on measurements and cost optimization," arXiv:2606.01440, 2026 (preprint; accepted at IEEE CLOUD 2026). https://arxiv.org/abs/2606.01440

[13] S. Liu, X. Mo, M. Hershcovitch, H. Zhang, A. Cheng, G. Girmonsky, G. Vernik, M. Factor, T. Bang, S. Ponnapalli, N. Crooks, J. E. Gonzalez, D. Harnik, and I. Stoica, "SkyStore: Cost-optimized object storage across regions and clouds," *Proc. VLDB Endowment*, vol. 18, no. 7, pp. 2084-2096, 2025. https://arxiv.org/abs/2502.20818

[14] J. Shu, X. Huang, G. Huang, H. Mei, X. Liu, and X. Jin, "Serverless replication of object storage across multi-vendor clouds and regions," in *Proc. 21st European Conf. Computer Systems (EuroSys)*, 2026, pp. 1780-1796. doi:10.1145/3767295.3769367. https://doi.org/10.1145/3767295.3769367

[15] G. Christofidi, F. Alvarez-Terribas, I. Roumpos, N. Kourtellis, J. Omana Iglesias, and T. D. Doudali, "HuntMS: A framework for microservice geo-distribution for carbon and cost reduction," arXiv:2603.10768, 2026 (preprint). https://arxiv.org/abs/2603.10768
