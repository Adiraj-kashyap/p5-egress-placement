# Review 1 — Slides outline (9 slides)

Order: problem → gap table → hypothesis → cost model → testbed → baselines → plan.
Every number below comes from a committed file named on the same slide. All screenshots named
below exist (✅, see `evidence_index.md`); the testbed rubric line says "slides alone = 0", so show them.

---

### 1. Egress-aware multi-cloud placement (title)
- P5: cost-optimal placement of multi-component workloads across AWS, Azure and GCP.
- Question: how much does ignoring inter-component transfer cost, and when does it change the answer?
- Review 1 covers: literature, hypotheses, cost model, testbed, baselines.
- **Show:** `docs/review1/problem_statement.md` (title block only)

### 2. The problem: transfer cost is defined over pairs
- Compute and storage prices depend on one location. Egress depends on the sender *and* the receiver.
- Choosing each component's cheapest location independently ignores the pairwise term.
- So placement is a joint optimisation problem, not n independent choices.
- **Show:** `docs/review1/problem_statement.md` §Problem and the cost formula in `docs/methodology/project_brief.md §6`

### 3. Objectives and scope
- O1 cost model · O2 formulation · O3 exact + heuristic with a measured gap · O4 egress-blind penalty.
- 3 providers, Linux on-demand, 12 core / 24 ext locations, one dated snapshot (2026-09-21).
- Decision = location per component; shape fixed in advance; T1–T3 plus synthetic graphs.
- **Show:** `docs/review1/problem_statement.md` §Objectives and §Scope tables

### 4. Literature and gap
- 14 papers (2021 or later), each URL fetched and title and year confirmed.
- Closest work: SkyPilot (NSDI 2023) prices egress for one-shot batch task DAGs.
- Our gap is narrower: always-on services, monthly per-edge traffic, dated 3-provider API snapshot, measured optimality gap.
- **Show:** `docs/review1/gap_table.md` (table) and `docs/review1/closest_prior_work.md`

### 5. Hypotheses (frozen before any result)
- H1: ILP reduces total monthly cost by ≥ 20% vs B1 on T1–T3 (≥ 500 GB/month traffic).
- H2: simulated annealing within 5% of the CBC optimum, ≥ 10× faster, at ≥ 15 components and ≥ 20 locations.
- H3: a traffic-scale crossover exists between single-provider optimum and multi-provider B1 (swept 10⁻² to 10²).
- **Show:** `docs/review1/hypotheses.md`

### 6. Unified cost model from public price lists
- Sources: Azure Retail Prices API, AWS Price List bulk files (per-region), GCP public pricing pages (no API key; waiver D-026).
- Result: 96 compute, 576 directed egress, 24 internet and 24 storage rows over 24 locations. 0 of 168 cells use a fallback.
- Validation: 10 of 10 checks pass (V1–V10).
- **Show:** ✅ `evidence/screenshots/M05_cost_model.png` (fallback: `cost_model/2026-09-21/validation.md`); pull screenshots ✅ `M02_azure_pull.png`, ✅ `M03_aws_pull.png`, ✅ `M04_gcp_pull.png`

### 7. Testbed: measured traffic for T1
- Local kind cluster with web → api → cache/db. Per-edge socket byte counters. Locust load, 3 × 10-min runs.
- 0 failures; max coefficient of variation 0.87% across edges.
- T1 at 50 req/s: 1,265.50 GB/month inter-component and 649.94 GB/month to the internet.
- **Show:** ✅ `evidence/screenshots/M07_kubectl.png`, ✅ `evidence/screenshots/M07_load_test.png`; data `testbed/measurements/summary.csv`

### 8. Baselines B1 and B2 (USD/month)
- B1 vs B2-best: T1 497.58 vs 481.18 · T2 1,303.65 vs 1,028.79 · T3 1,822.60 vs 1,789.88.
- B1's extra cost on T1 and T2 is egress (14.44 and 274.83) from splitting across two providers.
- aws:us-east-1 and azure:eastus tie on price per vCPU; the opposite tie-break gives B1 = B2-azure. H1 will be tested against both variants.
- **Show:** `docs/review1/baseline_results.md` (Summary table) and ✅ `evidence/screenshots/M08_baselines.png`

### 9. Plan for Review 2
- M10 exact ILP (PuLP + CBC); objective must equal the shared cost evaluator.
- M11–M12 egress-aware greedy and simulated annealing; M13–M14 generator and optimality-gap scaling.
- M15–M16 traffic sweep, penalty, crossover, and SUPPORTED / REFUTED / INCONCLUSIVE verdicts for H1–H3.
- **Show:** module table in `state/STATE.md` (M10–M16 rows)
