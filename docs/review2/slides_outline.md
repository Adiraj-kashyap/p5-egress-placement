# Review-2 slides — outline (9 slides)

For H-08-style slide building. Each slide names **the exact file to show**. Nothing here is a new
claim: every number is already in a generated table or figure.

---

### Slide 1 — Problem and hypotheses (recap, 1 minute)

- Placing the components of one application across AWS / Azure / GCP, where moving data between
  components is charged at asymmetric per-GB rates that couple the decisions.
- H1 ≥ 20 % cheaper than an egress-blind baseline · H2 heuristic within 5 % and ≥ 10× faster ·
  H3 a traffic threshold above which the optimum collapses to one provider.
- **Thresholds were frozen before any run and were never changed.**
- Show: `docs/review1/problem_statement.md`, `docs/review1/hypotheses.md`.

### Slide 2 — What was built (architecture / repo map)

- `pricing/` → `cost_model/` → `topologies/` + `testbed/` → `placement/` → `experiments/` →
  `analysis/` → `docs/report/`.
- 407 tests, green CI on every push, 68+ commits, every experiment row stamped with its commit,
  snapshot date and machine.
- Show: `docs/review2/o1_o2_evidence.md` (status table) and the GitHub Actions run
  (`evidence/screenshots/M19_ci_green.png`).

### Slide 3 — O1: the unified cost model

- 24 locations × 3 providers; 96 compute rows, 576 directed egress cells, 24 internet, 24 storage.
- 10/10 validation checks pass; **0 of 168 same-provider cells need a fallback rate**;
  229 of 276 location pairs are priced asymmetrically — the coupling is real.
- Show: `docs/report/tables/cost_model.md` and `cost_model/2026-09-21/validation.md`.

### Slide 4 — O2: the formulation

- Placement as an ILP with an explicit per-edge egress term; tight formulation ⊂ McCormick.
- T1–T3 proven optimal in < 0.2 s; tight has 76 / 175 / 371 constraints vs 436 / 1,015 / 2,171.
- Equivalence to the real cost function brute-forced on 20 seeded instances.
- Show: `docs/report/formulation.md`, `docs/report/tables/exact.md`.

### Slide 5 — **Headline: R2-1, baseline and method on the same axes**

- Total monthly cost vs traffic scale for ILP, SA, B1, B2-best on T1–T3, with 95 % CI bands over
  R = 30 draws.
- One sentence: *the distance between the B1 line and the ILP line is the price of ignoring egress.*
- Show: `figures/R2-1_cost_vs_scale.png`.

### Slide 6 — Where the money goes, and the H1 verdict

- F1 breakdown: compute is **identical** for B1 and the ILP; the whole difference is data movement.
- Reduction 3.29 % [3.04, 3.54] / **22.55 % [20.52, 24.59]** / 1.76 % [1.65, 1.87].
- **H1: REFUTED overall, SUPPORTED on T2** — say the margin is half a point and that B1-alt gives
  0 % everywhere.
- Show: `figures/F1_cost_breakdown.png`, `docs/report/tables/h1_replicated.md`,
  `docs/report/verdicts.md`.

### Slide 7 — Ablation: which component causes the gain

- F6: storage 0.00 everywhere; internet **negative** on T1 and T3; **egress coupling is the
  largest step at 6 of 6 points**.
- Removing per-edge egress from the ILP costs 23.30 % on T1 — worse than the baseline itself.
- Show: `figures/F6_gain_decomposition.png`, `docs/report/tables/ablation.md`.

### Slide 8 — Sweep, crossover and price sensitivity

- F2/F3: the ILP uses **one provider at all 810 points, sd 0.0** → **H3 REFUTED**, and the reason
  is structural (`azure:eastus` minimises every component's own cost), not a grid artefact.
- F7: a 25 % cut in egress prices takes T2 from 24.75 % to 19.83 % — below the threshold.
  The number of candidate locations changes nothing (≤ 0.10 pp).
- Show: `figures/F2_egress_penalty.png`, `figures/F3_providers_used.png`,
  `figures/F7_sensitivity.png`.

### Slide 9 — Threats to validity, and the plan for Review 3

- Four categories; lead with the two that matter: **B1's tie-break** (opposite tie-break → 0 %
  saving) and **no latency/SLO constraints** (colocation may be operationally impossible).
- H2 refuted honestly: SA is accurate (0.10 % gap) but **not faster** than CBC at these sizes
  (0.63×).
- Review 3: live Streamlit demo (M20), 6–8 page paper (M21), demo video (M22).
- Show: `docs/review2/threats_to_validity.md`, `docs/review_progress.md`.

---

**If asked "what is your actual contribution?"** — a dated, reproducible three-provider price
model with directional per-edge egress, an exact formulation that is proven equivalent to it, and
a measured statement of when egress-aware placement is worth doing: only when
inter-component traffic is large relative to the compute bill, which was true for exactly one of
the three studied applications.
